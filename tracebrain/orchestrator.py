"""Runs one investigation as resumable stages, driven by the state stored in the graph:

  OPEN          -> Triage agent writes findings -> handoff                     -> TRIAGED
  TRIAGED       -> Investigator agent -> evidence gate -> hypotheses + actions -> HYPOTHESIZED
  HYPOTHESIZED  -> sandbox rollback check of the top hypothesis  -> VERIFIED (if it clears)
                -> AWAITING_REVIEW  (then a human review runs the Curator: CONFIRMED/REJECTED -> LEARNED)

`run()` continues from whatever stage the graph says, so the same call starts a fresh investigation,
resumes one interrupted by a restart, or retries one that FAILED (e.g. LLM quota exhausted).
Completed tool calls are replayed from their persisted Steps, not re-executed.
Every event also goes to `on_event` (the API streams them to the UI).
"""

import logging
import time
from typing import Any, Callable

from mcp import Client

from tracebrain import db, faithfulness, llm, queries, verification
from tracebrain.agents import prompts
from tracebrain.agents.loop import AgentRun, Step, replay, run_agent
from tracebrain.memory import episodic
from tracebrain.tools import impl, mcp_server
from tracebrain.tools.impl import ToolCtx

# get_incident stays on the MCP server for external clients; the brief already carries the incident.
TRIAGE_TOOLS = {"blast_radius", "owners_of", "recall_similar", "write_finding"}
INVESTIGATOR_TOOLS = {"read_findings", "suspects", "path_between", "owners_of", "centrality",
                      "recall_lessons", "recall_similar", "get_past_investigation"}
REQUIRED_FINDINGS = {"blast_radius", "owners"}

log = logging.getLogger(__name__)
EventHook = Callable[[str, dict], Any]
DEFAULT_ENV = "default"


class Investigation:
    """Run state shared by both agents: all steps so far (loaded from the graph on resume)."""

    def __init__(self, tenant: str, inv_id: str, on_event: EventHook | None):
        self.tenant, self.inv_id, self.on_event = tenant, inv_id, on_event
        self.steps: list[Step] = [Step(s["n"], s["agent"], s["tool"], s["args"], s["result"], s["ms"],
                                       list(s["edge_ids"] or []), s["error"])
                                  for s in episodic.steps(tenant, inv_id)]
        self.runs: list[AgentRun] = []

    def emit(self, kind: str, data: dict) -> None:
        if self.on_event:
            try:
                self.on_event(kind, {"investigation": self.inv_id, **data})
            except Exception:  # a broken listener (console, SSE) must never fail the investigation
                log.exception("event hook failed on %r", kind)

    @property
    def state(self) -> str:
        return episodic.get(self.tenant, self.inv_id)["state"]

    def move(self, new_state: str) -> None:
        episodic.set_state(self.tenant, self.inv_id, new_state)
        self.emit("state", {"state": new_state})

    def record(self, step: Step) -> None:
        self.steps.append(step)
        n = len(self.steps)
        step.n = n
        episodic.log_step(self.tenant, self.inv_id, n, step.agent, step.tool, step.args, step.result,
                          step.edge_ids, step.ms, step.error)
        self.emit("step", {"n": n, "agent": step.agent, "tool": step.tool, "args": step.args, "ms": step.ms,
                           "edge_ids": step.edge_ids, "error": step.error})

    def agent_steps(self, agent: str) -> list[Step]:
        return [s for s in self.steps if s.agent == agent]

    @property
    def seen_edges(self) -> set[int]:
        return {e for s in self.steps for e in s.edge_ids}

    @property
    def seen_deploys(self) -> set[str]:
        return faithfulness.collect_deploys([s.result for s in self.steps if s.tool == "suspects"])

    def suspect_rows(self) -> dict[str, dict]:
        rows: dict[str, dict] = {}
        for s in self.steps:
            if s.tool == "suspects" and isinstance(s.result, dict):
                for r in s.result.get("suspects", []):
                    rows.setdefault(r["deploy"], r)
        return rows


def start(tenant: str, incident_id: str, memory_enabled: bool = True) -> str:
    return episodic.start_investigation(tenant, incident_id, memory_enabled)


async def investigate(tenant: str, incident_id: str, *, memory_enabled: bool = True, **kw) -> str:
    inv_id = start(tenant, incident_id, memory_enabled)
    await run(tenant, inv_id, **kw)
    return inv_id


