# Tracebrain Frontend: Master Architecture & UI/UX Plan

> **The Sovereign Incident Console for SREs & Graph-Powered Root Cause Analysis**
> Companion to [PLAN.md](../PLAN.md) and [IMPLEMENTATION.md](../IMPLEMENTATION.md).

---

## Executive Summary & Vision

Tracebrain is a multi-agent, temporal graph-powered incident investigation system built on **FalkorDB**. When a critical production incident strikes, on-call engineers cannot afford to sift through noisy dashboards or hallucinated LLM text. They need an **instrument-grade, evidence-backed command center** that answers three questions instantly:
1. **What is broken and downstream?** (Blast radius across the as-of topology)
2. **What change caused it and why?** (Deterministic suspect ranking + path-verified claims)
3. **What have we learned before?** (Human-in-the-loop institutional memory that accelerates repeat investigations)

### The UI Philosophy: "Calm Authority, Radical Transparency, Instant Wow"
- **Instrument Panel, Not a Dashboard:** Inspired by Linear, Honeycomb, and high-reliability aerospace consoles. Every pixel serves a purpose. No decorative neon gradients or distracting widgets.
- **Radical Transparency:** The graph is the primary visual surface. Every LLM claim illuminates its exact multi-hop causal path on screen. Hallucinated or unverifiable claims are exposed with explicit rejection reasons.
- **Instant Demo Impact:** A judge or SRE lands on the page and grasps the power of temporal graph analysis within 30 seconds via the **Demo Scenario Quick-Bar**, the **Temporal Time Scrubber ("As-Of" vs "Now")**, and the **Live Multi-Agent Stream**.

---

## 1. Persona & Journey Architecture

### 1.1 Key Personas
| Persona | Context & Stakes | Prime UI Need | Key Interaction |
|---|---|---|---|
| **Primary: On-Call SRE** | Paged at 2 AM, high cognitive load, under pressure to mitigate. | Immediate blast radius clarity, ranked suspect deploys, verified evidence path, 1-click confirm/rollback. | Clicks incident &rarr; runs investigation &rarr; inspects highlighted cited path &rarr; executes review. |
| **Secondary: Service Owner / Reviewer** | Inspecting post-incident proposals, validating cause attribution. | Inspect claim-to-edge fidelity, redirect suspect if #1 is a decoy, authorize lesson write-back. | Expands suspect card &rarr; hovers claims &rarr; edits distilled cause &rarr; commits to memory. |
| **Tertiary: Hackathon Judge / Evaluator** | Evaluating innovation, technical depth, and UX within a 3-minute video or 45-second live walkthrough. | Immediate proof of temporal graph superiority, multi-agent cooperation, and memory recall gains. | Uses Demo Scenario Quick-Bar &rarr; toggles As-Of vs Now &rarr; views Memory ON vs OFF tool-call savings. |

### 1.2 The "Judge in 30 Seconds" Quick-Bar
A persistent top bar selector allowing instant loading of verified demo beats from [PLAN.md §8](../PLAN.md):
- 🎯 **Beat 1: The Inc:001 Mystery:** `checkout` timeout caused by a config change on `redis-cart` 2 hops away, correctly beating a newer decoy deploy.
- ⏳ **Beat 2: Temporal Reality Check:** Switching between "As-Of" and "Now" exposes why static analysis yields the wrong root cause after Day 24's `currency-v2` migration.
- 🧠 **Beat 3: Institutional Memory in Action:** Running a repeat incident with Memory ON recalls the learned rule, reducing tool calls and diagnosing the culprit at Rank #1.
- 🛡️ **Beat 4: Counterfactual Sandbox Verification:** Simulated rollback verifies the fix in an isolated sandbox before human sign-off.
- 🚫 **Beat 5: Hallucination Resistance & Abstention:** Unverifiable claims flagged in red with exact graph check failures; incidents with no deploy at fault result in graceful abstention.

---

## 2. Visual Design System: The Obsidian & Cobalt Palette

A purpose-built dark theme designed for long incident sessions, high contrast readability, and broadcast-ready video capture.

### 2.1 Design Tokens (`ui/src/styles/tokens.css`)

