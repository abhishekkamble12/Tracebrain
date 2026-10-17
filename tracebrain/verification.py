"""Act, then check: before a human reviews a rollback proposal, try it in a sandbox.

Two separate things happen, and they are reported separately:

1. Graph counterfactual (real graph work). The live graph is copied (FalkorDB Graph.copy) to a
   throwaway sandbox, the proposed deploy is marked rolled_back there, and the suspect ranking is
   re-run on the copy (SUSPECTS skips rolled-back deploys). The reviewer sees which deploy would be
   blamed next if this rollback doesn't help, and how many candidates remain.
2. Symptom check (an ORACLE in this demo). An Environment answers "does the symptom clear?".
   SyntheticEnvironment answers from the fault-injection ground truth (data/ground_truth.json),
   i.e. it knows the answer. A real environment would revert the change in staging and watch metrics.
   It is labelled as an oracle everywhere it appears.

Both are stored as (Hypothesis)-[:VERIFIED_BY]->(Verification). Only the TOP hypothesis is checked,
and the result never re-ranks hypotheses or feeds the eval, so the oracle can't leak into accuracy.
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
    name = "simulated oracle: synthetic fault-injection ground truth"

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
    from tracebrain.tools import impl  # tools import memory modules; keep this module light

    suffix = f"__sandbox_{uuid.uuid4().hex[:6]}"
    sandbox = f"{db.graph_name(tenant)}{suffix}"
    db.graph_for(tenant).copy(sandbox)
    try:
        db.write(tenant + suffix, "MATCH (d:Deploy {id: $id}) SET d.rolled_back = true", {"id": deploy_id})
        inc = impl.get_incident(impl.ToolCtx(tenant + suffix, 0), incident_id)
        after = impl.suspects(impl.ToolCtx(tenant + suffix, inc["ts"], memory_enabled=False), inc["service"])
    finally:
        db.client().select_graph(sandbox).delete()
    remaining = after["suspects"]
    counterfactual = {"next_suspect": remaining[0]["deploy"] if remaining else None,
                      "next_suspect_service": remaining[0]["service"] if remaining else None,
                      "remaining_candidates": after["total_candidates"]}
    clears = env.rollback_clears(tenant, incident_id, deploy_id)
    out = {"deploy_id": deploy_id, "clears": clears, "environment": env.name, "sandbox": sandbox, **counterfactual}
    if clears is None:  # environment can't tell: record nothing, reviewer sees "not verified"
        return out
    db.write(tenant, queries.ADD_VERIFICATION, {
        "hid": hypothesis_id, "method": "sandbox_rollback", "environment": env.name, "clears": clears,
        "sandbox": sandbox, "now": int(time.time()), **counterfactual})
    return out
