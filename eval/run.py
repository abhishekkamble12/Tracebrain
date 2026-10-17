"""Deterministic evaluation: does the graph (and its time-awareness, and memory) pick the right deploy?

    uv run python eval/run.py            # needs FalkorDB; no LLM key, no tokens

Seeds its own throwaway graphs (`tenant_eval_<tenant>`) from the synthetic connector, so the demo
tenants are never touched, and drops them at the end. Writes eval/results.json, which the API
serves at GET /results and the UI shows on the Results page.

What is measured is the suspect ranking the Investigator agent receives (tools/impl.py::suspects),
not the LLM's final choice: that keeps the numbers reproducible and free. Methods:

- latest_anywhere / latest_on_alerted_service / largest_change: no graph, just the deploy table.
- graph_time_blind: same scoring, but dependency paths ignore valid_from/valid_to.
- graph_as_of: the real tool, memory off.
- graph_as_of_with_memory: the real tool after a human confirmed every earlier incident
  (Lesson write-back exactly as the curator does it, replayed in time order).
"""

import json
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

from tracebrain import db, queries, schema, scoring
from tracebrain.config import DEFAULT_WINDOW_S
from tracebrain.connectors.synthetic import TENANTS, SyntheticConnector
from tracebrain.ingest import ingest
from tracebrain.memory import procedural, semantic
from tracebrain.tools import impl
from tracebrain.tools.impl import ToolCtx

OUT = Path(__file__).resolve().parent / "results.json"
W = DEFAULT_WINDOW_S
METHODS = ["latest_anywhere", "latest_on_alerted_service", "largest_change", "graph_time_blind",
           "graph_as_of", "graph_as_of_with_memory"]


def window_deploys(tenant: str, t: int) -> list[dict]:
    return db.read(tenant, """
        MATCH (d:Deploy)-[:DEPLOYED_TO]->(s:Service) WHERE d.ts <= $t AND d.ts >= $t - $w
        RETURN d.id AS id, d.ts AS ts, d.change_size AS size, s.name AS service""", {"t": t, "w": W})


def time_blind_ranking(tenant: str, svc: str, t: int) -> list[dict]:
    rows = db.read(tenant, queries.NAIVE_SUSPECTS, {"svc": svc, "t": t, "window": W})
    fails = {r["service"]: r["n"] for r in db.read(
        tenant, queries.SERVICE_FAIL_COUNTS, {"services": sorted({r["service"] for r in rows}), "t": t})}
    return scoring.rank(rows, t, W, fails, impl._pagerank(tenant))


def teach(tenant: str, iid: str, inc: dict, truth: dict, top_service: str | None) -> None:
    """What curator.review(verdict='confirm') writes, without needing a full investigation."""
    cause = semantic.upsert(tenant, truth["cause_key"].replace("_", " "), judge=None)
    semantic.confirm(tenant, cause["key"])
    db.write(tenant, queries.LINK_ROOT_DEPLOY, {"incident_id": iid, "deploy_id": truth["culprit_deploy"]})
    procedural.learn(tenant, iid, inc["symptom"], inc["service"], truth["culprit_service"], cause["key"])
    if top_service and top_service != truth["culprit_service"]:
        procedural.penalise(tenant, inc["symptom"], inc["service"], top_service)


def evaluate(base: str) -> tuple[list[dict], dict]:
    tenant = f"eval_{base}"
    conn = SyntheticConnector(base)
    schema.drop(tenant)
    schema.apply(tenant)
    ingest(tenant, conn)
    truth = conn.world.truth
    deploy_role = {d: r for tr in truth.values() for d, r in tr["decoys"].items()}
    out, extra = [], defaultdict(int)
    for iid, tr in sorted(truth.items(), key=lambda kv: kv[1]["ts"]):
        inc = impl.get_incident(ToolCtx(tenant, 0), iid)
        t, svc = inc["ts"], inc["service"]
        off = ToolCtx(tenant, t, memory_enabled=False, symptom=inc["symptom"], service=svc)
        on = ToolCtx(tenant, t, memory_enabled=True, symptom=inc["symptom"], service=svc)

        # Time-awareness beyond ranking: blast radius and owners, as-of vs time-blind.
        asof_blast = {r["service"] for r in db.read(tenant, queries.BLAST_RADIUS, {"svc": svc, "t": t})}
        naive_blast = {r["service"] for r in db.read(tenant, queries.NAIVE_BLAST_RADIUS, {"svc": svc})}
        extra["blast_radius_differs"] += asof_blast != naive_blast
        involved = sorted({svc, *asof_blast})
        asof_own = {(r["service"], r["team"]) for r in db.read(tenant, queries.OWNERS, {"services": involved, "t": t})}
        naive_own = {(r["service"], r["team"]) for r in db.read(tenant, queries.NAIVE_OWNERS, {"services": involved})}
        extra["owners_time_blind_adds_wrong_team"] += bool(naive_own - asof_own)

        window = window_deploys(tenant, t)
        asof = impl.suspects(off, svc, limit=100)["suspects"]
        blind = time_blind_ranking(tenant, svc, t)
        if tr["culprit_deploy"] is None:
            extra["abstain_incidents"] += 1
            extra["abstain_correct_as_of"] += not asof       # no suspect -> the agent must abstain
            extra["abstain_correct_time_blind"] += not blind
            continue

        with_mem = impl.suspects(on, svc, limit=100)["suspects"]
        same_svc = [d for d in window if d["service"] == svc]
        ranked = {
            "latest_anywhere": [d["id"] for d in sorted(window, key=lambda d: -d["ts"])],
            "latest_on_alerted_service": [d["id"] for d in sorted(same_svc, key=lambda d: -d["ts"])],
            "largest_change": [d["id"] for d in sorted(window, key=lambda d: (-d["size"], -d["ts"]))],
            "graph_time_blind": [r["deploy"] for r in blind],
            "graph_as_of": [r["deploy"] for r in asof],
            "graph_as_of_with_memory": [r["deploy"] for r in with_mem],
        }
        row = {"tenant": base, "incident": iid, "split": tr["split"], "culprit": tr["culprit_deploy"],
               "window_deploys": len(window), "as_of_candidates": len(asof), "time_blind_candidates": len(blind),
               "time_blind_top_is_stale_decoy": bool(blind) and deploy_role.get(blind[0]["deploy"]) == "decoy_stale",
               "stale_decoy_in_window": "decoy_stale" in tr["decoys"].values()}
        for m, ids in ranked.items():
            row[m] = ids.index(tr["culprit_deploy"]) + 1 if tr["culprit_deploy"] in ids else None
        out.append(row)
        teach(tenant, iid, inc, tr, with_mem[0]["service"] if with_mem else None)
    return out, extra


