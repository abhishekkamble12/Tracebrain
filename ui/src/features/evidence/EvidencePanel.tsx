import React from 'react';
import { cn } from '@/lib/utils';
import { useSelection } from '@/state/SelectionContext';
import type { HypothesesPayload } from '@/stream/reducer';
import type { Hypothesis, Claim, Features } from '@/api/types';
import type { MemoryRecall } from '@/lib/memoryRecall';
import { MemoryRecallCallout } from './MemoryRecallCallout';
import { CheckCircle2, XCircle, HelpCircle, Brain, ChevronDown, ChevronRight, ExternalLink, Sparkles } from 'lucide-react';

// ─── FaithfulnessMeter ───────────────────────────────────────────────────────

export const FaithfulnessMeter: React.FC<{ value: number }> = ({ value }) => {
  const pct = Math.round(value * 100);
  const color = pct >= 80 ? 'var(--status-ok)' : pct >= 50 ? 'var(--status-warn)' : 'var(--status-bad)';
  return (
    <div className="flex flex-col gap-1.5 p-2 rounded-md bg-[var(--surface-hover)]/30 border border-[var(--border-subtle)]">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-medium text-[var(--text-secondary)]">Graph Faithfulness</span>
        <span className="text-[11px] font-mono font-semibold" style={{ color }}>
          {pct}% verified
        </span>
      </div>
      <div className="w-full h-1.5 rounded-full bg-[var(--surface-hover)] overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-700 ease-out"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
    </div>
  );
};

// ─── ScoreBars ───────────────────────────────────────────────────────────────

const FEATURE_LABELS: Record<string, string> = {
  proximity: 'Proximity',
  recency: 'Recency',
  change_size: 'Change Size',
  fail_rate: 'Fail Rate',
  centrality: 'Centrality',
  lesson_match: 'Lesson Match',
};

