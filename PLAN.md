# Tracebrain: Build Plan (Graph Hacks, Oct 15-18 2026)

**Tracks entered:** Track 01 *Agents That Act on Connected Data* (primary) + Track 02 *Agent Memory and Coordination* (secondary).
Track 03 is named on submission only if time allows. It is not a build target.

**Positioning: evidence-backed root-cause analysis across time.**
Tracebrain rebuilds the service dependency graph as it was when the incident happened. It ranks suspicious deploys using connected evidence, checks every claim against real graph edges, and learns only from outcomes an engineer has confirmed.
The core contribution is three things together: **temporal graph reasoning + edge-level evidence verification + review-gated memory.** Don't pitch it as "a multi-agent AI that finds root causes"; other projects already do that.

**Guiding principle:** don't make it bigger. Make it more trustworthy, measurable and convincing end to end. One flow that works reliably, plus honest numbers, beats many half-finished features.

---

## 1. How we win each track

The judges' "key focus" bullets are below, each mapped to a concrete, demo-able feature. Every row must be visible in the demo video.

### Track 01: Agents That Act on Connected Data

| Judge focus | Tracebrain feature | Demo proof |
|---|---|---|
| Multi-hop reasoning | As-of blast radius (`DEPENDS_ON*1..5` filtered by `valid_from/valid_to`) and suspect paths across service → dependency → deploy → author | Path highlighted in UI |
| Graph queries/algorithms as agent tools | MCP tools wrapping Cypher + FalkorDB algorithms (BFS, shortest path, PageRank/betweenness for centrality) | Agent trace panel shows each tool call |
| Tool selection through MCP | One MCP server, about 8 tools. The agents choose tools themselves; nothing is hard-coded | Trace shows different tool sequences for different incidents |
| Actions based on what the graph shows | Agent **acts**: creates `Ticket` node assigned to owning team, proposes (simulated) rollback of top suspect deploy, pages owner (logged) | `Action` nodes appear in graph after run |
| Explainable results | Claim → edge-id mapping, checked deterministically (path faithfulness) | Green/red ticks per claim in UI |

### Track 02: Agent Memory and Coordination

| Judge focus | Tracebrain feature | Demo proof |
|---|---|---|
| Episodic memory | `Investigation` + `Step` nodes: every run is stored as an episode (what was tried, in what order, result) | Replay a past investigation from the graph |
| Semantic memory | `Cause` nodes with entity resolution ("db timeout" = "database timeouts"), `confidence`, `provenance` | Two incidents link to one Cause node |
| Procedural memory | `Runbook` / `Lesson` nodes: "for symptom X on service-type Y, check Z first", with `success_count` / `fail_count` | Second run uses the lesson and needs fewer tool calls |
| Persistent history across sessions | Investigation state lives only in the graph. Kill the process, restart, resume | Demo: stop server mid-investigation, resume |
| Shared state + handoffs | Agents coordinate through a **blackboard in the graph**: Triage writes `Finding` nodes, Investigator reads them; Curator reads both. No in-memory passing | Trace shows `HANDOFF` edges |
| High-concurrency reads/writes | Run 10-20 investigations in parallel against one FalkorDB instance; report throughput + zero corrupted episodes | Small table in README |
| Separate memory per tenant | One FalkorDB graph per team (`tenant_payments`, `tenant_platform`), selected per request | Query from tenant A never sees tenant B's lessons (leak test = 0) |
| Memory that updates over time | Human confirm gate; confidence ↑ on re-confirmation, ↓ on rejection; `retracted` flag | Reject a wrong cause live, show it stops being recalled |

---

## 2. Architecture

```
            ┌──────────── Web UI (graph view + agent trace + confirm button) ────────────┐
            │                                                                             │
   Alert ──►│  Orchestrator (FastAPI)                                                     │
            │     │                                                                       │
            │     ├─► Triage agent ──────┐   writes Finding(blast_radius, owners)         │
            │     ├─► Investigator agent ┤   reads Findings, writes Hypothesis + Actions   │
            │     └─► Curator agent ─────┘   after human confirm: Cause/Lesson write-back  │
            │                │                                                            │
            │         MCP server (tools)                                                  │
            │                │                                                            │
            └──────────► FalkorDB (one graph per tenant) ◄────────────────────────────────┘
```

