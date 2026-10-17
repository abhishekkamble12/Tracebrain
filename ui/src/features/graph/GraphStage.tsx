import React, { useEffect, useMemo } from 'react';
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
  useReactFlow,
  type Node,
  type Edge,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { AlertTriangle, Loader2 } from 'lucide-react';
import { ServiceNode, type ServiceNodeData } from './ServiceNode';
import { DeployNode, type DeployNodeData } from './DeployNode';
import { getServicePosition, getDeployPosition, MAX_DEPLOYS_PER_SERVICE, SERVICE_POSITIONS } from './layout';
import type { RunView } from '@/stream/reducer';
import type {
  GraphEdge,
  GraphNodeDeploy,
  GraphNodeService,
  Hypothesis,
  IncidentRow,
  InvestigationFull,
} from '@/api/types';
import { useSelection } from '@/state/SelectionContext';
import { useGraph } from '@/api/hooks';

const NODE_TYPES = { service: ServiceNode, deploy: DeployNode };

// SVG marker colours are presentation attributes, which can't resolve CSS variables.
const COLOR = {
  edge: '#3A4560',
  cited: '#FB923C',
  unverified: '#F43F5E',
  hover: '#7C8CFF',
};

interface GraphStageProps {
  tenant: string;
  incident?: IncidentRow;
  inv?: InvestigationFull | null;
  runView: RunView;
}

/** Blast radius (service → hops) from the latest blast_radius step stored on the investigation. */
function blastFromSteps(inv?: InvestigationFull | null): Map<string, number> {
  const out = new Map<string, number>();
  const step = [...(inv?.steps ?? [])].reverse().find((s) => s.tool === 'blast_radius' && !s.error);
  const affected = (step?.result as { affected?: { service: string; hops: number }[] } | undefined)?.affected;
  for (const a of affected ?? []) out.set(a.service, a.hops);
  return out;
}