export const ScoreBars: React.FC<{ features?: Features }> = ({ features }) => {
  if (!features || Object.keys(features).length === 0) return null;

  return (
    <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 pt-2 pb-1">
      {Object.entries(features).map(([key, rawVal]) => {
        const val = typeof rawVal === 'number' ? Math.max(0, Math.min(1, rawVal)) : 0;
        const pct = Math.round(val * 100);
        const isLesson = key === 'lesson_match';
        const isBoosted = isLesson && val > 0;

        return (
          <div key={key} className="flex flex-col gap-0.5">
            <div className="flex items-center justify-between text-[10px]">
              <span
                className={cn(
                  'truncate',
                  isBoosted
                    ? 'text-[var(--agent-curator)] font-semibold flex items-center gap-1'
                    : 'text-[var(--text-faint)]'
                )}
              >
                {isBoosted && <Sparkles className="w-2.5 h-2.5" />}
                {FEATURE_LABELS[key] ?? key}
              </span>
              <span
                className={cn(
                  'font-mono text-[9px]',
                  isBoosted ? 'text-[var(--agent-curator)] font-bold' : 'text-[var(--text-faint)]'
                )}
              >
                {val.toFixed(2)}
              </span>
            </div>
            <div className="w-full h-1 rounded-full bg-[var(--surface-hover)] overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{
                  width: `${pct}%`,
                  background: isBoosted
                    ? 'var(--agent-curator)'
                    : 'var(--accent)',
                  opacity: isBoosted ? 1 : 0.7,
                }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
};

// ─── ClaimRow ────────────────────────────────────────────────────────────────

interface ClaimRowProps {
  claim: Claim;
  onHoverEdges: (ids: number[]) => void;
  onPinEdges: (ids: number[]) => void;
}

export const ClaimRow: React.FC<ClaimRowProps> = ({ claim, onHoverEdges, onPinEdges }) => {
  const edgeIds: number[] = claim.edge_ids ?? [];

  return (
    <div
      className={cn(
        'group flex flex-col gap-1 py-1.5 px-2 rounded text-[11px] border border-transparent transition-all cursor-pointer',
        claim.verified
          ? 'bg-[var(--status-ok)]/5 hover:bg-[var(--status-ok)]/10 hover:border-[var(--status-ok)]/20'
          : claim.verified === false
            ? 'bg-[var(--status-bad)]/5 hover:bg-[var(--status-bad)]/10 hover:border-[var(--status-bad)]/20'
            : 'hover:bg-[var(--surface-hover)]/40 hover:border-[var(--border-subtle)]'
      )}
      onMouseEnter={() => edgeIds.length > 0 && onHoverEdges(edgeIds)}
      onMouseLeave={() => onHoverEdges([])}
      onClick={() => edgeIds.length > 0 && onPinEdges(edgeIds)}
    >
      <div className="flex items-start gap-2">
        {/* Verified badge */}
        {claim.verified === true ? (
          <CheckCircle2 className="w-3.5 h-3.5 text-[var(--status-ok)] flex-shrink-0 mt-0.5" />
        ) : claim.verified === false ? (
          <XCircle className="w-3.5 h-3.5 text-[var(--status-bad)] flex-shrink-0 mt-0.5" />
        ) : (
          <HelpCircle className="w-3.5 h-3.5 text-[var(--text-faint)] flex-shrink-0 mt-0.5" />
        )}

        {/* Claim text */}
        <span className="flex-1 text-[var(--text-secondary)] group-hover:text-[var(--text-primary)] transition-colors leading-relaxed">
          {claim.text}
        </span>

        {/* Edge pill */}
        {edgeIds.length > 0 && (
          <span className="flex-shrink-0 px-1.5 py-0.5 rounded text-[9px] font-mono text-[var(--edge-cited)] bg-[var(--edge-cited)]/10 border border-[var(--edge-cited)]/30 group-hover:bg-[var(--edge-cited)]/20 transition-colors">
            {edgeIds.length} edge{edgeIds.length > 1 ? 's' : ''}
          </span>
        )}
      </div>

      {/* Failure reason if unverified */}
      {claim.verified === false && claim.reason && (
        <div className="pl-5 text-[10px] text-[var(--status-bad)] font-mono">
          ↳ {claim.reason}
        </div>
      )}
    </div>
  );
};

// ─── HypothesisCard ──────────────────────────────────────────────────────────

interface HypothesisCardProps {
  hyp: Hypothesis;
  isFocused: boolean;
  onFocus: () => void;
  onBlur: () => void;
}

export const HypothesisCard: React.FC<HypothesisCardProps> = ({ hyp, isFocused, onFocus, onBlur }) => {
  const [open, setOpen] = React.useState(true);
  const { setHoveredClaimEdgeIds, pinEdges, clearPinnedEdges } = useSelection();

  const claims = hyp.claims ?? [];
  const verified = claims.filter((c) => c.verified === true).length;
  const refuted = claims.filter((c) => c.verified === false).length;
  const pending = claims.filter((c) => c.verified == null).length;
  // Weighted sum of the six features (scoring.py), not a probability, so it is shown as a number.
  const score = (hyp.score ?? 0).toFixed(2);

  return (
    <div
      className={cn(
        'rounded-lg border transition-all duration-200 overflow-hidden',
        isFocused
          ? 'border-[var(--status-suspect)]/70 bg-[var(--status-suspect)]/5 shadow-[0_0_16px_rgba(251,146,60,0.18)] ring-1 ring-[var(--status-suspect)]/50'
          : 'border-[var(--border-strong)] bg-[var(--surface-card)] hover:border-[var(--border-strong)]/80'
      )}
    >
      {/* Header */}
      <button
        type="button"
        onClick={() => {
          setOpen((v) => !v);
          if (!isFocused) onFocus();
          else onBlur();
        }}
        className="w-full flex items-start gap-2.5 px-3 py-2.5 text-left transition-colors hover:bg-[var(--surface-hover)]/30"
      >
        {/* Rank badge */}
        <span
          className="flex-shrink-0 w-5 h-5 rounded-full border flex items-center justify-center text-[10px] font-bold mt-0.5"
          style={{
            borderColor: isFocused ? 'var(--status-suspect)' : 'var(--border-strong)',
            backgroundColor: isFocused ? 'var(--status-suspect)' : 'transparent',
            color: isFocused ? 'var(--text-inverse)' : 'var(--text-faint)',
          }}
        >
          {hyp.rank}
        </span>

        <div className="flex-1 min-w-0">
          {/* Likely cause headline */}
          <p className="text-xs font-semibold text-[var(--text-primary)] leading-snug">
            {hyp.likely_cause || 'Root cause under investigation'}
          </p>

          {/* Service & Deploy info */}
          <div className="flex items-center gap-2 mt-1 text-[10px] flex-wrap">
            {hyp.service && (
              <span className="font-medium text-[var(--accent)] bg-[var(--accent)]/10 px-1.5 py-0.5 rounded border border-[var(--accent)]/20">
                {hyp.service}
              </span>
            )}
            {hyp.deploy_id && (
              <span className="font-mono text-[var(--status-suspect)]">
                {hyp.deploy_id}
              </span>
            )}
            {hyp.author && (
              <span className="text-[var(--text-faint)]">by {hyp.author}</span>
            )}
            {hyp.minutes_before !== undefined && (
              <span className="text-[var(--text-faint)]">({hyp.minutes_before}m prior)</span>
            )}
          </div>

          {/* Score & Claim verification counts */}
          <div className="flex items-center gap-2 mt-2 text-[10px] font-mono">
            <span
              className="font-bold text-[var(--text-primary)] bg-[var(--surface-hover)] px-1.5 py-0.5 rounded border border-[var(--border-subtle)]"
              title="Weighted sum of the score features below"
            >
              score {score}
            </span>
            {verified > 0 && <span className="text-[var(--status-ok)] font-medium">{verified} verified</span>}
            {refuted > 0 && <span className="text-[var(--status-bad)] font-medium">{refuted} refuted</span>}
            {pending > 0 && <span className="text-[var(--text-faint)]">{pending} pending</span>}
          </div>
        </div>

        <span className="flex-shrink-0 text-[var(--text-faint)] mt-1">
          {open ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
        </span>
      </button>

      {/* Expanded body */}
      {open && (
        <div className="border-t border-[var(--border-subtle)] px-3 py-2 flex flex-col gap-2 bg-[var(--surface-panel)]/40">
          {/* Summary / Reasoning */}
          {hyp.summary && (
            <div className="text-[11px] text-[var(--text-secondary)] leading-relaxed italic border-l-2 border-[var(--status-suspect)] pl-2 py-0.5">
              {hyp.summary}
            </div>
          )}

          {/* 6-Feature Score Decomposition */}
          {hyp.features && (
            <div className="border-t border-[var(--border-subtle)] pt-1">
              <span className="text-[10px] font-medium text-[var(--text-faint)] uppercase tracking-wider">
                Score Features
              </span>
              <ScoreBars features={hyp.features} />
            </div>
          )}

          {/* Claims grid */}
          {claims.length > 0 && (
            <div className="border-t border-[var(--border-subtle)] pt-2 flex flex-col gap-1">
              <span className="text-[10px] font-medium text-[var(--text-faint)] uppercase tracking-wider mb-0.5">
                Claims & Graph Linkages ({claims.length})
              </span>
              {claims.map((claim, i) => (
                <ClaimRow
                  key={claim.edge_ids?.join('-') || claim.text.slice(0, 32) || String(i)}
                  claim={claim}
                  onHoverEdges={setHoveredClaimEdgeIds}
                  onPinEdges={(ids) => {
                    if (ids.length) pinEdges(ids);
                    else clearPinnedEdges();
                  }}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// ─── AbstainCard ─────────────────────────────────────────────────────────────

export const AbstainCard: React.FC<{ reason: string | null }> = ({ reason }) => (
  <div className="rounded-lg border border-[var(--status-warn)]/30 bg-[var(--status-warn)]/5 p-4 flex flex-col gap-2">
    <div className="flex items-center gap-2 text-xs font-semibold text-[var(--status-warn)]">
      <Brain className="w-4 h-4" />
      <span>Investigator Abstained</span>
    </div>
    <p className="text-[11px] text-[var(--text-primary)] leading-relaxed">
      {reason ?? 'The reason is shown while the run streams; it is not stored with the investigation.'}
    </p>
    <div className="mt-1 text-[11px] text-[var(--text-secondary)] border-t border-[var(--status-warn)]/20 pt-2">
      Tracebrain names no culprit when the graph doesn't support one. Any page it proposed is in the Actions tab.
    </div>
  </div>
);

// ─── EvidencePanel ───────────────────────────────────────────────────────────

interface EvidencePanelProps {
  payload: HypothesesPayload | null;
  invHypotheses?: Hypothesis[];
  invFaithfulness?: number | null;
  invOutcome?: string | null;
  /** Memory this run recalled (from its stored recall_* steps). */
  recall?: MemoryRecall;
  memoryEnabled?: boolean | null;
}

export const EvidencePanel: React.FC<EvidencePanelProps> = ({
  payload,
  invHypotheses,
  invFaithfulness,
  invOutcome,
  recall,
  memoryEnabled,
}) => {
  const { focusedHypothesisRank, setFocusedHypothesis } = useSelection();

  // Combine live stream payload with persisted investigation hypotheses fallback
  // (an abstained run stores no hypotheses, so its outcome alone decides the abstain card)
  const h = payload ?? ((invHypotheses && invHypotheses.length > 0) || invOutcome === 'abstained' ? {
    hypotheses: invHypotheses ?? [],
    actions: [],
    abstain: invOutcome === 'abstained',
    abstain_reason: null,
    faithfulness: invFaithfulness ?? null,
    problems: [],
  } : null);

  if (!h) {
    return (
      <div className="flex-1 flex items-center justify-center text-center p-6">
        <div className="flex flex-col items-center gap-2 max-w-[220px]">
          <Brain className="w-8 h-8 text-[var(--text-faint)] opacity-30" />
          <p className="text-xs font-medium text-[var(--text-secondary)]">No Evidence Yet</p>
          <p className="text-[11px] text-[var(--text-faint)] leading-relaxed">
            Hypotheses and verified claims will appear here once the Investigator agent evaluates the graph.
          </p>
        </div>
      </div>
    );
  }

  if (h.abstain) {
    return (
      <div className="flex-1 p-3">
        <AbstainCard reason={h.abstain_reason} />
      </div>
    );
  }

  const problems = h.problems ?? [];

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Faithfulness bar */}
      {typeof h.faithfulness === 'number' && (
        <div className="px-3 py-2 border-b border-[var(--border-subtle)] bg-[var(--surface-card)]">
          <FaithfulnessMeter value={h.faithfulness} />
        </div>
      )}

      {/* Problems / warnings */}
      {problems.length > 0 && (
        <div className="px-3 py-1.5 border-b border-[var(--border-subtle)] bg-[var(--status-bad)]/10">
          {problems.map((p, i) => (
            <p key={i} className="text-[10px] text-[var(--status-bad)] font-mono leading-relaxed">⚠ {p}</p>
          ))}
        </div>
      )}

      {/* Hypothesis cards */}
      <div className="flex-1 overflow-y-auto p-2.5 flex flex-col gap-2.5">
        {recall && (
          <MemoryRecallCallout recall={recall} memoryEnabled={memoryEnabled} top={h.hypotheses[0]} />
        )}
        {h.hypotheses.map((hyp) => (
          <HypothesisCard
            key={hyp.rank}
            hyp={hyp}
            isFocused={focusedHypothesisRank === hyp.rank}
            onFocus={() => setFocusedHypothesis(hyp.rank)}
            onBlur={() => setFocusedHypothesis(null)}
          />
        ))}
      </div>

      {/* Graph legend footnote */}
      <div className="px-3 py-2 border-t border-[var(--border-subtle)] bg-[var(--surface-panel)] text-[10px] text-[var(--text-faint)] flex items-center gap-1.5">
        <ExternalLink className="w-3 h-3 text-[var(--edge-cited)]" />
        <span>Click a claim to pin edges · hover to spotlight on graph</span>
      </div>
    </div>
  );
};
