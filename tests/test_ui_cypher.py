"""The UI's "Show Cypher" drawer must show exactly the queries the backend runs."""

import importlib.util
from pathlib import Path

from tracebrain.tools import mcp_server

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_cypher_for_ui.py"


def _exporter():
    spec = importlib.util.spec_from_file_location("export_cypher_for_ui", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_generated_ui_cypher_is_up_to_date():
    mod = _exporter()
    assert mod.OUT.read_text(encoding="utf-8") == mod.render(), \
        "run: uv run python scripts/export_cypher_for_ui.py"


def test_every_mcp_tool_has_its_queries_listed():
    import anyio

    async def names():
        return {t.name for t in await mcp_server.server.list_tools()}

    assert anyio.run(names) == set(_exporter().TOOL_QUERIES)
