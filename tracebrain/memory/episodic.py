"""Episodic memory: each investigation is stored in the graph as it happens.

Investigation -[:HAS_STEP]-> Step -[:NEXT]-> Step ...   (every tool call, with edge_ids)
Investigation -[:PRODUCED]-> Finding -[:HANDOFF]-> Investigation   (agent blackboard)
Investigation -[:PROPOSED]-> Hypothesis -[:ASSERTS]-> Claim ; Hypothesis -[:SUSPECTS]-> Deploy
Investigation -[:TOOK]-> Action -[:TARGETS]-> Team|Service|Deploy|Person

Agents share state ONLY through these nodes: Triage writes Findings, Investigator reads them.
"""

import json
import time
import uuid
from typing import Any

from tracebrain import db, queries

RESULT_LIMIT = 8000

# Incident state machine. Every transition goes through set_state, which rejects illegal moves.
TRANSITIONS: dict[str, set[str]] = {
    "OPEN": {"TRIAGED", "FAILED"},
    "TRIAGED": {"HYPOTHESIZED", "FAILED"},
    "HYPOTHESIZED": {"VERIFIED", "AWAITING_REVIEW", "FAILED"},
    "VERIFIED": {"AWAITING_REVIEW", "FAILED"},
    "AWAITING_REVIEW": {"CONFIRMED", "REJECTED"},
    "CONFIRMED": {"LEARNED"},
    "REJECTED": {"LEARNED"},
    "LEARNED": set(),
    # A failed run (quota exhausted, crash) can be resumed from the last completed stage.
    "FAILED": {"OPEN", "TRIAGED", "HYPOTHESIZED"},
}
TERMINAL = {"AWAITING_REVIEW", "CONFIRMED", "REJECTED", "LEARNED"}


class IllegalTransition(RuntimeError):
    pass


def _now() -> int:
    return int(time.time())


def _dump(obj: Any, limit: int = RESULT_LIMIT) -> str:
    text = json.dumps(obj, default=str)
    return text if len(text) <= limit else text[:limit] + "...[truncated]"


def start_investigation(tenant: str, incident_id: str, memory_enabled: bool = True) -> str:
    inv_id = f"inv:{uuid.uuid4().hex[:10]}"
    rows = db.write(tenant, queries.CREATE_INVESTIGATION,
                    {"id": inv_id, "incident_id": incident_id, "now": _now(), "memory": memory_enabled})
    if not rows:
        raise ValueError(f"no incident '{incident_id}' in tenant '{tenant}'")
    return inv_id


def get(tenant: str, inv_id: str) -> dict:
    rows = db.read(tenant, queries.GET_INVESTIGATION, {"id": inv_id})
    if not rows:
        raise KeyError(inv_id)
    return rows[0]


def set_state(tenant: str, inv_id: str, new_state: str) -> str:
    current = get(tenant, inv_id)["state"]
    if new_state not in TRANSITIONS.get(current, set()):
        raise IllegalTransition(f"{inv_id}: {current} -> {new_state} is not allowed")
    db.write(tenant, queries.SET_STATE, {"id": inv_id, "state": new_state, "now": _now()})
    return new_state


def log_step(tenant: str, inv_id: str, n: int, agent: str, tool: str, args: dict, result: Any,
             edge_ids: list[int], ms: int, error: str | None) -> None:
    db.write(tenant, queries.ADD_STEP, {"id": inv_id, "n": n, "agent": agent, "tool": tool, "args": _dump(args),
                                        "result": _dump(result), "edge_ids": edge_ids, "ms": ms,
                                        "error": error or "", "now": _now()})
    if n > 1:
        db.write(tenant, queries.LINK_STEP, {"id": inv_id, "prev": n - 1, "n": n})