```css
:root {
  /* Surfaces & Canvas */
  --bg-deep: #07090E;         /* Deep canvas */
  --bg-canvas: #0B0E14;       /* Main page background */
  --surface-panel: #11151F;   /* Docked panels & rails */
  --surface-card: #161C2A;    /* Elevated cards & nodes */
  --surface-hover: #1D2436;   /* Interactive hover states */
  --surface-glass: rgba(17, 21, 31, 0.75); /* Glassmorphism overlays */

  /* Hairlines & Borders */
  --border-subtle: #1C2333;   /* Default dividing lines */
  --border-strong: #2A344C;   /* Card contours, active inputs */
  --border-focus: #7C8CFF;    /* Accessibility focus rings */

  /* Typography Scale */
  --text-primary: #F1F4FA;   /* 13px/20px headings & body */
  --text-secondary: #9DA8BE; /* 12px/16px metadata, subheadings */
  --text-faint: #67748E;     /* 11px uppercase labels (≥4.5:1 ratio) */
  --text-inverse: #07090E;   /* Text on high-contrast badges */

  /* Accent & Core Brand */
  --accent: #7C8CFF;         /* Electric Periwinkle: focus, selection */
  --accent-glow: rgba(124, 140, 255, 0.15);

  /* Evidence & Investigation Status */
  --status-ok: #2DD4BF;      /* Emerald: verified claim, sandbox cleared, learned */
  --status-bad: #F43F5E;     /* Crimson: alert, unverified claim, rejected, failed */
  --status-warn: #F59E0B;    /* Amber: blast radius, awaiting review, model waiting */
  --status-suspect: #FB923C; /* Tangerine: suspect deploys, cited causal path */

  /* Multi-Agent Color Identities */
  --agent-triage: #38BDF8;      /* Sky Blue: blast radius & ownership */
  --agent-investigator: #A855F7;/* Purple: temporal suspect ranking */
  --agent-curator: #10B981;     /* Emerald: memory synthesis & writeback */
  --agent-orchestrator: #94A3B8;/* Slate: lifecycle & fallback findings */

  /* Canvas Graph Elements */
  --graph-grid: rgba(42, 52, 76, 0.25);
  --edge-default: #2A344C;
  --edge-active: #7C8CFF;
  --edge-cited: #FB923C;
}
```

### 2.2 Typography
- **UI & Prose:** `Geist Sans` (`@fontsource-variable/geist`) — Crisp, neutral, engineered for dense data displays.
- **Identifiers & Telemetry:** `Geist Mono` (`@fontsource-variable/geist-mono`) — Used for commit hashes, deploy IDs (`dep:0010`), tool names (`blast_radius`), edge IDs, timestamps, and Cypher snippets.
- **Tabular Figures:** `font-variant-numeric: tabular-nums` enforced across all score bars, token counters, and duration meters to eliminate layout jitters during live streaming.

### 2.3 Motion & Dynamic Aesthetics
- **Graph Tool Pulse:** When an agent tool accesses a node, a 600ms expanding halo ring pulses around the target service in the agent's signature hue.
- **Cited Path Beam:** Selecting a hypothesis triggers an animated directional beam (`stroke-dashoffset`) illuminating the causal edge chain from alerted service to culprit deploy.
- **Hypothesis Hover Spotlight:** Hovering a claim dims all unrelated graph nodes to 25% opacity while highlighting the exact supporting edges at 100% luminance with custom edge markers.
- **Memory Commitment Flight:** Upon clicking "Confirm" in the review box, a micro-card element smoothly transitions into the Memory navigation badge, visually reinforcing the write-back to FalkorDB.
- **Reduced Motion:** Fully conforms to `prefers-reduced-motion: reduce` by replacing animated strokes and pulses with immediate solid state switches.

---

## 3. High-Efficiency Tri-Pane Console Architecture

The primary console screen (`/t/:tenant/incidents/:id`) is organized into three unified, responsive panels with zero wasted whitespace.

