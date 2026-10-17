"""Seed tenant graphs with the synthetic world and write hidden ground truth for the eval.

    uv run python -m tracebrain.seed --reset
"""

import argparse
import json
import sys
from pathlib import Path

from tracebrain import db, schema
from tracebrain.connectors.synthetic import TENANTS, SyntheticConnector, leakage_violations
from tracebrain.ingest import ingest

TRUTH_PATH = Path(__file__).resolve().parent.parent / "data" / "ground_truth.json"


def seed(tenants: list[str], reset: bool) -> dict:
    truth: dict[str, dict] = {}
    for tenant in tenants:
        conn = SyntheticConnector(tenant)
        leaks = leakage_violations(conn.world)
        if leaks:
            raise SystemExit("leakage guard failed:\n  " + "\n  ".join(leaks))
        if reset:
            schema.drop(tenant)
        schema.apply(tenant)
        report = ingest(tenant, conn)
        print(f"{tenant}: {report}")
        truth.update({f"{tenant}/{k}": v for k, v in conn.world.truth.items()})
    TRUTH_PATH.parent.mkdir(parents=True, exist_ok=True)
    TRUTH_PATH.write_text(json.dumps(truth, indent=1), encoding="utf-8")
    print(f"ground truth: {len(truth)} incidents -> {TRUTH_PATH}")
    return truth


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenants", default=",".join(TENANTS))
    ap.add_argument("--reset", action="store_true", help="drop the tenant graphs first")
    args = ap.parse_args()
    try:
        db.ping()
    except Exception as e:
        raise SystemExit(f"Can't seed: {e}")
    seed([t for t in args.tenants.split(",") if t], args.reset)
    return 0


if __name__ == "__main__":
    sys.exit(main())
