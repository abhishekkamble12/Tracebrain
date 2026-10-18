import type { Step } from '@/api/types';

/** What memory a run recalled, read from its stored recall_* tool results (no extra API call). */
export interface RecalledLesson {
  id: string;
  check_first: string;
  success_count: number;
  fail_count: number;
  weight?: number;
  cause?: string | null;
  evidence: string[];
}

export interface SimilarIncident {
  incident: string;
  service: string;
  cause: string;
  culprit_service?: string | null;
}

export interface MemoryRecall {
  symptom?: string;
  service?: string;
  lessons: RecalledLesson[];
  similar: SimilarIncident[];
  /** True if a recall tool ran (with memory on or off). */
  consulted: boolean;
}

function lastResult(steps: Step[], tool: string): Record<string, unknown> | null {
  const s = [...steps].reverse().find((x) => x.tool === tool && !x.error && x.result && typeof x.result === 'object');
  return (s?.result as Record<string, unknown>) ?? null;
}

export function memoryRecall(steps: Step[] | undefined): MemoryRecall {
  const all = steps ?? [];
  const lessons = lastResult(all, 'recall_lessons');
  const similar = lastResult(all, 'recall_similar');
  return {
    symptom: (lessons?.symptom ?? similar?.symptom) as string | undefined,
    service: lessons?.service as string | undefined,
    lessons: ((lessons?.lessons as RecalledLesson[]) ?? []).filter((l) => l && l.check_first),
    similar: ((similar?.similar as SimilarIncident[]) ?? []).filter((x) => x && x.incident),
    consulted: Boolean(lessons || similar),
  };
}

/** Services that recalled memory points at: lesson check_first targets and past culprit services. */
export function recalledServices(r: MemoryRecall): Set<string> {
  return new Set([
    ...r.lessons.map((l) => l.check_first),
    ...r.similar.map((s) => s.culprit_service).filter((s): s is string => Boolean(s)),
  ]);
}