```
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ ◆ TRACEBRAIN   [payments ▾]   [Preset: inc:001 Checkout Timeout ▾]   Console  Memory ③  Results   ● FalkorDB ● Groq ⓘ │
├─────────────────────────┬──────────────────────────────────────────────────────┬───────────────────────┤
│ INCIDENT ROSTER (280px) │ TOPOLOGICAL GRAPH STAGE (Flex Center)                │ INVESTIGATION (420px) │
│ ┌─────────────────────┐ │ ┌ Header ──────────────────────────────────────────┐ │ [1] Triaged           │
│ │ ⌕ Search incidents  │ │ │ inc:001 · checkout requests timing out   [Sev 2] │ │ [2] Hypothesized      │
│ │ [All] [Needs Review]│ │ │ As of 2026-08-03 21:38 UTC · Memory: ON   [▶ Run]│ │ [3] Awaiting Review   │
│ │ Memory Next: [● ON] │ │ └──────────────────────────────────────────────────┘ │ 14 calls · 1m 42s · 11K│
│ ├─────────────────────┤ │ ┌ Graph Canvas ────────────────────────────────────┐ │ ┌───────────────────┐ │
│ │ ◆ inc:002 (checkout)│ │ │            [frontend]                            │ │ │ [Trace][Evidence] │ │
│ │   Needs Review · 2d │ │ │          /            \                          │ │ │ [Actions (3)]     │ │
│ │ ✓ inc:001 (checkout)│ │ │      [cart]        [checkout] (ALERT!)           │ │ ├───────────────────┤ │
│ │   Confirmed · 3d    │ │ │        |               \                         │ │ │ #1 dep:0010 (94%) │ │
│ │ ○ inc:003 (product) │ │ │   [redis-cart]      [dep:0010] (Rank #1)         │ │ │ redis-cart config │ │
│ │   Not investigated  │ │ │   (Blast Radius)    (Rollback Clears ✓)          │ │ │ ✓ 4/4 claims ok   │ │
│ └─────────────────────┘ │ └──────────────────────────────────────────────────┘ │ └───────────────────┘ │
│                         │ ◀━━━━━━━━━━━━━━━━━━━●━━━━━━━━━━━━━━━━━━━━━━━━━━━━▶   │ ┌ Sticky Review ────┐ │
│                         │ Time Scrubber: Day 12 [Switch to Current (Now) ⚡]    │ │ Deploy: dep:0010  │ │
│                         │ Legend: ◉ Alert  ▢ Blast  ━ Cited Path  ✓ Verified  │ │ Cause: redis conf │ │
│                         │                                                      │ │ [Confirm] [Reject]│ │
└─────────────────────────┴──────────────────────────────────────────────────────┴───────────────────────┘
```

### 3.1 Left Rail: Incident Roster (`IncidentRail`)
- **Quick Filters:** Segmented control for `All`, `Needs Review` (urgent queue), and `Not Investigated`.
- **Next-Run Memory Toggle:** Explicit switch controlling whether the subsequent investigation consults historical FalkorDB memory.
- **Incident Cards:** Shows incident ID, severity badge (`Sev1`, `Sev2`), root service, symptom badge (`timeout`, `error_spike`, `cpu`), timestamp, and lifecycle state glyph.
- **Keyboard Navigation:** `j`/`k` to traverse incidents; `Enter` to load; `/` to focus the search box.

### 3.2 Center Canvas: Topological Graph Stage (`GraphStage`)
Powered by **React Flow (`@xyflow/react`)** with hand-calibrated coordinates representing the Online Boutique tier hierarchy:
- **Service Nodes (`ServiceNode`):**
  - Displays service title, team ownership pill, tier indicator (Frontend, Core, Data), and protocol icon (gRPC, HTTP, Cache).
  - Multi-state styling: **Alerted** (pulsing crimson boundary), **Blast Radius** (amber wash with hop distance indicator), **Suspect Host** (tangerine commit badge), **Touched** (live pulse on tool invocation).
- **Deploy Nodes (`DeployNode`):**
  - Rendered as compact cards anchored beneath their target service via `DEPLOYED_TO` edges.
  - Displays deploy ID (`dep:0010`), commit change size (`+3 lines`), time relative to alert (`-81m`), author, and Rank badge (`#1`, `#2`, `#3`).
  - Contains the **Sandbox Rollback Verification Badge**: `✓ Clears (simulated)` or `✗ Fails to clear`.
