"""Tool functions and the MCP server against a seeded synthetic tenant."""

import json
import uuid

import anyio
import pytest
from mcp import Client

from tracebrain import db, schema
from tracebrain.connectors.synthetic import SyntheticConnector
from tracebrain.ingest import ingest
from tracebrain.tools import impl, mcp_server
from tracebrain.tools.impl import ToolCtx, ToolError


@pytest.fixture(scope="module")
def world(falkor):
    tenants = {name: f"test_{uuid.uuid4().hex[:8]}" for name in ("payments", "platform")}
    worlds = {}
    for name, tenant in tenants.items():
        schema.apply(tenant)
        conn = SyntheticConnector(name)
        ingest(tenant, conn)
        worlds[name] = (tenant, conn.world)
    impl._pagerank.cache_clear()
    yield worlds
    for tenant in tenants.values():
        schema.drop(tenant)


def first_incident(world, kind):
    tenant, w = world["payments"]
    iid, truth = next((k, v) for k, v in w.truth.items() if v["type"] == kind)
    return ToolCtx(tenant, truth["ts"]), iid, truth


def test_suspects_contain_culprit_with_scores_and_edges(world):
    ctx, iid, truth = first_incident(world, "timeout")
    out = impl.suspects(ctx, truth["service"])
    ids = [s["deploy"] for s in out["suspects"]]
    assert truth["culprit_deploy"] in ids
    top = out["suspects"][0]
    assert set(top["features"]) == {"proximity", "recency", "change_size", "fail_rate", "centrality", "lesson_match"}
    assert top["edge_ids"] and top["rank"] == 1
    assert [s["score"] for s in out["suspects"]] == sorted((s["score"] for s in out["suspects"]), reverse=True)


def test_unknown_service_is_a_helpful_error(world):
    ctx, _, _ = first_incident(world, "timeout")
    with pytest.raises(ToolError, match="Known services"):
        impl.blast_radius(ctx, "chekout")


def test_blast_radius_and_owners(world):
    ctx, _, truth = first_incident(world, "timeout")
    br = impl.blast_radius(ctx, "checkout")
    assert sorted(a["service"] for a in br["affected"]) == truth["blast_radius"]
    owners = impl.owners_of(ctx, ["checkout", "redis-cart"])
    assert {o["service"] for o in owners["owners"]} == {"checkout", "redis-cart"} and owners["edge_ids"]


def test_get_incident(world):
    ctx, iid, truth = first_incident(world, "crashloop")
    inc = impl.get_incident(ctx, iid)
    assert inc["service"] == truth["service"] and inc["symptom"] == "crashloop"


# ------------------------------------------------------------------ MCP protocol level

def _call(tool, args, meta):
    async def go():
        async with Client(mcp_server.server) as c:
            r = await c.call_tool(tool, args, meta=meta)
            return json.loads(r.content[0].text)
    return anyio.run(go)


def test_mcp_schemas_hide_tenant_and_time(falkor):
    async def go():
        async with Client(mcp_server.server) as c:
            return (await c.list_tools()).tools
    tools = anyio.run(go)
    assert {t.name for t in tools} >= {"get_incident", "blast_radius", "owners_of", "suspects", "path_between", "centrality"}
    for t in tools:
        props = t.input_schema.get("properties", {})
        assert not {"ctx", "tenant", "t"} & set(props), (t.name, props)


def test_mcp_call_uses_meta_tenant_and_time(world):
    ctx, iid, truth = first_incident(world, "timeout")
    out = _call("suspects", {"service": truth["service"]}, {mcp_server.META_TENANT: ctx.tenant, mcp_server.META_T: ctx.t})
    assert truth["culprit_deploy"] in [s["deploy"] for s in out["suspects"]]


def test_mcp_tenant_isolation(world):
    """The same incident id asked under another tenant's metadata returns that tenant's data only."""
    pay_tenant, pay = world["payments"]
    plat_tenant, plat = world["platform"]
    iid = "inc:001"
    a = _call("get_incident", {"incident_id": iid}, {mcp_server.META_TENANT: pay_tenant, mcp_server.META_T: 0})
    b = _call("get_incident", {"incident_id": iid}, {mcp_server.META_TENANT: plat_tenant, mcp_server.META_T: 0})
    assert a["ts"] == pay.truth[iid]["ts"] and b["ts"] == plat.truth[iid]["ts"] and a["ts"] != b["ts"]
    owners = _call("owners_of", {"services": ["payment"]}, {mcp_server.META_TENANT: plat_tenant, mcp_server.META_T: 0})
    assert {o["team"] for o in owners["owners"]} <= {"Platform", "Data", "Web"}


def test_mcp_errors_are_returned_not_raised(world):
    ctx, _, _ = first_incident(world, "timeout")
    out = _call("blast_radius", {"service": "nope"}, {mcp_server.META_TENANT: ctx.tenant, mcp_server.META_T: ctx.t})
    assert "unknown service" in out["error"]


def test_page_priority_ranks_blast_radius_by_asof_betweenness(world):
    """An algorithm, not the LLM, picks who is paged: betweenness on a time-sliced copy of the graph."""
    tenant, w = world["payments"]
    iid, truth = next((k, v) for k, v in sorted(w.truth.items()) if v["service"] == "payment")
    ctx = ToolCtx(tenant, truth["ts"])
    out = impl.page_priority(ctx, "payment")
    ranked = [r["service"] for r in out["ranking"]]
    assert sorted(ranked) == sorted(["payment", *truth["blast_radius"]])
    assert [r["betweenness"] for r in out["ranking"]] == sorted((r["betweenness"] for r in out["ranking"]),
                                                                reverse=True)
    # payment is a leaf; checkout, which calls it, is the chokepoint: its owner then is paged.
    assert out["page"]["service"] == "checkout" and out["page"]["service"] != "payment"
    (owner,) = [o for o in impl.owners_of(ctx, ["checkout"])["owners"]]
    assert out["page"]["team"] == owner["team"] and owner["edge_id"] in out["page"]["edge_ids"]
    action = impl.page_action(out)
    assert action["target"] == owner["team"] and "betweenness 1.00" in action["reason"]
    # The time-sliced copy is thrown away; the live graph keeps every edge.
    assert not [g for g in db.client().list_graphs() if "__asof_" in g]
