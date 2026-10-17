import React from 'react';
import { BarChart3, AlertTriangle, Loader2, FileQuestion } from 'lucide-react';
import { useResults } from '@/api/hooks';

// The eval harness owns the schema of eval/results.json, so this page renders whatever it wrote,
// section by section, without inventing labels, targets or comparisons. No numbers exist here
// that the eval didn't produce.

type Json = null | boolean | number | string | Json[] | { [k: string]: Json };

const META_KEYS = ['model', 'models', 'provider', 'run_at', 'date', 'generated_at', 'split', 'tenant', 'commit'];

const isRecord = (v: Json): v is { [k: string]: Json } => typeof v === 'object' && v !== null && !Array.isArray(v);
const isScalar = (v: Json) => v === null || ['string', 'number', 'boolean'].includes(typeof v);

function humanize(key: string): string {
  return key.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());
}

function formatValue(v: Json): string {
  if (v === null) return '—';
  if (typeof v === 'boolean') return v ? 'pass' : 'fail';
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : v.toFixed(3).replace(/0+$/, '').replace(/\.$/, '');
  if (typeof v === 'string') return v;
  return JSON.stringify(v);
}

const Cell: React.FC<{ value: Json }> = ({ value }) => (
  <td
    className={
      'px-3 py-2 font-mono text-[11px] whitespace-nowrap ' +
      (value === true ? 'text-[var(--status-ok)]' : value === false ? 'text-[var(--status-bad)]' : 'text-[var(--text-primary)]')
    }
  >
    {value === true ? '✓ ' : value === false ? '✗ ' : ''}
    {formatValue(value)}
  </td>
);

/** Rows of objects → table; object of objects → table keyed by row name; flat object → key/value grid. */
const Section: React.FC<{ name: string; value: Json }> = ({ name, value }) => {
  let body: React.ReactNode;

  const rows: { label?: string; row: { [k: string]: Json } }[] | null = Array.isArray(value) && value.every(isRecord)
    ? value.map((row) => ({ row: row as { [k: string]: Json } }))
    : isRecord(value) && Object.values(value).length > 0 && Object.values(value).every(isRecord)
      ? Object.entries(value).map(([label, row]) => ({ label, row: row as { [k: string]: Json } }))
      : null;

  if (rows) {
    const cols = [...new Set(rows.flatMap((r) => Object.keys(r.row)))];
    const labelled = rows.some((r) => r.label);
    body = (
      <div className="overflow-x-auto rounded-lg border border-[var(--border-strong)]">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="bg-[var(--surface-panel)] border-b border-[var(--border-subtle)]">
              {labelled && <th className="px-3 py-2 text-[11px] font-medium text-[var(--text-secondary)]" />}
              {cols.map((c) => (
                <th key={c} scope="col" className="px-3 py-2 text-[11px] font-medium text-[var(--text-secondary)] whitespace-nowrap">
                  {humanize(c)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--border-subtle)] bg-[var(--surface-card)]">
            {rows.map((r, i) => (
              <tr key={r.label ?? i}>
                {labelled && (
                  <th scope="row" className="px-3 py-2 text-[11px] font-medium text-[var(--text-primary)] whitespace-nowrap">
                    {r.label}
                  </th>
                )}
                {cols.map((c) => (
                  <Cell key={c} value={c in r.row ? r.row[c] : null} />
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  } else if (isRecord(value)) {
    body = (
      <dl className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {Object.entries(value).map(([k, v]) => (
          <div key={k} className="p-3 rounded-lg border border-[var(--border-strong)] bg-[var(--surface-card)]">
            <dt className="text-[11px] text-[var(--text-secondary)]">{humanize(k)}</dt>
            <dd className="mt-1 font-mono text-lg text-[var(--text-primary)] break-words">
              {isScalar(v) ? formatValue(v) : <pre className="text-[11px] whitespace-pre-wrap">{JSON.stringify(v, null, 2)}</pre>}
            </dd>
          </div>
        ))}
      </dl>
    );
  } else if (Array.isArray(value)) {
    body = <p className="font-mono text-xs text-[var(--text-primary)]">{value.map(formatValue).join(', ')}</p>;
  } else {
    body = <p className="font-mono text-lg text-[var(--text-primary)]">{formatValue(value)}</p>;
  }

  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-primary)]">{humanize(name)}</h2>
      {body}
    </section>
  );
};

export const ResultsPage: React.FC = () => {
  const { data, isLoading, isError, error, refetch } = useResults();

  const results = (data ?? null) as { [k: string]: Json } | null;
  const meta = results ? META_KEYS.filter((k) => k in results).map((k) => [k, results[k]] as const) : [];
  const sections = results ? Object.entries(results).filter(([k]) => !META_KEYS.includes(k)) : [];

  return (
    <div className="flex-1 flex flex-col p-6 overflow-y-auto max-w-6xl mx-auto w-full gap-6 [&>*]:shrink-0">
      <header className="flex flex-col gap-1 border-b border-[var(--border-subtle)] pb-4">
        <div className="flex items-center gap-2.5">
          <BarChart3 className="w-5 h-5 text-[var(--accent)]" />
          <h1 className="text-xl font-semibold tracking-tight text-[var(--text-primary)]">Evaluation results</h1>
        </div>
        <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
          Shown exactly as written to <code className="font-mono">eval/results.json</code> by the evaluation harness.
        </p>
        {meta.length > 0 && (
          <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-[11px] text-[var(--text-secondary)]">
            {meta.map(([k, v]) => (
              <span key={k}>
                {humanize(k)}: <span className="font-mono text-[var(--text-primary)]">{formatValue(v)}</span>
              </span>
            ))}
          </div>
        )}
      </header>

      {isLoading ? (
        <div className="p-12 flex items-center justify-center gap-2 text-xs text-[var(--text-secondary)]">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading results…
        </div>
      ) : isError ? (
        <div className="p-4 rounded-lg border border-[var(--status-bad)]/30 bg-[var(--status-bad)]/10 text-xs flex items-center justify-between gap-3">
          <span className="flex items-center gap-2 text-[var(--text-primary)]">
            <AlertTriangle className="w-4 h-4 text-[var(--status-bad)]" />
            Couldn't load results: {error instanceof Error ? error.message : 'unknown error'}
          </span>
          <button type="button" onClick={() => void refetch()} className="text-[var(--accent)] hover:underline">
            Retry
          </button>
        </div>
      ) : !results || sections.length === 0 ? (
        <div className="p-10 rounded-xl border border-dashed border-[var(--border-strong)] bg-[var(--surface-panel)] flex flex-col items-center text-center gap-3">
          <FileQuestion className="w-8 h-8 text-[var(--text-faint)]" />
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">No evaluation results yet</h2>
          <p className="text-xs text-[var(--text-secondary)] max-w-md leading-relaxed">
            This page shows real numbers only. Once the evaluation harness writes{' '}
            <code className="font-mono">eval/results.json</code>, its baselines, memory ON/OFF comparison and
            failure-suite results appear here.
          </p>
        </div>
      ) : (
        sections.map(([k, v]) => <Section key={k} name={k} value={v} />)
      )}
    </div>
  );
};
