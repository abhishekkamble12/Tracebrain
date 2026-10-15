"""T0.2: verify which FalkorDB features Tracebrain's plan relies on actually work.

Builds a tiny temporal fixture in a throwaway graph, runs one probe per feature,
and writes docs/falkordb_capabilities.md. Run:  uv run python scripts/capability_check.py
"""

import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from tracebrain import db

G = "capcheck"
COPY = "capcheck_copy"
OUT = Path(__file__).resolve().parent.parent / "docs" / "falkordb_capabilities.md"

# frontend -> checkout -> cart -> redis ; checkout -> currency (until t=100) ; checkout -> currency2 (from t=100)
FIXTURE = """
CREATE (fe:Service {name:'frontend'}), (co:Service {name:'checkout'}), (ca:Service {name:'cart'}),
       (re:Service {name:'redis'}), (cu:Service {name:'currency'}), (cu2:Service {name:'currency2'}),
       (t:Team {name:'Platform'}), (p:Person {handle:'ravi'}),
       (d1:Deploy {id:'dep:1', ts:90, change_size:40, kind:'config'}),
       (d2:Deploy {id:'dep:2', ts:95, change_size:5, kind:'code'}),
       (fe)-[:DEPENDS_ON {valid_from:0, valid_to:4102444800}]->(co),
       (co)-[:DEPENDS_ON {valid_from:0, valid_to:4102444800}]->(ca),
       (ca)-[:DEPENDS_ON {valid_from:0, valid_to:4102444800}]->(re),
       (co)-[:DEPENDS_ON {valid_from:0, valid_to:100}]->(cu),
       (co)-[:DEPENDS_ON {valid_from:100, valid_to:4102444800}]->(cu2),
       (t)-[:OWNS {valid_from:0, valid_to:4102444800}]->(re),
       (p)-[:MEMBER_OF]->(t),
       (d1)-[:DEPLOYED_TO]->(re), (d2)-[:DEPLOYED_TO]->(fe)
"""

AS_OF = "r.valid_from <= $t AND r.valid_to > $t"

