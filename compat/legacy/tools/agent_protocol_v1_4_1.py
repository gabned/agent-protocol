#!/usr/bin/env python3
"""Offline auditable-continuation contracts for Agent Protocol v1.4.1."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, NoReturn

PROTOCOL_VERSION = "1.4.1"
CAMPAIGN_SCHEMA_VERSION = 2
HANDOFF_SCHEMA_VERSION = 2
LEGACY_PROTOCOL_VERSION = "1.4.0"
LEGACY_CAMPAIGN_SCHEMA_VERSION = 1
LIFECYCLE_SCHEMA_VERSION = "1.2"
CONFORMANCE_SCHEMA_VERSION = 1

SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
ISSUE_PATTERN = re.compile(r"#[1-9][0-9]*")
RUN_PATTERN = re.compile(r"run:[1-9][0-9]*")
DEPLOYMENT_PATTERN = re.compile(r"deployment:[1-9][0-9]*")
REPOSITORY_PATTERN = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
SLICE_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]+/S[0-9]{2,}")
STRICT_SEMVER_PATTERN = re.compile(
    r"(?:0|[1-9][0-9]*)[.](?:0|[1-9][0-9]*)[.](?:0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:[.][0-9A-Za-z-]+)*)?"
    r"(?:[+][0-9A-Za-z-]+(?:[.][0-9A-Za-z-]+)*)?"
)
OBSERVED_AT_PATTERN = re.compile(
    r"20[0-9]{2}-[01][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]Z"
)
EVENT_REF_PATTERN = re.compile(
    r"(?:#[1-9][0-9]*|[0-9a-f]{40}|run:[1-9][0-9]*|"
    r"deployment:[1-9][0-9]*|release:v(?:0|[1-9][0-9]*)[.]"
    r"(?:0|[1-9][0-9]*)[.](?:0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:[.][0-9A-Za-z-]+)*)?"
    r"(?:[+][0-9A-Za-z-]+(?:[.][0-9A-Za-z-]+)*)?)"
)

CAMPAIGN_MODES = {"SINGLE_SLICE", "RELEASE_TRAIN"}
CAMPAIGN_STATES = {
    "PLANNED",
    "ACTIVE",
    "WAITING_EVENT",
    "HUMAN_GATE",
    "BLOCKED",
    "COMPLETE",
}
WORKSTREAM_CLASSES = {"PRODUCT", "PROTOCOL"}
AUTHORITY_ENVELOPES = {
    "SOURCE_ONLY": 0,
    "THROUGH_MERGE": 1,
    "THROUGH_RELEASE": 2,
    "THROUGH_PRODUCTION_B": 3,
}
RISK_PROFILES = {
    "NO_PRODUCTION",
    "PUBLIC_ARTIFACT",
    "REVERSIBLE_PRODUCTION",
    "CRITICAL_PRODUCTION",
}
RELEASE_PROFILES = {
    "GITHUB_ARTIFACT",
    "CODE_ONLY_PRODUCTION_B",
    "DEPLOYMENT_LEVEL_C",
    "UPSTREAM_RELEASE_VERIFIED",
}
AUTO_CONTINUATION = {"SEQUENTIAL", "DISABLED"}
STOP_REASONS = {
    "NONE",
    "AUTHORITY_EXHAUSTED",
    "HUMAN_DECISION_REQUIRED",
    "LEVEL_C_AUTHORIZATION",
    "MATERIAL_RISK_CHANGED",
    "CRITICAL_UNKNOWN",
    "UNRESOLVED_FINDING",
    "SCOPE_CHANGE_REQUIRED",
    "PUBLICATION_NOT_AUTHORIZED",
    "GATE_FAILURE",
}
HUMAN_GATE_REASONS = {
    "AUTHORITY_EXHAUSTED",
    "HUMAN_DECISION_REQUIRED",
    "LEVEL_C_AUTHORIZATION",
    "MATERIAL_RISK_CHANGED",
    "SCOPE_CHANGE_REQUIRED",
    "PUBLICATION_NOT_AUTHORIZED",
}
BLOCKED_REASONS = {
    "MATERIAL_RISK_CHANGED",
    "CRITICAL_UNKNOWN",
    "UNRESOLVED_FINDING",
    "SCOPE_CHANGE_REQUIRED",
    "GATE_FAILURE",
}
SLICE_STATES = {"PLANNED", "ACTIVE", "MERGED", "BLOCKED", "CANCELLED"}
TERMINAL_SLICE_STATES = {"MERGED", "CANCELLED"}
PR_ROLES = {"OWNER", "CORRECTION"}
PR_STATES = {"OPEN", "MERGED", "CLOSED"}
PUBLICATION_STATES = {"UNPUBLISHED", "CANDIDATE", "PUBLISHED"}
UPSTREAM_STATES = {"NOT_APPLICABLE", "PENDING", "VERIFIED"}
CHECKPOINT_STATES = {"NOT_DUE", "DUE", "RECORDED"}
OBSERVED_EVENTS = {
    "INITIAL_AUTHORIZATION",
    "PR_OPENED",
    "PR_SYNCHRONIZED",
    "PR_CLOSED",
    "PR_MERGED",
    "SLICE_ISSUE_OPENED",
    "SLICE_CANCELLED",
    "GATES_PASSED",
    "GATES_FAILED",
    "RELEASE_CANDIDATE_MERGED",
    "RELEASE_PUBLISHED",
    "RELEASE_VERIFIED",
    "PRODUCTION_DEPLOYED",
    "PRODUCTION_VERIFIED",
    "UPSTREAM_RELEASE_VERIFIED",
}
PENDING_ACTIONS = {
    "START_NEXT_SLICE",
    "CONTINUE_ACTIVE_SLICE",
    "MERGE_ACTIVE_SLICE",
    "PREPARE_RELEASE",
    "PUBLISH_RELEASE",
    "VERIFY_RELEASE",
    "VERIFY_UPSTREAM_RELEASE",
    "DEPLOY_PRODUCTION_B",
    "DEPLOY_PRODUCTION_C",
    "VERIFY_PRODUCTION",
    "RECORD_CHECKPOINT",
    "WAIT_FOR_EVENT",
    "NO_ACTION",
}
ACTION_LEVEL = {
    "START_NEXT_SLICE": 0,
    "CONTINUE_ACTIVE_SLICE": 0,
    "MERGE_ACTIVE_SLICE": 1,
    "PREPARE_RELEASE": 1,
    "PUBLISH_RELEASE": 2,
    "VERIFY_RELEASE": 2,
    "VERIFY_UPSTREAM_RELEASE": 0,
    "DEPLOY_PRODUCTION_B": 3,
    "DEPLOY_PRODUCTION_C": 4,
    "VERIFY_PRODUCTION": 0,
    "RECORD_CHECKPOINT": 0,
}
NEXT_ACTION_TYPES = {
    "AUTO_CONTINUE",
    "WAIT_EVENT",
    "USER_ACTION_REQUIRED",
    "CAMPAIGN_COMPLETE",
}
HANDOFF_NEXT_ACTION_TYPES = {*NEXT_ACTION_TYPES, "RESUME_SESSION"}
HANDOFF_OUTCOMES = {
    "DELIVERED",
    "BLOCKED",
    "CAMPAIGN_COMPLETE",
    "RESUME_REQUIRED",
}
RESUME_REASONS = {"NONE", "SESSION_LIMIT"}
RELEASE_STATUSES = {
    "NOT_APPLICABLE",
    "TRAIN_ACTIVE",
    "UNPUBLISHED",
    "CANDIDATE",
    "PUBLISHED",
    "DEPLOYED",
    "UPSTREAM_VERIFIED",
}
RECEIPT_OPERATIONS = {"INITIALIZE", "SCHEMA_MIGRATION", "STATE_TRANSITION"}
GITHUB_EVENT_KINDS = {
    "ISSUE",
    "PULL_REQUEST",
    "COMMIT",
    "WORKFLOW_RUN",
    "RELEASE",
    "DEPLOYMENT",
}
GITHUB_EVENT_ACTIONS = {
    "ISSUE": {"OPENED", "UPDATED", "CLOSED"},
    "PULL_REQUEST": {"OPENED", "SYNCHRONIZED", "CLOSED", "MERGED"},
    "COMMIT": {"CREATED"},
    "WORKFLOW_RUN": {"COMPLETED"},
    "RELEASE": {"PUBLISHED"},
    "DEPLOYMENT": {"CREATED", "STATUS_SUCCEEDED"},
}
GITHUB_EVENT_CONCLUSIONS = {
    "NOT_APPLICABLE",
    "SUCCESS",
    "FAILURE",
    "CANCELLED",
    "TIMED_OUT",
    "ACTION_REQUIRED",
    "NEUTRAL",
    "SKIPPED",
    "STALE",
    "STARTUP_FAILURE",
    "UNKNOWN",
}
UNSUCCESSFUL_GITHUB_CONCLUSIONS = {
    "FAILURE",
    "CANCELLED",
    "TIMED_OUT",
    "ACTION_REQUIRED",
    "NEUTRAL",
    "SKIPPED",
    "STALE",
    "STARTUP_FAILURE",
}
LEGACY_SUCCESS_DEPENDENT_ACTIONS = {
    ("GATES_PASSED", "MERGE_ACTIVE_SLICE"),
    ("RELEASE_VERIFIED", "RECORD_CHECKPOINT"),
    ("PRODUCTION_VERIFIED", "RECORD_CHECKPOINT"),
}
STATE_MODELS = {"PR_LOCAL", "PERSISTENT_CHECKPOINT"}
HUMAN_BOUNDARIES = {"NONE", "LEVEL_C_AUTHORIZATION"}

REPOSITORY_PROFILES: dict[str, dict[str, Any]] = {
    "gabned/provelume": {
        "default_branch": "main",
        "release_profile": "GITHUB_ARTIFACT",
        "state_model": "PR_LOCAL",
        "authority_ceiling": "THROUGH_RELEASE",
        "risk_ceiling": "PUBLIC_ARTIFACT",
        "human_boundary": "NONE",
        "upstream_repository": "NONE",
        "allowed_risks": {"NO_PRODUCTION", "PUBLIC_ARTIFACT"},
    },
    "brickms/brickms": {
        "default_branch": "main",
        "release_profile": "CODE_ONLY_PRODUCTION_B",
        "state_model": "PERSISTENT_CHECKPOINT",
        "authority_ceiling": "THROUGH_PRODUCTION_B",
        "risk_ceiling": "REVERSIBLE_PRODUCTION",
        "human_boundary": "NONE",
        "upstream_repository": "NONE",
        "allowed_risks": {"NO_PRODUCTION", "REVERSIBLE_PRODUCTION"},
    },
    "maxithlon/maxithlon": {
        "default_branch": "master",
        "release_profile": "DEPLOYMENT_LEVEL_C",
        "state_model": "PERSISTENT_CHECKPOINT",
        "authority_ceiling": "THROUGH_PRODUCTION_B",
        "risk_ceiling": "CRITICAL_PRODUCTION",
        "human_boundary": "LEVEL_C_AUTHORIZATION",
        "upstream_repository": "NONE",
        "allowed_risks": {
            "NO_PRODUCTION",
            "REVERSIBLE_PRODUCTION",
            "CRITICAL_PRODUCTION",
        },
    },
    "gabned/provelume.com": {
        "default_branch": "main",
        "release_profile": "UPSTREAM_RELEASE_VERIFIED",
        "state_model": "PR_LOCAL",
        "authority_ceiling": "THROUGH_PRODUCTION_B",
        "risk_ceiling": "REVERSIBLE_PRODUCTION",
        "human_boundary": "NONE",
        "upstream_repository": "gabned/provelume",
        "allowed_risks": {"NO_PRODUCTION", "REVERSIBLE_PRODUCTION"},
    },
}

CAMPAIGN_KEYS = {
    "schema_version",
    "protocol_version",
    "repository",
    "campaign_id",
    "owner_issue",
    "campaign_mode",
    "campaign_state",
    "workstream_class",
    "authority_envelope",
    "risk_profile",
    "release_profile",
    "auto_continuation",
    "checkpoint",
    "idea_inbox",
    "train",
    "slices",
    "receipts",
    "observed_event",
    "observed_event_ref",
    "pending_action",
    "stop_reason",
    "next_action",
}
CHECKPOINT_KEYS = {"policy", "state", "reference"}
IDEA_INBOX_KEYS = {"mode", "scope", "items"}
TRAIN_KEYS = {
    "train_id",
    "target_version",
    "publication_state",
    "published_version",
    "candidate_build_sha",
    "deployed_build_sha",
    "published_build_sha",
    "upstream",
}
UPSTREAM_KEYS = {
    "repository",
    "published_version",
    "published_build_sha",
    "verification_state",
}
SLICE_KEYS = {"id", "state", "issue", "pull_requests"}
PULL_REQUEST_KEYS = {
    "sequence",
    "role",
    "pr",
    "state",
    "head_sha",
    "merge_sha",
}
PENDING_ACTION_KEYS = {"kind", "slice_id"}
NEXT_ACTION_KEYS = {"type", "summary", "prompt"}
LEGACY_GITHUB_EVENT_KEYS = {"kind", "action", "repository", "reference", "sha"}
GITHUB_EVENT_KEYS = {*LEGACY_GITHUB_EVENT_KEYS, "conclusion"}
RECEIPT_KEYS = {
    "sequence",
    "operation",
    "github_event",
    "previous_state_sha256",
    "successor_state_sha256",
    "previous_receipt_sha256",
    "idempotency_key",
    "receipt_sha256",
}
INITIALIZE_RECEIPT_KEYS = {*RECEIPT_KEYS, "initial_state"}
STATEFUL_RECEIPT_KEYS = {*RECEIPT_KEYS, "previous_state", "successor_state"}
HANDOFF_KEYS = {
    "schema_version",
    "protocol_version",
    "campaign_id",
    "campaign_sha256",
    "outcome",
    "delivered",
    "release_status",
    "resume_reason",
    "next_action_type",
    "next_action",
    "next_prompt",
    "human_report",
}
BUNDLE_KEYS = {"campaign", "handoff"}
CONFORMANCE_KEYS = {
    "schema_version",
    "protocol_version",
    "mode",
    "observed_at",
    "repositories",
    "ledger_regression",
}
CONFORMANCE_REPOSITORY_KEYS = {
    "repository",
    "default_branch",
    "observed_head_sha",
    "observation_source",
    "release_profile",
    "state_model",
    "authority_ceiling",
    "risk_ceiling",
    "human_boundary",
    "upstream_repository",
    "source_paths",
    "writes_performed",
}
LEDGER_REGRESSION_KEYS = {
    "repository",
    "slice_id",
    "owner_issue",
    "pull_requests",
}

GENESIS_STATE_SHA256 = hashlib.sha256(
    b"AGENT_DEVELOPMENT_PROTOCOL_CAMPAIGN_GENESIS\n"
).hexdigest()


class ContractError(ValueError):
    """Raised when connector-supplied protocol evidence is invalid."""


def fail(message: str) -> NoReturn:
    raise ContractError(message)


def exact_object(value: Any, label: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(f"{label} must be an object")
    if set(value) != keys:
        missing = sorted(keys - set(value))
        extra = sorted(set(value) - keys)
        fail(f"{label} keys mismatch; missing={missing}, extra={extra}")
    return value


def closed(value: Any, label: str, choices: set[str]) -> str:
    if not isinstance(value, str) or value not in choices:
        fail(f"{label} is outside its closed registry")
    return value


def one_line(value: Any, label: str, *, maximum: int = 500) -> str:
    if not isinstance(value, str) or not value.strip():
        fail(f"{label} must be non-empty text")
    if value != value.strip() or "\n" in value or "\r" in value:
        fail(f"{label} must be one trimmed line")
    if len(value) > maximum:
        fail(f"{label} is too long")
    return value


def issue(value: Any, label: str) -> str:
    if not isinstance(value, str) or ISSUE_PATTERN.fullmatch(value) is None:
        fail(f"{label} must be an exact issue or pull-request reference")
    return value


def issue_or_none(value: Any, label: str) -> str:
    if value == "NONE":
        return value
    return issue(value, label)


def sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA_PATTERN.fullmatch(value) is None:
        fail(f"{label} must be an exact lowercase SHA")
    return value


def sha_or_none(value: Any, label: str) -> str:
    if value == "NONE":
        return value
    return sha(value, label)


def sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        fail(f"{label} must be an exact lowercase SHA-256")
    return value


def repository(value: Any, label: str) -> str:
    if not isinstance(value, str) or REPOSITORY_PATTERN.fullmatch(value) is None:
        fail(f"{label} must be an exact owner/name repository")
    return value


def semver(value: Any, label: str) -> str:
    if not isinstance(value, str) or STRICT_SEMVER_PATTERN.fullmatch(value) is None:
        fail(f"{label} must be a semantic version without a v prefix")
    return value


def event_ref(value: Any) -> str:
    if not isinstance(value, str) or EVENT_REF_PATTERN.fullmatch(value) is None:
        fail("observed_event_ref must be an exact GitHub-bound reference")
    return value


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def object_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def campaign_state_payload(value: dict[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(item) for key, item in value.items() if key != "receipts"}


def campaign_state_sha256(value: dict[str, Any]) -> str:
    return object_sha256(campaign_state_payload(value))


def campaign_sha256(value: dict[str, Any]) -> str:
    return object_sha256(value)


def receipt_payload(value: dict[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(item) for key, item in value.items() if key != "receipt_sha256"}


def receipt_sha256(value: dict[str, Any]) -> str:
    return object_sha256(receipt_payload(value))


def receipt_idempotency_key(
    *,
    campaign_id: str,
    operation: str,
    github_event: dict[str, Any],
    previous_state_sha256: str,
    successor_state_sha256: str,
) -> str:
    return object_sha256(
        {
            "campaign_id": campaign_id,
            "github_event": github_event,
            "operation": operation,
            "previous_state_sha256": previous_state_sha256,
            "successor_state_sha256": successor_state_sha256,
        }
    )


def validate_checkpoint(value: Any) -> dict[str, Any]:
    checkpoint = exact_object(value, "checkpoint", CHECKPOINT_KEYS)
    if checkpoint["policy"] != "RELEASE_BOUNDARY":
        fail("checkpoint.policy must be RELEASE_BOUNDARY")
    state = closed(checkpoint["state"], "checkpoint.state", CHECKPOINT_STATES)
    reference = issue_or_none(checkpoint["reference"], "checkpoint.reference")
    if (state == "RECORDED") != (reference != "NONE"):
        fail("only a recorded release checkpoint may carry a reference")
    return checkpoint


def validate_idea_inbox(value: Any) -> dict[str, Any]:
    inbox = exact_object(value, "idea_inbox", IDEA_INBOX_KEYS)
    if inbox["mode"] != "GITHUB_ISSUES_ONLY":
        fail("idea_inbox.mode must be GITHUB_ISSUES_ONLY")
    if inbox["scope"] != "FROZEN_UNTIL_RELEASE_BOUNDARY":
        fail("active campaign scope must remain frozen until the release boundary")
    items = inbox["items"]
    if not isinstance(items, list):
        fail("idea_inbox.items must be a list")
    checked = [issue(item, "idea inbox item") for item in items]
    if len(checked) != len(set(checked)):
        fail("idea inbox items must be unique issue references")
    return inbox


def validate_upstream(value: Any) -> dict[str, Any]:
    upstream = exact_object(value, "train.upstream", UPSTREAM_KEYS)
    state = closed(
        upstream["verification_state"],
        "train.upstream.verification_state",
        UPSTREAM_STATES,
    )
    repo = upstream["repository"]
    version = upstream["published_version"]
    build = upstream["published_build_sha"]
    if state == "NOT_APPLICABLE":
        if {repo, version, build} != {"NONE"}:
            fail("a non-applicable upstream release must contain only NONE identities")
    elif state == "PENDING":
        repository(repo, "train.upstream.repository")
        if version != "NONE" or build != "NONE":
            fail("a pending upstream release cannot claim a published identity")
    else:
        repository(repo, "train.upstream.repository")
        semver(version, "train.upstream.published_version")
        sha(build, "train.upstream.published_build_sha")
    return upstream


def validate_train(value: Any, release_profile: str) -> dict[str, Any]:
    train = exact_object(value, "train", TRAIN_KEYS)
    train_id = one_line(train["train_id"], "train.train_id", maximum=100)
    target = semver(train["target_version"], "train.target_version")
    publication = closed(
        train["publication_state"],
        "train.publication_state",
        PUBLICATION_STATES,
    )
    published_version = train["published_version"]
    candidate = sha_or_none(train["candidate_build_sha"], "train.candidate_build_sha")
    deployed = sha_or_none(train["deployed_build_sha"], "train.deployed_build_sha")
    published = sha_or_none(train["published_build_sha"], "train.published_build_sha")
    if published_version != "NONE":
        semver(published_version, "train.published_version")
    identities = {target, published_version, candidate, deployed, published}
    if train_id in identities:
        fail("train identity must remain distinct from version and build identities")
    if publication == "UNPUBLISHED" and (
        published_version != "NONE"
        or candidate != "NONE"
        or published != "NONE"
    ):
        fail("an unpublished train cannot claim candidate or published identity")
    if publication == "CANDIDATE" and (
        candidate == "NONE" or published_version != "NONE" or published != "NONE"
    ):
        fail("a candidate train needs only an exact candidate build")
    if publication == "PUBLISHED" and (
        candidate == "NONE"
        or published_version != target
        or published == "NONE"
        or published != candidate
    ):
        fail("a published train must bind target, candidate and published build")
    upstream = validate_upstream(train["upstream"])
    if release_profile == "GITHUB_ARTIFACT":
        if deployed != "NONE" or upstream["verification_state"] != "NOT_APPLICABLE":
            fail("the GitHub artifact profile has no deployment or upstream identity")
    elif release_profile in {"CODE_ONLY_PRODUCTION_B", "DEPLOYMENT_LEVEL_C"}:
        if publication == "PUBLISHED":
            fail("deployment-only profiles cannot claim GitHub publication")
        if upstream["verification_state"] != "NOT_APPLICABLE":
            fail("a direct deployment profile has no upstream release identity")
    elif release_profile == "UPSTREAM_RELEASE_VERIFIED":
        if publication == "PUBLISHED":
            fail("the upstream-verified site profile cannot claim local publication")
        if upstream["verification_state"] == "NOT_APPLICABLE":
            fail("the upstream-verified profile requires an upstream release")
    if deployed != "NONE" and candidate == "NONE":
        fail("a deployed build requires an exact candidate build")
    if deployed != "NONE" and deployed != candidate:
        fail("the deployed build must equal the qualified candidate build")
    return train


def validate_pull_request_ledger(
    value: Any,
    *,
    label: str,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        fail(f"{label} must be a list")
    result: list[dict[str, Any]] = []
    seen_prs: set[str] = set()
    open_seen = False
    for index, raw in enumerate(value, start=1):
        entry = exact_object(raw, f"{label}[{index - 1}]", PULL_REQUEST_KEYS)
        if entry["sequence"] != index:
            fail("pull-request ledger sequences must be contiguous and ordered")
        role = closed(entry["role"], "pull-request ledger role", PR_ROLES)
        if (index == 1 and role != "OWNER") or (index > 1 and role != "CORRECTION"):
            fail("the ledger starts with OWNER and retains ordered CORRECTION entries")
        pr = issue(entry["pr"], "pull-request ledger PR")
        if pr in seen_prs:
            fail("pull-request ledger entries must be unique")
        seen_prs.add(pr)
        state = closed(entry["state"], "pull-request ledger state", PR_STATES)
        sha(entry["head_sha"], "pull-request ledger head_sha")
        merge = sha_or_none(entry["merge_sha"], "pull-request ledger merge_sha")
        if state == "MERGED" and merge == "NONE":
            fail("a merged ledger entry requires its exact merge SHA")
        if state != "MERGED" and merge != "NONE":
            fail("only a merged ledger entry may carry a merge SHA")
        if state == "OPEN":
            if open_seen or index != len(value):
                fail("only the final ledger entry may be open")
            open_seen = True
        result.append(entry)
    return result


def validate_pull_request_history(
    previous: Any,
    successor: Any,
    *,
    label: str,
) -> None:
    before = validate_pull_request_ledger(previous, label=f"{label}.previous")
    after = validate_pull_request_ledger(successor, label=f"{label}.successor")
    if len(after) < len(before) or len(after) > len(before) + 1:
        fail("pull-request ledger history must retain its exact prefix")
    if not before:
        if after and after[0]["state"] != "OPEN":
            fail("a new owner PR enters the ledger from its open event")
        return

    last_before = before[-1]
    if last_before["state"] == "OPEN":
        if len(after) != len(before) or after[:-1] != before[:-1]:
            fail("an open PR must be closed or merged before a correction is appended")
        last_after = after[-1]
        frozen = {"sequence", "role", "pr"}
        if any(last_after[key] != last_before[key] for key in frozen):
            fail("the current PR identity cannot overwrite ledger history")
        if (
            last_after["state"] != "OPEN"
            and last_after["head_sha"] != last_before["head_sha"]
        ):
            fail("a PR must record its final open head before becoming terminal")
        return

    if after[: len(before)] != before:
        fail("terminal PR ledger history is immutable")
    if len(after) == len(before) + 1 and after[-1]["state"] != "OPEN":
        fail("a correction PR enters the ledger from its open event")


def validate_slices(value: Any, mode: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        fail("slices must be a non-empty list")
    if mode == "SINGLE_SLICE" and len(value) != 1:
        fail("SINGLE_SLICE campaigns must contain exactly one slice")
    result: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    nonterminal_seen = False
    planned_seen = False
    active_like = 0
    open_prs = 0
    for index, raw in enumerate(value):
        item = exact_object(raw, f"slices[{index}]", SLICE_KEYS)
        identifier = one_line(item["id"], f"slices[{index}].id", maximum=100)
        if SLICE_ID_PATTERN.fullmatch(identifier) is None or identifier in identifiers:
            fail("slice ids must be unique train/SNN identifiers")
        identifiers.add(identifier)
        state = closed(item["state"], f"slices[{index}].state", SLICE_STATES)
        issue_ref = issue_or_none(item["issue"], f"slices[{index}].issue")
        ledger = validate_pull_request_ledger(
            item["pull_requests"],
            label=f"slices[{index}].pull_requests",
        )
        open_prs += sum(entry["state"] == "OPEN" for entry in ledger)
        if state in TERMINAL_SLICE_STATES:
            if nonterminal_seen:
                fail("terminal slices must form a strict campaign prefix")
        else:
            nonterminal_seen = True
        if state == "PLANNED":
            planned_seen = True
        elif state in {"ACTIVE", "BLOCKED"} and planned_seen:
            fail("the active or blocked slice must be the first nonterminal slice")
        if state in {"ACTIVE", "BLOCKED"}:
            active_like += 1
        if state == "PLANNED" and ledger:
            fail("planned slices cannot claim pull-request history")
        if state in {"ACTIVE", "BLOCKED"} and issue_ref == "NONE":
            fail("active or blocked slices require an exact owner issue")
        if state == "MERGED" and (
            issue_ref == "NONE" or not ledger or ledger[-1]["state"] != "MERGED"
        ):
            fail("merged slices require an issue and a terminal merged ledger entry")
        if state == "CANCELLED" and (
            issue_ref == "NONE" or any(entry["state"] != "CLOSED" for entry in ledger)
        ):
            fail("cancelled slices retain only closed pull-request history")
        result.append(item)
    if active_like > 1:
        fail("a campaign may have at most one active or blocked slice")
    if open_prs > 1:
        fail("a campaign may have at most one open owner or correction PR")
    return result


def validate_github_event(
    value: Any,
    *,
    allow_legacy: bool = False,
    allow_unknown_conclusion: bool = False,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail("github_event must be an object")
    if set(value) == LEGACY_GITHUB_EVENT_KEYS and allow_legacy:
        event = deepcopy(value)
        event["conclusion"] = (
            "UNKNOWN"
            if event.get("kind") == "WORKFLOW_RUN"
            or event.get("action") == "STATUS_SUCCEEDED"
            else "NOT_APPLICABLE"
        )
    else:
        event = exact_object(value, "github_event", GITHUB_EVENT_KEYS)
    kind = closed(event["kind"], "github_event.kind", GITHUB_EVENT_KINDS)
    action = closed(event["action"], "github_event.action", GITHUB_EVENT_ACTIONS[kind])
    conclusion = closed(
        event["conclusion"],
        "github_event.conclusion",
        GITHUB_EVENT_CONCLUSIONS,
    )
    repository(event["repository"], "github_event.repository")
    reference = one_line(event["reference"], "github_event.reference", maximum=120)
    event_sha = sha_or_none(event["sha"], "github_event.sha")
    if kind in {"ISSUE", "PULL_REQUEST"}:
        issue(reference, "github_event.reference")
        if kind == "ISSUE" and event_sha != "NONE":
            fail("an issue event does not carry a commit SHA")
        if kind == "PULL_REQUEST" and event_sha == "NONE":
            fail("a pull-request event requires an exact head or merge SHA")
    elif kind == "COMMIT":
        sha(reference, "github_event.reference")
        if event_sha != reference:
            fail("a commit event reference and SHA must match")
    elif kind == "WORKFLOW_RUN":
        if RUN_PATTERN.fullmatch(reference) is None or event_sha == "NONE":
            fail("a workflow event requires run:<id> and an exact head SHA")
        if conclusion == "UNKNOWN" and not allow_unknown_conclusion:
            fail("a workflow event requires its exact terminal conclusion")
        if conclusion in {"NOT_APPLICABLE", "UNKNOWN"} and not (
            conclusion == "UNKNOWN" and allow_unknown_conclusion
        ):
            fail("a completed workflow event requires a terminal conclusion")
    elif kind == "DEPLOYMENT":
        if DEPLOYMENT_PATTERN.fullmatch(reference) is None or event_sha == "NONE":
            fail("a deployment event requires deployment:<id> and an exact SHA")
        if action == "CREATED" and conclusion != "NOT_APPLICABLE":
            fail("a created deployment event has no terminal conclusion")
        if (
            action == "STATUS_SUCCEEDED"
            and conclusion != "SUCCESS"
            and not (conclusion == "UNKNOWN" and allow_unknown_conclusion)
        ):
            fail("a successful deployment status requires SUCCESS")
    else:
        if not reference.startswith("release:v"):
            fail("a release event requires release:v<semantic-version>")
        semver(reference.removeprefix("release:v"), "github_event release")
        if event_sha == "NONE":
            fail("a release event requires an exact published build SHA")
    if kind not in {"WORKFLOW_RUN", "DEPLOYMENT"} and conclusion != "NOT_APPLICABLE":
        fail("this GitHub event kind requires conclusion NOT_APPLICABLE")
    return event


def github_event_identity(value: dict[str, Any]) -> str:
    return object_sha256({key: value[key] for key in LEGACY_GITHUB_EVENT_KEYS})


def build_receipt(
    *,
    sequence: int,
    operation: str,
    campaign_id: str,
    github_event: dict[str, Any],
    previous_state_sha256: str,
    successor_state_sha256: str,
    previous_receipt_sha256: str,
    initial_state: dict[str, Any] | None = None,
    previous_state: dict[str, Any] | None = None,
    successor_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    closed(operation, "receipt.operation", RECEIPT_OPERATIONS)
    validate_github_event(
        github_event,
        allow_unknown_conclusion=operation == "SCHEMA_MIGRATION",
    )
    sha256(previous_state_sha256, "receipt.previous_state_sha256")
    sha256(successor_state_sha256, "receipt.successor_state_sha256")
    if previous_receipt_sha256 != "NONE":
        sha256(previous_receipt_sha256, "receipt.previous_receipt_sha256")
    receipt: dict[str, Any] = {
        "sequence": sequence,
        "operation": operation,
        "github_event": deepcopy(github_event),
        "previous_state_sha256": previous_state_sha256,
        "successor_state_sha256": successor_state_sha256,
        "previous_receipt_sha256": previous_receipt_sha256,
        "idempotency_key": receipt_idempotency_key(
            campaign_id=campaign_id,
            operation=operation,
            github_event=github_event,
            previous_state_sha256=previous_state_sha256,
            successor_state_sha256=successor_state_sha256,
        ),
        "receipt_sha256": "",
    }
    if operation == "INITIALIZE":
        if initial_state is None or previous_state is not None or successor_state is not None:
            fail("INITIALIZE requires its reconstructible initial state")
        snapshot = exact_object(
            initial_state,
            "receipt.initial_state",
            CAMPAIGN_KEYS - {"receipts"},
        )
        if object_sha256(snapshot) != successor_state_sha256:
            fail("INITIALIZE initial state does not match its successor digest")
        receipt["initial_state"] = deepcopy(snapshot)
    elif initial_state is not None:
        fail("only INITIALIZE may carry an initial state")
    elif operation == "STATE_TRANSITION":
        if previous_state is None or successor_state is None:
            fail("STATE_TRANSITION requires reconstructible state snapshots")
        before = exact_object(
            previous_state,
            "receipt.previous_state",
            CAMPAIGN_KEYS - {"receipts"},
        )
        after = exact_object(
            successor_state,
            "receipt.successor_state",
            CAMPAIGN_KEYS - {"receipts"},
        )
        if object_sha256(before) != previous_state_sha256:
            fail("receipt previous state does not match its predecessor digest")
        if object_sha256(after) != successor_state_sha256:
            fail("receipt successor state does not match its successor digest")
        receipt["previous_state"] = deepcopy(before)
        receipt["successor_state"] = deepcopy(after)
    elif operation == "SCHEMA_MIGRATION":
        if previous_state is None or successor_state is None:
            fail("SCHEMA_MIGRATION requires its exact source and result snapshots")
        if object_sha256(previous_state) != previous_state_sha256:
            fail("migration source does not match its predecessor digest")
        after = exact_object(
            successor_state,
            "receipt.successor_state",
            CAMPAIGN_KEYS - {"receipts"},
        )
        if object_sha256(after) != successor_state_sha256:
            fail("migration result does not match its successor digest")
        receipt["previous_state"] = deepcopy(previous_state)
        receipt["successor_state"] = deepcopy(after)
    elif previous_state is not None or successor_state is not None:
        fail("state snapshots must be supplied as one closed pair")
    receipt["receipt_sha256"] = receipt_sha256(receipt)
    return receipt


def find_pr_for_merge(slices: list[dict[str, Any]], merge_sha: str) -> str | None:
    matches = [
        entry["pr"]
        for item in slices
        for entry in item["pull_requests"]
        if entry["merge_sha"] == merge_sha
    ]
    return matches[0] if len(matches) == 1 else None


def validate_receipt_binding(
    campaign: dict[str, Any], receipt: dict[str, Any]
) -> None:
    if receipt["operation"] == "SCHEMA_MIGRATION":
        return
    github_event = validate_github_event(
        receipt["github_event"],
        allow_legacy=True,
    )
    observed = campaign["observed_event"]
    observed_ref = campaign["observed_event_ref"]
    repo = campaign["repository"]
    train = campaign["train"]
    if observed == "SLICE_ISSUE_OPENED":
        expected = ("ISSUE", "OPENED", repo, observed_ref, "NONE")
    elif (
        receipt["operation"] == "STATE_TRANSITION"
        and github_event["kind"] == "ISSUE"
        and github_event["action"] == "OPENED"
        and github_event["reference"] in campaign["idea_inbox"]["items"]
    ):
        expected = (
            "ISSUE",
            "OPENED",
            repo,
            github_event["reference"],
            "NONE",
        )
        observed_tuple = (
            github_event["kind"],
            github_event["action"],
            github_event["repository"],
            github_event["reference"],
            github_event["sha"],
        )
        if observed_tuple != expected:
            fail("the idea receipt is not bound to its exact GitHub issue event")
        return
    elif observed == "INITIAL_AUTHORIZATION":
        expected = ("ISSUE", "OPENED", repo, campaign["owner_issue"], "NONE")
    elif observed in {"PR_OPENED", "PR_SYNCHRONIZED"}:
        open_entries = [
            entry
            for item in campaign["slices"]
            for entry in item["pull_requests"]
            if entry["state"] == "OPEN" and entry["pr"] == observed_ref
        ]
        if len(open_entries) != 1:
            fail(f"{observed} must bind the one open ledger entry")
        action = "OPENED" if observed == "PR_OPENED" else "SYNCHRONIZED"
        expected = (
            "PULL_REQUEST",
            action,
            repo,
            observed_ref,
            open_entries[0]["head_sha"],
        )
    elif observed == "PR_CLOSED":
        closed_entries = [
            entry
            for item in campaign["slices"]
            for entry in item["pull_requests"]
            if entry["state"] == "CLOSED" and entry["pr"] == observed_ref
        ]
        if len(closed_entries) != 1:
            fail("PR_CLOSED must bind one retained closed ledger entry")
        expected = (
            "PULL_REQUEST",
            "CLOSED",
            repo,
            observed_ref,
            closed_entries[0]["head_sha"],
        )
    elif observed == "PR_MERGED":
        pr = find_pr_for_merge(campaign["slices"], observed_ref)
        if pr is None:
            fail("PR_MERGED must bind one retained ledger entry")
        expected = ("PULL_REQUEST", "MERGED", repo, pr, observed_ref)
    elif observed == "SLICE_CANCELLED":
        expected = ("ISSUE", "CLOSED", repo, observed_ref, "NONE")
    elif observed in {"GATES_PASSED", "GATES_FAILED"}:
        expected = (
            "WORKFLOW_RUN",
            "COMPLETED",
            repo,
            github_event["reference"],
            observed_ref,
        )
    elif observed == "RELEASE_CANDIDATE_MERGED":
        candidate = train["candidate_build_sha"]
        if observed_ref != candidate:
            fail("candidate qualification is not bound to the exact candidate build")
        expected = ("COMMIT", "CREATED", repo, candidate, candidate)
    elif observed == "RELEASE_PUBLISHED":
        expected = (
            "RELEASE",
            "PUBLISHED",
            repo,
            observed_ref,
            train["published_build_sha"],
        )
    elif observed == "RELEASE_VERIFIED":
        expected = (
            "WORKFLOW_RUN",
            "COMPLETED",
            repo,
            github_event["reference"],
            train["published_build_sha"],
        )
    elif observed == "UPSTREAM_RELEASE_VERIFIED":
        upstream = train["upstream"]
        release_ref = f"release:v{upstream['published_version']}"
        if observed_ref != release_ref:
            fail("upstream observed release reference does not match published_version")
        expected = (
            "RELEASE",
            "PUBLISHED",
            upstream["repository"],
            release_ref,
            upstream["published_build_sha"],
        )
    elif observed in {"PRODUCTION_DEPLOYED", "PRODUCTION_VERIFIED"}:
        kind = github_event["kind"]
        if kind == "WORKFLOW_RUN":
            action = "COMPLETED"
        elif kind == "DEPLOYMENT":
            action = "STATUS_SUCCEEDED"
        else:
            fail("production evidence requires a workflow run or deployment event")
        expected_sha = train["deployed_build_sha"]
        if observed_ref != expected_sha:
            action_name = (
                "deployment" if observed == "PRODUCTION_DEPLOYED" else "verification"
            )
            fail(f"production {action_name} is not bound to the exact deployed build")
        expected = (
            kind,
            action,
            repo,
            github_event["reference"],
            expected_sha,
        )
    else:
        fail("the observed event has no closed GitHub receipt binding")
    observed_tuple = (
        github_event["kind"],
        github_event["action"],
        github_event["repository"],
        github_event["reference"],
        github_event["sha"],
    )
    if observed_tuple != expected:
        fail("the receipt is not bound to its exact real GitHub event")
    if observed in {
        "GATES_PASSED",
        "RELEASE_VERIFIED",
        "PRODUCTION_DEPLOYED",
        "PRODUCTION_VERIFIED",
    } and github_event["conclusion"] != "SUCCESS":
        fail(f"{observed} requires a successful GitHub event conclusion")
    if (
        observed == "GATES_FAILED"
        and github_event["conclusion"] not in UNSUCCESSFUL_GITHUB_CONCLUSIONS
    ):
        fail("GATES_FAILED requires an unsuccessful GitHub event conclusion")


def validate_last_receipt_binding(campaign: dict[str, Any]) -> None:
    validate_receipt_binding(campaign, campaign["receipts"][-1])


def validate_receipts(campaign: dict[str, Any]) -> list[dict[str, Any]]:
    receipts = campaign["receipts"]
    if not isinstance(receipts, list) or not receipts:
        fail("a schema v2 campaign requires at least one transition receipt")
    previous_receipt = "NONE"
    previous_successor: str | None = None
    reconstructed: dict[str, Any] | None = None
    idempotency_keys: set[str] = set()
    github_events: set[str] = set()

    def snapshot_campaign(value: Any, label: str) -> dict[str, Any]:
        snapshot = exact_object(
            deepcopy(value),
            label,
            CAMPAIGN_KEYS - {"receipts"},
        )
        result = {**snapshot, "receipts": []}
        validate_campaign_v2(result, validate_receipt_chain=False)
        return result

    for index, raw in enumerate(receipts, start=1):
        if not isinstance(raw, dict):
            fail(f"receipts[{index - 1}] must be an object")
        operation_hint = raw.get("operation")
        if operation_hint == "INITIALIZE" and set(raw) == RECEIPT_KEYS:
            fail("INITIALIZE lacks its reconstructible initial state")
        stateful = set(raw) == STATEFUL_RECEIPT_KEYS
        if operation_hint == "INITIALIZE":
            expected_receipt_keys = INITIALIZE_RECEIPT_KEYS
        elif stateful:
            expected_receipt_keys = STATEFUL_RECEIPT_KEYS
        else:
            expected_receipt_keys = RECEIPT_KEYS
        item = exact_object(
            raw,
            f"receipts[{index - 1}]",
            expected_receipt_keys,
        )
        if item["sequence"] != index:
            fail("receipt sequences must be contiguous and append-only")
        operation = closed(item["operation"], "receipt.operation", RECEIPT_OPERATIONS)
        if index == 1 and operation not in {"INITIALIZE", "SCHEMA_MIGRATION"}:
            fail("the first receipt must initialize or migrate the campaign")
        if index > 1 and operation != "STATE_TRANSITION":
            fail("only state transitions may follow the first receipt")
        checked_event = validate_github_event(
            item["github_event"],
            allow_legacy=True,
            allow_unknown_conclusion=operation == "SCHEMA_MIGRATION",
        )
        event_identity = github_event_identity(checked_event)
        if event_identity in github_events:
            fail("a real GitHub event cannot be reused by another receipt")
        github_events.add(event_identity)
        previous_state = sha256(
            item["previous_state_sha256"],
            "receipt.previous_state_sha256",
        )
        successor_state = sha256(
            item["successor_state_sha256"],
            "receipt.successor_state_sha256",
        )
        if operation == "INITIALIZE" and previous_state != GENESIS_STATE_SHA256:
            fail("campaign initialization must start at the canonical genesis digest")
        if operation == "INITIALIZE":
            expected_event = (
                "ISSUE",
                "OPENED",
                campaign["repository"],
                campaign["owner_issue"],
                "NONE",
                "NOT_APPLICABLE",
            )
            observed_event = (
                checked_event["kind"],
                checked_event["action"],
                checked_event["repository"],
                checked_event["reference"],
                checked_event["sha"],
                checked_event["conclusion"],
            )
            if observed_event != expected_event:
                fail("campaign initialization requires the exact owner issue event")
            initial_state = exact_object(
                item["initial_state"],
                "receipt.initial_state",
                CAMPAIGN_KEYS - {"receipts"},
            )
            initial_campaign = {**deepcopy(initial_state), "receipts": []}
            validate_campaign_v2(initial_campaign, validate_receipt_chain=False)
            validate_initial_campaign_state(initial_campaign)
            if object_sha256(initial_state) != successor_state:
                fail("INITIALIZE initial state does not match its successor digest")
            if immutable_campaign_identity(
                initial_campaign
            ) != immutable_campaign_identity(campaign):
                fail("INITIALIZE identity does not match the enclosing campaign")
            if [entry["id"] for entry in initial_campaign["slices"]] != [
                entry["id"] for entry in campaign["slices"]
            ]:
                fail("INITIALIZE slice order does not match the enclosing campaign")
            for initial_slice, current_slice in zip(
                initial_campaign["slices"], campaign["slices"], strict=True
            ):
                if (
                    initial_slice["issue"] != "NONE"
                    and current_slice["issue"] != initial_slice["issue"]
                ):
                    fail("INITIALIZE retained slice issue was rewritten")
            reconstructed = initial_campaign
        elif operation == "SCHEMA_MIGRATION":
            if not stateful:
                fail("SCHEMA_MIGRATION requires its exact source and result snapshots")
            if object_sha256(item["previous_state"]) != previous_state:
                fail("migration source does not match its predecessor digest")
            legacy = load_legacy_module()
            try:
                legacy.validate_campaign(deepcopy(item["previous_state"]))
            except legacy.ContractError as exc:
                raise ContractError(f"migration source is invalid: {exc}") from exc
            reconstructed = snapshot_campaign(
                item["successor_state"],
                "receipt.successor_state",
            )
            expected_migration = migrate_campaign(
                deepcopy(item["previous_state"]),
                _validate_result=False,
            )
            if campaign_state_payload(expected_migration) != campaign_state_payload(
                reconstructed
            ):
                fail("migration result is not the deterministic schema 1 projection")
            expected_event = expected_migration["receipts"][0]["github_event"]
            if item["github_event"] != expected_event:
                fail("migration receipt is not bound to its inferred GitHub event")
            if campaign_state_sha256(reconstructed) != successor_state:
                fail("migration result does not match its successor digest")
        else:
            if stateful:
                before = snapshot_campaign(
                    item["previous_state"],
                    "receipt.previous_state",
                )
                after = snapshot_campaign(
                    item["successor_state"],
                    "receipt.successor_state",
                )
            else:
                if reconstructed is None:
                    fail("legacy transition predecessor state cannot be reconstructed")
                if index == len(receipts):
                    successor_snapshot = campaign_state_payload(campaign)
                elif (
                    isinstance(receipts[index], dict)
                    and set(receipts[index]) == STATEFUL_RECEIPT_KEYS
                ):
                    successor_snapshot = receipts[index]["previous_state"]
                else:
                    fail(
                        "legacy intermediate transition lacks reconstructible "
                        "state snapshots"
                    )
                before = reconstructed
                after = snapshot_campaign(
                    successor_snapshot,
                    "reconstructed legacy successor state",
                )
            if campaign_state_sha256(before) != previous_state:
                fail("receipt snapshot does not match its predecessor digest")
            if campaign_state_sha256(after) != successor_state:
                fail("receipt snapshot does not match its successor digest")
            if (
                reconstructed is not None
                and campaign_state_payload(before)
                != campaign_state_payload(reconstructed)
            ):
                fail("adjacent receipt state snapshots do not chain")
            validate_transition_pair(before, after, checked_event)
            validate_receipt_binding(after, item)
            reconstructed = after
        if previous_successor is not None and previous_state != previous_successor:
            fail("receipt predecessor/successor state digests do not chain")
        if item["previous_receipt_sha256"] != previous_receipt:
            fail("receipt hashes do not form an append-only chain")
        expected_key = receipt_idempotency_key(
            campaign_id=campaign["campaign_id"],
            operation=operation,
            github_event=item["github_event"],
            previous_state_sha256=previous_state,
            successor_state_sha256=successor_state,
        )
        if item["idempotency_key"] != expected_key:
            fail("receipt idempotency key does not match its exact transition")
        if expected_key in idempotency_keys:
            fail("a GitHub transition receipt cannot be appended twice")
        idempotency_keys.add(expected_key)
        observed_receipt_sha = sha256(item["receipt_sha256"], "receipt.receipt_sha256")
        if observed_receipt_sha != receipt_sha256(item):
            fail("receipt_sha256 does not match the canonical receipt")
        previous_receipt = observed_receipt_sha
        previous_successor = successor_state
    if previous_successor != campaign_state_sha256(campaign):
        fail("the last receipt successor digest does not match campaign state")
    if (
        reconstructed is None
        or campaign_state_payload(reconstructed) != campaign_state_payload(campaign)
    ):
        fail("the reconstructed receipt chain does not match campaign state")
    validate_last_receipt_binding(campaign)
    return receipts


def validate_initial_campaign_state(campaign: dict[str, Any]) -> None:
    """Require a native schema-2 initialization to be uneffected and executable."""

    train = campaign["train"]
    checkpoint = campaign["checkpoint"]
    if (
        campaign["campaign_state"] not in {"PLANNED", "ACTIVE"}
        or campaign["observed_event"] != "INITIAL_AUTHORIZATION"
        or campaign["observed_event_ref"] != campaign["owner_issue"]
        or campaign["stop_reason"] != "NONE"
        or campaign["pending_action"]["kind"] != "START_NEXT_SLICE"
        or campaign["next_action"]["type"] != "AUTO_CONTINUE"
        or campaign["next_action"]["prompt"] != "NONE"
        or campaign["idea_inbox"]["items"]
        or checkpoint != {
            "policy": "RELEASE_BOUNDARY",
            "state": "NOT_DUE",
            "reference": "NONE",
        }
        or train["publication_state"] != "UNPUBLISHED"
        or train["published_version"] != "NONE"
        or any(
            train[key] != "NONE"
            for key in (
                "candidate_build_sha",
                "deployed_build_sha",
                "published_build_sha",
            )
        )
        or train["upstream"]["published_version"] != "NONE"
        or train["upstream"]["published_build_sha"] != "NONE"
        or any(
            item["state"] != "PLANNED" or item["pull_requests"]
            for item in campaign["slices"]
        )
    ):
        fail("INITIALIZE must establish a closed uneffected initial campaign state")


def expected_next_type(campaign: dict[str, Any]) -> str:
    state = campaign["campaign_state"]
    if state in {"HUMAN_GATE", "BLOCKED"}:
        return "USER_ACTION_REQUIRED"
    if state == "WAITING_EVENT":
        return "WAIT_EVENT"
    if state == "COMPLETE":
        return "CAMPAIGN_COMPLETE"
    kind = campaign["pending_action"]["kind"]
    required_level = ACTION_LEVEL.get(kind)
    if required_level is None:
        fail("an executable campaign state needs an executable pending action")
    if kind == "DEPLOY_PRODUCTION_C":
        fail("a Level C deployment must remain a closed human gate")
    authority = AUTHORITY_ENVELOPES[campaign["authority_envelope"]]
    if campaign["auto_continuation"] != "SEQUENTIAL" or required_level > authority:
        fail("non-executable work must be represented by a closed human gate")
    return "AUTO_CONTINUE"


def validate_human_stop(campaign: dict[str, Any]) -> None:
    reason = campaign["stop_reason"]
    kind = campaign["pending_action"]["kind"]
    required_level = ACTION_LEVEL.get(kind)
    authority = AUTHORITY_ENVELOPES[campaign["authority_envelope"]]
    if reason == "AUTHORITY_EXHAUSTED" and (
        required_level is None or required_level <= authority
    ):
        fail("AUTHORITY_EXHAUSTED requires an action beyond the envelope")
    if reason == "PUBLICATION_NOT_AUTHORIZED" and (
        kind != "PUBLISH_RELEASE"
        or authority >= AUTHORITY_ENVELOPES["THROUGH_RELEASE"]
    ):
        fail("PUBLICATION_NOT_AUTHORIZED requires a blocked publication boundary")
    if reason == "LEVEL_C_AUTHORIZATION" and (
        kind != "DEPLOY_PRODUCTION_C"
        or campaign["release_profile"] != "DEPLOYMENT_LEVEL_C"
    ):
        fail("LEVEL_C_AUTHORIZATION requires the closed Level C deployment action")


def validate_profile_binding(campaign: dict[str, Any]) -> dict[str, Any]:
    repo = campaign["repository"]
    if repo not in REPOSITORY_PROFILES:
        fail("campaign repository has no closed portable release profile")
    profile = REPOSITORY_PROFILES[repo]
    selected = closed(
        campaign["release_profile"],
        "release_profile",
        RELEASE_PROFILES,
    )
    if selected != profile["release_profile"]:
        fail("release_profile does not match the repository conformance profile")
    risk = closed(campaign["risk_profile"], "risk_profile", RISK_PROFILES)
    if risk not in profile["allowed_risks"]:
        fail("risk_profile exceeds the repository release profile")
    authority = closed(
        campaign["authority_envelope"],
        "authority_envelope",
        set(AUTHORITY_ENVELOPES),
    )
    if AUTHORITY_ENVELOPES[authority] > AUTHORITY_ENVELOPES[profile["authority_ceiling"]]:
        fail("authority_envelope exceeds the repository release profile")
    if campaign["workstream_class"] == "PROTOCOL" and (
        risk != "NO_PRODUCTION"
        or AUTHORITY_ENVELOPES[authority] > AUTHORITY_ENVELOPES["THROUGH_MERGE"]
    ):
        fail("a protocol campaign cannot acquire release or production authority")
    return profile


def validate_campaign_v2(
    value: Any,
    *,
    validate_receipt_chain: bool = True,
) -> dict[str, Any]:
    campaign = exact_object(value, "campaign", CAMPAIGN_KEYS)
    if campaign["schema_version"] != CAMPAIGN_SCHEMA_VERSION:
        fail("campaign schema_version mismatch")
    if campaign["protocol_version"] != PROTOCOL_VERSION:
        fail("campaign protocol_version mismatch")
    repository(campaign["repository"], "repository")
    one_line(campaign["campaign_id"], "campaign_id", maximum=100)
    owner_issue = issue(campaign["owner_issue"], "owner_issue")
    mode = closed(campaign["campaign_mode"], "campaign_mode", CAMPAIGN_MODES)
    state = closed(campaign["campaign_state"], "campaign_state", CAMPAIGN_STATES)
    closed(campaign["workstream_class"], "workstream_class", WORKSTREAM_CLASSES)
    profile = validate_profile_binding(campaign)
    closed(campaign["auto_continuation"], "auto_continuation", AUTO_CONTINUATION)
    checkpoint = validate_checkpoint(campaign["checkpoint"])
    validate_idea_inbox(campaign["idea_inbox"])
    train = validate_train(campaign["train"], campaign["release_profile"])
    expected_upstream = profile["upstream_repository"]
    observed_upstream = train["upstream"]["repository"]
    if campaign["release_profile"] == "UPSTREAM_RELEASE_VERIFIED":
        if observed_upstream != expected_upstream:
            fail("upstream release repository does not match the closed profile")
    elif observed_upstream != "NONE":
        fail("this release profile cannot carry an upstream repository")
    slices = validate_slices(campaign["slices"], mode)
    observed_event = closed(
        campaign["observed_event"],
        "observed_event",
        OBSERVED_EVENTS,
    )
    observed_ref = event_ref(campaign["observed_event_ref"])
    if observed_event == "INITIAL_AUTHORIZATION" and observed_ref != owner_issue:
        fail("initial authorization must bind the exact owner issue")
    pending = exact_object(campaign["pending_action"], "pending_action", PENDING_ACTION_KEYS)
    kind = closed(pending["kind"], "pending_action.kind", PENDING_ACTIONS)
    slice_id = pending["slice_id"]
    if slice_id != "NONE":
        one_line(slice_id, "pending_action.slice_id", maximum=100)
    stop = closed(campaign["stop_reason"], "stop_reason", STOP_REASONS)
    next_action = exact_object(campaign["next_action"], "next_action", NEXT_ACTION_KEYS)
    next_type = closed(next_action["type"], "next_action.type", NEXT_ACTION_TYPES)
    one_line(next_action["summary"], "next_action.summary", maximum=300)
    prompt = one_line(next_action["prompt"], "next_action.prompt", maximum=2000)

    active = [item for item in slices if item["state"] == "ACTIVE"]
    blocked = [item for item in slices if item["state"] == "BLOCKED"]
    planned = [item for item in slices if item["state"] == "PLANNED"]
    unfinished = [
        item for item in slices if item["state"] not in TERMINAL_SLICE_STATES
    ]
    slice_actions = {
        "START_NEXT_SLICE",
        "CONTINUE_ACTIVE_SLICE",
        "MERGE_ACTIVE_SLICE",
    }
    if kind in slice_actions:
        if slice_id == "NONE" or slice_id not in next_action["summary"]:
            fail("slice actions and their one next action require the exact slice_id")
    elif slice_id != "NONE":
        fail("release, wait and completion actions use slice_id NONE")
    if kind == "START_NEXT_SLICE":
        if active or blocked or not planned or slice_id != planned[0]["id"]:
            fail("START_NEXT_SLICE must select the first planned slice")
        prior_terminal = slices[: slices.index(planned[0])]
        if prior_terminal:
            previous = prior_terminal[-1]
            if previous["state"] == "MERGED":
                merge = previous["pull_requests"][-1]["merge_sha"]
                if observed_event != "PR_MERGED" or observed_ref != merge:
                    fail("sequential continuation requires its exact merge event")
            elif observed_event != "SLICE_CANCELLED" or observed_ref != previous["issue"]:
                fail("continuation after cancellation requires its exact issue event")
        elif observed_event != "INITIAL_AUTHORIZATION":
            fail("the first slice starts only from initial authorization")
    if kind in {"CONTINUE_ACTIVE_SLICE", "MERGE_ACTIVE_SLICE"} and (
        len(active) != 1 or slice_id != active[0]["id"]
    ):
        fail("the pending action must bind the one active slice")
    if kind == "MERGE_ACTIVE_SLICE":
        open_entries = [
            entry for entry in active[0]["pull_requests"] if entry["state"] == "OPEN"
        ]
        if (
            len(open_entries) != 1
            or observed_event != "GATES_PASSED"
            or observed_ref != open_entries[0]["head_sha"]
        ):
            fail("merge continuation requires exact-head passed-gate evidence")

    release_actions = {
        "PREPARE_RELEASE",
        "PUBLISH_RELEASE",
        "VERIFY_RELEASE",
        "VERIFY_UPSTREAM_RELEASE",
        "DEPLOY_PRODUCTION_B",
        "DEPLOY_PRODUCTION_C",
        "VERIFY_PRODUCTION",
        "RECORD_CHECKPOINT",
    }
    if kind in release_actions and unfinished:
        fail("release-boundary actions require all slices to be terminal")
    release_profile = campaign["release_profile"]
    publication = train["publication_state"]
    if kind in {"PREPARE_RELEASE", "PUBLISH_RELEASE", "VERIFY_RELEASE"} and (
        release_profile != "GITHUB_ARTIFACT"
        or campaign["workstream_class"] != "PRODUCT"
        or campaign["risk_profile"] != "PUBLIC_ARTIFACT"
    ):
        fail("GitHub release actions require the public-artifact product profile")
    if kind == "PREPARE_RELEASE" and publication != "UNPUBLISHED":
        fail("release preparation starts from an unpublished train")
    if kind == "PUBLISH_RELEASE" and (
        publication != "CANDIDATE"
        or observed_event != "RELEASE_CANDIDATE_MERGED"
        or observed_ref != train["candidate_build_sha"]
    ):
        fail("publication needs its merged exact candidate build")
    if kind == "VERIFY_RELEASE" and (
        publication != "PUBLISHED"
        or observed_event != "RELEASE_PUBLISHED"
        or observed_ref != f"release:v{train['published_version']}"
    ):
        fail("release verification needs its exact published version and build")
    if kind == "VERIFY_UPSTREAM_RELEASE" and (
        release_profile != "UPSTREAM_RELEASE_VERIFIED"
        or train["upstream"]["verification_state"] != "PENDING"
    ):
        fail("upstream verification requires the pending upstream profile")
    if kind == "DEPLOY_PRODUCTION_B" and (
        release_profile
        not in {"CODE_ONLY_PRODUCTION_B", "UPSTREAM_RELEASE_VERIFIED"}
        or campaign["risk_profile"] != "REVERSIBLE_PRODUCTION"
        or publication != "CANDIDATE"
    ):
        fail("production B deployment requires its exact reversible candidate profile")
    if kind == "DEPLOY_PRODUCTION_B" and (
        release_profile == "UPSTREAM_RELEASE_VERIFIED"
        and train["upstream"]["verification_state"] != "VERIFIED"
    ):
        fail("site deployment cannot precede verified upstream release evidence")
    if kind == "DEPLOY_PRODUCTION_C" and (
        release_profile != "DEPLOYMENT_LEVEL_C"
        or campaign["risk_profile"] != "CRITICAL_PRODUCTION"
        or publication != "CANDIDATE"
    ):
        fail("Level C deployment requires its critical exact candidate profile")
    if kind == "DEPLOY_PRODUCTION_C" and (
        state != "HUMAN_GATE" or stop != "LEVEL_C_AUTHORIZATION"
    ):
        fail("Level C deployment requires the closed human gate")
    if kind == "VERIFY_PRODUCTION" and (
        release_profile
        not in {
            "CODE_ONLY_PRODUCTION_B",
            "DEPLOYMENT_LEVEL_C",
            "UPSTREAM_RELEASE_VERIFIED",
        }
        or train["deployed_build_sha"] == "NONE"
        or observed_event != "PRODUCTION_DEPLOYED"
        or observed_ref != train["deployed_build_sha"]
    ):
        fail("production verification requires the exact deployed build event")
    if kind == "RECORD_CHECKPOINT":
        if checkpoint["state"] != "DUE":
            fail("checkpoint recording occurs once at the release boundary")
        if release_profile == "GITHUB_ARTIFACT":
            expected = (
                publication == "PUBLISHED"
                and observed_event == "RELEASE_VERIFIED"
                and observed_ref == f"release:v{train['published_version']}"
            )
        else:
            expected = (
                train["deployed_build_sha"] != "NONE"
                and observed_event == "PRODUCTION_VERIFIED"
                and observed_ref == train["deployed_build_sha"]
            )
        if not expected:
            fail("checkpoint recording requires the profile's verified terminal event")

    if state == "BLOCKED":
        if stop not in BLOCKED_REASONS or (not blocked and kind not in release_actions):
            fail("BLOCKED requires a closed blocker at the active delivery boundary")
    elif state == "HUMAN_GATE":
        if stop not in HUMAN_GATE_REASONS:
            fail("HUMAN_GATE requires a closed human stop reason")
        validate_human_stop(campaign)
    elif stop != "NONE":
        fail("only BLOCKED or HUMAN_GATE may carry a stop reason")
    if state == "WAITING_EVENT" and kind != "WAIT_FOR_EVENT":
        fail("WAITING_EVENT requires WAIT_FOR_EVENT")
    if state == "COMPLETE":
        if kind != "NO_ACTION" or unfinished:
            fail("COMPLETE requires no unfinished slice and NO_ACTION")
        if mode == "RELEASE_TRAIN":
            terminal = (
                publication == "PUBLISHED"
                if release_profile == "GITHUB_ARTIFACT"
                else train["deployed_build_sha"] != "NONE"
            )
            if not terminal or checkpoint["state"] != "RECORDED":
                fail("a completed train needs its profile's terminal build and checkpoint")
            if (
                release_profile == "UPSTREAM_RELEASE_VERIFIED"
                and train["upstream"]["verification_state"] != "VERIFIED"
            ):
                fail("a completed site train requires verified upstream release evidence")
        elif (
            publication != "UNPUBLISHED"
            or train["candidate_build_sha"] != "NONE"
            or train["deployed_build_sha"] != "NONE"
            or train["published_build_sha"] != "NONE"
            or checkpoint["state"] != "NOT_DUE"
        ):
            fail("a completed single-slice campaign must remain unreleased")
    if checkpoint["state"] == "RECORDED" and checkpoint["reference"] != owner_issue:
        fail("the release checkpoint must bind the campaign owner issue")
    if state in {"PLANNED", "ACTIVE"} and kind in {"WAIT_FOR_EVENT", "NO_ACTION"}:
        fail("executable campaign states need an executable pending action")

    expected_next = expected_next_type(campaign)
    if next_type != expected_next:
        fail(f"next_action.type must be {expected_next}")
    if (next_type == "USER_ACTION_REQUIRED") == (prompt == "NONE"):
        fail("only USER_ACTION_REQUIRED carries an exact next prompt")
    if validate_receipt_chain:
        validate_receipts(campaign)
    return campaign


def load_legacy_module() -> Any:
    path = Path(__file__).with_name("agent_protocol_v1_4.py")
    spec = importlib.util.spec_from_file_location("agent_protocol_v1_4_legacy", path)
    if spec is None or spec.loader is None:
        fail("unable to load the v1.4.0 compatibility validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def infer_migration_event(value: dict[str, Any]) -> dict[str, Any]:
    ref = value["observed_event_ref"]
    repo = value["repository"]
    if ISSUE_PATTERN.fullmatch(ref):
        action = "CLOSED" if value["observed_event"] == "SLICE_CANCELLED" else "OPENED"
        return {
            "kind": "ISSUE",
            "action": action,
            "repository": repo,
            "reference": ref,
            "sha": "NONE",
            "conclusion": "NOT_APPLICABLE",
        }
    if SHA_PATTERN.fullmatch(ref):
        merged = [item for item in value["slices"] if item["merge_sha"] == ref]
        if value["observed_event"] == "PR_MERGED" and len(merged) == 1:
            return {
                "kind": "PULL_REQUEST",
                "action": "MERGED",
                "repository": repo,
                "reference": merged[0]["pr"],
                "sha": ref,
                "conclusion": "NOT_APPLICABLE",
            }
        return {
            "kind": "COMMIT",
            "action": "CREATED",
            "repository": repo,
            "reference": ref,
            "sha": ref,
            "conclusion": "NOT_APPLICABLE",
        }
    if RUN_PATTERN.fullmatch(ref):
        heads = [
            item["head_sha"]
            for item in value["slices"]
            if item["head_sha"] != "NONE"
        ]
        build = heads[-1] if heads else value["train"]["build_sha"]
        if build == "NONE":
            fail("legacy workflow evidence has no deterministic exact build identity")
        return {
            "kind": "WORKFLOW_RUN",
            "action": "COMPLETED",
            "repository": repo,
            "reference": ref,
            "sha": build,
            "conclusion": "UNKNOWN",
        }
    if ref.startswith("release:v"):
        build = value["train"]["build_sha"]
        if build == "NONE":
            fail("legacy release evidence has no exact published build identity")
        return {
            "kind": "RELEASE",
            "action": "PUBLISHED",
            "repository": repo,
            "reference": ref,
            "sha": build,
            "conclusion": "NOT_APPLICABLE",
        }
    raise ContractError("legacy observed event cannot be bound to a real GitHub resource")


def migrate_campaign(
    value: Any, *, _validate_result: bool = True
) -> dict[str, Any]:
    if isinstance(value, dict) and value.get("schema_version") == CAMPAIGN_SCHEMA_VERSION:
        validate_campaign_v2(value)
        return deepcopy(value)
    if not isinstance(value, dict):
        fail("campaign must be an object")
    if (
        value.get("schema_version") != LEGACY_CAMPAIGN_SCHEMA_VERSION
        or value.get("protocol_version") != LEGACY_PROTOCOL_VERSION
    ):
        fail("only Agent Protocol 1.4.0 CAMPAIGN_SCHEMA 1 can migrate to schema 2")
    legacy = load_legacy_module()
    try:
        legacy.validate_campaign(deepcopy(value))
    except legacy.ContractError as exc:
        raise ContractError(f"legacy campaign is invalid: {exc}") from exc
    old_train = value["train"]
    publication = old_train["publication_state"]
    old_build = old_train["build_sha"]
    candidate = old_build if publication in {"CANDIDATE", "PUBLISHED"} else "NONE"
    published = old_build if publication == "PUBLISHED" else "NONE"
    slices: list[dict[str, Any]] = []
    for old_slice in value["slices"]:
        ledger: list[dict[str, Any]] = []
        if old_slice["pr"] != "NONE":
            pr_state = "MERGED" if old_slice["merge_sha"] != "NONE" else "OPEN"
            ledger.append(
                {
                    "sequence": 1,
                    "role": "OWNER",
                    "pr": old_slice["pr"],
                    "state": pr_state,
                    "head_sha": old_slice["head_sha"],
                    "merge_sha": old_slice["merge_sha"],
                }
            )
        slices.append(
            {
                "id": old_slice["id"],
                "state": old_slice["state"],
                "issue": old_slice["issue"],
                "pull_requests": ledger,
            }
        )
    migrated: dict[str, Any] = {
        "schema_version": CAMPAIGN_SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "repository": value["repository"],
        "campaign_id": value["campaign_id"],
        "owner_issue": value["owner_issue"],
        "campaign_mode": value["campaign_mode"],
        "campaign_state": value["campaign_state"],
        "workstream_class": value["workstream_class"],
        "authority_envelope": value["authority_envelope"],
        "risk_profile": value["risk_profile"],
        "release_profile": REPOSITORY_PROFILES[value["repository"]]["release_profile"],
        "auto_continuation": value["auto_continuation"],
        "checkpoint": deepcopy(value["checkpoint"]),
        "idea_inbox": deepcopy(value["idea_inbox"]),
        "train": {
            "train_id": old_train["train_id"],
            "target_version": old_train["target_version"],
            "publication_state": publication,
            "published_version": old_train["published_version"],
            "candidate_build_sha": candidate,
            "deployed_build_sha": "NONE",
            "published_build_sha": published,
            "upstream": {
                "repository": "NONE",
                "published_version": "NONE",
                "published_build_sha": "NONE",
                "verification_state": "NOT_APPLICABLE",
            },
        },
        "slices": slices,
        "receipts": [],
        "observed_event": value["observed_event"],
        "observed_event_ref": value["observed_event_ref"],
        "pending_action": deepcopy(value["pending_action"]),
        "stop_reason": value["stop_reason"],
        "next_action": deepcopy(value["next_action"]),
    }
    if (
        value["observed_event"],
        value["pending_action"]["kind"],
    ) in LEGACY_SUCCESS_DEPENDENT_ACTIONS:
        migrated["campaign_state"] = "WAITING_EVENT"
        migrated["pending_action"] = {
            "kind": "WAIT_FOR_EVENT",
            "slice_id": "NONE",
        }
        migrated["stop_reason"] = "NONE"
        migrated["next_action"] = {
            "type": "WAIT_EVENT",
            "summary": (
                "Wait for a new exact-head successful workflow event before "
                "continuing."
            ),
            "prompt": "NONE",
        }
    validate_campaign_v2(migrated, validate_receipt_chain=False)
    receipt = build_receipt(
        sequence=1,
        operation="SCHEMA_MIGRATION",
        campaign_id=migrated["campaign_id"],
        github_event=infer_migration_event(value),
        previous_state_sha256=object_sha256(value),
        successor_state_sha256=campaign_state_sha256(migrated),
        previous_receipt_sha256="NONE",
        previous_state=deepcopy(value),
        successor_state=campaign_state_payload(migrated),
    )
    migrated["receipts"] = [receipt]
    if _validate_result:
        validate_campaign_v2(migrated)
    return migrated


def immutable_campaign_identity(value: dict[str, Any]) -> dict[str, Any]:
    keys = {
        "repository",
        "campaign_id",
        "owner_issue",
        "campaign_mode",
        "workstream_class",
        "authority_envelope",
        "risk_profile",
        "release_profile",
        "auto_continuation",
    }
    identity = {key: deepcopy(value[key]) for key in keys}
    identity["idea_inbox_policy"] = {
        key: deepcopy(value["idea_inbox"][key]) for key in ("mode", "scope")
    }
    identity["train_identity"] = {
        "train_id": deepcopy(value["train"]["train_id"]),
        "target_version": deepcopy(value["train"]["target_version"]),
        "upstream_repository": deepcopy(value["train"]["upstream"]["repository"]),
    }
    return identity


def changed_paths(before: Any, after: Any, *, prefix: str = "") -> set[str]:
    if before == after:
        return set()
    if isinstance(before, dict) and isinstance(after, dict):
        paths: set[str] = set()
        for key in set(before) | set(after):
            child = f"{prefix}.{key}" if prefix else key
            if key not in before or key not in after:
                paths.add(child)
            else:
                paths.update(changed_paths(before[key], after[key], prefix=child))
        return paths
    if isinstance(before, list) and isinstance(after, list):
        paths = set()
        for index in range(max(len(before), len(after))):
            child = f"{prefix}.{index}" if prefix else str(index)
            if index >= len(before) or index >= len(after):
                paths.add(child)
            else:
                paths.update(changed_paths(before[index], after[index], prefix=child))
        return paths
    return {prefix}


def path_is_allowed(path: str, allowed: set[str]) -> bool:
    return any(path == item or path.startswith(f"{item}.") for item in allowed)


def slice_index_for_event(
    previous: dict[str, Any],
    successor: dict[str, Any],
    event: dict[str, Any],
) -> int:
    reference = event["reference"]
    if event["kind"] == "PULL_REQUEST":
        matches = {
            index
            for campaign in (previous, successor)
            for index, item in enumerate(campaign["slices"])
            if any(entry["pr"] == reference for entry in item["pull_requests"])
        }
    elif event["kind"] == "ISSUE":
        matches = {
            index
            for campaign in (previous, successor)
            for index, item in enumerate(campaign["slices"])
            if item["issue"] == reference
        }
    else:
        matches = {
            index
            for campaign in (previous, successor)
            for index, item in enumerate(campaign["slices"])
            if any(
                entry["state"] == "OPEN" and entry["head_sha"] == event["sha"]
                for entry in item["pull_requests"]
            )
        }
    if len(matches) != 1:
        fail("the GitHub event must identify exactly one mutable slice")
    return matches.pop()


def validate_pull_request_event_delta(
    previous: dict[str, Any],
    successor: dict[str, Any],
    event: dict[str, Any],
    index: int,
) -> None:
    """Bind PR_OPENED and PR_SYNCHRONIZED to distinct ledger mutations."""

    before = previous["slices"][index]["pull_requests"]
    after = successor["slices"][index]["pull_requests"]
    if campaign_state_payload(previous) == campaign_state_payload(successor):
        # Exact final-event replay is handled by append_transition_receipt().
        return

    observed = successor["observed_event"]
    if observed == "PR_OPENED":
        if (
            len(after) != len(before) + 1
            or after[:-1] != before
            or after[-1]["state"] != "OPEN"
            or after[-1]["pr"] != event["reference"]
            or after[-1]["head_sha"] != event["sha"]
        ):
            fail("PR_OPENED must append exactly its new open ledger entry")
        return

    if observed == "PR_SYNCHRONIZED":
        frozen = {"sequence", "role", "pr", "state", "merge_sha"}
        if (
            not before
            or len(after) != len(before)
            or after[:-1] != before[:-1]
            or before[-1]["state"] != "OPEN"
            or after[-1]["state"] != "OPEN"
            or any(before[-1][key] != after[-1][key] for key in frozen)
            or before[-1]["head_sha"] == after[-1]["head_sha"]
            or after[-1]["head_sha"] != event["sha"]
        ):
            fail("PR_SYNCHRONIZED may update only the existing open entry head_sha")


def validate_slice_issue_opened_delta(
    previous: dict[str, Any],
    successor: dict[str, Any],
    event: dict[str, Any],
    index: int,
) -> None:
    """Assign one real issue to one issue-less planned slice and activate it."""

    if campaign_state_payload(previous) == campaign_state_payload(successor):
        # Exact final-event replay is handled by append_transition_receipt().
        return
    before = previous["slices"][index]
    after = successor["slices"][index]
    if (
        event["kind"] != "ISSUE"
        or event["action"] != "OPENED"
        or before["state"] != "PLANNED"
        or before["issue"] != "NONE"
        or before["pull_requests"]
        or after["state"] != "ACTIVE"
        or after["issue"] != event["reference"]
        or after["pull_requests"] != before["pull_requests"]
    ):
        fail(
            "SLICE_ISSUE_OPENED must assign its exact issue to one issue-less "
            "planned slice and activate only that slice"
        )


def validate_event_transition(
    previous: dict[str, Any],
    successor: dict[str, Any],
    github_event: dict[str, Any],
) -> None:
    """Restrict one receipt to the state owned by its exact GitHub event."""

    event = validate_github_event(github_event, allow_legacy=True)
    observed = successor["observed_event"]
    before_items = previous["idea_inbox"]["items"]
    after_items = successor["idea_inbox"]["items"]
    if (
        event["kind"] == "ISSUE"
        and event["action"] == "OPENED"
        and after_items == [*before_items, event["reference"]]
    ):
        allowed = {"idea_inbox.items"}
    else:
        allowed = {
            "campaign_state",
            "observed_event",
            "observed_event_ref",
            "pending_action",
            "stop_reason",
            "next_action",
        }
        if observed in {"PR_OPENED", "PR_SYNCHRONIZED", "PR_CLOSED", "PR_MERGED"}:
            index = slice_index_for_event(previous, successor, event)
            if observed in {"PR_OPENED", "PR_SYNCHRONIZED"}:
                validate_pull_request_event_delta(previous, successor, event, index)
            allowed.update({f"slices.{index}.state", f"slices.{index}.pull_requests"})
        elif observed == "SLICE_ISSUE_OPENED":
            index = slice_index_for_event(previous, successor, event)
            validate_slice_issue_opened_delta(previous, successor, event, index)
            allowed.update({f"slices.{index}.issue", f"slices.{index}.state"})
        elif observed in {"SLICE_CANCELLED", "GATES_PASSED", "GATES_FAILED"}:
            index = slice_index_for_event(previous, successor, event)
            allowed.add(f"slices.{index}.state")
        elif observed == "RELEASE_CANDIDATE_MERGED":
            allowed.update({"train.publication_state", "train.candidate_build_sha"})
        elif observed == "RELEASE_PUBLISHED":
            allowed.update(
                {
                    "train.publication_state",
                    "train.published_version",
                    "train.published_build_sha",
                }
            )
        elif observed == "RELEASE_VERIFIED":
            allowed.add("checkpoint")
        elif observed == "UPSTREAM_RELEASE_VERIFIED":
            allowed.add("train.upstream")
        elif observed == "PRODUCTION_DEPLOYED":
            allowed.add("train.deployed_build_sha")
        elif observed == "PRODUCTION_VERIFIED":
            allowed.add("checkpoint")
        elif observed != "INITIAL_AUTHORIZATION":
            fail("the observed event has no closed transition profile")

    state_before = {key: value for key, value in previous.items() if key != "receipts"}
    state_after = {key: value for key, value in successor.items() if key != "receipts"}
    unauthorized = sorted(
        path
        for path in changed_paths(state_before, state_after)
        if not path_is_allowed(path, allowed)
    )
    if unauthorized:
        fail(
            "the GitHub event cannot mutate unrelated campaign state: "
            + ", ".join(unauthorized)
        )


def validate_transition_pair(
    previous: dict[str, Any],
    successor: dict[str, Any],
    github_event: dict[str, Any],
) -> None:
    """Validate one fully reconstructed adjacent campaign transition."""

    validate_campaign_v2(previous, validate_receipt_chain=False)
    validate_campaign_v2(successor, validate_receipt_chain=False)
    if immutable_campaign_identity(successor) != immutable_campaign_identity(previous):
        fail("a continuation receipt cannot rewrite campaign identity or authority")
    if [item["id"] for item in successor["slices"]] != [
        item["id"] for item in previous["slices"]
    ]:
        fail("a continuation receipt cannot reorder or replace frozen slice scope")
    for before_slice, after_slice in zip(
        previous["slices"], successor["slices"], strict=True
    ):
        if (
            before_slice["issue"] != "NONE"
            and after_slice["issue"] != before_slice["issue"]
        ):
            fail("a continuation receipt cannot rewrite a retained slice issue")
        if (
            before_slice["state"] in TERMINAL_SLICE_STATES
            and after_slice["state"] != before_slice["state"]
        ):
            fail("a continuation receipt cannot reopen a terminal slice")
        validate_pull_request_history(
            before_slice["pull_requests"],
            after_slice["pull_requests"],
            label=f"slice {before_slice['id']}",
        )
    validate_event_transition(previous, successor, github_event)


def append_transition_receipt(
    previous: Any,
    successor: Any,
    github_event: Any,
) -> dict[str, Any]:
    previous_value = validate_campaign_v2(deepcopy(previous))
    successor_value = exact_object(deepcopy(successor), "campaign", CAMPAIGN_KEYS)
    if successor_value["receipts"] != previous_value["receipts"]:
        fail("successor must retain the exact receipt prefix before append")
    checked_event = validate_github_event(deepcopy(github_event))
    validate_transition_pair(previous_value, successor_value, checked_event)
    previous_digest = campaign_state_sha256(previous_value)
    successor_digest = campaign_state_sha256(successor_value)
    last = previous_value["receipts"][-1]
    if previous_digest == successor_digest:
        last_event = validate_github_event(
            last["github_event"],
            allow_legacy=True,
            allow_unknown_conclusion=last["operation"] == "SCHEMA_MIGRATION",
        )
        if (
            github_event_identity(checked_event) == github_event_identity(last_event)
            and checked_event["conclusion"] == last_event["conclusion"]
        ):
            return previous_value
        fail("a new GitHub event cannot create a receipt without a state transition")
    for old_receipt in previous_value["receipts"]:
        old_event = validate_github_event(
            old_receipt["github_event"],
            allow_legacy=True,
            allow_unknown_conclusion=old_receipt["operation"] == "SCHEMA_MIGRATION",
        )
        if github_event_identity(old_event) == github_event_identity(checked_event):
            fail("a real GitHub event cannot be reused for a different transition")
    new_receipt = build_receipt(
        sequence=len(previous_value["receipts"]) + 1,
        operation="STATE_TRANSITION",
        campaign_id=successor_value["campaign_id"],
        github_event=checked_event,
        previous_state_sha256=previous_digest,
        successor_state_sha256=successor_digest,
        previous_receipt_sha256=last["receipt_sha256"],
        previous_state=campaign_state_payload(previous_value),
        successor_state=campaign_state_payload(successor_value),
    )
    successor_value["receipts"].append(new_receipt)
    validate_campaign_v2(successor_value)
    return successor_value


def validate_append_only(previous: Any, successor: Any) -> dict[str, Any]:
    before = validate_campaign_v2(deepcopy(previous))
    after = validate_campaign_v2(deepcopy(successor))
    if before == after:
        return after
    old_receipts = before["receipts"]
    new_receipts = after["receipts"]
    if len(new_receipts) != len(old_receipts) + 1 or new_receipts[:-1] != old_receipts:
        fail("continuation must append exactly one receipt without rewriting history")
    receipt = new_receipts[-1]
    if receipt["previous_state_sha256"] != campaign_state_sha256(before):
        fail("continuation receipt predecessor digest does not match prior campaign")
    if receipt["successor_state_sha256"] != campaign_state_sha256(after):
        fail("continuation receipt successor digest does not match next campaign")
    validate_transition_pair(before, after, receipt["github_event"])
    return after


def render_handoff(value: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"Outcome: {value['outcome']}.",
            f"Delivered: {value['delivered']}",
            f"Release: {value['release_status']}.",
            f"Next action [{value['next_action_type']}]: {value['next_action']}",
            f"Prompt: {value['next_prompt']}",
        ]
    )


def word_count(value: str) -> int:
    return len(re.findall(r"\S+", value))


def release_status(campaign: dict[str, Any]) -> str:
    if campaign["campaign_mode"] == "SINGLE_SLICE" and campaign["workstream_class"] == "PROTOCOL":
        return "NOT_APPLICABLE"
    train = campaign["train"]
    if train["publication_state"] == "PUBLISHED":
        return "PUBLISHED"
    if train["deployed_build_sha"] != "NONE":
        return "DEPLOYED"
    if train["publication_state"] == "CANDIDATE":
        return "CANDIDATE"
    if train["upstream"]["verification_state"] == "VERIFIED":
        return "UPSTREAM_VERIFIED"
    if campaign["campaign_state"] in {"PLANNED", "ACTIVE", "WAITING_EVENT"}:
        return "TRAIN_ACTIVE"
    return "UNPUBLISHED"


def normal_handoff_outcome(campaign: dict[str, Any]) -> str:
    if campaign["campaign_state"] == "COMPLETE":
        return "CAMPAIGN_COMPLETE"
    if campaign["campaign_state"] in {"BLOCKED", "HUMAN_GATE"}:
        return "BLOCKED"
    return "DELIVERED"


def build_handoff(
    campaign: Any,
    *,
    delivered: str,
    resume_required: bool = False,
) -> dict[str, Any]:
    value = validate_campaign_v2(deepcopy(campaign))
    delivered = one_line(delivered, "handoff.delivered", maximum=500)
    if resume_required:
        if value["campaign_state"] in {"BLOCKED", "HUMAN_GATE", "COMPLETE"}:
            fail("RESUME_REQUIRED cannot replace a blocker, human decision or completion")
        outcome = "RESUME_REQUIRED"
        resume_reason = "SESSION_LIMIT"
        next_type = "RESUME_SESSION"
        next_action = (
            f"Resume {value['campaign_id']} from receipt "
            f"{value['receipts'][-1]['sequence']} and {value['next_action']['summary']}"
        )
        next_prompt = "NONE"
    else:
        outcome = normal_handoff_outcome(value)
        resume_reason = "NONE"
        next_type = value["next_action"]["type"]
        next_action = value["next_action"]["summary"]
        next_prompt = value["next_action"]["prompt"]
    handoff: dict[str, Any] = {
        "schema_version": HANDOFF_SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "campaign_id": value["campaign_id"],
        "campaign_sha256": campaign_sha256(value),
        "outcome": outcome,
        "delivered": delivered,
        "release_status": release_status(value),
        "resume_reason": resume_reason,
        "next_action_type": next_type,
        "next_action": next_action,
        "next_prompt": next_prompt,
        "human_report": "",
    }
    handoff["human_report"] = render_handoff(handoff)
    validate_handoff(handoff)
    return handoff


def validate_handoff(value: Any) -> dict[str, Any]:
    handoff = exact_object(value, "handoff", HANDOFF_KEYS)
    if handoff["schema_version"] != HANDOFF_SCHEMA_VERSION:
        fail("handoff schema_version mismatch")
    if handoff["protocol_version"] != PROTOCOL_VERSION:
        fail("handoff protocol_version mismatch")
    one_line(handoff["campaign_id"], "handoff.campaign_id", maximum=100)
    sha256(handoff["campaign_sha256"], "handoff.campaign_sha256")
    outcome = closed(handoff["outcome"], "handoff.outcome", HANDOFF_OUTCOMES)
    one_line(handoff["delivered"], "handoff.delivered", maximum=500)
    closed(handoff["release_status"], "handoff.release_status", RELEASE_STATUSES)
    resume_reason = closed(
        handoff["resume_reason"],
        "handoff.resume_reason",
        RESUME_REASONS,
    )
    next_type = closed(
        handoff["next_action_type"],
        "handoff.next_action_type",
        HANDOFF_NEXT_ACTION_TYPES,
    )
    one_line(handoff["next_action"], "handoff.next_action", maximum=500)
    prompt = one_line(handoff["next_prompt"], "handoff.next_prompt", maximum=2000)
    report = handoff["human_report"]
    if not isinstance(report, str) or report != render_handoff(handoff):
        fail("human_report must be the canonical five-line concise handoff")
    if report.count("Next action [") != 1:
        fail("human_report must contain exactly one next action")
    if word_count(report) > 120:
        fail("human_report exceeds 120 words")
    if (next_type == "USER_ACTION_REQUIRED") == (prompt == "NONE"):
        fail("only USER_ACTION_REQUIRED carries an exact next prompt")
    if outcome == "BLOCKED" and next_type != "USER_ACTION_REQUIRED":
        fail("a blocked handoff requires one human action")
    if next_type == "USER_ACTION_REQUIRED" and outcome != "BLOCKED":
        fail("only a blocked or human-gate handoff may require a human action")
    if outcome == "DELIVERED" and next_type not in {"AUTO_CONTINUE", "WAIT_EVENT"}:
        fail("a delivered handoff must continue or wait for one real event")
    if outcome == "CAMPAIGN_COMPLETE" and next_type != "CAMPAIGN_COMPLETE":
        fail("campaign completion must be explicit")
    if next_type == "CAMPAIGN_COMPLETE" and outcome != "CAMPAIGN_COMPLETE":
        fail("only campaign completion may use CAMPAIGN_COMPLETE")
    if outcome == "RESUME_REQUIRED":
        if resume_reason != "SESSION_LIMIT" or next_type != "RESUME_SESSION":
            fail("RESUME_REQUIRED is reserved for a closed session-limit resume")
    elif resume_reason != "NONE" or next_type == "RESUME_SESSION":
        fail("session resume cannot masquerade as delivery, blocking or completion")
    return handoff


def build_bundle(
    campaign: Any,
    *,
    delivered: str,
    resume_required: bool = False,
) -> dict[str, Any]:
    campaign_v2 = migrate_campaign(deepcopy(campaign))
    bundle = {
        "campaign": campaign_v2,
        "handoff": build_handoff(
            campaign_v2,
            delivered=delivered,
            resume_required=resume_required,
        ),
    }
    validate_bundle(bundle)
    return bundle


def validate_bundle(value: Any) -> dict[str, Any]:
    bundle = exact_object(value, "bundle", BUNDLE_KEYS)
    campaign = validate_campaign_v2(bundle["campaign"])
    handoff = validate_handoff(bundle["handoff"])
    if handoff["campaign_id"] != campaign["campaign_id"]:
        fail("handoff campaign_id does not match the campaign")
    if handoff["campaign_sha256"] != campaign_sha256(campaign):
        fail("handoff campaign digest does not match the exact campaign")
    expected = build_handoff(
        campaign,
        delivered=handoff["delivered"],
        resume_required=handoff["outcome"] == "RESUME_REQUIRED",
    )
    if handoff != expected:
        fail("campaign and handoff were not generated and validated jointly")
    return bundle


def validate_conformance_fixture(value: Any) -> dict[str, Any]:
    fixture = exact_object(value, "conformance fixture", CONFORMANCE_KEYS)
    if fixture["schema_version"] != CONFORMANCE_SCHEMA_VERSION:
        fail("conformance fixture schema_version mismatch")
    if fixture["protocol_version"] != PROTOCOL_VERSION:
        fail("conformance fixture protocol_version mismatch")
    if fixture["mode"] != "READ_ONLY":
        fail("cross-repository conformance fixtures must be READ_ONLY")
    if (
        not isinstance(fixture["observed_at"], str)
        or OBSERVED_AT_PATTERN.fullmatch(fixture["observed_at"]) is None
    ):
        fail("conformance observed_at must be a closed UTC timestamp")
    rows = fixture["repositories"]
    if not isinstance(rows, list) or len(rows) != len(REPOSITORY_PROFILES):
        fail("conformance fixture must contain the four closed repositories")
    observed: set[str] = set()
    for index, raw in enumerate(rows):
        row = exact_object(
            raw,
            f"conformance repositories[{index}]",
            CONFORMANCE_REPOSITORY_KEYS,
        )
        repo = repository(row["repository"], "conformance repository")
        if repo in observed or repo not in REPOSITORY_PROFILES:
            fail("conformance repositories must be unique and closed")
        observed.add(repo)
        expected = REPOSITORY_PROFILES[repo]
        sha(row["observed_head_sha"], "conformance observed_head_sha")
        if row["observation_source"] != "GITHUB_READ_ONLY":
            fail("conformance evidence must be observed read-only from GitHub")
        if row["writes_performed"] is not False:
            fail("conformance evidence cannot report a cross-repository write")
        for key in (
            "default_branch",
            "release_profile",
            "state_model",
            "authority_ceiling",
            "risk_ceiling",
            "human_boundary",
            "upstream_repository",
        ):
            if row[key] != expected[key]:
                fail(f"conformance {repo} {key} does not match its closed profile")
        closed(row["release_profile"], "conformance release_profile", RELEASE_PROFILES)
        closed(row["state_model"], "conformance state_model", STATE_MODELS)
        closed(
            row["authority_ceiling"],
            "conformance authority_ceiling",
            set(AUTHORITY_ENVELOPES),
        )
        closed(row["risk_ceiling"], "conformance risk_ceiling", RISK_PROFILES)
        closed(row["human_boundary"], "conformance human_boundary", HUMAN_BOUNDARIES)
        paths = row["source_paths"]
        if (
            not isinstance(paths, list)
            or not paths
            or any(not isinstance(path, str) or not path or path.startswith("/") for path in paths)
        ):
            fail("conformance source_paths must be non-empty repository-relative paths")
    if observed != set(REPOSITORY_PROFILES):
        fail("conformance fixture repository set is incomplete")
    regression = exact_object(
        fixture["ledger_regression"],
        "ledger_regression",
        LEDGER_REGRESSION_KEYS,
    )
    if (
        regression["repository"] != "gabned/provelume"
        or regression["slice_id"] != "0.10/S04"
        or regression["owner_issue"] != "#171"
    ):
        fail("ledger regression must bind the observed S04 owner issue")
    ledger = validate_pull_request_ledger(
        regression["pull_requests"],
        label="ledger_regression.pull_requests",
    )
    if (
        len(ledger) != 2
        or [entry["role"] for entry in ledger] != ["OWNER", "CORRECTION"]
        or [entry["pr"] for entry in ledger] != ["#172", "#173"]
        or any(entry["state"] != "MERGED" for entry in ledger)
    ):
        fail("ledger regression must retain ordered #172 owner and #173 correction")
    core_row = next(row for row in rows if row["repository"] == "gabned/provelume")
    if ledger[-1]["merge_sha"] != core_row["observed_head_sha"]:
        fail("ledger regression terminal merge must match the observed Core head")
    return fixture


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"unable to read JSON evidence: {exc}") from exc
    if not isinstance(value, dict):
        fail("JSON evidence must be an object")
    return value


def write_object(value: dict[str, Any], output: Path | None) -> None:
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output is None:
        print(rendered, end="")
    else:
        output.write_text(rendered, encoding="utf-8")


def sample_campaign_v1() -> dict[str, Any]:
    legacy = load_legacy_module()
    return legacy.sample_campaign()


def sample_campaign() -> dict[str, Any]:
    return migrate_campaign(sample_campaign_v1())


def sample_handoff() -> dict[str, Any]:
    return build_handoff(
        sample_campaign(),
        delivered="The exact GitHub transition is recorded without changing release state.",
    )


def self_test() -> None:
    legacy = sample_campaign_v1()
    migrated = migrate_campaign(legacy)
    if migrated != migrate_campaign(legacy) or migrated != migrate_campaign(migrated):
        fail("campaign migration is not deterministic and idempotent")
    validate_campaign_v2(migrated)
    validate_bundle(
        build_bundle(
            migrated,
            delivered="The exact GitHub transition is recorded without changing release state.",
        )
    )
    resume = build_bundle(
        migrated,
        delivered="The current session reached its bounded limit.",
        resume_required=True,
    )
    if resume["handoff"]["outcome"] != "RESUME_REQUIRED":
        fail("session-limit handoff did not produce RESUME_REQUIRED")
    invalid = deepcopy(migrated)
    invalid["receipts"][0]["successor_state_sha256"] = "0" * 64
    try:
        validate_campaign_v2(invalid)
    except ContractError:
        pass
    else:
        fail("self-test accepted a rewritten transition receipt")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("validate-campaign", "validate-bundle"):
        child = subparsers.add_parser(command)
        child.add_argument("path", type=Path)
    handoff_validation = subparsers.add_parser("validate-handoff")
    handoff_validation.add_argument("path", type=Path)
    handoff_validation.add_argument("--campaign", type=Path, required=True)
    conformance = subparsers.add_parser("validate-conformance")
    conformance.add_argument("path", type=Path)
    migration = subparsers.add_parser("migrate-campaign")
    migration.add_argument("path", type=Path)
    migration.add_argument("--output", type=Path)
    generation = subparsers.add_parser("generate-bundle")
    generation.add_argument("path", type=Path)
    generation.add_argument("--delivered", required=True)
    generation.add_argument("--resume-required", action="store_true")
    generation.add_argument("--output", type=Path)
    continuation = subparsers.add_parser("verify-continuation")
    continuation.add_argument("previous", type=Path)
    continuation.add_argument("successor", type=Path)
    subparsers.add_parser("self-test")
    args = parser.parse_args()
    try:
        if args.command == "self-test":
            self_test()
            result = {"protocol_version": PROTOCOL_VERSION, "result": "PASS"}
        elif args.command == "validate-campaign":
            value = load_object(args.path)
            if value.get("schema_version") == LEGACY_CAMPAIGN_SCHEMA_VERSION:
                load_legacy_module().validate_campaign(value)
                schema_version = LEGACY_CAMPAIGN_SCHEMA_VERSION
            else:
                validate_campaign_v2(value)
                schema_version = CAMPAIGN_SCHEMA_VERSION
            result = {
                "protocol_version": PROTOCOL_VERSION,
                "result": "PASS",
                "schema_version": schema_version,
            }
        elif args.command == "validate-handoff":
            handoff = load_object(args.path)
            bundle = validate_bundle(
                {"campaign": load_object(args.campaign), "handoff": handoff}
            )
            result = {
                "protocol_version": PROTOCOL_VERSION,
                "result": "PASS",
                "word_count": word_count(bundle["handoff"]["human_report"]),
            }
        elif args.command == "validate-bundle":
            bundle = validate_bundle(load_object(args.path))
            result = {
                "campaign_sha256": bundle["handoff"]["campaign_sha256"],
                "protocol_version": PROTOCOL_VERSION,
                "result": "PASS",
            }
        elif args.command == "validate-conformance":
            fixture = validate_conformance_fixture(load_object(args.path))
            result = {
                "profiles": len(fixture["repositories"]),
                "protocol_version": PROTOCOL_VERSION,
                "result": "PASS",
            }
        elif args.command == "migrate-campaign":
            migrated = migrate_campaign(load_object(args.path))
            write_object(migrated, args.output)
            return 0
        elif args.command == "generate-bundle":
            bundle = build_bundle(
                load_object(args.path),
                delivered=args.delivered,
                resume_required=args.resume_required,
            )
            write_object(bundle, args.output)
            return 0
        else:
            validate_append_only(
                load_object(args.previous),
                load_object(args.successor),
            )
            result = {"protocol_version": PROTOCOL_VERSION, "result": "PASS"}
    except (ContractError, load_legacy_module().ContractError) as exc:
        print(json.dumps({"error": str(exc), "result": "BLOCKED"}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
