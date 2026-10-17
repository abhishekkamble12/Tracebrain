"""End-to-end investigation, review and memory, driven by a scripted policy LLM that reads the REAL
tool results from the conversation (no API key). Everything except the model is the real system:
MCP server, graph, blackboard, evidence gate, state machine, curator."""

import json
import uuid

import anyio
import pytest

from tracebrain import db, llm, schema
from tracebrain.agents import curator
from tracebrain.connectors.synthetic import SyntheticConnector
from tracebrain.ingest import ingest
from tracebrain.memory import episodic, procedural, semantic
from tracebrain import orchestrator
from tracebrain.tools import impl
from tracebrain.tools.impl import ToolCtx


def call(name, args, i=0):
    return llm.ToolCall(f"{name}-{i}", name, args, json.dumps(args))


def result(name, args):
    return llm.ChatResult(None, [call(name, args)], "tool_calls", {"prompt_tokens": 100, "completion_tokens": 20},
                          "fake", "policy")


def tool_results(messages):
    return [json.loads(m["content"].split("... [truncated")[0]) if m["content"].startswith("{") else m["content"]
            for m in messages if m["role"] == "tool"]


class Policy:
    """Plays both agents. `pick` chooses which suspect to blame: 'top' (rank 1) or a deploy id.
    `fake_first` makes the first submission cite a fabricated edge id (gate test)."""

    def __init__(self, service, pick="top", fake_first=False, abstain_if_empty=True):
        self.service, self.pick, self.fake_first, self.abstain_if_empty = service, pick, fake_first, abstain_if_empty
        self.submissions = 0

    def __call__(self, messages, tools):
        system = messages[0]["content"]
        done = [m for m in messages if m["role"] == "assistant"]
        res = tool_results(messages)
        if system.startswith("You are the TRIAGE"):
            plan = [("blast_radius", {"service": self.service}), ("owners_of", {"services": [self.service]}),
                    ("write_finding", {"kind": "blast_radius", "payload": res[0] if res else {}}),
                    ("write_finding", {"kind": "owners", "payload": res[1] if len(res) > 1 else {}}),
                    ("finish_triage", {"summary": "triage done"})]
            return result(*plan[min(len(done), len(plan) - 1)])

        plan = [("read_findings", {}), ("recall_lessons", {}), ("suspects", {"service": self.service})]
        if len(done) < len(plan):
            return result(*plan[len(done)])
        sus = next(r for r in reversed(res) if isinstance(r, dict) and "suspects" in r)["suspects"]
        if not sus:
            return result("submit_hypotheses", {"hypotheses": [], "abstain": True, "abstain_reason": "no deploys",
                                                "actions": [{"kind": "page", "target": "Checkout"}]})
        target = sus[0] if self.pick == "top" else next(s for s in sus if s["deploy"] == self.pick)
        deployed_to = target["edge_ids"][-1]
        claims = [{"text": f"{target['deploy']} was deployed to {target['service']}", "edge_ids": [deployed_to]}]
        if target["edge_ids"][:-1]:
            claims.append({"text": f"{self.service} depends on {target['service']}", "edge_ids": target["edge_ids"][:-1]})
        if self.fake_first and self.submissions == 0:
            claims.append({"text": f"{target['service']} was overloaded", "edge_ids": [987654]})
        self.submissions += 1
        return result("submit_hypotheses", {
            "hypotheses": [{"deploy_id": target["deploy"], "likely_cause": "connection pool exhaustion",
                            "summary": "recent change on the dependency path", "claims": claims}],
            "actions": [{"kind": "rollback_proposal", "target": target["deploy"], "reason": "top suspect"}],
            "abstain": False})


@pytest.fixture
def world(falkor):
    tenant = f"test_{uuid.uuid4().hex[:8]}"
    schema.apply(tenant)
    conn = SyntheticConnector("payments")
    ingest(tenant, conn)
    impl._pagerank.cache_clear()
    yield tenant, conn.world
    schema.drop(tenant)


def incidents_of(world, kind):
    return [(k, v) for k, v in sorted(world.truth.items(), key=lambda kv: kv[1]["ts"]) if v["type"] == kind]