PROBES: list[tuple[str, str, str, dict]] = [
    # (key, description, cypher, params). Expected outcome is noted in the description.
    ("varlen_all_filter",
     "Var-length path + all() over relationships (as-of filter). Expect currency at t=50, currency2 at t=150 upstream of checkout's deps",
     f"MATCH p=(:Service {{name:'checkout'}})-[:DEPENDS_ON*1..3]->(s:Service) "
     f"WHERE all(r IN relationships(p) WHERE {AS_OF}) RETURN collect(DISTINCT s.name) AS deps",
     {"t": 50}),
    ("varlen_all_filter_t150", "Same at t=150 (topology changed)",
     f"MATCH p=(:Service {{name:'checkout'}})-[:DEPENDS_ON*1..3]->(s:Service) "
     f"WHERE all(r IN relationships(p) WHERE {AS_OF}) RETURN collect(DISTINCT s.name) AS deps",
     {"t": 150}),
    ("blast_radius_full",
     "Full BLAST_RADIUS query from IMPLEMENTATION.md (min(length), collect(p)[0], edge ids)",
     f"MATCH p = (up:Service)-[:DEPENDS_ON*1..5]->(f:Service {{name: $svc}}) "
     f"WHERE all(r IN relationships(p) WHERE {AS_OF}) "
     f"WITH up, min(length(p)) AS hops, collect(p)[0] AS path "
     f"RETURN up.name AS service, hops, [r IN relationships(path) | id(r)] AS edge_ids ORDER BY hops",
     {"svc": "redis", "t": 50}),
    ("suspects_full",
     "Full SUSPECTS query (0..3 hops, window filter, edge ids incl. DEPLOYED_TO)",
     f"MATCH p = (f:Service {{name: $svc}})-[:DEPENDS_ON*0..3]->(s:Service) "
     f"WHERE all(r IN relationships(p) WHERE {AS_OF}) "
     f"WITH s, min(length(p)) AS proximity, collect(p)[0] AS path "
     f"MATCH (d:Deploy)-[dr:DEPLOYED_TO]->(s) WHERE d.ts <= $t AND d.ts >= $t - $window "
     f"RETURN d.id AS deploy, s.name AS service, proximity, "
     f"[r IN relationships(path) | id(r)] + [id(dr)] AS edge_ids",
     {"svc": "checkout", "t": 99, "window": 50}),
    ("shortest_path_plain", "shortestPath() without WHERE",
     "MATCH (a:Service {name:'frontend'}), (b:Service {name:'redis'}) "
     "MATCH p = shortestPath((a)-[:DEPENDS_ON*..6]->(b)) RETURN [n IN nodes(p) | n.name] AS path",
     {}),
    ("shortest_path_where", "shortestPath() + WHERE all() as-of filter",
     f"MATCH (a:Service {{name:'frontend'}}), (b:Service {{name:'currency2'}}) "
     f"MATCH p = shortestPath((a)-[:DEPENDS_ON*..6]->(b)) WHERE all(r IN relationships(p) WHERE {AS_OF}) "
     f"RETURN [n IN nodes(p) | n.name] AS path",
     {"t": 150}),
    ("algo_sppaths", "algo.SPpaths procedure",
     "MATCH (a:Service {name:'frontend'}), (b:Service {name:'redis'}) "
     "CALL algo.SPpaths({sourceNode: a, targetNode: b, relTypes: ['DEPENDS_ON'], maxLen: 6}) "
     "YIELD path RETURN [n IN nodes(path) | n.name] AS path",
     {}),
    ("algo_bfs", "algo.BFS procedure",
     "MATCH (a:Service {name:'frontend'}) CALL algo.BFS(a, 3, 'DEPENDS_ON') YIELD nodes "
     "RETURN [n IN nodes | n.name] AS reached",
     {}),
    ("algo_pagerank", "algo.pageRank procedure",
     "CALL algo.pageRank('Service', 'DEPENDS_ON') YIELD node, score RETURN node.name AS svc, score ORDER BY score DESC",
     {}),
    ("algo_betweenness", "algo.betweenness procedure",
     "CALL algo.betweenness({nodeLabels: ['Service'], relationshipTypes: ['DEPENDS_ON']}) "
     "YIELD node, score RETURN node.name AS svc, score ORDER BY score DESC",
     {}),
    ("algo_wcc", "algo.WCC procedure",
     "CALL algo.WCC({nodeLabels: ['Service'], relationshipTypes: ['DEPENDS_ON']}) "
     "YIELD node, componentId RETURN componentId, collect(node.name) AS members",
     {}),
    ("algo_labelprop", "algo.labelPropagation (community detection)",
     "CALL algo.labelPropagation({nodeLabels: ['Service'], relationshipTypes: ['DEPENDS_ON']}) "
     "YIELD node, communityId RETURN communityId, collect(node.name) AS members",
     {}),
    ("edge_lookup_by_id", "Look up edges by id(r) IN $ids (faithfulness checker)",
     "MATCH (a)-[r]->(b) WHERE id(r) IN $ids "
     "RETURN id(r) AS id, type(r) AS type, coalesce(a.name, a.id) AS src, coalesce(b.name, b.id) AS dst",
     {"ids": [0, 1, 2]}),
    ("list_property", "List-valued properties + IN on list param",
     "MERGE (c:Cause {key:'db_timeout'}) SET c.aliases = ['db timeout', 'database timeouts'] "
     "RETURN c.aliases AS aliases, 'db timeout' IN c.aliases AS hit",
     {}),
    ("merge_on_create_match", "MERGE ... ON CREATE SET / ON MATCH SET (counters)",
     "MERGE (l:Lesson {id:'L1'}) ON CREATE SET l.success_count = 1 ON MATCH SET l.success_count = l.success_count + 1 "
     "RETURN l.success_count AS n",
     {}),
]


