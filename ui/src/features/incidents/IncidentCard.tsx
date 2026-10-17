import React from 'react';
import { cn } from '@/lib/utils';
import type { IncidentRow } from '@/api/types';
import { getStatusDisplay, formatRelativeTime, formatUtcTimestamp } from '@/lib/status';

interface IncidentCardProps {
  incident: IncidentRow;
  selected: boolean;
  onClick: () => void;
}

const SYMPTOM_COLORS: Record<string, string> = {
  timeout: 'bg-[var(--status-warn)]/15 text-[var(--status-warn)] border-[var(--status-warn)]/30',
  error: 'bg-[var(--status-bad)]/15 text-[var(--status-bad)] border-[var(--status-bad)]/30',
  error_spike: 'bg-[var(--status-bad)]/15 text-[var(--status-bad)] border-[var(--status-bad)]/30',
  latency: 'bg-[var(--status-suspect)]/15 text-[var(--status-suspect)] border-[var(--status-suspect)]/30',
  cpu: 'bg-[var(--status-suspect)]/15 text-[var(--status-suspect)] border-[var(--status-suspect)]/30',
  memory: 'bg-[var(--agent-investigator)]/15 text-[var(--agent-investigator)] border-[var(--agent-investigator)]/30',
};

export const IncidentCard: React.FC<IncidentCardProps> = ({ incident, selected, onClick }) => {
  const status = getStatusDisplay(incident);
  const rel = formatRelativeTime(incident.ts);
  const abs = formatUtcTimestamp(incident.ts);
  const symptomClass =
    SYMPTOM_COLORS[incident.symptom?.toLowerCase()] ??
    'bg-[var(--border-strong)]/50 text-[var(--text-secondary)] border-[var(--border-strong)]';

  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={selected ? 'page' : undefined}
      className={cn(
        'w-full text-left px-3 py-2.5 rounded transition-all duration-150 border-l-[2px] flex flex-col gap-1 group',
        selected
          ? 'bg-[var(--surface-hover)] border-l-[var(--accent)]'
          : 'bg-transparent border-l-transparent hover:bg-[var(--surface-hover)]/50'
      )}
    >
      {/* Top row: glyph + id + severity */}
      <div className="flex items-center gap-1.5 min-w-0">
        <span
          className="text-[13px] leading-none flex-shrink-0 tabular-nums"
          style={{ color: status.color }}
          title={status.word}
        >
          {status.glyph}
        </span>
        <span className="font-mono text-[11px] text-[var(--text-faint)] flex-shrink-0">{incident.id}</span>
        <span
          className={cn(
            'ml-auto flex-shrink-0 text-[10px] font-mono px-1 py-0.5 rounded border',
            incident.severity === 'sev1' ? 'bg-[var(--status-bad)]/20 text-[var(--status-bad)] border-[var(--status-bad)]/40' : 'bg-[var(--status-warn)]/10 text-[var(--status-warn)] border-[var(--status-warn)]/30'
          )}
        >
          {incident.severity?.toUpperCase()}
        </span>
      </div>

      {/* Middle row: service + symptom chip */}
      <div className="flex items-center gap-1.5 min-w-0">
        <span className="text-xs text-[var(--text-primary)] font-medium truncate flex-1">{incident.service}</span>
        <span className={cn('text-[10px] font-mono px-1.5 py-0.5 rounded border flex-shrink-0', symptomClass)}>
          {incident.symptom}
        </span>
      </div>

      {/* Bottom row: status word + timestamp */}
      <div className="flex items-center justify-between gap-1 text-[11px]">
        <span style={{ color: status.color }} className="font-medium">
          {status.word}
        </span>
        <span
          className="text-[var(--text-faint)] font-mono"
          title={abs}
        >
          {rel}
        </span>
      </div>
    </button>
  );
};
