"""Generic agent loop: LLM (llm.chat) <-> MCP tools, with per-agent allowlists and hidden context.

- Tools come from the MCP server's list_tools(), filtered to the agent's allowlist and converted to
  the OpenAI function schema. Tenant / incident time travel as MCP request metadata, never as
  LLM-visible arguments.
- An optional *final tool* (local, not on the MCP server) ends the run; its arguments are the
  agent's structured output. `validate_final` can reject them with a message the agent must fix
  (this is where the evidence gate plugs in).
- Every tool call is recorded as a Step with timing and the edge_ids it returned.
"""

import json
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import anyio
from mcp import Client

from tracebrain import llm
from tracebrain.tools import mcp_server
from tracebrain.tools.impl import ToolCtx

ChatFn = Callable[..., llm.ChatResult]
StepHook = Callable[["Step"], Awaitable[None] | None]


@dataclass
class Step:
    n: int
    agent: str
    tool: str
    args: dict[str, Any]
    result: Any
    ms: int
    edge_ids: list[int] = field(default_factory=list)
    error: str | None = None


@dataclass
class AgentRun:
    agent: str
    final: dict | None = None
    text: str | None = None
    steps: list[Step] = field(default_factory=list)
    turns: int = 0
    usage: dict[str, int] = field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0})
    models: set[str] = field(default_factory=set)
    stopped: str = ""   # final | no_tool_call | max_turns

    @property
    def edge_ids_seen(self) -> set[int]:
        return {e for s in self.steps for e in s.edge_ids}


def meta_for(ctx: ToolCtx) -> dict:
    return {mcp_server.META_TENANT: ctx.tenant, mcp_server.META_T: ctx.t,
            mcp_server.META_INVESTIGATION: ctx.investigation_id, mcp_server.META_MEMORY: ctx.memory_enabled}


def clean_schema(schema: Any) -> Any:
    """Make MCP/pydantic JSON schemas portable across providers: drop titles, and turn
    `anyOf: [X, null]` (optional args) into plain X."""
    if isinstance(schema, list):
        return [clean_schema(s) for s in schema]
    if not isinstance(schema, dict):
        return schema
    out = {k: clean_schema(v) for k, v in schema.items() if k != "title"}
    any_of = out.get("anyOf")
    if isinstance(any_of, list):
        non_null = [s for s in any_of if s.get("type") != "null"]
        if len(non_null) == 1:
            out.pop("anyOf")
            out = {**non_null[0], **out}
    if out.get("default", 0) is None:
        out.pop("default")
    return out


def to_openai_tool(name: str, description: str, parameters: dict) -> dict:
    return {"type": "function", "function": {"name": name, "description": description or "",
                                             "parameters": clean_schema(parameters)}}


def collect_edge_ids(obj: Any) -> list[int]:
    found: set[int] = set()

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "edge_ids" and isinstance(v, list):
                    found.update(x for x in v if isinstance(x, int))
                elif k == "edge_id" and isinstance(v, int):
                    found.add(v)
                else:
                    walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(obj)
    return sorted(found)


def _decode(result) -> Any:
    text = "".join(getattr(c, "text", "") for c in result.content)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"text": text}


async def run_agent(
    name: str,
    system: str,
    user: str,
    ctx: ToolCtx,
    allowed_tools: set[str],
    client: Client,
    final_tool: dict | None = None,
    validate_final: Callable[[dict], str | None] | None = None,
    max_turns: int = 12,
    max_final_retries: int = 2,
    chat_fn: ChatFn = llm.chat,
    on_step: StepHook | None = None,
) -> AgentRun:
    run = AgentRun(agent=name)
    listed = (await client.list_tools()).tools
    tools = [to_openai_tool(t.name, t.description, t.input_schema) for t in listed if t.name in allowed_tools]
    final_name = final_tool["function"]["name"] if final_tool else None
    if final_tool:
        tools.append(final_tool)

    messages: list[dict] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    final_rejections = 0
    nudged = False

    while run.turns < max_turns:
        run.turns += 1
        reply = await anyio.to_thread.run_sync(lambda: chat_fn(messages, tools))
        run.models.add(f"{reply.provider}/{reply.model}")
        for k in run.usage:
            run.usage[k] += reply.usage.get(k, 0)
        messages.append(reply.assistant_message())

        if not reply.tool_calls:
            if final_name and not nudged:
                nudged = True
                messages.append({"role": "user", "content": f"Call `{final_name}` to submit your result."})
                continue
            run.text, run.stopped = reply.content, "no_tool_call"
            return run

        for call in reply.tool_calls:
            if call.name == final_name:
                problem = "unparseable arguments" if "_unparseable" in call.arguments else (
                    validate_final(call.arguments) if validate_final else None)
                if problem and final_rejections < max_final_retries:
                    final_rejections += 1
                    messages.append(llm.tool_result_message(call, {"rejected": problem,
                                                                   "action": "fix the problems and call again"}))
                    continue
                run.final, run.text, run.stopped = call.arguments, reply.content, "final"
                if problem:
                    run.final = {**call.arguments, "_unresolved_problems": problem}
                return run

            start = time.perf_counter()
            error = None
            if call.name not in allowed_tools:
                result: Any = {"error": f"tool '{call.name}' is not available to the {name} agent"}
                error = "not_allowed"
            elif "_unparseable" in call.arguments:
                result = {"error": "arguments were not valid JSON; retry with a JSON object"}
                error = "bad_json"
            else:
                result = _decode(await client.call_tool(call.name, call.arguments, meta=meta_for(ctx)))
                if isinstance(result, dict) and "error" in result:
                    error = "tool_error"
            step = Step(len(run.steps) + 1, name, call.name, call.arguments, result,
                        int((time.perf_counter() - start) * 1000), collect_edge_ids(result), error)
            run.steps.append(step)
            if on_step:
                maybe = on_step(step)
                if maybe is not None:
                    await maybe
            messages.append(llm.tool_result_message(call, result))

    run.stopped = "max_turns"
    return run
