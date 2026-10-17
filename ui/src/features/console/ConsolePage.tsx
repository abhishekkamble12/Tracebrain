import React from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useIncidents, useInvestigation, useStartInvestigation } from '@/api/hooks';
import { IncidentRail } from '@/features/incidents/IncidentRail';
import { TracePanel } from '@/features/trace/TracePanel';
import { Stepper, RunStats } from './Stepper';
import { useInvestigationStream } from '@/stream/useInvestigationStream';
import { apiPost } from '@/api/client';
import { cn } from '@/lib/utils';
import { isRunning, isTerminal, formatUtcTimestamp } from '@/lib/status';
import { Play, RotateCcw, Loader2, Brain, Clock } from 'lucide-react';
import { toast } from 'sonner';
import type { InvestigationState, Action } from '@/api/types';
import { GraphStage } from '@/features/graph/GraphStage';
import { useSelection } from '@/state/SelectionContext';
import { useMemory } from '@/state/MemoryContext';
import { EvidencePanel } from '@/features/evidence/EvidencePanel';
import { ActionsPanel } from '@/features/actions/ActionsPanel';
import { ReviewBox } from '@/features/review/ReviewBox';
import { SelectionProvider } from '@/state/SelectionContext';
import type { IncidentRow } from '@/api/types';
import { memoryRecall } from '@/lib/memoryRecall';

export const ConsolePage: React.FC = () => {
  const { tenant = 'payments', incidentId, invId } = useParams<{
    tenant: string;
    incidentId?: string;
    invId?: string;
  }>();

  const { data: incidents } = useIncidents(tenant);
  const incident = incidents?.find((i) => i.id === incidentId);

  // Resolve active investigation id: URL pinned > incident's latest
  const activeInvId = invId ?? incident?.investigation ?? undefined;

  return (
    <div className="flex-1 flex w-full h-full overflow-hidden">
      {/* ── Left Rail ─────────────────────────────────────────────────── */}
      <IncidentRail />

      {/* Everything run-scoped (stream reducer, selection, tabs, review form) remounts when the run
          changes, so state from one investigation can never leak into another. */}
      <SelectionProvider key={`${tenant}/${incidentId ?? ''}/${activeInvId ?? ''}`}>
        <ConsoleRun tenant={tenant} incidentId={incidentId} incident={incident} activeInvId={activeInvId} />
      </SelectionProvider>
    </div>
  );
};

interface ConsoleRunProps {
  tenant: string;
  incidentId?: string;
  incident?: IncidentRow;
  activeInvId?: string;
}

