import React from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import { cn } from '@/lib/utils';
import { Brain } from 'lucide-react';
import { SERVICE_NODE_H, SERVICE_NODE_W } from './layout';

export interface ServiceNodeData {
  name: string;
  team?: string;
  /** The service the alert fired on. */
  alerted?: boolean;
  /** Hops from the alerted service, if it is in the as-of blast radius. */
  blastHops?: number | null;
  /** Number of ranked suspect deploys on this service. */
  suspects?: number;
  /** A tool call just referenced this service. */
  touched?: boolean;
  /** Off the highlighted path. */
  dimmed?: boolean;
  /** Recalled memory (a lesson or a confirmed precedent) points at this service. */
  recalled?: boolean;
}

export const ServiceNode: React.FC<NodeProps> = ({ data }) => {
  const d = data as unknown as ServiceNodeData;
  const inBlast = typeof d.blastHops === 'number';

  return (
    <div
      className={cn(
        'relative flex flex-col justify-center rounded-lg border select-none transition-[opacity,border-color,background-color] duration-200',
        d.alerted
          ? 'border-[var(--status-bad)] bg-[var(--status-bad)]/10 ring-2 ring-[var(--status-bad)]/40'
          : inBlast
            ? 'border-[var(--status-warn)]/60 bg-[var(--status-warn)]/10'
            : d.suspects
              ? 'border-[var(--status-suspect)]/70 bg-[var(--surface-card)]'
              : 'border-[var(--border-strong)] bg-[var(--surface-card)]',
        d.dimmed && 'opacity-35',
      )}
      style={{ width: SERVICE_NODE_W, height: SERVICE_NODE_H, padding: '6px 10px' }}
    >
      {d.touched && (
        <span className="absolute -inset-1 rounded-xl border-2 border-[var(--accent)] motion-safe:animate-ping opacity-40 pointer-events-none" />
      )}

      <div className="flex items-center gap-1.5 min-w-0">
        <span className="font-mono text-[16px] font-semibold text-[var(--text-primary)] truncate">{d.name}</span>
        {d.recalled && (
          <span
            className={cn(
              'flex-shrink-0 flex items-center gap-0.5 px-1 rounded text-[11px] bg-[var(--agent-curator)]/20 text-[var(--agent-curator)] font-medium',
              !d.alerted && !inBlast && 'ml-auto'
            )}
            title="A confirmed lesson or past incident points here"
          >
            <Brain className="w-3 h-3" /> lesson
          </span>
        )}
        {d.alerted && (
          <span className="ml-auto flex-shrink-0 text-[11px] font-bold tracking-wider px-1 rounded bg-[var(--status-bad)] text-white">
            ALERT
          </span>
        )}
        {!d.alerted && inBlast && (
          <span className="ml-auto flex-shrink-0 text-[11px] font-mono px-1 rounded border border-[var(--status-warn)]/50 text-[var(--status-warn)]">
            hop {d.blastHops}
          </span>
        )}
      </div>

      <div className="flex items-center gap-1.5 mt-0.5 text-[12px] min-w-0">
        <span className="text-[var(--text-secondary)] truncate">{d.team ?? 'no owner'}</span>
        {!!d.suspects && (
          <span className="ml-auto flex-shrink-0 font-mono text-[var(--status-suspect)]">
            {d.suspects} suspect{d.suspects > 1 ? 's' : ''}
          </span>
        )}
      </div>

      <Handle type="target" position={Position.Top} className="!opacity-0 !w-1 !h-1 !min-w-0 !min-h-0" />
      <Handle type="source" position={Position.Bottom} className="!opacity-0 !w-1 !h-1 !min-w-0 !min-h-0" />
      <Handle id="deploy-in" type="target" position={Position.Bottom} className="!opacity-0 !w-1 !h-1 !min-w-0 !min-h-0" />
    </div>
  );
};
