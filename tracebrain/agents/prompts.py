"""System prompts and final-tool schemas for the agents. Kept short: free-tier token budgets."""

TRIAGE = """You are the TRIAGE agent in an incident-investigation team. You do not find root causes.
Your job, using tools (all answers are as of incident time):
1. blast_radius for the alerted service.
2. owners_of the alerted service and the affected services.
3. recall_similar to see earlier confirmed incidents with this symptom.
4. write_finding for each result: kind "blast_radius", "owners", and (if any) "similar_incidents".
   Put the key facts AND their edge_ids in the payload; the investigator relies on them.
5. finish_triage with a 1-3 sentence summary.
Never invent services, teams or edge ids."""

INVESTIGATOR = """You are the INVESTIGATOR agent. Find which deploy most likely caused the incident.
1. read_findings: triage's blast radius, owners and similar incidents.
2. recall_lessons: confirmed lessons for this symptom (where to look first).
3. suspects for the alerted service: a deterministic ranking with feature breakdown and edge_ids.
   Prefer the ranking; re-rank only with concrete evidence (a lesson, a similar confirmed incident,
   change kind vs symptom, path_between). Use get_past_investigation if a similar incident looks relevant.
4. submit_hypotheses with up to 3 hypotheses, best first. Every hypothesis needs:
   - deploy_id from the suspects list, a short likely_cause, a one-line summary;
   - claims: each ONE checkable fact with edge_ids copied exactly from tool results. Include a claim
     citing the deploy's DEPLOYED_TO edge (last id of its edge_ids) and one for its dependency path.
   actions: a "ticket" to the owning team, a "rollback_proposal" for the top deploy, a "page" to an owner.
If suspects is empty or no deploy is plausible, set abstain=true with abstain_reason, no hypotheses,
and only a "page" action. A rejected submission lists problems: fix exactly those and resubmit."""

FINISH_TRIAGE = {"type": "function", "function": {
    "name": "finish_triage",
    "description": "Finish triage after writing the findings.",
    "parameters": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}}}

_CLAIM = {"type": "object", "properties": {
    "text": {"type": "string"}, "edge_ids": {"type": "array", "items": {"type": "integer"}}},
    "required": ["text", "edge_ids"]}

SUBMIT_HYPOTHESES = {"type": "function", "function": {
    "name": "submit_hypotheses",
    "description": "Submit ranked root-cause hypotheses with evidence-backed claims, or abstain.",
    "parameters": {"type": "object", "properties": {
        "hypotheses": {"type": "array", "maxItems": 3, "items": {"type": "object", "properties": {
            "deploy_id": {"type": "string"}, "likely_cause": {"type": "string"}, "summary": {"type": "string"},
            "claims": {"type": "array", "items": _CLAIM}},
            "required": ["deploy_id", "likely_cause", "summary", "claims"]}},
        "actions": {"type": "array", "items": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": ["ticket", "rollback_proposal", "page"]},
            "target": {"type": "string"}, "reason": {"type": "string"}}, "required": ["kind", "target"]}},
        "abstain": {"type": "boolean"},
        "abstain_reason": {"type": "string"}},
        "required": ["hypotheses", "abstain"]}}}


def incident_brief(inc: dict, inv_id: str) -> str:
    return (f"Incident {inc['id']}: \"{inc['text']}\" on service {inc['service']} "
            f"(symptom: {inc['symptom']}, severity: {inc['severity']}). Investigation {inv_id}.")
