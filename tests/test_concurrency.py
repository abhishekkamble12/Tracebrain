"""Many investigations at once across both tenants, then their reviews at once, the way the API runs them:
investigations as concurrent tasks on one event loop (LLM calls on worker threads), reviews on worker threads.
Checks that no run's steps, findings, hypotheses or memory leak into another run or tenant, and that no
memory update is lost."""

import random
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import anyio
import pytest

from test_orchestrator import Policy
from tracebrain import db, orchestrator, schema
from tracebrain.agents import curator
from tracebrain.connectors.synthetic import SyntheticConnector
from tracebrain.ingest import ingest
from tracebrain.memory import episodic
from tracebrain.tools import impl

PER_TENANT = 10


class Jittery(Policy):
    """A scripted policy with LLM-like latency, so the runs genuinely interleave."""

    def __call__(self, messages, tools):
        time.sleep(random.uniform(0.0, 0.05))
        return super().__call__(messages, tools)


@pytest.fixture(scope="module")
def tenants(falkor):
    out = {}
    for name in ("payments", "platform"):
        tenant = f"test_{uuid.uuid4().hex[:8]}"
        schema.apply(tenant)
        conn = SyntheticConnector(name)
        ingest(tenant, conn)
        out[tenant] = conn.world
    impl._pagerank.cache_clear()
    yield out
    for tenant in out:
        schema.drop(tenant)


def test_parallel_investigations_and_reviews_do_not_interfere(tenants):
    jobs = []  # (tenant, incident id, truth)
    for tenant, w in tenants.items():
        picked = [(k, v) for k, v in sorted(w.truth.items()) if v.get("culprit_deploy")][:PER_TENANT]
        jobs += [(tenant, k, v) for k, v in picked]
    assert len(jobs) == 2 * PER_TENANT

    inv_ids: dict[int, str] = {}

    async def one(i, tenant, iid, truth):
        inv_ids[i] = await orchestrator.investigate(
            tenant, iid, chat_fn=Jittery(truth["service"], pick=truth["culprit_deploy"]), environment=None)

    async def all_runs():
        async with anyio.create_task_group() as tg:
            for i, job in enumerate(jobs):
                tg.start_soon(one, i, *job)

    anyio.run(all_runs)

    for i, (tenant, iid, truth) in enumerate(jobs):
        full = episodic.full(tenant, inv_ids[i])
        assert full["state"] == "AWAITING_REVIEW" and full["incident_id"] == iid
        # The episodic chain is intact: steps 1..n, one NEXT per consecutive pair, nothing from other runs.
        assert [s["n"] for s in full["steps"]] == list(range(1, len(full["steps"]) + 1))
        assert db.read(tenant, "MATCH (:Investigation {id:$id})-[:HAS_STEP]->()-[:NEXT]->() RETURN count(*) AS n",
                       {"id": inv_ids[i]})[0]["n"] == len(full["steps"]) - 1
        assert all(s["args"].get("service", truth["service"]) == truth["service"] for s in full["steps"])
        # Blackboard: exactly this run's two findings, handed to the investigator.
        assert [a["kind"] for a in full["actions"]] == ["rollback_proposal", "page"]
        assert sorted(f["kind"] for f in full["findings"]) == ["blast_radius", "owners", "page_priority"]
        assert all(f["handed_to"] == ["investigator"] for f in full["findings"])
        (h,) = full["hypotheses"]
        assert h["deploy_id"] == truth["culprit_deploy"] and all(c["verified"] for c in h["claims"])

    # Every step, finding and investigation belongs to exactly one investigation, in its own tenant only.
    for tenant in tenants:
        mine = {inv_ids[i] for i, j in enumerate(jobs) if j[0] == tenant}
        assert {r["id"] for r in db.read(tenant, "MATCH (v:Investigation) RETURN v.id AS id")} == mine
        assert db.read(tenant, "MATCH (s:Step)<-[:HAS_STEP]-(v:Investigation) WITH s, count(v) AS n "
                               "WHERE n <> 1 RETURN count(s) AS bad")[0]["bad"] == 0
        assert db.read(tenant, "MATCH (s:Step) WHERE NOT ()-[:HAS_STEP]->(s) RETURN count(s) AS n")[0]["n"] == 0

    # All 20 human confirmations at once. Each confirms the same cause text, so per tenant the Cause must
    # count every confirmation (no lost update) and stay a single node (no duplicate from a racing MERGE).
    def review(i):
        tenant = jobs[i][0]
        return curator.review(tenant, inv_ids[i], "confirm", reviewer="asha", judge=None)

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        outs = list(pool.map(review, range(len(jobs))))
    assert all(o["verdict"] == "confirm" for o in outs)

    for tenant in tenants:
        mine = [i for i, j in enumerate(jobs) if j[0] == tenant]
        assert all(episodic.get(tenant, inv_ids[i])["state"] == "LEARNED" for i in mine)
        (cause,) = db.read(tenant, "MATCH (c:Cause) RETURN c.confirmations AS n")
        assert cause["n"] == PER_TENANT
        lessons = db.read(tenant, "MATCH (l:Lesson) RETURN sum(l.success_count) AS n, count(l) AS lessons")[0]
        assert lessons["n"] == PER_TENANT
        assert db.read(tenant, "MATCH (i:Incident)-[:CAUSED_BY]->() RETURN count(DISTINCT i) AS n")[0]["n"] \
            == len({jobs[i][1] for i in mine})
