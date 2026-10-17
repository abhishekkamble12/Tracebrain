import React from 'react';
import { cn } from '@/lib/utils';
import { INVESTIGATION_STEPS, stepIndex } from '@/lib/status';
import type { InvestigationState } from '@/api/types';
import { AlertTriangle } from 'lucide-react';

const STEP_LABELS: Record<string, string> = {
  OPEN: 'Open',
  TRIAGED: 'Triaged',
  HYPOTHESIZED: 'Hypothesized',
  VERIFIED: 'Verified',
  AWAITING_REVIEW: 'Review',
  LEARNED: 'Done',
};

interface StepperProps {
  state: InvestigationState | null | undefined;
  failed?: boolean;
}

export const Stepper: React.FC<StepperProps> = ({ state, failed }) => {
  const currentIdx = stepIndex(state);

  return (
    <div className="flex flex-col gap-1.5">
      <ol className="grid grid-cols-6" aria-label="Investigation progress">
        {INVESTIGATION_STEPS.map((step, i) => {
          const isDone = i < currentIdx || (i === currentIdx && step === 'LEARNED');
          const isCurrent = i === currentIdx && !isDone;
          const label = STEP_LABELS[step] ?? step;

          return (
            <li key={step} className="relative flex flex-col items-center gap-1" aria-current={isCurrent ? 'step' : undefined}>
              {/* Connector from the previous step's dot to this one */}
              {i > 0 && (
                <span
                  className={cn(
                    'absolute top-[4px] right-1/2 w-full h-px transition-colors duration-500',
                    i <= currentIdx ? 'bg-[var(--status-ok)]' : 'bg-[var(--border-strong)]'
                  )}
                />
              )}
              <span
                className={cn(
                  'relative z-10 w-2.5 h-2.5 rounded-full border transition-colors',
                  isDone
                    ? 'bg-[var(--status-ok)] border-[var(--status-ok)]'
                    : isCurrent
                      ? 'bg-[var(--accent)] border-[var(--accent)] ring-4 ring-[var(--accent)]/20'
                      : 'bg-[var(--surface-panel)] border-[var(--border-strong)]'
                )}
              />
              <span
                className={cn(
                  'text-[10px] whitespace-nowrap',
                  isDone ? 'text-[var(--text-secondary)]' : isCurrent ? 'text-[var(--accent)] font-medium' : 'text-[var(--text-faint)]'
                )}
              >
                {label}
              </span>
            </li>
          );
        })}
      </ol>
      {failed && (
        <p className="flex items-center gap-1.5 text-[11px] text-[var(--status-bad)]">
          <AlertTriangle className="w-3 h-3 flex-shrink-0" />
          Run failed. Resume continues from the last completed stage.
        </p>
      )}
    </div>
  );
};

// ─── RunStats line ─────────────────────────────────────────────────────────────

import { formatDuration, formatTokens } from '@/lib/status';
import type { InvestigationFull } from '@/api/types';
import type { RunView } from '@/stream/reducer';

interface RunStatsProps {
  inv?: InvestigationFull | null;
  runView?: RunView;
}

export const RunStats: React.FC<RunStatsProps> = ({ inv, runView }) => {
  const toolCalls = inv?.tool_calls ?? null;
  const tokens = formatTokens(inv?.prompt_tokens, inv?.completion_tokens);
  const duration = runView?.live
    ? null // show live timer instead
    : formatDuration(inv?.duration_ms);

  const [elapsed, setElapsed] = React.useState(0);
  React.useEffect(() => {
    if (!runView?.live) return;
    const base = inv?.started
      ? inv.started * 1000          // seconds → ms
      : (runView.lastEventAt ?? Date.now()); // fallback: first SSE event time
    const id = setInterval(() => {
      setElapsed(Math.floor((Date.now() - base) / 1000));
    }, 1000);
    return () => clearInterval(id);
  }, [runView?.live, inv?.started, runView?.lastEventAt]);

  const parts = [
    toolCalls != null ? `${toolCalls} calls` : null,
    runView?.live ? `${elapsed}s` : duration,
    tokens !== '—' ? tokens : null,
    inv?.resumes ? `${inv.resumes} resume${inv.resumes > 1 ? 's' : ''}` : null,
  ].filter(Boolean);

  if (parts.length === 0) return null;

  return (
    <div className="text-[10px] font-mono text-[var(--text-faint)] flex items-center gap-2 flex-wrap">
      {parts.map((p, i) => (
        <React.Fragment key={i}>
          {i > 0 && <span className="opacity-40">·</span>}
          <span>{p}</span>
        </React.Fragment>
      ))}
    </div>
  );
};
