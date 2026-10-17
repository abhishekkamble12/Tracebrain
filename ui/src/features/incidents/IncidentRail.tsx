import React, { useCallback, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useIncidents } from '@/api/hooks';
import { IncidentCard } from './IncidentCard';
import { cn } from '@/lib/utils';
import { Search, Brain, Loader2, AlertTriangle, RefreshCw } from 'lucide-react';
import type { IncidentRow } from '@/api/types';
import { isRunning } from '@/lib/status';
import { useMemory } from '@/state/MemoryContext';

type FilterMode = 'all' | 'needs_review' | 'not_investigated';

export const IncidentRail: React.FC = () => {
  const { tenant = 'payments', incidentId } = useParams<{ tenant: string; incidentId?: string }>();
  const navigate = useNavigate();

  const [query, setQuery] = React.useState('');
  const [filter, setFilter] = React.useState<FilterMode>('all');
  const { memoryEnabled, setMemoryEnabled } = useMemory();

  const { data: incidents, isLoading, isError, refetch } = useIncidents(tenant);

  // Poll while any incident has a running investigation
  const hasRunning = incidents?.some((i) => isRunning(i.investigation_state)) ?? false;
  useEffect(() => {
    if (!hasRunning) return;
    const id = setInterval(() => { void refetch(); }, 5000);
    return () => clearInterval(id);
  }, [hasRunning, refetch]);

  // Auto-select first priority incident on load
  useEffect(() => {
    if (incidentId || !incidents?.length) return;
    const priority =
      incidents.find((i) => i.investigation_state === 'AWAITING_REVIEW') ||
      incidents.find((i) => isRunning(i.investigation_state)) ||
      incidents.find((i) => !i.investigation) ||
      incidents[incidents.length - 1]; // newest
    if (priority) {
      navigate(`/t/${tenant}/incidents/${priority.id}`, { replace: true });
    }
  }, [incidents, incidentId, tenant, navigate]);

  // Keyboard j/k navigation
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (!incidents || (document.activeElement as HTMLElement)?.tagName === 'INPUT') return;
      if (e.key !== 'j' && e.key !== 'k') return;
      const visible = filtered(incidents, filter, query);
      const idx = visible.findIndex((i) => i.id === incidentId);
      const next = e.key === 'j' ? idx + 1 : idx - 1;
      if (next >= 0 && next < visible.length) {
        navigate(`/t/${tenant}/incidents/${visible[next].id}`);
      }
    },
    [incidents, incidentId, tenant, navigate, filter, query]
  );
  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  const displayed = React.useMemo(
    () => filtered(incidents ?? [], filter, query),
    [incidents, filter, query]
  );

  return (
    <aside className="w-[280px] border-r border-[var(--border-subtle)] bg-[var(--surface-panel)] flex flex-col overflow-hidden">
      {/* Header */}
      <div className="px-3 pt-3 pb-2 border-b border-[var(--border-subtle)] flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-semibold uppercase tracking-widest text-[var(--text-faint)]">
            Incidents
          </span>
          <button
            type="button"
            onClick={() => void refetch()}
            className="p-0.5 rounded text-[var(--text-faint)] hover:text-[var(--text-primary)] transition-colors"
            aria-label="Refresh incidents"
            title="Refresh"
          >
            <RefreshCw className="w-3 h-3" />
          </button>
        </div>

        {/* Memory switch */}
        <label className="flex items-center gap-2 cursor-pointer group py-1">
          <Brain className="w-3.5 h-3.5 text-[var(--agent-curator)] flex-shrink-0" />
          <span className="text-[11px] text-[var(--text-secondary)] group-hover:text-[var(--text-primary)] transition-colors flex-1">
            Memory for next run
          </span>
          <button
            type="button"
            role="switch"
            aria-checked={memoryEnabled}
            onClick={() => setMemoryEnabled(!memoryEnabled)}
            className={cn(
              'relative w-8 h-4.5 rounded-full transition-all duration-200 border flex-shrink-0',
              memoryEnabled
                ? 'bg-[var(--agent-curator)]/20 border-[var(--agent-curator)]/50'
                : 'bg-[var(--surface-hover)] border-[var(--border-strong)]'
            )}
          >
            <span
              className={cn(
                'absolute top-0.5 h-3 w-3 rounded-full transition-all duration-200',
                memoryEnabled
                  ? 'translate-x-4 bg-[var(--agent-curator)]'
                  : 'translate-x-0.5 bg-[var(--text-faint)]'
              )}
            />
          </button>
        </label>

        {/* Search */}
        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3 h-3 text-[var(--text-faint)]" />
          <input
            type="text"
            placeholder="Filter incidents…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="w-full bg-[var(--surface-card)] border border-[var(--border-subtle)] rounded pl-6 pr-2 py-1 text-xs text-[var(--text-primary)] placeholder-[var(--text-faint)] focus:outline-none focus:border-[var(--accent)] transition-colors"
          />
        </div>

        {/* Filter tabs */}
        <div className="flex gap-1">
          {(['all', 'needs_review', 'not_investigated'] as FilterMode[]).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setFilter(m)}
              className={cn(
                'flex-1 py-1 rounded text-[10px] font-medium transition-colors',
                filter === m
                  ? 'bg-[var(--accent)]/15 text-[var(--accent)] border border-[var(--accent)]/30'
                  : 'text-[var(--text-faint)] hover:text-[var(--text-secondary)] hover:bg-[var(--surface-hover)]'
              )}
            >
              {m === 'all' ? 'All' : m === 'needs_review' ? 'Review' : 'New'}
            </button>
          ))}
        </div>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto py-1 px-1">
        {isLoading ? (
          <div className="flex flex-col gap-1 p-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="h-[70px] rounded bg-[var(--surface-card)]/60 animate-pulse" />
            ))}
          </div>
        ) : isError ? (
          <div className="p-3 flex flex-col items-center gap-2 text-center mt-4">
            <AlertTriangle className="w-5 h-5 text-[var(--status-bad)]" />
            <p className="text-xs text-[var(--text-secondary)]">Failed to load incidents</p>
            <button
              type="button"
              onClick={() => void refetch()}
              className="text-[11px] text-[var(--accent)] hover:underline"
            >
              Retry
            </button>
          </div>
        ) : displayed.length === 0 ? (
          <div className="p-4 text-center text-xs text-[var(--text-faint)] mt-4">
            {query ? `No incidents match "${query}"` : 'No incidents in this tenant.'}
          </div>
        ) : (
          <div role="list">
            {displayed.map((inc) => (
              <IncidentCard
                key={inc.id}
                incident={inc}
                selected={inc.id === incidentId}
                onClick={() => navigate(`/t/${tenant}/incidents/${inc.id}`)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Footer: loading indicator */}
      {hasRunning && (
        <div className="px-3 py-2 border-t border-[var(--border-subtle)] flex items-center gap-1.5 text-[11px] text-[var(--accent)]">
          <Loader2 className="w-3 h-3 animate-spin" />
          <span>Investigation running…</span>
        </div>
      )}
    </aside>
  );
};

function filtered(incidents: IncidentRow[], mode: FilterMode, query: string): IncidentRow[] {
  let list = [...incidents].reverse(); // newest first
  if (mode === 'needs_review') {
    list = list.filter((i) => i.investigation_state === 'AWAITING_REVIEW');
  } else if (mode === 'not_investigated') {
    list = list.filter((i) => !i.investigation);
  }
  if (query) {
    const q = query.toLowerCase();
    list = list.filter(
      (i) =>
        i.id.toLowerCase().includes(q) ||
        i.service?.toLowerCase().includes(q) ||
        i.symptom?.toLowerCase().includes(q) ||
        i.text?.toLowerCase().includes(q)
    );
  }
  return list;
}
