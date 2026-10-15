"""FalkorDB access. One graph per tenant; agent-reachable reads go through ro_query."""

from functools import lru_cache
from typing import Any

from falkordb import FalkorDB, Graph

from tracebrain import config


@lru_cache(maxsize=1)
def client() -> FalkorDB:
    return FalkorDB(host=config.FALKOR_HOST, port=config.FALKOR_PORT)


def graph_name(tenant: str) -> str:
    return f"tenant_{tenant}"


def graph_for(tenant: str) -> Graph:
    return client().select_graph(graph_name(tenant))


def _column_names(header) -> list[str]:
    # falkordb-py returns header entries as [type, name]; tolerate plain names too.
    return [h[1] if isinstance(h, (list, tuple)) else h for h in header]


def rows(result) -> list[dict[str, Any]]:
    names = _column_names(result.header)
    return [dict(zip(names, row)) for row in result.result_set]


def read(tenant: str, query: str, params: dict | None = None) -> list[dict[str, Any]]:
    """Read-only query. FalkorDB rejects any write inside ro_query."""
    return rows(graph_for(tenant).ro_query(query, params))


def write(tenant: str, query: str, params: dict | None = None) -> list[dict[str, Any]]:
    """Write query. Only memory modules, ingestion and the review endpoint may call this."""
    return rows(graph_for(tenant).query(query, params))


def ping() -> bool:
    return bool(client().connection.ping())
