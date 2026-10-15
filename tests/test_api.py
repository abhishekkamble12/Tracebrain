"""HTTP API end to end: start -> live SSE stream -> review -> memory, plus resume and alerts."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from test_orchestrator import Policy, incidents_of, world  # noqa: F401  (fixture re-export)
from test_resume_verify import CrashOn, env_for
from tracebrain.api.main import app


@pytest.fixture
def api(world):
    tenant, w = world
    saved = (app.state.chat_fn, app.state.environment, app.state.judge)
    app.state.environment = env_for(tenant, w)
    app.state.judge = None
    with TestClient(app) as client:
        yield client, tenant, w
    app.state.chat_fn, app.state.environment, app.state.judge = saved


def wait_for(client, url, states, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(url).json()
        if body["state"] in states:
            return body
        time.sleep(0.1)
    raise AssertionError(f"timed out; last state {body['state']}")


def sse_events(client, url):
    events, kind = [], None
    with client.stream("GET", url) as r:
        for line in r.iter_lines():
            if line.startswith("event:"):
                kind = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                events.append((kind, json.loads(line.split(":", 1)[1])))
    return events


def test_investigate_stream_review_memory(api):
    client, tenant, w = api
    iid, truth = incidents_of(w, "timeout")[0]
    app.state.chat_fn = Policy(truth["service"], pick=truth["culprit_deploy"])

    assert tenant in client.get("/tenants").json()
    assert any(i["id"] == iid for i in client.get(f"/tenants/{tenant}/incidents").json())
    started = client.post(f"/tenants/{tenant}/incidents/{iid}/investigate", json={"memory_enabled": True}).json()
    inv_id = started["investigation_id"]
    base = f"/tenants/{tenant}/investigations/{inv_id}"
    full = wait_for(client, base, {"AWAITING_REVIEW"})
    assert full["hypotheses"][0]["deploy_id"] == truth["culprit_deploy"]
    assert full["hypotheses"][0]["verifications"][0]["clears"] is True

    kinds = [k for k, _ in sse_events(client, started["events"])]
    assert kinds[0] == "started" and kinds[-1] == "done"
    assert {"step", "handoff", "state", "hypotheses", "verification"} <= set(kinds)

    review = client.post(f"{base}/review", json={"verdict": "confirm", "reviewer": "asha"}).json()
    assert review["lesson"]["success_count"] == 1
    assert client.post(f"{base}/review", json={"verdict": "confirm", "reviewer": "asha"}).status_code == 409
    mem = client.get(f"/tenants/{tenant}/memory").json()
    assert mem["lessons"][0]["check_first"] == truth["culprit_service"] and mem["causes"]

    g = client.get(f"/tenants/{tenant}/graph", params={"t": truth["ts"]}).json()
    cited = {e for c in full["hypotheses"][0]["claims"] for e in c["edge_ids"]}
    assert cited <= {e["id"] for e in g["edges"]}  # every cited edge can be highlighted in the UI


def test_resume_over_http(api):
    client, tenant, w = api
    iid, truth = incidents_of(w, "timeout")[0]
    app.state.chat_fn = CrashOn(Policy(truth["service"]), "investigator", nth=2)
    inv_id = client.post(f"/tenants/{tenant}/incidents/{iid}/investigate").json()["investigation_id"]
    base = f"/tenants/{tenant}/investigations/{inv_id}"
    wait_for(client, base, {"FAILED"})
    app.state.chat_fn = Policy(truth["service"])
    assert client.post(f"{base}/resume").json()["from_state"] == "FAILED"
    assert wait_for(client, base, {"AWAITING_REVIEW", "VERIFIED"})["resumes"] == 1
    assert client.post(f"{base}/resume").status_code == 409


def test_alert_webhook_and_tenant_checks(api):
    client, tenant, w = api
    assert client.get("/tenants/nope/incidents").status_code == 404
    bad = client.post(f"/tenants/{tenant}/alerts", json={"service": "nope", "symptom": "latency", "text": "x"})
    assert bad.status_code == 422
    app.state.chat_fn = Policy("checkout")
    out = client.post(f"/tenants/{tenant}/alerts", json={
        "service": "checkout", "symptom": "timeout", "text": "checkout requests timing out",
        "ts": incidents_of(w, "timeout")[0][1]["ts"], "auto_investigate": True}).json()
    assert out["incident_id"].startswith("inc:live-")
    body = wait_for(client, f"/tenants/{tenant}/investigations/{out['investigation_id']}",
                    {"AWAITING_REVIEW", "VERIFIED"})
    assert body["incident_id"] == out["incident_id"]
