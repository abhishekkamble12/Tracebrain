export type InvestigationState =
  | 'OPEN'
  | 'TRIAGED'
  | 'HYPOTHESIZED'
  | 'VERIFIED'
  | 'AWAITING_REVIEW'
  | 'CONFIRMED'
  | 'REJECTED'
  | 'LEARNED'
  | 'FAILED';

export interface IncidentRow {
  id: string;
  ts: number;
  symptom: string;
  text: string;
  severity: string;
  status: string;
  service: string;
  investigation: string | null;
  investigation_state: InvestigationState | null;
}

export interface Claim {
  text: string;
  edge_ids: number[];
  verified: boolean;
  reason: string;
}

export type ScoreFeatureName =
  | 'proximity'
  | 'recency'
  | 'change_size'
  | 'fail_rate'
  | 'centrality'
  | 'lesson_match';

export type Features = Record<ScoreFeatureName, number>;

export interface Verification {
  method: string;
  environment: string;
  clears: boolean | null;
  ts: number;
  next_suspect?: string | null;
  next_suspect_service?: string | null;
  remaining_candidates?: number;
}

export interface Hypothesis {
  id?: string;
  rank: number;
  deploy_id: string;
  service?: string;
  kind?: string;
  change_size?: number;
  minutes_before?: number;
  author?: string;
  likely_cause: string;
  summary: string;
  score: number;
  features: Features;
  claims: Claim[];
  verifications?: Verification[];
}

export interface Action {
  id?: string;
  kind: 'ticket' | 'rollback_proposal' | 'page';
  target: string;
  reason: string;
  status?: string;
}

export interface Finding {
  kind: string;
  data: Record<string, unknown>;
  handed_to?: string;
}

export interface Step {
  n: number;
  agent: string;
  tool: string;
  args: Record<string, unknown>;
  result?: unknown;
  ms: number;
  edge_ids: number[];
  error: string | null;
}

export interface InvestigationFull {
  id: string;
  incident_id: string;
  state: InvestigationState;
  started: number;
  updated: number;
  memory_enabled: boolean;
  outcome: 'proposed' | 'abstained' | 'confirmed' | 'rejected' | null;
  tool_calls: number | null;
  turns: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  models: string[] | null;
  faithfulness: number | null;
  duration_ms: number | null;
  resumes: number | null;
  steps: Step[];
  findings: Finding[];
  hypotheses: Hypothesis[];
  actions: Action[];
  incident?: IncidentRow | null;
  running?: boolean;
}

export interface GraphNodeService {
  id: string;
  type: 'service';
  name: string;
  tier?: string;
  service_type?: string;
  team?: string;
}

export interface GraphNodeDeploy {
  id: string;
  type: 'deploy';
  service: string;
  ts: number;
  kind?: string;
  change_size?: number;
  summary?: string;
  author?: string;
  edge_id?: number;
}

export type GraphNode = GraphNodeService | GraphNodeDeploy;

export interface GraphEdge {
  id: number;
  source: string;
  target: string;
  type: 'DEPENDS_ON' | 'DEPLOYED_TO';
}

export interface GraphPayload {
  as_of: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface Lesson {
  id: string;
  symptom: string;
  service: string;
  check_first: string;
  success_count: number;
  fail_count: number;
  retracted: boolean;
  cause: string;
  evidence: string[];
}

export interface Cause {
  key: string;
  name: string;
  aliases: string[];
  confidence: number;
  confirmations: number;
  rejections: number;
  retracted: boolean;
}

export interface MemoryPayload {
  causes: Cause[];
  lessons: Lesson[];
}

export interface HealthResponse {
  falkordb: boolean;
  llm_providers: string[];
  running: number;
}

export interface StartInvestigationResponse {
  investigation_id: string;
  events: string;
}

export interface ReviewRequest {
  verdict: 'confirm' | 'reject';
  reviewer: string;
  deploy_id?: string;
  cause_text?: string;
}

/** Mirrors curator.review's return value. */
export interface ReviewResponse {
  verdict: 'confirm' | 'reject';
  investigation: string;
  incident: string;
  // confirm
  lesson?: { id: string; success_count: number; fail_count: number };
  cause_key?: string;
  cause_is_new?: boolean;
  confidence?: number;
  deploy_id?: string;
  top_was_right?: boolean;
  // confirm (when #1 was wrong) or reject
  weakened?: { id: string; fail_count: number; retracted?: boolean }[];
  // reject, when the rejected cause matched a known one
  cause?: { key: string; confidence: number; retracted: boolean };
}
