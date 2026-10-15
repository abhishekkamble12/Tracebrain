"""End-to-end check with a real LLM: Triage -> Investigator -> evidence gate on one incident.

    uv run python -m tracebrain.agents.smoke --tenant payments --incident inc:001 [--no-memory] [--confirm]

Needs at least one LLM key in .env. Prints the live trace, the hypotheses with claim verdicts, and
whether the hidden ground-truth culprit was found (ground truth is read only here, never by agents).
--confirm then reviews the top hypothesis as the ground truth says (teaching memory).
"""

import argparse
import json
from pathlib import Path

import anyio

from tracebrain import orchestrator
from tracebrain.agents import curator
from tracebrain.memory import episodic

TRUTH = Path(__file__).resolve().parents[2] / "data" / "ground_truth.json"


def show(kind: str, d: dict) -> None:
    if kind == "step":
        err = f"  ERROR {d['error']}" if d["error"] else ""
        print(f"  [{d['n']:>2}] {d['agent']:<12} {d['tool']}({json.dumps(d['args'])[:90]}) {d['ms']}ms "
              f"edges={len(d['edge_ids'])}{err}")
    elif kind in ("state", "handoff", "fallback_findings", "error"):
        print(f"  -- {kind}: {({k: v for k, v in d.items() if k != 'investigation'})}")


async def main(tenant: str, incident_id: str, memory: bool, confirm: bool) -> int:
    truth = json.loads(TRUTH.read_text(encoding="utf-8")).get(f"{tenant}/{incident_id}", {})
    inv_id = await orchestrator.investigate(tenant, incident_id, memory_enabled=memory, on_event=show)
    full = episodic.full(tenant, inv_id)
    print(f"\n{inv_id}: state={full['state']} outcome={full['outcome']}")
    for h in full["hypotheses"]:
        print(f"  #{h['rank']} {h['deploy_id']} score={h['score']} cause={h['likely_cause']!r}")
        for c in h["claims"]:
            print(f"       {'OK ' if c['verified'] else 'BAD'} {c['text']}  {c['edge_ids']}  {'' if c['verified'] else c['reason']}")
    for a in full["actions"]:
        print(f"  action {a['kind']} -> {a['target']}: {a['reason']}")
    picks = [h["deploy_id"] for h in full["hypotheses"]]
    if truth:
        want = truth["culprit_deploy"]
        if want is None:
            print(f"\nground truth: no culprit -> {'CORRECT abstain' if full['outcome'] == 'abstained' else 'should have abstained'}")
        else:
            print(f"\nground truth {want}: top-1 {'HIT' if picks[:1] == [want] else 'miss'}, "
                  f"top-3 {'HIT' if want in picks else 'miss'}")
        if confirm and want:
            out = curator.review(tenant, inv_id, "confirm", reviewer="smoke", deploy_id=want,
                                 cause_text=truth["cause_key"].replace("_", " "))
            print(f"confirmed -> lesson {out['lesson']['id']} (cause {out['cause_key']})")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="payments")
    ap.add_argument("--incident", default="inc:001")
    ap.add_argument("--no-memory", action="store_true")
    ap.add_argument("--confirm", action="store_true", help="confirm with the ground-truth answer afterwards")
    a = ap.parse_args()
    raise SystemExit(anyio.run(main, a.tenant, a.incident, not a.no_memory, a.confirm))
