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
# Deploys marked rolled_back (only ever set inside a sandbox copy, see verification.py) are skipped.
SUSPECTS = f"""
MATCH p = (f:Service {{name: $svc}})-[:DEPENDS_ON*0..3]->(s:Service)
WHERE all(r IN relationships(p) WHERE {AS_OF})
WITH s, p, length(p) AS len ORDER BY len
WITH s, collect(p)[0] AS path, min(len) AS proximity
MATCH (d:Deploy)-[dr:DEPLOYED_TO]->(s)
WHERE d.ts <= $t AND d.ts >= $t - $window AND NOT coalesce(d.rolled_back, false)
OPTIONAL MATCH (a:Person)-[:AUTHORED]->(d)
RETURN d.id AS deploy, s.name AS service, s.service_type AS service_type, d.ts AS ts,
       d.change_size AS change_size, d.kind AS kind, d.summary AS summary, a.handle AS author,
       proximity, [r IN relationships(path) | id(r)] + [id(dr)] AS edge_ids
ORDER BY proximity, ts DESC"""

# Time-blind variants: the same questions over ALL edges ever seen. Used only by eval/run.py to
# measure what the as-of filter buys; never given to agents.
NAIVE_SUSPECTS = SUSPECTS.replace(f"WHERE all(r IN relationships(p) WHERE {AS_OF})\n", "")
NAIVE_OWNERS = OWNERS.replace(f" AND {AS_OF}", "")

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

# --------------------------------------------------------------------------- episodic memory + blackboard

CREATE_INVESTIGATION = """
MATCH (i:Incident {id: $incident_id})
CREATE (v:Investigation {id: $id, incident_id: $incident_id, state: 'OPEN', started: $now, updated: $now,
                         memory_enabled: $memory})
CREATE (i)-[:INVESTIGATED_IN]->(v)
SET i.status = 'investigating'
RETURN v.id AS id"""

GET_INVESTIGATION = """
MATCH (v:Investigation {id: $id})
RETURN v.id AS id, v.incident_id AS incident_id, v.state AS state, v.started AS started,
       v.updated AS updated, v.memory_enabled AS memory_enabled, v.outcome AS outcome,
       v.tool_calls AS tool_calls, v.turns AS turns, v.prompt_tokens AS prompt_tokens,
       v.completion_tokens AS completion_tokens, v.models AS models, v.faithfulness AS faithfulness,
       v.duration_ms AS duration_ms, v.resumes AS resumes"""

SET_STATE = """
MATCH (v:Investigation {id: $id})
SET v.state = $state, v.updated = $now
RETURN v.state AS state"""

ADD_STEP = """
MATCH (v:Investigation {id: $id})
CREATE (v)-[:HAS_STEP]->(s:Step {n: $n, agent: $agent, tool: $tool, args_json: $args, result_json: $result,
                                 edge_ids: $edge_ids, ms: $ms, error: $error, ts: $now})
RETURN s.n AS n"""

LINK_STEP = """
MATCH (v:Investigation {id: $id})-[:HAS_STEP]->(a:Step {n: $prev}), (v)-[:HAS_STEP]->(b:Step {n: $n})
CREATE (a)-[:NEXT]->(b)"""

STEPS = """
MATCH (v:Investigation {id: $id})-[:HAS_STEP]->(s:Step)
RETURN s.n AS n, s.agent AS agent, s.tool AS tool, s.args_json AS args_json, s.result_json AS result_json,
       s.edge_ids AS edge_ids, s.ms AS ms, s.error AS error
ORDER BY n"""

ADD_FINDING = """
MATCH (v:Investigation {id: $id})
CREATE (v)-[:PRODUCED]->(f:Finding {id: $fid, kind: $kind, agent: $agent, payload_json: $payload, ts: $now})
RETURN f.id AS id"""

FINDINGS = """
MATCH (v:Investigation {id: $id})-[:PRODUCED]->(f:Finding)
OPTIONAL MATCH (f)-[h:HANDOFF]->(v)
WITH f, collect(h.to_agent) AS handed_to
RETURN f.id AS id, f.kind AS kind, f.agent AS agent, f.payload_json AS payload_json, handed_to, f.ts AS ts
ORDER BY ts, id"""