- **Temporal Time Travel Scrubber (`TimeScrubber`):**
  - Horizontal timeline covering the 56-day observation window.
  - Interactive event pins for known structural mutations:
    - *Day 24:* `currency` replaced by `currency-v2`
    - *Day 36:* `payments` service ownership transfer to Team Alpha
    - *Day 44:* `recommendation` dependency cutover to `ad`
  - Dragging the scrubber instantly re-evaluates `GET /graph?t={timestamp}` with smooth edge cross-fading.
- **"As-Of" vs "Now" Contrast Mode (`TopologyToggle`):**
  - One-click toggle switching between the incident snapshot and the current live topology.
  - When viewing "Now", an amber banner appears: *"Static View (Now): Missing historical checkout &rarr; redis-cart dependency. Temporal RCA required."*

### 3.3 Right Panel: Adaptive Investigation Inspector
The right panel adapts dynamically to the current lifecycle phase:

#### Tab 1: Live Trace (`TracePanel`)
- Real-time event log rendered via Server-Sent Events (SSE).
- **Multi-Agent Handoff Cards:** Visual blackboard dividers illustrating state handoffs between `Triage`, `Investigator`, and `Curator`.
- **Tool Invocations:** Shows tool name (`blast_radius`, `suspects_asof`, `path_between`), formatted arguments, duration (`14ms`), and edge count.
- **Expandable Step Payloads:** One-click inspection of raw tool inputs and JSON outputs.
- **LLM Rate-Limit Waiting Counter:** Displays a graceful countdown (`"Waiting for model rate-limit · 24s"`) rather than appearing frozen during Groq API pauses.

#### Tab 2: Evidence Matrix (`EvidencePanel`)
- **Faithfulness Meter:** Prominent header metric showing the exact proportion of claims verified against FalkorDB graph edges (e.g., `4/4 claims verified (100%)`).
- **Ranked Hypothesis Cards (`HypothesisCard`):**
  - Rank badge, suspect deploy ID, service name, and natural-language cause headline.
  - **6-Feature Score Decomposition (`ScoreBars`):**
    - Proximity (hops from alert)
    - Recency (minutes prior to incident)
    - Change Size (lines of code / config change)
    - Historical Failure Rate
    - Service Centrality
    - **Lesson Match (Highlighted in Emerald when boosted by institutional memory)**
  - **Claim-by-Claim Verification Grid (`ClaimRow`):**
    - Individual claim statements tagged with `✓ Verified` or `✗ Unverified`.
    - Edge-ID chips linking claims directly to graph edges.
    - Hovering any claim triggers the **Graph Spotlight** effect.
    - Explicit rejection reasons displayed for invalid claims (e.g., *"Edge 987654 does not exist in graph snapshot"*).
- **Abstention State Card (`AbstainCard`):**
  - Displayed when no deploy is supported by graph evidence (e.g., `inc:025`).
  - Outlines the exact abstention rationale and offers human escalation options.

#### Tab 3: Action Dispatch (`ActionsPanel`)
- Lists proposed mitigation steps generated by the agents:
  - `rollback_proposal`: Details targeted commit and sandbox verification status.
  - `ticket`: Pre-populated Jira/Linear ticket for owning team.
  - `page`: Escalation details for service owners.
- Marked clearly: *"Proposed mitigation — awaiting human authorization."*

#### Sticky Review Dock (`ReviewBox`)
Permanently accessible at the bottom of the right panel when an investigation enters `AWAITING_REVIEW`:
- **Culprit Selector:** Defaults to Hypothesis #1, with instant dropdown access to #2, #3, or all scored candidates.
- **Cause Synthesis Field:** Pre-populated with the generated cause; fully editable by the engineer.
- **Reviewer Signature:** Remembers reviewer identity via `localStorage`.
- **Confirm / Reject Buttons:**
  - `Confirm`: Triggers `POST /review` &rarr; writes Cause & Lesson nodes to FalkorDB &rarr; triggers celebratory Toast & increments Memory badge.
  - `Reject`: Weakens associated lesson weights and flags suspect deploy as reviewed false positive.

---

## 4. Secondary Views

### 4.1 Institutional Memory Explorer (`/t/:tenant/memory`)
Showcases the long-term knowledge graph compiled strictly from human-confirmed incident reviews:
- **Header Lineage:** *"Memory is written only by human review. Every entry links to proven incident evidence."*
- **Learned Lessons Table (`LessonList`):**
  - Natural language formulation: `"timeout @ checkout → check redis-cart first"`.
  - Confidence weight bar: `(success - fail) / (success + fail + 1)`.
  - Confirmation/Rejection counts (`✓ 4 · ✗ 0`).
  - Source incident provenance chips linking directly to past investigation runs.