def steps(tenant: str, inv_id: str) -> list[dict]:
    out = []
    for r in db.read(tenant, queries.STEPS, {"id": inv_id}):
        r["args"] = json.loads(r.pop("args_json"))
        raw = r.pop("result_json")
        try:
            r["result"] = json.loads(raw)
        except json.JSONDecodeError:
            r["result"] = raw
        r["error"] = r["error"] or None
        out.append(r)
    return out


def write_finding(tenant: str, inv_id: str, agent: str, kind: str, payload: Any) -> str:
    fid = f"fnd:{uuid.uuid4().hex[:8]}"
    db.write(tenant, queries.ADD_FINDING, {"id": inv_id, "fid": fid, "kind": kind, "agent": agent,
                                           "payload": _dump(payload), "now": _now()})
    return fid


def findings(tenant: str, inv_id: str) -> list[dict]:
    rows = db.read(tenant, queries.FINDINGS, {"id": inv_id})
    for r in rows:
        r["payload"] = json.loads(r.pop("payload_json"))
    return rows


def handoff(tenant: str, inv_id: str, from_agent: str, to_agent: str) -> int:
    return db.write(tenant, queries.HANDOFF, {"id": inv_id, "from_agent": from_agent, "to_agent": to_agent,
                                              "now": _now()})[0]["n"]


def store_hypotheses(tenant: str, inv_id: str, hypotheses: list[dict]) -> None:
    for h in hypotheses:
        hid = f"hyp:{uuid.uuid4().hex[:8]}"
        db.write(tenant, queries.ADD_HYPOTHESIS, {
            "id": inv_id, "hid": hid, "rank": h["rank"], "deploy_id": h["deploy_id"],
            "likely_cause": h.get("likely_cause") or "", "summary": h.get("summary") or "",
            "score": float(h.get("score") or 0.0), "features": _dump(h.get("features") or {})})
        for n, c in enumerate(h.get("claims", []), 1):
            db.write(tenant, queries.ADD_CLAIM, {"hid": hid, "n": n, "text": c["text"], "edge_ids": c["edge_ids"],
                                                 "verified": c["verified"], "reason": c.get("reason") or ""})


def store_actions(tenant: str, inv_id: str, actions: list[dict]) -> None:
    for i, a in enumerate(actions, 1):
        db.write(tenant, queries.ADD_ACTION, {"id": inv_id, "aid": f"{inv_id}:act{i}", "kind": a["kind"],
                                              "target": a["target"], "reason": a.get("reason") or ""})


def set_outcome(tenant: str, inv_id: str, outcome: str, incident_status: str) -> None:
    db.write(tenant, queries.SET_OUTCOME, {"id": inv_id, "outcome": outcome, "incident_status": incident_status})


def hypotheses(tenant: str, inv_id: str) -> list[dict]:
    rows = db.read(tenant, queries.HYPOTHESES, {"id": inv_id})
    for r in rows:
        r["features"] = json.loads(r.pop("features_json") or "{}")
        r["claims"] = [c for c in r["claims"] if c.get("text") is not None]
        r["verifications"] = [v for v in r["verifications"] if v.get("method") is not None]
    return rows


def resume_point(tenant: str, inv_id: str) -> str:
    """The stage a FAILED/interrupted run should continue from, judged from what is in the graph."""
    if hypotheses(tenant, inv_id):
        return "HYPOTHESIZED"
    if any(f["handed_to"] for f in findings(tenant, inv_id)):
        return "TRIAGED"
    return "OPEN"


def list_investigations(tenant: str, limit: int = 50) -> list[dict]:
    return db.read(tenant, queries.LIST_INVESTIGATIONS, {"limit": limit})


def full(tenant: str, inv_id: str) -> dict:
    """Everything about one investigation, read back from the graph (API / UI / resume)."""
    return {**get(tenant, inv_id), "steps": steps(tenant, inv_id), "findings": findings(tenant, inv_id),
            "hypotheses": hypotheses(tenant, inv_id),
            "actions": db.read(tenant, queries.ACTIONS, {"id": inv_id})}
