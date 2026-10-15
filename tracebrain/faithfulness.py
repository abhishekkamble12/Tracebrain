"""Path faithfulness: every claim must be backed by graph edges the agent actually retrieved.

A claim {text, edge_ids} is VERIFIED only if:
  1. it cites at least one edge id;
  2. every cited id was returned by a tool during THIS investigation (no invented ids);
  3. every cited id exists in the graph;
  4. each cited edge is relevant: its source or target name appears in the claim text.
A hypothesis is ACCEPTABLE only if its deploy was among the retrieved suspects and one of its
verified claims cites that deploy's DEPLOYED_TO edge.

`gate()` turns these checks into a rejection message the Investigator must fix before its
submission is accepted (the agent loop retries); `apply()` grades what was finally submitted.
"""

from typing import Any

from tracebrain import db, queries

ACTION_KINDS = {"ticket", "rollback_proposal", "page"}


def lookup_edges(tenant: str, ids: list[int]) -> dict[int, dict]:
    if not ids:
        return {}
    return {r["id"]: r for r in db.read(tenant, queries.EDGE_LOOKUP, {"ids": sorted(set(ids))})}


def collect_deploys(results: list[Any]) -> set[str]:
    """Deploy ids that appeared in tool results (suspects lists) during the investigation."""
    found: set[str] = set()

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            if isinstance(o.get("deploy"), str):
                found.add(o["deploy"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    for r in results:
        walk(r)
    return found


def check_claim(claim: dict, seen_edges: set[int], edges: dict[int, dict]) -> tuple[bool, str]:
    ids = [i for i in claim.get("edge_ids") or [] if isinstance(i, int)]
    text = (claim.get("text") or "").lower()
    if not ids:
        return False, "no evidence: cite edge_ids from tool results"
    unseen = [i for i in ids if i not in seen_edges]
    if unseen:
        return False, f"edge(s) {unseen} were not returned by any tool in this investigation"
    missing = [i for i in ids if i not in edges]
    if missing:
        return False, f"edge(s) {missing} do not exist"
    irrelevant = [i for i in ids if str(edges[i]["src"]).lower() not in text and str(edges[i]["dst"]).lower() not in text]
    if irrelevant:
        e = edges[irrelevant[0]]
        return False, f"edge {irrelevant[0]} ({e['src']} -{e['type']}-> {e['dst']}) is not about what the claim says"
    return True, "ok"


def apply(tenant: str, final: dict, seen_edges: set[int], seen_deploys: set[str]) -> dict:
    """Grade a submission. Returns the hypotheses with per-claim verdicts, hypothesis-level problems,
    and the faithfulness score (verified claims / all claims)."""
    hyps = final.get("hypotheses") or []
    cited = [i for h in hyps for c in h.get("claims") or [] for i in c.get("edge_ids") or [] if isinstance(i, int)]
    edges = lookup_edges(tenant, cited)
    graded, problems, total, verified = [], [], 0, 0
    for rank, h in enumerate(hyps, 1):
        deploy = h.get("deploy_id")
        claims = []
        for c in h.get("claims") or []:
            ok, reason = check_claim(c, seen_edges, edges)
            total += 1
            verified += ok
            claims.append({"text": c.get("text", ""), "edge_ids": c.get("edge_ids") or [], "verified": ok,
                           "reason": reason})
        if deploy not in seen_deploys:
            problems.append(f"hypothesis {rank}: deploy {deploy!r} was not among the retrieved suspects")
        elif not any(c["verified"] and any(edges.get(i, {}).get("type") == "DEPLOYED_TO" and edges[i]["src"] == deploy
                                           for i in c["edge_ids"]) for c in claims):
            problems.append(f"hypothesis {rank}: no verified claim cites the DEPLOYED_TO edge of {deploy}")
        for c in claims:
            if not c["verified"]:
                problems.append(f"hypothesis {rank} claim {c['text']!r}: {c['reason']}")
        graded.append({**h, "rank": rank, "claims": claims})
    for a in final.get("actions") or []:
        if a.get("kind") not in ACTION_KINDS:
            problems.append(f"action kind {a.get('kind')!r} must be one of {sorted(ACTION_KINDS)}")
        elif final.get("abstain") and a.get("kind") != "page":
            problems.append("when abstaining, only 'page' actions are allowed")
    if not final.get("abstain") and not hyps:
        problems.append("no hypotheses: submit at least one, or set abstain=true with a reason")
    return {"hypotheses": graded, "problems": problems, "claims_total": total, "claims_verified": verified,
            "faithfulness": round(verified / total, 4) if total else None}


def gate(tenant: str, final: dict, seen_edges: set[int], seen_deploys: set[str]) -> str | None:
    """None if the submission is acceptable, else a message telling the agent what to fix."""
    problems = apply(tenant, final, seen_edges, seen_deploys)["problems"]
    return "; ".join(problems) if problems else None
