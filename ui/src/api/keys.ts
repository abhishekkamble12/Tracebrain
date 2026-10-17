export const queryKeys = {
  health: () => ['health'] as const,
  tenants: () => ['tenants'] as const,
  incidents: (tenant: string) => ['t', tenant, 'incidents'] as const,
  investigation: (tenant: string, invId: string) => ['t', tenant, 'inv', invId] as const,
  investigations: (tenant: string) => ['t', tenant, 'investigations'] as const,
  graph: (tenant: string, t?: number | null) => ['t', tenant, 'graph', t ?? 'now'] as const,
  memory: (tenant: string) => ['t', tenant, 'memory'] as const,
  results: () => ['results'] as const,
};
