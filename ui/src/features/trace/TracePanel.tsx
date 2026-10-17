import React from 'react';
import { cn } from '@/lib/utils';
import { useSelection } from '@/state/SelectionContext';
import { CypherDrawer, type CypherContext } from './CypherDrawer';
import type { TraceItem, TraceStep, TraceHandoff, TraceHypotheses, TraceVerification, TraceError, TraceDone, TraceWaiting } from '@/stream/reducer';
import {
  ChevronRight,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Brain,
  Loader2,
  Clock,
  Zap,
} from 'lucide-react';

// ─── Arg summaries ────────────────────────────────────────────────────────────

// Argument names match the MCP tool signatures in tracebrain/tools/mcp_server.py.
function summariseArgs(tool: string, args: Record<string, unknown>): string {
  switch (tool) {
    case 'blast_radius': return `${args.service ?? '?'}${args.max_hops ? ` · ≤${args.max_hops} hops` : ''}`;
    case 'owners_of': {
      const s = Array.isArray(args.services) ? (args.services as string[]) : [];
      return s.length <= 3 ? s.join(', ') : `${s.length} services`;
    }
    case 'suspects': return `${args.service ?? '?'} · ${args.window_hours ?? 24}h window`;
    case 'path_between': return `${args.from_service ?? '?'} → ${args.to_service ?? '?'}`;
    case 'recall_lessons': return `${args.service ?? 'alerted service'}`;
    case 'write_finding': return `kind: ${args.kind ?? '?'}`;
    case 'read_findings': return 'blackboard';
    case 'centrality': return 'PageRank + betweenness';
    case 'recall_similar': return 'confirmed incidents, same symptom';
    case 'get_past_investigation': return `${args.incident_id ?? '?'}`;
    default: return JSON.stringify(args).slice(0, 80);
  }
}

function preview(value: unknown, limit = 3000): string {
  const text = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
  return text.length > limit ? `${text.slice(0, limit)}\n… (${text.length - limit} more characters)` : text;
}

const AGENT_COLORS: Record<string, string> = {
  triage: 'var(--agent-triage)',
  investigator: 'var(--agent-investigator)',
  curator: 'var(--agent-curator)',
  orchestrator: 'var(--agent-orchestrator)',
};

// ─── Individual row renderers ─────────────────────────────────────────────────

