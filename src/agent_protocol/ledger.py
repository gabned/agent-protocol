"""Strict, append-only lifecycle replay. Authentication belongs to the host.

An authenticated host supplies the complete Git ancestry and verifies each commit
signature against the accepted host signer registry before calling replay. A JSON
digest is an integrity check only, never an identity or authority assertion.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def exact(value, fields, name):
    require(
        isinstance(value, dict) and set(value) == set(fields.split()),
        "Unknown or missing " + name + " fields",
    )
    return value


def sha(value):
    require(
        isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value), "Exact Git SHA required"
    )
    return value


IDENTITY = "repository repository_id pr branch workstream workstream_class origin_owner"
EVENT = (
    "schema operation_id request_sha256 operation actor expected_previous "
    "expected_head observed_at payload"
)
OPERATIONS = {
    "START",
    "INTERRUPT",
    "RESUME",
    "HANDOFF",
    "QUALIFY",
    "INTEGRATE",
    "RECONCILE",
    "CLOSE",
    "ABANDON",
    "REFRESH",
}


def validate_identity(value):
    exact(value, IDENTITY, "identity")
    require(
        re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value["repository"]),
        "Repository identity required",
    )
    require(
        type(value["repository_id"]) is int
        and value["repository_id"] > 0
        and type(value["pr"]) is int
        and value["pr"] > 0,
        "Stable remote identity required",
    )
    require(value["workstream_class"] in {"PROTOCOL", "PRODUCT"}, "Unknown workstream class")
    for key in ("branch", "workstream", "origin_owner"):
        require(
            isinstance(value[key], str) and value[key] and all(ord(c) >= 32 for c in value[key]),
            "Invalid identity field",
        )


def replay(rows, *, identity, authenticated_commits):
    """Derive one current state from a complete independently authenticated chain.

    authenticated_commits is selected by the host's accepted signer verifier,
    never copied from candidate event fields. Each value identifies the principal
    authenticated by that commit's signature. Empty history means not started.
    """
    validate_identity(identity)
    require(
        isinstance(rows, list) and isinstance(authenticated_commits, dict),
        "Complete history required",
    )
    require(
        set(authenticated_commits) == {r.get("commit") for r in rows},
        "Incomplete authenticated history",
    )
    state = {
        "identity": deepcopy(identity),
        "status": "NEW",
        "owner": identity["origin_owner"],
        "tip": None,
        "head": None,
        "coordinates": None,
        "qualification": None,
        "merge": None,
        "events": [],
        "operations": {},
    }
    for row in rows:
        exact(row, "commit parents event", "history row")
        commit = sha(row["commit"])
        require(
            row["parents"] == ([] if state["tip"] is None else [state["tip"]]),
            "Incomplete, reordered, merged or rewritten ledger history",
        )
        event = exact(row["event"], EVENT, "event")
        require(event["schema"] == "agent-lifecycle-event/v2", "Unknown event schema")
        require(event["operation"] in OPERATIONS, "Unknown lifecycle operation")
        require(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}", event["operation_id"]),
            "Stable operation identity required",
        )
        require(event["operation_id"] not in state["operations"], "Duplicated operation in history")
        require(
            isinstance(event["request_sha256"], str)
            and re.fullmatch(r"[0-9a-f]{64}", event["request_sha256"]),
            "Request identity missing",
        )
        require(event["expected_previous"] == state["tip"], "Expected ledger head mismatch")
        require(
            event["actor"] == authenticated_commits[commit],
            "Actor differs from authenticated signer",
        )
        require(
            re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", event["observed_at"]),
            "UTC event time required",
        )
        apply(state, event)
        state["tip"] = commit
        state["operations"][event["operation_id"]] = deepcopy(event)
        state["events"].append({"commit": commit, "event": deepcopy(event)})
    return state


def apply(state, event):
    """Apply a previously authenticated event, preserving failures and identities."""
    operation, payload = event["operation"], event["payload"]
    require(state["status"] not in {"CLOSED", "ABANDONED"}, "Terminal ledger cannot reopen")
    require(event["actor"] == state["owner"], "Only the current authenticated owner can transition")
    sha(event["expected_head"])
    if operation == "START":
        require(state["status"] == "NEW", "Workstream already started")
        exact(payload, "identity coordinates policy capabilities", "start")
        require(payload["identity"] == state["identity"], "Origin identity changed")
        state.update(
            status="ACTIVE",
            head=event["expected_head"],
            coordinates=deepcopy(payload["coordinates"]),
            policy=payload["policy"],
            capabilities=deepcopy(payload["capabilities"]),
        )
        return
    require(state["status"] != "NEW", "First event must be START")
    if operation == "REFRESH":
        require(
            state["status"] in {"ACTIVE", "INTERRUPTED", "QUALIFIED"}, "Cannot refresh this state"
        )
        exact(payload, "previous_head coordinates", "refresh")
        require(payload["previous_head"] == state["head"], "Refresh lost prior candidate identity")
        require(payload["coordinates"] != state["coordinates"], "Unchanged refresh is not progress")
        state.update(
            head=event["expected_head"],
            coordinates=deepcopy(payload["coordinates"]),
            qualification=None,
            status="INTERRUPTED" if state["status"] == "INTERRUPTED" else "ACTIVE",
        )
        return
    require(event["expected_head"] == state["head"], "Unexpected candidate head")
    if operation == "INTERRUPT":
        exact(payload, "reason material", "interrupt")
        require(
            state["status"] in {"ACTIVE", "QUALIFIED"}
            and payload["reason"]
            and payload["material"],
            "Interruption requires durable material",
        )
        state["status"] = "INTERRUPTED"
        state["qualification"] = None
    elif operation == "RESUME":
        exact(payload, "restoration", "resume")
        require(
            state["status"] == "INTERRUPTED" and payload["restoration"],
            "Verified restoration required",
        )
        state["status"] = "ACTIVE"
    elif operation == "HANDOFF":
        exact(payload, "new_owner authorization material", "handoff")
        require(
            state["status"] == "INTERRUPTED"
            and payload["new_owner"] != state["owner"]
            and payload["authorization"]
            and payload["material"],
            "Authorized interrupted handoff required",
        )
        state["owner"] = payload["new_owner"]
    elif operation == "QUALIFY":
        exact(payload, "result coordinates evidence", "qualification")
        require(
            state["status"] in {"ACTIVE", "QUALIFIED"} and payload["result"] in {"PASS", "FAIL"},
            "Invalid qualification state/result",
        )
        require(payload["coordinates"] == state["coordinates"], "Qualification coordinates changed")
        require(payload["evidence"], "Qualification evidence required")
        state["qualification"] = deepcopy(payload)
        state["status"] = "QUALIFIED" if payload["result"] == "PASS" else "ACTIVE"
    elif operation == "INTEGRATE":
        exact(payload, "qualification_operation expected_base", "integration intent")
        require(
            state["status"] == "QUALIFIED" and state["qualification"]["result"] == "PASS",
            "Exact candidate qualification required",
        )
        prior = state["operations"].get(payload["qualification_operation"], {})
        require(
            prior.get("operation") == "QUALIFY" and prior.get("payload") == state["qualification"],
            "Integration must reference its actual qualification",
        )
        state["status"] = "INTEGRATING"
    elif operation == "RECONCILE":
        exact(payload, "merge_sha base_sha head_sha tree_sha", "merge observation")
        require(
            state["status"] == "INTEGRATING" and payload["head_sha"] == state["head"],
            "Actual merge must bind the intended candidate",
        )
        for value in payload.values():
            sha(value)
        state.update(status="INTEGRATED", merge=deepcopy(payload))
    elif operation == "CLOSE":
        exact(payload, "post_merge_evidence next_action next_location", "closure")
        require(
            state["status"] == "INTEGRATED" and all(payload.values()),
            "Verified delivery and next action required",
        )
        state["status"] = "CLOSED"
    elif operation == "ABANDON":
        exact(payload, "reason material authorization", "abandonment")
        require(
            state["status"] in {"ACTIVE", "INTERRUPTED", "QUALIFIED"} and all(payload.values()),
            "Abandonment cannot hide an uncertain integration",
        )
        state["status"] = "ABANDONED"
