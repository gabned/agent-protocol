"""Offline campaign view over local ledgers, with an independently accepted scope.

No repository discovery, networking or global operational checkpoint is created.
The public Core contains synthetic tests only. Private scope records stay private.
"""

from __future__ import annotations

from .ledger import digest, exact, require, sha

DIMENSIONS = {"adoption", "migration", "cleanup", "native_conformance"}


def reconcile(scope, rows, *, accepted_scope_digest, release_revision):
    require(digest(scope) == accepted_scope_digest, "Scope lacks independent acceptance")
    exact(scope, "schema repositories", "audit scope")
    require(scope["schema"] == "agent-protocol-audit-scope/v2", "Unknown audit scope")
    sha(release_revision)
    identities = {}
    for record in scope["repositories"]:
        exact(record, "repository id role", "scope record")
        require(
            record["repository"] not in identities
            and type(record["id"]) is int
            and record["id"] > 0
            and record["role"] in {"CORE", "CONSUMER", "WORKSPACE"},
            "Ambiguous scope identity",
        )
        identities[record["repository"]] = record
    require(
        identities and len({r["id"] for r in identities.values()}) == len(identities),
        "Empty or repeated stable identities",
    )
    by_repo = {}
    for row in rows:
        exact(row, "repository id revision owner ledger evidence dimensions", "audit observation")
        name = row["repository"]
        require(
            name in identities and name not in by_repo and row["id"] == identities[name]["id"],
            "Unknown/recreated repository or duplicate observation",
        )
        require(set(row["dimensions"]) == DIMENSIONS, "Adoption/migration/cleanup must be distinct")
        for dimension, result in row["dimensions"].items():
            require(
                result in {"VERIFIED", "BLOCKED", "NOT_RUN", "NOT_REQUIRED"}, "Unknown audit result"
            )
            if result in {"VERIFIED", "NOT_REQUIRED"}:
                require(
                    row["evidence"].get(dimension) and row["ledger"], "Unsupported completion claim"
                )
        by_repo[name] = row
    consumers = [name for name, record in identities.items() if record["role"] == "CONSUMER"]
    complete = [
        name
        for name in consumers
        if name in by_repo
        and by_repo[name]["revision"] == release_revision
        and all(
            result in {"VERIFIED", "NOT_REQUIRED"}
            for result in by_repo[name]["dimensions"].values()
        )
    ]
    return {
        "schema": "agent-protocol-audit/v2",
        "authority": "DERIVED_VIEW_ONLY",
        "rollout": "COMPLETE" if consumers and len(complete) == len(consumers) else "PARTIAL",
        "accepted_revision": release_revision,
        "complete": len(complete),
        "denominator": len(consumers),
        "missing": sorted(set(identities) - set(by_repo)),
        "rows": rows,
        "costs": {"AI": "UNKNOWN", "CI": "UNKNOWN", "workspace": "UNKNOWN"},
    }
