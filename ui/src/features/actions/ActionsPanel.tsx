import React from 'react';
import { cn } from '@/lib/utils';
import type { Action } from '@/api/types';
import type { VerificationPayload } from '@/stream/reducer';
import { RotateCcw, Ticket, Bell, CheckCircle2, XCircle, HelpCircle, Copy, Info, Layers } from 'lucide-react';
import { toast } from 'sonner';

interface ActionsPanelProps {
  actions?: Action[];
  /** Sandbox rollback check of the top hypothesis, if it ran. */
  verification?: VerificationPayload | null;
  incidentId?: string;
}

const KIND_LABEL: Record<Action['kind'], string> = {
  ticket: 'Ticket',
  rollback_proposal: 'Rollback proposal',
  page: 'Page owner',
};

const KIND_ICON: Record<Action['kind'], React.ReactNode> = {
  ticket: <Ticket className="w-3.5 h-3.5 text-[var(--accent)]" />,
  rollback_proposal: <RotateCcw className="w-3.5 h-3.5 text-[var(--status-suspect)]" />,
  page: <Bell className="w-3.5 h-3.5 text-[var(--status-warn)]" />,
};

/** One line describing the recorded rollback check; never claims more than `clears` says. */
const VerificationLine: React.FC<{ v: VerificationPayload }> = ({ v }) => (
  <div
    className={cn(
      'flex items-start gap-2 p-2.5 rounded-md border text-xs',
      v.clears === true && 'border-[var(--status-ok)]/30 bg-[var(--status-ok)]/5',
      v.clears === false && 'border-[var(--status-bad)]/30 bg-[var(--status-bad)]/5',
      v.clears == null && 'border-[var(--border-subtle)] bg-[var(--surface-panel)]'
    )}
  >
    {v.clears === true ? (
      <CheckCircle2 className="w-4 h-4 flex-shrink-0 text-[var(--status-ok)]" />
    ) : v.clears === false ? (
      <XCircle className="w-4 h-4 flex-shrink-0 text-[var(--status-bad)]" />
    ) : (
      <HelpCircle className="w-4 h-4 flex-shrink-0 text-[var(--text-secondary)]" />
    )}
    <div className="flex flex-col gap-0.5 min-w-0">
      <span className="text-[var(--text-primary)]">
        Rolling back <span className="font-mono">{v.deploy_id}</span>{' '}
        {v.clears === true ? 'clears the symptom' : v.clears === false ? 'does not clear the symptom' : 'could not be checked'}
      </span>
      {v.remaining_candidates != null && (
        <span className="text-[10px] text-[var(--text-secondary)]">
          Graph sandbox: with it rolled back,{' '}
          {v.next_suspect ? (
            <>next suspect is <span className="font-mono">{v.next_suspect}</span> on {v.next_suspect_service}</>
          ) : (
            'no other suspect remains'
          )}{' '}
          ({v.remaining_candidates} candidate{v.remaining_candidates === 1 ? '' : 's'})
        </span>
      )}
      <span className="text-[10px] text-[var(--text-secondary)]">Symptom check · {v.environment}</span>
    </div>
  </div>
);

export const ActionsPanel: React.FC<ActionsPanelProps> = ({ actions = [], verification, incidentId }) => {
  const copyAsTicket = async (act: Action) => {
    const text = [
      `[Tracebrain] ${KIND_LABEL[act.kind]}: ${act.target}`,
      incidentId ? `Incident: ${incidentId}` : null,
      `Reason: ${act.reason}`,
      'Proposed by the Tracebrain investigator. Review the cited evidence before acting.',
    ].filter(Boolean).join('\n');
    try {
      await navigator.clipboard.writeText(text);
      toast.success('Copied to clipboard');
    } catch {
      toast.error("Couldn't copy: clipboard access was blocked by the browser");
    }
  };

  if (!actions.length && !verification) {
    return (
      <div className="flex-1 flex items-center justify-center text-center p-6">
        <div className="flex flex-col items-center gap-2 max-w-[240px]">
          <Layers className="w-7 h-7 text-[var(--text-faint)]" />
          <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
            No actions proposed. The investigator proposes tickets, rollbacks and pages alongside its hypotheses.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col overflow-y-auto p-3 gap-3 [&>*]:shrink-0">
      <div className="flex items-start gap-2 p-2.5 rounded-md bg-[var(--surface-card)] border border-[var(--border-subtle)] text-[11px] leading-snug text-[var(--text-secondary)]">
        <Info className="w-3.5 h-3.5 flex-shrink-0 mt-0.5 text-[var(--accent)]" />
        <span>
          Proposals recorded on this investigation. Tracebrain does not execute them; an engineer decides.
        </span>
      </div>

      {verification && <VerificationLine v={verification} />}

      {actions.map((act, idx) => (
        <div
          key={act.id ?? `${act.kind}-${idx}`}
          className="p-3 rounded-lg border border-[var(--border-strong)] bg-[var(--surface-card)] flex flex-col gap-2"
        >
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-1.5">
              {KIND_ICON[act.kind]}
              <span className="text-xs font-semibold text-[var(--text-primary)]">{KIND_LABEL[act.kind] ?? act.kind}</span>
            </div>
            <span className="text-[11px] font-mono px-1.5 py-0.5 rounded bg-[var(--surface-hover)] text-[var(--text-secondary)] border border-[var(--border-subtle)] truncate">
              {act.target}
            </span>
          </div>

          {act.reason && <p className="text-xs text-[var(--text-secondary)] leading-relaxed">{act.reason}</p>}

          {act.kind === 'rollback_proposal' && verification?.deploy_id === act.target && (
            <p className="text-[11px] text-[var(--text-secondary)]">
              Sandbox check: {verification.clears === true ? '✓ clears the symptom' : verification.clears === false ? '✗ does not clear the symptom' : 'not determined'} (
              {verification.environment})
            </p>
          )}

          <div className="border-t border-[var(--border-subtle)] pt-2 flex items-center justify-between gap-2">
            <span className="text-[10px] text-[var(--text-secondary)] font-mono">
              {act.status ? `Status: ${act.status}` : 'Proposed · not executed'}
            </span>
            <button
              type="button"
              onClick={() => void copyAsTicket(act)}
              className="px-2 py-1 rounded text-[11px] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-hover)] border border-[var(--border-subtle)] flex items-center gap-1"
            >
              <Copy className="w-3 h-3" />
              Copy as text
            </button>
          </div>
        </div>
      ))}
    </div>
  );
};
