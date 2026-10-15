"""Suspect ranking: an explicit, inspectable score per deploy (no LLM involved).

score = Σ w_k · f_k over features normalised to [0, 1]:
- proximity    1 / (1 + hops) from the alerted service along as-of dependencies (0 hops -> 1.0)
- recency      1 - age / window (deployed right before the alert -> 1.0)
- change_size  log-scaled lines changed, capped at 2000
- fail_rate    prior incidents on the deploy's service, capped at 5
- centrality   PageRank of the deploy's service, normalised (time-agnostic prior)
- lesson_match strength of a confirmed Lesson pointing at this service (memory; 0 until learned)

Weights default below; `data/weights.json` (written by calibration on the *seen* split only) overrides.
"""

import json
import math
from pathlib import Path

FEATURES = ("proximity", "recency", "change_size", "fail_rate", "centrality", "lesson_match")
DEFAULT_WEIGHTS = {"proximity": 1.0, "recency": 1.5, "change_size": 0.5, "fail_rate": 0.3,
                   "centrality": 0.2, "lesson_match": 2.0}
WEIGHTS_PATH = Path(__file__).resolve().parent.parent / "data" / "weights.json"


def load_weights() -> dict[str, float]:
    if WEIGHTS_PATH.exists():
        return {**DEFAULT_WEIGHTS, **json.loads(WEIGHTS_PATH.read_text(encoding="utf-8"))}
    return dict(DEFAULT_WEIGHTS)


def features(row: dict, t: int, window_s: int, fail_count: int, centrality: float,
             lesson_match: float = 0.0) -> dict[str, float]:
    age = max(0, t - row["ts"])
    return {
        "proximity": 1.0 / (1 + row["proximity"]),
        "recency": max(0.0, 1.0 - age / window_s),
        "change_size": min(1.0, math.log1p(max(0, row["change_size"])) / math.log1p(2000)),
        "fail_rate": min(1.0, fail_count / 5),
        "centrality": max(0.0, min(1.0, centrality)),
        "lesson_match": max(0.0, min(1.0, lesson_match)),
    }


def score(f: dict[str, float], weights: dict[str, float]) -> float:
    return sum(weights.get(k, 0.0) * f[k] for k in FEATURES)


def rank(rows: list[dict], t: int, window_s: int, fail_counts: dict[str, int], centrality: dict[str, float],
         lesson_boosts: dict[str, float] | None = None, weights: dict[str, float] | None = None) -> list[dict]:
    """Return rows sorted best-first, each with `features`, `score` and `rank` added."""
    weights = weights or load_weights()
    lesson_boosts = lesson_boosts or {}
    scored = []
    for row in rows:
        f = features(row, t, window_s, fail_counts.get(row["service"], 0), centrality.get(row["service"], 0.0),
                     lesson_boosts.get(row["service"], 0.0))
        scored.append({**row, "features": {k: round(v, 3) for k, v in f.items()},
                       "score": round(score(f, weights), 4)})
    # Ties: newer deploy first, then id, so ranking is deterministic.
    scored.sort(key=lambda r: (-r["score"], -r["ts"], r["deploy"]))
    for i, r in enumerate(scored, 1):
        r["rank"] = i
    return scored