const StepRow: React.FC<{ item: TraceStep; result?: unknown; context: CypherContext }> = ({ item, result, context }) => {
  const [open, setOpen] = React.useState(false);
  const { step } = item;
  const agentColor = AGENT_COLORS[step.agent] ?? 'var(--text-faint)';
  const { setHoveredClaimEdgeIds, pinEdges, pinnedEdgeIds } = useSelection();
  const edges = step.edge_ids ?? [];
  const pinned = edges.length > 0 && edges.length === pinnedEdgeIds.length && edges.every((e) => pinnedEdgeIds.includes(e));
  const shownResult = (step as { result?: unknown }).result ?? result;

  return (
    <div
      className={cn(
        'flex flex-col gap-1 py-1.5 px-2 rounded transition-colors border',
        step.error
          ? 'bg-[var(--status-bad)]/10 border-[var(--status-bad)]/30'
          : pinned
            ? 'bg-[var(--edge-cited)]/10 border-[var(--edge-cited)]/40'
            : 'border-transparent hover:bg-[var(--surface-hover)]/40 hover:border-[var(--border-subtle)]'
      )}
      // Hover shows this tool call's edges on the graph; clicking the tool name pins them.
      onMouseEnter={() => edges.length > 0 && setHoveredClaimEdgeIds(edges)}
      onMouseLeave={() => setHoveredClaimEdgeIds([])}
    >
      <div className="flex items-center gap-2">
        {/* Agent dot */}
        <span
          className="w-2 h-2 rounded-full flex-shrink-0 ring-1 ring-white/10"
          style={{ background: agentColor }}
          title={step.agent}
        />
        {/* Tool name: a button when the call returned graph edges, so it can be pinned by keyboard too */}
        {edges.length > 0 ? (
          <button
            type="button"
            onClick={() => pinEdges(pinned ? [] : edges)}
            onFocus={() => setHoveredClaimEdgeIds(edges)}
            onBlur={() => setHoveredClaimEdgeIds([])}
            title={pinned ? 'Unpin from graph' : "Pin this tool call's edges on the graph"}
            className="font-mono text-[12px] text-left text-[var(--text-primary)] flex-1 truncate hover:text-[var(--edge-cited)]"
          >
            {step.tool}
            <span className="text-[var(--text-faint)] ml-1">({summariseArgs(step.tool, step.args)})</span>
          </button>
        ) : (
          <span className="font-mono text-[12px] text-[var(--text-primary)] flex-1 truncate">
            {step.tool}
            <span className="text-[var(--text-faint)] ml-1">({summariseArgs(step.tool, step.args)})</span>
          </span>
        )}
        {/* Meta */}
        <div className="flex items-center gap-2 text-[10px] font-mono text-[var(--text-faint)] flex-shrink-0">
          <span>{step.ms}ms</span>
          {edges.length > 0 && (
            <span className="text-[var(--edge-cited)]">
              {edges.length} edge{edges.length === 1 ? '' : 's'}
            </span>
          )}
          {step.error && <AlertTriangle className="w-3 h-3 text-[var(--status-bad)]" />}
          <CypherDrawer
            tool={step.tool}
            agent={step.agent}
            args={step.args}
            edgeCount={edges.length}
            context={context}
            onOpen={() => edges.length > 0 && pinEdges(edges)}
          />
        </div>
        {/* Expand button */}
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="p-0.5 rounded text-[var(--text-faint)] hover:text-[var(--text-primary)] transition-colors flex-shrink-0"
          aria-label={open ? 'Collapse step' : 'Expand step'}
        >
          <ChevronRight className={cn('w-3 h-3 transition-transform', open && 'rotate-90')} />
        </button>
      </div>
      {step.error && (
        <p className="text-[11px] text-[var(--status-bad)] pl-4 font-mono">{step.error}</p>
      )}
      {open && (
        <div className="flex flex-col gap-1 mt-1">
          <span className="text-[10px] uppercase tracking-wider text-[var(--text-faint)]">Arguments</span>
          <pre className="text-[11px] font-mono text-[var(--text-secondary)] bg-[var(--bg-deep)] rounded p-2 overflow-x-auto leading-relaxed">
            {preview(step.args)}
          </pre>
          <span className="text-[10px] uppercase tracking-wider text-[var(--text-faint)]">Result from the graph</span>
          {shownResult === undefined ? (
            <p className="text-[11px] text-[var(--text-faint)] italic px-1">Shown once the run finishes.</p>
          ) : (
            <pre className="text-[11px] font-mono text-[var(--text-secondary)] bg-[var(--bg-deep)] rounded p-2 overflow-auto max-h-64 leading-relaxed">
              {preview(shownResult)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
};

const HandoffCard: React.FC<{ item: TraceHandoff }> = ({ item }) => {
  const [open, setOpen] = React.useState(false);
  const { handoff } = item;
  const fromColor = AGENT_COLORS[handoff.from] ?? 'var(--text-faint)';
  const toColor = AGENT_COLORS[handoff.to] ?? 'var(--text-faint)';

  return (
    <div className="my-1.5 mx-1 rounded border border-[var(--border-strong)] bg-[var(--surface-card)] overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full px-3 py-2 flex items-center gap-2 text-left hover:bg-[var(--surface-hover)]/40 transition-colors"
      >
        <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: fromColor }} />
        <span className="text-[11px] font-mono text-[var(--text-faint)]">{handoff.from}</span>
        <span className="text-[var(--text-faint)] mx-0.5">→</span>
        <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: toColor }} />
        <span className="text-[11px] font-mono text-[var(--text-faint)]">{handoff.to}</span>
        {handoff.findings?.length > 0 && (
          <span className="ml-auto text-[10px] font-mono text-[var(--text-faint)]">
            {handoff.findings.length} finding{handoff.findings.length !== 1 ? 's' : ''}
          </span>
        )}
        <ChevronRight className={cn('w-3 h-3 text-[var(--text-faint)] transition-transform', open && 'rotate-90')} />
      </button>
      {handoff.summary && (
        <div className="px-3 pb-1 text-[11px] text-[var(--text-secondary)] border-t border-[var(--border-subtle)]">
          <p className="pt-1.5">{handoff.summary}</p>
        </div>
      )}
      {open && handoff.findings?.length > 0 && (
        <pre className="text-[10px] font-mono text-[var(--text-secondary)] bg-[var(--bg-deep)] px-3 py-2 overflow-x-auto border-t border-[var(--border-subtle)]">
          {JSON.stringify(handoff.findings, null, 2)}
        </pre>
      )}
    </div>
  );
};

const HypothesesRow: React.FC<{ item: TraceHypotheses }> = ({ item }) => {
  const { h } = item;
  const total = h.hypotheses?.length ?? 0;
  const claims = h.hypotheses?.flatMap((hyp) => hyp.claims ?? []) ?? [];
  const verified = claims.filter((c) => c.verified).length;

  return (
    <div className="flex items-center gap-2 py-1.5 px-2 rounded bg-[var(--agent-investigator)]/10 border border-[var(--agent-investigator)]/20">
      <Brain className="w-3.5 h-3.5 text-[var(--agent-investigator)] flex-shrink-0" />
      <span className="text-xs text-[var(--text-primary)] flex-1">
        {h.abstain
          ? 'Abstained — no deploy supported by graph'
          : `${total} hypothesis${total !== 1 ? 'es' : ''} · ${verified}/${claims.length} claims verified`}
      </span>
      {typeof h.faithfulness === 'number' && (
        <span className="text-[10px] font-mono text-[var(--status-ok)]">
          {(h.faithfulness * 100).toFixed(0)}% faithful
        </span>
      )}
    </div>
  );
};

const VerificationRow: React.FC<{ item: TraceVerification }> = ({ item }) => {
  const { v } = item;
  const clears = v.clears;

  return (
    <div
      className={cn(
        'flex items-center gap-2 py-1.5 px-2 rounded border text-xs',
        clears === true
          ? 'bg-[var(--status-ok)]/10 border-[var(--status-ok)]/30 text-[var(--status-ok)]'
          : clears === false
            ? 'bg-[var(--status-bad)]/10 border-[var(--status-bad)]/30 text-[var(--status-bad)]'
            : 'bg-[var(--surface-card)] border-[var(--border-subtle)] text-[var(--text-secondary)]'
      )}
    >
      {clears === true ? (
        <CheckCircle2 className="w-3.5 h-3.5 flex-shrink-0" />
      ) : clears === false ? (
        <XCircle className="w-3.5 h-3.5 flex-shrink-0" />
      ) : (
        <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
      )}
      <span className="font-mono text-[11px]">{v.deploy_id}</span>
      <span>
        {clears === true ? 'rollback clears (simulated)' : clears === false ? 'rollback does not clear (simulated)' : 'could not determine'}
      </span>
    </div>
  );
};

const ErrorRow: React.FC<{ item: TraceError; onResume?: () => void }> = ({ item, onResume }) => (
  <div className="flex items-start gap-2 py-2 px-2 rounded border border-[var(--status-bad)]/40 bg-[var(--status-bad)]/10">
    <AlertTriangle className="w-3.5 h-3.5 text-[var(--status-bad)] flex-shrink-0 mt-0.5" />
    <div className="flex flex-col gap-1 flex-1 min-w-0">
      <span className="text-xs text-[var(--status-bad)] font-medium">Investigation error</span>
      <span className="text-[11px] text-[var(--text-secondary)] font-mono break-all">{item.message}</span>
      {onResume && (
        <button
          type="button"
          onClick={onResume}
          className="self-start mt-1 text-[11px] font-medium px-2 py-1 rounded bg-[var(--accent)]/15 text-[var(--accent)] hover:bg-[var(--accent)]/25 transition-colors"
        >
          Resume investigation →
        </button>
      )}
    </div>
  </div>
);

const DoneRow: React.FC<{ item: TraceDone }> = ({ item }) => (
  <div className="flex items-center gap-2 py-1.5 px-2 rounded border border-[var(--border-strong)] bg-[var(--surface-card)] text-xs text-[var(--text-secondary)]">
    <Zap className="w-3.5 h-3.5 text-[var(--accent)] flex-shrink-0" />
    <span>
      Finished in {item.payload.state} · {item.payload.tool_calls} tool calls
    </span>
    {typeof item.payload.faithfulness === 'number' && (
      <span className="ml-auto font-mono text-[10px] text-[var(--status-ok)]">
        {(item.payload.faithfulness * 100).toFixed(0)}% faithful
      </span>
    )}
  </div>
);

const WaitingRow: React.FC<{ item: TraceWaiting }> = ({ item }) => {
  const [seconds, setSeconds] = React.useState(0);
  React.useEffect(() => {
    const id = setInterval(() => {
      setSeconds(Math.floor((Date.now() - item.since) / 1000));
    }, 1000);
    return () => clearInterval(id);
  }, [item.since]);

  return (
    <div className="flex items-center gap-2 py-1.5 px-2 rounded border border-[var(--status-warn)]/30 bg-[var(--status-warn)]/10 text-xs text-[var(--status-warn)]">
      <Clock className="w-3.5 h-3.5 flex-shrink-0" />
      <span>Waiting for model · {seconds}s</span>
      <Loader2 className="w-3 h-3 ml-auto animate-spin flex-shrink-0" />
    </div>
  );
};

// ─── TracePanel ───────────────────────────────────────────────────────────────

interface TracePanelProps {
  rows: TraceItem[];
  /** Stored tool results by step number (live SSE steps carry no result). */
  results?: Map<number, unknown>;
  /** Incident context for filling query parameters in the Cypher drawer. */
  cypherContext?: CypherContext;
  onResume?: () => void;
  /** A run is in progress (shows a spinner in the empty state). */
  live?: boolean;
  emptyText?: string;
}

export const TracePanel: React.FC<TracePanelProps> = ({ rows, results, cypherContext = {}, onResume, live = false, emptyText }) => {
  const bottomRef = React.useRef<HTMLDivElement>(null);
  const listRef = React.useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = React.useState(true);
  const [newCount, setNewCount] = React.useState(0);
  const prevLen = React.useRef(rows.length);

  const scrollToBottom = () => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    setNewCount(0);
  };

  // Auto-scroll if user is at bottom; otherwise show pill
  React.useEffect(() => {
    if (rows.length <= prevLen.current) return;
    const diff = rows.length - prevLen.current;
    prevLen.current = rows.length;
    if (atBottom) {
      scrollToBottom();
    } else {
      setNewCount((n) => n + diff);
    }
  }, [rows.length, atBottom]);

  const handleScroll = () => {
    const el = listRef.current;
    if (!el) return;
    const threshold = 40;
    const isAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight <= threshold;
    setAtBottom(isAtBottom);
    if (isAtBottom) setNewCount(0);
  };

  if (rows.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-center p-6">
        <div className="flex flex-col items-center gap-2 max-w-[240px]">
          {live && <Loader2 className="w-5 h-5 text-[var(--accent)] animate-spin" />}
          <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
            {emptyText ?? 'Waiting for investigation events…'}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative flex-1 flex flex-col overflow-hidden">
      <div
        ref={listRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-2 py-2 flex flex-col gap-1 [&>*]:shrink-0"
      >
        {rows.map((item, i) => {
          const key = `${item.kind}-${item.seq}-${i}`;
          switch (item.kind) {
            case 'header':
              return (
                <div key={key} className="px-2 py-1 text-[11px] text-[var(--text-faint)] italic">
                  {item.text}
                </div>
              );
            case 'step':
              return <StepRow key={key} item={item} result={results?.get(item.step.n)} context={cypherContext} />;
            case 'handoff':
              return <HandoffCard key={key} item={item} />;
            case 'fallback':
              return (
                <div key={key} className="flex items-center gap-1.5 px-2 py-1 text-[11px] text-[var(--text-secondary)]">
                  <AlertTriangle className="w-3 h-3 text-[var(--status-warn)]" />
                  {item.text}
                </div>
              );
            case 'hypotheses_summary':
              return <HypothesesRow key={key} item={item} />;
            case 'verification_summary':
              return <VerificationRow key={key} item={item} />;
            case 'error':
              return <ErrorRow key={key} item={item} onResume={onResume} />;
            case 'done':
              return <DoneRow key={key} item={item} />;
            case 'reviewed':
              return (
                <div key={key} className="flex items-center gap-1.5 px-2 py-1 text-xs text-[var(--status-ok)]">
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  {item.payload.verdict === 'confirm' ? 'Confirmed' : 'Rejected'}
                  {item.payload.reviewer ? ` by ${item.payload.reviewer}` : ''}
                </div>
              );
            case 'waiting':
              return <WaitingRow key={key} item={item} />;
            default:
              return null;
          }
        })}
        <div ref={bottomRef} />
      </div>

      {/* New rows pill */}
      {!atBottom && newCount > 0 && (
        <button
          type="button"
          onClick={scrollToBottom}
          className="absolute bottom-2 left-1/2 -translate-x-1/2 px-3 py-1.5 rounded-full bg-[var(--accent)] text-[var(--text-inverse)] text-[10px] font-semibold shadow-lg hover:opacity-90 transition-opacity"
        >
          ↓ {newCount} new
        </button>
      )}
    </div>
  );
};
