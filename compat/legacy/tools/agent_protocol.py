#!/usr/bin/env python3
"""Stateless v1.2 gates, v1.2.1 change control, and active governance metadata."""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

PROTOCOL_VERSION = "1.2"
SCHEMA_VERSION = 2
CHANGE_CONTROL_VERSION = "1.2.1"
CHANGE_CONTROL_SCHEMA_VERSION = 1
GOVERNANCE_RELEASE = "1.4.2"
REPOSITORY = "gabned/provelume"
DEFAULT_BRANCH = "main"
MAX_EVIDENCE_AGE = timedelta(minutes=15)
CLOCK_SKEW = timedelta(seconds=30)
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
PR_PATTERN = re.compile(r"#[1-9][0-9]*")
WORKSTREAM_PATTERN = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")
LOGIN_PATTERN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
WITHDRAWAL_REFERENCE_PATTERN = re.compile(
    r"(?:https://github[.]com/(?P<url_repository>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/"
    r"(?:pull|issues)/(?P<url_pr>[1-9][0-9]*)#issuecomment-[1-9][0-9]*|"
    r"(?P<compact_repository>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)"
    r"#(?P<compact_pr>[1-9][0-9]*)@comment-[1-9][0-9]*)"
)
WORKSTREAM_CLASS_PATTERN = re.compile(
    r"(?m)^WORKSTREAM_CLASS:[ \t]*([^\r\n]+?)[ \t]*\r?$"
)
PROTOCOL_ESCALATION_PATTERN = re.compile(
    r"(?m)^PROTOCOL_ESCALATION:[ \t]*([^\r\n]+?)[ \t]*\r?$"
)
WAIVER_PATTERN = re.compile(
    r"<!--\s*PROTOCOL_EMERGENCY_WAIVER\s*\n(.*?)\n"
    r"PROTOCOL_EMERGENCY_WAIVER\s*-->",
    re.DOTALL,
)
POLICIES = {"NO_PRODUCTION", "REPOSITORY_POLICY"}
SOURCES = {"LOCAL_GIT", "GITHUB_CONNECTOR"}
SAFE_PROTOCOL_PATHS = {
    ".github/agent-protocol/transfer-v1.5.0.json",
    ".github/agent-protocol/documents-v1.5.0.json",
    "docs/agent-development-v1.5.0.md",
    "tools/agent_protocol_transfer.py",
    "tests/test_agent_protocol_transfer.py",
    "tools/agent_protocol_v2.py",
    "tests/test_agent_protocol_v2.py",
    ".github/agent-protocol/documents-v1.4.9.json",
    "docs/agent-development-v1.4.9.md",
    "tools/agent_protocol_v1_4_9.py",
    "tests/test_agent_protocol_v1_4_9.py",
    ".github/agent-protocol/documents-v1.4.8.json",
    "docs/agent-development-v1.4.8.md",
    ".github/agent-protocol/documents-v1.4.7.json",
    "docs/agent-development-v1.4.7.md",
    "tools/agent_protocol_v1_4_7.py",
    "tests/test_agent_protocol_v1_4_7.py",
    "docs/agent-development-v1.4.6-work.md",
    "docs/agent-development-v1.4.5-work.md",
    "tests/test_agent_protocol_work_recovery.py",
    "tools/agent_protocol_work_recovery.py",
    'tests/test_agent_protocol_work_check.py',
    'tools/agent_protocol_work_check.py',
    'docs/agent-development-v1.4.3-work.md',
    'tools/agent_protocol_work_source.py',
    'tools/agent_protocol_work_collect.mjs',
    'tests/test_agent_protocol_work_source.py',
    'tests/test_agent_protocol_work_collect.mjs',
    "docs/agent-development-v1.4.2.md",
    "tests/test_agent_protocol_v1_4_2_ops.py",
    "tools/agent_protocol_v1_4_2.py",
    "tools/agent_protocol_v1_4_2_ops.py",
    ".github/agent-protocol/conformance-v1.4.1.json",
    ".github/workflows/ci.yml",
    ".github/pull_request_template.md",
    ".gitignore",
    "AGENTS.md",
    "docs/agent-development-v1.2.md",
    "docs/agent-development-v1.2.1.md",
    "docs/agent-development-v1.3.0.md",
    "docs/agent-development-v1.4.0.md",
    "docs/agent-development-v1.4.1.md",
    "tests/test_agent_protocol_v1_2.py",
    "tests/test_agent_protocol_v1_2_1.py",
    "tests/test_agent_protocol_v1_4.py",
    "tests/test_agent_protocol_v1_4_1.py",
    "tools/agent_protocol.py",
    "tools/agent_protocol_v1_4.py",
    "tools/agent_protocol_v1_4_1.py",
}
WORKSTREAM_CLASSES = {"PRODUCT", "PROTOCOL"}
PROTECTED_PROTOCOL_EXACT = {
    ".github/agent-protocol/conformance-v1.4.1.json",
    ".github/CODEOWNERS",
    ".github/pull_request_template.md",
    ".github/workflows/ci.yml",
    ".gitignore",
    "AGENTS.md",
    "docs/agent-development-v1.2.md",
    "docs/agent-development-v1.2.1.md",
    "docs/agent-development-v1.3.0.md",
    "docs/agent-development-v1.4.0.md",
    "docs/agent-development-v1.4.1.md",
    "tests/test_agent_protocol_v1_2.py",
    "tests/test_agent_protocol_v1_2_1.py",
    "tests/test_agent_protocol_v1_4.py",
    "tests/test_agent_protocol_v1_4_1.py",
    "tools/agent_protocol.py",
    "tools/agent_protocol_v1_4.py",
    "tools/agent_protocol_v1_4_1.py",
}
PROTECTED_PROTOCOL_PREFIXES = (
    ".github/agent-protocol/",
    "docs/agent-development-v",
    "tests/test_agent_protocol_",
    "tools/agent_protocol",
)
PATH_CATEGORIES = {
    "FORBIDDEN_GLOBAL_STATE",
    "PRODUCT_SURFACE",
    "PROTOCOL_SURFACE",
}
FINDING_CODES = {
    "MIXED_SCOPE_DETECTED",
    "PRODUCT_SURFACE_CHANGED",
    "PROTOCOL_DEFECT_SUSPECTED",
    "PROTOCOL_SURFACE_CHANGED",
    "WAIVER_REQUESTED",
}
ESCALATION_VALUES = {"NONE", *FINDING_CODES}
BLOCKER_CODES = {
    "CHANGESET_UNKNOWN",
    "CONNECTOR_EVIDENCE_INVALID",
    "GLOBAL_STATE_FORBIDDEN",
    "MIXED_SCOPE",
    "PR_CLASS_AMBIGUOUS",
    "PR_CLASS_INVALID",
    "PR_CLASS_MISSING",
    "PRODUCT_TOUCHES_PROTOCOL",
    "PROTOCOL_ESCALATION_INVALID",
    "PROTOCOL_ESCALATION_REQUIRED",
    "PROTOCOL_TOUCHES_PRODUCT",
    "WAIVER_BLOCKER_NOT_WAIVABLE",
    "WAIVER_HEAD_MISMATCH",
    "WAIVER_INVALID",
    "WAIVER_NOT_HUMAN",
}
WAIVABLE_BLOCKER_CODES = {
    "MIXED_SCOPE",
    "PRODUCT_TOUCHES_PROTOCOL",
    "PROTOCOL_ESCALATION_REQUIRED",
    "PROTOCOL_TOUCHES_PRODUCT",
}
WAIVER_REASON_CODES = {
    "EMERGENCY_COMPLIANCE",
    "EMERGENCY_PRODUCTION_RESTORE",
    "EMERGENCY_SECURITY_RESPONSE",
}
REVIEW_REQUIREMENT_SOURCES = {
    "REPOSITORY",
    "EXPLICIT_MAINTAINER",
    "NONE",
    "UNKNOWN",
}
CODEX_REVIEW_STATES = {
    "NOT_REQUESTED",
    "PENDING",
    "CLEAN",
    "FINDINGS",
    "WITHDRAWN",
    "UNAVAILABLE",
    "UNKNOWN",
}
CODEX_REVIEW_SIGNALS = {
    "NONE",
    "EYES",
    "COMMENTED",
    "CLEAN",
    "FINDINGS",
    "UNKNOWN",
}
REPOSITORY_REVIEW_STATES = {
    "NOT_APPLICABLE",
    "SATISFIED",
    "BLOCKED",
    "UNKNOWN",
}
TECHNICAL_FINDING_STATES = {"NONE", "CURRENT", "UNKNOWN"}
WAIVER_FIELDS = {
    "active",
    "approver_login",
    "approver_type",
    "change_control_version",
    "credentials_accessed",
    "head_sha",
    "human_only",
    "mode",
    "owner_pr",
    "production_environment_accessed",
    "reason_code",
    "repository",
    "schema_version",
    "source",
    "static",
    "waived_blocker_codes",
}
PRODUCTION_EXACT = {
    "CHANGELOG.md",
    "pyproject.toml",
    "requirements-release.txt",
}
PRODUCTION_PREFIXES = ("core/", "release/", "scripts/")


