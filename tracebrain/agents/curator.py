"""Curator: turns a HUMAN review into long-term memory. Nothing else writes Causes or Lessons.

confirm -> Cause upserted (entity-resolved) + confidence up, Incident -CAUSED_BY-> Cause,
           Incident -ROOT_DEPLOY-> Deploy, Lesson "symptom@service -> culprit service" strengthened,
           and a lesson that pointed at the wrong service (if the top hypothesis was wrong) weakened.
reject  -> lessons pointing at the rejected deploy's service weakened, the rejected cause's
           confidence halved (retracted below 0.2). Nothing new is learned from a rejection.
"""

from typing import Literal

from tracebrain import db, queries
from tracebrain.memory import episodic, procedural, semantic
from tracebrain.tools import impl
from tracebrain.tools.impl import ToolCtx


class ReviewError(ValueError):
    pass


def _deploy_service(tenant: str, deploy_id: str) -> str:
    rows = db.read(tenant, queries.DEPLOY_SERVICE, {"deploy_id": deploy_id})
    if not rows:
        raise ReviewError(f"unknown deploy {deploy_id!r}")
    return rows[0]["service"]


def review(tenant: str, inv_id: str, verdict: Literal["confirm", "reject"], reviewer: str,
           deploy_id: str | None = None, cause_text: str | None = None,
           judge: semantic.Judge | None = semantic.llm_judge) -> dict:
    inv = episodic.get(tenant, inv_id)
    if inv["state"] != "AWAITING_REVIEW":
        raise ReviewError(f"{inv_id} is {inv['state']}, not AWAITING_REVIEW")
    inc = impl.get_incident(ToolCtx(tenant, 0), inv["incident_id"])
    hyps = episodic.hypotheses(tenant, inv_id)
    top = hyps[0] if hyps else None
    top_service = _deploy_service(tenant, top["deploy_id"]) if top else None
    out: dict = {"investigation": inv_id, "incident": inc["id"], "verdict": verdict}

    if verdict == "confirm":
        deploy_id = deploy_id or (top and top["deploy_id"])
        cause_text = cause_text or (top and top["likely_cause"])
        if not deploy_id or not cause_text:
            raise ReviewError("confirm needs a deploy_id and cause_text (no hypothesis to default from)")
        culprit_service = _deploy_service(tenant, deploy_id)
        episodic.set_state(tenant, inv_id, "CONFIRMED")
        cause = semantic.upsert(tenant, cause_text, judge)
        stats = semantic.confirm(tenant, cause["key"])
        db.write(tenant, queries.LINK_CAUSE, {"incident_id": inc["id"], "key": cause["key"], "reviewer": reviewer,
                                              "now": episodic._now(), "confidence": stats["confidence"],
                                              "investigation": inv_id})
        db.write(tenant, queries.LINK_ROOT_DEPLOY, {"incident_id": inc["id"], "deploy_id": deploy_id})
        out["lesson"] = procedural.learn(tenant, inc["id"], inc["symptom"], inc["service"], culprit_service,
                                         cause["key"])
        if top_service and top_service != culprit_service:
            out["weakened"] = procedural.penalise(tenant, inc["symptom"], inc["service"], top_service)
        out.update(cause_key=cause["key"], cause_is_new=cause["is_new"], confidence=stats["confidence"],
                   deploy_id=deploy_id, top_was_right=bool(top and top["deploy_id"] == deploy_id))
        episodic.set_outcome(tenant, inv_id, "confirmed", "resolved")
    else:
        episodic.set_state(tenant, inv_id, "REJECTED")
        if top_service:
            out["weakened"] = procedural.penalise(tenant, inc["symptom"], inc["service"], top_service)
        rejected_cause = cause_text or (top and top["likely_cause"])
        if rejected_cause:
            key, is_new = semantic.resolve(tenant, rejected_cause, judge)
            if not is_new:
                out["cause"] = semantic.reject(tenant, key)
        episodic.set_outcome(tenant, inv_id, "rejected", "open")

    episodic.set_state(tenant, inv_id, "LEARNED")
    return out
