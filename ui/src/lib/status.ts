import type { InvestigationState, IncidentRow } from '@/api/types';

export interface StatusDisplay {
  glyph: string;
  word: string;
  color: string; // CSS var
}

export function getStatusDisplay(row: IncidentRow): StatusDisplay {
  const state = row.investigation_state;
  if (!state || !row.investigation) {
    return { glyph: '○', word: 'Not investigated', color: 'var(--text-faint)' };
  }
  // Review always ends in LEARNED; the incident status says which way it went (curator.review).
  if (state === 'LEARNED' && row.status === 'open') return getStateDisplay('REJECTED');
  return getStateDisplay(state);
}

export function getStateDisplay(state: InvestigationState): StatusDisplay {
  switch (state) {
    case 'OPEN':
    case 'TRIAGED':
    case 'HYPOTHESIZED':
    case 'VERIFIED':
      return { glyph: '◌', word: 'Investigating', color: 'var(--accent)' };
    case 'AWAITING_REVIEW':
      return { glyph: '◆', word: 'Needs review', color: 'var(--status-warn)' };
    case 'CONFIRMED':
    case 'LEARNED':
      return { glyph: '✓', word: 'Confirmed', color: 'var(--status-ok)' };
    case 'REJECTED':
      return { glyph: '✗', word: 'Rejected', color: 'var(--status-bad)' };
    case 'FAILED':
      return { glyph: '⚠', word: 'Failed', color: 'var(--status-bad)' };
    default:
      return { glyph: '○', word: 'Unknown', color: 'var(--text-faint)' };
  }
}

export function isRunning(state: InvestigationState | null | undefined): boolean {
  return state === 'OPEN' || state === 'TRIAGED' || state === 'HYPOTHESIZED' || state === 'VERIFIED';
}

export function isTerminal(state: InvestigationState | null | undefined): boolean {
  return (
    state === 'CONFIRMED' ||
    state === 'REJECTED' ||
    state === 'LEARNED'
  );
}

export const INVESTIGATION_STEPS: InvestigationState[] = [
  'OPEN',
  'TRIAGED',
  'HYPOTHESIZED',
  'VERIFIED',
  'AWAITING_REVIEW',
  'LEARNED',
];

export function stepIndex(state: InvestigationState | null | undefined): number {
  if (!state) return -1;
  const map: Record<string, number> = {
    OPEN: 0,
    TRIAGED: 1,
    HYPOTHESIZED: 2,
    VERIFIED: 3,
    AWAITING_REVIEW: 4,
    CONFIRMED: 5,
    REJECTED: 5,
    LEARNED: 5,
    FAILED: -1,
  };
  return map[state] ?? -1;
}

export function formatRelativeTime(tsSeconds: number): string {
  const diffMs = Date.now() - tsSeconds * 1000;
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `${diffH}h ago`;
  const diffD = Math.floor(diffH / 24);
  return `${diffD}d ago`;
}

export function formatUtcTimestamp(tsSeconds: number): string {
  return new Date(tsSeconds * 1000).toISOString().replace('T', ' ').replace(/\.\d+Z$/, ' UTC');
}

export function formatDuration(ms: number | null | undefined): string {
  if (!ms) return '—';
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}m ${rem}s`;
}

export function formatTokens(prompt: number | null | undefined, completion: number | null | undefined): string {
  const total = (prompt ?? 0) + (completion ?? 0);
  if (total === 0) return '—';
  if (total >= 1000) return `${(total / 1000).toFixed(1)}K tok`;
  return `${total} tok`;
}
