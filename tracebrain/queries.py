"""Every Cypher query Tracebrain runs, as named constants (single source for the README).

Conventions
- Time is epoch seconds. `$t` is the incident time; temporal edges carry valid_from/valid_to
  (valid_to = config.FOREVER when open-ended), so "as of t" is `valid_from <= t < valid_to`.
- Path-derived results always return `edge_ids` (FalkorDB id(r)) so claims can cite exact edges.
- Ordering by path length goes through `WITH ..., length(p) AS len` first: FalkorDB can't ORDER BY
  length(p) directly after RETURN, and its shortestPath() ignores edge properties (see
  docs/falkordb_capabilities.md), so shortest paths are var-length + as-of filter + LIMIT 1.
"""

AS_OF = "r.valid_from <= $t AND r.valid_to > $t"

# --------------------------------------------------------------------------- schema

INDEXES = [
    "CREATE INDEX FOR (s:Service) ON (s.name)",
    "CREATE INDEX FOR (t:Team) ON (t.name)",
    "CREATE INDEX FOR (p:Person) ON (p.handle)",
    "CREATE INDEX FOR (d:Deploy) ON (d.id)",
    "CREATE INDEX FOR (d:Deploy) ON (d.ts)",
    "CREATE INDEX FOR (a:Alert) ON (a.id)",
    "CREATE INDEX FOR (i:Incident) ON (i.id)",
    "CREATE INDEX FOR (v:Investigation) ON (v.id)",
    "CREATE INDEX FOR (c:Cause) ON (c.key)",
    "CREATE INDEX FOR (l:Lesson) ON (l.id)",
    "CREATE INDEX FOR (l:Lesson) ON (l.symptom)",
]

EMBEDDING_DIM = 384  # all-MiniLM-L6-v2
VECTOR_INDEXES = [
    f"CREATE VECTOR INDEX FOR (i:Incident) ON (i.embedding) OPTIONS {{dimension:{EMBEDDING_DIM}, similarityFunction:'cosine'}}",
    f"CREATE VECTOR INDEX FOR (c:Cause) ON (c.embedding) OPTIONS {{dimension:{EMBEDDING_DIM}, similarityFunction:'cosine'}}",
]

# --------------------------------------------------------------------------- ingestion (idempotent upserts)

UPSERT_SERVICES = """
UNWIND $rows AS r
MERGE (s:Service {name: r.name})
SET s.tier = r.tier, s.service_type = r.service_type"""

UPSERT_DEPENDENCIES = """
UNWIND $rows AS r
MATCH (a:Service {name: r.src}), (b:Service {name: r.dst})
MERGE (a)-[e:DEPENDS_ON {valid_from: r.valid_from}]->(b)
SET e.valid_to = r.valid_to"""

UPSERT_OWNERSHIP = """
UNWIND $rows AS r
MATCH (s:Service {name: r.service})
MERGE (t:Team {name: r.team})
MERGE (t)-[o:OWNS {valid_from: r.valid_from}]->(s)
SET o.valid_to = r.valid_to"""

UPSERT_MEMBERS = """
UNWIND $rows AS r
MERGE (t:Team {name: r.team})
MERGE (p:Person {handle: r.handle})
MERGE (p)-[:MEMBER_OF]->(t)"""

UPSERT_DEPLOYS = """
UNWIND $rows AS r
MATCH (s:Service {name: r.service})
MERGE (d:Deploy {id: r.id})
SET d.ts = r.ts, d.change_size = r.change_size, d.kind = r.kind, d.summary = r.summary
MERGE (d)-[:DEPLOYED_TO]->(s)
MERGE (p:Person {handle: r.author})
MERGE (p)-[:AUTHORED]->(d)"""

UPSERT_INCIDENTS = """
UNWIND $rows AS r
MATCH (s:Service {name: r.service})
MERGE (a:Alert {id: 'alert:' + r.id})
SET a.ts = r.ts, a.symptom = r.symptom, a.message = r.text
MERGE (a)-[:FIRED_ON]->(s)
MERGE (i:Incident {id: r.id})
SET i.ts = r.ts, i.severity = r.severity, i.symptom = r.symptom, i.text = r.text,
    i.status = coalesce(i.status, 'open')
MERGE (i)-[:TRIGGERED_BY]->(a)
MERGE (i)-[:AFFECTED]->(s)"""

# --------------------------------------------------------------------------- world-graph reads (agent tools)

