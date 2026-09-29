"""Offline campaign view over local ledgers, with an independently accepted scope.

No repository discovery, networking or global operational checkpoint is created.
The public Core contains synthetic tests only. Private scope records stay private.
"""

from __future__ import annotations

from .ledger import digest, exact, replay, require, sha
from .lifecycle import freshness

DIMENSIONS = {"adoption", "migration", "cleanup", "native_conformance"}


def reconcile(scope, rows, *, accepted_scope_digest, release_revision, authenticate_ledger=None):
    """Only a separately bound host can authenticate history for completion claims.

    The JSON CLI has no such capability. The callback must verify every retained
    signature using independently accepted signer identities; it returns raw
    events plus that authentication map, never a caller-supplied completion flag.
    """
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
        claims = any(v in {"VERIFIED", "NOT_REQUIRED"} for v in row["dimensions"].values())
        if claims:
            require(callable(authenticate_ledger), "Authenticated ledger host required")
            exact(row["ledger"], "repository pr tip", "ledger reference")
            proof = authenticate_ledger(row["ledger"])
            exact(proof, "rows identity authenticated_commits", "authenticated journal proof")
            state = replay(**proof)
            require(
                state["status"] == "CLOSED"
                and state["qualification"]["result"] == "PASS"
                and state["identity"]["repository"] == name == row["ledger"]["repository"]
                and state["identity"]["repository_id"] == row["id"]
                and state["identity"]["pr"] == row["ledger"]["pr"]
                and state["tip"] == row["ledger"]["tip"]
                and state["owner"] == row["owner"]
                and state["coordinates"]["PIN"] == row["revision"] == release_revision,
                "Completion differs from authenticated closed journal identity",
            )
            claimed = {
                key: row[key]
                for key in ("repository", "id", "revision", "owner", "evidence", "dimensions")
            }
            closure = state["events"][-1]["event"]
            qualification = state["qualification"]
            gates = qualification["evidence"]
            require(
                {gate["gate"] for gate in gates} == set(state["policy"]["required_gates"])
                and len(gates) == len(state["policy"]["required_gates"])
                and all(
                    freshness(gate, state["coordinates"])
                    == {"state": "REUSABLE", "result": "PASS", "invalidators": []}
                    for gate in gates
                ),
                "Retained qualification is incomplete or contains failed evidence",
            )
            post = closure["payload"]["post_merge_evidence"]
            require(
                post["head"] == state["merge"]["merge_sha"]
                and post["result"] == "PASS"
                and post["complete"] is True,
                "Retained post-merge delivery failed or incomplete",
            )
            require(
                closure["operation"] == "CLOSE"
                and {"delivery": claimed} in closure["payload"]["post_merge_evidence"]["evidence"],
                "Delivery dimensions/evidence are absent from authenticated closure",
            )
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
