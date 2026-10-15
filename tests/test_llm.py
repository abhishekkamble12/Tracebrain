"""Offline tests for provider fallback and caching in tracebrain.llm (no API keys, no network)."""

from types import SimpleNamespace

import httpx
import pytest
from openai import BadRequestError, RateLimitError

from tracebrain import config, llm


def _resp(content="ok", tool_calls=None):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")], usage=None)


def _err(cls, status, headers=None):
    response = httpx.Response(status, headers=headers or {}, request=httpx.Request("POST", "http://test"))
    return cls("err", response=response, body=None)


class FakeClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **payload):
        self.calls += 1
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


@pytest.fixture
def two_providers(monkeypatch, tmp_path):
    providers = {
        "a": config.Provider("a", "http://a", "key-a", "model-a", "fast-a"),
        "b": config.Provider("b", "http://b", "key-b", "model-b", "fast-b"),
    }
    monkeypatch.setattr(config, "PROVIDERS", providers)
    monkeypatch.setattr(config, "LLM_PROVIDERS", ["a", "b"])
    monkeypatch.setattr(config, "LLM_MAX_WAIT_S", 20.0)
    monkeypatch.setattr(config, "LLM_CACHE", True)
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    clients: dict[str, FakeClient] = {}
    monkeypatch.setattr(llm, "_client", lambda name: clients[name])
    return clients


def test_quota_exhausted_falls_back_to_next_provider(two_providers):
    two_providers["a"] = FakeClient([_err(RateLimitError, 429, {"retry-after": "3600"})])
    two_providers["b"] = FakeClient([_resp("from b")])
    r = llm.chat([{"role": "user", "content": "hi"}])
    assert (r.provider, r.model, r.content) == ("b", "model-b", "from b")


def test_short_rate_limit_retries_same_provider(two_providers):
    two_providers["a"] = FakeClient([_err(RateLimitError, 429, {"retry-after": "2"}), _resp("from a")])
    two_providers["b"] = FakeClient([])
    r = llm.chat([{"role": "user", "content": "hi"}])
    assert r.provider == "a" and two_providers["a"].calls == 2


def test_bad_request_moves_on(two_providers):
    two_providers["a"] = FakeClient([_err(BadRequestError, 400)])
    two_providers["b"] = FakeClient([_resp("from b")])
    assert llm.chat([{"role": "user", "content": "x"}], tier="fast").model == "fast-b"


def test_all_exhausted_raises(two_providers):
    two_providers["a"] = FakeClient([_err(RateLimitError, 429, {"retry-after": "999"})])
    two_providers["b"] = FakeClient([_err(RateLimitError, 429, {"retry-after": "999"})])
    with pytest.raises(llm.AllProvidersExhausted):
        llm.chat([{"role": "user", "content": "hi"}])


def test_cache_hit_costs_no_call(two_providers):
    two_providers["a"] = FakeClient([_resp("first")])
    two_providers["b"] = FakeClient([])
    msgs = [{"role": "user", "content": "same"}]
    assert llm.chat(msgs).cached is False
    again = llm.chat(msgs)
    assert again.cached is True and again.content == "first" and two_providers["a"].calls == 1


def test_tool_calls_parsed_and_bad_json_tolerated(two_providers):
    fn = lambda name, args: SimpleNamespace(id=f"c-{name}", function=SimpleNamespace(name=name, arguments=args))
    two_providers["a"] = FakeClient([_resp(None, [fn("blast_radius", '{"service": "redis", "t": 50}'),
                                                  fn("owners_of", "{not json")])])
    two_providers["b"] = FakeClient([])
    r = llm.chat([{"role": "user", "content": "tools"}], tools=[{"type": "function", "function": {"name": "x"}}])
    assert r.tool_calls[0].arguments == {"service": "redis", "t": 50}
    assert "_unparseable" in r.tool_calls[1].arguments
    assert r.assistant_message()["tool_calls"][0]["function"]["name"] == "blast_radius"