def investigate(tenant, iid, policy, memory=True, events=None):
    return anyio.run(lambda: orchestrator.investigate(
        tenant, iid, memory_enabled=memory, chat_fn=policy,
        on_event=(lambda k, d: events.append((k, d))) if events is not None else None))


def test_full_pipeline_persists_everything(world):
    tenant, w = world
    iid, truth = incidents_of(w, "timeout")[0]
    events: list = []
    inv_id = investigate(tenant, iid, Policy(truth["service"], pick=truth["culprit_deploy"]), events=events)

    full = episodic.full(tenant, inv_id)
    assert full["state"] == "AWAITING_REVIEW" and full["outcome"] == "proposed"
    assert [s["tool"] for s in full["steps"]][:4] == ["blast_radius", "owners_of", "write_finding", "write_finding"]
    assert db.read(tenant, "MATCH (:Investigation {id:$id})-[:HAS_STEP]->(a)-[:NEXT]->(b) RETURN count(*) AS n",
                   {"id": inv_id})[0]["n"] == len(full["steps"]) - 1
    assert {f["kind"] for f in full["findings"]} == {"blast_radius", "owners"}
    assert all(f["handed_to"] == ["investigator"] for f in full["findings"])
    (h,) = full["hypotheses"]
    assert h["deploy_id"] == truth["culprit_deploy"] and all(c["verified"] for c in h["claims"])
    assert full["actions"][0]["kind"] == "rollback_proposal"
    states = [d["state"] for k, d in events if k == "state"]
    assert states == ["TRIAGED", "HYPOTHESIZED", "AWAITING_REVIEW"]
    stats = db.read(tenant, "MATCH (v:Investigation {id:$id}) RETURN v.faithfulness AS f, v.tool_calls AS n",
                    {"id": inv_id})[0]
    assert stats["f"] == 1.0 and stats["n"] == len(full["steps"])


def test_broken_event_listener_does_not_fail_the_investigation(world):
    """Regression: a console that can't print the model's Unicode used to mark the run FAILED."""
    tenant, w = world
    iid, truth = incidents_of(w, "timeout")[0]

    def listener(kind, data):
        raise UnicodeEncodeError("charmap", "‑", 0, 1, "character maps to <undefined>")

    inv_id = anyio.run(lambda: orchestrator.investigate(tenant, iid, chat_fn=Policy(truth["service"]),
                                                        on_event=listener))
    assert episodic.get(tenant, inv_id)["state"] == "AWAITING_REVIEW"


def test_describe_error_unwraps_exception_groups():
    e = ExceptionGroup("unhandled errors in a TaskGroup", [llm.AllProvidersExhausted("groq: quota")])
    assert orchestrator.describe_error(e) == "AllProvidersExhausted: groq: quota"


def test_gate_bounces_fabricated_edges_then_accepts(world):
    tenant, w = world
    iid, truth = incidents_of(w, "timeout")[0]
    policy = Policy(truth["service"], fake_first=True)
    inv_id = investigate(tenant, iid, policy)
    assert policy.submissions == 2
    (h,) = episodic.hypotheses(tenant, inv_id)
    assert all(c["verified"] for c in h["claims"]) and not any(987654 in c["edge_ids"] for c in h["claims"])


def test_abstains_when_no_deploy_is_plausible(world):
    tenant, w = world
    iid, truth = incidents_of(w, "abstain")[0]
    inv_id = investigate(tenant, iid, Policy(truth["service"]))
    full = episodic.full(tenant, inv_id)
    assert full["outcome"] == "abstained" and full["hypotheses"] == []
    assert all(a["kind"] == "page" for a in full["actions"])


