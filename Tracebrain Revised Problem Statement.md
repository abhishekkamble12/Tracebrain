# Tracebrain: Revised Problem Statement

A graph-powered, multi-agent incident investigation system built on FalkorDB.

## 1. Context

A single production incident touches many things at once: services, the teams that own them, recent deploys, past incidents, runbooks, and decisions from old postmortems. This knowledge is scattered across monitoring, git, ticketing, chat, and wikis, and most of it lives in the heads of a few senior people.

## 2. Problem

When an incident fires, the responder has to answer questions that are about connections, not individual records:

- Which services are affected downstream of the failing one? (blast radius)
- Which recent deploy or config change sits on the path to this failure? (suspects)
- Who has fixed something like this before, and what worked? (precedent)
- Which decision or postmortem created this risk in the first place? (provenance)

Today this means jumping between 5-6 tools and stitching context together by hand under time pressure. The result is slow root-cause analysis, repeated incidents, and heavy dependence on whoever is on-call and "knows the system".

## 3. Why Existing Approaches Fall Short

Existing AIOps tools (PagerDuty AIOps, Rootly, incident.io, Cleric) and generic RAG/GraphRAG systems fail in three ways:

1. **They don't see structure.** Vector search returns similar text but cannot follow "A depends on B, which team C deployed yesterday."
2. **They don't understand time.** "Which change landed before this incident" is a temporal question. A static topology cannot answer it.
3. **They aren't verifiable.** Answers arrive as paragraphs. Even when a path is shown, nobody checks whether the claims are actually supported by it or hallucinated by the LLM.

**Tracebrain's differentiator:** deterministic graph traversal to find suspects, every claim verified against the edges of the returned path (**path faithfulness**), and confirmed learnings written back into the graph with provenance.

## 4. Why a Graph

Blast radius, ownership chains, and root-cause paths are single traversals. In a relational or vector store they become expensive stitched joins at every agent step. In a graph they are one query, and the returned path is the explanation. Remove the graph and there is no way to compute blast radius, causal paths, or "similar incident and what fixed it."

## 5. Proposed Solution

Tracebrain uses FalkorDB as its single context layer to investigate incidents.

### Agents (two, deliberately)

- **Triage agent:** reads the alert, finds affected services, blast radius, and owners (via ownership edges).
- **Investigator agent:** finds suspect deploys/changes in a time-windowed graph, ranks them with an explicit scoring function, and calls graph algorithms exposed as MCP tools.

### Suspect scoring (ablation-ready)

`score = w1·path_proximity + w2·deploy_recency + w3·change_size + w4·service_historical_failure_rate + w5·centrality`

Each feature is toggled on/off in an ablation to show how much it contributes. Weights are hand-tuned or found by a small grid search, then validated on a held-out set.

### Memory loop (guarded)

When an incident closes, the proposed cause/fix/runbook is written to the graph only after **human confirmation**, with `confidence` and `provenance` (source incident, confirmer, timestamp). Cause nodes go through **entity resolution** so "db timeout" and "database timeouts" resolve to one node. A retract flag handles wrong entries.

### Output

Every answer comes with the exact graph path, highlighted in the UI, plus a claim-to-edge mapping.

## 6. Graph Data Model

**Nodes:** Service, Team, Person, Deploy (`ts`, `change_size`, `author`), Incident, Cause, Runbook, Ticket, Postmortem/Decision, Alert.

**Edges:** DEPENDS\_ON, OWNS, MEMBER\_OF, DEPLOYED, AFFECTED, CAUSED\_BY, FIXED\_BY, RESOLVED, DERIVED\_FROM, ABOUT.

**Temporal modeling:** DEPENDS\_ON and OWNS carry `valid_from` / `valid_to`. The Investigator always queries the snapshot valid at incident time `t` (as-of query), so stale topology never produces a wrong root cause.