- **LLM ($0 budget, free tiers only):** one OpenAI-compatible client (`tracebrain/llm.py`) with automatic fallback **Groq → Cerebras → Gemini**. Groq (`openai/gpt-oss-120b`) for building and the demo, since it's fastest. Cerebras (`gpt-oss-120b`, 1M tokens/day) for the evaluation runs. Gemini is the last resort. Every response is cached on disk, and every result records the provider and model that produced it.
- **MCP server:** Python (`mcp` / FastMCP) + `falkordb` client.
- **Backend:** FastAPI, with server-sent events to stream the agent trace to the UI.
- **UI:** Vite + React + Cytoscape.js for the graph (fallback: Streamlit + pyvis if frontend time runs out).
- **Deploy:** FalkorDB Cloud (or Docker on a VM) + Render/Railway for the API/UI. Docker Compose for local setup.

### Three agents, one job each

1. **Triage:** input is the alert. Calls `blast_radius`, `owners_of`, `recall_similar`. Writes `Finding` nodes.
2. **Investigator:** reads Triage's Findings from the graph. Calls `suspects_asof`, `path_between`, `centrality`, `recall_lessons`. Ranks suspects with the scoring function. Writes `Hypothesis` + structured claims + `Action` proposals.
3. **Curator (memory agent):** runs **only after a human confirms or rejects**. Entity-resolves the cause, upserts `Cause`/`Lesson`, updates confidence and success counts, links provenance.

The Curator is what makes Track 02 real: memory is managed by an agent, not a side effect.

---

## 3. Graph data model

### World graph (facts about the system)
**Nodes:** `Service{name, tier}`, `Team{name}`, `Person{name}`, `Deploy{id, ts, change_size, author, service}`, `Alert{id, ts, service, symptom}`, `Incident{id, ts, severity, status}`, `Runbook{id, title, steps}`

**Edges:**
- `(Service)-[:DEPENDS_ON {valid_from, valid_to}]->(Service)`
- `(Team)-[:OWNS {valid_from, valid_to}]->(Service)`
- `(Person)-[:MEMBER_OF]->(Team)`
- `(Deploy)-[:DEPLOYED_TO]->(Service)`, `(Person)-[:AUTHORED]->(Deploy)`
- `(Alert)-[:FIRED_ON]->(Service)`, `(Incident)-[:TRIGGERED_BY]->(Alert)`, `(Incident)-[:AFFECTED]->(Service)`

### Memory graph (what agents learned)
**Nodes:** `Investigation{id, started, status, tenant}`, `Step{n, agent, tool, args, result_summary, ts}`, `Finding{kind, payload}`, `Hypothesis{rank, score, features}`, `Claim{text, verified}`, `Action{kind, target, status}`, `Cause{name, aliases[], confidence, retracted}`, `Lesson{symptom, service_type, check_first, success_count, fail_count}`

**Edges:**
- `(Incident)-[:INVESTIGATED_IN]->(Investigation)-[:HAS_STEP]->(Step)-[:NEXT]->(Step)` (episodic)
- `(Investigation)-[:PRODUCED]->(Finding)`, `(Finding)-[:HANDOFF {from, to}]->(Hypothesis)` (coordination)
- `(Hypothesis)-[:SUSPECTS]->(Deploy)`, `(Claim)-[:SUPPORTED_BY]->(edge ref)` (explainability)
- `(Incident)-[:CAUSED_BY {confirmed_by, ts, confidence}]->(Cause)` (semantic)
- `(Cause)-[:FIXED_BY]->(Runbook)`, `(Lesson)-[:LEARNED_FROM]->(Incident)` (procedural + provenance)

**Tenancy:** `db.select_graph(f"tenant_{team}")`. The same schema is used in every graph, and no cross-graph queries are allowed.

---

## 4. MCP tools (verify FalkorDB algorithm support first, Day 1, hour 1)