def probe_vector(g) -> tuple[bool, str]:
    g.query("CREATE VECTOR INDEX FOR (i:Incident) ON (i.embedding) OPTIONS {dimension:3, similarityFunction:'cosine'}")
    g.query("CREATE (:Incident {id:'inc:1', embedding: vecf32([1.0, 0.0, 0.0])}), "
            "(:Incident {id:'inc:2', embedding: vecf32([0.0, 1.0, 0.0])})")
    res = g.ro_query("CALL db.idx.vector.queryNodes('Incident', 'embedding', 2, vecf32($v)) "
                     "YIELD node, score RETURN node.id AS id, score", {"v": [0.9, 0.1, 0.0]})
    return True, json.dumps(db.rows(res))


def probe_ro_query_blocks_writes(g) -> tuple[bool, str]:
    try:
        g.ro_query("CREATE (:Service {name:'should_not_exist'})")
    except Exception as e:  # expected
        return True, f"write rejected: {type(e).__name__}: {e}"
    return False, "ro_query ALLOWED a write (unsafe; must enforce elsewhere)"


def probe_copy(g) -> tuple[bool, str]:
    client = db.client()
    try:
        client.select_graph(COPY).delete()
    except Exception:
        pass
    if hasattr(g, "copy"):
        g.copy(COPY)
        how = "Graph.copy()"
    else:
        client.connection.execute_command("GRAPH.COPY", G, COPY)
        how = "GRAPH.COPY command"
    n = client.select_graph(COPY).ro_query("MATCH (s:Service) RETURN count(s)").result_set[0][0]
    client.select_graph(COPY).delete()
    return True, f"{how} ok; copied {n} services"


def probe_list_graphs(_g) -> tuple[bool, str]:
    return True, json.dumps(db.client().list_graphs())


def run() -> int:
    client = db.client()
    g = client.select_graph(G)
    try:
        g.delete()
    except Exception:
        pass
    g.query(FIXTURE)

    results: list[tuple[str, str, bool, str]] = []
    for key, desc, q, params in PROBES:
        try:
            out = db.rows(g.query(q, params))
            results.append((key, desc, True, json.dumps(out, default=str)))
        except Exception as e:
            results.append((key, desc, False, f"{type(e).__name__}: {e}"))

    for key, desc, fn in [
        ("vector_index", "Vector index + db.idx.vector.queryNodes", probe_vector),
        ("ro_query_blocks_writes", "ro_query rejects writes (read-only enforcement)", probe_ro_query_blocks_writes),
        ("graph_copy", "Copy a graph (sandbox for rollback verification)", probe_copy),
        ("list_graphs", "Multigraph listing (one graph per tenant)", probe_list_graphs),
    ]:
        try:
            ok, out = fn(g)
        except Exception as e:
            ok, out = False, f"{type(e).__name__}: {e}"
        results.append((key, desc, ok, out))

    version = "unknown"
    try:
        mods = client.connection.execute_command("MODULE", "LIST")
        version = str(mods)
    except Exception:
        pass
    g.delete()

    lines = [
        "# FalkorDB capability check (T0.2)",
        "",
        f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC} by `scripts/capability_check.py`.",
        f"Server modules: `{version}`",
        "",
        "| Probe | What it checks | Result | Output / error |",
        "|---|---|---|---|",
    ]
    for key, desc, ok, out in results:
        out = out.replace("|", "\\|").replace("\n", " ")
        if len(out) > 300:
            out = out[:300] + "…"
        lines.append(f"| `{key}` | {desc} | {'✅' if ok else '❌'} | {out} |")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    for key, _desc, ok, out in results:
        print(f"{'OK  ' if ok else 'FAIL'} {key:26s} {out[:160]}")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(run())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
