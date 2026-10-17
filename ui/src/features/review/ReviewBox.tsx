import React from 'react';
import { useReview } from '@/api/hooks';
import type { Hypothesis, InvestigationState } from '@/api/types';
import type { VerificationPayload } from '@/stream/reducer';
import {
  CheckCircle2,
  XCircle,
  Brain,
  User,
  Loader2,
  Sparkles,
  ArrowRight,
} from 'lucide-react';
import { toast } from 'sonner';
import { Link } from 'react-router-dom';

interface ReviewBoxProps {
  tenant: string;
  invId: string;
  state: InvestigationState | null;
  /** Investigation outcome; tells a confirmed LEARNED run from a rejected one. */
  outcome?: string | null;
  hypotheses?: Hypothesis[];
  /** Sandbox rollback check of the top hypothesis (guides the default selection). */
  verification?: VerificationPayload | null;
  onReviewed?: () => void;
}

export const ReviewBox: React.FC<ReviewBoxProps> = ({
  tenant,
  invId,
  state,
  outcome,
  hypotheses = [],
  verification,
  onReviewed,
}) => {
  // The reviewer is recorded as provenance on the cause link, so it is never defaulted to a made-up name.
  const [reviewer, setReviewer] = React.useState(() => {
    try {
      return localStorage.getItem('tracebrain.reviewer') || '';
    } catch {
      return '';
    }
  });

  const [selectedDeployId, setSelectedDeployId] = React.useState<string>(() => {
    return hypotheses[0]?.deploy_id || '';
  });

  const [causeText, setCauseText] = React.useState<string>(() => {
    return hypotheses[0]?.likely_cause || '';
  });

  // Default pick: #1, unless rolling #1 back did not clear the symptom and the sandbox's next suspect
  // is among the hypotheses. Never overrides a choice the reviewer made.
  const picked = React.useRef(false);
  const suggested =
    verification?.clears === false && hypotheses.some((h) => h.deploy_id === verification.next_suspect)
      ? hypotheses.find((h) => h.deploy_id === verification.next_suspect)
      : undefined;
  React.useEffect(() => {
    if (picked.current || hypotheses.length === 0) return;
    const h = suggested ?? hypotheses[0];
    if (h.deploy_id !== selectedDeployId) {
      setSelectedDeployId(h.deploy_id);
      setCauseText(h.likely_cause || '');
    }
  }, [hypotheses, suggested, selectedDeployId]);

  const handleSelectHypothesis = (depId: string) => {
    picked.current = true;
    setSelectedDeployId(depId);
    const found = hypotheses.find((h) => h.deploy_id === depId);
    if (found?.likely_cause) {
      setCauseText(found.likely_cause);
    }
  };

  const reviewMutation = useReview(tenant, invId);

  const handleReview = async (verdict: 'confirm' | 'reject') => {
    if (!reviewer.trim()) {
      toast.error('Please enter your reviewer identity.');
      return;
    }

    try {
      localStorage.setItem('tracebrain.reviewer', reviewer.trim());
    } catch {
      // ignore
    }

    try {
      const res = await reviewMutation.mutateAsync({
        verdict,
        reviewer: reviewer.trim(),
        deploy_id: selectedDeployId || undefined,
        cause_text: causeText.trim() || undefined,
      });

      // Report only what the curator returned
      const weakened = res.weakened?.length ?? 0;
      if (verdict === 'confirm') {
        toast.success(`Confirmed ${res.deploy_id ?? ''} · lesson saved`, {
          description: [
            res.cause_key && `${res.cause_is_new ? 'New cause' : 'Matched existing cause'} "${res.cause_key.replace(/_/g, ' ')}"`,
            typeof res.confidence === 'number' && `confidence ${(res.confidence * 100).toFixed(0)}%`,
            res.lesson && `lesson ✓${res.lesson.success_count} ✗${res.lesson.fail_count}`,
            res.top_was_right === false && weakened > 0 && `#1 was wrong: ${weakened} lesson${weakened > 1 ? 's' : ''} weakened`,
          ].filter(Boolean).join(' · '),
          duration: 6000,
          icon: React.createElement(Sparkles, { className: 'w-4 h-4 text-[var(--agent-curator)]' }),
        });
      } else {
        toast.warning('Rejected', {
          description: [
            weakened > 0 ? `${weakened} lesson${weakened > 1 ? 's' : ''} weakened` : 'No existing lesson to weaken',
            res.cause && `cause "${res.cause.key}" confidence now ${(res.cause.confidence * 100).toFixed(0)}%`,
          ].filter(Boolean).join(' · '),
        });
      }

      onReviewed?.();
    } catch (e: unknown) {
      const err = e as { detail?: string; message?: string };
      toast.error(err.detail ?? err.message ?? 'Review submission failed');
    }
  };

  // ─── If already CONFIRMED or LEARNED ─────────────────────────────────────────
  const rejected = state === 'REJECTED' || (state === 'LEARNED' && outcome === 'rejected');
  if (state === 'CONFIRMED' || (state === 'LEARNED' && !rejected)) {
    return (
      <div className="border-t border-[var(--status-ok)]/30 bg-[var(--status-ok)]/5 p-3 flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-[var(--status-ok)]">
            <CheckCircle2 className="w-4 h-4" />
            <span>Human Review: Confirmed</span>
          </div>
          <Link
            to={`/t/${tenant}/memory`}
            className="flex items-center gap-1 text-[10px] font-medium text-[var(--accent)] hover:underline"
          >
            <Brain className="w-3 h-3" />
            View in Memory <ArrowRight className="w-2.5 h-2.5" />
          </Link>
        </div>
        <p className="text-[11px] text-[var(--text-secondary)]">
          Cause and lesson saved to memory. Later runs with memory ON recall them for the same symptom and service.
        </p>
      </div>
    );
  }

  // ─── If already REJECTED ────────────────────────────────────────────────────
  if (rejected) {
    return (
      <div className="border-t border-[var(--status-bad)]/30 bg-[var(--status-bad)]/5 p-3 flex flex-col gap-1.5">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-[var(--status-bad)]">
          <XCircle className="w-4 h-4" />
          <span>Human Review: Rejected</span>
        </div>
        <p className="text-[11px] text-[var(--text-secondary)]">
          Rejected by the reviewer. Any lesson pointing at the #1 suspect's service was weakened, so it is recalled less.
        </p>
      </div>
    );
  }

  // ─── Only show active review dock when awaiting review or hypotheses exist ───
  const isAwaiting = state === 'AWAITING_REVIEW';
  if (!isAwaiting && (!hypotheses || hypotheses.length === 0)) {
    return null;
  }

  return (
    <div className="border-t border-[var(--border-strong)] bg-[var(--surface-panel)] p-3 flex flex-col gap-2.5 shadow-[0_-4px_16px_rgba(0,0,0,0.3)]">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <Brain className="w-3.5 h-3.5 text-[var(--agent-curator)]" />
          <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-primary)]">
            Human-in-the-Loop Review
          </span>
        </div>
        {isAwaiting && (
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[var(--status-warn)]/15 text-[var(--status-warn)] border border-[var(--status-warn)]/30 animate-pulse">
            Awaiting Review
          </span>
        )}
      </div>

      {/* Why the default pick is what it is */}
      {verification && hypotheses.length > 0 && verification.clears !== null && verification.clears !== undefined && (
        <p
          className={
            'text-[11px] leading-relaxed px-2 py-1.5 rounded border ' +
            (verification.clears
              ? 'text-[var(--status-ok)] border-[var(--status-ok)]/30 bg-[var(--status-ok)]/5'
              : 'text-[var(--status-warn)] border-[var(--status-warn)]/30 bg-[var(--status-warn)]/5')
          }
        >
          {verification.clears
            ? `Sandbox check: rolling back ${verification.deploy_id} clears the symptom (simulated).`
            : suggested
              ? `Sandbox check: rolling back ${verification.deploy_id} did not clear the symptom, so the next suspect ${suggested.deploy_id} (#${suggested.rank}) is preselected. Change it if you know better.`
              : `Sandbox check: rolling back ${verification.deploy_id} did not clear the symptom. Check before confirming.`}
        </p>
      )}

      {/* Culprit Selector */}
      {hypotheses.length > 0 && (
        <div className="flex flex-col gap-1">
          <label className="text-[10px] text-[var(--text-faint)] uppercase font-mono">
            Selected Culprit Deploy
          </label>
          <select
            value={selectedDeployId}
            onChange={(e) => handleSelectHypothesis(e.target.value)}
            className="w-full text-xs font-mono px-2 py-1.5 rounded bg-[var(--surface-card)] border border-[var(--border-strong)] text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
          >
            {hypotheses.map((h) => (
              <option key={h.deploy_id} value={h.deploy_id}>
                #{h.rank} · {h.deploy_id} {h.service ? `(${h.service})` : ''} · score {h.score.toFixed(2)}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Abstention: there is no culprit to confirm (the curator needs a deploy), so say so instead of
          offering a Confirm that the API would refuse. Reject records that the abstention was wrong. */}
      {hypotheses.length === 0 && (
        <p className="text-[12px] text-[var(--text-secondary)] leading-relaxed">
          The investigator abstained: nothing deployed on this service's dependencies (as of the incident) in
          the look-back window. There is no culprit to confirm, so nothing is written to memory. If you know
          the abstention was wrong, reject it.
        </p>
      )}

      {/* Cause Synthesis Field */}
      {hypotheses.length > 0 && (
      <div className="flex flex-col gap-1">
        <label className="text-[10px] text-[var(--text-faint)] uppercase font-mono">
          Synthesized Root Cause
        </label>
        <textarea
          rows={2}
          value={causeText}
          onChange={(e) => setCauseText(e.target.value)}
          placeholder="Detailed root cause explanation to preserve in institutional memory..."
          className="w-full text-xs px-2 py-1.5 rounded bg-[var(--surface-card)] border border-[var(--border-strong)] text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)] resize-none"
        />
      </div>
      )}

      {/* Reviewer Signature & Submit Buttons */}
      <div className="flex items-center gap-2 pt-1">
        <div className="flex items-center gap-1.5 flex-1 px-2 py-1 rounded bg-[var(--surface-card)] border border-[var(--border-strong)]">
          <User className="w-3 h-3 text-[var(--text-faint)]" />
          <input
            type="text"
            value={reviewer}
            onChange={(e) => setReviewer(e.target.value)}
            placeholder="your name"
            aria-label="Reviewer name"
            className="w-full text-[11px] font-mono bg-transparent text-[var(--text-secondary)] focus:outline-none"
          />
        </div>

        <button
          type="button"
          onClick={() => void handleReview('reject')}
          disabled={reviewMutation.isPending}
          className="px-2.5 py-1.5 rounded text-xs font-medium text-[var(--status-bad)] bg-[var(--status-bad)]/10 border border-[var(--status-bad)]/30 hover:bg-[var(--status-bad)]/20 disabled:opacity-50 transition-colors flex items-center gap-1"
        >
          <XCircle className="w-3.5 h-3.5" />
          {hypotheses.length === 0 ? 'Abstention was wrong' : 'Reject'}
        </button>

        {hypotheses.length > 0 && (
        <button
          type="button"
          onClick={() => void handleReview('confirm')}
          disabled={reviewMutation.isPending}
          className="px-3 py-1.5 rounded text-xs font-semibold text-[var(--text-inverse)] bg-[var(--agent-curator)] hover:opacity-90 disabled:opacity-50 transition-all flex items-center gap-1 shadow-sm"
        >
          {reviewMutation.isPending ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <Sparkles className="w-3.5 h-3.5" />
          )}
          Confirm
        </button>
        )}
      </div>
    </div>
  );
};
