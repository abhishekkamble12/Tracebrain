"""FalkorDB access. One graph per tenant; agent-reachable reads go through ro_query."""

import threading
import time
import uuid
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Iterator

from falkordb import FalkorDB, Graph
from redis.exceptions import ResponseError

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


_copy_lock = threading.Lock()  # GRAPH.COPY forks the server, and concurrent forks fail: one at a time


@contextmanager
def sandbox(tenant: str, tag: str = "sandbox") -> Iterator[str]:
    """A throwaway copy of the tenant's graph (GRAPH.COPY). Yields a tenant name usable with read/write;
    the copy is deleted on exit. The live graph is never touched."""
    suffix = f"__{tag}_{uuid.uuid4().hex[:6]}"
    for attempt in range(4):  # another process (or a BGSAVE) may still be forking: retry with backoff
        try:
            with _copy_lock:
                graph_for(tenant).copy(graph_name(tenant + suffix))
            break
        except Exception:
            if attempt == 3:
                raise
            time.sleep(0.5 * (attempt + 1))
    try:
        yield tenant + suffix
    finally:
        graph_for(tenant + suffix).delete()


class NotFalkorDB(RuntimeError):
    """The configured server answers but has no graph module (usually another Redis on that port)."""


def ping() -> bool:
    """True when FalkorDB answers. Raises NotFalkorDB for a plain Redis, so callers fail with a clear
    message instead of 'unknown command GRAPH.*' deep inside a query."""
    c = client()
    c.connection.ping()
    try:
        c.list_graphs()
    except ResponseError as e:
        if "unknown command" in str(e).lower():
            raise NotFalkorDB(
                f"{config.FALKOR_HOST}:{config.FALKOR_PORT} is a Redis server without the FalkorDB graph module "
                "(another Redis on that port?). Start FalkorDB with `docker compose up -d` and set FALKOR_PORT "
                "in .env to the port it publishes.") from e
        raise
    return True
