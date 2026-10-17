# Tracebrain: Implementation Plan

## Progress (updated Oct 15)
| Done | Tasks | Notes |
|---|---|---|
| ✅ | T0.1-T0.7 | Scaffold, FalkorDB capability check, schema + queries, connectors + synthetic world + seed, tools + scoring, MCP server (2.x, context via request meta), agent loop |
| ✅ | T1.1, T1.2, T1.4, T1.5, T1.5b, T1.6, T1.7, T1.7b, T1.7c | Episodic steps + NEXT chain, findings blackboard + HANDOFF, Triage/Investigator, evidence gate in `submit_hypotheses`, causes (entity resolution) + lessons + recall + progressive disclosure, orchestrator + state machine + abstention, curator review |
| ✅ | T1.7d | Sandbox rollback check (`verification.py`): `Graph.copy` → mark rolled back → environment answers → `(Hypothesis)-[:VERIFIED_BY]->(Verification)` → `VERIFIED` state. Only the top hypothesis is checked, and the result never re-ranks |
| ✅ | T1.8 | FastAPI (`tracebrain/api/main.py`) + SSE event bus with replay for late subscribers (`events.py`), alert webhook, as-of graph endpoint for the UI |
| ✅ | resume | `orchestrator.run()` continues from the stored state; completed tool calls are replayed from `Step` nodes, not re-executed; `FAILED` is resumable; `POST .../resume` |
| ✅ | first real-LLM runs | Groq `gpt-oss-120b`, payments: inc:001 (culprit #2 behind a newer decoy, 4/4 claims verified), confirm → inc:007 repeat with memory ON (culprit #1), inc:025 correct abstain, inc:002 (culprit #2). Fixed: event-hook crash on Unicode (Windows console) failed runs; ExceptionGroup hid errors; repeated 8K-TPM 429s exhausted retries; prompts now batch independent calls (~25% fewer tokens/run). Top-1 misses on first occurrences are a ranking question → calibrate weights on the seen split in eval |
| ⬜ | **Oct 16:** UI + eval (baselines, memory ON/OFF, failure suite), `make judge-check` | see PLAN.md "Revised schedule" |
| ⬜ | **Oct 16 late / 17 AM:** earned autonomy A1-A6 (§14d) | only after the UI + eval exit checks pass; first to cut |

**API (as built)**: `GET /health`, `GET /tenants`, `GET /tenants/{t}/incidents`, `POST /tenants/{t}/incidents/{id}/investigate`, `GET /tenants/{t}/investigations[/{inv}]`, `GET .../{inv}/events` (SSE), `POST .../{inv}/resume`, `POST .../{inv}/review`, `GET /tenants/{t}/graph?t=`, `GET /tenants/{t}/memory`, `POST /tenants/{t}/causes/{key}/retract`, `POST /tenants/{t}/alerts`. Run: `uv run uvicorn tracebrain.api.main:app --port 8000` (docs at `/docs`).

Deviation: embeddings (sentence-transformers) are not used yet. Entity resolution is normalisation + token Jaccard + a small-LLM judge for borderline cases, and recall matches on symptom + service. That's enough on this dataset and avoids a ~1 GB torch install. B1 (vector RAG) will need the `embed` extra.

Companion to [PLAN.md](PLAN.md), which covers the what and the why. This file covers the how: repo layout, modules, interfaces, queries, prompts, API, UI, tests and the ticket list.

Stack: Python 3.11, `falkordb` client, `mcp` (FastMCP), LLM via the `openai` SDK against the **Groq** free tier (OpenAI-compatible; `gpt-oss-120b` for agents; wrapper + cache in `tracebrain/llm.py`, tested offline in `tests/test_llm.py`), FastAPI + SSE, `sentence-transformers` (local embeddings, `all-MiniLM-L6-v2`, 384-dim), Vite + React + Cytoscape.js, Docker Compose.

> **Verify before building on it.** All Cypher and `algo.*` calls below are written against FalkorDB docs as remembered. Ticket **T0.2** checks each one against the running server and records the results in `docs/falkordb_capabilities.md`. Anything unsupported gets replaced before tools are built on it.

---

## 0. Repository layout

```
tracebrain/
├── docker-compose.yml           # falkordb + api + ui
├── pyproject.toml
├── .env.example                 # ANTHROPIC_API_KEY, FALKOR_HOST, FALKOR_PORT, MODEL
├── README.md
├── docs/
│   ├── falkordb_capabilities.md # output of T0.2
│   └── data_model.md            # schema diagram + every Cypher query (Rule 10)
├── tracebrain/
│   ├── config.py                # env + constants (FOREVER, WINDOW defaults, weights)
│   ├── db.py                    # FalkorDB connection, graph_for(tenant), run(q, params)
│   ├── schema.py                # indexes + constraints per tenant graph
│   ├── queries.py               # ALL Cypher as named constants (single source for README)
│   ├── connectors/              # synthetic, otel_traces, git_deploys, codeowners, rcaeval, postmortems (§3.4)
│   ├── tools/
│   │   ├── impl.py              # pure Python tool functions (used by MCP, baselines, tests)
│   │   └── mcp_server.py        # FastMCP wrapper exposing impl.py
│   ├── agents/
│   │   ├── loop.py              # generic tool-use loop (Groq via llm.py) over MCP client + step logging
│   │   ├── prompts.py           # system prompts for triage / investigator / curator
│   │   ├── triage.py
│   │   ├── investigator.py
│   │   └── curator.py
│   ├── memory/
│   │   ├── episodic.py          # Investigation / Step / Finding persistence + resume
│   │   ├── semantic.py          # Cause upsert + entity resolution + confidence
│   │   └── procedural.py        # Lesson upsert + success/fail counters
│   ├── scoring.py               # suspect feature extraction + weighted score
│   ├── faithfulness.py          # claim → edge verification
│   ├── orchestrator.py          # runs triage → investigator, emits events, handles resume
│   ├── events.py                # in-process pub/sub for SSE
│   └── api/main.py              # FastAPI app
├── data/
│   ├── postmortems.json         # 5-8 public causes/runbooks w/ source URLs
│   └── ground_truth.json        # written by `python -m tracebrain.seed`, read only by eval
│   # (topology + generator live in tracebrain/connectors/synthetic.py; seeding in tracebrain/seed.py,
│   #  loading in tracebrain/ingest.py, indexes in tracebrain/schema.py)
├── lab/                         # real incidents on the OpenTelemetry Demo (§3.5)
├── eval/
│   ├── baselines.py             # B0 recent-deploy, B1 vector-RAG
│   ├── metrics.py               # top-k, F1, faithfulness, tool-call counts
│   ├── run_eval.py              # full table → eval/results.md + results.json
│   ├── memory_eval.py           # memory OFF vs ON, poisoning with/without gate
│   ├── tenancy_eval.py          # cross-tenant leak test
│   └── concurrency.py           # N parallel investigations
├── ui/                          # Vite + React + TS
│   └── src/{App.tsx, api.ts, components/*}
└── tests/
    ├── test_queries.py          # temporal correctness on a tiny fixture graph
    ├── test_scoring.py
    ├── test_faithfulness.py
    └── test_entity_resolution.py
```

**Rule:** agents never write raw Cypher. All graph access goes through `tools/impl.py` or `memory/*`, which use constants from `queries.py`. This keeps queries reviewable, testable and easy to list in the README.

---

## 1. Conventions

- **Time:** integer epoch seconds everywhere. `FOREVER = 4102444800` (2100-01-01) for open-ended `valid_to`, so no null checks are needed in hot queries.
- **IDs:** string business ids (`svc:checkout`, `dep:0042`, `inc:007`, `inv:<uuid>`). Use FalkorDB internal `id(r)` only for edge references in claims.
- **Tenants:** graph name = `tenant_<slug>` (`tenant_payments`, `tenant_platform`). The tenant is **never an LLM-controlled argument.** The orchestrator injects it into every tool call (see §5.1).
- **Simulated "now":** the incident's `ts` is passed as `t` to every as-of query.

---

## 2. Graph schema (`schema.py`, `queries.py`)

### 2.1 Indexes (run per tenant graph)
```cypher
CREATE INDEX FOR (s:Service) ON (s.name)
CREATE INDEX FOR (d:Deploy) ON (d.ts)
CREATE INDEX FOR (d:Deploy) ON (d.id)
CREATE INDEX FOR (i:Incident) ON (i.id)
CREATE INDEX FOR (v:Investigation) ON (v.id)
CREATE INDEX FOR (c:Cause) ON (c.key)
CREATE INDEX FOR (l:Lesson) ON (l.symptom)
CREATE VECTOR INDEX FOR (i:Incident) ON (i.embedding) OPTIONS {dimension:384, similarityFunction:'cosine'}
CREATE VECTOR INDEX FOR (c:Cause) ON (c.embedding) OPTIONS {dimension:384, similarityFunction:'cosine'}
```

### 2.2 Node properties
| Label | Properties |
|---|---|
| `Service` | `name, tier ('frontend'|'core'|'data'), service_type ('http'|'grpc'|'cache'|'db')` |
| `Team` | `name` |
| `Person` | `name, handle` |
| `Deploy` | `id, ts, change_size (lines), kind ('code'|'config'|'flag'), summary` |
| `Alert` | `id, ts, symptom ('latency'|'error_rate'|'timeout'|'oom'|'crashloop'|'saturation'), message` |
| `Incident` | `id, ts, severity, status ('open'|'investigating'|'resolved'), text, embedding` |
| `Runbook` | `id, title, steps (list<string>), source_url` |
| `Investigation` | `id, incident_id, status ('running'|'awaiting_review'|'confirmed'|'rejected'), started, ended, memory_enabled (bool)` |
| `Step` | `n, agent, tool, args_json, result_json (truncated), edge_ids (list<int>), ts, ms` |
| `Finding` | `kind ('blast_radius'|'owners'|'similar'), payload_json` |
| `Hypothesis` | `rank, score, features_json, deploy_id` |
| `Claim` | `text, edge_ids (list<int>), verified (bool), reason` |
| `Action` | `kind ('ticket'|'rollback_proposal'|'page'), target, status ('proposed'|'done'), payload_json` |
| `Cause` | `key, name, aliases (list), confidence (0..1), confirmations, rejections, retracted (bool), embedding` |
| `Lesson` | `id, symptom, service_type, check_first ('recent_deploy:<service>'|'dependency:<service>'|'config'), success_count, fail_count, retracted` |

### 2.3 Relationships
```
(Service)-[:DEPENDS_ON {valid_from, valid_to}]->(Service)
(Team)-[:OWNS {valid_from, valid_to}]->(Service)
(Person)-[:MEMBER_OF]->(Team)
(Deploy)-[:DEPLOYED_TO]->(Service)          (Person)-[:AUTHORED]->(Deploy)
(Alert)-[:FIRED_ON]->(Service)              (Incident)-[:TRIGGERED_BY]->(Alert)
(Incident)-[:AFFECTED]->(Service)
(Incident)-[:INVESTIGATED_IN]->(Investigation)
(Investigation)-[:HAS_STEP]->(Step)         (Step)-[:NEXT]->(Step)
(Investigation)-[:PRODUCED]->(Finding)
(Finding)-[:HANDOFF {from_agent, to_agent, ts}]->(Investigation)   // read by next agent
(Investigation)-[:PROPOSED]->(Hypothesis)-[:SUSPECTS]->(Deploy)
(Hypothesis)-[:ASSERTS]->(Claim)
(Investigation)-[:TOOK]->(Action)-[:TARGETS]->(Service|Team|Deploy)
(Incident)-[:CAUSED_BY {confirmed_by, ts, confidence}]->(Cause)
(Incident)-[:ROOT_DEPLOY]->(Deploy)                                 // confirmed
(Cause)-[:FIXED_BY]->(Runbook)
(Lesson)-[:LEARNED_FROM]->(Incident)        (Lesson)-[:ABOUT]->(Cause)
(Cause)-[:DERIVED_FROM]->(Runbook)                                  // seeded from public postmortems
```

---

## 3. Data generation: BUILT (`tracebrain/connectors/synthetic.py`, `tracebrain/seed.py`)

### 3.1 Topology
- 12 services: Online Boutique's 11 plus `currency-v2`. Tiers and service types are on the nodes.
- DEPENDS_ON follows the published call graph: `frontend→{productcatalog, currency, cart, recommendation, shipping, checkout, ad}`, `checkout→{productcatalog, shipping, payment, email, currency, cart}`, `cart→redis-cart`, `recommendation→productcatalog`.
- **tenant_payments** teams: Checkout, Payments, Storefront. **tenant_platform** teams: Platform, Data, Web. Same topology, different owners, people, deploys and incidents (separate seeds), which makes the leak test meaningful.
- Temporal changes over 56 days from 2026-08-01:
  - **day 24:** frontend and checkout move from `currency` to `currency-v2`.
  - **day 36:** `payment` ownership transfers to another team.
  - **day 44:** `recommendation→ad` added.

### 3.2 Generator (seeded and deterministic; a test asserts it)
| Symptom (alerted service) | Hidden cause | Culprit placement |
|---|---|---|
| `timeout` on checkout | connection_pool_exhaustion | config on `redis-cart` (2 hops) |
| `error_rate` on frontend | currency_conversion_bug | code on `currency` before day 24, `currency-v2` after (1 hop, tests as-of) |
| `latency` on checkout | n_plus_one_query | code on `productcatalog` (1 hop) |
| `crashloop` on payment | missing_env_var | config on `payment` (0 hops) |
| `oom` on recommendation | cache_size_flag | flag on `recommendation` (0 hops) |
| `saturation` on shipping | retry_storm | code on `shipping` (0 hops) |

- 4 occurrences per type, interleaved, **2 days apart** in 08:00-20:00 slots, so 24h windows never overlap. Culprit lands 20 min-6 h before the alert.
- **Decoys per incident:**
  - a caller-side deploy (newer than the culprit 45% of the time);
  - 1-2 deploys on the dependency path, including the culprit's own service (newer 30% of the time);
  - 0-2 noise deploys.
  - Background deploys (~4/day) stay outside every incident window.
- **Abstention:** 2 per tenant (alerts on `ad` and `email`, leaf services) with deploys only outside their dependency closure. `culprit_deploy: null`.
- **Leakage guard:** neutral summaries (`release X build N`, `update X configuration`, `toggle flag on X`) and texts. `leakage_violations()` checks for cause keys and words like "culprit", "faulty", "injected"; seeding aborts on any hit.
- **Measured difficulty** (top-1 on 24 culprit incidents per tenant):
  - B0 "latest deploy anywhere in window": **25% / 12%** (payments / platform).
  - "Newest as-of graph suspect": **46% / 46%**.
  - So the graph clearly helps, and ranking + memory still have room to add value. `test_benchmark_difficulty_is_realistic` keeps this in range.
- `data/ground_truth.json` is keyed `"<tenant>/<incident>"` with: type, service, ts, culprit_deploy, culprit_service, cause_key, occurrence, split (`seen` = occurrence 1, else `test`), blast_radius (computed by an **independent Python BFS**, and the Cypher must match it), and decoy roles.

### 3.3 Seeding
`uv run python -m tracebrain.seed --reset` runs the leakage guard, drops and recreates both tenant graphs (indexes + vector indexes), and ingests through `SyntheticConnector` via `ingest()`. It writes the ground truth to `data/ground_truth.json`.
**Still to do:** `Incident.embedding` (needs the `embed` extra) and `postmortems.json` → `Cause`/`Runbook`. Both are needed for recall (T1.6).

---

## 3.4 Connectors (`tracebrain/connectors/`): what makes it usable in real life

```python
class Connector(Protocol):
    name: str
    def services(self) -> Iterable[ServiceRec]: ...              # name, tier, service_type
    def dependencies(self) -> Iterable[DepRec]: ...              # src, dst, valid_from, valid_to
    def ownership(self) -> Iterable[OwnRec]: ...                 # team, service, people, valid_from, valid_to
    def deploys(self, since: int, until: int) -> Iterable[DeployRec]: ...  # id, service, ts, change_size, kind, author, summary
    def incidents(self) -> Iterable[IncidentRec]: ...            # optional (historical); live alerts arrive via webhook

def ingest(tenant: str, *connectors: Connector) -> IngestReport   # idempotent MERGE upserts; reports counts
```

| Connector | File | Source | Notes |
|---|---|---|---|
| `SyntheticConnector` | `synthetic.py` | `data/generator.py` | Day 1. Unblocks everyone |
| `OtelTraceConnector` | `otel_traces.py` | Jaeger HTTP API (`/api/traces?service=X&lookback=…`, or Jaeger UI at `:8080/jaeger` in the OTel Demo) | Parent/child spans across services → `src→dst`. Edges are bucketed per 5 min: `valid_from` = first bucket seen, `valid_to` = last bucket + 5 min (or `FOREVER` if still active) |
| `GitDeployConnector` | `git_deploys.py` | Local git log of `tracebrain-lab` (or GitHub API for remote) | Path → service mapping (`services/<svc>/…`, `flags/<svc>.json`). `change_size` = lines changed. `kind` from path (`flags/` → `flag`, `config/` → `config`, else `code`) |
| `CodeownersConnector` | `codeowners.py` | `CODEOWNERS` file (+ git history for ownership changes) | `@org/team` → `Team`; `valid_from` from the commit that added the line |
| `RcaEvalConnector` | `rcaeval.py` | RCAEval RE2 case folders | Traces → DEPENDS_ON; the label → incident ground truth (`culprit_service`, no deploy). Read-only import, eval-only |
| `PostmortemConnector` | `postmortems.py` | `data/postmortems.json` | `Cause` + `Runbook` + `source_url` |

**Live alerts:** `POST /tenants/{t}/alerts` accepts an Alertmanager-style payload `{labels:{service, alertname}, startsAt}`. It creates `Alert` + `Incident` and auto-starts an investigation if `auto_investigate=true`. The lab uses a tiny `lab/watch.py` that polls the OTel Demo's metrics (error rate/latency per service from Prometheus at `:9090`) and fires this webhook. That way incidents are *detected*, not hand-created.

### 3.5 The lab (`lab/`, real incidents from the OpenTelemetry Demo)

```
lab/
├── README.md               # how to bring up the OTel Demo + run scenarios
├── scenarios.yaml          # one entry per incident: flag, variant, culprit commit, decoy commits, expected symptom
├── inject.py               # commit (real git) → flip flagd flag → wait → record ground truth → revert
├── watch.py                # Prometheus poll → POST /alerts
└── ground_truth_real.json  # written by inject.py, read only by eval
```
- **Setup:** `git clone https://github.com/open-telemetry/opentelemetry-demo && docker compose up -d` (Docker Desktop memory ≥ 8 GB). The UI is at `:8080`, flags at `:8080/feature`, Jaeger at `:8080/jaeger/ui`. **Verify the ports and the flagd config file path in the first 30 minutes**; the docs page doesn't state the file path.
- **Flag flipping:** edit the flagd JSON config through the mounted file (preferred, since that edit is the git commit) or the flagd UI.
- **Scenario example:** `cart-redis`: decoy commit on `frontend` (t-5 min), culprit commit `flags: cartFailure 50%` (t-20 min) → symptom: checkout error rate. Expected: culprit = cart commit, blast radius includes checkout + frontend.
- **Target:** 6-10 scenarios. Run each once for the "seen" split, and re-run 3-4 of them later for the memory test on real data.

### 3.6 RCAEval import (`eval/rcaeval_subset.py`)
- Download only RE2 cases for Online Boutique (smallest); pick about 30 cases.
- **Check the license** (repo LICENSE + Zenodo record) before committing *any* derived data. If it's unclear, ship the import script only and have users download the data themselves.
- Metric: top-1/top-3 **root-cause service** (not deploy). Tracebrain uses `blast_radius` + `centrality` + anomaly-annotated services (from the case metrics) to rank. Compare against the RCAEval-reported baselines where formats align; otherwise only against our B0/B1 adaptations.

---

## 4. Queries (`queries.py`). Every constant is documented in the README.

```python
AS_OF = "r.valid_from <= $t AND r.valid_to > $t"

BLAST_RADIUS = f"""
MATCH p = (up:Service)-[:DEPENDS_ON*1..5]->(f:Service {{name: $svc}})
WHERE all(r IN relationships(p) WHERE {AS_OF})
WITH up, min(length(p)) AS hops, collect(p)[0] AS path
RETURN up.name AS service, hops, [r IN relationships(path) | id(r)] AS edge_ids
ORDER BY hops"""

OWNERS = f"""
MATCH (t:Team)-[r:OWNS]->(s:Service) WHERE s.name IN $services AND {AS_OF}
OPTIONAL MATCH (p:Person)-[:MEMBER_OF]->(t)
RETURN s.name AS service, t.name AS team, collect(p.handle) AS people, id(r) AS edge_id"""

SUSPECTS = f"""
MATCH p = (f:Service {{name: $svc}})-[:DEPENDS_ON*0..3]->(s:Service)
WHERE all(r IN relationships(p) WHERE {AS_OF})
WITH s, min(length(p)) AS proximity, collect(p)[0] AS path
MATCH (d:Deploy)-[dr:DEPLOYED_TO]->(s)
WHERE d.ts <= $t AND d.ts >= $t - $window
OPTIONAL MATCH (a:Person)-[:AUTHORED]->(d)
RETURN d.id AS deploy, s.name AS service, d.ts AS ts, d.change_size AS change_size,
       d.kind AS kind, a.handle AS author, proximity,
       [r IN relationships(path) | id(r)] + [id(dr)] AS edge_ids"""

SERVICE_FAIL_RATE = """
MATCH (s:Service {name: $svc})<-[:AFFECTED]-(i:Incident) WHERE i.ts < $t
RETURN count(i) AS n"""

SHORTEST_PATH = f"""
MATCH p = (a:Service {{name: $a}})-[:DEPENDS_ON*1..6]->(b:Service {{name: $b}})
WHERE all(r IN relationships(p) WHERE {AS_OF})
WITH p, length(p) AS len ORDER BY len LIMIT 1
RETURN [n IN nodes(p) | n.name] AS services, [r IN relationships(p) | id(r)] AS edge_ids"""
# VERIFIED (T0.2): FalkorDB's shortestPath() only works in WITH/RETURN and ignores valid_from/to,
# so it would return stale paths. The var-length + as-of filter above is correct.

PAGERANK = "CALL algo.pageRank('Service', 'DEPENDS_ON') YIELD node, score RETURN node.name, score"
# NOTE: pageRank ignores valid_from/to. Acceptable as a weak prior; document it.

RECALL_SIMILAR = """
CALL db.idx.vector.queryNodes('Incident', 'embedding', $k, vecf32($vec)) YIELD node, score
WHERE node.id <> $incident_id AND node.ts < $t
MATCH (node)-[cb:CAUSED_BY]->(c:Cause) WHERE NOT c.retracted
OPTIONAL MATCH (node)-[:ROOT_DEPLOY]->(d:Deploy)-[:DEPLOYED_TO]->(s:Service)
OPTIONAL MATCH (c)-[:FIXED_BY]->(rb:Runbook)
RETURN node.id AS incident, score, c.name AS cause, c.confidence AS confidence,
       s.name AS culprit_service, rb.title AS runbook, id(cb) AS edge_id"""

RECALL_LESSONS = """
MATCH (l:Lesson {symptom: $symptom})-[:LEARNED_FROM]->(i:Incident)
WHERE NOT l.retracted AND i.ts < $t AND (l.service_type = $stype OR $stype IS NULL)
RETURN l.id, l.check_first, l.success_count, l.fail_count, collect(i.id) AS evidence
ORDER BY l.success_count - l.fail_count DESC LIMIT 3"""

EDGE_LOOKUP = """
MATCH (a)-[r]->(b) WHERE id(r) IN $ids
RETURN id(r) AS id, type(r) AS type, coalesce(a.name, a.id) AS src, coalesce(b.name, b.id) AS dst"""
```
Memory writes (episodic/semantic/procedural) are also in `queries.py` as `MERGE`-based upserts. See §6.

---

## 5. MCP server (`tools/`)

### 5.1 `impl.py`: pure functions
Each takes `ctx: ToolCtx` (tenant, t, investigation_id, memory_enabled) plus the LLM-visible args. Each returns a JSON-serializable dict that **always includes `edge_ids`** for anything path-derived.

```python
@dataclass
class ToolCtx: tenant: str; t: int; investigation_id: str; memory_enabled: bool = True

def blast_radius(ctx, service: str, max_hops: int = 5) -> dict
def owners_of(ctx, services: list[str]) -> dict
def suspects_asof(ctx, service: str, window_hours: int = 24) -> dict   # returns scored + ranked list (calls scoring.py)
def path_between(ctx, a: str, b: str) -> dict
def centrality(ctx) -> dict
def recall_similar(ctx, incident_id: str, k: int = 5) -> dict          # returns [] if not ctx.memory_enabled; SUMMARY ONLY (id, score, cause, confidence)
def get_past_investigation(ctx, incident_id: str) -> dict             # progressive disclosure: full steps/claims of ONE past case, only when the agent decides it's relevant
def recall_lessons(ctx, symptom: str, service_type: str | None) -> dict # returns [] if not ctx.memory_enabled
def create_action(ctx, kind: str, target: str, reason: str) -> dict
def read_findings(ctx) -> dict                                          # blackboard read (Investigator)
def write_finding(ctx, kind: str, payload: dict) -> dict                # blackboard write (Triage)
```

### 5.2 `mcp_server.py`
**BUILT** on MCP Python SDK **2.x**, where `FastMCP` is renamed `MCPServer`. Tools take only LLM-facing args. Tenant, incident time, investigation id and the memory flag travel as **MCP request metadata** (`tracebrain/tenant`, `tracebrain/t`, ...), read server-side from `ctx.request_context.meta`:

```python
server = MCPServer("tracebrain")

@server.tool()
def blast_radius(service: str, ctx: Context, max_hops: int = 5) -> dict:
    """Services that depend (directly or transitively) on `service` at incident time."""
    return _run(impl.blast_radius, ctx, service, max_hops)   # tool_ctx(ctx) builds ToolCtx from meta
```
- Tenant and time **never appear in the tool schema** (a test asserts this), so the LLM can't see or choose them. That's tenant isolation by construction, and it's verified over the protocol in `tests/test_tools.py`.
- External MCP clients that send no metadata fall back to `TRACEBRAIN_DEFAULT_TENANT` and the current time.
- Tool errors (e.g. an unknown service) come back as `{"error": "... Known services: [...]"}` so the agent can recover.
- Tools: `get_incident, blast_radius, owners_of, suspects, path_between, centrality`. Memory and blackboard tools are added on Day 2.
- Transport: stdio for local runs, streamable-HTTP for the deployed version. The same server can be plugged into any MCP client (e.g. Claude Desktop, Cursor) for a "bonus" demo clip.

### 5.3 Tool allowlists per agent
| Agent | Tools |
|---|---|
| Triage | `blast_radius, owners_of, recall_similar, write_finding` |
| Investigator | `read_findings, suspects_asof, path_between, centrality, recall_lessons, get_past_investigation, create_action` |

**Progressive disclosure:** memory is recalled in stages. The first stage is cheap summaries (`recall_similar`, `recall_lessons`). The agent pulls the full details of a past case with `get_past_investigation` only when a summary looks relevant, which keeps context small. Rejected or retracted memory is filtered out at every stage.
| Curator | none via LLM (deterministic Python + one LLM call for entity-resolution fallback) |

---

## 6. Memory modules (`memory/`)

### 6.1 `episodic.py`
```python
start_investigation(tenant, incident_id, memory_enabled) -> inv_id   # creates Investigation, links Incident
log_step(tenant, inv_id, agent, tool, args, result, ms) -> step_n    # appends Step, NEXT chain, stores edge_ids
load_steps(tenant, inv_id) -> list[Step]                              # for resume + UI replay
set_status(tenant, inv_id, status)
```
**Resume:** `orchestrator.resume(inv_id)` loads the steps. If no `Finding` exists, Triage is rerun. If Findings exist but no `Hypothesis`, Investigator runs with prior tool results replayed into its message history from `Step.result_json`. Demo: kill the API mid-run, restart, call `POST /investigations/{id}/resume`.

### 6.2 `semantic.py`: entity resolution + confidence
```python
resolve_cause(tenant, text) -> (cause_key, is_new)
```
1. `normalize(text)`: lowercase, strip punctuation, synonym map (`db→database`, `conn→connection`, `pool exhausted→pool exhaustion`, `oom→out of memory`), singularize trailing `s`.
2. Exact match on `key` or `aliases`, and the result is final.
3. Vector top-3 on `Cause.embedding`. FalkorDB returns a cosine **distance** (0 = identical; verified in T0.2). If distance ≤ 0.15, merge (add alias).
4. If distance is 0.15-0.30: one cheap LLM call ("same root cause? yes/no + which") with the candidates.
5. Otherwise create a new `Cause{confidence: 0.5}`.

Confidence update on review:
- **confirm:** `confirmations += 1; confidence = 1 - 0.5 * 0.7**confirmations`
- **reject:** `rejections += 1; confidence *= 0.5`; if `confidence < 0.2` then `retracted = true`.

### 6.3 `procedural.py`
On **confirm**: upsert `Lesson{symptom, service_type(of alerted service), check_first: f"recent_deploy:{culprit_service}" or "dependency:<svc>"}`, `success_count += 1`, link `LEARNED_FROM` + `ABOUT`.
On a later investigation where a recalled lesson pointed at the wrong place and the review rejects: `fail_count += 1`.

### 6.4 Confirm gate (memory safety)
The Curator only runs from `POST /investigations/{id}/review`. The eval runs a variant with `gate=False` (auto-write the top hypothesis as confirmed) to measure poisoning.

---

## 7. Scoring (`scoring.py`)

```python
FEATURES = ["proximity", "recency", "change_size", "fail_rate", "centrality", "lesson_match"]

def features(row, t, window, fail_rate, centrality, lessons) -> dict:
    proximity    = 1 / (1 + row["proximity"])                       # 0 hops → 1.0
    recency      = 1 - (t - row["ts"]) / window                    # newer → 1.0
    change_size  = min(1, log1p(row["change_size"]) / log1p(2000))
    fail_rate    = min(1, fail_rate / 5)
    centrality   = centrality.get(row["service"], 0)              # pre-normalized 0..1
    lesson_match = max((l.weight for l in lessons if l.points_to(row["service"])), default=0)
    return {...}

def score(f: dict, w: dict) -> float: return sum(w[k] * f[k] for k in FEATURES)
```
- Default weights are in `config.py`. `eval/run_eval.py --calibrate` grid-searches `w ∈ {0, 0.5, 1, 2}^6` on the **seen split only** and writes `weights.json`.
- `ablation`: zero each weight in turn and report the top-3 delta. This is optional and goes in the cut list.
- `suspects_asof` returns ranked rows with `features` + `score` + `edge_ids`, so the LLM reasons over ranked evidence and doesn't invent rankings.

---

## 8. Faithfulness (`faithfulness.py`)

Investigator's final output (enforced via a `submit_hypotheses` tool whose input schema is this JSON):
```json
{
  "hypotheses": [
    {"rank": 1, "deploy_id": "dep:0042", "summary": "...",
     "claims": [
       {"text": "checkout depends on redis-cart via cart", "edge_ids": [311, 318]},
       {"text": "dep:0042 was deployed to redis-cart 40 min before the alert", "edge_ids": [902]}
     ]}
  ],
  "actions": [{"kind": "ticket", "target": "team:Platform", "reason": "..."}],
  "abstain": false,
  "abstain_reason": null
}
```
**Abstention rule:** if `suspects_asof` returns nothing, or the top score is below `ABSTAIN_TAU` (calibrated on the seen split), the Investigator must set `abstain: true`. In that case it should propose only a "page owner" action, not a rollback. The orchestrator enforces the threshold even if the LLM ignores it.
Checker:
1. `seen = ∪ Step.edge_ids` for this investigation (edges the agent actually received from tools).
2. For each claim: every id must be in `seen` (otherwise `reason="edge not retrieved"`). `EDGE_LOOKUP` must return all of them, and the `src/dst` names must appear in the claim text (fuzzy match). Otherwise `reason="edge does not support claim"`.
3. Claims with no `edge_ids` are marked unverified (`reason="no evidence"`).
4. Store `Claim{verified, reason}`. `faithfulness = verified/total`. Unverified claims are shown red and dropped from the summary sent to Slack/ticket.

---

## 9. Agents (`agents/`)

### 9.1 `loop.py`: shared tool-use loop
```python
async def run_agent(name, system, user_msg, tools, ctx, max_turns=12, final_tool=None) -> dict:
    # tools: MCP list_tools() filtered by allowlist -> OpenAI schema (clean_schema); context sent as MCP meta
    # each turn: client.messages.create(model=MODEL, system=..., tools=..., messages=...)
    # for each tool_use block: inject ctx → call MCP → log_step() → events.emit("tool_call"/"tool_result")
    # stop when final_tool is called (its input is the return value) or max_turns hit
```
- Tool results are truncated to about 4k chars before going back to the model, and the full result is stored in `Step`.
- Every call is timed (`ms`) for latency stats.

### 9.2 Prompts (`prompts.py`): key instructions
- **Triage:** "You are the triage agent. Determine blast radius and owners for the alerted service at incident time. Check for similar past incidents. Record each result with `write_finding` (kinds: blast_radius, owners, similar). Do not guess root cause. Finish by calling `write_finding` with kind `done`."
- **Investigator:** "Start by calling `read_findings`. Use `recall_lessons` before searching broadly. `suspects_asof` returns ranked deploys with scores; you may re-rank only with evidence from `path_between`, findings or lessons. Every claim must cite `edge_ids` copied from tool results. Never invent ids. Propose at most 3 actions. Finish with `submit_hypotheses`."
- **Curator (entity-resolution fallback only):** "Given a new cause description and candidate causes, answer JSON `{same: bool, key: str|null}`."

### 9.3 `orchestrator.py`
```python
async def investigate(tenant, incident_id, memory_enabled=True) -> inv_id:
    inv = episodic.start_investigation(...)
    ctx = ToolCtx(tenant, incident.ts, inv, memory_enabled)
    await run_agent("triage", ...)                   # writes Findings + HANDOFF edge
    out = await run_agent("investigator", ..., final_tool="submit_hypotheses")
    hyps = faithfulness.verify_and_store(ctx, out)
    actions.store(ctx, out["actions"])               # Action nodes, status=proposed
    episodic.set_status(..., "awaiting_review")
    events.emit("done", {...})

async def review(tenant, inv_id, verdict, cause_text, deploy_id, runbook_id, reviewer):
    curator.apply(...)   # semantic + procedural updates, CAUSED_BY / ROOT_DEPLOY edges, status
```

---

## 10. API (`api/main.py`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/tenants` | list tenant graphs |
| GET | `/tenants/{t}/incidents` | incidents + status |
| POST | `/tenants/{t}/incidents/{id}/investigate` | body `{memory_enabled}` → `{investigation_id}` (runs as background task) |
| GET | `/investigations/{id}/stream` | SSE: `step`, `tool_call`, `tool_result`, `finding`, `handoff`, `hypothesis`, `claim`, `action`, `done`, `error` |
| GET | `/investigations/{id}` | full state from graph (steps, findings, hypotheses, claims, actions) |
| POST | `/investigations/{id}/resume` | resume from graph |
| POST | `/investigations/{id}/review` | `{verdict: confirm|reject, cause_text, deploy_id, runbook_id?, reviewer}` |
| GET | `/tenants/{t}/subgraph?center=svc&t=&hops=2` | nodes+edges for Cytoscape (with internal edge ids) |
| GET | `/tenants/{t}/memory` | causes, lessons, confidence, provenance |
| POST | `/tenants/{t}/causes/{key}/retract` | manual retract |
| GET | `/tenants/{t}/cypher-log` | last N queries executed (judges like seeing them) |

---

## 11. UI (`ui/`)

> **Superseded by [docs/FRONTEND_PLAN.md](docs/FRONTEND_PLAN.md)** (React Flow instead of Cytoscape, design system, event → UI mapping, tickets U0-U10). The original sketch is kept below for reference.

Single page, 3 columns:
- **Left:** `TenantSwitcher`, `IncidentList` (status chips), "Investigate" button, "Memory ON/OFF" toggle.
- **Center:** `GraphView` (Cytoscape, `cose-bilkent` or `dagre` layout). Shows the subgraph around the alerted service at time `t`. Blast radius nodes are orange, the suspect path is red and thick, and the culprit deploy is a red diamond. Edge ids are kept as Cytoscape element ids, so hovering a claim highlights its exact edges.
- **Right:** `TracePanel` (live SSE list: agent badge, tool name, args, ms, expandable result), `HypothesesPanel` (ranked suspects + feature bars), `ClaimsPanel` (✓/✗ + reason, hover → highlight edges), `ActionsPanel`, `ReviewBox` (Confirm / Reject, cause text, prefilled).
- **Tab 2: Memory.** Causes table (aliases, confidence, provenance links), Lessons table (success/fail), Retract button.
- **Tab 3: Results.** Renders `eval/results.json`.

Fallback (cut item 4): Streamlit app with `pyvis` graph + the same panels, consuming the same API.

---

## 12. Evaluation (`eval/`)

| Script | Output |
|---|---|
| `baselines.py` | **B0:** latest deploy in window on any service in blast radius ∪ {svc}. **B1:** embed alert text → vector top-k over `Deploy.summary` + past incidents, rank by similarity (no traversal). |
| `run_eval.py` | For the test split: top-1/top-3 accuracy (B0, B1, Tracebrain), blast-radius F1 (naive vs as-of), faithfulness mean, tool calls/steps, p50/p95 latency |
| `memory_eval.py` | Fresh seed → run test incidents with `memory_enabled=False`. Fresh seed → run seen incidents + auto-confirm with ground truth → run test incidents with memory ON. Report Δ tool calls, Δ top-1. **Poisoning:** confirm one wrong cause with gate vs `gate=False` auto-write; count later wrong recalls. |
| `tenancy_eval.py` | For every tool, call with tenant A context using entity names only present in B: expect empty. Plus 0 lessons from B ever returned in A's runs. |
| `failure_suite.py` | One pass/fail row per scenario: (1) newer decoy deploy is not ranked #1, (2) dependency changed before incident → as-of path used, naive path differs, (3) claim citing an un-retrieved/irrelevant edge → rejected, (4) rejected cause is not recalled / its lesson weight drops, (5) cross-tenant probe → empty, (6) no-deploy incident → `abstain: true`. Also runs the leakage guard. |
| `concurrency.py` | `asyncio.gather` of N=10,20 investigations (LLM mocked with recorded tool sequences to isolate DB load) → throughput, p95, integrity check (each Investigation's `Step.n` contiguous, no orphan Steps). |

Results go to `eval/results.json` + `eval/results.md`, and are pasted into the README.

**Cost guard:** cache LLM responses keyed by `(prompt hash, tool results hash)` in `eval/.cache/` so reruns are free. 24 test incidents × 2 tenants × ~2 configs ≈ 100 runs, which is affordable.

---

## 13. Tests (`tests/`, pytest, run against a throwaway graph `test_<uuid>`)

- `test_queries.py`: 4-node fixture. Edge A→B valid until t=100, A→C from t=100. Blast radius at t=50 vs t=150 differs. Suspects only return deploys in window.
- `test_scoring.py`: 0-hop beats 2-hop at equal recency; `lesson_match` flips rank.
- `test_faithfulness.py`: claim with an un-retrieved edge id fails; claim with mismatched endpoint names fails; good claim passes.
- `test_entity_resolution.py`: "db timeout" ≡ "database timeouts"; "OOM" ≡ "out of memory"; "disk full" ≠ "db timeout".
- Tenancy: tool schemas contain no tenant/time; the same incident id under two tenants' metadata returns each tenant's own data (`tests/test_tools.py`).

---

## 14. Ticket list (ordered, with dependencies)

Estimates are for one person. **Bold** = critical path.

### Day 1 (Oct 15): foundation
| ID | Task | Est | Depends | Done when |
|---|---|---|---|---|
| **T0.1** | Repo scaffold, pyproject, docker-compose (falkordb), `.env`, `db.py` | 0.5h | | `python -c "import tracebrain.db"` connects |
| **T0.2** | Capability check: var-length + `all()` filter, `shortestPath` + WHERE, `algo.pageRank`, `algo.betweenness`, `algo.BFS`, `algo.SPpaths`, vector index + `queryNodes`, `id(r)` stability, list props | 1h | T0.1 | `docs/falkordb_capabilities.md` written; queries adjusted |
| **T0.3** | `schema.py` + `queries.py` (world graph) | 1h | T0.2 | indexes created on 2 graphs |
| **T0.4** | `data/topology.py`, `generator.py`, `seed.py`, `ground_truth.json` | 2.5h | T0.3 | both tenants seeded; Browser shows graph; 48 incidents |
| **T0.5** | `tools/impl.py`: blast_radius, owners_of, suspects_asof (unscored), path_between, centrality | 1.5h | T0.4 | `test_queries.py` green |
| **T0.6** | `mcp_server.py` + context via MCP request metadata | 1h | T0.5 | MCP Inspector lists and calls tools |
| **T0.7** | `agents/loop.py` + one-agent smoke run on 1 incident | 1.5h | T0.6 | console prints ranked suspects with edge ids |

### Day 2 (Oct 16): agents + memory
| ID | Task | Est | Depends | Done when |
|---|---|---|---|---|
| **T1.1** | `episodic.py` (Investigation/Step logging, NEXT chain) wired into loop | 1h | T0.7 | steps visible in Browser |
| **T1.2** | Findings blackboard (`write_finding`, `read_findings`, HANDOFF) + Triage agent | 1.5h | T1.1 | Triage writes 3 findings |
| **T1.3** | `scoring.py` + scored `suspects_asof` | 1h | T0.5 | `test_scoring.py` green |
| **T1.4** | Investigator agent + `submit_hypotheses` + `create_action` | 1.5h | T1.2, T1.3 | structured output stored |
| **T1.5** | `faithfulness.py` + Claim nodes | 1h | T1.4 | `test_faithfulness.py` green |
| **T1.6** | `semantic.py` entity resolution + confidence; `procedural.py` Lessons; `recall_similar`, `recall_lessons` | 2h | T1.4 | `test_entity_resolution.py` green |
| **T1.7** | `orchestrator.py` (investigate / review / resume) + `events.py` | 1h | T1.5, T1.6 | **same incident type run twice: 2nd run uses lesson, fewer tool calls** |
| T1.7b | `get_past_investigation` tool + abstention rule in orchestrator | 0.5h | T1.7 | no-deploy incident → `abstain: true` |
| T1.8 | FastAPI endpoints + SSE | 1h | T1.7 | curl stream shows events |

### Day 3 (Oct 17): UI + eval + deploy
| ID | Task | Est | Depends | Done when |
|---|---|---|---|---|
| **T2.1** | UI scaffold + incident list + investigate + SSE trace | 1.5h | T1.8 | live trace renders |
| **T2.2** | GraphView with path/blast highlight + claim hover → edge highlight | 2h | T2.1 | claim hover lights exact edges |
| **T2.3** | Review box + Memory tab + tenant switcher | 1h | T2.1 | confirm updates Memory tab |
| **T2.4** | `baselines.py` + `run_eval.py` + weight calibration on seen split | 2h | T1.7 | results.json with B0/B1/Tracebrain |
| T2.5 | `memory_eval.py` (OFF vs ON, then poisoning) | 1.5h | T2.4 | Δ tool calls reported |
| T2.6 | `tenancy_eval.py` + `test_tenancy.py` | 0.5h | T1.7 | leaks = 0 |
| **T2.6b** | `failure_suite.py` (6 scenarios + leakage guard) + abstention threshold calibration | 1.5h | T2.4 | pass/fail table in results.md |
| T2.7 | `concurrency.py` (P2: only after the main flow is solid) | 1h | T1.7 | table in results.md |
| **T2.8** | Deploy: FalkorDB Cloud + API/UI on Render/Railway; seed remote | 1.5h | T2.3 | public URL runs full demo |

### Day 4 (Oct 18): ship (submit by 21:00 IST)
| ID | Task | Est | Done when |
|---|---|---|---|
| **T3.1** | Bug bash on the demo path only; code freeze 18:00 | 3h | demo script runs 3× clean |
| **T3.2** | README: pitch, tracks, architecture, data model diagram, **all queries from `queries.py`**, results, setup (Docker Compose one-liner), synthetic-data note, AI-assistant disclosure | 2h | a fresh clone runs via README |
| **T3.3** | Demo video (script in PLAN.md §8) | 2h | ≤ 4 min, uploaded |
| T3.4 | Blog post (side prize) | 1.5h | published |
| **T3.5** | Submit | 0.5h | confirmation received |

### Parallel split for a team (if you have one)
- **Person A (graph/data/eval):** T0.2-T0.5, T1.6, T2.4-T2.7, README data model.
- **Person B (agents/MCP):** T0.6-T0.7, T1.1-T1.5, T1.7.
- **Person C (API/UI/deploy):** T0.1, T1.8, T2.1-T2.3, T2.8, video.
- **Person D (if any):** blog, demo script, eval harness support, Online Boutique real-trace stretch.

**Interface freeze, end of Day 1:** `queries.py` constant names, `impl.py` signatures, SSE event names and the `submit_hypotheses` JSON schema. Lanes then work independently against these contracts.

---

## 14b. Additions from winning-project lessons (see PLAN.md §9)

| ID | Task | Est | Depends | Done when |
|---|---|---|---|---|
| **T1.5b** | Make `submit_hypotheses` a gate: run `faithfulness.verify` inside the tool. On failure, return an error listing the bad claims; agent retries (max 2), then remaining bad claims are dropped and flagged | 0.5h | T1.5 | a fabricated edge id is bounced back to the agent in the trace |
| **T1.7c** | `Investigation.state` machine (`OPEN→TRIAGED→HYPOTHESIZED→VERIFIED→AWAITING_REVIEW→CONFIRMED/REJECTED→LEARNED`); illegal transitions raise; emitted over SSE | 0.5h | T1.7 | UI stepper reflects state |
| **T1.7d** | `verify_rollback(deploy_id)`: sandbox = copy graph with `GRAPH.COPY` (verify in T0.2) or an in-memory world model from `generator.py`; re-evaluate symptom with deploy reverted; returns `{clears: bool}`. Runs before review; result stored on `Hypothesis.verified_by_rollback` | 1.5h | T1.4 | decoy rollback → `clears=false`; culprit → `true` |
| T1.9 | Read-only enforcement: all tool queries via `graph.ro_query`; writes only in `memory/*` and `orchestrator.review` | 0.25h | T0.5 | test: write attempt via tool raises |
| T2.4b | Ablation: "flat tools" variant (no traversal: lists of deploys/services) + scale test with `generator.py --services 200` | 1.5h | T2.4 | rows in results.md, reported honestly |
| T2.4c | Run stats: turns, tool calls, wall time, **tokens + cost per investigation** from API usage; commit 1 unedited transcript to `eval/transcripts/` | 0.5h | T2.4 | stats in results.md |
| **T3.0** | `make judge-check`: pytest + failure suite on recorded LLM transcripts, no API key needed; README "45-second judge path" + safety-envelope table | 1h | T2.6b | fresh clone passes `make judge-check` offline |
| T3.6 | Stretch: upstream PR to FalkorDB docs/examples (temporal as-of traversal pattern) | 1h | — | PR link in README |

Cut order for these: T3.6 → T2.4b scale test → T1.7d (fall back to "proposed, not verified" labeling). Keep T1.5b, T1.7c and T3.0.

## 14c. Real-data tasks (see PLAN.md §5 and §3.4-3.6 above)

| ID | Task | Est | When | Done when |
|---|---|---|---|---|
| **T0.4a** | `Connector` protocol + `ingest()`; refactor `SyntheticConnector` onto it | 1h | Day 1, with T0.4 | seed runs via `ingest()` |
| **R1** | OTel Demo up in Docker; confirm ports, flagd config path, Jaeger API; create `tracebrain-lab` repo + `CODEOWNERS` | 1.5h | Day 1 evening (parallel lane) | flags flip and traces are visible in Jaeger |
| **R2** | `OtelTraceConnector` + `CodeownersConnector` + `GitDeployConnector` | 2.5h | Day 2 | `tenant_lab` graph has a real topology, owners and deploys |
| **R3** | `lab/inject.py` + `scenarios.yaml` (6-10 scenarios) + `watch.py` → `POST /alerts` | 2h | Day 2 | an injected failure auto-creates an incident and investigation |
| R4 | Run all scenarios, record `ground_truth_real.json`; add "real lab" rows to results | 1h | Day 3 | real-incident rows in results.md |
| R5 | RCAEval license check + `rcaeval_subset.py` (about 30 RE2 cases) | 2h | Day 3, if time | benchmark rows in results.md, or a documented skip |

**Stop-loss:** if R1 isn't working after about 3 hours, drop R1-R4 and ship on synthetic + RCAEval. Decide by **Day 2 at 12:00**.
**Team split:** with a teammate, R1-R4 is their whole lane. Solo: do R1 on Day 1 evening, and do R2-R3 only if T1.7 is done by Day 2 afternoon.

## 14d. Earned autonomy tasks (PLAN.md §9b), Oct 16 late / Oct 17 AM

**Start only after** the Oct 16 UI and eval exit checks pass. First item on the cut list.
**Design constraint:** the investigation state machine does **not** change. Mitigation state lives on the `Action` node, and long-term memory is still written only by `curator.review`.

### Design
- **Customer impact** (`impact.py`): synthetic `ServiceRec` gains `journey` (`browse`: frontend, productcatalog, recommendation, ad, currency/-v2; `cart`: cart, redis-cart; `purchase`: checkout, payment, shipping, email). Impact = journeys of {alerted service} ∪ blast radius, e.g. `{"journeys": ["purchase", "browse"], "customer_facing": true}`. Stored on the Investigation and shown in the UI header. Real connectors set `journey` from config.
- **Timing**: `episodic.set_state` also writes `<state>_at` (e.g. `v.triaged_at`). Mitigation writes `v.mitigated_at`. Derived: `time_to_cause = hypothesized_at - started`, `time_to_mitigation = mitigated_at - started`. Human approval wait is reported separately; we never invent it.
- **Policy** (`policy.py`, deterministic, pure function over graph facts):
  ```python
  def decide(tenant, inv_id) -> dict:
      # returns {"mode": "auto" | "approval_required" | "none",
      #          "checks": [{"name", "passed", "detail"}...], "deploy_id": ...}
  CHECKS = [
    "not_abstained",          # there is a top hypothesis
    "sandbox_verified",       # top hypothesis has Verification.clears = true
    "reversible_change",      # Deploy.kind in {config, flag}
    "earned_by_memory",       # non-retracted Lesson(symptom, service -> deploy's service), weight >= 0.5, learned before t
    "evidence_complete",      # all claims of the top hypothesis verified
    "clear_margin",           # score(#1) - score(#2) >= 0.25, or a single suspect
    "customers_affected",     # impact.customer_facing
    "autonomy_enabled",       # tenant kill switch (TenantSettings node), default ON for demo tenants
    "no_prior_auto_action",   # at most one automatic action per incident
  ]
  ```
  `mode = auto` iff all checks pass; `none` if abstained; otherwise `approval_required`. The decision and its checks are stored on the rollback `Action` as `policy_json` and streamed as a `policy` event, so the UI shows the checklist.
- **Executor** (`executor.py`):
  ```python
  class Executor(Protocol):
      name: str
      def rollback(self, tenant, deploy_id) -> dict: ...
      def undo(self, tenant, rollback_id) -> dict: ...
      def symptom_cleared(self, tenant, incident_id) -> bool | None: ...
  ```
  `SimulatedExecutor`: writes `(Rollback {id, ts, by, mode: 'auto'|'approved', simulated: true})-[:REVERTS]->(Deploy)`. `symptom_cleared` uses the same SyntheticEnvironment as verification (labelled simulated). `LabExecutor` (only with R1-R3): `git revert` in `tracebrain-lab`, flagd reload, poll Prometheus until recovered or timeout.
  **Flow:** execute → check symptom → if not cleared: `undo` + `Action.status = failed_undone` + escalate (page action, `escalated` event). If cleared: `Action.status = done_verified`, `v.mitigated_at`.
- **Handover message** (`handover.py`): a deterministic text from graph facts: symptom + start, customer impact, cause hypothesis + deploy + author + owner team, cited path (service names), what was done (auto/approved/proposed) + result, Undo endpoint. Stored on the page `Action` as `message`.
- **API**:
  - `POST /tenants/{t}/investigations/{inv}/mitigate` (human approval path; runs the same executor + check)
  - `POST /tenants/{t}/rollbacks/{id}/undo`
  - `GET/PUT /tenants/{t}/settings` (`autonomy_enabled`)
- **Orchestrator hook:** after `_verify` (whether or not it moved to VERIFIED), call `policy.decide`; if `auto`, execute immediately (before AWAITING_REVIEW is reached). The investigation still ends in `AWAITING_REVIEW` for the human's confirm/reject, and that review is what teaches memory.

### Tickets
| ID | Task | Est | Done when |
|---|---|---|---|
| **A1** | `journey` on services + `impact.py` + impact on Investigation + UI header | 0.5h | incident shows "purchase flow affected" |
| **A2** | `<state>_at` timestamps + `time_to_cause` / `time_to_mitigation` in run stats + UI timer | 0.5h | stats present on every investigation |
| **A3** | `policy.py` with the 9 checks, stored + streamed decision | 1h | first-time pattern → `approval_required` (fails `earned_by_memory`); after one confirmed review of the same pattern → `auto` |
| **A4** | `executor.py` (SimulatedExecutor), auto path in orchestrator, approval path endpoint, undo + escalate | 1h | auto rollback recorded as `Rollback` node; wrong-deploy rollback is undone + escalated |
| **A5** | `handover.py` + page action message | 0.5h | message names cause, deploy, owner, path, action, Undo |
| **A6** | Tests: policy matrix (each check failing alone → not auto), code-change never auto, kill switch, one auto action max, memory unchanged by auto actions until review, undo on failed check | 0.5h | all green |
| A7 | (stretch, needs R1-R3) `LabExecutor`: real `git revert` + Prometheus recovery check | 1.5h | real fault auto-mitigated in the OTel Demo |

### Eval additions (honest)
- Per incident: `time_to_cause`, `time_to_verified_fix`, and for repeats `time_to_mitigation (auto)`, all measured.
- Policy correctness on the test split: how often `auto` fired on a **wrong** deploy (target 0; report it whatever it is), and how often it correctly declined (first-time patterns, code changes, failed checks).
- No "time saved vs humans" claims: we have no human baseline data.

## 15. Risk register

| Risk | Mitigation |
|---|---|
| `all()` over path relationships or `shortestPath ... WHERE` unsupported | T0.2 finds out in hour 1. Fallback: filter edges in Python after fetching paths, or keep two relationship types (`DEPENDS_ON` current + versioned snapshots) |
| Graph algorithms can't filter by time | Use them only as a weak prior (centrality feature) and document it. Time-critical logic stays in Cypher |
| LLM invents edge ids | Faithfulness checker rejects them, and the prompt says "copy ids". Track the rate as a metric (this is a feature, not a bug) |
| Agent loops/wanders | `max_turns=12`, tool allowlists, `suspects_asof` returns a pre-ranked list |
| **Groq rate limits** (Developer-plan base for `gpt-oss-120b`: 30 RPM, **8K TPM, 200K tokens/day**, so only a handful of full investigations per day per model) | Response cache in `llm.py` (reruns cost 0 tokens); tool results truncated to 4K chars; compact system prompts; 429 backoff using `retry-after`; run the full eval once, spread over the day, and keep it cached. $0 budget: no paid plans. Check your actual limits at console.groq.com/settings/limits |
| LLM latency during eval | Groq is fast; mocked LLM for the concurrency test |
| UI eats Day 3 | Streamlit fallback consumes the same API. Decide by Day 3 13:00 |
| Deployment fails late | Deploy a skeleton on Day 2 evening (T2.8 can start early with only the API) |