| Tool | Backing query | Used by |
|---|---|---|
| `blast_radius(service, t)` | var-length `DEPENDS_ON` reversed, as-of `t` | Triage |
| `owners_of(services[], t)` | `OWNS` as-of `t` → Team → Person | Triage |
| `suspects_asof(service, t, window)` | deploys on service + its deps in `[t-window, t]` | Investigator |
| `path_between(a, b, t)` | shortest path (FalkorDB `shortestPath` / `algo.SPpaths`) | Investigator |
| `centrality(t)` | PageRank / betweenness (if supported) | Investigator (score feature) |
| `recall_similar(symptom, service)` | past Incidents with same symptom + `CAUSED_BY` (non-retracted) | Triage |
| `recall_lessons(symptom, service_type)` | `Lesson` ordered by `success_count - fail_count` | Investigator |
| `create_action(kind, target)` | writes `Action` node (ticket / rollback proposal / page) | Investigator |

### Core Cypher (check the syntax against FalkorDB on Day 1)

```cypher
// As-of blast radius: who is hurt if $svc fails at time $t
MATCH p = (up:Service)-[:DEPENDS_ON*1..5]->(f:Service {name: $svc})
WHERE all(r IN relationships(p) WHERE r.valid_from <= $t AND (r.valid_to IS NULL OR r.valid_to > $t))
RETURN DISTINCT up.name AS affected, length(p) AS hops
ORDER BY hops
```

```cypher
// As-of suspects: deploys on the failing service or anything it depends on, inside the window
MATCH p = (f:Service {name: $svc})-[:DEPENDS_ON*0..3]->(s:Service)
WHERE all(r IN relationships(p) WHERE r.valid_from <= $t AND (r.valid_to IS NULL OR r.valid_to > $t))
MATCH (d:Deploy)-[:DEPLOYED_TO]->(s)
WHERE d.ts <= $t AND d.ts >= $t - $window
RETURN d.id, s.name, d.ts, d.change_size, length(p) AS proximity
```

```cypher
// Procedural recall
MATCH (l:Lesson {symptom: $symptom, service_type: $stype})-[:LEARNED_FROM]->(i:Incident)
WHERE NOT coalesce(l.retracted, false)
RETURN l.check_first, l.success_count, l.fail_count, collect(i.id) AS evidence
ORDER BY l.success_count - l.fail_count DESC LIMIT 3
```

### Suspect score
`score = w1·proximity⁻¹ + w2·recency + w3·change_size_norm + w4·service_fail_rate + w5·centrality + w6·lesson_match`

`lesson_match` is the memory feature. It is the reason the second run is faster and more accurate.

### Path faithfulness (cheap and deterministic)
The Investigator must output JSON: `[{claim, edge_ids: [...]}]`. A checker confirms that each `edge_id` exists in the returned path(s) and that the edge's endpoints match the entities named in the claim.
`faithfulness = verified_claims / total_claims`. Claims with unverified edges are rendered red in the UI and excluded from the final answer.

---

## 5. Data: real where it counts, synthetic where volume is needed

**Design rule: connectors, not a hard-wired dataset.** Every part of the graph is loaded through a small connector interface (IMPLEMENTATION.md §3.4). The synthetic generator is just one connector. A real team could plug in their own traces, GitHub, CODEOWNERS and Alertmanager without touching the agents, graph or UI. That's what makes Tracebrain usable in real life and not just a demo.

| Graph piece | Real-life source (connector) | Hackathon source |
|---|---|---|
| `DEPENDS_ON {valid_from, valid_to}` | OpenTelemetry traces (Jaeger API) | **OTel Demo traces (real)** + synthetic |
| `Deploy` | GitHub commits/releases/deployments | **real commits in our own `tracebrain-lab` repo** (config changes to the demo) + synthetic |
| `OWNS`, `Team`, `Person` | `CODEOWNERS` file | `CODEOWNERS` in `tracebrain-lab` (fictional team names) |
| `Alert` | Alertmanager / Grafana webhook → `POST /alerts` | Same webhook, fired by a watcher script or Alertmanager |
| `Cause`, `Runbook` | Internal postmortems (markdown) | Public postmortems (danluu/post-mortems), cited |

### Three data sources, three jobs