class ContractError(ValueError):
    """Raised when protocol evidence is incomplete, open, stale or inconsistent."""


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fail(message: str) -> None:
    raise ContractError(message)


def parse_time(value: Any) -> datetime:
    text = str(value or "")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError as exc:
        raise ContractError("timestamp must be RFC3339") from exc
    if parsed.tzinfo is None:
        fail("timestamp must include a timezone")
    return parsed.astimezone(UTC)


def require_fresh(value: Any) -> None:
    observed = parse_time(value)
    current = datetime.now(UTC)
    if observed > current + CLOCK_SKEW:
        fail("evidence timestamp is in the future")
    if current - observed > MAX_EVIDENCE_AGE:
        fail("evidence is outside the fifteen-minute replay window")


def require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA_PATTERN.fullmatch(value) is None:
        fail(f"{label} must be an exact lowercase 40-character SHA")
    return value


def require_choice(value: Any, label: str, allowed: set[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        fail(f"{label} has unsupported value {value!r}")
    return value


def require_pr(value: Any, label: str = "owner_pr") -> str:
    if not isinstance(value, str) or PR_PATTERN.fullmatch(value) is None:
        fail(f"{label} must use exact #123 form")
    return value


def derive_codex_review_state(
    *,
    requested: bool,
    available: bool,
    signal: str,
    current_head: str,
    reviewed_head: str | None = None,
    withdrawn: bool = False,
    current_technical_finding: bool = False,
) -> str:
    for value, label in (
        (requested, "requested"),
        (available, "available"),
        (withdrawn, "withdrawn"),
        (current_technical_finding, "current technical finding"),
    ):
        if type(value) is not bool:
            raise ContractError(f"{label} must be boolean")
    require_choice(signal, "Codex review signal", CODEX_REVIEW_SIGNALS)
    require_sha(current_head, "current_head")
    if current_technical_finding or signal == "FINDINGS":
        return "FINDINGS"
    if withdrawn:
        if not requested:
            raise ContractError("an unrequested review cannot be withdrawn")
        return "WITHDRAWN"
    if not requested:
        return "NOT_REQUESTED"
    if not available:
        return "UNAVAILABLE"
    if signal == "CLEAN":
        return "CLEAN" if reviewed_head == current_head else "UNKNOWN"
    if signal in {"NONE", "EYES", "COMMENTED"}:
        return "PENDING"
    return "UNKNOWN"


def validate_review_withdrawal(
    record: Any,
    *,
    repository: str,
    owner_pr: str,
    owner_head: str,
) -> bool:
    required = {
        "repository",
        "owner_pr",
        "owner_head_sha",
        "withdrawn_by",
        "comment_reference",
        "maintainer_verified",
    }
    if not isinstance(record, dict) or set(record) != required:
        raise ContractError("exact review-withdrawal record required")
    if (
        record["repository"] != repository
        or record["owner_pr"] != owner_pr
        or record["owner_head_sha"] != owner_head
    ):
        raise ContractError("review withdrawal scope mismatch")
    require_pr(record["owner_pr"])
    require_sha(record["owner_head_sha"], "owner_head_sha")
    login = record["withdrawn_by"]
    if (
        not isinstance(login, str)
        or LOGIN_PATTERN.fullmatch(login) is None
        or login.endswith("[bot]")
        or record["maintainer_verified"] is not True
    ):
        raise ContractError("verified human maintainer withdrawal required")
    reference = record["comment_reference"]
    match = (
        WITHDRAWAL_REFERENCE_PATTERN.fullmatch(reference)
        if isinstance(reference, str)
        else None
    )
    if match is None:
        raise ContractError("immutable withdrawal comment reference required")
    reference_repository = (
        match.group("url_repository") or match.group("compact_repository")
    )
    reference_pr = match.group("url_pr") or match.group("compact_pr")
    if reference_repository != repository or f"#{reference_pr}" != owner_pr:
        raise ContractError("withdrawal comment reference does not match the owner PR")
    return True


def evaluate_review_gate(
    *,
    source: str,
    codex_state: str,
    repository: str,
    owner_pr: str,
    current_head: str,
    reviewed_head: str | None = None,
    repository_review: str = "NOT_APPLICABLE",
    technical_finding: str = "NONE",
    withdrawal: dict[str, Any] | None = None,
    waiver: Any = None,
) -> dict[str, Any]:
    errors: list[str] = []
    for value, allowed, label in (
        (source, REVIEW_REQUIREMENT_SOURCES, "review requirement source"),
        (codex_state, CODEX_REVIEW_STATES, "Codex review state"),
        (repository_review, REPOSITORY_REVIEW_STATES, "repository review"),
        (technical_finding, TECHNICAL_FINDING_STATES, "technical finding"),
    ):
        try:
            require_choice(value, label, allowed)
        except ContractError as exc:
            errors.append(str(exc))
    try:
        require_pr(owner_pr)
        require_sha(current_head, "current_head")
    except ContractError as exc:
        errors.append(str(exc))

    clean_signal = False
    if waiver is not None:
        errors.append("review policy cannot create, extend or reuse a waiver")
    if source == "UNKNOWN" or codex_state == "UNKNOWN":
        errors.append("review decision evidence is UNKNOWN")
    if technical_finding != "NONE" or codex_state == "FINDINGS":
        errors.append("current technical finding blocks")

    codex_gate = "BLOCKED"
    if source == "NONE":
        if codex_state == "NOT_REQUESTED":
            codex_gate = "NOT_APPLICABLE"
        elif codex_state not in {"FINDINGS", "UNKNOWN"}:
            errors.append("Codex state is inconsistent with an unrequested review")
    elif source == "REPOSITORY":
        if repository_review == "SATISFIED" and codex_state == "NOT_REQUESTED":
            codex_gate = "NOT_APPLICABLE"
        elif repository_review != "SATISFIED":
            errors.append("GitHub-required review is not satisfied")
        else:
            errors.append("Codex state is inconsistent with a repository review")
    elif source == "EXPLICIT_MAINTAINER":
        if codex_state == "CLEAN":
            if reviewed_head == current_head:
                codex_gate = "SATISFIED"
                clean_signal = True
            else:
                errors.append("clean review is not bound to the current exact head")
        elif codex_state == "WITHDRAWN":
            try:
                validate_review_withdrawal(
                    withdrawal,
                    repository=repository,
                    owner_pr=owner_pr,
                    owner_head=current_head,
                )
                codex_gate = "WITHDRAWN"
            except ContractError as exc:
                errors.append(str(exc))
        elif codex_state not in {"FINDINGS", "UNKNOWN"}:
            errors.append("explicit Codex review has no terminal clean or withdrawal state")

    if source != "REPOSITORY" and repository_review in {"BLOCKED", "UNKNOWN"}:
        errors.append("repository review is blocked or UNKNOWN")
    if source == "REPOSITORY" and repository_review == "NOT_APPLICABLE":
        errors.append("repository review requirement cannot be not applicable")
    if source == "NONE" and repository_review != "NOT_APPLICABLE":
        errors.append("unrequested review must have no repository review gate")
    allowed = not errors
    return {
        "governance_release": GOVERNANCE_RELEASE,
        "lifecycle_schema": PROTOCOL_VERSION,
        "review_requirement_source": source,
        "codex_review_state": codex_state,
        "codex_gate": codex_gate if allowed else "BLOCKED",
        "clean_review_signal": clean_signal and allowed,
        "waiver_applied": False,
        "merge_allowed": allowed,
        "errors": errors,
    }


def require_workstream(value: Any) -> str:
    if not isinstance(value, str) or WORKSTREAM_PATTERN.fullmatch(value) is None:
        fail("workstream must be a closed slug")
    return value


def normalize_path(raw: str) -> str:
    if not isinstance(raw, str):
        fail("changed path must be text")
    value = raw.strip().replace("\\", "/")
    if not value or value == "UNKNOWN" or value.startswith("/"):
        fail("changed path is empty, absolute or UNKNOWN")
    normalized = PurePosixPath(value).as_posix()
    if normalized in {".", ".."} or normalized.startswith("../") or "/../" in normalized:
        fail("changed path escapes the repository")
    return normalized


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid JSON evidence {path}: {exc}") from exc
    if not isinstance(value, dict):
        fail(f"JSON evidence must be an object: {path}")
    return value


def load_value(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid JSON evidence {path}: {exc}") from exc


def write_object(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    unsigned = {key: value for key, value in payload.items() if key != "report_sha256"}
    return (
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def report_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def seal(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result["report_sha256"] = report_hash(result)
    return result


def verify_seal(payload: dict[str, Any]) -> None:
    observed = payload.get("report_sha256")
    if not isinstance(observed, str) or SHA256_PATTERN.fullmatch(observed) is None:
        fail("report_sha256 must be an exact lowercase SHA-256")
    if observed != report_hash(payload):
        fail("report_sha256 does not match the exact canonical report")


def classify_path(path: str) -> tuple[str, str | None]:
    if path in SAFE_PROTOCOL_PATHS:
        return "NO_PRODUCTION", None
    if path.startswith(".github/workflows/") or path.startswith(".github/actions/"):
        return "PRODUCTION", "WORKFLOW_OR_REUSABLE_ACTION"
    if path in PRODUCTION_EXACT:
        return "PRODUCTION", "RELEASE_IDENTITY_OR_DEPENDENCY"
    if any(path.startswith(prefix) for prefix in PRODUCTION_PREFIXES):
        return "PRODUCTION", "CORE_OR_RELEASE_PATH"
    return "PRODUCTION", "UNCLASSIFIED_PATH"


def connector_paths(payload: Any) -> list[str]:
    values = payload if isinstance(payload, list) else None
    if isinstance(payload, dict):
        values = payload.get("changed_files")
    if not isinstance(values, list):
        fail("connector input must be a list or contain changed_files")
    result: list[str] = []
    for item in values:
        if isinstance(item, str):
            result.append(item)
            continue
        if not isinstance(item, dict):
            fail("invalid connector changed-file entry")
        previous = item.get("previous_path")
        if isinstance(previous, str):
            result.append(previous)
        current = item.get("path") if isinstance(item.get("path"), str) else item.get("filename")
        if isinstance(current, str):
            result.append(current)
        elif not isinstance(previous, str):
            fail("connector changed-file entry has no path")
    return result


def read_changed_paths(path: Path) -> list[str]:
    try:
        values = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ContractError(f"unable to read changed paths: {exc}") from exc
    return [value for value in values if value.strip()]


def read_name_status(path: Path) -> list[str]:
    try:
        tokens = path.read_bytes().split(b"\0")
    except OSError as exc:
        raise ContractError(f"unable to read name-status evidence: {exc}") from exc
    if tokens and tokens[-1] == b"":
        tokens.pop()
    result: list[str] = []
    index = 0
    while index < len(tokens):
        try:
            status = tokens[index].decode("ascii")
        except UnicodeDecodeError as exc:
            raise ContractError("name-status code must be ASCII") from exc
        index += 1
        if not status or status[0] not in {"A", "C", "D", "M", "R", "T", "U", "X", "B"}:
            fail("name-status evidence contains an unsupported status")
        path_count = 2 if status[0] in {"C", "R"} else 1
        if index + path_count > len(tokens):
            fail("name-status evidence is truncated")
        for raw in tokens[index : index + path_count]:
            try:
                result.append(raw.decode("utf-8"))
            except UnicodeDecodeError as exc:
                raise ContractError("changed path must be UTF-8") from exc
        index += path_count
    return result


def change_control_path_category(path: str) -> str:
    normalized = normalize_path(path)
    if (
        PurePosixPath(normalized).name == "AGENT_STATUS.md"
        or normalized == ".agent"
        or normalized.startswith(".agent/")
    ):
        return "FORBIDDEN_GLOBAL_STATE"
    if normalized in PROTECTED_PROTOCOL_EXACT or any(
        normalized.startswith(prefix) for prefix in PROTECTED_PROTOCOL_PREFIXES
    ):
        return "PROTOCOL_SURFACE"
    return "PRODUCT_SURFACE"


def parse_workstream_class(body: str) -> tuple[str, list[str]]:
    matches = [value.strip() for value in WORKSTREAM_CLASS_PATTERN.findall(body)]
    if not matches:
        return "UNKNOWN", ["PR_CLASS_MISSING"]
    if len(matches) != 1:
        return "UNKNOWN", ["PR_CLASS_AMBIGUOUS"]
    if matches[0] not in WORKSTREAM_CLASSES:
        return "UNKNOWN", ["PR_CLASS_INVALID"]
    return matches[0], []


def parse_escalation_marker(body: str) -> tuple[str, list[str]]:
    matches = [value.strip() for value in PROTOCOL_ESCALATION_PATTERN.findall(body)]
    if not matches:
        return "NONE", []
    if len(matches) != 1 or matches[0] not in ESCALATION_VALUES:
        return "UNKNOWN", ["PROTOCOL_ESCALATION_INVALID"]
    return matches[0], []


def extract_emergency_waiver(body: str) -> tuple[dict[str, Any] | None, list[str]]:
    matches = WAIVER_PATTERN.findall(body)
    if not matches:
        if "PROTOCOL_EMERGENCY_WAIVER" in body:
            return None, ["WAIVER_INVALID"]
        return None, []
    if len(matches) != 1:
        return None, ["WAIVER_INVALID"]
    try:
        value = json.loads(matches[0])
    except json.JSONDecodeError:
        return None, ["WAIVER_INVALID"]
    if not isinstance(value, dict):
        return None, ["WAIVER_INVALID"]
    return value, []


def event_pr_identity(event: dict[str, Any]) -> dict[str, str]:
    pull_request = event.get("pull_request")
    repository = event.get("repository")
    if not isinstance(pull_request, dict) or not isinstance(repository, dict):
        fail("connector event must contain pull_request and repository objects")
    number = event.get("number")
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        fail("connector event PR number is invalid")
    base = pull_request.get("base")
    head = pull_request.get("head")
    if not isinstance(base, dict) or not isinstance(head, dict):
        fail("connector event must contain base and head objects")
    return {
        "repository": str(repository.get("full_name", "")),
        "owner_pr": f"#{number}",
        "base_sha": require_sha(base.get("sha"), "event base_sha"),
        "head_sha": require_sha(head.get("sha"), "event head_sha"),
        "body": str(pull_request.get("body") or ""),
    }


def bind_current_pr_body(
    event: dict[str, Any], current_pr: dict[str, Any]
) -> dict[str, Any]:
    """Bind the current public PR body after proving its event identity."""
    identity = event_pr_identity(event)
    if not isinstance(current_pr, dict):
        fail("current PR metadata must be an object")
    if current_pr.get("number") != int(identity["owner_pr"].removeprefix("#")):
        fail("current PR number does not match the event")
    base = current_pr.get("base")
    head = current_pr.get("head")
    if not isinstance(base, dict) or not isinstance(head, dict):
        fail("current PR metadata must contain base and head objects")
    if base.get("sha") != identity["base_sha"]:
        fail("current PR base does not match the event")
    if head.get("sha") != identity["head_sha"]:
        fail("current PR head does not match the event")
    body = current_pr.get("body")
    if not isinstance(body, str):
        fail("current PR body must be a string")
    bound = copy.deepcopy(event)
    bound["pull_request"]["body"] = body
    return bound


def build_effect_report(
    *,
    base_sha: str,
    head_sha: str,
    changed_paths: list[str],
    policy: str,
    source: str,
    complete: bool,
    observed_at: str | None = None,
) -> dict[str, Any]:
    stamp = observed_at or now_utc()
    errors: list[str] = []
    if source not in SOURCES:
        errors.append("source uses an unsupported identifier")
    if policy not in POLICIES:
        errors.append("policy uses an unsupported identifier")
    if not isinstance(base_sha, str) or SHA_PATTERN.fullmatch(base_sha) is None:
        errors.append("base_sha must be exact")
    if not isinstance(head_sha, str) or SHA_PATTERN.fullmatch(head_sha) is None:
        errors.append("head_sha must be exact")
    try:
        parse_time(stamp)
        normalized = sorted({normalize_path(path) for path in changed_paths})
    except ContractError as exc:
        normalized = []
        errors.append(str(exc))
    if not complete:
        errors.append("changed-path enumeration is incomplete")
    if not normalized:
        errors.append("changed_paths must be non-empty")

    matches: list[dict[str, str]] = []
    if not errors:
        for path in normalized:
            effect, identifier = classify_path(path)
            if effect == "PRODUCTION" and identifier is not None:
                matches.append({"identifier": identifier, "path": path})
    effect = "UNKNOWN" if errors else ("PRODUCTION" if matches else "NO_PRODUCTION")
    bind_allowed = not errors and effect != "UNKNOWN" and (
        policy == "REPOSITORY_POLICY" or effect == "NO_PRODUCTION"
    )
    return seal(
        {
            "schema_version": SCHEMA_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "mode": "PREDICT",
            "source": source,
            "repository": REPOSITORY,
            "observed_at": stamp,
            "base_sha": base_sha,
            "head_sha": head_sha,
            "policy": policy,
            "complete": complete,
            "changed_paths": normalized,
            "effect": effect,
            "matches": matches,
            "bind_allowed": bind_allowed,
            "errors": errors,
        }
    )


def verify_effect_report(
    report: dict[str, Any], *, base_sha: str, head_sha: str, policy: str
) -> None:
    verify_seal(report)
    expected_identity = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "mode": "PREDICT",
        "repository": REPOSITORY,
        "base_sha": require_sha(base_sha, "base_sha"),
        "head_sha": require_sha(head_sha, "head_sha"),
        "policy": require_choice(policy, "policy", POLICIES),
    }
    for key, value in expected_identity.items():
        if report.get(key) != value:
            fail(f"effect report {key} mismatch")
    paths = report.get("changed_paths")
    if not isinstance(paths, list) or any(not isinstance(path, str) for path in paths):
        fail("effect report changed_paths must be a string list")
    source = require_choice(report.get("source"), "source", SOURCES)
    complete = report.get("complete")
    if not isinstance(complete, bool):
        fail("effect report complete must be boolean")
    recomputed = build_effect_report(
        base_sha=base_sha,
        head_sha=head_sha,
        changed_paths=paths,
        policy=policy,
        source=source,
        complete=complete,
        observed_at=str(report.get("observed_at", "")),
    )
    if report != recomputed:
        fail("effect report classifications or authorization do not match the exact path set")
    if report.get("effect") == "UNKNOWN" or report.get("bind_allowed") is not True:
        fail("effect report does not authorize PR binding")


def policy_module():
    spec = importlib.util.spec_from_file_location(
        "protocol_policy", Path(__file__).with_name("agent_protocol_v1_4_9.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_binding(
    report: dict[str, Any], *, active_pr: str, workstream: str,
    workstream_class: str, adopted_contract: dict[str, Any], trusted_contract: str,
    production_authority: dict[str, bool],
) -> dict[str, Any]:
    base_sha = require_sha(report.get("base_sha"), "base_sha")
    head_sha = require_sha(report.get("head_sha"), "head_sha")
    policy = require_choice(report.get("policy"), "policy", POLICIES)
    verify_effect_report(report, base_sha=base_sha, head_sha=head_sha, policy=policy)
    if adopted_contract.get("repository") != REPOSITORY:
        fail("INPUT_MISMATCH: adopted routing repository mismatch")
    try:
        decision = policy_module().require_policy_coherence(
            contract=adopted_contract, trusted_contract=trusted_contract,
            workstream=workstream, workstream_class=workstream_class,
            selected_policy=policy, observed_effects=report["effect"],
            production_authority=production_authority,
        )
    except ValueError as error:
        fail(str(error))
    return seal(
        {
            "schema_version": SCHEMA_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "mode": "BIND",
            "repository": REPOSITORY,
            "observed_at": now_utc(),
            "active_pr": require_pr(active_pr, "active_pr"),
            "workstream": require_workstream(workstream),
            "base_sha": base_sha,
            "binding_basis_sha": head_sha,
            "effect_report_sha256": report["report_sha256"],
            "effect_policy": policy,
            "effect_prediction": report["effect"],
            "adopted_contract": copy.deepcopy(adopted_contract),
            "policy_resolution": decision,
            "state": "BOUND",
            "errors": [],
        }
    )


def validate_binding(binding: dict[str, Any], policy_context=None) -> None:
    verify_seal(binding)
    expected = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "mode": "BIND",
        "repository": REPOSITORY,
        "state": "BOUND",
        "errors": [],
    }
    for key, value in expected.items():
        if binding.get(key) != value:
            fail(f"binding {key} mismatch")
    require_pr(binding.get("active_pr"), "active_pr")
    require_workstream(binding.get("workstream"))
    require_sha(binding.get("base_sha"), "base_sha")
    require_sha(binding.get("binding_basis_sha"), "binding_basis_sha")
    require_choice(binding.get("effect_policy"), "effect_policy", POLICIES)
    require_choice(
        binding.get("effect_prediction"),
        "effect_prediction",
        {"NO_PRODUCTION", "PRODUCTION"},
    )
    digest = binding.get("effect_report_sha256")
    if not isinstance(digest, str) or SHA256_PATTERN.fullmatch(digest) is None:
        fail("binding effect_report_sha256 is invalid")
    # Every fresh gate uses independently selected current routing. An unkeyed
    # seal and a decision embedded in the candidate cannot supply that authority.
    if policy_context is None:
        fail("STALE_EVIDENCE: binding needs current adopted routing evidence; "
             "collect policy_context with the ordinary snapshot, do not rebind")
    try:
        if policy_context["contract"]["repository"] != REPOSITORY:
            fail("INPUT_MISMATCH: current routing repository mismatch")
        policy_module().require_policy_coherence(
            **policy_context, workstream=binding["workstream"],
            selected_policy=binding["effect_policy"],
            observed_effects=binding["effect_prediction"],
        )
    except (ValueError, TypeError, KeyError) as error:
        fail(str(error))
    if "policy_resolution" not in binding and "adopted_contract" not in binding:
        return
    try:
        decision = binding["policy_resolution"]
        contract = binding["adopted_contract"]
        if contract["repository"] != REPOSITORY:
            fail("binding adopted routing repository mismatch")
        expected_decision = policy_module().require_policy_coherence(
            contract=contract, trusted_contract=decision["contract_sha256"],
            workstream=binding["workstream"], workstream_class=decision["workstream_class"],
            selected_policy=binding["effect_policy"], observed_effects=binding["effect_prediction"],
            production_authority=decision["production_authority"],
        )
        if decision != expected_decision:
            fail("binding policy decision drift")
    except (ValueError, KeyError, TypeError) as error:
        fail(f"BOUND_TERMINAL: current policy proof missing or inconsistent: {error}; "
             "historical bindings retain their original validator; use typed recovery "
             "only for a proven policy mismatch")


def validate_snapshot_identity(snapshot: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    expected = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "mode": "SNAPSHOT",
        "source": "GITHUB_CONNECTOR",
        "repository": REPOSITORY,
        "default_branch": DEFAULT_BRANCH,
    }
    for key, value in expected.items():
        if snapshot.get(key) != value:
            errors.append(f"snapshot {key} mismatch")
    try:
        verify_seal(snapshot)
    except ContractError as exc:
        errors.append(str(exc))
    try:
        require_fresh(snapshot.get("observed_at"))
    except ContractError as exc:
        errors.append(str(exc))
    return errors


def normalize_review_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Normalize an unambiguous lifecycle-v1.2 connector into v1.3 governance."""

    v13_keys = {
        "review_requirement_source",
        "codex_review_state",
        "repository_review",
        "technical_finding",
        "codex_reviewed_head",
        "codex_review_withdrawal",
    }
    if any(key in snapshot for key in v13_keys):
        return {
            "source": snapshot.get("review_requirement_source", "UNKNOWN"),
            "codex_state": snapshot.get("codex_review_state", "UNKNOWN"),
            "repository_review": snapshot.get("repository_review", "UNKNOWN"),
            "technical_finding": snapshot.get("technical_finding", "UNKNOWN"),
            "reviewed_head": snapshot.get("codex_reviewed_head"),
            "withdrawal": snapshot.get("codex_review_withdrawal"),
            "adapter": "V1_3_NATIVE",
        }

    requires_approval = snapshot.get("requires_approval", "UNKNOWN")
    review = snapshot.get("review", "UNKNOWN")
    if requires_approval not in {"TRUE", "FALSE", "UNKNOWN"} or review not in {
        "APPROVED",
        "CHANGES_REQUESTED",
        "NONE",
        "UNKNOWN",
    }:
        requires_approval = "UNKNOWN"
    technical_finding = "CURRENT" if review == "CHANGES_REQUESTED" else "NONE"
    if requires_approval == "FALSE":
        source = "NONE"
        repository_review = "NOT_APPLICABLE"
    elif requires_approval == "TRUE":
        source = "REPOSITORY"
        repository_review = "SATISFIED" if review == "APPROVED" else "BLOCKED"
    else:
        source = "UNKNOWN"
        repository_review = "UNKNOWN"
        technical_finding = "UNKNOWN"
    return {
        "source": source,
        "codex_state": "NOT_REQUESTED" if source != "UNKNOWN" else "UNKNOWN",
        "repository_review": repository_review,
        "technical_finding": technical_finding,
        "reviewed_head": None,
        "withdrawal": None,
        "adapter": "LIFECYCLE_V1_2_COMPATIBILITY",
    }


def preflight(snapshot: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    errors = validate_snapshot_identity(snapshot)
    try:
        validate_binding(binding, snapshot.get("policy_context"))
    except ContractError as exc:
        errors.append(str(exc))

    for key in ("default_sha", "base_sha", "head_sha", "binding_basis_sha"):
        try:
            require_sha(snapshot.get(key), key)
        except ContractError as exc:
            errors.append(str(exc))
    try:
        require_pr(snapshot.get("owner_pr"), "owner_pr")
    except ContractError as exc:
        errors.append(str(exc))

    comparisons = {
        "owner_pr": "active_pr",
        "base_sha": "base_sha",
        "binding_basis_sha": "binding_basis_sha",
        "effect_report_sha256": "effect_report_sha256",
    }
    for snapshot_key, binding_key in comparisons.items():
        if snapshot.get(snapshot_key) != binding.get(binding_key):
            errors.append(f"snapshot {snapshot_key} does not match binding")

    closed = {
        "pr_state": {"OPEN", "UNKNOWN"},
        "draft": {"TRUE", "FALSE", "UNKNOWN"},
        "checks": {"SUCCESS", "PENDING", "FAILURE", "NONE", "UNKNOWN"},
        "mergeability": {"MERGEABLE", "CONFLICTING", "UNKNOWN"},
        "base_ancestry": {"TRUE", "FALSE", "UNKNOWN"},
        "binding_basis_ancestor": {"TRUE", "FALSE", "UNKNOWN"},
    }
    for key, allowed in closed.items():
        if snapshot.get(key) not in allowed:
            errors.append(f"snapshot {key} is not a closed identifier")

    if snapshot.get("pr_state") != "OPEN":
        errors.append("owner PR is not OPEN")
    if snapshot.get("draft") != "FALSE":
        errors.append("owner PR is draft or UNKNOWN")
    if snapshot.get("checks") != "SUCCESS":
        errors.append("required checks are not successful")
    if snapshot.get("mergeability") != "MERGEABLE":
        errors.append("mergeability is not proven")
    if snapshot.get("base_ancestry") != "TRUE":
        errors.append("base ancestry is not proven")
    if snapshot.get("binding_basis_ancestor") != "TRUE":
        errors.append("binding-basis ancestry is not proven")

    unresolved = snapshot.get("unresolved_threads")
    if not isinstance(unresolved, int) or isinstance(unresolved, bool) or unresolved != 0:
        errors.append("unresolved thread count blocks or is UNKNOWN")

    review_input = normalize_review_snapshot(snapshot)
    review_result = evaluate_review_gate(
        source=str(review_input["source"]),
        codex_state=str(review_input["codex_state"]),
        repository=REPOSITORY,
        owner_pr=str(snapshot.get("owner_pr", "UNKNOWN")),
        current_head=str(snapshot.get("head_sha", "UNKNOWN")),
        reviewed_head=(
            review_input["reviewed_head"]
            if isinstance(review_input["reviewed_head"], str)
            else None
        ),
        repository_review=str(review_input["repository_review"]),
        technical_finding=str(review_input["technical_finding"]),
        withdrawal=(
            review_input["withdrawal"]
            if isinstance(review_input["withdrawal"], dict)
            else None
        ),
    )
    review_result["adapter"] = review_input["adapter"]
    errors.extend(review_result["errors"])

    if snapshot.get("credentials_accessed") is not False:
        errors.append("connector snapshot accessed credentials or is UNKNOWN")
    if snapshot.get("production_environment_accessed") is not False:
        errors.append("connector snapshot accessed production or is UNKNOWN")

    result = "READY" if not errors else "BLOCKED"
    return seal(
        {
            "schema_version": SCHEMA_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "mode": "PREFLIGHT",
            "repository": REPOSITORY,
            "observed_at": now_utc(),
            "result": result,
            "merge_ready": result == "READY",
            "review_governance": review_result,
            "errors": errors,
        }
    )


def reconcile(evidence: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    identity_errors: list[str] = []
    try:
        validate_binding(binding, evidence.get("policy_context"))
    except ContractError as exc:
        identity_errors.append(str(exc))
    expected = {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "mode": "RECONCILE_EVIDENCE",
        "source": "GITHUB_CONNECTOR",
        "repository": REPOSITORY,
        "default_branch": DEFAULT_BRANCH,
        "pr_state": "MERGED",
        "binding_basis_ancestor": "TRUE",
        "merge_sha_on_default": "TRUE",
        "production_action_performed": False,
    }
    for key, value in expected.items():
        if evidence.get(key) != value:
            identity_errors.append(f"evidence {key} mismatch")
    try:
        verify_seal(evidence)
    except ContractError as exc:
        identity_errors.append(str(exc))
    try:
        require_fresh(evidence.get("observed_at"))
    except ContractError as exc:
        identity_errors.append(str(exc))
    for key in ("default_sha", "merge_sha", "binding_basis_sha"):
        try:
            require_sha(evidence.get(key), key)
        except ContractError as exc:
            identity_errors.append(str(exc))
    try:
        require_pr(evidence.get("active_pr"), "active_pr")
    except ContractError as exc:
        identity_errors.append(str(exc))

    comparisons = {
        "active_pr": "active_pr",
        "binding_basis_sha": "binding_basis_sha",
        "effect_report_sha256": "effect_report_sha256",
    }
    for evidence_key, binding_key in comparisons.items():
        if evidence.get(evidence_key) != binding.get(binding_key):
            identity_errors.append(f"evidence {evidence_key} does not match binding")

    workflow = evidence.get("workflow_status")
    release = evidence.get("release_status")
    allowed_workflow = {"NOT_TRIGGERED", "PENDING", "SUCCEEDED", "FAILED", "UNKNOWN"}
    allowed_release = {"NOT_APPLICABLE", "NOT_TRIGGERED", "SUCCEEDED", "FAILED", "UNKNOWN"}
    observation_errors: list[str] = []
    if workflow not in allowed_workflow:
        observation_errors.append("workflow_status is not closed")
    if release not in allowed_release:
        observation_errors.append("release_status is not closed")

    if identity_errors or observation_errors or "UNKNOWN" in {workflow, release}:
        result = "UNKNOWN"
    elif "FAILED" in {workflow, release}:
        result = "FAILED"
    elif workflow == "PENDING":
        result = "PENDING"
    elif release == "SUCCEEDED":
        result = "SUCCEEDED"
    else:
        result = "NOT_TRIGGERED"

    return seal(
        {
            "schema_version": SCHEMA_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "mode": "RECONCILE",
            "repository": REPOSITORY,
            "observed_at": evidence.get("observed_at"),
            "result": result,
            "release_allowed": not identity_errors,
            "observational_only": True,
            "production_action_performed": False,
            "identity_errors": identity_errors,
            "observation_errors": observation_errors,
            "evidence": evidence,
        }
    )


def validate_emergency_waiver(
    waiver: dict[str, Any],
    *,
    event: dict[str, Any],
    owner_pr: str,
    head_sha: str,
    active_blockers: set[str],
) -> tuple[set[str], set[str]]:
    failures: set[str] = set()
    if set(waiver) != WAIVER_FIELDS:
        failures.add("WAIVER_INVALID")
    expected = {
        "active": True,
        "change_control_version": CHANGE_CONTROL_VERSION,
        "credentials_accessed": False,
        "head_sha": head_sha,
        "human_only": True,
        "mode": "EMERGENCY_WAIVER",
        "owner_pr": owner_pr,
        "production_environment_accessed": False,
        "repository": REPOSITORY,
        "schema_version": CHANGE_CONTROL_SCHEMA_VERSION,
        "source": "GITHUB_CONNECTOR",
        "static": True,
    }
    for key, value in expected.items():
        if waiver.get(key) != value:
            if key == "head_sha":
                failures.add("WAIVER_HEAD_MISMATCH")
            else:
                failures.add("WAIVER_INVALID")

    sender = event.get("sender")
    pull_request = event.get("pull_request")
    sender_login = sender.get("login") if isinstance(sender, dict) else None
    sender_type = sender.get("type") if isinstance(sender, dict) else None
    pull_request_user = (
        pull_request.get("user") if isinstance(pull_request, dict) else None
    )
    author_login = (
        pull_request_user.get("login")
        if isinstance(pull_request_user, dict)
        else None
    )
    association = (
        pull_request.get("author_association")
        if isinstance(pull_request, dict)
        else None
    )
    approver_login = waiver.get("approver_login")
    human_approver = (
        isinstance(approver_login, str)
        and LOGIN_PATTERN.fullmatch(approver_login) is not None
        and waiver.get("approver_type") == "User"
        and sender_type == "User"
        and sender_login == approver_login
        and author_login == approver_login
        and association in {"OWNER", "MEMBER", "COLLABORATOR"}
    )
    if not human_approver:
        failures.add("WAIVER_NOT_HUMAN")

    if waiver.get("reason_code") not in WAIVER_REASON_CODES:
        failures.add("WAIVER_INVALID")
    raw_codes = waiver.get("waived_blocker_codes")
    if (
        not isinstance(raw_codes, list)
        or not raw_codes
        or any(not isinstance(code, str) for code in raw_codes)
    ):
        waived: set[str] = set()
        failures.add("WAIVER_BLOCKER_NOT_WAIVABLE")
    else:
        waived = set(raw_codes)
        if raw_codes != sorted(waived):
            failures.add("WAIVER_INVALID")
        if not waived <= WAIVABLE_BLOCKER_CODES or not waived <= active_blockers:
            failures.add("WAIVER_BLOCKER_NOT_WAIVABLE")
    if failures:
        return set(), failures
    return waived, set()


def build_change_control_report(
    *,
    event: dict[str, Any],
    changed_paths: list[str],
    expected_base_sha: str,
    expected_head_sha: str,
    complete: bool,
    credentials_accessed: bool | None,
    production_environment_accessed: bool | None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    stamp = observed_at or now_utc()
    parse_time(stamp)
    blockers: set[str] = set()
    findings: set[str] = set()
    identity = {
        "repository": "UNKNOWN",
        "owner_pr": "UNKNOWN",
        "base_sha": "UNKNOWN",
        "head_sha": "UNKNOWN",
        "body": "",
    }
    try:
        identity = event_pr_identity(event)
    except ContractError:
        blockers.add("CONNECTOR_EVIDENCE_INVALID")
    if identity["repository"] != REPOSITORY:
        blockers.add("CONNECTOR_EVIDENCE_INVALID")
    try:
        expected_base = require_sha(expected_base_sha, "expected_base_sha")
        expected_head = require_sha(expected_head_sha, "expected_head_sha")
    except ContractError:
        expected_base = expected_base_sha
        expected_head = expected_head_sha
        blockers.add("CONNECTOR_EVIDENCE_INVALID")
    if identity["base_sha"] != expected_base or identity["head_sha"] != expected_head:
        blockers.add("CONNECTOR_EVIDENCE_INVALID")
    if credentials_accessed is not False or production_environment_accessed is not False:
        blockers.add("CONNECTOR_EVIDENCE_INVALID")

    workstream_class, class_blockers = parse_workstream_class(identity["body"])
    blockers.update(class_blockers)
    escalation, escalation_blockers = parse_escalation_marker(identity["body"])
    blockers.update(escalation_blockers)

    normalized: list[str] = []
    if not isinstance(complete, bool) or not complete:
        blockers.add("CHANGESET_UNKNOWN")
    try:
        normalized = sorted({normalize_path(path) for path in changed_paths})
    except ContractError:
        blockers.add("CHANGESET_UNKNOWN")
    if not normalized:
        blockers.add("CHANGESET_UNKNOWN")

    rows = [
        {"category": change_control_path_category(path), "path": path}
        for path in normalized
    ]
    categories = {row["category"] for row in rows}
    if "PROTOCOL_SURFACE" in categories:
        findings.add("PROTOCOL_SURFACE_CHANGED")
    if "PRODUCT_SURFACE" in categories:
        findings.add("PRODUCT_SURFACE_CHANGED")
    if "FORBIDDEN_GLOBAL_STATE" in categories:
        blockers.add("GLOBAL_STATE_FORBIDDEN")
    if {"PROTOCOL_SURFACE", "PRODUCT_SURFACE"} <= categories:
        findings.add("MIXED_SCOPE_DETECTED")
        blockers.add("MIXED_SCOPE")

    if workstream_class == "PRODUCT" and "PROTOCOL_SURFACE" in categories:
        blockers.update({"PRODUCT_TOUCHES_PROTOCOL", "PROTOCOL_ESCALATION_REQUIRED"})
    if workstream_class == "PROTOCOL" and "PRODUCT_SURFACE" in categories:
        blockers.add("PROTOCOL_TOUCHES_PRODUCT")
    if escalation != "NONE" and escalation != "UNKNOWN":
        findings.add(escalation)
        if workstream_class != "PROTOCOL":
            blockers.add("PROTOCOL_ESCALATION_REQUIRED")

    waiver, waiver_parse_blockers = extract_emergency_waiver(identity["body"])
    blockers.update(waiver_parse_blockers)
    active_before_waiver = set(blockers)
    waived: set[str] = set()
    waiver_status = "NONE"
    if waiver is not None:
        waiver_status = "INVALID"
        waived, waiver_blockers = validate_emergency_waiver(
            waiver,
            event=event,
            owner_pr=identity["owner_pr"],
            head_sha=identity["head_sha"],
            active_blockers=active_before_waiver,
        )
        blockers.update(waiver_blockers)
        if not waiver_blockers:
            blockers.difference_update(waived)
            waiver_status = "VALID"

    if not blockers:
        result = "PASS"
        required_action = "NONE"
    elif blockers & {
        "MIXED_SCOPE",
        "PRODUCT_TOUCHES_PROTOCOL",
        "PROTOCOL_ESCALATION_REQUIRED",
        "PROTOCOL_TOUCHES_PRODUCT",
    }:
        result = "STOP"
        required_action = "PROTOCOL_ESCALATION"
    else:
        result = "STOP"
        required_action = "STOP"

    if not findings <= FINDING_CODES or not blockers <= BLOCKER_CODES:
        fail("change-control codes escaped their closed registries")
    return seal(
        {
            "schema_version": CHANGE_CONTROL_SCHEMA_VERSION,
            "change_control_version": CHANGE_CONTROL_VERSION,
            "mode": "CHANGE_CONTROL",
            "source": "GITHUB_CONNECTOR",
            "repository": REPOSITORY,
            "observed_at": stamp,
            "owner_pr": identity["owner_pr"],
            "base_sha": identity["base_sha"],
            "head_sha": identity["head_sha"],
            "expected_base_sha": expected_base,
            "expected_head_sha": expected_head,
            "complete": complete,
            "workstream_class": workstream_class,
            "protocol_escalation": escalation,
            "changed_paths": normalized,
            "path_categories": rows,
            "observed_path_categories": sorted(categories),
            "finding_codes": sorted(findings),
            "active_blocker_codes": sorted(active_before_waiver),
            "waived_blocker_codes": sorted(waived),
            "blocker_codes": sorted(blockers),
            "waiver_status": waiver_status,
            "connector_only": True,
            "credentials_accessed": credentials_accessed,
            "production_environment_accessed": production_environment_accessed,
            "result": result,
            "required_action": required_action,
            "merge_allowed": not blockers,
        }
    )


def verify_change_control_report(
    report: dict[str, Any],
    *,
    event: dict[str, Any],
    changed_paths: list[str],
    expected_base_sha: str,
    expected_head_sha: str,
    complete: bool,
    credentials_accessed: bool | None,
    production_environment_accessed: bool | None,
) -> None:
    verify_seal(report)
    recomputed = build_change_control_report(
        event=event,
        changed_paths=changed_paths,
        expected_base_sha=expected_base_sha,
        expected_head_sha=expected_head_sha,
        complete=complete,
        credentials_accessed=credentials_accessed,
        production_environment_accessed=production_environment_accessed,
        observed_at=str(report.get("observed_at", "")),
    )
    if report != recomputed:
        fail("change-control report does not match its exact event, head and path set")


def build_protocol_escalation(
    *,
    event: dict[str, Any],
    finding_code: str,
    expected_head_sha: str,
    credentials_accessed: bool | None,
    production_environment_accessed: bool | None,
) -> dict[str, Any]:
    identity = event_pr_identity(event)
    if identity["repository"] != REPOSITORY:
        fail("protocol escalation repository mismatch")
    head_sha = require_sha(expected_head_sha, "expected_head_sha")
    if identity["head_sha"] != head_sha:
        fail("protocol escalation head mismatch")
    finding = require_choice(finding_code, "finding_code", FINDING_CODES)
    if credentials_accessed is not False or production_environment_accessed is not False:
        fail("protocol escalation must remain connector-only")
    return seal(
        {
            "schema_version": CHANGE_CONTROL_SCHEMA_VERSION,
            "change_control_version": CHANGE_CONTROL_VERSION,
            "mode": "PROTOCOL_ESCALATION",
            "source": "GITHUB_CONNECTOR",
            "repository": REPOSITORY,
            "observed_at": now_utc(),
            "owner_pr": identity["owner_pr"],
            "head_sha": head_sha,
            "finding_code": finding,
            "blocker_code": "PROTOCOL_ESCALATION_REQUIRED",
            "result": "STOPPED",
            "required_action": "OPEN_SEPARATE_PROTOCOL_PR",
            "agents_may_modify_protocol_in_current_pr": False,
            "connector_only": True,
            "credentials_accessed": False,
            "production_environment_accessed": False,
            "production_action_performed": False,
        }
    )


def self_test() -> None:
    base_sha = "a" * 40
    head_sha = "b" * 40
    current_default = "d" * 40
    stamp = now_utc()

    safe = build_effect_report(
        base_sha=base_sha,
        head_sha=head_sha,
        changed_paths=sorted(SAFE_PROTOCOL_PATHS),
        policy="NO_PRODUCTION",
        source="GITHUB_CONNECTOR",
        complete=True,
        observed_at=stamp,
    )
    verify_effect_report(safe, base_sha=base_sha, head_sha=head_sha, policy="NO_PRODUCTION")
    assert safe["effect"] == "NO_PRODUCTION" and safe["bind_allowed"] is True

    unclassified = build_effect_report(
        base_sha=base_sha,
        head_sha=head_sha,
        changed_paths=["Dockerfile"],
        policy="NO_PRODUCTION",
        source="GITHUB_CONNECTOR",
        complete=True,
        observed_at=stamp,
    )
    assert unclassified["effect"] == "PRODUCTION"
    assert unclassified["bind_allowed"] is False

    renamed = connector_paths(
        {"changed_files": [{"previous_path": "core/old.py", "filename": "docs/new.md"}]}
    )
    assert renamed == ["core/old.py", "docs/new.md"]

    binding = build_binding(
        safe, active_pr="#45", workstream="agent-protocol-v1.2-subset",
        workstream_class="PROTOCOL", adopted_contract=(contract := {
            "schema": "agent-policy-contract/v1", "repository": REPOSITORY,
            "source_commit": base_sha, "reference": "synthetic accepted contract",
            "routing": "PROTOCOL/v1"}), trusted_contract=policy_module().digest(contract),
        production_authority={"production": False, "deploy": False, "migrate": False},
    )
    policy_context = {"contract": contract, "trusted_contract": policy_module().digest(contract),
                      "workstream_class": "PROTOCOL",
                      "production_authority": dict.fromkeys(
                          ["production", "deploy", "migrate"], False)}
    snapshot = seal(
        {
            "policy_context": policy_context,
            "schema_version": SCHEMA_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "mode": "SNAPSHOT",
            "source": "GITHUB_CONNECTOR",
            "repository": REPOSITORY,
            "observed_at": stamp,
            "default_branch": DEFAULT_BRANCH,
            "default_sha": base_sha,
            "owner_pr": "#45",
            "base_sha": base_sha,
            "head_sha": head_sha,
            "binding_basis_sha": head_sha,
            "effect_report_sha256": safe["report_sha256"],
            "pr_state": "OPEN",
            "draft": "FALSE",
            "checks": "SUCCESS",
            "review_requirement_source": "NONE",
            "codex_review_state": "NOT_REQUESTED",
            "repository_review": "NOT_APPLICABLE",
            "technical_finding": "NONE",
            "codex_reviewed_head": "NOT_APPLICABLE",
            "unresolved_threads": 0,
            "mergeability": "MERGEABLE",
            "base_ancestry": "TRUE",
            "binding_basis_ancestor": "TRUE",
            "credentials_accessed": False,
            "production_environment_accessed": False,
        }
    )
    assert preflight(snapshot, binding)["merge_ready"] is True

    stale_identity = dict(snapshot)
    stale_identity["owner_pr"] = "#999"
    stale_identity = seal(stale_identity)
    assert preflight(stale_identity, binding)["merge_ready"] is False

    tampered = dict(safe)
    tampered["effect"] = "PRODUCTION"
    tampered = seal(tampered)
    try:
        verify_effect_report(
            tampered, base_sha=base_sha, head_sha=head_sha, policy="NO_PRODUCTION"
        )
    except ContractError:
        pass
    else:
        fail("tampered effect classification was accepted")

    evidence = seal(
        {
            "policy_context": policy_context,
            "schema_version": SCHEMA_VERSION,
            "protocol_version": PROTOCOL_VERSION,
            "mode": "RECONCILE_EVIDENCE",
            "source": "GITHUB_CONNECTOR",
            "repository": REPOSITORY,
            "observed_at": stamp,
            "default_branch": DEFAULT_BRANCH,
            "default_sha": current_default,
            "active_pr": "#45",
            "pr_state": "MERGED",
            "binding_basis_sha": head_sha,
            "binding_basis_ancestor": "TRUE",
            "effect_report_sha256": safe["report_sha256"],
            "merge_sha": "c" * 40,
            "merge_sha_on_default": "TRUE",
            "workflow_status": "UNKNOWN",
            "release_status": "NOT_APPLICABLE",
            "production_action_performed": False,
        }
    )
    report = reconcile(evidence, binding)
    assert report["release_allowed"] is True
    assert report["result"] == "UNKNOWN"
    assert evidence["default_sha"] != evidence["merge_sha"]

    event = {
        "number": 46,
        "repository": {"full_name": REPOSITORY},
        "sender": {"login": "gabned", "type": "User"},
        "pull_request": {
            "body": "WORKSTREAM_CLASS: PROTOCOL\nPROTOCOL_ESCALATION: NONE\n",
            "author_association": "OWNER",
            "base": {"sha": base_sha},
            "head": {"sha": head_sha},
        },
    }
    change_control = build_change_control_report(
        event=event,
        changed_paths=["AGENTS.md", "tools/agent_protocol.py"],
        expected_base_sha=base_sha,
        expected_head_sha=head_sha,
        complete=True,
        credentials_accessed=False,
        production_environment_accessed=False,
        observed_at=stamp,
    )
    assert change_control["merge_allowed"] is True
    mixed = build_change_control_report(
        event=event,
        changed_paths=["AGENTS.md", "core/provelume/cli.py"],
        expected_base_sha=base_sha,
        expected_head_sha=head_sha,
        complete=True,
        credentials_accessed=False,
        production_environment_accessed=False,
        observed_at=stamp,
    )
    assert mixed["merge_allowed"] is False
    assert "MIXED_SCOPE" in mixed["blocker_codes"]
    print(
        f"{REPOSITORY} Agent Development Protocol lifecycle v{PROTOCOL_VERSION}, "
        f"change control v{CHANGE_CONTROL_VERSION} and review governance "
        f"v{GOVERNANCE_RELEASE} passed."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    effects = commands.add_parser("effects")
    source = effects.add_mutually_exclusive_group(required=True)
    source.add_argument("--changed-paths", type=Path)
    source.add_argument("--connector-files", type=Path)
    effects.add_argument("--source", choices=sorted(SOURCES), required=True)
    effects.add_argument("--base-sha", required=True)
    effects.add_argument("--head-sha", required=True)
    effects.add_argument("--policy", choices=sorted(POLICIES), required=True)
    effects.add_argument("--complete", action="store_true")
    effects.add_argument("--output", type=Path)

    verify = commands.add_parser("verify-effect")
    verify.add_argument("--report", type=Path, required=True)
    verify.add_argument("--base-sha", required=True)
    verify.add_argument("--head-sha", required=True)
    verify.add_argument("--policy", choices=sorted(POLICIES), required=True)

    bind = commands.add_parser("bind")
    bind.add_argument("--report", type=Path, required=True)
    bind.add_argument("--pr", required=True)
    bind.add_argument("--workstream", required=True)
    bind.add_argument("--workstream-class", choices=sorted(WORKSTREAM_CLASSES), required=True)
    bind.add_argument("--adopted-contract", type=Path, required=True)
    bind.add_argument("--trusted-contract", required=True)
    bind.add_argument("--production-authority", type=Path, required=True)
    bind.add_argument("--output", type=Path)

    check = commands.add_parser("preflight")
    check.add_argument("--snapshot", type=Path, required=True)
    check.add_argument("--binding", type=Path, required=True)
    check.add_argument("--output", type=Path)

    observed = commands.add_parser("reconcile")
    observed.add_argument("--evidence", type=Path, required=True)
    observed.add_argument("--binding", type=Path, required=True)
    observed.add_argument("--output", type=Path)

    change_control = commands.add_parser("change-control")
    change_control.add_argument("--event", type=Path, required=True)
    change_control.add_argument("--current-pr", type=Path)
    change_control.add_argument("--name-status", type=Path, required=True)
    change_control.add_argument("--expected-base-sha", required=True)
    change_control.add_argument("--expected-head-sha", required=True)
    change_control.add_argument("--complete", action="store_true")
    change_control.add_argument("--output", type=Path)

    escalation = commands.add_parser("escalate")
    escalation.add_argument("--event", type=Path, required=True)
    escalation.add_argument("--finding-code", choices=sorted(FINDING_CODES), required=True)
    escalation.add_argument("--expected-head-sha", required=True)
    escalation.add_argument("--output", type=Path)

    commands.add_parser("self-test")
    return parser


def emit(payload: dict[str, Any], output: Path | None) -> None:
    if output is not None:
        write_object(output, payload)
    print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "effects":
            paths = (
                read_changed_paths(args.changed_paths)
                if args.changed_paths is not None
                else connector_paths(load_value(args.connector_files))
            )
            report = build_effect_report(
                base_sha=args.base_sha,
                head_sha=args.head_sha,
                changed_paths=paths,
                policy=args.policy,
                source=args.source,
                complete=args.complete,
            )
            emit(report, args.output)
            return 0 if report["bind_allowed"] else 1
        if args.command == "verify-effect":
            verify_effect_report(
                load_object(args.report),
                base_sha=args.base_sha,
                head_sha=args.head_sha,
                policy=args.policy,
            )
            print("Effect report is exact and binding-compatible.")
            return 0
        if args.command == "bind":
            emit(
                build_binding(
                    load_object(args.report),
                    active_pr=args.pr,
                    workstream=args.workstream,
                    workstream_class=args.workstream_class,
                    adopted_contract=load_object(args.adopted_contract),
                    trusted_contract=args.trusted_contract,
                    production_authority=load_object(args.production_authority),
                ),
                args.output,
            )
            return 0
        if args.command == "preflight":
            report = preflight(load_object(args.snapshot), load_object(args.binding))
            emit(report, args.output)
            return 0 if report["merge_ready"] else 1
        if args.command == "reconcile":
            report = reconcile(load_object(args.evidence), load_object(args.binding))
            emit(report, args.output)
            return 0 if report["release_allowed"] else 1
        if args.command == "change-control":
            event = load_object(args.event)
            if args.current_pr is not None:
                event = bind_current_pr_body(event, load_object(args.current_pr))
            report = build_change_control_report(
                event=event,
                changed_paths=read_name_status(args.name_status),
                expected_base_sha=args.expected_base_sha,
                expected_head_sha=args.expected_head_sha,
                complete=args.complete,
                credentials_accessed=False,
                production_environment_accessed=False,
            )
            emit(report, args.output)
            return 0 if report["merge_allowed"] else 1
        if args.command == "escalate":
            emit(
                build_protocol_escalation(
                    event=load_object(args.event),
                    finding_code=args.finding_code,
                    expected_head_sha=args.expected_head_sha,
                    credentials_accessed=False,
                    production_environment_accessed=False,
                ),
                args.output,
            )
            return 1
        self_test()
        return 0
    except ContractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
