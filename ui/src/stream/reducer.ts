import type { InvestigationFull, InvestigationState, Hypothesis } from '@/api/types';

// ─── SSE event payloads (mirror the backend, verified against events.py) ──────

export interface StartedPayload {
  incident: string;
  memory_enabled: boolean;
  from_state?: string;
  replayed_steps?: number;
}

export interface StepPayload {
  n: number;
  agent: string;
  tool: string;
  args: Record<string, unknown>;
  ms: number;
  edge_ids: number[];
  error: string | null;
}

export interface HandoffPayload {
  from: string;
  to: string;
  findings: unknown[];
  summary: string;
}

export interface StatePayload {
  state: string;
}

export interface HypothesesPayload {
  hypotheses: Hypothesis[];
  actions: unknown[];
  abstain: boolean;
  abstain_reason: string | null;
  faithfulness: number | null;
  problems: string[];
}

export interface VerificationPayload {
  deploy_id: string;
  clears: boolean | null;
  environment: string;
  sandbox?: string;
  next_suspect?: string | null;
  next_suspect_service?: string | null;
  remaining_candidates?: number;
}

export interface ErrorPayload {
  error: string;
}

export interface DonePayload {
  state: string;
  outcome: string | null;
  tool_calls: number;
  faithfulness: number | null;
}

export interface ReviewedPayload {
  verdict: string;
  reviewer?: string;
}

export type SseEventKind =
  | 'started'
  | 'resumed'
  | 'step'
  | 'fallback_findings'
  | 'handoff'
  | 'state'
  | 'hypotheses'
  | 'verification'
  | 'error'
  | 'done'
  | 'reviewed';

export interface SseEvent {
  kind: SseEventKind;
  seq: number;
  data: Record<string, unknown>;
}

// ─── Trace items (rendered timeline rows) ────────────────────────────────────

export type TraceItemKind =
  | 'header'
  | 'step'
  | 'handoff'
  | 'fallback'
  | 'hypotheses_summary'
  | 'verification_summary'
  | 'error'
  | 'done'
  | 'reviewed'
  | 'waiting';

export interface TraceHeader { kind: 'header'; seq: number; text: string; }
export interface TraceStep { kind: 'step'; seq: number; step: StepPayload; }
export interface TraceHandoff { kind: 'handoff'; seq: number; handoff: HandoffPayload; }
export interface TraceFallback { kind: 'fallback'; seq: number; text: string; }
export interface TraceHypotheses { kind: 'hypotheses_summary'; seq: number; h: HypothesesPayload; }
export interface TraceVerification { kind: 'verification_summary'; seq: number; v: VerificationPayload; }
export interface TraceError { kind: 'error'; seq: number; message: string; }
export interface TraceDone { kind: 'done'; seq: number; payload: DonePayload; }
export interface TraceReviewed { kind: 'reviewed'; seq: number; payload: ReviewedPayload; }
export interface TraceWaiting { kind: 'waiting'; seq: number; since: number; }

export type TraceItem =
  | TraceHeader
  | TraceStep
  | TraceHandoff
  | TraceFallback
  | TraceHypotheses
  | TraceVerification
  | TraceError
  | TraceDone
  | TraceReviewed
  | TraceWaiting;

// ─── RunView: the full derived state from the event stream ───────────────────

export interface RunView {
  lastSeq: number;
  connection: 'idle' | 'open' | 'reconnecting' | 'closed';
  live: boolean;
  state: InvestigationState | null;
  rows: TraceItem[];
  touched: Set<string>;      // service names to pulse — cleared after 600ms
  hypotheses: HypothesesPayload | null;
  verification: VerificationPayload | null;
  errorMessage: string | null;
  lastEventAt: number | null; // epoch ms, drives "Waiting for model"
}

export const INITIAL_RUN_VIEW: RunView = {
  lastSeq: 0,
  connection: 'idle',
  live: false,
  state: null,
  rows: [],
  touched: new Set(),
  hypotheses: null,
  verification: null,
  errorMessage: null,
  lastEventAt: null,
};

// ─── Actions ─────────────────────────────────────────────────────────────────

export type RunAction =
  | { type: 'SSE_EVENT'; event: SseEvent }
  | { type: 'CONNECTION'; status: RunView['connection'] }
  | { type: 'CLEAR_TOUCHED' }
  | { type: 'ADD_WAITING' }
  | { type: 'RESET_CURSOR' }
  | { type: 'HYDRATE'; inv: InvestigationFull };

// ─── Reducer ─────────────────────────────────────────────────────────────────

function touchedFromArgs(args: Record<string, unknown>): Set<string> {
  const names = new Set<string>();
  const walk = (v: unknown) => {
    if (typeof v === 'string') names.add(v);
    else if (Array.isArray(v)) v.forEach(walk);
    else if (v && typeof v === 'object') Object.values(v as Record<string, unknown>).forEach(walk);
  };
  walk(args);
  return names;
}

