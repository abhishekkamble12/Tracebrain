"""Agent tools as plain functions over the graph (used by the MCP server, baselines and tests).

Every function takes a ToolCtx that the *orchestrator* sets (tenant, incident time, ...); the LLM
only supplies the remaining arguments. All reads go through db.read (FalkorDB ro_query), and
anything derived from graph paths returns `edge_ids` so claims can cite exact edges.
Bad input raises ToolError with a message written for the LLM to recover from.
"""

import threading
from dataclasses import dataclass
from functools import lru_cache

from tracebrain import db, queries, scoring
from tracebrain.config import DEFAULT_WINDOW_S
from tracebrain.memory import episodic, procedural

FINDING_KINDS = {"blast_radius", "owners", "page_priority", "similar_incidents", "note"}


@dataclass(frozen=True)
class ToolCtx:
    tenant: str
    t: int                           # incident time: every as-of query is evaluated here
    investigation_id: str = ""
    memory_enabled: bool = True
    window_s: int = DEFAULT_WINDOW_S
    symptom: str = ""                # of the incident under investigation (set by the orchestrator)
    service: str = ""                # alerted service of that incident
    agent: str = ""                  # which agent is calling (for blackboard provenance)


class ToolError(Exception):
    pass


def _services(ctx: ToolCtx) -> list[str]:
    return [r["name"] for r in db.read(ctx.tenant, queries.SERVICE_NAMES)]


def _check_services(ctx: ToolCtx, names: list[str]) -> None:
    known = set(_services(ctx))
    unknown = [n for n in names if n not in known]
    if unknown:
        raise ToolError(f"unknown service(s) {unknown}. Known services: {sorted(known)}")


def get_incident(ctx: ToolCtx, incident_id: str) -> dict:
    rows = db.read(ctx.tenant, queries.INCIDENT, {"id": incident_id})
    if not rows:
        raise ToolError(f"no incident '{incident_id}'")
    return rows[0]


def blast_radius(ctx: ToolCtx, service: str, max_hops: int = 5) -> dict:
    _check_services(ctx, [service])
    rows = [r for r in db.read(ctx.tenant, queries.BLAST_RADIUS, {"svc": service, "t": ctx.t})
            if r["hops"] <= max_hops]
    return {"failing_service": service, "as_of": ctx.t, "affected": rows,
            "edge_ids": sorted({e for r in rows for e in r["edge_ids"]})}


def owners_of(ctx: ToolCtx, services: list[str]) -> dict:
    _check_services(ctx, services)
    rows = db.read(ctx.tenant, queries.OWNERS, {"services": services, "t": ctx.t})
    return {"as_of": ctx.t, "owners": rows, "edge_ids": sorted(r["edge_id"] for r in rows)}


@lru_cache(maxsize=32)
def _pagerank(tenant: str) -> dict[str, float]:
    rows = db.read(tenant, queries.PAGERANK)
    top = max((r["score"] for r in rows), default=0) or 1.0
    return {r["service"]: r["score"] / top for r in rows}


def suspects(ctx: ToolCtx, service: str, window_hours: float | None = None, limit: int = 10,
             lesson_boosts: dict[str, float] | None = None) -> dict:
    """Ranked deploys on `service` and its as-of dependencies inside the look-back window."""
    _check_services(ctx, [service])
    window_s = int(window_hours * 3600) if window_hours else ctx.window_s
    rows = db.read(ctx.tenant, queries.SUSPECTS, {"svc": service, "t": ctx.t, "window": window_s})
    services = sorted({r["service"] for r in rows})
    fails = {r["service"]: r["n"] for r in
             db.read(ctx.tenant, queries.SERVICE_FAIL_COUNTS, {"services": services, "t": ctx.t})}
    if lesson_boosts is None and ctx.memory_enabled and ctx.symptom:
        lesson_boosts = procedural.boosts(ctx.tenant, ctx.symptom, service, ctx.t)
    ranked = scoring.rank(rows, ctx.t, window_s, fails, _pagerank(ctx.tenant), lesson_boosts)
    out = [{
        "rank": r["rank"], "deploy": r["deploy"], "service": r["service"], "hops": r["proximity"],
        "minutes_before_incident": round((ctx.t - r["ts"]) / 60), "kind": r["kind"],
        "change_size": r["change_size"], "author": r["author"], "summary": r["summary"],
        "score": r["score"], "features": r["features"], "edge_ids": r["edge_ids"],
    } for r in ranked[:limit]]
    return {"alerted_service": service, "as_of": ctx.t, "window_hours": window_s / 3600,
            "total_candidates": len(ranked), "suspects": out,
            "note": "Scores are computed deterministically; cite edge_ids from here in claims."}


