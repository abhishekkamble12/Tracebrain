"""Connector contract: every source of graph data (synthetic, OTel traces, git, CODEOWNERS,
RCAEval, postmortems) yields these records. ingest() turns them into MERGE upserts."""

from dataclasses import dataclass, field
from typing import Iterable, Protocol

from tracebrain.config import FOREVER


@dataclass(frozen=True)
class ServiceRec:
    name: str
    tier: str = "core"            # frontend | core | data
    service_type: str = "grpc"    # http | grpc | cache | db | queue


@dataclass(frozen=True)
class DependencyRec:
    src: str                      # caller
    dst: str                      # callee
    valid_from: int
    valid_to: int = FOREVER


@dataclass(frozen=True)
class OwnershipRec:
    team: str
    service: str
    people: tuple[str, ...] = ()
    valid_from: int = 0
    valid_to: int = FOREVER


@dataclass(frozen=True)
class DeployRec:
    id: str
    service: str
    ts: int
    change_size: int
    kind: str                     # code | config | flag
    author: str
    summary: str                  # neutral wording: must never name the injected cause


@dataclass(frozen=True)
class IncidentRec:
    id: str
    ts: int
    service: str                  # where the alert fired
    symptom: str                  # latency | error_rate | timeout | oom | crashloop | saturation
    text: str
    severity: str = "sev2"
    labels: dict = field(default_factory=dict, compare=False)


class Connector(Protocol):
    name: str

    def services(self) -> Iterable[ServiceRec]: ...
    def dependencies(self) -> Iterable[DependencyRec]: ...
    def ownership(self) -> Iterable[OwnershipRec]: ...
    def deploys(self, since: int, until: int) -> Iterable[DeployRec]: ...
    def incidents(self) -> Iterable[IncidentRec]: ...
