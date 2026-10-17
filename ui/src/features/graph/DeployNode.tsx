import React from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import { cn } from '@/lib/utils';
import { GitCommitVertical, Check, X } from 'lucide-react';

export interface DeployNodeData {
  deployId: string;
  kind?: string;
  /** Minutes between the deploy and the incident. */
  minutesBefore?: number | null;
  /** Hypothesis rank, if the investigator ranked this deploy. */
  rank?: number | null;
  /** Simulated sandbox rollback result for this deploy, if checked. */
  clears?: boolean | null;
  dimmed?: boolean;
  /** Overflow pill: "+n more" deploys on the same service. */
  more?: number;
}

export const DeployNode: React.FC<NodeProps> = ({ data }) => {
  const d = data as unknown as DeployNodeData;
  const ranked = typeof d.rank === 'number';

  if (d.more) {
    return (
      <div className="font-mono text-[10px] text-[var(--text-faint)] px-2" style={{ width: 150 }}>
        +{d.more} more deploys
        <Handle type="source" position={Position.Top} className="!opacity-0" />
      </div>
    );
  }

  return (
    <div
      className={cn(
        'flex items-center gap-1.5 rounded-md border px-1.5 transition-opacity duration-200',
        ranked
          ? 'bg-[var(--status-suspect)]/12 border-[var(--status-suspect)]/60'
          : 'bg-[var(--surface-panel)] border-[var(--border-subtle)]',
        d.dimmed && 'opacity-35',
      )}
      style={{ width: 150, height: 30 }}
      title={`${d.deployId}${d.kind ? ` · ${d.kind}` : ''}`}
    >
      {ranked ? (
        <span className="flex-shrink-0 w-4 h-4 rounded-full bg-[var(--status-suspect)] text-[var(--text-inverse)] text-[9px] font-bold flex items-center justify-center">
          {d.rank}
        </span>
      ) : (
        <GitCommitVertical className="w-3.5 h-3.5 flex-shrink-0 text-[var(--text-faint)]" />
      )}
      <div className="flex flex-col min-w-0 leading-tight">
        <span className={cn('font-mono text-[10px] truncate', ranked ? 'text-[var(--text-primary)]' : 'text-[var(--text-secondary)]')}>
          {d.deployId}
        </span>
        <span className="font-mono text-[9px] text-[var(--text-faint)] truncate">
          {[d.kind, typeof d.minutesBefore === 'number' ? `${d.minutesBefore}m before` : null].filter(Boolean).join(' · ')}
        </span>
      </div>
      {d.clears === true && (
        <span className="ml-auto flex-shrink-0 flex items-center text-[var(--status-ok)]" title="Simulated rollback clears the symptom">
          <Check className="w-3 h-3" />
        </span>
      )}
      {d.clears === false && (
        <span className="ml-auto flex-shrink-0 flex items-center text-[var(--status-bad)]" title="Simulated rollback does not clear the symptom">
          <X className="w-3 h-3" />
        </span>
      )}

      <Handle type="source" position={Position.Top} className="!opacity-0 !w-1 !h-1 !min-w-0 !min-h-0" />
    </div>
  );
};