HANDOFF = """
MATCH (v:Investigation {id: $id})-[:PRODUCED]->(f:Finding {agent: $from_agent})
CREATE (f)-[:HANDOFF {from_agent: $from_agent, to_agent: $to_agent, ts: $now}]->(v)
RETURN count(f) AS n"""

ADD_HYPOTHESIS = """
MATCH (v:Investigation {id: $id}), (d:Deploy {id: $deploy_id})
CREATE (v)-[:PROPOSED]->(h:Hypothesis {id: $hid, rank: $rank, deploy_id: $deploy_id, likely_cause: $likely_cause,
                                       summary: $summary, score: $score, features_json: $features})
CREATE (h)-[:SUSPECTS]->(d)
RETURN h.id AS id"""

ADD_CLAIM = """
MATCH (h:Hypothesis {id: $hid})
CREATE (h)-[:ASSERTS]->(c:Claim {n: $n, text: $text, edge_ids: $edge_ids, verified: $verified, reason: $reason})"""

ADD_ACTION = """
MATCH (v:Investigation {id: $id})
CREATE (v)-[:TOOK]->(a:Action {id: $aid, kind: $kind, target: $target, reason: $reason, status: 'proposed'})
WITH a
OPTIONAL MATCH (t) WHERE (t:Team AND t.name = $target) OR (t:Service AND t.name = $target)
                      OR (t:Deploy AND t.id = $target) OR (t:Person AND t.handle = $target)
FOREACH (x IN CASE WHEN t IS NULL THEN [] ELSE [t] END | CREATE (a)-[:TARGETS]->(x))
RETURN a.id AS id"""

HYPOTHESES = """
MATCH (v:Investigation {id: $id})-[:PROPOSED]->(h:Hypothesis)
OPTIONAL MATCH (h)-[:VERIFIED_BY]->(vf:Verification)
WITH h, collect({method: vf.method, environment: vf.environment, clears: vf.clears, ts: vf.ts,
                     next_suspect: vf.next_suspect, next_suspect_service: vf.next_suspect_service,
                     remaining_candidates: vf.remaining_candidates}) AS verifications
OPTIONAL MATCH (h)-[:ASSERTS]->(c:Claim)
WITH h, verifications, c ORDER BY c.n
WITH h, verifications, collect({text: c.text, edge_ids: c.edge_ids, verified: c.verified, reason: c.reason}) AS claims
RETURN h.id AS id, h.rank AS rank, h.deploy_id AS deploy_id, h.likely_cause AS likely_cause, h.summary AS summary,
       h.score AS score, h.features_json AS features_json, claims, verifications
ORDER BY rank"""

ADD_VERIFICATION = """
MATCH (h:Hypothesis {id: $hid})
CREATE (h)-[:VERIFIED_BY]->(vf:Verification {method: $method, environment: $environment, clears: $clears,
                                             sandbox: $sandbox, ts: $now, next_suspect: $next_suspect,
                                             next_suspect_service: $next_suspect_service,
                                             remaining_candidates: $remaining_candidates})
RETURN vf.clears AS clears"""

LIST_INVESTIGATIONS = """
MATCH (i:Incident)-[:INVESTIGATED_IN]->(v:Investigation)
RETURN v.id AS id, i.id AS incident_id, v.state AS state, v.outcome AS outcome, v.started AS started,
       v.updated AS updated, v.memory_enabled AS memory_enabled
ORDER BY started DESC LIMIT $limit"""

INCIDENTS_WITH_LATEST = """
MATCH (i:Incident)-[:AFFECTED]->(s:Service)
OPTIONAL MATCH (i)-[:INVESTIGATED_IN]->(v:Investigation)
WITH i, s, v ORDER BY v.started DESC
WITH i, s, collect(v)[0] AS latest
RETURN i.id AS id, i.ts AS ts, i.symptom AS symptom, i.text AS text, i.severity AS severity, i.status AS status,
       s.name AS service, latest.id AS investigation, latest.state AS investigation_state
ORDER BY ts"""