def path_between(ctx: ToolCtx, from_service: str, to_service: str) -> dict:
    _check_services(ctx, [from_service, to_service])
    rows = db.read(ctx.tenant, queries.SHORTEST_PATH, {"a": from_service, "b": to_service, "t": ctx.t})
    if not rows:
        return {"from": from_service, "to": to_service, "as_of": ctx.t, "path": None,
                "edge_ids": [], "note": "no dependency path at incident time"}
    return {"from": from_service, "to": to_service, "as_of": ctx.t, "path": rows[0]["services"],
            "edge_ids": rows[0]["edge_ids"]}


def _require_investigation(ctx: ToolCtx) -> None:
    if not ctx.investigation_id:
        raise ToolError("no investigation in context (blackboard tools only work inside an investigation)")


def write_finding(ctx: ToolCtx, kind: str, payload: dict) -> dict:
    """Blackboard write: the only graph write an agent can trigger, scoped to its own investigation."""
    _require_investigation(ctx)
    if kind not in FINDING_KINDS:
        raise ToolError(f"kind must be one of {sorted(FINDING_KINDS)}")
    fid = episodic.write_finding(ctx.tenant, ctx.investigation_id, ctx.agent or "agent", kind, payload)
    return {"finding_id": fid, "kind": kind, "stored": True}


def read_findings(ctx: ToolCtx) -> dict:
    _require_investigation(ctx)
    return {"findings": episodic.findings(ctx.tenant, ctx.investigation_id)}


def recall_similar(ctx: ToolCtx, limit: int = 5) -> dict:
    """Confirmed past incidents with the same symptom (same service first). Summaries only;
    use get_past_investigation for details. Empty when memory is disabled."""
    if not ctx.memory_enabled:
        return {"similar": [], "note": "memory disabled for this investigation"}
    rows = db.read(ctx.tenant, queries.RECALL_SIMILAR,
                   {"t": ctx.t, "symptom": ctx.symptom, "service": ctx.service, "limit": limit})
    return {"symptom": ctx.symptom, "similar": rows}


def recall_lessons(ctx: ToolCtx, service: str | None = None) -> dict:
    if not ctx.memory_enabled:
        return {"lessons": [], "note": "memory disabled for this investigation"}
    service = service or ctx.service
    return {"symptom": ctx.symptom, "service": service,
            "lessons": procedural.recall(ctx.tenant, ctx.symptom, service, ctx.t),
            "note": "check_first = service whose deploys caused this symptom before (human-confirmed)."}


def get_past_investigation(ctx: ToolCtx, incident_id: str) -> dict:
    """Progressive disclosure: the confirmed investigation of ONE earlier incident (tools used,
    hypotheses and verified claims)."""
    if not ctx.memory_enabled:
        return {"error": "memory disabled for this investigation"}
    rows = db.read(ctx.tenant, queries.PAST_INCIDENT_INVESTIGATION, {"incident_id": incident_id, "t": ctx.t})
    if not rows or not rows[0]["investigation"]:
        raise ToolError(f"no confirmed earlier investigation for '{incident_id}'")
    inv = rows[0]["investigation"]
    hyps = episodic.hypotheses(ctx.tenant, inv)
    return {"incident": incident_id, "confirmed_cause": rows[0]["cause"],
            "tool_sequence": [s["tool"] for s in episodic.steps(ctx.tenant, inv)],
            "hypotheses": [{"rank": h["rank"], "deploy_id": h["deploy_id"], "likely_cause": h["likely_cause"],
                            "verified_claims": [c["text"] for c in h["claims"] if c["verified"]]} for h in hyps]}


