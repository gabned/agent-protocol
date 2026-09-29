#!/usr/bin/env python3
"""Offline campaign and concise-handoff contracts for Agent Protocol v1.4."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = "1.4.0"
SCHEMA_VERSION = 1
REPOSITORY = "gabned/provelume"

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
LOCAL_RISK_PROFILES = {"NO_PRODUCTION", "PUBLIC_ARTIFACT"}
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
PUBLICATION_STATES = {"UNPUBLISHED", "CANDIDATE", "PUBLISHED"}
CHECKPOINT_STATES = {"NOT_DUE", "DUE", "RECORDED"}
OBSERVED_EVENTS = {
    "INITIAL_AUTHORIZATION",
    "PR_MERGED",
    "SLICE_CANCELLED",
    "GATES_PASSED",
    "RELEASE_CANDIDATE_MERGED",
    "RELEASE_PUBLISHED",
    "RELEASE_VERIFIED",
    "PRODUCTION_VERIFIED",
}
PENDING_ACTIONS = {
    "START_NEXT_SLICE",
    "CONTINUE_ACTIVE_SLICE",
    "MERGE_ACTIVE_SLICE",
    "PREPARE_RELEASE",
    "PUBLISH_RELEASE",
    "VERIFY_RELEASE",
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
    "RECORD_CHECKPOINT": 2,
    "VERIFY_PRODUCTION": 3,
}
NEXT_ACTION_TYPES = {
    "AUTO_CONTINUE",
    "WAIT_EVENT",
    "USER_ACTION_REQUIRED",
    "CAMPAIGN_COMPLETE",
}
HANDOFF_OUTCOMES = {"DELIVERED", "BLOCKED", "CAMPAIGN_COMPLETE"}
RELEASE_STATUSES = {
    "NOT_APPLICABLE",
    "TRAIN_ACTIVE",
    "UNPUBLISHED",
    "CANDIDATE",
    "PUBLISHED",
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
    "auto_continuation",
    "checkpoint",
    "idea_inbox",
    "train",
    "slices",
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
    "build_sha",
}
SLICE_KEYS = {"id", "state", "issue", "pr", "head_sha", "merge_sha"}
PENDING_ACTION_KEYS = {"kind", "slice_id"}
NEXT_ACTION_KEYS = {"type", "summary", "prompt"}
HANDOFF_KEYS = {
    "schema_version",
    "protocol_version",
    "campaign_id",
    "outcome",
    "delivered",
    "release_status",
    "next_action_type",
    "next_action",
    "next_prompt",
    "human_report",
}

SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
STRICT_SEMVER_PATTERN = re.compile(
    r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)
ISSUE_PATTERN = re.compile(r"#[1-9]\d*")
SLICE_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]+/S[0-9]{2,}")
EVENT_REF_PATTERN = re.compile(
    r"(?:#[1-9]\d*|[0-9a-f]{40}|run:[1-9]\d*|release:[A-Za-z0-9._-]+)"
)


class ContractError(ValueError):
    """Raised when connector-supplied protocol evidence is invalid."""


def fail(message: str) -> None:
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


def issue_or_none(value: Any, label: str) -> str:
    if value == "NONE":
        return value
    if not isinstance(value, str) or ISSUE_PATTERN.fullmatch(value) is None:
        fail(f"{label} must be NONE or an exact issue/PR reference")
    return value


def sha_or_none(value: Any, label: str) -> str:
    if value == "NONE":
        return value
    if not isinstance(value, str) or SHA_PATTERN.fullmatch(value) is None:
        fail(f"{label} must be NONE or an exact lowercase SHA")
    return value


def semver(value: Any, label: str) -> str:
    if not isinstance(value, str) or STRICT_SEMVER_PATTERN.fullmatch(value) is None:
        fail(f"{label} must be a semantic version without a v prefix")
    return value


def event_ref(value: Any) -> str:
    if not isinstance(value, str) or EVENT_REF_PATTERN.fullmatch(value) is None:
        fail("observed_event_ref must be an exact GitHub-bound reference")
    return value


def validate_train(value: Any) -> dict[str, Any]:
    train = exact_object(value, "train", TRAIN_KEYS)
    train_id = one_line(train["train_id"], "train.train_id", maximum=100)
    target = semver(train["target_version"], "train.target_version")
    state = closed(
        train["publication_state"],
        "train.publication_state",
        PUBLICATION_STATES,
    )
    published = train["published_version"]
    build_sha = sha_or_none(train["build_sha"], "train.build_sha")
    if published != "NONE":
        published = semver(published, "train.published_version")
    if train_id in {target, published, build_sha}:
        fail("train identity must remain distinct from version and build identity")
    if state == "UNPUBLISHED" and (published != "NONE" or build_sha != "NONE"):
        fail("an unpublished train cannot claim a published version or build")
    if state == "CANDIDATE" and (published != "NONE" or build_sha == "NONE"):
        fail("a candidate needs a build SHA and no published version")
    if state == "PUBLISHED" and (published != target or build_sha == "NONE"):
        fail("a published train must bind target version and exact build SHA")
    return train


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
    checked = [issue_or_none(item, "idea inbox item") for item in items]
    if "NONE" in checked or len(checked) != len(set(checked)):
        fail("idea inbox items must be unique issue references")
    return inbox


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
    for index, raw in enumerate(value):
        item = exact_object(raw, f"slices[{index}]", SLICE_KEYS)
        identifier = one_line(item["id"], f"slices[{index}].id", maximum=100)
        if SLICE_ID_PATTERN.fullmatch(identifier) is None or identifier in identifiers:
            fail("slice ids must be unique train/SNN identifiers")
        identifiers.add(identifier)
        state = closed(item["state"], f"slices[{index}].state", SLICE_STATES)
        issue = issue_or_none(item["issue"], f"slices[{index}].issue")
        pr = issue_or_none(item["pr"], f"slices[{index}].pr")
        head = sha_or_none(item["head_sha"], f"slices[{index}].head_sha")
        merge = sha_or_none(item["merge_sha"], f"slices[{index}].merge_sha")
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
        if state == "PLANNED":
            if pr != "NONE" or head != "NONE" or merge != "NONE":
                fail("planned slices cannot claim PR or commit identity")
        elif state in {"ACTIVE", "BLOCKED"}:
            if issue == "NONE" or merge != "NONE":
                fail("active or blocked slices need an issue and no merge SHA")
            if (pr == "NONE") != (head == "NONE"):
                fail("active slice PR and head SHA must appear together")
        elif state == "MERGED":
            if "NONE" in {issue, pr, head, merge}:
                fail("merged slices need issue, PR, head and merge identity")
        elif state == "CANCELLED" and (
            issue == "NONE" or {pr, head, merge} != {"NONE"}
        ):
            fail("cancelled slices retain an issue and no PR/commit identity")
        result.append(item)
    if active_like > 1:
        fail("a campaign may have at most one active or blocked slice")
    return result


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
        kind != "VERIFY_PRODUCTION"
        or authority >= AUTHORITY_ENVELOPES["THROUGH_PRODUCTION_B"]
    ):
        fail("LEVEL_C_AUTHORIZATION requires a production boundary")


def validate_campaign(value: Any) -> dict[str, Any]:
    campaign = exact_object(value, "campaign", CAMPAIGN_KEYS)
    if campaign["schema_version"] != SCHEMA_VERSION:
        fail("campaign schema_version mismatch")
    if campaign["protocol_version"] != PROTOCOL_VERSION:
        fail("campaign protocol_version mismatch")
    if campaign["repository"] != REPOSITORY:
        fail("campaign repository mismatch")
    one_line(campaign["campaign_id"], "campaign_id", maximum=100)
    owner_issue = issue_or_none(campaign["owner_issue"], "owner_issue")
    if owner_issue == "NONE":
        fail("campaign evidence requires an exact owner issue")
    mode = closed(campaign["campaign_mode"], "campaign_mode", CAMPAIGN_MODES)
    state = closed(campaign["campaign_state"], "campaign_state", CAMPAIGN_STATES)
    closed(
        campaign["workstream_class"],
        "workstream_class",
        WORKSTREAM_CLASSES,
    )
    authority = closed(
        campaign["authority_envelope"],
        "authority_envelope",
        set(AUTHORITY_ENVELOPES),
    )
    risk = closed(campaign["risk_profile"], "risk_profile", RISK_PROFILES)
    if risk not in LOCAL_RISK_PROFILES or authority == "THROUGH_PRODUCTION_B":
        fail("the Provelume Core profile has no production authority")
    if campaign["workstream_class"] == "PROTOCOL" and (
        risk != "NO_PRODUCTION"
        or AUTHORITY_ENVELOPES[authority] > AUTHORITY_ENVELOPES["THROUGH_MERGE"]
    ):
        fail("a protocol campaign cannot acquire release or production authority")
    closed(
        campaign["auto_continuation"],
        "auto_continuation",
        AUTO_CONTINUATION,
    )
    checkpoint = validate_checkpoint(campaign["checkpoint"])
    validate_idea_inbox(campaign["idea_inbox"])
    train = validate_train(campaign["train"])
    slices = validate_slices(campaign["slices"], mode)
    event = closed(campaign["observed_event"], "observed_event", OBSERVED_EVENTS)
    observed_ref = event_ref(campaign["observed_event_ref"])
    if event == "INITIAL_AUTHORIZATION" and observed_ref != owner_issue:
        fail("initial authorization must bind the exact owner issue")
    pending = exact_object(
        campaign["pending_action"],
        "pending_action",
        PENDING_ACTION_KEYS,
    )
    kind = closed(pending["kind"], "pending_action.kind", PENDING_ACTIONS)
    slice_id = pending["slice_id"]
    if slice_id != "NONE":
        one_line(slice_id, "pending_action.slice_id", maximum=100)
    stop = closed(campaign["stop_reason"], "stop_reason", STOP_REASONS)
    next_action = exact_object(
        campaign["next_action"],
        "next_action",
        NEXT_ACTION_KEYS,
    )
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
        if slice_id == "NONE":
            fail("slice actions require an exact slice_id")
        if slice_id not in next_action["summary"]:
            fail("a slice next action must name its exact slice_id")
    elif slice_id != "NONE":
        fail("release, wait and completion actions use slice_id NONE")
    if kind == "START_NEXT_SLICE":
        if active or blocked or not planned or slice_id != planned[0]["id"]:
            fail("START_NEXT_SLICE must select the first planned slice")
        prior_terminal = slices[: slices.index(planned[0])]
        if prior_terminal:
            previous = prior_terminal[-1]
            if previous["state"] == "MERGED":
                if event != "PR_MERGED" or observed_ref != previous["merge_sha"]:
                    fail("sequential continuation requires its exact merge event")
            elif event != "SLICE_CANCELLED" or observed_ref != previous["issue"]:
                fail("continuation after cancellation requires its exact issue event")
        elif event != "INITIAL_AUTHORIZATION":
            fail("the first slice starts only from initial authorization")
    if kind in {"CONTINUE_ACTIVE_SLICE", "MERGE_ACTIVE_SLICE"} and (
        len(active) != 1 or slice_id != active[0]["id"]
    ):
        fail("the pending action must bind the one active slice")
    if kind == "MERGE_ACTIVE_SLICE" and (
        event != "GATES_PASSED" or observed_ref != active[0]["head_sha"]
    ):
        fail("merge continuation requires exact-head passed-gate evidence")
    release_actions = {
        "PREPARE_RELEASE",
        "PUBLISH_RELEASE",
        "VERIFY_RELEASE",
        "VERIFY_PRODUCTION",
        "RECORD_CHECKPOINT",
    }
    if kind in release_actions and unfinished:
        fail("release-boundary actions require all slices to be terminal")
    publication = train["publication_state"]
    if kind in release_actions and (
        campaign["workstream_class"] != "PRODUCT" or risk != "PUBLIC_ARTIFACT"
    ):
        fail("release-boundary actions require a public-artifact product campaign")
    if kind == "PREPARE_RELEASE" and publication != "UNPUBLISHED":
        fail("release preparation starts from an unpublished train")
    if kind == "PUBLISH_RELEASE" and (
        publication != "CANDIDATE"
        or event != "RELEASE_CANDIDATE_MERGED"
        or observed_ref != train["build_sha"]
    ):
        fail("publication needs its merged exact-build candidate")
    if kind == "VERIFY_RELEASE" and (
        publication != "PUBLISHED"
        or event != "RELEASE_PUBLISHED"
        or observed_ref != f"release:v{train['published_version']}"
    ):
        fail("release verification needs its exact publication event")
    if kind == "VERIFY_PRODUCTION" and risk != "REVERSIBLE_PRODUCTION":
        fail("production verification is outside the local Core risk profile")
    if kind == "RECORD_CHECKPOINT":
        if publication != "PUBLISHED" or checkpoint["state"] != "DUE":
            fail("checkpoint recording occurs once after publication verification")
        if (
            event != "RELEASE_VERIFIED"
            or observed_ref != f"release:v{train['published_version']}"
        ):
            fail("checkpoint recording needs its exact release verification")

    if state == "BLOCKED":
        if stop not in BLOCKED_REASONS or not blocked:
            fail("BLOCKED requires a blocked slice and a closed blocker reason")
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
        if mode == "RELEASE_TRAIN" and (
            publication != "PUBLISHED" or checkpoint["state"] != "RECORDED"
        ):
            fail("a completed train needs a published build and release checkpoint")
        if mode == "SINGLE_SLICE" and (
            publication != "UNPUBLISHED" or checkpoint["state"] != "NOT_DUE"
        ):
            fail("a completed single-slice campaign must remain unreleased")
    if checkpoint["state"] == "RECORDED" and checkpoint["reference"] != owner_issue:
        fail("the release checkpoint must bind the campaign owner issue")
    if state in {"PLANNED", "ACTIVE"} and kind in {"WAIT_FOR_EVENT", "NO_ACTION"}:
        fail("executable campaign states need an executable pending action")

    expected = expected_next_type(campaign)
    if next_type != expected:
        fail(f"next_action.type must be {expected}")
    if (next_type == "USER_ACTION_REQUIRED") == (prompt == "NONE"):
        fail("only USER_ACTION_REQUIRED carries an exact next prompt")
    return campaign


def render_handoff(value: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"Outcome: {value['outcome']}.",
            f"Delivered: {value['delivered']}",
            f"Release: {value['release_status']}.",
            (
                f"Next action [{value['next_action_type']}]: "
                f"{value['next_action']}"
            ),
            f"Prompt: {value['next_prompt']}",
        ]
    )


def word_count(value: str) -> int:
    return len(re.findall(r"\S+", value))


def validate_handoff(value: Any) -> dict[str, Any]:
    handoff = exact_object(value, "handoff", HANDOFF_KEYS)
    if handoff["schema_version"] != SCHEMA_VERSION:
        fail("handoff schema_version mismatch")
    if handoff["protocol_version"] != PROTOCOL_VERSION:
        fail("handoff protocol_version mismatch")
    one_line(handoff["campaign_id"], "handoff.campaign_id", maximum=100)
    outcome = closed(handoff["outcome"], "handoff.outcome", HANDOFF_OUTCOMES)
    one_line(handoff["delivered"], "handoff.delivered", maximum=500)
    closed(handoff["release_status"], "handoff.release_status", RELEASE_STATUSES)
    next_type = closed(
        handoff["next_action_type"],
        "handoff.next_action_type",
        NEXT_ACTION_TYPES,
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
        fail("a blocked handoff requires one user action")
    if outcome == "CAMPAIGN_COMPLETE" and next_type != "CAMPAIGN_COMPLETE":
        fail("campaign completion must be explicit")
    if next_type == "CAMPAIGN_COMPLETE" and outcome != "CAMPAIGN_COMPLETE":
        fail("only campaign completion may use CAMPAIGN_COMPLETE")
    return handoff


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"unable to read JSON evidence: {exc}") from exc
    if not isinstance(value, dict):
        fail("JSON evidence must be an object")
    return value


def sample_campaign() -> dict[str, Any]:
    merged = "1" * 40
    return {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "repository": REPOSITORY,
        "campaign_id": "pilot-1",
        "owner_issue": "#164",
        "campaign_mode": "RELEASE_TRAIN",
        "campaign_state": "ACTIVE",
        "workstream_class": "PRODUCT",
        "authority_envelope": "THROUGH_MERGE",
        "risk_profile": "PUBLIC_ARTIFACT",
        "auto_continuation": "SEQUENTIAL",
        "checkpoint": {
            "policy": "RELEASE_BOUNDARY",
            "state": "NOT_DUE",
            "reference": "NONE",
        },
        "idea_inbox": {
            "mode": "GITHUB_ISSUES_ONLY",
            "scope": "FROZEN_UNTIL_RELEASE_BOUNDARY",
            "items": ["#99"],
        },
        "train": {
            "train_id": "pilot-train",
            "target_version": "1.0.0",
            "publication_state": "UNPUBLISHED",
            "published_version": "NONE",
            "build_sha": "NONE",
        },
        "slices": [
            {
                "id": "pilot/S01",
                "state": "MERGED",
                "issue": "#1",
                "pr": "#2",
                "head_sha": "2" * 40,
                "merge_sha": merged,
            },
            {
                "id": "pilot/S02",
                "state": "PLANNED",
                "issue": "#3",
                "pr": "NONE",
                "head_sha": "NONE",
                "merge_sha": "NONE",
            },
        ],
        "observed_event": "PR_MERGED",
        "observed_event_ref": merged,
        "pending_action": {"kind": "START_NEXT_SLICE", "slice_id": "pilot/S02"},
        "stop_reason": "NONE",
        "next_action": {
            "type": "AUTO_CONTINUE",
            "summary": "Start pilot/S02 from the reconciled merge.",
            "prompt": "NONE",
        },
    }


def sample_handoff() -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": 1,
        "protocol_version": PROTOCOL_VERSION,
        "campaign_id": "pilot-1",
        "outcome": "DELIVERED",
        "delivered": "The slice merged and exact-head gates passed.",
        "release_status": "TRAIN_ACTIVE",
        "next_action_type": "AUTO_CONTINUE",
        "next_action": "Start the next ordered slice.",
        "next_prompt": "NONE",
        "human_report": "",
    }
    value["human_report"] = render_handoff(value)
    return value


def self_test() -> None:
    validate_campaign(sample_campaign())
    validate_handoff(sample_handoff())
    invalid = sample_campaign()
    invalid["stop_reason"] = "MAYBE"
    try:
        validate_campaign(invalid)
    except ContractError:
        pass
    else:
        fail("self-test accepted an open stop reason")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("validate-campaign", "validate-handoff"):
        child = subparsers.add_parser(command)
        child.add_argument("path", type=Path)
    subparsers.add_parser("self-test")
    args = parser.parse_args()
    try:
        if args.command == "self-test":
            self_test()
            result = {"protocol_version": PROTOCOL_VERSION, "result": "PASS"}
        elif args.command == "validate-campaign":
            campaign = validate_campaign(load_object(args.path))
            result = {
                "next_action_type": campaign["next_action"]["type"],
                "protocol_version": PROTOCOL_VERSION,
                "result": "PASS",
                "stop_reason": campaign["stop_reason"],
            }
        else:
            handoff = validate_handoff(load_object(args.path))
            result = {
                "protocol_version": PROTOCOL_VERSION,
                "result": "PASS",
                "word_count": word_count(handoff["human_report"]),
            }
    except ContractError as exc:
        print(json.dumps({"result": "BLOCKED", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