async def run(tenant: str, inv_id: str, *, chat_fn: Callable[..., llm.ChatResult] = llm.chat,
              on_event: EventHook | None = None, client: Client | None = None,
              environment: verification.Environment | None | str = DEFAULT_ENV) -> str:
    """Start or continue an investigation from its stored state. Returns the final state."""
    meta = episodic.get(tenant, inv_id)
    if meta["state"] in episodic.TERMINAL:
        return meta["state"]
    started = time.perf_counter()
    inv = Investigation(tenant, inv_id, on_event)
    resumed = bool(inv.steps) or meta["state"] != "OPEN"
    if meta["state"] == "FAILED":
        inv.move(episodic.resume_point(tenant, inv_id))
    inc = impl.get_incident(ToolCtx(tenant, 0), meta["incident_id"])
    ctx = ToolCtx(tenant=tenant, t=inc["ts"], investigation_id=inv_id, memory_enabled=meta["memory_enabled"],
                  symptom=inc["symptom"], service=inc["service"])
    env = verification.default_environment() if environment == DEFAULT_ENV else environment
    inv.emit("resumed" if resumed else "started",
             {"incident": inc, "memory_enabled": meta["memory_enabled"], "from_state": inv.state,
              "replayed_steps": len(inv.steps)})

    try:
        if client is None:
            async with Client(mcp_server.server) as c:
                await _stages(inv, ctx, inc, c, chat_fn, env)
        else:
            await _stages(inv, ctx, inc, client, chat_fn, env)
    except Exception as e:  # quota, provider or graph failure: keep everything, mark resumable
        inv.emit("error", {"error": describe_error(e)})
        if inv.state not in episodic.TERMINAL and inv.state != "FAILED":
            inv.move("FAILED")

    _save_stats(inv, meta, int((time.perf_counter() - started) * 1000), resumed)
    final = episodic.get(tenant, inv_id)
    inv.emit("done", {"state": final["state"], "outcome": final["outcome"], "tool_calls": final["tool_calls"],
                      "faithfulness": final["faithfulness"]})
    return final["state"]


def describe_error(e: BaseException) -> str:
    """The MCP client runs inside an anyio TaskGroup, so a failure surfaces as an ExceptionGroup
    whose message hides the cause. Report the leaf exception(s) instead."""
    if isinstance(e, BaseExceptionGroup):
        return "; ".join(describe_error(x) for x in e.exceptions)
    return f"{type(e).__name__}: {e}"


async def _stages(inv: Investigation, ctx: ToolCtx, inc: dict, client: Client, chat_fn,
                  env: verification.Environment | None) -> None:
    brief = prompts.incident_brief(inc, inv.inv_id)
    if inv.state == "OPEN":
        await _triage(inv, ctx, brief, client, chat_fn)
    if inv.state == "TRIAGED":
        await _investigate(inv, ctx, brief, client, chat_fn)
    if inv.state == "HYPOTHESIZED":
        _verify(inv, inc, env)
    if inv.state == "VERIFIED":
        inv.move("AWAITING_REVIEW")


async def _triage(inv: Investigation, ctx: ToolCtx, brief: str, client: Client, chat_fn) -> None:
    def gate(_args: dict, _run: AgentRun) -> str | None:
        kinds = {f["kind"] for f in episodic.findings(inv.tenant, inv.inv_id)}
        missing = REQUIRED_FINDINGS - kinds
        return f"write findings of kind {sorted(missing)} with write_finding before finishing" if missing else None

    triage = await run_agent("triage", prompts.TRIAGE, brief, ctx, TRIAGE_TOOLS, client,
                             final_tool=prompts.FINISH_TRIAGE, validate_final=gate, chat_fn=chat_fn,
                             on_step=inv.record, history=replay(inv.agent_steps("triage")))
    inv.runs.append(triage)
    added = _ensure_findings(inv, ctx)
    if added:
        inv.emit("fallback_findings", {"kinds": added})
    handed = episodic.handoff(inv.tenant, inv.inv_id, "triage", "investigator")
    inv.emit("handoff", {"from": "triage", "to": "investigator", "findings": handed,
                         "summary": (triage.final or {}).get("summary")})
    inv.move("TRIAGED")


def _ensure_findings(inv: Investigation, ctx: ToolCtx) -> list[str]:
    """If triage failed to record required findings, record them deterministically (marked as such)."""
    kinds = {f["kind"] for f in episodic.findings(inv.tenant, inv.inv_id)}
    added = []
    if "blast_radius" not in kinds:
        episodic.write_finding(inv.tenant, inv.inv_id, "orchestrator", "blast_radius",
                               impl.blast_radius(ctx, ctx.service))
        added.append("blast_radius")
    if "owners" not in kinds:
        affected = [a["service"] for a in impl.blast_radius(ctx, ctx.service)["affected"]]
        episodic.write_finding(inv.tenant, inv.inv_id, "orchestrator", "owners",
                               impl.owners_of(ctx, [ctx.service, *affected]))
        added.append("owners")
    return added


