"""Synthetic connector: an Online Boutique-shaped system with injected incidents and known causes.

Everything is seeded and deterministic. Ground truth (culprit deploy, cause) lives only in
`SyntheticWorld.truth`, never in records the graph or agents can see; deploy summaries and
incident texts come from neutral templates, and `leakage_violations()` checks that.

Timeline (56 days from T0):
- day 24: frontend and checkout move from `currency` to `currency-v2` (topology change)
- day 36: `payment` ownership transfers to another team (ownership change)
- day 44: `recommendation` starts calling `ad`
Incidents are 2 days apart, each in an 08:00-20:00 slot, so 24h look-back windows never overlap.
"""

import random
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from tracebrain.config import FOREVER
from tracebrain.connectors.base import DependencyRec, DeployRec, IncidentRec, OwnershipRec, ServiceRec

DAY = 86400
HOUR = 3600
T0 = int(datetime(2026, 8, 1, tzinfo=timezone.utc).timestamp())
DAYS = 56
WINDOW = 24 * HOUR
CURRENCY_SWITCH_DAY = 24
OWNERSHIP_TRANSFER_DAY = 36
RECO_AD_DAY = 44

SERVICES = [
    ServiceRec("frontend", "frontend", "http"),
    ServiceRec("checkout", "core", "grpc"),
    ServiceRec("cart", "core", "grpc"),
    ServiceRec("productcatalog", "core", "grpc"),
    ServiceRec("currency", "core", "grpc"),
    ServiceRec("currency-v2", "core", "grpc"),
    ServiceRec("payment", "core", "grpc"),
    ServiceRec("shipping", "core", "grpc"),
    ServiceRec("email", "core", "grpc"),
    ServiceRec("recommendation", "core", "grpc"),
    ServiceRec("ad", "core", "grpc"),
    ServiceRec("redis-cart", "data", "cache"),
]
SERVICE_NAMES = [s.name for s in SERVICES]


def _dependencies() -> list[DependencyRec]:
    switch = T0 + CURRENCY_SWITCH_DAY * DAY
    reco_ad = T0 + RECO_AD_DAY * DAY
    static = [
        ("frontend", "productcatalog"), ("frontend", "cart"), ("frontend", "recommendation"),
        ("frontend", "shipping"), ("frontend", "checkout"), ("frontend", "ad"),
        ("checkout", "productcatalog"), ("checkout", "shipping"), ("checkout", "payment"),
        ("checkout", "email"), ("checkout", "cart"),
        ("cart", "redis-cart"), ("recommendation", "productcatalog"),
    ]
    deps = [DependencyRec(a, b, 0, FOREVER) for a, b in static]
    for caller in ("frontend", "checkout"):
        deps.append(DependencyRec(caller, "currency", 0, switch))
        deps.append(DependencyRec(caller, "currency-v2", switch, FOREVER))
    deps.append(DependencyRec("recommendation", "ad", reco_ad, FOREVER))
    return deps


DEPENDENCIES = _dependencies()

# Per-tenant org: teams, people, initial ownership, and one ownership transfer.
TENANTS = {
    "payments": {
        "seed": 42,
        "teams": {"Checkout": ("asha", "vikram"), "Payments": ("meera", "rohan"),
                  "Storefront": ("li", "sam", "dev")},
        "owns": {"checkout": "Checkout", "cart": "Checkout", "redis-cart": "Checkout",
                 "payment": "Payments", "currency": "Payments", "currency-v2": "Payments",
                 "frontend": "Storefront", "productcatalog": "Storefront", "recommendation": "Storefront",
                 "ad": "Storefront", "shipping": "Storefront", "email": "Storefront"},
        "transfer": ("payment", "Checkout"),
    },
    "platform": {
        "seed": 7,
        "teams": {"Platform": ("noor", "arjun"), "Data": ("kenji", "priya"), "Web": ("omar", "tara", "zoe")},
        "owns": {"redis-cart": "Platform", "cart": "Platform", "productcatalog": "Platform",
                 "shipping": "Platform", "email": "Platform", "recommendation": "Data", "ad": "Data",
                 "currency": "Data", "currency-v2": "Data", "frontend": "Web", "checkout": "Web",
                 "payment": "Web"},
        "transfer": ("payment", "Platform"),
    },
}

