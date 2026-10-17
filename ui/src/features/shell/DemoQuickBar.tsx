import React from 'react';
import { useNavigate, useParams, Link } from 'react-router-dom';
import { Zap, Brain, Keyboard, BarChart3, ChevronDown, Flame, ShieldCheck } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useMemory } from '@/state/MemoryContext';
import { useIncidents } from '@/api/hooks';

interface DemoQuickBarProps {
  onOpenShortcuts: () => void;
}

// Demo beats from PLAN.md §8; only offered when the incident exists in the current tenant.
const DEMO_INCIDENTS = [
  { id: 'inc:001', label: 'RCA vs decoy', icon: Flame, color: 'var(--status-warn)' },
  { id: 'inc:025', label: 'Abstain', icon: ShieldCheck, color: 'var(--status-suspect)' },
];

/** Top-bar dropdown with shortcuts for recording the demo. */
export const DemoQuickBar: React.FC<DemoQuickBarProps> = ({ onOpenShortcuts }) => {
  const { tenant = 'payments' } = useParams<{ tenant: string }>();
  const navigate = useNavigate();
  const [open, setOpen] = React.useState(false);
  const rootRef = React.useRef<HTMLDivElement>(null);

  const { memoryEnabled, setMemoryEnabled } = useMemory();
  const { data: incidents } = useIncidents(tenant);
  const demos = DEMO_INCIDENTS.filter((d) => incidents?.some((i) => i.id === d.id));

  // Close on outside click or Escape
  React.useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const go = (incId: string) => {
    navigate(`/t/${tenant}/incidents/${incId}`);
    setOpen(false);
  };

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="true"
        className={cn(
          'flex items-center gap-1 px-2 py-1 rounded text-[11px] font-medium border transition-colors',
          open
            ? 'bg-[var(--surface-card)] text-[var(--text-primary)] border-[var(--border-strong)]'
            : 'text-[var(--text-secondary)] border-transparent hover:text-[var(--text-primary)] hover:bg-[var(--surface-card)]'
        )}
      >
        <Zap className="w-3.5 h-3.5 text-[var(--accent)]" />
        Demo
        <ChevronDown className={cn('w-3 h-3 transition-transform', open && 'rotate-180')} />
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 z-50 w-64 rounded-lg border border-[var(--border-strong)] bg-[var(--surface-panel)] p-3 shadow-[0_8px_24px_rgba(0,0,0,0.4)] flex flex-col gap-3">
          {demos.length > 0 && (
            <div className="flex flex-col gap-1.5">
              <span className="text-[10px] uppercase tracking-wider text-[var(--text-faint)]">Demo incidents</span>
              {demos.map((d) => (
                <button
                  key={d.id}
                  type="button"
                  onClick={() => go(d.id)}
                  className="px-2 py-1.5 rounded text-[11px] bg-[var(--surface-card)] hover:bg-[var(--surface-hover)] border border-[var(--border-subtle)] text-[var(--text-primary)] text-left flex items-center gap-2"
                >
                  <d.icon className="w-3 h-3 flex-shrink-0" style={{ color: d.color }} />
                  <span className="font-mono">{d.id}</span>
                  <span className="text-[var(--text-secondary)]">{d.label}</span>
                </button>
              ))}
            </div>
          )}

          <div className="flex items-center justify-between p-2 rounded bg-[var(--surface-card)] border border-[var(--border-subtle)]">
            <div className="flex items-center gap-2">
              <Brain className={cn('w-3.5 h-3.5', memoryEnabled ? 'text-[var(--agent-curator)]' : 'text-[var(--text-faint)]')} />
              <div className="flex flex-col">
                <span className="text-xs text-[var(--text-primary)]">Memory</span>
                <span className="text-[10px] text-[var(--text-faint)]">Applies to the next run</span>
              </div>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={memoryEnabled}
              onClick={() => setMemoryEnabled(!memoryEnabled)}
              className={cn(
                'px-2 py-0.5 rounded text-[10px] font-mono font-semibold border',
                memoryEnabled
                  ? 'bg-[var(--agent-curator)]/20 text-[var(--agent-curator)] border-[var(--agent-curator)]/40'
                  : 'bg-[var(--surface-hover)] text-[var(--text-secondary)] border-[var(--border-subtle)]'
              )}
            >
              {memoryEnabled ? 'ON' : 'OFF'}
            </button>
          </div>

          <div className="flex items-center justify-between pt-1 border-t border-[var(--border-subtle)]">
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                onOpenShortcuts();
              }}
              className="text-[11px] text-[var(--text-secondary)] hover:text-[var(--text-primary)] flex items-center gap-1"
            >
              <Keyboard className="w-3 h-3" />
              Shortcuts
            </button>
            <Link to="/results" onClick={() => setOpen(false)} className="text-[11px] text-[var(--accent)] hover:underline flex items-center gap-1">
              <BarChart3 className="w-3 h-3" />
              Results
            </Link>
          </div>
        </div>
      )}
    </div>
  );
};