async def _investigate(inv: Investigation, ctx: ToolCtx, brief: str, client: Client, chat_fn) -> None:
    def gate(args: dict, _run: AgentRun) -> str | None:
        return faithfulness.gate(inv.tenant, args, inv.seen_edges, inv.seen_deploys)

    investigator = await run_agent("investigator", prompts.INVESTIGATOR,
                                   brief + " Triage is done; its findings are on the blackboard.", ctx,
                                   INVESTIGATOR_TOOLS, client, final_tool=prompts.SUBMIT_HYPOTHESES,
                                   validate_final=gate, chat_fn=chat_fn, on_step=inv.record,
                                   history=replay(inv.agent_steps("investigator")))
    inv.runs.append(investigator)

    final = dict(investigator.final or {})
    final.setdefault("hypotheses", [])
    rows = inv.suspect_rows()
    if not rows:  # nothing deployed on the as-of dependency closure in the window
        final.update(abstain=True, hypotheses=[],
                     abstain_reason=final.get("abstain_reason") or "no suspect deploys in the look-back window",
                     actions=[a for a in final.get("actions") or [] if a.get("kind") == "page"])
    if investigator.stopped != "final":
        final.setdefault("abstain", not final["hypotheses"])
        final.setdefault("abstain_reason", f"investigator stopped: {investigator.stopped}")

    graded = faithfulness.apply(inv.tenant, final, inv.seen_edges, inv.seen_deploys)
    hyps = [{**h, "score": rows.get(h.get("deploy_id"), {}).get("score", 0.0),
             "features": rows.get(h.get("deploy_id"), {}).get("features", {})}
            for h in graded["hypotheses"] if h.get("deploy_id") in inv.seen_deploys]
    episodic.store_hypotheses(inv.tenant, inv.inv_id, hyps)
    actions = [a for a in final.get("actions") or []
               if a.get("kind") in faithfulness.ACTION_KINDS and a.get("target")]
    episodic.store_actions(inv.tenant, inv.inv_id, actions)
    inv.graded = graded
    inv.move("HYPOTHESIZED")
    abstained = bool(final.get("abstain")) or not hyps
    episodic.set_outcome(inv.tenant, inv.inv_id, "abstained" if abstained else "proposed", "awaiting_review")
    inv.emit("hypotheses", {"hypotheses": hyps, "actions": actions, "abstain": abstained,
                            "abstain_reason": final.get("abstain_reason"), "faithfulness": graded["faithfulness"],
                            "problems": graded["problems"]})


def _verify(inv: Investigation, inc: dict, env: verification.Environment | None) -> None:
    hyps = episodic.hypotheses(inv.tenant, inv.inv_id)
    if hyps and env is not None:
        top = hyps[0]
        if top["verifications"]:  # already verified before an interruption
            result = {"deploy_id": top["deploy_id"], **top["verifications"][0]}
        else:
            result = verification.verify_rollback(inv.tenant, inc["id"], top["id"], top["deploy_id"], env)
        inv.emit("verification", result)
        if result["clears"]:
            inv.move("VERIFIED")
            return
    inv.move("AWAITING_REVIEW")


def _save_stats(inv: Investigation, before: dict, duration_ms: int, resumed: bool) -> None:
    graded = getattr(inv, "graded", None)
    db.write(inv.tenant, queries.SET_RUN_STATS, {
        "id": inv.inv_id,
        "tool_calls": len(inv.steps),
        "turns": (before.get("turns") or 0) + sum(r.turns for r in inv.runs),
        "prompt_tokens": (before.get("prompt_tokens") or 0) + sum(r.usage["prompt_tokens"] for r in inv.runs),
        "completion_tokens": (before.get("completion_tokens") or 0)
        + sum(r.usage["completion_tokens"] for r in inv.runs),
        "models": sorted(set(before.get("models") or []) | {m for r in inv.runs for m in r.models}),
        "faithfulness": graded["faithfulness"] if graded else before.get("faithfulness"),
        "claims_total": graded["claims_total"] if graded else 0,
        "duration_ms": (before.get("duration_ms") or 0) + duration_ms,
        "abstained": episodic.get(inv.tenant, inv.inv_id)["outcome"] == "abstained",
        "resumes": (before.get("resumes") or 0) + int(resumed),
    })
