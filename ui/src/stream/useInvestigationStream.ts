import { useEffect, useReducer, useRef, useCallback } from 'react';
import { runReducer, INITIAL_RUN_VIEW, SseEventKind, SseEvent } from './reducer';
import type { RunView } from './reducer';
import type { InvestigationFull } from '@/api/types';

const API_BASE = import.meta.env.VITE_API_BASE ?? '/api';
const WAITING_TIMEOUT_MS = 8000;
const BACKOFF_DELAYS = [1000, 2000, 4000, 8000, 10000];

const ALL_EVENT_KINDS: SseEventKind[] = [
  'started', 'resumed', 'step', 'fallback_findings', 'handoff',
  'state', 'hypotheses', 'verification', 'error', 'done', 'reviewed',
];

/**
 * One hook instance serves one investigation: the caller remounts it (via `key`) when the run changes.
 * `epoch` is bumped on Resume to re-read the event history from the start.
 */
export function useInvestigationStream(
  tenant: string,
  invId: string | null | undefined,
  opts: { enabled: boolean; inv?: InvestigationFull | null; epoch?: number }
): RunView {
  const [state, dispatch] = useReducer(runReducer, INITIAL_RUN_VIEW);
  const esRef = useRef<EventSource | null>(null);
  const backoffRef = useRef(0);
  const waitingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastKindRef = useRef<SseEventKind | null>(null);
  const epochRef = useRef(opts.epoch ?? 0);
  const mountedRef = useRef(true);
  const stateRef = useRef(state);
  stateRef.current = state;

  // Seed the timeline from the stored record once. If the event bus still holds this run's history,
  // its replay starts with `started`, which replaces these rows; after a server restart the bus is
  // empty, so these rows stay and new events (e.g. `resumed`) are appended to them.
  const hydratedRef = useRef(false);
  useEffect(() => {
    if (!opts.inv || hydratedRef.current || stateRef.current.lastSeq > 0) return;
    hydratedRef.current = true;
    dispatch({ type: 'HYDRATE', inv: opts.inv });
  }, [opts.inv]);

  const scheduleWaitingRow = useCallback(() => {
    if (waitingTimerRef.current) clearTimeout(waitingTimerRef.current);
    waitingTimerRef.current = setTimeout(() => {
      if (mountedRef.current) dispatch({ type: 'ADD_WAITING' });
    }, WAITING_TIMEOUT_MS);
  }, []);

  const clearTimers = useCallback(() => {
    if (waitingTimerRef.current) {
      clearTimeout(waitingTimerRef.current);
      waitingTimerRef.current = null;
    }
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);

  const openStream = useCallback(
    (after: number, attempt: number) => {
      if (!invId || !tenant || !mountedRef.current) return;

      esRef.current?.close();

      const url = `${API_BASE}/tenants/${tenant}/investigations/${invId}/events?after=${after}`;
      const es = new EventSource(url);
      esRef.current = es;
      dispatch({ type: 'CONNECTION', status: attempt === 0 ? 'open' : 'reconnecting' });
      es.onopen = () => {
        if (mountedRef.current) dispatch({ type: 'CONNECTION', status: 'open' });
      };

      scheduleWaitingRow();

      ALL_EVENT_KINDS.forEach((kind) => {
        es.addEventListener(kind, (e: MessageEvent) => {
          if (!mountedRef.current) return;
          try {
            const data = JSON.parse(e.data) as Record<string, unknown>;
            const seq = parseInt(e.lastEventId || '0', 10);
            const event: SseEvent = { kind, seq, data };
            dispatch({ type: 'SSE_EVENT', event });
            lastKindRef.current = kind;
            backoffRef.current = 0;

            // Reset waiting timer on every event; nothing more is expected after `done`
            if (kind === 'done') {
              if (waitingTimerRef.current) clearTimeout(waitingTimerRef.current);
            } else {
              scheduleWaitingRow();
            }

            // Clear touched nodes after 600ms
            if (kind === 'step') {
              setTimeout(() => {
                if (mountedRef.current) dispatch({ type: 'CLEAR_TOUCHED' });
              }, 600);
            }
          } catch {
            // ignore parse errors
          }
        });
      });

      es.onerror = () => {
        if (!mountedRef.current) return;
        es.close();
        clearTimers();
        // The server ends the stream after the final `done`. A `done` replayed from before a resume
        // is followed by more events, so the close is final only if `done` was the last event seen.
        if (lastKindRef.current === 'done') {
          dispatch({ type: 'CONNECTION', status: 'closed' });
          return;
        }
        const delay = BACKOFF_DELAYS[Math.min(backoffRef.current, BACKOFF_DELAYS.length - 1)];
        backoffRef.current += 1;
        dispatch({ type: 'CONNECTION', status: 'reconnecting' });
        reconnectTimerRef.current = setTimeout(() => {
          if (mountedRef.current) {
            openStream(stateRef.current.lastSeq, backoffRef.current);
          }
        }, delay);
      };
    },
    [tenant, invId, scheduleWaitingRow, clearTimers]
  );

  useEffect(() => {
    mountedRef.current = true;

    if (!invId || !opts.enabled) {
      esRef.current?.close();
      esRef.current = null;
      return;
    }

    let after = stateRef.current.lastSeq;
    const epoch = opts.epoch ?? 0;
    if (epoch !== epochRef.current) {
      epochRef.current = epoch;
      after = 0;
      dispatch({ type: 'RESET_CURSOR' });
    }
    lastKindRef.current = null;
    backoffRef.current = 0;
    openStream(after, 0);

    return () => {
      mountedRef.current = false;
      esRef.current?.close();
      esRef.current = null;
      clearTimers();
    };
  }, [invId, opts.enabled, opts.epoch, openStream, clearTimers]);

  return state;
}