def summarise(rows: list[dict]) -> dict:
    n = len(rows)
    res = {}
    for m in METHODS:
        ranks = [r[m] for r in rows]
        res[m] = {"incidents": n, "top1": sum(x == 1 for x in ranks), "top3": sum(x is not None and x <= 3 for x in ranks),
                  "top1_rate": round(sum(x == 1 for x in ranks) / n, 3) if n else None,
                  "mrr": round(sum(1 / x for x in ranks if x) / n, 3) if n else None,
                  "culprit_never_ranked": sum(x is None for x in ranks)}
    return res


def main() -> int:
    t0 = time.time()
    rows, extra = [], defaultdict(int)
    try:
        for base in TENANTS:
            r, e = evaluate(base)
            rows += r
            for k, v in e.items():
                extra[k] += v
    finally:
        for base in TENANTS:
            schema.drop(f"eval_{base}")

    stale = [r for r in rows if r["stale_decoy_in_window"]]
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    except OSError:
        commit = ""
    total_incidents = len(rows) + extra["abstain_incidents"]
    results = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "commit": commit,
        "dataset": {"tenants": len(TENANTS), "incidents": total_incidents, "with_culprit_deploy": len(rows),
                    "no_deploy_at_fault": extra["abstain_incidents"], "llm_calls": 0},
        "ranking_all_incidents": summarise(rows),
        "ranking_repeat_incidents_only": summarise([r for r in rows if r["split"] == "test"]),
        "time_awareness": {
            "incidents_with_stale_dependency_decoy": len(stale),
            "time_blind_ranks_stale_decoy_first": sum(r["time_blind_top_is_stale_decoy"] for r in stale),
            "as_of_top1_on_those": sum(r["graph_as_of"] == 1 for r in stale),
            "time_blind_top1_on_those": sum(r["graph_time_blind"] == 1 for r in stale),
            "time_blind_ranks_culprit_lower": sum((r["graph_time_blind"] or 99) > (r["graph_as_of"] or 99) for r in rows),
            "time_blind_ranks_culprit_higher": sum((r["graph_time_blind"] or 99) < (r["graph_as_of"] or 99) for r in rows),
            "incidents_where_owner_lookup_differs": extra["owners_time_blind_adds_wrong_team"],
            "incidents_where_blast_radius_differs": extra["blast_radius_differs"],
        },
        "candidate_narrowing": {
            "mean_deploys_in_window": round(sum(r["window_deploys"] for r in rows) / len(rows), 2),
            "mean_time_blind_candidates": round(sum(r["time_blind_candidates"] for r in rows) / len(rows), 2),
            "mean_as_of_candidates": round(sum(r["as_of_candidates"] for r in rows) / len(rows), 2),
        },
        "abstention": {
            "no_deploy_incidents": extra["abstain_incidents"],
            "as_of_graph_returns_no_suspects": extra["abstain_correct_as_of"],
            "time_blind_graph_returns_no_suspects": extra["abstain_correct_time_blind"],
        },
        "runtime_s": round(time.time() - t0, 1),
    }
    OUT.write_text(json.dumps(results, indent=1), encoding="utf-8")
    (OUT.parent / "per_incident.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(json.dumps({k: results[k] for k in ("ranking_all_incidents", "ranking_repeat_incidents_only",
                                              "time_awareness", "abstention")}, indent=1))
    print(f"-> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