- **Cause Entities Table (`CauseTable`):**
  - Displays normalized cause names, aliases generated via entity resolution, confidence meters, and a **Retract** action.
  - Retraction confirmation dialog allows marking invalid causes without breaking graph referential integrity.

### 4.2 Benchmark & Evaluation Dashboard (`/results`)
Renders empirical validation data from `eval/results.json`:
- **Top-1 / Top-3 Accuracy vs Baselines:** Comparative bar charts contrasting Tracebrain against Baseline 0 (Most Recent Deploy) and Baseline 1 (Vector RAG).
- **Memory Acceleration Benefit:** Side-by-side comparison of Memory OFF vs Memory ON (measuring average tool-call reduction & token savings on repeat incidents).
- **Temporal vs Naive Blast-Radius F1:** Demonstrates the measured degradation when using static vs as-of graph queries.
- **Failure-Mode Robustness Matrix:** Visual pass/fail grid covering decoy rejection, stale topology handling, hallucinated claim detection, and correct abstention.
- **Zero-Fake-Data Guarantee:** If `eval/results.json` is not present, displays an honest empty state with execution instructions rather than placeholder mock numbers.

---

## 5. Technical Architecture & Component Tree

### 5.1 Technology Stack
- **Framework:** React 19 + TypeScript (Strict Mode) + Vite 6
- **Routing:** React Router v7 (Data Router mode with nested routes & lazy loading)
- **Styling:** Tailwind CSS v4 + Custom Design Tokens (`tokens.css`)
- **Graph Engine:** `@xyflow/react` v12 (React Flow)
- **Server State & Cache:** `@tanstack/react-query` v5
- **Primitive Components:** Radix UI primitives (shadcn architecture)
- **Icons & Typography:** `lucide-react`, `@fontsource-variable/geist`, `@fontsource-variable/geist-mono`
- **Streaming:** Native `EventSource` with custom multi-event reducer & cursor reconnection

### 5.2 Frontend Directory Structure
```
ui/
├── index.html
├── package.json
├── vite.config.ts
├── tsconfig.json
└── src/
    ├── main.tsx                         # QueryClient, Router, Toaster
    ├── router.tsx                       # Route declarations & lazy boundaries
    ├── styles/
    │   ├── tokens.css                   # CSS variable design tokens
    │   └── globals.css                  # Tailwind imports & base styles
    ├── api/
    │   ├── client.ts                    # Fetch client with ApiError handling
    │   ├── types.ts                     # Strict TypeScript interfaces matching API
    │   ├── keys.ts                      # React Query key factories
    │   └── hooks.ts                     # TanStack Query & Mutation hooks
    ├── stream/
    │   ├── useInvestigationStream.ts    # Resilient SSE hook with backoff & cursor
    │   └── reducer.ts                   # Pure state reducer for 11 SSE event kinds
    ├── state/
    │   └── SelectionContext.tsx         # Hypothesis focus, claim hover, pinned edges
    ├── features/
    │   ├── shell/                       # TopBar, TenantSwitcher, HealthDots, DemoQuickBar
    │   ├── incidents/                   # IncidentRail, IncidentCard, IncidentFilter
    │   ├── console/                     # ConsolePage, IncidentHeader, Stepper, RunStats
    │   ├── graph/                       # GraphStage, ServiceNode, DeployNode, CitedEdge,
    │   │                                # layout.ts, highlight.ts, TimeScrubber
    │   ├── trace/                       # TracePanel, TraceRow, HandoffCard, WaitingRow
    │   ├── evidence/                    # EvidencePanel, HypothesisCard, ClaimRow, ScoreBars
    │   ├── actions/                     # ActionsPanel, ActionCard
    │   ├── review/                      # ReviewBox, ReviewModal
    │   ├── memory/                      # MemoryPage, LessonList, CauseTable, RetractModal
    │   └── results/                     # ResultsPage, AccuracyChart, FailureMatrix
    ├── components/ui/                   # Buttons, Badges, Tabs, Tooltips, Dialogs, Toasts
    └── lib/
        ├── time.ts                      # Relative and UTC formatting
        ├── status.ts                    # State machine to glyph/badge mapping
        └── lessonWeight.ts              # Procedural confidence formula mirroring backend
```

