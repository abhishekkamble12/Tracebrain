"""Agent loop with a scripted fake LLM against the real MCP server and graph (no API key needed)."""

import uuid

import anyio
import pytest
from mcp import Client

from tracebrain import llm, schema
from tracebrain.agents import loop
from tracebrain.connectors.synthetic import SyntheticConnector
from tracebrain.ingest import ingest
from tracebrain.tools import mcp_server
from tracebrain.tools.impl import ToolCtx

FINAL = {"type": "function", "function": {"name": "submit", "description": "done",
                                          "parameters": {"type": "object", "properties": {"deploy": {"type": "string"}}}}}


def reply(*calls, content=None):
    tcs = [llm.ToolCall(f"c{i}", n, a, str(a)) for i, (n, a) in enumerate(calls)]
    return llm.ChatResult(content, tcs, "tool_calls" if tcs else "stop", {"prompt_tokens": 10, "completion_tokens": 5},
                          "fake", "scripted")


class Script:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.seen_tools: list[list[str]] = []
        self.seen_messages: list[list[dict]] = []

    def __call__(self, messages, tools):
        self.seen_tools.append([t["function"]["name"] for t in tools])
        self.seen_messages.append(list(messages))
        return self.replies.pop(0)


@pytest.fixture(scope="module")
def seeded(falkor):
    tenant = f"test_{uuid.uuid4().hex[:8]}"
    schema.apply(tenant)
    conn = SyntheticConnector("payments")
    ingest(tenant, conn)
    iid, truth = next((k, v) for k, v in conn.world.truth.items() if v["type"] == "timeout")
    yield ToolCtx(tenant, truth["ts"]), iid, truth
    schema.drop(tenant)


def run(ctx, script, allowed, **kw):
    async def go():
        async with Client(mcp_server.server) as client:
            return await loop.run_agent("investigator", "sys", "go", ctx, allowed, client, chat_fn=script, **kw)
    return anyio.run(go)


def test_tool_calls_use_hidden_context_and_record_edges(seeded):
    ctx, iid, truth = seeded
    script = Script(reply(("get_incident", {"incident_id": iid})),
                    reply(("suspects", {"service": truth["service"]})),
                    reply(("submit", {"deploy": truth["culprit_deploy"]})))
    r = run(ctx, script, {"get_incident", "suspects"}, final_tool=FINAL)
    assert r.stopped == "final" and r.final == {"deploy": truth["culprit_deploy"]}
    assert [s.tool for s in r.steps] == ["get_incident", "suspects"]
    assert r.steps[0].result["service"] == truth["service"]          # tenant + time came from meta
    assert r.steps[1].edge_ids and r.edge_ids_seen >= set(r.steps[1].edge_ids)
    assert r.usage == {"prompt_tokens": 30, "completion_tokens": 15}
    # The LLM only ever saw allowlisted tools plus the final tool.
    assert all(set(names) == {"get_incident", "suspects", "submit"} for names in script.seen_tools)


def test_disallowed_and_bad_json_calls_are_errors_not_crashes(seeded):
    ctx, _, truth = seeded
    script = Script(reply(("centrality", {}), ("suspects", {"_unparseable": "{oops"})),
                    reply(("submit", {"deploy": "x"})))
    r = run(ctx, script, {"suspects"}, final_tool=FINAL)
    assert [s.error for s in r.steps] == ["not_allowed", "bad_json"]
    assert r.stopped == "final"


def test_validate_final_rejects_then_accepts(seeded):
    ctx, _, truth = seeded
    script = Script(reply(("submit", {"deploy": "dep:9999"})), reply(("submit", {"deploy": truth["culprit_deploy"]})))
    check = lambda a, run: None if a["deploy"] == truth["culprit_deploy"] else "deploy not among retrieved suspects"
    r = run(ctx, script, {"suspects"}, final_tool=FINAL, validate_final=check)
    assert r.final == {"deploy": truth["culprit_deploy"]} and r.turns == 2
    rejected = script.seen_messages[1][-1]
    assert rejected["role"] == "tool" and "not among retrieved suspects" in rejected["content"]


def test_nudge_then_stop_when_no_final(seeded):
    ctx, _, _ = seeded
    r = run(ctx, Script(reply(content="I think it's redis"), reply(content="still redis")), {"suspects"}, final_tool=FINAL)
    assert r.stopped == "no_tool_call" and r.turns == 2


def test_max_turns(seeded):
    ctx, _, truth = seeded
    script = Script(*[reply(("suspects", {"service": truth["service"]})) for _ in range(3)])
    assert run(ctx, script, {"suspects"}, max_turns=3).stopped == "max_turns"


def test_clean_schema_flattens_optional_and_drops_titles():
    s = {"title": "X", "type": "object", "properties": {
        "w": {"anyOf": [{"type": "number"}, {"type": "null"}], "default": None, "title": "W"}}}
    assert loop.clean_schema(s) == {"type": "object", "properties": {"w": {"type": "number"}}}