_centrality_lock = threading.Lock()
_centrality_cache: dict[tuple[str, tuple], tuple[dict[str, float], dict[str, float]]] = {}


def _asof_centrality(tenant: str, t: int) -> tuple[dict[str, float], dict[str, float]]:
    """Native algo.betweenness / algo.pageRank on the dependency graph AS OF t. The algorithms can't
    filter edges by time, so they run on a sandbox copy with every DEPENDS_ON not valid at t deleted.
    Cached per distinct as-of topology: incidents that see the same edges share one computation."""
    topology = tuple((r["id"], r["a"], r["b"]) for r in db.read(tenant, queries.ASOF_DEPENDENCY_IDS, {"t": t}))
    with _centrality_lock:  # single-flight: concurrent investigations wait for one copy, not N
        if (tenant, topology) not in _centrality_cache:
            with db.sandbox(tenant, "asof") as box:
                db.write(box, queries.DROP_EDGES_NOT_AS_OF, {"t": t})
                between = {r["service"]: r["score"] for r in db.read(box, queries.BETWEENNESS)}
                pagerank = {r["service"]: r["score"] for r in db.read(box, queries.PAGERANK)}
            _centrality_cache[(tenant, topology)] = between, pagerank
        return _centrality_cache[(tenant, topology)]


def page_priority(ctx: ToolCtx, service: str) -> dict:
    """Who to page: the alerted service and everything that calls it (as of t), ranked by betweenness
    on the as-of graph. The top service is the chokepoint most traffic flows through, so its owning
    team (as of t) is paged."""
    br = blast_radius(ctx, service)
    hops = {service: 0, **{a["service"]: a["hops"] for a in br["affected"]}}
    path_edges = {service: [], **{a["service"]: a["edge_ids"] for a in br["affected"]}}
    between, pagerank = _asof_centrality(ctx.tenant, ctx.t)
    top_b, top_p = max(between.values(), default=0) or 1.0, max(pagerank.values(), default=0) or 1.0
    owners = {o["service"]: o for o in owners_of(ctx, list(hops))["owners"]}
    ranking = sorted(({
        "service": s, "hops": h,
        "betweenness": round(between.get(s, 0.0) / top_b, 3), "pagerank": round(pagerank.get(s, 0.0) / top_p, 3),
        "team": owners.get(s, {}).get("team"), "people": owners.get(s, {}).get("people", []),
        "edge_ids": path_edges[s] + ([owners[s]["edge_id"]] if s in owners else []),
    } for s, h in hops.items()), key=lambda r: (-r["betweenness"], -r["pagerank"], r["hops"], r["service"]))
    for i, r in enumerate(ranking, 1):
        r["rank"] = i
    page = next((r for r in ranking if r["team"]), None)
    return {"alerted_service": service, "as_of": ctx.t, "ranking": ranking, "page": page,
            "edge_ids": sorted({e for r in ranking for e in r["edge_ids"]}),
            "method": "algo.betweenness and algo.pageRank on a copy of the graph with only the DEPENDS_ON "
                      "edges valid at incident time; owner = OWNS edge valid at incident time"}


def page_action(result: dict) -> dict | None:
    """The page action an investigation proposes, chosen by page_priority (not by the LLM)."""
    top, ranking = result.get("page"), result.get("ranking") or []
    if not top:
        return None
    people = ", ".join(f"@{p}" for p in top["people"]) or "no members on record"
    where = ("the alerted service" if top["hops"] == 0
             else f"{top['hops']} hop(s) upstream of {result['alerted_service']}")
    return {"kind": "page", "target": top["team"],
            "reason": f"{top['team']} owns {top['service']} ({where}), the biggest chokepoint in the blast radius: "
                      f"betweenness {top['betweenness']:.2f}, rank 1 of {len(ranking)} on the graph as of the "
                      f"incident. On the team: {people}."}


def centrality(ctx: ToolCtx) -> dict:
    between = db.read(ctx.tenant, queries.BETWEENNESS)
    return {"pagerank_normalised": {k: round(v, 3) for k, v in _pagerank(ctx.tenant).items()},
            "betweenness": {r["service"]: r["score"] for r in between},
            "note": "Structural importance over all dependencies ever seen (graph algorithms are not time-filtered)."}
