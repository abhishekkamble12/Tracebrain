"""Tracebrain HTTP API: start/resume investigations, stream them live (SSE), review, inspect memory.

    uv run uvicorn tracebrain.api.main:app --reload --port 8000

Tenant is a path segment and maps to its own FalkorDB graph; every read/write is scoped to it.
"""

import asyncio
import json
import re
import time
import uuid
from pathlib import Path
from typing import Literal

import anyio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from tracebrain import db, llm, orchestrator, queries
from tracebrain.agents import curator
from tracebrain.events import EventBus
from tracebrain.memory import episodic, semantic

app = FastAPI(title="Tracebrain", description="Evidence-backed root-cause analysis across time, on FalkorDB.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.state.bus = EventBus()
app.state.chat_fn = llm.chat                         # tests swap in a scripted policy
app.state.environment = orchestrator.DEFAULT_ENV     # rollback-verification environment
app.state.judge = semantic.llm_judge                 # entity-resolution fallback
app.state.results_path = Path(__file__).resolve().parents[2] / "eval" / "results.json"  # written by the eval
_tasks: set[asyncio.Task] = set()
TENANT_RE = re.compile(r"^[a-z0-9_]{1,64}$")


# ------------------------------------------------------------------ helpers

def tenants() -> list[str]:
    prefix = "tenant_"
    return sorted(g[len(prefix):] for g in db.client().list_graphs()
                  if g.startswith(prefix) and "__sandbox_" not in g)


def check_tenant(tenant: str) -> str:
    if not TENANT_RE.match(tenant) or tenant not in tenants():
        raise HTTPException(404, f"unknown tenant {tenant!r}")
    return tenant


def check_investigation(tenant: str, inv_id: str) -> dict:
    try:
        return episodic.get(tenant, inv_id)
    except KeyError:
        raise HTTPException(404, f"unknown investigation {inv_id!r}")


def spawn(tenant: str, inv_id: str) -> None:
    bus: EventBus = app.state.bus
    task = asyncio.create_task(orchestrator.run(
        tenant, inv_id, chat_fn=app.state.chat_fn, environment=app.state.environment,
        on_event=lambda kind, data: bus.publish(inv_id, kind, data)), name=inv_id)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


# ------------------------------------------------------------------ models

class InvestigateReq(BaseModel):
    memory_enabled: bool = True


class ReviewReq(BaseModel):
    verdict: Literal["confirm", "reject"]
    reviewer: str = Field(min_length=1)
    deploy_id: str | None = None
    cause_text: str | None = None


class AlertReq(BaseModel):
    """Alertmanager-style webhook payload (flattened)."""
    service: str
    symptom: str
    text: str
    severity: str = "sev2"
    ts: int | None = None
    auto_investigate: bool = False
    memory_enabled: bool = True


# ------------------------------------------------------------------ routes

@app.get("/health")
def health() -> dict:
    providers = []
    try:
        providers = [p.name for p in llm.available_providers()]
    except RuntimeError:
        pass
    try:
        falkordb, error = db.ping(), None
    except Exception as e:  # unreachable, or a plain Redis on that port
        falkordb, error = False, str(e)
    out = {"falkordb": falkordb, "llm_providers": providers, "running": len(_tasks)}
    if error:
        out["falkordb_error"] = error
    return out


@app.get("/results")
def results() -> dict:
    """Evaluation results as written by the eval harness; 404 until it has run (the UI never shows
    placeholder numbers)."""
    path: Path = app.state.results_path
    if not path.exists():
        raise HTTPException(404, f"no evaluation results yet ({path.name} not found)")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/tenants")
def list_tenants() -> list[str]:
    return tenants()


@app.get("/tenants/{tenant}/incidents")
def list_incidents(tenant: str) -> list[dict]:
    return db.read(check_tenant(tenant), queries.INCIDENTS_WITH_LATEST)


@app.post("/tenants/{tenant}/incidents/{incident_id}/investigate")
async def start_investigation(tenant: str, incident_id: str, req: InvestigateReq | None = None) -> dict:
    check_tenant(tenant)
    try:
        inv_id = orchestrator.start(tenant, incident_id, (req or InvestigateReq()).memory_enabled)
    except ValueError as e:
        raise HTTPException(404, str(e))
    spawn(tenant, inv_id)
    return {"investigation_id": inv_id, "events": f"/tenants/{tenant}/investigations/{inv_id}/events"}


@app.get("/tenants/{tenant}/investigations")
def list_investigations(tenant: str, limit: int = 50) -> list[dict]:
    return episodic.list_investigations(check_tenant(tenant), limit)


@app.get("/tenants/{tenant}/investigations/{inv_id}")
def get_investigation(tenant: str, inv_id: str) -> dict:
    check_tenant(tenant)
    check_investigation(tenant, inv_id)
    out = episodic.full(tenant, inv_id)
    out["running"] = any(not t.done() and t.get_name() == inv_id for t in _tasks)
    inc_rows = db.read(tenant, queries.INCIDENT_BY_ID, {"id": out["incident_id"]})
    out["incident"] = inc_rows[0] if inc_rows else None
    return out


@app.post("/tenants/{tenant}/investigations/{inv_id}/resume")
async def resume_investigation(tenant: str, inv_id: str) -> dict:
    check_tenant(tenant)
    inv = check_investigation(tenant, inv_id)
    if inv["state"] in episodic.TERMINAL:
        raise HTTPException(409, f"{inv_id} is {inv['state']}; nothing to resume")
    if any(not t.done() and t.get_name() == inv_id for t in _tasks):
        raise HTTPException(409, f"{inv_id} is already running")
    spawn(tenant, inv_id)
    return {"investigation_id": inv_id, "from_state": inv["state"]}


@app.get("/tenants/{tenant}/investigations/{inv_id}/events")
async def stream_events(tenant: str, inv_id: str, after: int = 0):
    check_tenant(tenant)
    check_investigation(tenant, inv_id)
    bus: EventBus = app.state.bus

    async def gen():
        async for ev in bus.subscribe(inv_id, after_seq=after):
            yield {"event": ev["kind"], "id": str(ev["seq"]), "data": json.dumps(ev["data"], default=str)}

    return EventSourceResponse(gen(), ping=15)


@app.post("/tenants/{tenant}/investigations/{inv_id}/review")
async def review(tenant: str, inv_id: str, req: ReviewReq) -> dict:
    check_tenant(tenant)
    check_investigation(tenant, inv_id)
    try:
        out = await anyio.to_thread.run_sync(lambda: curator.review(
            tenant, inv_id, req.verdict, req.reviewer, req.deploy_id, req.cause_text, judge=app.state.judge))
    except curator.ReviewError as e:
        raise HTTPException(409, str(e))
    app.state.bus.publish(inv_id, "reviewed", out)
    return out


@app.get("/tenants/{tenant}/graph")
def graph(tenant: str, t: int | None = None, window_hours: float = 24) -> dict:
    """Services, as-of dependencies (with edge ids, for highlighting cited paths) and recent deploys."""
    check_tenant(tenant)
    t = t if t is not None else int(time.time())
    p = {"t": t, "window": int(window_hours * 3600)}
    services = db.read(tenant, queries.GRAPH_SERVICES, p)
    deps = db.read(tenant, queries.GRAPH_DEPENDENCIES, p)
    deploys = db.read(tenant, queries.GRAPH_DEPLOYS, p)
    nodes = [{"id": s["name"], "type": "service", **s} for s in services]
    nodes += [{"id": d["id"], "type": "deploy", **d} for d in deploys]
    edges = [{"id": d["id"], "source": d["src"], "target": d["dst"], "type": "DEPENDS_ON"} for d in deps]
    edges += [{"id": d["edge_id"], "source": d["id"], "target": d["service"], "type": "DEPLOYED_TO"} for d in deploys]
    return {"as_of": t, "nodes": nodes, "edges": edges}


@app.get("/tenants/{tenant}/memory")
def memory(tenant: str) -> dict:
    check_tenant(tenant)
    return {"causes": semantic.all_causes(tenant), "lessons": db.read(tenant, queries.LESSONS)}


@app.post("/tenants/{tenant}/causes/{key}/retract")
def retract_cause(tenant: str, key: str) -> dict:
    check_tenant(tenant)
    try:
        semantic.retract(tenant, key)
    except StopIteration:
        raise HTTPException(404, f"unknown cause {key!r}")
    return {"key": key, "retracted": True}


@app.post("/tenants/{tenant}/alerts")
async def alert(tenant: str, req: AlertReq) -> dict:
    """Webhook for live alerts (e.g. an Alertmanager/Grafana contact point): creates an incident and can
    start investigating it immediately."""
    check_tenant(tenant)
    known = {r["name"] for r in db.read(tenant, queries.SERVICE_NAMES)}
    if req.service not in known:
        raise HTTPException(422, f"unknown service {req.service!r}")
    incident_id = f"inc:live-{uuid.uuid4().hex[:8]}"
    db.write(tenant, queries.UPSERT_INCIDENTS, {"rows": [{
        "id": incident_id, "ts": req.ts or int(time.time()), "service": req.service, "symptom": req.symptom,
        "text": req.text, "severity": req.severity}]})
    out: dict = {"incident_id": incident_id}
    if req.auto_investigate:
        out["investigation_id"] = orchestrator.start(tenant, incident_id, req.memory_enabled)
        spawn(tenant, out["investigation_id"])
    return out
