"""LLM calls over OpenAI-compatible endpoints (Groq, Cerebras, Gemini), all free tiers.

- Tries providers in `config.LLM_PROVIDERS` order; skips any without an API key.
- Short 429 waits are honored; a long wait (daily quota gone) falls through to the next provider.
- Every response is cached on disk, so eval reruns cost zero tokens.
- Each result records provider + model + usage, so reported numbers say what produced them.

The agent loop only talks to `chat()`; nothing else imports a provider SDK.
"""

import hashlib
import json
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError

from tracebrain import config

CACHE_DIR = Path(__file__).resolve().parent.parent / "eval" / ".cache" / "llm"
RETRIES_PER_PROVIDER = 4

Tier = Literal["agent", "fast"]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str


@dataclass
class ChatResult:
    content: str | None
    tool_calls: list[ToolCall]
    finish_reason: str
    usage: dict[str, int] = field(default_factory=dict)
    provider: str = ""
    model: str = ""
    cached: bool = False
    ms: int = 0

    def assistant_message(self) -> dict:
        """The message to append to history so the next turn sees this reply."""
        msg: dict[str, Any] = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            msg["tool_calls"] = [
                {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.raw_arguments}}
                for c in self.tool_calls
            ]
        return msg


class AllProvidersExhausted(RuntimeError):
    pass


def available_providers() -> list[config.Provider]:
    providers = [config.PROVIDERS[n] for n in config.LLM_PROVIDERS if n in config.PROVIDERS]
    ready = [p for p in providers if p.api_key]
    if not ready:
        raise RuntimeError("No LLM API key set. Add GROQ_API_KEY, CEREBRAS_API_KEY or GEMINI_API_KEY to .env")
    return ready


@lru_cache(maxsize=None)
def _client(name: str) -> OpenAI:
    p = config.PROVIDERS[name]
    return OpenAI(base_url=p.base_url, api_key=p.api_key, max_retries=0)  # we handle retries


def tool_result_message(call: ToolCall, result: Any, limit: int = 4000) -> dict:
    """Tool output goes back as a string; truncate so context (and token quotas) stay small."""
    text = result if isinstance(result, str) else json.dumps(result, default=str)
    if len(text) > limit:
        text = text[:limit] + f"... [truncated {len(text) - limit} chars]"
    return {"role": "tool", "tool_call_id": call.id, "content": text}


def _parse(resp, provider: str, model: str, ms: int) -> ChatResult:
    choice = resp.choices[0]
    calls = []
    for tc in choice.message.tool_calls or []:
        raw = tc.function.arguments or "{}"
        try:
            args = json.loads(raw)
        except json.JSONDecodeError:
            args = {"_unparseable": raw}  # surfaced to the agent as a tool error, not a crash
        calls.append(ToolCall(tc.id, tc.function.name, args, raw))
    usage = {}
    if resp.usage:
        usage = {"prompt_tokens": resp.usage.prompt_tokens, "completion_tokens": resp.usage.completion_tokens,
                 "total_tokens": resp.usage.total_tokens}
    return ChatResult(choice.message.content, calls, choice.finish_reason or "", usage, provider, model, False, ms)


def _cache_path(request: dict) -> Path:
    key = hashlib.sha256(json.dumps(request, sort_keys=True, default=str).encode()).hexdigest()
    return CACHE_DIR / f"{key}.json"


def _save(path: Path, r: ChatResult) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data = {"content": r.content, "finish_reason": r.finish_reason, "usage": r.usage, "provider": r.provider,
            "model": r.model, "tool_calls": [{"id": c.id, "name": c.name, "arguments": c.arguments,
                                              "raw": c.raw_arguments} for c in r.tool_calls]}
    path.write_text(json.dumps(data), encoding="utf-8")


def _load(path: Path) -> ChatResult:
    d = json.loads(path.read_text(encoding="utf-8"))
    calls = [ToolCall(c["id"], c["name"], c["arguments"], c["raw"]) for c in d["tool_calls"]]
    return ChatResult(d["content"], calls, d["finish_reason"], d["usage"], d["provider"], d["model"], cached=True)


def _retry_after(e: APIStatusError, attempt: int) -> float:
    try:
        return float(e.response.headers.get("retry-after", 2 ** attempt))
    except (TypeError, ValueError):
        return float(2 ** attempt)


def chat(messages: list[dict], tools: list[dict] | None = None, tier: Tier = "agent",
         tool_choice: str | dict = "auto", temperature: float = 0.0, max_tokens: int = 4096) -> ChatResult:
    """One chat-completion turn. `tools` use the OpenAI function schema:
    {"type": "function", "function": {"name", "description", "parameters": <JSON schema>}}."""
    # Cache on the logical request (not the provider), so a cached answer survives a fallback switch.
    request = {"tier": tier, "messages": messages, "tools": tools, "tool_choice": tool_choice if tools else None,
               "temperature": temperature}
    path = _cache_path(request)
    if config.LLM_CACHE and path.exists():
        return _load(path)

    errors: list[str] = []
    for p in available_providers():
        model = p.agent_model if tier == "agent" else p.fast_model
        payload: dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature,
                                   "max_tokens": max_tokens}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice

        for attempt in range(RETRIES_PER_PROVIDER):
            start = time.perf_counter()
            try:
                resp = _client(p.name).chat.completions.create(**payload)
            except RateLimitError as e:
                wait = _retry_after(e, attempt)
                if wait > config.LLM_MAX_WAIT_S:
                    errors.append(f"{p.name}: quota (retry-after {wait:.0f}s)")
                    break  # quota gone for now: next provider
                time.sleep(wait)
                continue
            except APIConnectionError as e:
                errors.append(f"{p.name}: connection {e}")
                time.sleep(2 ** attempt)
                continue
            except APIStatusError as e:
                if e.status_code >= 500:
                    errors.append(f"{p.name}: {e.status_code}")
                    time.sleep(2 ** attempt)
                    continue
                errors.append(f"{p.name}: {e.status_code} {e.message}")
                break  # 4xx other than 429 (bad model name, unsupported param): next provider
            result = _parse(resp, p.name, model, int((time.perf_counter() - start) * 1000))
            if config.LLM_CACHE:
                _save(path, result)
            return result
        else:
            errors.append(f"{p.name}: gave up after {RETRIES_PER_PROVIDER} attempts")

    raise AllProvidersExhausted("; ".join(errors))