# Incident templates: where the alert fires, where the injected change lands, and the hidden cause.
TEMPLATES = [
    {"type": "timeout", "alert": "checkout", "culprit": "redis-cart", "kind": "config",
     "cause": "connection_pool_exhaustion", "text": "checkout requests timing out"},
    {"type": "error_rate", "alert": "frontend", "culprit": "currency", "kind": "code",
     "cause": "currency_conversion_bug", "text": "frontend 5xx error rate above threshold"},
    {"type": "latency", "alert": "checkout", "culprit": "productcatalog", "kind": "code",
     "cause": "n_plus_one_query", "text": "checkout p99 latency above SLO"},
    {"type": "crashloop", "alert": "payment", "culprit": "payment", "kind": "config",
     "cause": "missing_env_var", "text": "payment pods restarting repeatedly"},
    {"type": "oom", "alert": "recommendation", "culprit": "recommendation", "kind": "flag",
     "cause": "cache_size_flag", "text": "recommendation containers OOM-killed"},
    {"type": "saturation", "alert": "shipping", "culprit": "shipping", "kind": "code",
     "cause": "retry_storm", "text": "shipping worker saturation"},
]
OCCURRENCES = 4
# No-deploy incidents (external cause): alerts on leaf services with no dependencies.
ABSTAIN = [
    {"type": "latency", "alert": "ad", "text": "ad service latency elevated", "day": 51},
    {"type": "latency", "alert": "email", "text": "email send latency elevated", "day": 54},
]
SUMMARY = {"code": "release {svc} build {n}", "config": "update {svc} configuration", "flag": "toggle flag on {svc}"}
# Words that would hint at the answer if they appeared in agent-visible text.
LEAK_WORDS = ("culprit", "root cause", "broken", "bad ", "faulty", "injected")


# --------------------------------------------------------------------------- topology helpers (pure Python)

def deps_at(t: int) -> list[tuple[str, str]]:
    return [(d.src, d.dst) for d in DEPENDENCIES if d.valid_from <= t < d.valid_to]


def blast_radius_at(svc: str, t: int, max_hops: int = 5) -> dict[str, int]:
    """Callers of `svc` (transitively) at time t -> min hops. Independent of the Cypher version."""
    callers: dict[str, list[str]] = {}
    for a, b in deps_at(t):
        callers.setdefault(b, []).append(a)
    return _bfs(svc, callers, max_hops)


def closure_at(svc: str, t: int, max_hops: int = 3) -> dict[str, int]:
    """`svc` plus everything it depends on (transitively) at time t -> min hops."""
    callees: dict[str, list[str]] = {}
    for a, b in deps_at(t):
        callees.setdefault(a, []).append(b)
    return {svc: 0, **_bfs(svc, callees, max_hops)}


def _bfs(start: str, adj: dict[str, list[str]], max_hops: int) -> dict[str, int]:
    seen: dict[str, int] = {}
    q = deque([(start, 0)])
    while q:
        node, h = q.popleft()
        if h == max_hops:
            continue
        for nxt in adj.get(node, []):
            if nxt != start and nxt not in seen:
                seen[nxt] = h + 1
                q.append((nxt, h + 1))
    return seen


# --------------------------------------------------------------------------- world

@dataclass
class SyntheticWorld:
    tenant: str
    ownership: list[OwnershipRec]
    deploys: list[DeployRec]
    incidents: list[IncidentRec]
    truth: dict[str, dict] = field(default_factory=dict)  # incident id -> hidden ground truth