1. **Own real data: OpenTelemetry Demo (main demo).**
   - The official 15-service shop runs locally in Docker Compose. Give Docker about 8 GB; this laptop has 16 GB.
   - Incidents are triggered with its built-in **flagd failure flags** at `http://localhost:8080/feature`. Usable flags: `paymentFailure`, `paymentUnreachable`, `cartFailure`, `productCatalogFailure`, `productCatalogLockContention`, `adHighCpu`, `adFailure`, `recommendationCacheFailure`, `emailMemoryLeak`, `imageSlowLoad`, `intlShippingSlowdown`, `kafkaQueueProblems`.
   - **Real deploys:** each flag flip is preceded by a real git commit in `tracebrain-lab` (the flag config change *is* the deploy, which is honest). Unrelated decoy commits land on other services around the same time.
   - **Real topology over time:** DEPENDS_ON edges come from trace spans, with `valid_from` = first seen and `valid_to` = last seen. Restart a service with a changed dependency to get a real topology change.
   - **Target: 6-10 real incidents**, ground truth logged by the injection script. One of these is the video demo.
2. **Public benchmark: RCAEval (credibility).**
   - A published RCA benchmark: 735 labelled failure cases on Online Boutique, Sock Shop and Train Ticket (RE1 metrics-only, RE2 metrics+logs+traces, RE3 code-level faults).
   - We use **RE2 traces** for DEPENDS_ON and the labelled root-cause service. That lets us report "root-cause service top-3 on a public benchmark subset".
   - Caveat: RCAEval has no deploy history, so it tests the *topology + blast-radius + service ranking* part, not deploy ranking. Say this clearly.
   - **License check first** (GitHub `phamquiluan/RCAEval` + Zenodo record). If the license isn't compatible, skip it.
3. **Synthetic (volume + edge cases).**
   - The generator from before (Online Boutique-shaped topology, 2 tenants, about 120 deploys, 24 incidents per tenant + 2 abstention cases).
   - Used for the memory ON/OFF repeats, decoys, dependency changes, the tenant leak test and the 200-service scale test. It's labelled synthetic everywhere it appears.

**Fallback:** if the OTel Demo or its trace export eats more than about 3 hours, stop and ship on synthetic + RCAEval. The connector design means nothing else changes.

**README data statement:** *"Main demo on live incidents injected into the OpenTelemetry Demo; benchmark on a subset of the public RCAEval dataset; volume and edge-case tests on clearly labelled synthetic data."*

---

## 6. Evaluation (small, honest, demo-able)

| Metric | Comparison |
|---|---|
| Root cause top-3 accuracy | B0 most-recent-deploy vs B1 vector-RAG (FalkorDB vector index, no traversal) vs Tracebrain |
| Blast radius F1 | Naive (current topology) vs as-of (temporal). Shows why time matters |
| Path faithfulness | % claims verified |
| Memory benefit | Tool calls + steps on repeat incidents: memory OFF vs ON |
| Memory safety | Inject 1 wrong cause: with confirm gate vs without, measure wrong recalls |
| Tenant isolation | Cross-tenant leak count (target 0) |
| Concurrency | N=10/20 parallel investigations: throughput, p95 latency, 0 corrupted episodes |
| **Failure-mode suite** | Pass/fail per scenario: newer irrelevant deploy (decoy), dependency changed before incident, unsupported claim, previously rejected cause, cross-tenant probe, **no deploy at fault → agent must abstain** |

Ground-truth labels are used **only by the evaluation**. Agents never see them: deploy summaries and incident text must not name the injected cause, and a leakage check enforces this.

Report whatever numbers you actually get. A table with honest numbers is stronger than a target table.

---

## 7. Day-by-day schedule

Work lanes, if you're a team: **A** = graph/data/eval, **B** = agents/MCP, **C** = UI/demo/deploy. Solo: do the lanes top to bottom each day.

