"""Load connector records into a tenant graph with idempotent MERGE upserts."""

from dataclasses import asdict, dataclass

from tracebrain import db, queries
from tracebrain.connectors.base import Connector

BATCH = 500


@dataclass
class IngestReport:
    services: int = 0
    dependencies: int = 0
    ownership: int = 0
    members: int = 0
    deploys: int = 0
    incidents: int = 0


def _upsert(tenant: str, query: str, rows: list[dict]) -> int:
    for i in range(0, len(rows), BATCH):
        db.write(tenant, query, {"rows": rows[i:i + BATCH]})
    return len(rows)


def ingest(tenant: str, *connectors: Connector, since: int = 0, until: int = 2**62) -> IngestReport:
    report = IngestReport()
    for c in connectors:
        # Services first: every other upsert MATCHes them.
        report.services += _upsert(tenant, queries.UPSERT_SERVICES, [asdict(s) for s in c.services()])
        report.dependencies += _upsert(tenant, queries.UPSERT_DEPENDENCIES, [asdict(d) for d in c.dependencies()])
        owns = list(c.ownership())
        report.ownership += _upsert(tenant, queries.UPSERT_OWNERSHIP,
                                    [{k: v for k, v in asdict(o).items() if k != "people"} for o in owns])
        members = {(o.team, h) for o in owns for h in o.people}
        report.members += _upsert(tenant, queries.UPSERT_MEMBERS,
                                  [{"team": t, "handle": h} for t, h in sorted(members)])
        report.deploys += _upsert(tenant, queries.UPSERT_DEPLOYS, [asdict(d) for d in c.deploys(since, until)])
        report.incidents += _upsert(tenant, queries.UPSERT_INCIDENTS,
                                    [{k: v for k, v in asdict(i).items() if k != "labels"} for i in c.incidents()])
    return report