def _owner_at(tenant_cfg: dict, svc: str, t: int) -> str:
    moved, new_team = tenant_cfg["transfer"]
    if svc == moved and t >= T0 + OWNERSHIP_TRANSFER_DAY * DAY:
        return new_team
    return tenant_cfg["owns"][svc]


def _ownership(tenant_cfg: dict) -> list[OwnershipRec]:
    teams = tenant_cfg["teams"]
    moved, new_team = tenant_cfg["transfer"]
    at = T0 + OWNERSHIP_TRANSFER_DAY * DAY
    recs = []
    for svc, team in tenant_cfg["owns"].items():
        if svc == moved:
            recs.append(OwnershipRec(team, svc, teams[team], 0, at))
            recs.append(OwnershipRec(new_team, svc, teams[new_team], at, FOREVER))
        else:
            recs.append(OwnershipRec(team, svc, teams[team], 0, FOREVER))
    return recs


def build_world(tenant: str) -> SyntheticWorld:
    cfg = TENANTS[tenant]
    rng = random.Random(cfg["seed"])
    raw_deploys: list[dict] = []
    raw_incidents: list[dict] = []

    def author(svc: str, t: int) -> str:
        return rng.choice(cfg["teams"][_owner_at(cfg, svc, t)])

    def deploy(svc: str, t: int, kind: str, size: int, role: str) -> dict:
        d = {"service": svc, "ts": t, "kind": kind, "change_size": size, "author": author(svc, t), "role": role}
        raw_deploys.append(d)
        return d

    # Templated incidents, interleaved so every type recurs across the timeline.
    slot = 0
    for occ in range(OCCURRENCES):
        for tpl in TEMPLATES:
            day = 2 + 2 * slot
            slot += 1
            t = T0 + day * DAY + rng.randint(8 * HOUR, 20 * HOUR)
            culprit_svc = tpl["culprit"]
            if culprit_svc == "currency" and t >= T0 + CURRENCY_SWITCH_DAY * DAY:
                culprit_svc = "currency-v2"
            closure = closure_at(tpl["alert"], t)
            assert culprit_svc in closure, (tpl, culprit_svc)

            c_ts = t - rng.randint(20 * 60, 6 * HOUR)
            size = rng.randint(2, 40) if tpl["kind"] != "code" else rng.randint(40, 600)
            culprit = deploy(culprit_svc, c_ts, tpl["kind"], size, "culprit")

            def before_or_after_culprit(p_newer: float) -> int:
                if rng.random() < p_newer:
                    return rng.randint(c_ts + 60, t - 60)
                return rng.randint(t - WINDOW + HOUR, c_ts - 60)

            # Caller decoy: usually NEWER than the culprit, on a caller of the alerted service
            # (or anywhere else if none). Traps "blame the latest deploy", but not always.
            callers = sorted(blast_radius_at(tpl["alert"], t))
            pool = callers or [s for s in SERVICE_NAMES if s not in (culprit_svc, tpl["alert"])]
            deploy(rng.choice(pool), before_or_after_culprit(0.45), "code", rng.randint(5, 800), "decoy_newer")
            # Reachable decoys on the dependency path (including the culprit's own service), sometimes
            # newer than the culprit: the graph narrows the field, ranking still has to pick.
            for _ in range(rng.randint(1, 2)):
                deploy(rng.choice(sorted(closure)), before_or_after_culprit(0.3), "code",
                       rng.randint(5, 300), "decoy_path")
            # Unrelated noise.
            for _ in range(rng.randint(0, 2)):
                svc = rng.choice([s for s in SERVICE_NAMES if s != culprit_svc])
                deploy(svc, rng.randint(t - WINDOW + 60, t - 60), rng.choice(["code", "config"]),
                       rng.randint(3, 500), "noise")

            raw_incidents.append({"ts": t, "service": tpl["alert"], "symptom": tpl["type"], "text": tpl["text"],
                                  "truth": {"type": tpl["type"], "culprit": culprit, "cause_key": tpl["cause"],
                                            "occurrence": occ + 1, "split": "seen" if occ == 0 else "test"}})

    # Abstention incidents: deploys only on services outside the alerted service's dependency closure.
    for ab in ABSTAIN:
        t = T0 + ab["day"] * DAY + rng.randint(8 * HOUR, 20 * HOUR)
        closure = closure_at(ab["alert"], t)
        pool = [s for s in SERVICE_NAMES if s not in closure]
        for _ in range(rng.randint(2, 3)):
            deploy(rng.choice(pool), rng.randint(t - WINDOW + 60, t - 60), "code", rng.randint(5, 500), "noise")
        raw_incidents.append({"ts": t, "service": ab["alert"], "symptom": ab["type"], "text": ab["text"],
                              "truth": {"type": "abstain", "culprit": None, "cause_key": None,
                                        "occurrence": 1, "split": "test"}})

    # Background deploys, kept out of every incident's look-back window.
    windows = [(i["ts"] - WINDOW - 2 * HOUR, i["ts"] + 2 * HOUR) for i in raw_incidents]
    for day in range(DAYS):
        for _ in range(4):
            t = T0 + day * DAY + rng.randint(0, DAY - 1)
            if any(lo <= t <= hi for lo, hi in windows):
                continue
            deploy(rng.choice(SERVICE_NAMES), t, rng.choices(["code", "config", "flag"], [6, 3, 1])[0],
                   rng.randint(2, 800), "background")

    # Stable ids in time order.
    raw_deploys.sort(key=lambda d: d["ts"])
    for n, d in enumerate(raw_deploys, 1):
        d["id"] = f"dep:{n:04d}"
    raw_incidents.sort(key=lambda i: i["ts"])

    deploys = [DeployRec(d["id"], d["service"], d["ts"], d["change_size"], d["kind"], d["author"],
                         SUMMARY[d["kind"]].format(svc=d["service"], n=1000 + int(d["id"][4:])))
               for d in raw_deploys]
    incidents, truth = [], {}
    for n, i in enumerate(raw_incidents, 1):
        iid = f"inc:{n:03d}"
        incidents.append(IncidentRec(iid, i["ts"], i["service"], i["symptom"], i["text"]))
        tr, c = i["truth"], i["truth"]["culprit"]
        truth[iid] = {
            "tenant": tenant, "type": tr["type"], "service": i["service"], "ts": i["ts"],
            "culprit_deploy": c["id"] if c else None, "culprit_service": c["service"] if c else None,
            "cause_key": tr["cause_key"], "occurrence": tr["occurrence"], "split": tr["split"],
            "blast_radius": sorted(blast_radius_at(i["service"], i["ts"])),
            "decoys": {d["id"]: d["role"] for d in raw_deploys
                       if d["role"].startswith("decoy") and i["ts"] - WINDOW <= d["ts"] <= i["ts"]},
        }
    return SyntheticWorld(tenant, _ownership(cfg), deploys, incidents, truth)


def leakage_violations(world: SyntheticWorld) -> list[str]:
    """Agent-visible text must never reveal the injected cause."""
    causes = {t["cause_key"].replace("_", " ") for t in world.truth.values() if t["cause_key"]}
    texts = [("deploy", d.id, d.summary) for d in world.deploys] + [("incident", i.id, i.text) for i in world.incidents]
    bad = []
    for kind, id_, text in texts:
        low = text.lower()
        for word in (*causes, *LEAK_WORDS):
            if word in low:
                bad.append(f"{kind} {id_}: '{word}' in {text!r}")
    return bad


class SyntheticConnector:
    name = "synthetic"

    def __init__(self, tenant: str):
        self.world = build_world(tenant)

    def services(self):
        return list(SERVICES)

    def dependencies(self):
        return list(DEPENDENCIES)

    def ownership(self):
        return list(self.world.ownership)

    def deploys(self, since: int, until: int):
        return [d for d in self.world.deploys if since <= d.ts <= until]

    def incidents(self):
        return list(self.world.incidents)