### Day 1 (Oct 15): graph + tools
- [ ] A: FalkorDB in Docker, test algorithm support (BFS, shortestPath, PageRank, betweenness). Write down the results.
- [ ] A: Schema + generator script → load both tenant graphs. Check with FalkorDB Browser.
- [ ] A: Write and test the 3 core Cypher queries (blast radius, suspects, recall).
- [ ] B: MCP server skeleton with `blast_radius`, `owners_of`, `suspects_asof`, `path_between`.
- [ ] B: Minimal single Groq tool-use loop calling the MCP server end-to-end on 1 incident.
- [ ] C: Repo layout, Docker Compose (FalkorDB + API), README skeleton with data model.
- **Exit check:** one incident goes from alert to ranked suspects through MCP.

### Day 2 (Oct 16): agents + memory
- [ ] B: Split into Triage / Investigator / Curator. Handoff via `Finding` nodes only.
- [ ] B: Scoring function, structured claims output, faithfulness checker.
- [ ] B: `create_action` (Ticket / rollback proposal / page owner).
- [ ] A: Episodic logging (`Investigation`→`Step` chain), resume-after-restart.
- [ ] A: Curator: confirm/reject API, entity resolution (normalize + alias list + LLM fallback), confidence and success counts, retract.
- [ ] C: FastAPI endpoints + SSE trace stream; start UI (graph view + trace panel).
- **Exit check:** run incident type X twice. The second run recalls the Lesson and needs fewer tool calls.

### Day 3 (Oct 17): UI + evaluation
- [ ] C: Highlighted path in Cytoscape, claim list with ✓/✗, Confirm/Reject buttons, tenant switcher.
- [ ] A: Eval harness: B0, B1, Tracebrain, memory OFF/ON, temporal vs naive, leak test, concurrency test.
- [ ] B: Tune weights on the "seen" split only. Fix the agent failure modes found by the eval.
- [ ] C: Deploy (FalkorDB Cloud + Render/Railway). Make sure the public URL works.
- **Exit check:** results table filled in; deployed app runs one full demo.

### Day 4 (Oct 18, deadline 11:59 PM IST): ship
- [ ] Morning: bug fixes only, no new features. Freeze code at 6 PM.
- [ ] README: setup, graph data model diagram, **all Cypher queries/algorithms used**, results table, tracks entered, AI-assistant disclosure, synthetic-data note.
- [ ] Demo video (3-4 min, see script below).
- [ ] Optional blog post (AirPods side prize). Can reuse the README.
- [ ] Submit by 9 PM to leave a buffer.

### Cut order if behind
1. Concurrency benchmark → 2. Memory-poisoning test → 3. Real Online Boutique stretch → 4. Cytoscape UI (fall back to Streamlit) → 5. B1 vector baseline.

**Never cut:** temporal as-of queries, MCP tools, the Finding handoff between agents, the confirm-gated memory write-back, path faithfulness, the memory OFF vs ON result, B0 + B1 baselines on the test split, the failure-mode suite.

---

## 8. Demo video script (about 3.5 min)

1. **0:00 Problem (20 s):** an incident needs connections across services, deploys, owners and history.
2. **0:20 Incident #1, Payments tenant (60 s):** `checkout` starts timing out. The injected cause is a config change on `redis-cart`, two hops away. A **newer, unrelated deploy** acts as the decoy. Triage shows the blast radius and owners. Investigator ranks suspects and shows **why** each scored (feature bars); the culprit beats the decoy. The path is highlighted and claims show ✓. Agent creates a ticket for the owning team.
3. **1:20 Temporal + evidence (30 s):** the naive current-topology query gives the wrong answer; the as-of query gives the right one. Then show the checker rejecting an unsupported claim (✗ with its reason). If no real one occurred in the run, use the labeled test fixture.
4. **1:50 Memory (45 s):** engineer clicks *Confirm*. Curator writes Cause + Lesson with provenance (show the nodes). Restart the server. A related incident arrives with memory ON: the agent recalls the lesson. Show the **real** ON-vs-OFF tool-call and accuracy numbers from the eval; don't use scripted numbers.
5. **2:35 Safety + tenancy (25 s):** reject a wrong cause and its influence drops. Switch to the Platform tenant; there are zero Payments lessons. A no-deploy incident shows the agent abstaining instead of inventing a culprit.
6. **3:00 Results table (20 s):** baselines vs Tracebrain, memory ON/OFF, failure-suite pass/fail, then the architecture slide and "the graph is the product: remove FalkorDB and nothing works."

