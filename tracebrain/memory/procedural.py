"""Procedural memory: Lessons like "for `timeout` on checkout, check redis-cart first".

A Lesson is keyed by (symptom, alerted service, check_first service). It is created/strengthened only
by a human-confirmed investigation and weakened when a review rejects a hypothesis it pointed to.
Its weight feeds the `lesson_match` scoring feature: (success - fail) / (success + fail + 1), in [0, 1).
Only lessons learned from incidents BEFORE the current incident time are ever recalled.
"""

from tracebrain import db, queries


def lesson_id(symptom: str, service: str, check_first: str) -> str:
    return f"lesson:{symptom}@{service}->{check_first}"


def weight(success: int, fail: int) -> float:
    return max(0.0, (success - fail) / (success + fail + 1))


def learn(tenant: str, incident_id: str, symptom: str, service: str, check_first: str, cause_key: str) -> dict:
    return db.write(tenant, queries.UPSERT_LESSON, {
        "id": lesson_id(symptom, service, check_first), "incident_id": incident_id, "cause_key": cause_key,
        "symptom": symptom, "service": service, "check_first": check_first})[0]


def penalise(tenant: str, symptom: str, service: str, check_first: str) -> list[dict]:
    return db.write(tenant, queries.FAIL_LESSONS, {"symptom": symptom, "service": service,
                                                   "check_first": check_first})


def recall(tenant: str, symptom: str, service: str, t: int) -> list[dict]:
    rows = db.read(tenant, queries.RECALL_LESSONS, {"symptom": symptom, "service": service, "t": t})
    for r in rows:
        r["weight"] = round(weight(r["success_count"], r["fail_count"]), 3)
    return rows


def boosts(tenant: str, symptom: str, service: str, t: int) -> dict[str, float]:
    """check_first service -> lesson weight, for the scoring function's lesson_match feature."""
    out: dict[str, float] = {}
    for r in recall(tenant, symptom, service, t):
        out[r["check_first"]] = max(out.get(r["check_first"], 0.0), r["weight"])
    return out
