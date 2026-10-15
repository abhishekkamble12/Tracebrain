# FalkorDB capability check (T0.2)

Generated 2026-10-15 10:32 UTC by `scripts/capability_check.py`.
Server modules: `[['name', 'graph', 'ver', 42201, 'path', '/var/lib/falkordb/bin/falkordb.so', 'args', ['MAX_QUEUED_QUERIES', '25', 'TIMEOUT', '1000', 'RESULTSET_SIZE', '10000']], ['name', 'vectorset', 'ver', 1, 'path', '', 'args', []]]`

| Probe | What it checks | Result | Output / error |
|---|---|---|---|
| `varlen_all_filter` | Var-length path + all() over relationships (as-of filter). Expect currency at t=50, currency2 at t=150 upstream of checkout's deps | ✅ | [{"deps": ["currency", "cart", "redis"]}] |
| `varlen_all_filter_t150` | Same at t=150 (topology changed) | ✅ | [{"deps": ["currency2", "cart", "redis"]}] |
| `blast_radius_full` | Full BLAST_RADIUS query from IMPLEMENTATION.md (min(length), collect(p)[0], edge ids) | ✅ | [{"service": "cart", "hops": 1, "edge_ids": [2]}, {"service": "checkout", "hops": 2, "edge_ids": [1, 2]}, {"service": "frontend", "hops": 3, "edge_ids": [0, 1, 2]}] |
| `suspects_full` | Full SUSPECTS query (0..3 hops, window filter, edge ids incl. DEPLOYED_TO) | ✅ | [{"deploy": "dep:1", "service": "redis", "proximity": 2, "edge_ids": [1, 2, 7]}] |
| `shortest_path_plain` | shortestPath() without WHERE | ❌ | ResponseError: FalkorDB currently only supports shortestPaths in WITH or RETURN clauses |
| `shortest_path_where` | shortestPath() + WHERE all() as-of filter | ❌ | ResponseError: FalkorDB currently only supports shortestPaths in WITH or RETURN clauses |
| `algo_sppaths` | algo.SPpaths procedure | ✅ | [{"path": ["frontend", "checkout", "cart", "redis"]}] |
| `algo_bfs` | algo.BFS procedure | ✅ | [{"reached": ["checkout", "cart", "redis", "currency", "currency2"]}] |
| `algo_pagerank` | algo.pageRank procedure | ✅ | [{"svc": "redis", "score": 0.167336702346802}, {"svc": "checkout", "score": 0.134859398007393}, {"svc": "cart", "score": 0.111104220151901}, {"svc": "currency", "score": 0.111104220151901}, {"svc": "currency2", "score": 0.111104220151901}, {"svc": "frontend", "score": 0.0728982612490654}] |
| `algo_betweenness` | algo.betweenness procedure | ✅ | [{"svc": "cart", "score": 3.0}, {"svc": "frontend", "score": 0.0}, {"svc": "checkout", "score": 0.0}, {"svc": "redis", "score": 0.0}, {"svc": "currency", "score": 0.0}, {"svc": "currency2", "score": 0.0}] |
| `algo_wcc` | algo.WCC procedure | ✅ | [{"componentId": 0, "members": ["frontend", "checkout", "cart", "redis", "currency", "currency2"]}] |
| `algo_labelprop` | algo.labelPropagation (community detection) | ✅ | [{"communityId": 0, "members": ["frontend", "cart", "currency", "currency2"]}, {"communityId": 1, "members": ["checkout", "redis"]}] |
| `edge_lookup_by_id` | Look up edges by id(r) IN $ids (faithfulness checker) | ✅ | [{"id": 0, "type": "DEPENDS_ON", "src": "frontend", "dst": "checkout"}, {"id": 1, "type": "DEPENDS_ON", "src": "checkout", "dst": "cart"}, {"id": 2, "type": "DEPENDS_ON", "src": "cart", "dst": "redis"}] |
| `list_property` | List-valued properties + IN on list param | ✅ | [{"aliases": ["db timeout", "database timeouts"], "hit": true}] |
| `merge_on_create_match` | MERGE ... ON CREATE SET / ON MATCH SET (counters) | ✅ | [{"n": 1}] |
| `vector_index` | Vector index + db.idx.vector.queryNodes | ✅ | [{"id": "inc:1", "score": 0.00611627101898193}, {"id": "inc:2", "score": 0.889568448066711}] |
| `ro_query_blocks_writes` | ro_query rejects writes (read-only enforcement) | ✅ | write rejected: ResponseError: graph.RO_QUERY is to be executed only on read-only queries |
| `graph_copy` | Copy a graph (sandbox for rollback verification) | ✅ | Graph.copy() ok; copied 6 services |
| `list_graphs` | Multigraph listing (one graph per tenant) | ✅ | ["capcheck"] |

## Follow-up probes and decisions

| Finding | Impact | Decision |
|---|---|---|
| `shortestPath()` is only allowed in `WITH`/`RETURN`, not `MATCH`. In `WITH` it works but **ignores `valid_from/valid_to`**: at t=50 it returned `frontend→checkout→currency2`, a dependency that didn't exist yet | Using it would give stale-topology answers, the exact error Tracebrain exists to prevent | `SHORTEST_PATH` uses var-length + as-of `all()` filter + `WITH p, length(p) AS len ORDER BY len LIMIT 1`. Verified: `currency` reachable at t=50 only, `currency2` at t=150 only |
| `ORDER BY length(p)` directly after `RETURN` fails (`Unable to locate a value with alias p`) | Query-writing gotcha | Always project `length(p) AS len` in a `WITH` before ordering |
| `algo.SPpaths`, `algo.BFS`, `algo.pageRank`, `algo.betweenness`, `algo.WCC`, `algo.labelPropagation` all work, but none filter by edge properties | Graph algorithms see the union of all-time topology | Use them only as time-agnostic priors (the centrality score feature, community view in the UI). All time-critical logic stays in as-of Cypher. State this in the README |
| Vector `queryNodes` `score` is a **distance** (0 = identical): the near-identical vector scored 0.006 | Thresholds in IMPLEMENTATION.md §6.2 were written as similarity | Entity resolution: merge if distance ≤ 0.15, ask the LLM if 0.15–0.30, else new Cause |
| `ro_query` rejects writes | Read-only enforcement comes for free | All agent-reachable tools use `db.read()` → `ro_query` |
| `Graph.copy()` works | Sandbox for rollback verification (T1.7d) is feasible natively | Use `copy()` to a throwaway graph, apply the rollback, re-evaluate, delete |
| `SUSPECTS` correctly excluded a newer deploy on `frontend` (a caller, not a dependency of `checkout`) | The decoy logic works as designed | Keep as-is |