export function runReducer(state: RunView, action: RunAction): RunView {
  switch (action.type) {
    case 'CONNECTION':
      return { ...state, connection: action.status, live: action.status === 'open' || action.status === 'reconnecting' };

    case 'CLEAR_TOUCHED':
      return { ...state, touched: new Set() };

    case 'RESET_CURSOR':
      // Re-reading history from seq 1 (Resume); rows are kept and `started` replaces them if replayed.
      return { ...state, lastSeq: 0 };

    case 'ADD_WAITING':
      return {
        ...state,
        rows: [
          ...state.rows.filter((r) => r.kind !== 'waiting'),
          { kind: 'waiting', seq: state.lastSeq + 0.5, since: Date.now() } as TraceWaiting,
        ],
      };

    case 'SSE_EVENT': {
      const { event } = action;
      if (event.seq <= state.lastSeq) return state; // dedup

      const rows = state.rows.filter((r) => r.kind !== 'waiting'); // remove old waiting row
      let newState = { ...state, lastSeq: event.seq, lastEventAt: Date.now(), rows };

      switch (event.kind) {
        case 'started':
        case 'resumed': {
          const p = event.data as unknown as StartedPayload;
          const memory = p.memory_enabled ? 'memory ON' : 'memory OFF';
          const text =
            event.kind === 'resumed' && p.from_state
              ? `Resumed from ${p.from_state} · ${p.replayed_steps ?? 0} steps replayed (not re-executed) · ${memory}`
              : `Started · ${memory}`;
          const header = { kind: 'header', seq: event.seq, text } as TraceHeader;
          newState = {
            ...newState,
            // `started` is the first event of a run's history, so everything before it (rows seeded
            // from the stored record) is superseded by the replay that follows.
            ...(event.kind === 'started' ? { hypotheses: null, verification: null } : {}),
            rows: event.kind === 'started' ? [header] : [...rows, header],
            live: true,
            errorMessage: null,
          };
          break;
        }

        case 'step': {
          const p = event.data as unknown as StepPayload;
          newState = {
            ...newState,
            rows: [...rows, { kind: 'step', seq: event.seq, step: p } as TraceStep],
            touched: touchedFromArgs(p.args),
          };
          break;
        }

        case 'handoff': {
          const p = event.data as unknown as HandoffPayload;
          newState = {
            ...newState,
            rows: [...rows, { kind: 'handoff', seq: event.seq, handoff: p } as TraceHandoff],
          };
          break;
        }

        case 'fallback_findings': {
          const d = event.data as unknown as { kinds?: string[] };
          const kinds = d.kinds?.join(', ') ?? 'unknown';
          newState = {
            ...newState,
            rows: [
              ...rows,
              { kind: 'fallback', seq: event.seq, text: `Orchestrator recorded missing findings: ${kinds}` } as TraceFallback,
            ],
          };
          break;
        }

        case 'state': {
          const p = event.data as unknown as StatePayload;
          newState = { ...newState, state: p.state as InvestigationState };
          break;
        }

        case 'hypotheses': {
          const p = event.data as unknown as HypothesesPayload;
          newState = {
            ...newState,
            hypotheses: p,
            rows: [
              ...rows,
              { kind: 'hypotheses_summary', seq: event.seq, h: p } as TraceHypotheses,
            ],
          };
          break;
        }

        case 'verification': {
          const p = event.data as unknown as VerificationPayload;
          newState = {
            ...newState,
            verification: p,
            rows: [
              ...rows,
              { kind: 'verification_summary', seq: event.seq, v: p } as TraceVerification,
            ],
          };
          break;
        }

        case 'error': {
          const p = event.data as unknown as ErrorPayload;
          newState = {
            ...newState,
            errorMessage: p.error,
            rows: [
              ...rows,
              { kind: 'error', seq: event.seq, message: p.error } as TraceError,
            ],
          };
          break;
        }

        case 'done': {
          const p = event.data as unknown as DonePayload;
          newState = {
            ...newState,
            live: false,
            state: p.state as InvestigationState,
            rows: [...rows, { kind: 'done', seq: event.seq, payload: p } as TraceDone],
          };
          break;
        }

        case 'reviewed': {
          const p = event.data as unknown as ReviewedPayload;
          newState = {
            ...newState,
            rows: [...rows, { kind: 'reviewed', seq: event.seq, payload: p } as TraceReviewed],
          };
          break;
        }
      }
      return newState;
    }

    case 'HYDRATE': {
      // Seed the timeline from the stored record (e.g. after page reload). Row seqs here are local
      // keys only; lastSeq and connection are left alone so they keep tracking real bus events.
      const { inv } = action;
      const rows: TraceItem[] = [];
      let seq = 0;

      rows.push({ kind: 'header', seq: seq++, text: `Started · ${inv.memory_enabled ? 'memory ON' : 'memory OFF'}` });

      for (const step of inv.steps ?? []) {
        rows.push({ kind: 'step', seq: seq++, step: { ...step } } as TraceStep);
      }

      if (inv.hypotheses?.length) {
        rows.push({
          kind: 'hypotheses_summary',
          seq: seq++,
          h: {
            hypotheses: inv.hypotheses,
            actions: inv.actions ?? [],
            abstain: false,
            abstain_reason: null,
            faithfulness: inv.faithfulness,
            problems: [],
          },
        } as TraceHypotheses);
      }

      return {
        lastSeq: state.lastSeq,
        connection: state.connection,
        live: state.live,
        state: inv.state,
        rows,
        touched: new Set(),
        hypotheses: inv.hypotheses?.length
          ? {
              hypotheses: inv.hypotheses,
              actions: inv.actions ?? [],
              abstain: false,
              abstain_reason: null,
              faithfulness: inv.faithfulness,
              problems: [],
            }
          : null,
        verification: null,
        errorMessage: null,
        lastEventAt: null,
      };
    }

    default:
      return state;
  }
}
