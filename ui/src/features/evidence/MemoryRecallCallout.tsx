import React from 'react';
import { Link, useParams } from 'react-router-dom';
import { Brain, ArrowRight } from 'lucide-react';
import type { Hypothesis } from '@/api/types';
import type { MemoryRecall } from '@/lib/memoryRecall';

interface MemoryRecallCalloutProps {
  recall: MemoryRecall;
  memoryEnabled?: boolean | null;
  top?: Hypothesis;
}

/** Shows which confirmed memory this run used, and where it came from (Track 2: memory reused). */
export const MemoryRecallCallout: React.FC<MemoryRecallCalloutProps> = ({ recall, memoryEnabled, top }) => {
  const { tenant = 'payments' } = useParams<{ tenant: string }>();
  const boost = typeof top?.features?.lesson_match === 'number' ? top.features.lesson_match : 0;
  const used = recall.lessons.length > 0 || recall.similar.length > 0 || boost > 0;

  if (memoryEnabled === false) {
    return (
      <div className="flex items-center gap-2 px-3 py-2 rounded-md border border-[var(--border-subtle)] bg-[var(--surface-card)] text-[12px] text-[var(--text-secondary)]">
        <Brain className="w-4 h-4 text-[var(--text-faint)] flex-shrink-0" />
        Memory OFF for this run: no lessons or past incidents were consulted.
      </div>
    );
  }
  if (!used) {
    if (!recall.consulted) return null;
    return (
      <div className="flex items-center gap-2 px-3 py-2 rounded-md border border-[var(--border-subtle)] bg-[var(--surface-card)] text-[12px] text-[var(--text-secondary)]">
        <Brain className="w-4 h-4 text-[var(--agent-curator)] flex-shrink-0" />
        Memory checked: nothing confirmed yet for this symptom. Confirming this run will teach it.
      </div>
    );
  }

  const incidentLink = (id: string) => (
    <Link
      key={id}
      to={`/t/${tenant}/incidents/${id}`}
      className="font-mono text-[var(--accent)] hover:underline"
    >
      {id}
    </Link>
  );

  return (
    <div className="flex flex-col gap-2 p-3 rounded-md border border-[var(--agent-curator)]/40 bg-[var(--agent-curator)]/10">
      <div className="flex items-center gap-2">
        <Brain className="w-4 h-4 text-[var(--agent-curator)] flex-shrink-0" />
        <span className="text-[13px] font-semibold text-[var(--text-primary)]">Memory used in this run</span>
        <Link
          to={`/t/${tenant}/memory`}
          className="ml-auto flex items-center gap-1 text-[11px] text-[var(--agent-curator)] hover:underline"
        >
          Memory <ArrowRight className="w-3 h-3" />
        </Link>
      </div>

      {recall.lessons.map((l) => (
        <div key={l.id} className="text-[12px] text-[var(--text-primary)] leading-relaxed">
          Lesson: when <span className="font-mono">{recall.symptom ?? 'this symptom'}</span> hits{' '}
          <span className="font-mono">{recall.service ?? 'this service'}</span>, check{' '}
          <span className="font-mono font-semibold text-[var(--agent-curator)]">{l.check_first}</span> first
          <div className="text-[11px] text-[var(--text-secondary)]">
            learned from {l.evidence.length ? l.evidence.map((id, i) => [i > 0 && ', ', incidentLink(id)]) : 'a confirmed review'}
            {' · '}✓{l.success_count} ✗{l.fail_count}
            {typeof l.weight === 'number' && ` · weight ${l.weight.toFixed(2)}`}
            {l.cause && ` · cause: ${l.cause}`}
          </div>
        </div>
      ))}

      {recall.similar.map((s) => (
        <div key={s.incident} className="text-[12px] text-[var(--text-primary)] leading-relaxed">
          Precedent: {incidentLink(s.incident)} on <span className="font-mono">{s.service}</span>, confirmed cause{' '}
          <span className="italic">{s.cause}</span>
          {s.culprit_service && (
            <>
              {' '}(culprit on <span className="font-mono">{s.culprit_service}</span>)
            </>
          )}
        </div>
      ))}

      {boost > 0 && top && (
        <div className="text-[11px] text-[var(--agent-curator)] border-t border-[var(--agent-curator)]/20 pt-1.5">
          Raised #{top.rank} <span className="font-mono">{top.deploy_id}</span> through its lesson_match feature (
          {boost.toFixed(2)}).
        </div>
      )}
    </div>
  );
};