export const GraphStage: React.FC<GraphStageProps> = ({ tenant, incident, inv, runView }) => {
  const { pinnedEdgeIds, hoveredClaimEdgeIds, focusedHypothesisRank, activeTopoMode } = useSelection();

  // As-of graph at incident time (current topology when no incident is selected). In "Now" mode the
  // dependency edges come from the current topology, but deploys stay as-of so suspects remain visible.
  const asOf = useGraph(tenant, incident?.ts);
  const showNow = activeTopoMode === 'now' && Boolean(incident);
  const now = useGraph(tenant, null, showNow);

  const hypotheses: Hypothesis[] = useMemo(
    () => runView.hypotheses?.hypotheses ?? inv?.hypotheses ?? [],
    [runView.hypotheses, inv?.hypotheses]
  );

  const { nodes, edges } = useMemo(() => {
    if (!asOf.data) return { nodes: [] as Node[], edges: [] as Edge[] };

    const services = asOf.data.nodes.filter((n): n is GraphNodeService => n.type === 'service');
    const deploys = asOf.data.nodes.filter((n): n is GraphNodeDeploy => n.type === 'deploy');
    const deployEdges = asOf.data.edges.filter((e) => e.type === 'DEPLOYED_TO');
    const depEdges: GraphEdge[] = (showNow && now.data ? now.data.edges : asOf.data.edges)
      .filter((e) => e.type === 'DEPENDS_ON');

    // Ranked hypotheses and their sandbox verification
    const rankByDeploy = new Map(hypotheses.map((h) => [h.deploy_id, h.rank]));
    const clearsByDeploy = new Map<string, boolean | null>();
    for (const h of hypotheses) {
      const v = h.verifications?.[0];
      if (v) clearsByDeploy.set(h.deploy_id, v.clears);
    }
    if (runView.verification) clearsByDeploy.set(runView.verification.deploy_id, runView.verification.clears);

    // Cited edges of the focused hypothesis (#1 by default), split by verdict
    const focused = hypotheses.find((h) => h.rank === (focusedHypothesisRank ?? 1));
    const citedOk = new Set<number>();
    const citedBad = new Set<number>();
    for (const c of focused?.claims ?? []) {
      for (const id of c.edge_ids ?? []) (c.verified ? citedOk : citedBad).add(id);
    }

    // Explicit highlight (hovered claim, else pinned claim) dims everything off its path
    const highlight = new Set(hoveredClaimEdgeIds.length ? hoveredClaimEdgeIds : pinnedEdgeIds);
    const spotlight = highlight.size > 0 ? highlight : focusedHypothesisRank != null ? new Set([...citedOk, ...citedBad]) : null;
    const onPath = new Set<string>();
    if (spotlight) {
      for (const e of [...depEdges, ...deployEdges]) {
        if (spotlight.has(e.id)) {
          onPath.add(e.source);
          onPath.add(e.target);
        }
      }
    }
    const dim = (id: string) => spotlight != null && onPath.size > 0 && !onPath.has(id);

    const blast = blastFromSteps(inv);
    const serviceNames = new Set(services.map((s) => s.name));
    const touched = new Set([...runView.touched].filter((s) => serviceNames.has(s)));

    const suspectsPerService = new Map<string, number>();
    for (const d of deploys) {
      if (rankByDeploy.has(d.id)) suspectsPerService.set(d.service, (suspectsPerService.get(d.service) ?? 0) + 1);
    }

    const nodes: Node[] = [];
    let fallback = 0;
    const positions = new Map<string, { x: number; y: number }>();
    for (const s of services) {
      const pos = getServicePosition(s.name, s.name in SERVICE_POSITIONS ? 0 : fallback++);
      positions.set(s.name, pos);
      const data: ServiceNodeData = {
        name: s.name,
        team: s.team,
        alerted: s.name === incident?.service,
        blastHops: blast.get(s.name) ?? null,
        suspects: suspectsPerService.get(s.name) ?? 0,
        touched: touched.has(s.name),
        dimmed: dim(s.name),
      };
      nodes.push({ id: s.name, type: 'service', position: pos, data: data as unknown as Record<string, unknown> });
    }

    // Deploys: ranked first, then most recent; at most MAX_DEPLOYS_PER_SERVICE per service
    const byService = new Map<string, GraphNodeDeploy[]>();
    for (const d of deploys) byService.set(d.service, [...(byService.get(d.service) ?? []), d]);
    const shownDeploys = new Set<string>();
    for (const [svc, list] of byService) {
      const svcPos = positions.get(svc);
      if (!svcPos) continue;
      list.sort((a, b) => (rankByDeploy.get(a.id) ?? 99) - (rankByDeploy.get(b.id) ?? 99) || b.ts - a.ts);
      list.slice(0, MAX_DEPLOYS_PER_SERVICE).forEach((d, i) => {
        shownDeploys.add(d.id);
        const data: DeployNodeData = {
          deployId: d.id,
          kind: d.kind,
          minutesBefore: incident ? Math.round((incident.ts - d.ts) / 60) : null,
          rank: rankByDeploy.get(d.id) ?? null,
          clears: clearsByDeploy.get(d.id),
          dimmed: dim(d.id),
        };
        nodes.push({ id: d.id, type: 'deploy', position: getDeployPosition(svcPos, i), data: data as unknown as Record<string, unknown> });
      });
      if (list.length > MAX_DEPLOYS_PER_SERVICE) {
        nodes.push({
          id: `${svc}:more`,
          type: 'deploy',
          position: getDeployPosition(svcPos, MAX_DEPLOYS_PER_SERVICE),
          data: { deployId: '', more: list.length - MAX_DEPLOYS_PER_SERVICE } as unknown as Record<string, unknown>,
          selectable: false,
        });
      }
    }

    const style = (id: number, base: { stroke: string; width: number; dash?: string }) => {
      if (highlight.has(id)) return { stroke: COLOR.hover, width: 3, dash: undefined, z: 3 };
      if (citedBad.has(id)) return { stroke: COLOR.unverified, width: 2, dash: '5 4', z: 2 };
      if (citedOk.has(id)) return { stroke: COLOR.cited, width: 2.5, dash: undefined, z: 2 };
      return { ...base, z: 0 };
    };

    const edges: Edge[] = [];
    for (const e of depEdges) {
      const s = style(e.id, { stroke: COLOR.edge, width: 1.25 });
      edges.push({
        id: String(e.id),
        source: e.source,
        target: e.target,
        type: 'default',
        zIndex: s.z,
        style: { stroke: s.stroke, strokeWidth: s.width, strokeDasharray: s.dash, opacity: spotlight && s.z === 0 ? 0.25 : 1 },
        markerEnd: { type: MarkerType.ArrowClosed, color: s.stroke, width: 14, height: 14 },
      });
    }
    for (const e of deployEdges) {
      if (!shownDeploys.has(e.source)) continue;
      const s = style(e.id, { stroke: COLOR.edge, width: 1, dash: '3 3' });
      edges.push({
        id: String(e.id),
        source: e.source,
        target: e.target,
        targetHandle: 'deploy-in',
        type: 'straight',
        zIndex: s.z,
        style: { stroke: s.stroke, strokeWidth: s.width, strokeDasharray: s.dash, opacity: spotlight && s.z === 0 ? 0.25 : 1 },
      });
    }

    return { nodes, edges };
  }, [asOf.data, now.data, showNow, hypotheses, runView.verification, runView.touched, inv, incident,
      focusedHypothesisRank, hoveredClaimEdgeIds, pinnedEdgeIds]);

  return (
    <div className="absolute inset-0 overflow-hidden">
      {showNow && (
        <div className="absolute top-3 left-1/2 -translate-x-1/2 z-10 px-3 py-1 rounded-full text-[11px] bg-[var(--status-warn)]/15 border border-[var(--status-warn)]/40 text-[var(--status-warn)] flex items-center gap-1.5">
          <AlertTriangle className="w-3 h-3" />
          Current topology, not what existed at incident time
        </div>
      )}

      {asOf.isError ? (
        <div className="absolute inset-0 flex items-center justify-center p-6">
          <div className="flex flex-col items-center gap-2 text-center max-w-xs">
            <AlertTriangle className="w-6 h-6 text-[var(--status-bad)]" />
            <p className="text-sm text-[var(--text-primary)]">Topology unavailable</p>
            <p className="text-xs text-[var(--text-secondary)]">The graph is read from the Tracebrain API, which isn't reachable.</p>
          </div>
        </div>
      ) : asOf.isLoading ? (
        <div className="absolute inset-0 flex items-center justify-center gap-2 text-xs text-[var(--text-secondary)]">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading topology…
        </div>
      ) : (
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          colorMode="dark"
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          fitView
          fitViewOptions={{ padding: 0.15 }}
          minZoom={0.4}
          maxZoom={1.75}
          proOptions={{ hideAttribution: true }}
          style={{ background: 'var(--bg-deep)' }}
        >
          <Background variant={BackgroundVariant.Dots} gap={24} size={1} color="#1C2333" />
          <Controls showInteractive={false} position="bottom-left" />
          <FitOnTopologyChange nodeIds={nodes.map((n) => n.id).join('|')} />
        </ReactFlow>
      )}

      {!asOf.isError && !asOf.isLoading && <Legend />}
    </div>
  );
};