# Who is hurt if $svc fails at time $t: every service that (transitively) depends on it.
BLAST_RADIUS = f"""
MATCH p = (up:Service)-[:DEPENDS_ON*1..5]->(f:Service {{name: $svc}})
WHERE all(r IN relationships(p) WHERE {AS_OF})
WITH up, p, length(p) AS len ORDER BY len
WITH up, collect(p)[0] AS path, min(len) AS hops
RETURN up.name AS service, hops, [r IN relationships(path) | id(r)] AS edge_ids
ORDER BY hops, service"""

# The same question answered against ALL edges ever seen: what a non-temporal tool would say.
# Used only to demonstrate/evaluate why as-of matters; never given to agents.
NAIVE_BLAST_RADIUS = """
MATCH p = (up:Service)-[:DEPENDS_ON*1..5]->(f:Service {name: $svc})
WITH up, min(length(p)) AS hops
RETURN up.name AS service, hops ORDER BY hops, service"""

OWNERS = f"""
MATCH (t:Team)-[r:OWNS]->(s:Service)
WHERE s.name IN $services AND {AS_OF}
OPTIONAL MATCH (p:Person)-[:MEMBER_OF]->(t)
RETURN s.name AS service, t.name AS team, collect(p.handle) AS people, id(r) AS edge_id
ORDER BY service"""

# Deploys inside [t - window, t] on the failing service or anything it depends on (<= 3 hops) at t.
SUSPECTS = f"""
MATCH p = (f:Service {{name: $svc}})-[:DEPENDS_ON*0..3]->(s:Service)
WHERE all(r IN relationships(p) WHERE {AS_OF})
WITH s, p, length(p) AS len ORDER BY len
WITH s, collect(p)[0] AS path, min(len) AS proximity
MATCH (d:Deploy)-[dr:DEPLOYED_TO]->(s)
WHERE d.ts <= $t AND d.ts >= $t - $window
OPTIONAL MATCH (a:Person)-[:AUTHORED]->(d)
RETURN d.id AS deploy, s.name AS service, s.service_type AS service_type, d.ts AS ts,
       d.change_size AS change_size, d.kind AS kind, d.summary AS summary, a.handle AS author,
       proximity, [r IN relationships(path) | id(r)] + [id(dr)] AS edge_ids
ORDER BY proximity, ts DESC"""

SHORTEST_PATH = f"""
MATCH p = (a:Service {{name: $a}})-[:DEPENDS_ON*1..6]->(b:Service {{name: $b}})
WHERE all(r IN relationships(p) WHERE {AS_OF})
WITH p, length(p) AS len ORDER BY len LIMIT 1
RETURN [n IN nodes(p) | n.name] AS services, [r IN relationships(p) | id(r)] AS edge_ids"""

SERVICE_FAIL_COUNTS = """
MATCH (s:Service)<-[:AFFECTED]-(i:Incident)
WHERE s.name IN $services AND i.ts < $t
RETURN s.name AS service, count(i) AS n"""

SERVICE_NAMES = "MATCH (s:Service) RETURN s.name AS name ORDER BY name"

# Time-agnostic structural priors (FalkorDB algorithms don't filter on edge properties).
PAGERANK = """
CALL algo.pageRank('Service', 'DEPENDS_ON') YIELD node, score
RETURN node.name AS service, score ORDER BY score DESC"""

BETWEENNESS = """
CALL algo.betweenness({nodeLabels: ['Service'], relationshipTypes: ['DEPENDS_ON']}) YIELD node, score
RETURN node.name AS service, score ORDER BY score DESC"""

# Faithfulness checker: resolve cited edge ids to (type, src, dst).
EDGE_LOOKUP = """
MATCH (a)-[r]->(b) WHERE id(r) IN $ids
RETURN id(r) AS id, type(r) AS type, coalesce(a.name, a.handle, a.id) AS src,
       coalesce(b.name, b.handle, b.id) AS dst"""

INCIDENT = """
MATCH (i:Incident {id: $id})-[:TRIGGERED_BY]->(a:Alert)-[:FIRED_ON]->(s:Service)
RETURN i.id AS id, i.ts AS ts, i.symptom AS symptom, i.text AS text, i.severity AS severity,
       i.status AS status, s.name AS service, s.service_type AS service_type"""

LIST_INCIDENTS = """
MATCH (i:Incident)-[:AFFECTED]->(s:Service)
RETURN i.id AS id, i.ts AS ts, i.symptom AS symptom, i.status AS status, s.name AS service
ORDER BY ts"""