**Tenancy:** one isolated graph per team using FalkorDB's multigraph support. This is a lightweight demo only (real auth/RBAC is a non-goal).

## 7. Data

**Primary: fault injection on a real microservices app.**

- Run the OpenTelemetry Demo or Google Online Boutique and generate incidents using feature flags / fault injection.
- Derive DEPENDS\_ON edges from real traces, not a hand-written topology.
- Ground truth is known (you know what you injected).
- For the memory loop, seed some Cause/Runbook nodes from public postmortems (e.g. the danluu/post-mortems repo).

**Fallback:** if infra setup eats too much time, use a generated topology, but label it clearly as synthetic in the README.

## 8. Target Users

On-call engineers and SREs, engineering managers (ownership clarity), and new team members who lack institutional knowledge.

## 9. Evaluation (breaking the circularity)

### Baselines (same incidents, same data)

- **B0:** most-recent-deploy-wins
- **B1:** plain vector RAG
- **B2:** single LLM agent with tools, no graph (SQL/recursive CTE equivalent)
- **B3:** single-agent with graph vs the two-agent Tracebrain (to justify multi-agent; report the result honestly either way)

### Split

Divide incidents into a **calibration set** (tune weights) and a **held-out test set**. For the memory test, keep "seen incident types" and "unseen types" separate.

### Metrics (illustrative targets; final numbers reported honestly)

| Metric | Definition | Target |
| --- | --- | --- |
| Root cause top-3 | Injected cause appears in the agent's top-3 suspects | ≥ 80% (compared against B0/B1) |
| Blast radius F1 | Predicted vs ground-truth dependency set | ≥ 0.9 |
| Path faithfulness | Share of answer claims verifiable from edges in the returned path | ≥ 95% |
| Memory benefit | Tool calls + steps to correct fix on repeated incident types, before vs after write-back (held-out) | ≥ 30% reduction |
| Memory safety | Inject a wrong cause and measure how much it poisons the next incident, with vs without the confirm gate | report |
| Tenant isolation | Cross-tenant data leaks | 0 |
| Latency | p50/p95 per tool call and end-to-end investigation | report |

"Faster" means tool calls and reasoning steps (wall-clock is noisy). Every tool call is logged as an agent trace, useful for both debugging and the demo.

## 10. Constraints

- 4-day hackathon window; FalkorDB is the primary and central datastore.
- No private or restricted data.
- First verify which algorithms FalkorDB natively supports (PageRank, BFS, shortest path, WCC, etc.) and design MCP tools only around what is actually available.

## 11. Non-Goals

A comms/notification agent (drafting messages is an easy LLM task, not a hard graph problem; owners come out of Triage), real Slack/Jira/PagerDuty integrations, auth/RBAC, automated rollbacks on real infrastructure, and production-scale ingestion.

## 12. 4-Day Plan (with cut-list)

| Day | Deliverable |
| --- | --- |
| 1 | Online Boutique/OTel demo + fault injection, trace-to-graph ingestion, temporal schema, 15-20 labeled incidents |
| 2 | Triage + Investigator agents, scoring function, MCP tools, agent trace logging |
| 3 | Eval harness (baselines B0-B2, held-out split, faithfulness checker), memory loop with confirm gate |
| 4 | Highlighted-path UI, ablation + results table, README, demo video |

**If time runs short, cut in this order:** multi-tenancy demo, B3 comparison, memory-poisoning test.

**Never cut:** baselines, held-out split, path faithfulness.

## Resume Bullet This Project Can Yield

> Built Tracebrain, a FalkorDB-backed incident investigation agent with temporal graph modeling from real OpenTelemetry traces; outperformed vector-RAG and recent-deploy baselines on held-out fault-injection incidents (top-3 root cause X% vs Y%), with Z% path-faithful answers and N% fewer tool calls after confirmed memory write-back.

Fill in X, Y, Z, N only when you have real numbers. The current targets are just targets.
