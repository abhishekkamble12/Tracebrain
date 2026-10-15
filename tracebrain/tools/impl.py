"""Agent tools as plain functions over the graph (used by the MCP server, baselines and tests).

Every function takes a ToolCtx that the *orchestrator* sets (tenant, incident time, ...); the LLM
only supplies the remaining arguments. All reads go through db.read (FalkorDB ro_query), and
anything derived from graph paths returns `edge_ids` so claims can cite exact edges.
Bad input raises ToolError with a message written for the LLM to recover from.
"""

from dataclasses import dataclass
from functools import lru_cache

from tracebrain import db, queries, scoring
from tracebrain.config import DEFAULT_WINDOW_S


@dataclass(frozen=True)
class ToolCtx:
    tenant: str
    t: int                           # incident time: every as-of query is evaluated here
    investigation_id: str = ""
    memory_enabled: bool = True
    window_s: int = DEFAULT_WINDOW_S


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


def centrality(ctx: ToolCtx) -> dict:
    between = db.read(ctx.tenant, queries.BETWEENNESS)
    return {"pagerank_normalised": {k: round(v, 3) for k, v in _pagerank(ctx.tenant).items()},
            "betweenness": {r["service"]: r["score"] for r in between},
            "note": "Structural importance over all dependencies ever seen (graph algorithms are not time-filtered)."}
