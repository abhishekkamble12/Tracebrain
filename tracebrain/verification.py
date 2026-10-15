"""Act, then verify: before a human reviews a rollback proposal, try it in a sandbox.

The live graph is copied (FalkorDB Graph.copy) to a throwaway sandbox graph, the proposed deploy is
marked rolled back there, and an Environment answers "does the symptom clear?". The result is stored
on the hypothesis as (Hypothesis)-[:VERIFIED_BY]->(Verification) and shown to the reviewer.

Only the TOP hypothesis (the one the rollback proposal is for) is verified, and the result never
re-ranks hypotheses. Verification informs the human; it is not used to pick the answer, so the
environment's knowledge can't leak into the measured accuracy.

Environments:
- SyntheticEnvironment: the fault-injection simulator. It knows which deploy was injected, the way a
  staging cluster "knows" whether a revert fixes it. Labelled "simulated" everywhere it appears.
- (lab) a real environment would revert the change in the OpenTelemetry Demo and re-check its metrics.
"""

import json
import time
import uuid
from pathlib import Path
from typing import Protocol

from tracebrain import db, queries

TRUTH_PATH = Path(__file__).resolve().parent.parent / "data" / "ground_truth.json"


class Environment(Protocol):
    name: str

    def rollback_clears(self, tenant: str, incident_id: str, deploy_id: str) -> bool | None:
        """True/False if reverting `deploy_id` clears the incident's symptom; None if unknown."""
        ...


class SyntheticEnvironment:
    name = "simulated: synthetic fault injection"

    def __init__(self, injected: dict[str, str | None]):
        # "tenant/incident" -> injected deploy id (None = no deploy at fault)
        self._injected = injected

    @classmethod
    def from_truth(cls, truth: dict[str, dict]) -> "SyntheticEnvironment":
        return cls({k: v["culprit_deploy"] for k, v in truth.items()})

    def rollback_clears(self, tenant: str, incident_id: str, deploy_id: str) -> bool | None:
        key = f"{tenant}/{incident_id}"
        if key not in self._injected:
            return None
        return self._injected[key] == deploy_id


def default_environment() -> Environment | None:
    if TRUTH_PATH.exists():
        return SyntheticEnvironment.from_truth(json.loads(TRUTH_PATH.read_text(encoding="utf-8")))
    return None


def verify_rollback(tenant: str, incident_id: str, hypothesis_id: str, deploy_id: str,
                    env: Environment) -> dict:
    sandbox = f"{db.graph_name(tenant)}__sandbox_{uuid.uuid4().hex[:6]}"
    db.graph_for(tenant).copy(sandbox)
    sb = db.client().select_graph(sandbox)
    try:
        sb.query("MATCH (d:Deploy {id: $id}) SET d.rolled_back = true", {"id": deploy_id})
        clears = env.rollback_clears(tenant, incident_id, deploy_id)
    finally:
        sb.delete()
    if clears is None:  # environment can't tell: record nothing, reviewer sees "not verified"
        return {"deploy_id": deploy_id, "clears": None, "environment": env.name, "sandbox": sandbox}
    db.write(tenant, queries.ADD_VERIFICATION, {
        "hid": hypothesis_id, "method": "sandbox_rollback", "environment": env.name,
        "clears": clears, "sandbox": sandbox, "now": int(time.time())})
    return {"deploy_id": deploy_id, "clears": clears, "environment": env.name, "sandbox": sandbox}