INCIDENT_BY_ID = """
MATCH (i:Incident {id: $id})-[:AFFECTED]->(s:Service)
RETURN i.id AS id, i.ts AS ts, i.symptom AS symptom, i.text AS text,
       i.severity AS severity, i.status AS status, s.name AS service"""


GRAPH_SERVICES = f"""
MATCH (s:Service)
OPTIONAL MATCH (t:Team)-[r:OWNS]->(s) WHERE {AS_OF}
RETURN s.name AS name, s.tier AS tier, s.service_type AS service_type, t.name AS team
ORDER BY name"""

GRAPH_DEPENDENCIES = f"""
MATCH (a:Service)-[r:DEPENDS_ON]->(b:Service) WHERE {AS_OF}
RETURN id(r) AS id, a.name AS src, b.name AS dst"""

GRAPH_DEPLOYS = """
MATCH (d:Deploy)-[r:DEPLOYED_TO]->(s:Service)
WHERE d.ts <= $t AND d.ts >= $t - $window
RETURN d.id AS id, s.name AS service, d.ts AS ts, d.kind AS kind, d.change_size AS change_size, id(r) AS edge_id
ORDER BY ts"""

LESSONS = """
MATCH (l:Lesson)
OPTIONAL MATCH (l)-[:ABOUT]->(c:Cause)
OPTIONAL MATCH (l)-[:LEARNED_FROM]->(i:Incident)
WITH l, c, collect(i.id) AS evidence
RETURN l.id AS id, l.symptom AS symptom, l.service AS service, l.check_first AS check_first,
       l.success_count AS success_count, l.fail_count AS fail_count, l.retracted AS retracted,
       c.name AS cause, evidence
ORDER BY id"""

ACTIONS = """
MATCH (v:Investigation {id: $id})-[:TOOK]->(a:Action)
RETURN a.id AS id, a.kind AS kind, a.target AS target, a.reason AS reason, a.status AS status
ORDER BY id"""

SET_RUN_STATS = """
MATCH (v:Investigation {id: $id})
SET v.tool_calls = $tool_calls, v.turns = $turns, v.prompt_tokens = $prompt_tokens,
    v.completion_tokens = $completion_tokens, v.models = $models, v.faithfulness = $faithfulness,
    v.claims_total = $claims_total, v.duration_ms = $duration_ms, v.abstained = $abstained,
    v.resumes = $resumes
RETURN v.id AS id"""

DEPLOY_SERVICE = """
MATCH (d:Deploy {id: $deploy_id})-[:DEPLOYED_TO]->(s:Service)
RETURN s.name AS service, d.kind AS kind"""

SET_OUTCOME = """
MATCH (v:Investigation {id: $id})-[:INVESTIGATED_IN]-(i:Incident)
SET v.outcome = $outcome, i.status = $incident_status
RETURN v.id AS id"""

# --------------------------------------------------------------------------- semantic + procedural memory

CAUSES = """
MATCH (c:Cause)
RETURN c.key AS key, c.name AS name, c.aliases AS aliases, c.confidence AS confidence,
       c.confirmations AS confirmations, c.rejections AS rejections, c.retracted AS retracted
ORDER BY key"""

UPSERT_CAUSE = """
MERGE (c:Cause {key: $key})
ON CREATE SET c.name = $name, c.aliases = [], c.confidence = 0.5, c.confirmations = 0, c.rejections = 0,
              c.retracted = false
SET c.aliases = CASE WHEN $alias IN c.aliases OR $alias = c.name THEN c.aliases ELSE c.aliases + [$alias] END
RETURN c.key AS key, c.confirmations AS confirmations, c.rejections AS rejections, c.confidence AS confidence"""

# Confirm/reject update the counters inside one query, so concurrent reviews can't lose an update.
CONFIRM_CAUSE = """
MATCH (c:Cause {key: $key})
SET c.confirmations = c.confirmations + 1
SET c.confidence = round((1 - 0.5 * 0.7 ^ c.confirmations) * 10000) / 10000.0, c.retracted = false
RETURN c.key AS key, c.confirmations AS confirmations, c.confidence AS confidence"""