---

## 6. Critical State Synchronization: `SelectionContext`

To deliver fluid, synchronized interactions between the graph canvas and inspector panels without prop drilling, a dedicated lightweight `SelectionContext` maintains:
1. `focusedHypothesisId`: Currently selected hypothesis (determines active cited path and dimmed background nodes).
2. `hoveredClaimEdgeIds`: Array of FalkorDB edge IDs corresponding to the hovered claim row (activates high-intensity edge highlight).
3. `pinnedEdgeIds`: Edges locked in highlight mode via direct user click.
4. `activeTopologyMode`: Toggle state between `'as_of'` and `'now'`.
5. `scrubbedTimestamp`: Temporal slider position (debounced at 200ms before triggering graph query refetches).

---

## 7. Execution Roadmap & Milestones

The development roadmap is divided into structured, verifiable sprints to guarantee demo readiness.

| Sprint | Objective | Deliverables | Verification Check |
|---|---|---|---|
| **Sprint 0: Foundation & Shell** | UI scaffold, tokens, layout, router, API proxy, backend B4 patch. | Vite + React 19 setup, Tailwind v4 tokens, `TopBar`, `TenantSwitcher`, `HealthDots`. | Shell renders with live `/health` connection; tenant switching functional. |
| **Sprint 1: Incident Command Rail** | Incident roster, filtering, search, memory toggle, API data layer. | `api/` hooks, `IncidentRail`, `IncidentCard`, status mapping. | Real incidents list from FalkorDB; clicking incident updates route. |
| **Sprint 2: Live Multi-Agent Trace** | SSE stream receiver, trace timeline, handoff cards, live stepper. | `useInvestigationStream.ts`, `reducer.ts`, `TracePanel`, `Stepper`. | Real investigation streams live; reconnects seamlessly after server restart. |
| **Sprint 3: Topological Graph Stage** | React Flow canvas, custom service & deploy nodes, time scrubber. | `GraphStage`, `ServiceNode`, `DeployNode`, `layout.ts`, `TimeScrubber`. | Graph reflects as-of topology; nodes pulse during tool calls; scrubber switches topology. |
| **Sprint 4: Evidence & Explainability** | Hypothesis cards, score breakdown, claim-to-edge spotlighting. | `EvidencePanel`, `HypothesisCard`, `ScoreBars`, `ClaimRow`, `SelectionContext`. | Hovering claim illuminates exact graph edges; unverified claims show failure reason. |
| **Sprint 5: Human-in-the-Loop Review** | Review dock, verification pill, cause write-back, toast alerts. | `ReviewBox`, `ActionsPanel`, toast integration, cache invalidation. | Confirming incident writes lesson to FalkorDB; Memory badge increments. |
| **Sprint 6: Institutional Memory Hub** | Learned lessons view, cause entity table, retraction workflow. | `MemoryPage`, `LessonList`, `CauseTable`, `RetractModal`. | Confirmed lessons visible; retraction strikes out cause and updates confidence. |
| **Sprint 7: Benchmark Results & Polish** | Evaluation dashboard, keyboard shortcuts, demo quick-bar. | `ResultsPage`, `ShortcutSheet`, `DemoQuickBar`, a11y audit. | Full end-to-end recording checklist verified across 1280x800 and 1440x900 viewports. |

---

## 8. Definition of Done & Quality Gates

1. **Aesthetic Excellence:** Premium dark theme, harmonious typography, smooth 150-250ms transitions, zero visual layout shift (CLS < 0.05).
2. **Explainability Invariant:** Every LLM claim maps to an explicit edge on the graph; no silent drops or missing edge references.
3. **Honesty Invariant:** No placeholder numbers or mocked evaluation stats; all verification labels explicitly marked `"simulated"`.
4. **Reliability:** Recovers automatically from SSE disconnects, server restarts, and API 429 rate limits.
5. **Accessibility (WCAG 2.2 AA):** Fully keyboard operable, visible focus rings, minimum 4.5:1 text contrast ratios, screen reader announcement regions for state transitions.
