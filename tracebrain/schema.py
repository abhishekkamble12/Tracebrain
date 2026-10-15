"""Create indexes for a tenant graph. Safe to run repeatedly."""

from tracebrain import db, queries


def apply(tenant: str) -> list[str]:
    created = []
    g = db.graph_for(tenant)
    for q in queries.INDEXES + queries.VECTOR_INDEXES:
        try:
            g.query(q)
            created.append(q)
        except Exception as e:
            if "already indexed" not in str(e).lower():
                raise
    return created


def drop(tenant: str) -> None:
    try:
        db.graph_for(tenant).delete()
    except Exception as e:
        if "empty key" not in str(e).lower() and "invalid graph" not in str(e).lower():
            raise
