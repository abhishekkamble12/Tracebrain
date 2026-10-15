"""Temporal correctness of the core queries on a tiny hand-checkable graph.

    frontend -> checkout -> cart -> redis
    checkout -> currency   (t < 100)
    checkout -> currency2  (t >= 100)
    cart owned by TeamA until t=100, then TeamB
"""

import pytest

from tracebrain import db, queries
from tracebrain.config import FOREVER
from tracebrain.connectors.base import DependencyRec, DeployRec, OwnershipRec, ServiceRec
from tracebrain.ingest import ingest


class Tiny:
    name = "tiny"

    def services(self):
        return [ServiceRec(n) for n in ("frontend", "checkout", "cart", "redis", "currency", "currency2")]

    def dependencies(self):
        return [DependencyRec("frontend", "checkout", 0), DependencyRec("checkout", "cart", 0),
                DependencyRec("cart", "redis", 0), DependencyRec("checkout", "currency", 0, 100),
                DependencyRec("checkout", "currency2", 100)]

    def ownership(self):
        return [OwnershipRec("Platform", "redis", ("ravi",)), OwnershipRec("TeamA", "cart", ("ann",), 0, 100),
                OwnershipRec("TeamB", "cart", ("bob",), 100, FOREVER)]

    def deploys(self, since, until):
        return [DeployRec("dep:1", "redis", 90, 40, "config", "ravi", "update redis configuration"),
                DeployRec("dep:2", "frontend", 95, 5, "code", "ann", "release frontend build 2")]

    def incidents(self):
        return []


@pytest.fixture
def tiny(temp_tenant):
    ingest(temp_tenant, Tiny())
    return temp_tenant


def names(rows, key="service"):
    return [r[key] for r in rows]


def test_blast_radius_hops_and_edges(tiny):
    rows = db.read(tiny, queries.BLAST_RADIUS, {"svc": "redis", "t": 50})
    assert [(r["service"], r["hops"]) for r in rows] == [("cart", 1), ("checkout", 2), ("frontend", 3)]
    assert all(len(r["edge_ids"]) == r["hops"] for r in rows)


def test_blast_radius_respects_time(tiny):
    assert names(db.read(tiny, queries.BLAST_RADIUS, {"svc": "currency", "t": 50})) == ["checkout", "frontend"]
    assert db.read(tiny, queries.BLAST_RADIUS, {"svc": "currency", "t": 150}) == []
    # The naive query still blames the retired dependency: the error as-of queries prevent.
    assert names(db.read(tiny, queries.NAIVE_BLAST_RADIUS, {"svc": "currency"})) == ["checkout", "frontend"]


def test_suspects_window_and_direction(tiny):
    rows = db.read(tiny, queries.SUSPECTS, {"svc": "checkout", "t": 99, "window": 50})
    # dep:2 is newer but on frontend, a caller of checkout, so it is not a suspect.
    assert [(r["deploy"], r["service"], r["proximity"]) for r in rows] == [("dep:1", "redis", 2)]
    assert len(rows[0]["edge_ids"]) == 3  # checkout->cart, cart->redis, DEPLOYED_TO
    assert db.read(tiny, queries.SUSPECTS, {"svc": "checkout", "t": 99, "window": 5}) == []


def test_shortest_path_as_of(tiny):
    q, p = queries.SHORTEST_PATH, {"a": "frontend"}
    assert db.read(tiny, q, {**p, "b": "currency", "t": 50})[0]["services"] == ["frontend", "checkout", "currency"]
    assert db.read(tiny, q, {**p, "b": "currency", "t": 150}) == []
    assert db.read(tiny, q, {**p, "b": "currency2", "t": 50}) == []


def test_owners_as_of(tiny):
    at = lambda t: [(r["team"], r["people"]) for r in db.read(tiny, queries.OWNERS, {"services": ["cart"], "t": t})]
    assert at(50) == [("TeamA", ["ann"])]
    assert at(150) == [("TeamB", ["bob"])]


def test_edge_lookup_resolves_cited_edges(tiny):
    edge_ids = db.read(tiny, queries.SUSPECTS, {"svc": "checkout", "t": 99, "window": 50})[0]["edge_ids"]
    rows = db.read(tiny, queries.EDGE_LOOKUP, {"ids": edge_ids})
    got = {(r["type"], r["src"], r["dst"]) for r in rows}
    assert got == {("DEPENDS_ON", "checkout", "cart"), ("DEPENDS_ON", "cart", "redis"),
                   ("DEPLOYED_TO", "dep:1", "redis")}


def test_read_path_rejects_writes(tiny):
    with pytest.raises(Exception):
        db.read(tiny, "CREATE (:Service {name: 'sneaky'})")


def test_ingest_is_idempotent(tiny):
    ingest(tiny, Tiny())
    counts = db.read(tiny, "MATCH ()-[r]->() RETURN type(r) AS t, count(r) AS n ORDER BY t")
    assert {r["t"]: r["n"] for r in counts}["DEPENDS_ON"] == 5
