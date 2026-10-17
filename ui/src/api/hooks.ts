import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiGet, apiPost, ApiError } from './client';
import { queryKeys } from './keys';
import type {
  HealthResponse,
  IncidentRow,
  InvestigationFull,
  GraphPayload,
  MemoryPayload,
  StartInvestigationResponse,
  ReviewRequest,
  ReviewResponse,
} from './types';

export function useHealth() {
  return useQuery({
    queryKey: queryKeys.health(),
    queryFn: () => apiGet<HealthResponse>('/health'),
    refetchInterval: 30000,
    retry: 0,
  });
}

/** True only for Tracebrain's /health shape; another service answering on the same port fails this. */
export function isTracebrainHealth(h: unknown): h is HealthResponse {
  const r = h as Partial<HealthResponse> | null | undefined;
  return Boolean(r && typeof r.falkordb === 'boolean' && Array.isArray(r.llm_providers));
}

export function useTenants() {
  return useQuery({
    queryKey: queryKeys.tenants(),
    queryFn: () => apiGet<string[]>('/tenants'),
  });
}

export function useIncidents(tenant: string) {
  return useQuery({
    queryKey: queryKeys.incidents(tenant),
    queryFn: () => apiGet<IncidentRow[]>(`/tenants/${tenant}/incidents`),
    enabled: Boolean(tenant),
    staleTime: 5000,
  });
}

export function useInvestigation(tenant: string, invId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.investigation(tenant, invId || ''),
    queryFn: () => apiGet<InvestigationFull>(`/tenants/${tenant}/investigations/${invId}`),
    enabled: Boolean(tenant && invId),
    // Step results (blast radius, suspects) aren't in the SSE events; poll the record while it runs.
    refetchInterval: (q) => (q.state.data?.running ? 4000 : false),
  });
}

/** `t` = as-of timestamp; omitted means the current topology. */
export function useGraph(tenant: string, t?: number | null, enabled = true) {
  return useQuery({
    queryKey: queryKeys.graph(tenant, t),
    queryFn: () => apiGet<GraphPayload>(`/tenants/${tenant}/graph`, t ? { t } : undefined),
    enabled: Boolean(tenant) && enabled,
    staleTime: t ? Infinity : 5000,
  });
}

export function useMemory(tenant: string) {
  return useQuery({
    queryKey: queryKeys.memory(tenant),
    queryFn: () => apiGet<MemoryPayload>(`/tenants/${tenant}/memory`),
    enabled: Boolean(tenant),
    staleTime: 15000,
  });
}

/** eval/results.json via the API; `null` when the eval hasn't produced it yet (404). */
export function useResults() {
  return useQuery({
    queryKey: queryKeys.results(),
    queryFn: async () => {
      try {
        return await apiGet<Record<string, unknown>>('/results');
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return null;
        throw e;
      }
    },
    retry: 0,
  });
}

export function useStartInvestigation(tenant: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ incidentId, memoryEnabled }: { incidentId: string; memoryEnabled: boolean }) =>
      apiPost<StartInvestigationResponse>(`/tenants/${tenant}/incidents/${incidentId}/investigate`, {
        memory_enabled: memoryEnabled,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.incidents(tenant) });
    },
  });
}

export function useReview(tenant: string, invId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: ReviewRequest) =>
      apiPost<ReviewResponse>(`/tenants/${tenant}/investigations/${invId}/review`, req),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.incidents(tenant) });
      qc.invalidateQueries({ queryKey: queryKeys.investigation(tenant, invId) });
      qc.invalidateQueries({ queryKey: queryKeys.memory(tenant) });
    },
  });
}

export function useRetractCause(tenant: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (key: string) => apiPost<{ key: string; retracted: boolean }>(`/tenants/${tenant}/causes/${key}/retract`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.memory(tenant) });
    },
  });
}
