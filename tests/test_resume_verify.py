"""Sandbox rollback verification and resuming interrupted investigations."""

import anyio

from test_orchestrator import Policy, incidents_of, world  # noqa: F401  (fixture re-export)
from tracebrain import db, orchestrator
from tracebrain.memory import episodic
from tracebrain.verification import SyntheticEnvironment


def env_for(tenant, w):
    return SyntheticEnvironment({f"{tenant}/{k}": v["culprit_deploy"] for k, v in w.truth.items()})


def run_inv(tenant, iid, policy, env, events=None, memory=True):
    return anyio.run(lambda: orchestrator.investigate(
        tenant, iid, memory_enabled=memory, chat_fn=policy, environment=env,
        on_event=(lambda k, d: events.append((k, d))) if events is not None else None))


def test_rollback_of_culprit_verifies(world):
    tenant, w = world
    iid, truth = incidents_of(w, "timeout")[0]
    events: list = []
    inv_id = run_inv(tenant, iid, Policy(truth["service"], pick=truth["culprit_deploy"]), env_for(tenant, w), events)
    states = [d["state"] for k, d in events if k == "state"]
    assert states == ["TRIAGED", "HYPOTHESIZED", "VERIFIED", "AWAITING_REVIEW"]
    (h,) = episodic.hypotheses(tenant, inv_id)
    assert h["verifications"][0]["clears"] is True and "simulated" in h["verifications"][0]["environment"]
    # The sandbox was thrown away and the live graph was not touched.
    assert not [g for g in db.client().list_graphs() if "__sandbox_" in g and tenant in g]
    assert db.read(tenant, "MATCH (d:Deploy {id:$id}) RETURN d.rolled_back AS r",
                   {"id": truth["culprit_deploy"]})[0]["r"] is None


def test_rollback_of_wrong_deploy_is_caught(world):
    tenant, w = world
    iid, truth = next((k, v) for k, v in incidents_of(w, "timeout")
                      if any(r.startswith("decoy_path") for r in v["decoys"].values()))
    decoy = next(d for d, r in truth["decoys"].items() if r == "decoy_path")
    events: list = []
    inv_id = run_inv(tenant, iid, Policy(truth["service"], pick=decoy), env_for(tenant, w), events)
    assert "VERIFIED" not in [d["state"] for k, d in events if k == "state"]
    assert next(d for k, d in events if k == "verification")["clears"] is False
    assert episodic.get(tenant, inv_id)["state"] == "AWAITING_REVIEW"


def test_no_environment_means_no_verification(world):
    tenant, w = world
    iid, truth = incidents_of(w, "timeout")[0]
    inv_id = run_inv(tenant, iid, Policy(truth["service"]), None)
    assert episodic.hypotheses(tenant, inv_id)[0]["verifications"] == []


class CrashOn:
    """Raises (like a lost provider or a killed process) on the Nth call made by one agent."""

    def __init__(self, inner, agent, nth):
        self.inner, self.agent, self.nth, self.calls = inner, agent, nth, 0

    def __call__(self, messages, tools):
        if messages[0]["content"].startswith(f"You are the {self.agent.upper()}"):
            self.calls += 1
            if self.calls == self.nth:
                raise RuntimeError("simulated crash")
        return self.inner(messages, tools)


def test_resume_after_crash_in_investigator_replays_instead_of_rerunning(world):
    tenant, w = world
    iid, truth = incidents_of(w, "timeout")[0]
    inv_id = orchestrator.start(tenant, iid)
    crash = CrashOn(Policy(truth["service"]), "investigator", nth=3)  # after read_findings + recall_lessons
    assert anyio.run(lambda: orchestrator.run(tenant, inv_id, chat_fn=crash, environment=None)) == "FAILED"
    before = [s["tool"] for s in episodic.steps(tenant, inv_id)]
    assert before == ["blast_radius", "owners_of", "write_finding", "write_finding", "read_findings", "recall_lessons"]

    events: list = []
    state = anyio.run(lambda: orchestrator.run(tenant, inv_id, chat_fn=Policy(truth["service"]), environment=None,
                                               on_event=lambda k, d: events.append((k, d))))
    assert state == "AWAITING_REVIEW"
    resumed = next(d for k, d in events if k == "resumed")
    assert resumed["from_state"] == "TRIAGED" and resumed["replayed_steps"] == 6
    after = episodic.steps(tenant, inv_id)
    assert [s["tool"] for s in after] == before + ["suspects"]          # nothing re-executed
    assert [s["n"] for s in after] == list(range(1, len(after) + 1))
    assert db.read(tenant, "MATCH (:Investigation {id:$id})-[:HAS_STEP]->()-[:NEXT]->() RETURN count(*) AS n",
                   {"id": inv_id})[0]["n"] == len(after) - 1
    assert episodic.get(tenant, inv_id)["resumes"] == 1
    assert len(episodic.hypotheses(tenant, inv_id)) == 1


def test_resume_mid_triage_continues_triage(world):
    tenant, w = world
    iid, truth = incidents_of(w, "timeout")[0]
    inv_id = orchestrator.start(tenant, iid)
    crash = CrashOn(Policy(truth["service"]), "triage", nth=3)  # after blast_radius + owners_of
    anyio.run(lambda: orchestrator.run(tenant, inv_id, chat_fn=crash, environment=None))
    assert episodic.get(tenant, inv_id)["state"] == "FAILED"
    anyio.run(lambda: orchestrator.run(tenant, inv_id, chat_fn=Policy(truth["service"]), environment=None))
    tools = [s["tool"] for s in episodic.steps(tenant, inv_id)]
    assert tools[:4] == ["blast_radius", "owners_of", "write_finding", "write_finding"]
    assert tools.count("blast_radius") == 1
    assert {f["kind"] for f in episodic.findings(tenant, inv_id)} == {"blast_radius", "owners"}


def test_run_on_finished_investigation_is_a_no_op(world):
    tenant, w = world
    iid, truth = incidents_of(w, "timeout")[0]
    inv_id = run_inv(tenant, iid, Policy(truth["service"]), None)
    n = len(episodic.steps(tenant, inv_id))
    assert anyio.run(lambda: orchestrator.run(tenant, inv_id, chat_fn=Policy(truth["service"]))) == "AWAITING_REVIEW"
    assert len(episodic.steps(tenant, inv_id)) == n
