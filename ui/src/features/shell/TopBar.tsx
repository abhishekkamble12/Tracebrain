import React from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { useHealth, useMemory, useTenants, isTracebrainHealth } from '@/api/hooks';
import { Database, Cpu, Brain, Layers, Activity, HelpCircle } from 'lucide-react';
import { cn } from '@/lib/utils';
import { DemoQuickBar } from './DemoQuickBar';

const HealthDot: React.FC<{
  icon: React.ReactNode;
  state: 'ok' | 'warn' | 'bad' | 'idle';
  label: string;
  title?: string;
}> = ({ icon, state, label, title }) => (
  <div className="flex items-center gap-1.5" title={title ?? label}>
    {icon}
    <span
      className={cn(
        'w-2 h-2 rounded-full',
        state === 'ok' && 'bg-[var(--status-ok)]',
        state === 'warn' && 'bg-[var(--status-warn)]',
        state === 'bad' && 'bg-[var(--status-bad)]',
        state === 'idle' && 'bg-[var(--text-faint)]'
      )}
    />
    <span className={cn('font-mono text-[11px]', state === 'bad' ? 'text-[var(--status-bad)]' : 'text-[var(--text-secondary)]')}>
      {label}
    </span>
  </div>
);

interface TopBarProps {
  onOpenShortcuts?: () => void;
}

export const TopBar: React.FC<TopBarProps> = ({ onOpenShortcuts }) => {
  const { tenant } = useParams<{ tenant: string }>();
  const navigate = useNavigate();
  const location = useLocation();

  const currentTenant = tenant || 'payments';
  const { data: tenantsList } = useTenants();
  const { data: health, isLoading: healthLoading } = useHealth();
  const apiOk = isTracebrainHealth(health);
  const { data: mem } = useMemory(currentTenant);

  const activeLessonCount = mem?.lessons?.filter((l) => !l.retracted)?.length ?? 0;

  const [bouncing, setBouncing] = React.useState(false);
  const prevLessonCount = React.useRef(activeLessonCount);

  React.useEffect(() => {
    if (activeLessonCount !== prevLessonCount.current) {
      prevLessonCount.current = activeLessonCount;
      setBouncing(true);
      const t = setTimeout(() => setBouncing(false), 1000);
      return () => clearTimeout(t);
    }
  }, [activeLessonCount]);

  const isConsole = location.pathname.startsWith(`/t/${currentTenant}/incidents`) || location.pathname === `/t/${currentTenant}`;
  const isMemory = location.pathname.startsWith(`/t/${currentTenant}/memory`);
  const isResults = location.pathname.startsWith('/results');

  const handleTenantChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const nextTenant = e.target.value;
    navigate(`/t/${nextTenant}`);
  };

  return (
    <header className="h-12 border-b border-[var(--border-subtle)] bg-[var(--surface-panel)]/90 backdrop-blur-md px-4 flex items-center justify-between z-40 select-none">
      {/* Brand & Tenant Switcher */}
      <div className="flex items-center gap-4">
        <Link to={`/t/${currentTenant}`} className="flex items-center gap-2 group">
          <div className="w-6 h-6 rounded bg-[var(--accent)]/15 border border-[var(--accent)]/30 flex items-center justify-center text-[var(--accent)] group-hover:scale-105 transition-transform">
            <Activity className="w-3.5 h-3.5" />
          </div>
          <span className="font-mono text-sm font-semibold tracking-wider text-[var(--text-primary)]">
            TRACEBRAIN
          </span>
        </Link>

        {/* Tenant selector */}
        <div className="flex items-center gap-1.5 bg-[var(--surface-card)] border border-[var(--border-subtle)] rounded px-2 py-0.5 text-xs">
          <Layers className="w-3 h-3 text-[var(--text-faint)]" />
          <select
            value={currentTenant}
            onChange={handleTenantChange}
            className="bg-transparent text-[var(--text-secondary)] font-mono focus:outline-none cursor-pointer pr-1"
          >
            {tenantsList?.map((t) => (
              <option key={t} value={t} className="bg-[var(--surface-panel)] text-[var(--text-primary)]">
                {t}
              </option>
            )) || <option value={currentTenant}>{currentTenant}</option>}
          </select>
        </div>
      </div>

      {/* Primary Nav */}
      <nav className="flex items-center gap-1">
        <Link
          to={`/t/${currentTenant}`}
          className={cn(
            'px-3 py-1 rounded text-xs font-medium transition-colors',
            isConsole
              ? 'bg-[var(--surface-card)] text-[var(--accent)] border border-[var(--accent)]/20 shadow-sm'
              : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-card)]/50'
          )}
        >
          Console
        </Link>
        <Link
          to={`/t/${currentTenant}/memory`}
          className={cn(
            'px-3 py-1 rounded text-xs font-medium transition-colors flex items-center gap-1.5',
            isMemory
              ? 'bg-[var(--surface-card)] text-[var(--accent)] border border-[var(--accent)]/20 shadow-sm'
              : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-card)]/50'
          )}
        >
          <Brain className="w-3.5 h-3.5" />
          <span>Memory</span>
          {activeLessonCount > 0 && (
            <span className={cn(
              'px-1.5 py-0.2 rounded-full text-[10px] font-mono bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/30',
              bouncing && 'animate-bounce'
            )}>
              {activeLessonCount}
            </span>
          )}
        </Link>
        <Link
          to="/results"
          className={cn(
            'px-3 py-1 rounded text-xs font-medium transition-colors',
            isResults
              ? 'bg-[var(--surface-card)] text-[var(--accent)] border border-[var(--accent)]/20 shadow-sm'
              : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-card)]/50'
          )}
        >
          Results
        </Link>
      </nav>

      {/* System Health Indicators & Help */}
      <div className="flex items-center gap-3 text-xs">
        {apiOk ? (
          <>
            <HealthDot
              icon={<Database className="w-3.5 h-3.5 text-[var(--text-faint)]" />}
              state={health.falkordb ? 'ok' : 'bad'}
              label={health.falkordb ? 'FalkorDB' : 'FalkorDB down'}
            />
            <HealthDot
              icon={<Cpu className="w-3.5 h-3.5 text-[var(--text-faint)]" />}
              state={health.llm_providers.length ? 'ok' : 'warn'}
              label={health.llm_providers[0] ?? 'No LLM key'}
              title={health.llm_providers.join(', ') || 'No LLM provider configured'}
            />
            {health.running > 0 && (
              <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-[var(--accent)]/15 text-[var(--accent)]">
                {health.running} running
              </span>
            )}
          </>
        ) : (
          <HealthDot
            icon={<Database className="w-3.5 h-3.5 text-[var(--text-faint)]" />}
            state={healthLoading ? 'idle' : 'bad'}
            label={healthLoading ? 'Connecting…' : 'API offline'}
          />
        )}

        <DemoQuickBar onOpenShortcuts={() => onOpenShortcuts?.()} />

        {/* Help tooltip button */}
        <button
          type="button"
          onClick={() => onOpenShortcuts?.()}
          className="p-1 rounded text-[var(--text-faint)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-card)] transition-colors"
          aria-label="Keyboard shortcuts"
          title="Keyboard shortcuts (?)"
        >
          <HelpCircle className="w-3.5 h-3.5" />
        </button>
      </div>
    </header>
  );
};
