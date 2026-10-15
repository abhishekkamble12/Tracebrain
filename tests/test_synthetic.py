"""The synthetic world is solvable, leak-free, and its Cypher answers match an independent
Python implementation of the same temporal topology."""

import pytest

from tracebrain import db, queries
from tracebrain.config import DEFAULT_WINDOW_S
from tracebrain.connectors.synthetic import (CURRENCY_SWITCH_DAY, DAY, T0, SyntheticConnector, TENANTS,
                                             build_world, leakage_violations)
from tracebrain.ingest import ingest


@pytest.mark.parametrize("tenant", list(TENANTS))
def test_world_is_deterministic_and_leak_free(tenant):
    a, b = build_world(tenant), build_world(tenant)
    assert a.truth == b.truth and a.deploys == b.deploys
    assert leakage_violations(a) == []
    assert len(a.incidents) == 26
    assert sum(t["split"] == "seen" for t in a.truth.values()) == 6


def test_temporal_change_is_exercised():
    truth = build_world("payments").truth.values()
    switch = T0 + CURRENCY_SWITCH_DAY * DAY
    culprits = {t["culprit_service"] for t in truth if t["type"] == "error_rate"}
    assert culprits == {"currency", "currency-v2"}
    assert any(t["type"] == "error_rate" and t["ts"] >= switch for t in truth)


@pytest.fixture(scope="module")
def seeded(falkor):
    import uuid
    from tracebrain import schema
    tenant = f"test_{uuid.uuid4().hex[:8]}"
    schema.apply(tenant)
    conn = SyntheticConnector("payments")
    ingest(tenant, conn)
    yield tenant, conn.world
    schema.drop(tenant)


def test_cypher_blast_radius_matches_python(seeded):
    tenant, world = seeded
    for iid, t in world.truth.items():
        rows = db.read(tenant, queries.BLAST_RADIUS, {"svc": t["service"], "t": t["ts"]})
        assert sorted(r["service"] for r in rows) == t["blast_radius"], iid


def test_culprit_is_always_a_suspect_and_abstentions_have_none(seeded):
    tenant, world = seeded
    for iid, t in world.truth.items():
        rows = db.read(tenant, queries.SUSPECTS, {"svc": t["service"], "t": t["ts"], "window": DEFAULT_WINDOW_S})
        found = {r["deploy"] for r in rows}
        if t["culprit_deploy"] is None:
            assert found == set(), iid
        else:
            assert t["culprit_deploy"] in found, iid


@pytest.mark.parametrize("tenant", list(TENANTS))
def test_benchmark_difficulty_is_realistic(tenant):
    """B0 (latest deploy anywhere in the window) should be right sometimes but not mostly, and the
    graph alone (newest deploy among as-of suspects) should beat it without solving everything,
    so ranking and memory have room to show value."""
    from tracebrain.connectors.synthetic import closure_at
    world = build_world(tenant)
    b0 = graph_newest = total = 0
    for t in world.truth.values():
        if t["culprit_deploy"] is None:
            continue
        window = [d for d in world.deploys if t["ts"] - DEFAULT_WINDOW_S <= d.ts <= t["ts"]]
        suspects = [d for d in window if d.service in closure_at(t["service"], t["ts"])]
        total += 1
        b0 += max(window, key=lambda d: d.ts).id == t["culprit_deploy"]
        graph_newest += max(suspects, key=lambda d: d.ts).id == t["culprit_deploy"]
    assert 0.10 <= b0 / total <= 0.45, f"B0 {b0}/{total}"
    assert b0 < graph_newest and graph_newest / total <= 0.80, f"graph-newest {graph_newest}/{total}"