/** Re-fit when nodes appear or disappear (deploys arrive, tenant changes); not on highlight changes. */
const FitOnTopologyChange: React.FC<{ nodeIds: string }> = ({ nodeIds }) => {
  const { fitView } = useReactFlow();
  useEffect(() => {
    const id = requestAnimationFrame(() => void fitView({ padding: 0.15, duration: 200 }));
    return () => cancelAnimationFrame(id);
  }, [nodeIds, fitView]);
  return null;
};

const Legend: React.FC = () => (
  <div className="absolute bottom-3 right-3 z-10 flex items-center gap-3 px-3 py-1.5 rounded-md border border-[var(--border-subtle)] bg-[var(--surface-panel)]/90 text-[10px] text-[var(--text-secondary)]">
    <span className="flex items-center gap-1.5">
      <span className="w-2.5 h-2.5 rounded-sm border-2 border-[var(--status-bad)]" /> Alert
    </span>
    <span className="flex items-center gap-1.5">
      <span className="w-2.5 h-2.5 rounded-sm bg-[var(--status-warn)]/30 border border-[var(--status-warn)]/60" /> Blast radius
    </span>
    <span className="flex items-center gap-1.5">
      <span className="w-4 h-0.5 rounded bg-[#FB923C]" /> Cited path
    </span>
    <span className="flex items-center gap-1.5">
      <span className="w-4 border-t-2 border-dashed border-[#F43F5E]" /> Unverified
    </span>
    <span className="flex items-center gap-1.5">
      <span className="w-3.5 h-3.5 rounded-full bg-[var(--status-suspect)] text-[var(--text-inverse)] text-[8px] font-bold flex items-center justify-center">1</span> Suspect rank
    </span>
  </div>
);
