"""Check Groq tool calling end to end against the live graph.

Seeds nothing: builds a tiny throwaway graph, exposes one as-of blast-radius tool,
and lets the model call it. Run:  uv run python scripts/llm_smoke.py
"""

import json
import sys

from scripts.capability_check import FIXTURE
from tracebrain import db, llm

GRAPH = "smoke"

BLAST = ("MATCH p = (up:Service)-[:DEPENDS_ON*1..5]->(f:Service {name: $svc}) "
         "WHERE all(r IN relationships(p) WHERE r.valid_from <= $t AND r.valid_to > $t) "
         "WITH up, min(length(p)) AS hops RETURN up.name AS service, hops ORDER BY hops")

TOOLS = [{
    "type": "function",
    "function": {
        "name": "blast_radius",
        "description": "Services that depend (directly or transitively) on `service` at time t.",
        "parameters": {
            "type": "object",
            "properties": {"service": {"type": "string"}, "t": {"type": "integer"}},
            "required": ["service", "t"],
        },
    },
}]


def main() -> int:
    g = db.client().select_graph(GRAPH)
    try:
        g.delete()
    except Exception:
        pass
    g.query(FIXTURE)
    try:
        messages = [
            {"role": "system", "content": "You are an SRE assistant. Use tools; never guess graph facts."},
            {"role": "user", "content": "At time t=50 the redis service failed. Which services are affected?"},
        ]
        for _ in range(4):
            r = llm.chat(messages, TOOLS)
            print(f"[{r.provider}/{r.model}] finish={r.finish_reason} usage={r.usage} cached={r.cached} {r.ms}ms")
            messages.append(r.assistant_message())
            if not r.tool_calls:
                print("\nFINAL:", r.content)
                return 0
            for call in r.tool_calls:
                result = db.rows(g.ro_query(BLAST, {"svc": call.arguments["service"], "t": call.arguments["t"]}))
                print(f"  tool {call.name}({json.dumps(call.arguments)}) -> {result}")
                messages.append(llm.tool_result_message(call, result))
        print("no final answer after 4 turns")
        return 1
    finally:
        g.delete()


if __name__ == "__main__":
    print("providers with keys:", [p.name for p in llm.available_providers()])
    sys.exit(main())