const ConsoleRun: React.FC<ConsoleRunProps> = ({ tenant, incidentId, incident, activeInvId }) => {
  const navigate = useNavigate();

  const { memoryEnabled, setMemoryEnabled } = useMemory();
  const { activeTopoMode, setTopoMode, clearPinnedEdges } = useSelection();

  const { data: inv, refetch: refetchInv } = useInvestigation(tenant, activeInvId);

  // Only a live task produces events (this includes a FAILED run that was just resumed).
  const streamEnabled = Boolean(activeInvId && inv?.running);

  // Bumped on Resume so the stream re-reads history from the start: after a server restart the
  // event bus numbers events from 1 again.
  const [streamEpoch, setStreamEpoch] = React.useState(0);

  const runView = useInvestigationStream(tenant, activeInvId, {
    enabled: streamEnabled,
    inv,
    epoch: streamEpoch,
  });

  // Invalidate on done/reviewed
  React.useEffect(() => {
    if (runView.connection === 'closed' && runView.rows.some((r) => r.kind === 'done')) {
      void refetchInv();
    }
  }, [runView.connection, runView.rows, refetchInv]);

  const startMutation = useStartInvestigation(tenant);

  // ─── Investigate handler ──────────────────────────────────────────────────
  const handleInvestigate = async () => {
    if (!incidentId) return;
    try {
      const result = await startMutation.mutateAsync({ incidentId, memoryEnabled });
      navigate(`/t/${tenant}/incidents/${incidentId}/runs/${result.investigation_id}`);
    } catch (e: unknown) {
      const err = e as { detail?: string; message?: string };
      toast.error(err.detail ?? err.message ?? 'Failed to start investigation');
    }
  };

  // ─── Resume handler ──────────────────────────────────────────────────────
  const handleResume = async () => {
    if (!activeInvId) return;
    try {
      await apiPost(`/tenants/${tenant}/investigations/${activeInvId}/resume`);
      setStreamEpoch((e) => e + 1);
      void refetchInv();
    } catch (e: unknown) {
      const err = e as { detail?: string; message?: string };
      if ((err as { status?: number }).status === 409) {
        // already running — just reattach stream
        void refetchInv();
      } else {
        toast.error(err.detail ?? err.message ?? 'Failed to resume');
      }
    }
  };

  // ─── Derive states ────────────────────────────────────────────────────────
  const invState = (runView.state ?? inv?.state ?? null) as InvestigationState | null;
  const isLive = runView.live || (inv?.running ?? false);
  const isFailed = invState === 'FAILED';
  const isInterrupted = !isLive && Boolean(inv) && isRunning(invState) && !isFailed;

  // ─── Primary action button logic ─────────────────────────────────────────
  const renderPrimaryAction = () => {
    if (!incidentId) return null;

    if (isLive) {
      return (
        <button
          type="button"
          disabled
          className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-[var(--accent)]/10 text-[var(--accent)] border border-[var(--accent)]/20 cursor-not-allowed"
        >
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
          Investigating…
        </button>
      );
    }

    if (isFailed || isInterrupted) {
      return (
        <button
          type="button"
          onClick={() => void handleResume()}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-[var(--status-warn)]/15 text-[var(--status-warn)] border border-[var(--status-warn)]/30 hover:bg-[var(--status-warn)]/25 transition-colors"
        >
          <RotateCcw className="w-3.5 h-3.5" />
          Resume
        </button>
      );
    }

    if (!inv) {
      return (
        <button
          type="button"
          onClick={() => void handleInvestigate()}
          disabled={startMutation.isPending}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-semibold bg-[var(--accent)] text-[var(--text-inverse)] hover:opacity-90 disabled:opacity-50 transition-all"
        >
          {startMutation.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
          Investigate
        </button>
      );
    }

    if (isTerminal(invState) || invState === 'AWAITING_REVIEW') {
      return (
        <button
          type="button"
          onClick={() => void handleInvestigate()}
          disabled={startMutation.isPending}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-[var(--surface-card)] text-[var(--text-secondary)] border border-[var(--border-subtle)] hover:border-[var(--accent)]/50 hover:text-[var(--accent)] transition-colors"
        >
          <RotateCcw className="w-3.5 h-3.5" />
          Run again
        </button>
      );
    }

    return null;
  };

  // ─── Tab management ───────────────────────────────────────────────────────
  const [activeTab, setActiveTab] = React.useState<'trace' | 'evidence' | 'actions'>('trace');

  // Auto-switch to evidence when hypotheses arrive
  React.useEffect(() => {
    if (runView.hypotheses) setActiveTab('evidence');
  }, [runView.hypotheses]);

  // ─── Keyboard shortcuts ───────────────────────────────────────────────────
  React.useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (document.activeElement as HTMLElement)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      if (e.altKey || e.ctrlKey || e.metaKey) return; // Alt+digits navigate (AppShell)
      switch (e.key) {
        case 'Escape':
          clearPinnedEdges();
          break;
        case 'I':
        case 'i':
          if (!inv && !isLive) void handleInvestigate();
          break;
        case 'R':
        case 'r':
          if (isFailed || isInterrupted) void handleResume();
          break;
        case 'M':
        case 'm':
          setMemoryEnabled(!memoryEnabled);
          break;
        case 'T':
        case 't':
          setTopoMode(activeTopoMode === 'asof' ? 'now' : 'asof');
          break;
        case '1':
          setActiveTab('trace');
          break;
        case '2':
          setActiveTab('evidence');
          break;
        case '3':
          setActiveTab('actions');
          break;
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [inv, isLive, isFailed, isInterrupted, memoryEnabled, setMemoryEnabled, activeTopoMode, setTopoMode, clearPinnedEdges]);

  const reconnectStatus = runView.connection;

  // Sandbox rollback check of the top hypothesis: live event, else the stored Verification node
  const topHyp = (runView.hypotheses?.hypotheses ?? inv?.hypotheses ?? [])[0];
  const storedCheck = topHyp?.verifications?.[0];
  const topVerification =
    runView.verification ??
    (topHyp && storedCheck
      ? { deploy_id: topHyp.deploy_id, clears: storedCheck.clears, environment: storedCheck.environment,
          next_suspect: storedCheck.next_suspect, next_suspect_service: storedCheck.next_suspect_service,
          remaining_candidates: storedCheck.remaining_candidates }
      : null);

  const recall = React.useMemo(() => memoryRecall(inv?.steps), [inv?.steps]);

  const stepResults = React.useMemo(
    () => new Map((inv?.steps ?? []).map((s) => [s.n, s.result] as [number, unknown])),
    [inv?.steps]
  );

  return (
    <>
      {/* ── Centre: Graph Stage ───────────────────────────────────────── */}
      <section className="flex-1 flex flex-col bg-[var(--bg-deep)] relative overflow-hidden">
        {/* Incident Header */}
        {incident ? (
          <div className="border-b border-[var(--border-subtle)] bg-[var(--surface-panel)]/70 backdrop-blur-sm px-4 py-2.5 flex flex-col gap-1.5">
            <div className="flex items-start justify-between gap-2">
              <div className="flex items-center gap-2 min-w-0">
                <span className="font-mono text-[11px] text-[var(--text-faint)]">{incident.id}</span>
                <span
                  className={cn(
                    'text-[10px] font-mono px-1.5 py-0.5 rounded border',
                    incident.severity === 'sev1'
                      ? 'bg-[var(--status-bad)]/20 text-[var(--status-bad)] border-[var(--status-bad)]/40'
                      : 'bg-[var(--status-warn)]/10 text-[var(--status-warn)] border-[var(--status-warn)]/30'
                  )}
                >
                  {incident.severity?.toUpperCase()}
                </span>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                {renderPrimaryAction()}
              </div>
            </div>

            <p className="text-sm font-medium text-[var(--text-primary)] truncate">{incident.text}</p>

            <div className="flex items-center gap-3 text-[11px] text-[var(--text-faint)] flex-wrap">
              <span className="flex items-center gap-1">
                <Clock className="w-3 h-3" />
                <span className="font-mono">As of {formatUtcTimestamp(incident.ts)}</span>
              </span>
              {inv && (
                <span className="flex items-center gap-1">
                  <Brain className="w-3 h-3 text-[var(--agent-curator)]" />
                  <span>Memory: {inv.memory_enabled ? 'ON' : 'OFF'}</span>
                </span>
              )}
              {reconnectStatus === 'reconnecting' && (
                <span className="flex items-center gap-1 text-[var(--status-warn)] animate-pulse">
                  <Loader2 className="w-3 h-3 animate-spin" />
                  Reconnecting…
                </span>
              )}
            </div>
          </div>
        ) : (
          <div className="border-b border-[var(--border-subtle)] bg-[var(--surface-panel)]/70 px-4 py-3">
            <p className="text-xs text-[var(--text-secondary)]">
              {incidentId ? `Incident ${incidentId} not found in this tenant.` : 'Select an incident to investigate. Showing the current topology.'}
            </p>
          </div>
        )}

        {/* Graph Stage */}
        <div className="flex-1 relative overflow-hidden">
          <GraphStage runView={runView} inv={inv} tenant={tenant} incident={incident} />
        </div>

        {/* Topology Toggle */}
        <div className="border-t border-[var(--border-subtle)] flex flex-col bg-[var(--surface-panel)]/50">
          <div className="px-4 py-2 flex items-center gap-3">
            <div className="flex items-center gap-1">
              <button type="button" onClick={() => setTopoMode('asof')}
                className={`flex items-center gap-1.5 px-2 py-1 rounded text-[11px] font-medium border transition-colors ${activeTopoMode === 'asof'
                  ? 'bg-[var(--accent)]/15 text-[var(--accent)] border-[var(--accent)]/30'
                  : 'text-[var(--text-faint)] border-transparent hover:text-[var(--text-secondary)]'
                  }`}>
                As-Of
              </button>
              <button type="button" onClick={() => setTopoMode('now')}
                className={`flex items-center gap-1.5 px-2 py-1 rounded text-[11px] font-medium border transition-colors ${activeTopoMode === 'now'
                  ? 'bg-[var(--status-warn)]/15 text-[var(--status-warn)] border-[var(--status-warn)]/30'
                  : 'text-[var(--text-faint)] border-transparent hover:text-[var(--text-secondary)]'
                  }`}>
                Now
              </button>
            </div>
            {activeTopoMode === 'now' && (
              <p className="text-[10px] text-[var(--status-warn)] font-mono">⚠ not as-of-incident snapshot</p>
            )}
          </div>
        </div>
      </section>

      {/* ── Right Panel: Investigation Inspector ──────────────────────── */}
      <aside className="w-[420px] border-l border-[var(--border-subtle)] bg-[var(--surface-panel)] flex flex-col overflow-hidden">
        {/* Stepper + Stats */}
        <div className="px-3 py-2.5 border-b border-[var(--border-subtle)] flex flex-col gap-2">
          <Stepper state={invState} failed={isFailed} check={topVerification?.clears} />
          <RunStats inv={inv} runView={runView} />
        </div>

        {/* Tabs */}
        <div className="flex border-b border-[var(--border-subtle)]">
          {(['trace', 'evidence', 'actions'] as const).map((tab) => (
            <button
              key={tab}
              type="button"
              onClick={() => setActiveTab(tab)}
              className={cn(
                'flex-1 py-2 text-[11px] font-medium capitalize transition-colors',
                activeTab === tab
                  ? 'border-b-2 border-[var(--accent)] text-[var(--accent)] bg-[var(--accent)]/5'
                  : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] border-b-2 border-transparent'
              )}
            >
              {tab}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {activeTab === 'trace' && (
            <TracePanel
              rows={runView.rows}
              results={stepResults}
              cypherContext={{ t: incident?.ts, service: incident?.service, symptom: incident?.symptom }}
              onResume={handleResume}
              live={isLive}
              emptyText={
                !incident
                  ? 'Select an incident on the left to see its investigation.'
                  : !activeInvId
                    ? 'Not investigated yet. Press Investigate to start a run.'
                    : isLive
                      ? 'Waiting for investigation events…'
                      : 'No steps recorded for this run.'
              }
            />
          )}
          {activeTab === 'evidence' && (
            <EvidencePanel
              payload={runView.hypotheses}
              invHypotheses={inv?.hypotheses}
              invFaithfulness={inv?.faithfulness}
              invOutcome={inv?.outcome}
              recall={recall}
              memoryEnabled={inv?.memory_enabled}
            />
          )}
          {activeTab === 'actions' && (
            <ActionsPanel
              actions={((runView.hypotheses?.actions as unknown as Action[]) || inv?.actions || [])}
              verification={topVerification}
              incidentId={incident?.id}
            />
          )}
        </div>

        {/* Sticky Review Dock */}
        {activeInvId && (
          <ReviewBox
            tenant={tenant}
            invId={activeInvId}
            state={invState}
            outcome={inv?.outcome}
            hypotheses={runView.hypotheses?.hypotheses ?? inv?.hypotheses}
            onReviewed={() => {
              void refetchInv();
            }}
          />
        )}
      </aside>
    </>
  );
};
