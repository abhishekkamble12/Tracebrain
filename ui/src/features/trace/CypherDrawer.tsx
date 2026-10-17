import React from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { Database, X, Lock, PenLine } from 'lucide-react';
import { CYPHER, TOOL_QUERIES, WRITE_TOOLS } from '@/lib/cypher.generated';

/** What the drawer needs to fill in query parameters the way the backend does. */
export interface CypherContext {
  /** Incident time (epoch seconds): every as-of query is evaluated here. */
  t?: number;
  /** Alerted service and symptom of the incident (set by the orchestrator, not the LLM). */
  service?: string;
  symptom?: string;
}

interface CypherDrawerProps {
  tool: string;
  agent: string;
  args: Record<string, unknown>;
  edgeCount: number;
  context: CypherContext;
  /** Called when the drawer opens (the trace pins this step's edges so the graph shows them). */
  onOpen?: () => void;
}

const KEYWORDS =
  /\b(OPTIONAL MATCH|MATCH|WHERE|RETURN|WITH|ORDER BY|LIMIT|UNWIND|MERGE|CREATE|SET|CALL|YIELD|AS|AND|OR|NOT|IN|DESC|ON CREATE SET|FOREACH|CASE|WHEN|THEN|ELSE|END|all|collect|relationships|nodes|length|coalesce|min|count|id|type)\b/g;

/** Light syntax colouring without innerHTML: keywords, $params, and everything else. */
function highlight(query: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  const pattern = new RegExp(`${KEYWORDS.source}|(\\$[a-z_]+)`, 'g');
  let last = 0;
  for (const m of query.matchAll(pattern)) {
    if (m.index! > last) out.push(query.slice(last, m.index));
    const isParam = m[0].startsWith('$');
    out.push(
      <span key={m.index} className={isParam ? 'text-[var(--status-suspect)]' : 'text-[var(--accent)] font-semibold'}>
        {m[0]}
      </span>
    );
    last = m.index! + m[0].length;
  }
  out.push(query.slice(last));
  return out;
}

/** Parameter values as tracebrain/tools/impl.py passes them (tenant and t come from MCP metadata). */
function paramValues(args: Record<string, unknown>, ctx: CypherContext): Record<string, unknown> {
  const window = typeof args.window_hours === 'number' ? args.window_hours * 3600 : 24 * 3600;
  return {
    svc: args.service,
    t: ctx.t,
    window,
    services: args.services,
    a: args.from_service,
    b: args.to_service,
    symptom: ctx.symptom,
    service: args.service ?? ctx.service,
    incident_id: args.incident_id,
    limit: args.limit ?? 5,
    kind: args.kind,
  };
}

function paramsFor(query: string, values: Record<string, unknown>): [string, string][] {
  const names = [...new Set([...query.matchAll(/\$([a-z_]+)/g)].map((m) => m[1]))];
  return names.map((n) => {
    const v = values[n];
    if (v === undefined || v === null) return [n, 'set by Tracebrain'];
    if (n === 't' && typeof v === 'number') return [n, `${v}  (${new Date(v * 1000).toISOString().replace('.000Z', 'Z')})`];
    return [n, typeof v === 'string' ? v : JSON.stringify(v)];
  });
}

/** "Cypher" chip on a trace step: opens a drawer with the exact queries that MCP tool ran. */
export const CypherDrawer: React.FC<CypherDrawerProps> = ({ tool, agent, args, edgeCount, context, onOpen }) => {
  const queries = TOOL_QUERIES[tool];
  if (!queries) return null;
  const isWrite = WRITE_TOOLS.includes(tool);
  const values = paramValues(args, context);

  return (
    <Dialog.Root onOpenChange={(open) => open && onOpen?.()}>
      <Dialog.Trigger asChild>
        <button
          type="button"
          className="flex items-center gap-1 px-1.5 py-0.5 rounded border border-[var(--border-strong)] text-[10px] font-mono text-[var(--text-secondary)] hover:text-[var(--accent)] hover:border-[var(--accent)]/50 transition-colors"
          aria-label={`Show the Cypher run by ${tool}`}
        >
          <Database className="w-3 h-3" />
          Cypher
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/20" />
        <Dialog.Content className="fixed right-0 top-0 bottom-0 z-50 w-[min(620px,100vw)] bg-[var(--surface-panel)] border-l border-[var(--border-strong)] shadow-2xl flex flex-col focus:outline-none">
          <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-[var(--border-subtle)]">
            <div className="flex flex-col gap-1 min-w-0">
              <Dialog.Title className="font-mono text-[15px] font-semibold text-[var(--text-primary)]">
                {tool}
              </Dialog.Title>
              <Dialog.Description className="text-[12px] text-[var(--text-secondary)] leading-relaxed">
                MCP tool called by the <span className="font-medium">{agent}</span> agent. These are the exact Cypher
                statements it runs on this tenant's FalkorDB graph
                {edgeCount > 0 ? `; the call returned ${edgeCount} edge id${edgeCount === 1 ? '' : 's'} as evidence.` : '.'}
              </Dialog.Description>
              <span className="mt-1 inline-flex w-fit items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono border border-[var(--border-strong)] text-[var(--text-secondary)]">
                {isWrite ? <PenLine className="w-3 h-3" /> : <Lock className="w-3 h-3" />}
                {isWrite ? 'write, scoped to this investigation' : 'read-only (GRAPH.RO_QUERY)'}
              </span>
            </div>
            <Dialog.Close asChild>
              <button type="button" aria-label="Close" className="p-1 rounded text-[var(--text-faint)] hover:text-[var(--text-primary)]">
                <X className="w-4 h-4" />
              </button>
            </Dialog.Close>
          </div>

          <div className="flex-1 overflow-y-auto px-5 py-4 flex flex-col gap-5 [&>*]:shrink-0">
            {queries.map(({ name, role }) => {
              const query = CYPHER[name] ?? '';
              return (
                <section key={name} className="flex flex-col gap-2">
                  <div className="flex items-baseline justify-between gap-2">
                    <h3 className="font-mono text-[12px] font-semibold text-[var(--text-primary)]">{name}</h3>
                    <span className="text-[11px] text-[var(--text-secondary)] text-right">{role}</span>
                  </div>
                  <pre className="text-[12px] leading-relaxed font-mono text-[var(--text-secondary)] bg-[var(--bg-deep)] border border-[var(--border-subtle)] rounded-md p-3 overflow-x-auto whitespace-pre">
                    {highlight(query)}
                  </pre>
                  {paramsFor(query, values).length > 0 && (
                    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[11px] font-mono">
                      {paramsFor(query, values).map(([k, v]) => (
                        <React.Fragment key={k}>
                          <dt className="text-[var(--status-suspect)]">${k}</dt>
                          <dd className="text-[var(--text-secondary)] truncate">{v}</dd>
                        </React.Fragment>
                      ))}
                    </dl>
                  )}
                </section>
              );
            })}
          </div>
          <p className="px-5 py-3 border-t border-[var(--border-subtle)] text-[11px] text-[var(--text-faint)]">
            Source: <span className="font-mono">tracebrain/queries.py</span>. Tenant and incident time are sent as MCP
            request metadata, so the model never sees or chooses them.
          </p>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
};
