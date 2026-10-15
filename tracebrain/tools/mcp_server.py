"""Tracebrain MCP server: graph tools for incident investigation.

Tenant isolation by construction: the tenant and incident time are NOT tool arguments. Tracebrain's
orchestrator sends them as MCP request metadata (`tracebrain/tenant`, `tracebrain/t`, ...), so the
LLM never sees or chooses them. External MCP clients (Claude Desktop, Cursor, Inspector) that send
no metadata get TRACEBRAIN_DEFAULT_TENANT and the current time.

    uv run python -m tracebrain.tools.mcp_server            # stdio
    uv run python -m tracebrain.tools.mcp_server --http     # streamable HTTP on :8765/mcp
"""

import argparse
import os
import time

from mcp.server.mcpserver import Context, MCPServer

from tracebrain.tools import impl
from tracebrain.tools.impl import ToolCtx, ToolError

META_TENANT = "tracebrain/tenant"
META_T = "tracebrain/t"
META_INVESTIGATION = "tracebrain/investigation"
META_MEMORY = "tracebrain/memory"
META_SYMPTOM = "tracebrain/symptom"
META_SERVICE = "tracebrain/service"
META_AGENT = "tracebrain/agent"

server = MCPServer(
    "tracebrain",
    instructions="Graph tools over a temporal service-dependency graph (FalkorDB). All answers are "
                 "evaluated at the incident time. Cite the returned edge_ids for every factual claim.",
)


def tool_ctx(ctx: Context) -> ToolCtx:
    meta = ctx.request_context.meta or {}
    tenant = meta.get(META_TENANT) or os.getenv("TRACEBRAIN_DEFAULT_TENANT")
    if not tenant:
        raise ToolError("no tenant in request metadata and TRACEBRAIN_DEFAULT_TENANT is not set")
    return ToolCtx(tenant=str(tenant), t=int(meta.get(META_T) or time.time()),
                   investigation_id=str(meta.get(META_INVESTIGATION) or ""),
                   memory_enabled=bool(meta.get(META_MEMORY, True)),
                   symptom=str(meta.get(META_SYMPTOM) or ""), service=str(meta.get(META_SERVICE) or ""),
                   agent=str(meta.get(META_AGENT) or ""))


def _run(fn, ctx: Context, *args, **kwargs) -> dict:
    try:
        return fn(tool_ctx(ctx), *args, **kwargs)
    except ToolError as e:
        return {"error": str(e)}


@server.tool()
def get_incident(incident_id: str, ctx: Context) -> dict:
    """Details of an incident: alerted service, symptom, time, severity and alert text."""
    return _run(impl.get_incident, ctx, incident_id)


@server.tool()
def blast_radius(service: str, ctx: Context, max_hops: int = 5) -> dict:
    """Services affected if `service` fails: everything that depends on it (directly or transitively)
    at incident time, with hop counts and the dependency edge_ids of each path."""
    return _run(impl.blast_radius, ctx, service, max_hops)


@server.tool()
def owners_of(services: list[str], ctx: Context) -> dict:
    """Owning team and its people for each service, as of incident time (ownership changes over time)."""
    return _run(impl.owners_of, ctx, services)


@server.tool()
def suspects(service: str, ctx: Context, window_hours: float | None = None, limit: int = 10) -> dict:
    """Ranked suspect deploys for an incident on `service`: deploys in the look-back window on the
    service itself or anything it depends on at incident time. Each suspect has a deterministic score,
    its feature breakdown (proximity, recency, change_size, fail_rate, centrality, lesson_match),
    and the edge_ids of the dependency path + deploy edge that connect it to the alerted service."""
    return _run(impl.suspects, ctx, service, window_hours, limit)


@server.tool()
def path_between(from_service: str, to_service: str, ctx: Context) -> dict:
    """Shortest dependency path from one service to another at incident time, with edge_ids
    (null if no path existed then)."""
    return _run(impl.path_between, ctx, from_service, to_service)


@server.tool()
def centrality(ctx: Context) -> dict:
    """Structural importance of each service (PageRank, betweenness). Time-agnostic prior only."""
    return _run(impl.centrality, ctx)


@server.tool()
def write_finding(kind: str, payload: dict, ctx: Context) -> dict:
    """Record a finding on this investigation's shared blackboard so the next agent can use it.
    kind: blast_radius | owners | similar_incidents | note. Include the edge_ids that support it."""
    return _run(impl.write_finding, ctx, kind, payload)


@server.tool()
def read_findings(ctx: Context) -> dict:
    """Read the findings earlier agents recorded on this investigation's blackboard."""
    return _run(impl.read_findings, ctx)


@server.tool()
def recall_similar(ctx: Context, limit: int = 5) -> dict:
    """Memory: earlier human-confirmed incidents with the same symptom (same service first), with their
    confirmed cause and culprit service. Summaries only."""
    return _run(impl.recall_similar, ctx, limit)


@server.tool()
def recall_lessons(ctx: Context, service: str | None = None) -> dict:
    """Memory: confirmed lessons for this symptom on the alerted service, e.g. 'check redis-cart first',
    with success/fail counts. Lessons also boost matching suspects' lesson_match score."""
    return _run(impl.recall_lessons, ctx, service)


@server.tool()
def get_past_investigation(incident_id: str, ctx: Context) -> dict:
    """Memory, details on demand: the confirmed investigation of one earlier incident (tool sequence,
    hypotheses and verified claims). Use after recall_similar shows it is relevant."""
    return _run(impl.get_past_investigation, ctx, incident_id)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", action="store_true", help="serve streamable HTTP instead of stdio")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    if args.http:
        server.run("streamable-http", port=args.port)
    else:
        server.run("stdio")


if __name__ == "__main__":
    main()
