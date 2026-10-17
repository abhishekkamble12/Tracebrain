import React from 'react';
import { useParams, Link } from 'react-router-dom';
import { useMemory, useRetractCause } from '@/api/hooks';
import type { Lesson, Cause } from '@/api/types';
import {
  Brain,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Sparkles,
  Link2,
  Trash2,
  ShieldAlert,
  Loader2,
  ArrowRight,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { toast } from 'sonner';

// ─── RetractModal ────────────────────────────────────────────────────────────

interface RetractModalProps {
  cause: Cause | null;
  tenant: string;
  onClose: () => void;
  onSuccess: () => void;
}

export const RetractModal: React.FC<RetractModalProps> = ({
  cause,
  tenant,
  onClose,
  onSuccess,
}) => {
  const retractMutation = useRetractCause(tenant);

  if (!cause) return null;

  const handleRetract = async () => {
    try {
      await retractMutation.mutateAsync(cause.key);
      toast.success(`Cause "${cause.name}" has been retracted.`);
      onSuccess();
      onClose();
    } catch (e: unknown) {
      const err = e as { detail?: string; message?: string };
      toast.error(err.detail ?? err.message ?? 'Failed to retract cause');
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-in fade-in duration-150">
      <div className="w-full max-w-md rounded-xl border border-[var(--status-bad)]/40 bg-[var(--surface-panel)] p-5 shadow-2xl flex flex-col gap-4">
        {/* Header */}
        <div className="flex items-start gap-3">
          <div className="p-2 rounded-lg bg-[var(--status-bad)]/15 text-[var(--status-bad)] flex-shrink-0">
            <ShieldAlert className="w-5 h-5" />
          </div>
          <div className="flex-1">
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">
              Retract Institutional Cause
            </h3>
            <p className="text-xs text-[var(--text-faint)] mt-0.5">
              Disputes the root cause without breaking graph referential integrity.
            </p>
          </div>
        </div>

        {/* Cause details */}
        <div className="p-3 rounded-lg bg-[var(--surface-card)] border border-[var(--border-subtle)] flex flex-col gap-1.5 text-xs">
          <div className="flex items-center justify-between">
            <span className="text-[var(--text-faint)]">Cause:</span>
            <span className="font-semibold text-[var(--text-primary)]">{cause.name}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[var(--text-faint)]">Key:</span>
            <span className="font-mono text-[var(--text-secondary)]">{cause.key}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[var(--text-faint)]">Current Confidence:</span>
            <span className="font-mono text-[var(--accent)] font-medium">
              {(cause.confidence * 100).toFixed(0)}%
            </span>
          </div>
        </div>

        <p className="text-[11px] text-[var(--text-secondary)] leading-relaxed">
          Retraction marks this cause as inactive in FalkorDB. The memory engine will no longer boost hypotheses matching this pattern in future incidents.
        </p>

        {/* Modal actions */}
        <div className="flex items-center justify-end gap-2 pt-2 border-t border-[var(--border-subtle)]">
          <button
            type="button"
            onClick={onClose}
            disabled={retractMutation.isPending}
            className="px-3 py-1.5 rounded text-xs font-medium text-[var(--text-secondary)] hover:bg-[var(--surface-hover)] transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void handleRetract()}
            disabled={retractMutation.isPending}
            className="px-3.5 py-1.5 rounded text-xs font-semibold text-[var(--text-inverse)] bg-[var(--status-bad)] hover:opacity-90 disabled:opacity-50 transition-all flex items-center gap-1.5 shadow-sm"
          >
            {retractMutation.isPending ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Trash2 className="w-3.5 h-3.5" />
            )}
            Confirm Retraction
          </button>
        </div>
      </div>
    </div>
  );
};

// ─── LessonCard ──────────────────────────────────────────────────────────────

interface LessonCardProps {
  lesson: Lesson;
  tenant: string;
}

export const LessonCard: React.FC<LessonCardProps> = ({ lesson, tenant }) => {
  // Confidence formula: (success - fail) / (success + fail + 1)
  const score = (lesson.success_count - lesson.fail_count) / (lesson.success_count + lesson.fail_count + 1);
  const normalizedScore = Math.max(0, Math.min(1, (score + 1) / 2)); // map -1..1 to 0..1 for bar
  const pct = Math.round(normalizedScore * 100);

  return (
    <div
      className={cn(
        'p-3.5 rounded-lg border transition-all flex flex-col gap-2.5',
        lesson.retracted
          ? 'border-[var(--border-subtle)] bg-[var(--surface-card)]/50 opacity-60'
          : 'border-[var(--border-strong)] bg-[var(--surface-card)] hover:border-[var(--border-strong)]/80 shadow-sm'
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs px-2 py-0.5 rounded bg-[var(--surface-hover)] text-[var(--text-primary)] border border-[var(--border-subtle)]">
            {lesson.symptom} @ {lesson.service}
          </span>
          {lesson.retracted && (
            <span className="text-[9px] font-mono uppercase px-1.5 py-0.5 rounded bg-[var(--status-bad)]/15 text-[var(--status-bad)] border border-[var(--status-bad)]/30">
              Retracted
            </span>
          )}
        </div>

        {/* Validation counts */}
        <div className="flex items-center gap-2 text-xs font-mono">
          <span className="flex items-center gap-1 text-[var(--status-ok)]">
            <CheckCircle2 className="w-3 h-3" />
            {lesson.success_count}
          </span>
          <span className="flex items-center gap-1 text-[var(--status-bad)]">
            <XCircle className="w-3 h-3" />
            {lesson.fail_count}
          </span>
        </div>
      </div>

      {/* Recommendation rule */}
      <div className="p-2.5 rounded bg-[var(--surface-panel)] border border-[var(--border-subtle)] flex items-center justify-between">
        <div className="text-xs text-[var(--text-secondary)]">
          Rule: When <span className="font-semibold text-[var(--text-primary)]">{lesson.symptom}</span> occurs on{' '}
          <span className="font-semibold text-[var(--accent)]">{lesson.service}</span>, inspect{' '}
          <strong className="text-[var(--status-suspect)] font-mono">{lesson.check_first}</strong> first.
        </div>
      </div>

      {/* Cause linkage & Confidence Weight */}
      <div className="flex flex-col gap-1.5 pt-1">
        <div className="flex items-center justify-between text-[11px]">
          <span className="text-[var(--text-faint)] flex items-center gap-1">
            <Sparkles className="w-3 h-3 text-[var(--agent-curator)]" />
            Procedural Weight
          </span>
          <span className="font-mono text-[10px] text-[var(--text-faint)]">
            score: {score.toFixed(2)} ({pct}%)
          </span>
        </div>
        <div className="w-full h-1.5 rounded-full bg-[var(--surface-hover)] overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{
              width: `${pct}%`,
              background: lesson.retracted ? 'var(--text-faint)' : 'var(--agent-curator)',
            }}
          />
        </div>
      </div>

      {/* Provenance & Evidence */}
      <div className="flex items-center justify-between pt-1 border-t border-[var(--border-subtle)] text-[11px] text-[var(--text-faint)]">
        <span className="truncate max-w-[240px]">
          Root Cause: <strong className="text-[var(--text-secondary)] font-normal">{lesson.cause}</strong>
        </span>

        {lesson.evidence && lesson.evidence.length > 0 && (
          <div className="flex items-center gap-1.5 flex-wrap">
            <Link2 className="w-3 h-3 text-[var(--accent)] flex-shrink-0" />
            {lesson.evidence.map((ev, i) => {
              const isInc = ev.startsWith('inc:');
              if (isInc) {
                return (
                  <Link
                    key={i}
                    to={`/t/${tenant}/incidents/${ev}`}
                    className="font-mono text-[10px] text-[var(--accent)] hover:underline bg-[var(--accent)]/10 px-1 rounded"
                  >
                    {ev}
                  </Link>
                );
              }
              return (
                <span key={i} className="font-mono text-[10px] text-[var(--text-faint)]">
                  {ev}
                </span>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};

// ─── MemoryPage ──────────────────────────────────────────────────────────────

export const MemoryPage: React.FC = () => {
  const { tenant = 'payments' } = useParams<{ tenant: string }>();
  const { data: mem, isLoading, isError, refetch } = useMemory(tenant);
  const [retractTarget, setRetractTarget] = React.useState<Cause | null>(null);

  const activeLessons = mem?.lessons?.filter((l) => !l.retracted) ?? [];
  const retractedLessons = mem?.lessons?.filter((l) => l.retracted) ?? [];

  return (
    <div className="flex-1 flex flex-col p-6 overflow-y-auto max-w-6xl mx-auto w-full gap-6 [&>*]:shrink-0">
      {/* Header */}
      <header className="flex flex-col gap-1 border-b border-[var(--border-subtle)] pb-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5 text-[var(--accent)]">
            <div className="p-1.5 rounded-md bg-[var(--accent)]/15 border border-[var(--accent)]/30">
              <Brain className="w-5 h-5 text-[var(--accent)]" />
            </div>
            <h1 className="text-xl font-bold tracking-tight text-[var(--text-primary)]">
              Institutional Memory Hub
            </h1>
            <span className="font-mono text-xs px-2 py-0.5 rounded bg-[var(--surface-card)] text-[var(--accent)] border border-[var(--accent)]/20">
              tenant: {tenant}
            </span>
          </div>

          <Link
            to={`/t/${tenant}`}
            className="flex items-center gap-1 text-xs text-[var(--text-faint)] hover:text-[var(--text-primary)] transition-colors"
          >
            Incident Console <ArrowRight className="w-3 h-3" />
          </Link>
        </div>
        <p className="text-xs text-[var(--text-secondary)] leading-relaxed mt-1">
          Memory is written only by human review. Every entry links to proven incident evidence in FalkorDB and accelerates root-cause localization for repeat failures.
        </p>
      </header>

      {isLoading ? (
        <div className="p-12 text-center text-xs text-[var(--text-faint)] flex flex-col items-center gap-2">
          <Loader2 className="w-6 h-6 animate-spin text-[var(--accent)]" />
          <span>Loading knowledge graph from FalkorDB...</span>
        </div>
      ) : isError ? (
        <div className="p-4 rounded-lg border border-[var(--status-bad)]/30 bg-[var(--status-bad)]/10 text-xs text-[var(--status-bad)] flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4" />
            <span>Failed to load institutional memory graph for tenant {tenant}.</span>
          </div>
          <button
            type="button"
            onClick={() => void refetch()}
            className="px-2.5 py-1 rounded bg-[var(--status-bad)]/20 hover:bg-[var(--status-bad)]/30 text-xs font-medium transition-colors"
          >
            Retry
          </button>
        </div>
      ) : (
        <div className="flex flex-col gap-8">
          {/* ── Learned Lessons Section ─────────────────────────────────── */}
          <section className="flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-[var(--agent-curator)]" />
                <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-primary)]">
                  Learned Procedural Lessons ({mem?.lessons?.length ?? 0})
                </h2>
              </div>
              <span className="text-[11px] text-[var(--text-faint)]">
                Formula: (success - fail) / (success + fail + 1)
              </span>
            </div>

            {(!mem?.lessons || mem.lessons.length === 0) ? (
              <div className="p-8 rounded-lg border border-dashed border-[var(--border-strong)] bg-[var(--surface-panel)] text-center flex flex-col items-center gap-2">
                <Brain className="w-8 h-8 text-[var(--text-faint)] opacity-30" />
                <p className="text-xs text-[var(--text-secondary)] font-medium">Nothing learned yet</p>
                <p className="text-[11px] text-[var(--text-faint)] max-w-sm">
                  Investigate an incident and confirm the root cause in the Human Review dock to write your first institutional lesson.
                </p>
              </div>
            ) : (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                {activeLessons.map((l) => (
                  <LessonCard key={l.id} lesson={l} tenant={tenant} />
                ))}
                {retractedLessons.map((l) => (
                  <LessonCard key={l.id} lesson={l} tenant={tenant} />
                ))}
              </div>
            )}
          </section>

          {/* ── Causes Entities Table ───────────────────────────────────── */}
          <section className="flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-primary)]">
                Resolved Semantic Causes ({mem?.causes?.length ?? 0})
              </h2>
              <span className="text-[11px] text-[var(--text-faint)]">
                Confidence adjusts automatically on confirm/reject reviews
              </span>
            </div>

            {(!mem?.causes || mem.causes.length === 0) ? (
              <div className="p-6 rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-panel)] text-xs text-[var(--text-faint)] text-center">
                No semantic causes registered yet.
              </div>
            ) : (
              <div className="rounded-lg border border-[var(--border-strong)] overflow-hidden bg-[var(--surface-card)]">
                <table className="w-full text-left text-xs border-collapse">
                  <thead>
                    <tr className="bg-[var(--surface-panel)] text-[var(--text-faint)] border-b border-[var(--border-subtle)]">
                      <th className="p-3 font-medium">Cause Entity</th>
                      <th className="p-3 font-medium">Aliases</th>
                      <th className="p-3 font-medium">Confidence</th>
                      <th className="p-3 font-medium">Confirmations</th>
                      <th className="p-3 font-medium">Status</th>
                      <th className="p-3 font-medium text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--border-subtle)]">
                    {mem.causes.map((c) => {
                      const confPct = Math.round(c.confidence * 100);
                      return (
                        <tr key={c.key} className="hover:bg-[var(--surface-hover)]/40 transition-colors">
                          {/* Name & Key */}
                          <td className="p-3 font-medium text-[var(--text-primary)]">
                            <div className="flex flex-col">
                              <span>{c.name}</span>
                              <span className="font-mono text-[10px] text-[var(--text-faint)]">{c.key}</span>
                            </div>
                          </td>

                          {/* Aliases */}
                          <td className="p-3 font-mono text-[11px] text-[var(--text-secondary)]">
                            {c.aliases && c.aliases.length > 0 ? (
                              <div className="flex flex-wrap gap-1">
                                {c.aliases.map((alias) => (
                                  <span
                                    key={alias}
                                    className="px-1.5 py-0.5 rounded bg-[var(--surface-hover)] border border-[var(--border-subtle)] text-[10px]"
                                  >
                                    {alias}
                                  </span>
                                ))}
                              </div>
                            ) : (
                              <span className="text-[var(--text-faint)]">—</span>
                            )}
                          </td>

                          {/* Confidence */}
                          <td className="p-3">
                            <div className="flex items-center gap-2">
                              <div className="w-16 h-1.5 rounded-full bg-[var(--surface-hover)] overflow-hidden">
                                <div
                                  className="h-full rounded-full transition-all duration-500"
                                  style={{
                                    width: `${confPct}%`,
                                    background: c.retracted ? 'var(--text-faint)' : 'var(--accent)',
                                  }}
                                />
                              </div>
                              <span className="font-mono text-[11px] text-[var(--text-secondary)]">
                                {confPct}%
                              </span>
                            </div>
                          </td>

                          {/* Confirmations / Rejections */}
                          <td className="p-3 font-mono text-[11px] text-[var(--text-secondary)]">
                            <span className="text-[var(--status-ok)] font-medium">+{c.confirmations}</span>
                            {c.rejections > 0 && (
                              <span className="text-[var(--status-bad)] ml-1.5 font-medium">
                                -{c.rejections}
                              </span>
                            )}
                          </td>

                          {/* Status */}
                          <td className="p-3">
                            {c.retracted ? (
                              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[var(--status-bad)]/15 text-[var(--status-bad)] border border-[var(--status-bad)]/30">
                                Retracted
                              </span>
                            ) : (
                              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[var(--status-ok)]/15 text-[var(--status-ok)] border border-[var(--status-ok)]/30">
                                Active
                              </span>
                            )}
                          </td>

                          {/* Actions */}
                          <td className="p-3 text-right">
                            {!c.retracted ? (
                              <button
                                type="button"
                                onClick={() => setRetractTarget(c)}
                                className="px-2.5 py-1 rounded text-[11px] font-medium text-[var(--status-bad)] bg-[var(--status-bad)]/10 border border-[var(--status-bad)]/25 hover:bg-[var(--status-bad)]/20 transition-colors inline-flex items-center gap-1"
                              >
                                <Trash2 className="w-3 h-3" />
                                Retract
                              </button>
                            ) : (
                              <span className="text-[11px] text-[var(--text-faint)] italic">
                                Disputed
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      )}

      {/* Retract Confirmation Modal */}
      {retractTarget && (
        <RetractModal
          cause={retractTarget}
          tenant={tenant}
          onClose={() => setRetractTarget(null)}
          onSuccess={() => void refetch()}
        />
      )}
    </div>
  );
};
