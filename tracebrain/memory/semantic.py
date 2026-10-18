"""Semantic memory: Cause nodes with entity resolution, confidence and retraction.

"db timeout", "Database timeouts" and "DB time-outs" must resolve to ONE Cause node, or memory
fragments. Resolution order (cheap first):
  1. normalise -> exact match on a Cause key or alias
  2. token Jaccard >= MERGE_AT against existing causes -> merge
  3. ASK_AT <= Jaccard < MERGE_AT -> ask a small LLM "same cause?" (optional; skipped if unavailable)
  4. otherwise a new Cause (confidence 0.5)
Confidence: confirm -> 1 - 0.5 * 0.7^confirmations ; reject -> halve ; retracted below 0.2.
"""

import re
from typing import Callable

from tracebrain import db, queries

MERGE_AT = 0.6
ASK_AT = 0.3
RETRACT_BELOW = 0.2

SYNONYMS = {
    "db": "database", "dbs": "database", "conn": "connection", "conns": "connection", "oom": "out memory",
    "env": "environment", "var": "variable", "vars": "variable", "config": "configuration",
    "cfg": "configuration", "perf": "performance", "timeouts": "timeout", "timed": "timeout",
    "n+1": "n plus one", "exhausted": "exhaustion", "leak": "leak", "leaks": "leak",
}
STOPWORDS = {"the", "a", "an", "of", "in", "on", "to", "due", "caused", "by", "issue", "problem", "and", "for",
             "with", "from", "at", "is", "was", "too", "many"}

# Judge: (new_text, candidate_names) -> index of the matching candidate, or None.
Judge = Callable[[str, list[str]], int | None]


def tokens(text: str) -> list[str]:
    text = text.lower().replace("time-out", "timeout").replace("time out", "timeout")
    out: list[str] = []
    for raw in re.findall(r"[a-z0-9+]+", text):
        for tok in SYNONYMS.get(raw, raw).split():
            if len(tok) > 3 and tok.endswith("s") and not tok.endswith(("ss", "is", "us")):
                tok = tok[:-1]
            if tok not in STOPWORDS:
                out.append(tok)
    return out


def normalise(text: str) -> str:
    return "_".join(tokens(text))


def jaccard(a: str, b: str) -> float:
    sa, sb = set(tokens(a)), set(tokens(b))
    return len(sa & sb) / len(sa | sb) if sa | sb else 0.0


def all_causes(tenant: str) -> list[dict]:
    return db.read(tenant, queries.CAUSES)


def llm_judge(text: str, candidates: list[str]) -> int | None:
    """Small-model fallback for borderline matches. Any failure means 'no match'."""
    from tracebrain import llm
    prompt = (f"New root-cause description: {text!r}\nExisting causes:\n" +
              "\n".join(f"{i}. {c}" for i, c in enumerate(candidates)) +
              "\nIs the new description the SAME root cause as one of them? "
              "Answer with only the number, or 'none'.")
    try:
        reply = llm.chat([{"role": "user", "content": prompt}], tier="fast", max_tokens=8)
    except Exception:
        return None
    m = re.search(r"\d+", reply.content or "")
    return int(m.group()) if m and int(m.group()) < len(candidates) else None


def resolve(tenant: str, text: str, judge: Judge | None = llm_judge) -> tuple[str, bool]:
    """Return (cause_key, is_new) for a free-text cause description."""
    key = normalise(text)
    if not key:
        raise ValueError("empty cause description")
    causes = all_causes(tenant)
    for c in causes:
        if key == c["key"] or key in {normalise(a) for a in (c["aliases"] or [])}:
            return c["key"], False
    scored = sorted(((max([jaccard(text, c["name"])] + [jaccard(text, a) for a in c["aliases"] or []]), c)
                     for c in causes), key=lambda x: -x[0])
    if scored and scored[0][0] >= MERGE_AT:
        return scored[0][1]["key"], False
    borderline = [c for s, c in scored if ASK_AT <= s < MERGE_AT][:3]
    if borderline and judge:
        pick = judge(text, [c["name"] for c in borderline])
        if pick is not None:
            return borderline[pick]["key"], False
    return key, True


def upsert(tenant: str, text: str, judge: Judge | None = llm_judge) -> dict:
    key, is_new = resolve(tenant, text, judge)
    row = db.write(tenant, queries.UPSERT_CAUSE, {"key": key, "name": text.strip(), "alias": text.strip()})[0]
    return {**row, "is_new": is_new}


def _one(rows: list[dict], key: str) -> dict:
    if not rows:
        raise KeyError(key)
    return rows[0]


def confirm(tenant: str, key: str) -> dict:
    """confidence = 1 - 0.5 * 0.7^confirmations, computed in the graph so concurrent confirms all count."""
    return _one(db.write(tenant, queries.CONFIRM_CAUSE, {"key": key}), key)


def reject(tenant: str, key: str) -> dict:
    return _one(db.write(tenant, queries.REJECT_CAUSE, {"key": key, "retract_below": RETRACT_BELOW}), key)


def retract(tenant: str, key: str) -> None:
    _one(db.write(tenant, queries.RETRACT_CAUSE, {"key": key}), key)