---

## 9. Lessons adopted from winning projects

Sources: BlackBox (DataHub Agent Hackathon 2026 Grand Prize), Data-OnCall (DataHub × Nebius, 1st place), HiveOps (Devpost).

| # | Lesson | Where it came from | Change to Tracebrain |
|---|---|---|---|
| L1 | *"The LLM decides what to investigate; deterministic tools decide what is true."* | BlackBox | Our core principle, in the README and video. Agents never write Cypher or compute scores; tools do. |
| L2 | Gates, not post-hoc checks | BlackBox `confirm_root_cause` rejected without cited evidence | `submit_hypotheses` is a **gate**: unverified claims or missing score evidence → tool returns an error and the agent must fix it (max 2 retries). |
| L3 | Explicit incident state machine | BlackBox `ROOT_CAUSE_CONFIRMED` pause | `OPEN → TRIAGED → HYPOTHESIZED → VERIFIED → AWAITING_REVIEW → CONFIRMED/REJECTED → LEARNED`, stored on `Investigation` and shown as a stepper in the UI. |
| L4 | Act, then verify | BlackBox READ→PROVE→ACT→VERIFY→WRITE; HiveOps sandbox-tests fixes before human review | **Counterfactual rollback check:** before review, simulate rolling back the top suspect in a sandbox copy of the world and check whether the symptom clears. Humans review a *verified* proposal. Wrong rollbacks are caught and counted. |
| L5 | A bad-action rejection test | BlackBox `bad_repair_rejected` | Failure suite adds: "rolling back the decoy deploy does not clear the symptom → rejected". |
| L6 | Safety constraints enforced in code, with a table | BlackBox safety-envelope table; its SQL guard bypass | README table *constraint → enforcing file*. All agent-reachable queries go through `ro_query` (read-only); writes happen only through memory modules or the review endpoint. |
| L7 | Honest ablation, even when the result is unflattering | BlackBox admits its no-DataHub ablation still found the cause | Ablation: Tracebrain with graph tools replaced by flat lists. Report it honestly, plus a **scale test** (200-service generated topology) where graph traversal should matter more. |
| L8 | Judges can verify without keys | BlackBox `make judge-check`, 45-second judge path | `make judge-check` runs query tests + failure suite on recorded transcripts with no API key. README opens with a 45-second judge path. |
| L9 | Concrete run stats | BlackBox: 13 turns / 24 tool calls / 180 s; Data-OnCall: 54.8 s, about 2¢ | Report turns, tool calls, seconds and **cost per investigation**. Commit one unedited run transcript. |
| L10 | Exact, checkable results | Data-OnCall matched planted bugs by exact row count | The results table shows the exact culprit ID per test incident (hit/miss), not just percentages. |
| L11 | Vivid motivating story | Data-OnCall's hallucinating-agent story | Lead with one 2 AM incident story (the decoy deploy vs the real config change two hops away, made by another team). |
| L12 | Contribute upstream | BlackBox opened 2 DataHub OSS PRs | Day 4 stretch: PR a "temporal as-of traversal" example or doc to FalkorDB. FalkorDB is the sponsor and judge. |

**What we don't copy:** fine-tuning a model (Data-OnCall's LoRA), four different LLM providers, or a heavy Next.js command center. They cost time without strengthening our main claims.

**Competition signal:** incident response with memory is a crowded idea (RecallOps, MemoryOps, OpsMind, HiveOps). What sets us apart has to be visible in the first 30 seconds: **as-of-time graph + evidence gates + verified actions**.

## 10. Rule compliance checklist

- [ ] FalkorDB is the only datastore (episodes, memory and tenants included). Rule 2/3.
- [ ] Only synthetic + public postmortem data, cited. Rule 6.
- [ ] All code written after Oct 15 00:01 IST. Rule 8.
- [ ] Public repo, README + data model, Cypher queries, demo video, deployment/setup, tracks named. Rule 10.
- [ ] AI-assistant use disclosed in README. Rule 11.
- [ ] Every team member can explain the schema, the as-of query and the scoring. Rule 12.