def test_confirm_teaches_and_memory_changes_the_next_ranking(world):
    tenant, w = world
    (first, t1), (second, t2) = incidents_of(w, "timeout")[:2]
    inv1 = investigate(tenant, first, Policy(t1["service"], pick=t1["culprit_deploy"]))
    out = curator.review(tenant, inv1, "confirm", reviewer="asha", judge=None)
    assert out["lesson"]["success_count"] == 1 and episodic.get(tenant, inv1)["state"] == "LEARNED"

    on = impl.suspects(ToolCtx(tenant, t2["ts"], symptom="timeout", service=t2["service"]), t2["service"])
    off = impl.suspects(ToolCtx(tenant, t2["ts"], memory_enabled=False, symptom="timeout", service=t2["service"]),
                        t2["service"])
    culprit_on = next(s for s in on["suspects"] if s["deploy"] == t2["culprit_deploy"])
    culprit_off = next(s for s in off["suspects"] if s["deploy"] == t2["culprit_deploy"])
    assert culprit_on["features"]["lesson_match"] > 0 == culprit_off["features"]["lesson_match"]
    assert culprit_on["rank"] <= culprit_off["rank"]

    ctx = ToolCtx(tenant, t2["ts"], symptom="timeout", service=t2["service"])
    assert impl.recall_lessons(ctx)["lessons"][0]["check_first"] == t2["culprit_service"]
    similar = impl.recall_similar(ctx)["similar"]
    assert similar[0]["incident"] == first and similar[0]["culprit_service"] == t1["culprit_service"]
    past = impl.get_past_investigation(ctx, first)
    assert past["hypotheses"][0]["deploy_id"] == t1["culprit_deploy"] and "suspects" in past["tool_sequence"]
    # Memory never leaks backwards in time: the first incident can't see its own lesson.
    assert impl.recall_lessons(ToolCtx(tenant, t1["ts"], symptom="timeout", service=t1["service"]))["lessons"] == []


def test_reject_weakens_lessons_and_cause(world):
    tenant, w = world
    (first, t1), (second, t2) = incidents_of(w, "timeout")[:2]
    culprit_svc = t1["culprit_service"]
    curator.review(tenant, investigate(tenant, first, Policy(t1["service"], pick=t1["culprit_deploy"])),
                   "confirm", reviewer="asha", judge=None)
    inv2 = investigate(tenant, second, Policy(t2["service"], pick=t2["culprit_deploy"]))
    out = curator.review(tenant, inv2, "reject", reviewer="vikram", judge=None)
    assert out["weakened"][0]["fail_count"] == 1
    assert out["cause"]["confidence"] < 0.85  # was 0.65 after one confirmation, halved
    lesson = procedural.recall(tenant, "timeout", t1["service"], 10**12)
    assert lesson == [] or lesson[0]["weight"] < 0.5
    assert all(r["check_first"] == culprit_svc for r in lesson)


def test_review_requires_awaiting_review_and_states_are_enforced(world):
    tenant, w = world
    iid, truth = incidents_of(w, "timeout")[0]
    inv_id = investigate(tenant, iid, Policy(truth["service"]))
    curator.review(tenant, inv_id, "confirm", reviewer="asha", judge=None)
    with pytest.raises(curator.ReviewError):
        curator.review(tenant, inv_id, "confirm", reviewer="asha", judge=None)
    with pytest.raises(episodic.IllegalTransition):
        episodic.set_state(tenant, inv_id, "TRIAGED")


def test_entity_resolution(world):
    tenant, _ = world
    a = semantic.upsert(tenant, "db timeout", judge=None)
    assert semantic.upsert(tenant, "Database timeouts", judge=None)["key"] == a["key"]
    assert semantic.upsert(tenant, "DB time-outs", judge=None)["key"] == a["key"]
    oom = semantic.upsert(tenant, "OOM", judge=None)
    assert semantic.upsert(tenant, "out of memory", judge=None)["key"] == oom["key"]
    assert semantic.upsert(tenant, "disk full", judge=None)["is_new"]
    # Borderline match is delegated to the judge.
    pool = semantic.upsert(tenant, "connection pool exhaustion", judge=None)
    assert semantic.resolve(tenant, "pool exhaustion on redis", judge=lambda text, cands: 0)[0] == pool["key"]
    assert semantic.resolve(tenant, "pool exhaustion on redis", judge=lambda text, cands: None)[1] is True