REJECT_CAUSE = """
MATCH (c:Cause {key: $key})
SET c.rejections = c.rejections + 1, c.confidence = round(c.confidence * 0.5 * 10000) / 10000.0
SET c.retracted = c.confidence < $retract_below
RETURN c.key AS key, c.confidence AS confidence, c.retracted AS retracted"""

RETRACT_CAUSE = """
MATCH (c:Cause {key: $key})
SET c.retracted = true
RETURN c.key AS key"""

LINK_CAUSE = """
MATCH (i:Incident {id: $incident_id}), (c:Cause {key: $key})
MERGE (i)-[r:CAUSED_BY]->(c)
SET r.confirmed_by = $reviewer, r.ts = $now, r.confidence = $confidence, r.investigation = $investigation"""

LINK_ROOT_DEPLOY = """
MATCH (i:Incident {id: $incident_id}), (d:Deploy {id: $deploy_id})
MERGE (i)-[:ROOT_DEPLOY]->(d)"""

UPSERT_LESSON = """
MATCH (i:Incident {id: $incident_id}), (c:Cause {key: $cause_key})
MERGE (l:Lesson {id: $id})
ON CREATE SET l.symptom = $symptom, l.service = $service, l.check_first = $check_first,
              l.success_count = 0, l.fail_count = 0, l.retracted = false
SET l.success_count = l.success_count + 1
MERGE (l)-[:LEARNED_FROM]->(i)
MERGE (l)-[:ABOUT]->(c)
RETURN l.id AS id, l.success_count AS success_count, l.fail_count AS fail_count"""

FAIL_LESSONS = """
MATCH (l:Lesson {symptom: $symptom, service: $service, check_first: $check_first})
SET l.fail_count = l.fail_count + 1,
    l.retracted = l.fail_count + 1 >= l.success_count + 2
RETURN l.id AS id, l.fail_count AS fail_count, l.retracted AS retracted"""

RECALL_LESSONS = """
MATCH (l:Lesson {symptom: $symptom, service: $service})-[:LEARNED_FROM]->(i:Incident)
WHERE NOT l.retracted AND i.ts < $t
WITH l, collect(i.id) AS evidence
OPTIONAL MATCH (l)-[:ABOUT]->(c:Cause)
RETURN l.id AS id, l.check_first AS check_first, l.success_count AS success_count,
       l.fail_count AS fail_count, c.name AS cause, evidence
ORDER BY success_count - fail_count DESC LIMIT 5"""

RECALL_SIMILAR = """
MATCH (i:Incident)-[cb:CAUSED_BY]->(c:Cause)
WHERE i.ts < $t AND i.symptom = $symptom AND NOT c.retracted
MATCH (i)-[:AFFECTED]->(s:Service)
OPTIONAL MATCH (i)-[:ROOT_DEPLOY]->(d:Deploy)-[:DEPLOYED_TO]->(ds:Service)
WITH i, cb, c, s, d, ds, CASE WHEN s.name = $service THEN 0 ELSE 1 END AS other_service
RETURN i.id AS incident, s.name AS service, i.symptom AS symptom, c.name AS cause,
       round(c.confidence * 100) / 100.0 AS confidence, ds.name AS culprit_service, d.kind AS culprit_kind,
       cb.investigation AS investigation
ORDER BY other_service, i.ts DESC LIMIT $limit"""

PAST_INCIDENT_INVESTIGATION = """
MATCH (i:Incident {id: $incident_id})-[cb:CAUSED_BY]->(c:Cause)
WHERE i.ts < $t
RETURN cb.investigation AS investigation, c.name AS cause"""

INCIDENT = """
MATCH (i:Incident {id: $id})-[:TRIGGERED_BY]->(a:Alert)-[:FIRED_ON]->(s:Service)
RETURN i.id AS id, i.ts AS ts, i.symptom AS symptom, i.text AS text, i.severity AS severity,
       i.status AS status, s.name AS service, s.service_type AS service_type"""
