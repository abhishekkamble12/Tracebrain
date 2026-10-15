"""Day-1 end-to-end check: one agent investigates one incident through the MCP tools.

    uv run python -m tracebrain.agents.smoke --tenant payments --incident inc:001

Needs at least one LLM key in .env. Prints the trace, the agent's ranked answer, and whether the
hidden ground-truth culprit was in it (ground truth is read only here, never shown to the agent).
"""

import argparse
import json
from pathlib import Path

import anyio
from mcp import Client

from tracebrain.agents.loop import run_agent
from tracebrain.tools import impl, mcp_server
from tracebrain.tools.impl import ToolCtx

SYSTEM = """You are an incident investigator. Use the tools to find which deploy most likely caused the
incident. Facts must come from tool results; never invent services, deploys or edge ids.
Steps: get the incident, get ranked suspects for the alerted service, check paths or owners if useful,
then call submit_suspects with your top 3 (best first) and the edge_ids that support each one."""

SUBMIT = {"type": "function", "function": {
    "name": "submit_suspects",
    "description": "Submit your final ranked suspects (best first).",
    "parameters": {"type": "object", "properties": {
        "suspects": {"type": "array", "maxItems": 3, "items": {"type": "object", "properties": {
            "deploy": {"type": "string"}, "reason": {"type": "string"},
            "edge_ids": {"type": "array", "items": {"type": "integer"}}},
            "required": ["deploy", "reason", "edge_ids"]}}},
        "required": ["suspects"]}}}


async def main(tenant: str, incident_id: str) -> int:
    truth = json.loads((Path(__file__).resolve().parents[2] / "data" / "ground_truth.json")
                       .read_text(encoding="utf-8")).get(f"{tenant}/{incident_id}")
    inc = impl.get_incident(ToolCtx(tenant, 0), incident_id)
    ctx = ToolCtx(tenant=tenant, t=inc["ts"], investigation_id=f"smoke:{incident_id}")

    async with Client(mcp_server.server) as client:
        run = await run_agent(
            "investigator", SYSTEM, f"Investigate incident {incident_id}.", ctx,
            {"get_incident", "suspects", "path_between", "owners_of", "blast_radius"}, client,
            final_tool=SUBMIT,
            on_step=lambda s: print(f"  [{s.n}] {s.tool}({json.dumps(s.args)}) {s.ms}ms "
                                    f"edges={len(s.edge_ids)}{' ERROR ' + s.error if s.error else ''}"),
        )
    print(f"\nstopped={run.stopped} turns={run.turns} tool_calls={len(run.steps)} "
          f"tokens={run.usage} models={sorted(run.models)}")
    picks = [s["deploy"] for s in (run.final or {}).get("suspects", [])]
    for s in (run.final or {}).get("suspects", []):
        print(f"  -> {s['deploy']}: {s['reason']} (edges {s['edge_ids']})")
    if truth and truth["culprit_deploy"]:
        hit = truth["culprit_deploy"] in picks
        print(f"\nground truth {truth['culprit_deploy']}: top-1 {'HIT' if picks[:1] == [truth['culprit_deploy']] else 'miss'}, "
              f"top-3 {'HIT' if hit else 'miss'}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="payments")
    ap.add_argument("--incident", default="inc:001")
    a = ap.parse_args()
    raise SystemExit(anyio.run(main, a.tenant, a.incident))
