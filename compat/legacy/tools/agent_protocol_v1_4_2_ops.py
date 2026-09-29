"""Offline operational evidence for Protocol 1.4.2; never executes GitHub actions."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

VERSION = "1.4.2"
PROFILES = {
    "gabned/provelume": ("main", "GITHUB_ARTIFACT"),
    "maxithlon/maxithlon": ("master", "DEPLOYMENT_LEVEL_C"),
    "brickms/brickms": ("main", "CODE_ONLY_PRODUCTION_B"),
    "gabned/provelume.com": ("main", "UPSTREAM_RELEASE_VERIFIED"),
    "gabned/nexus": ("main", "DESCRIPTIVE_ONLY"),
}
VENDOR_FILES = {
    "tools/agent_protocol_v1_4.py": "100755",
    "tools/agent_protocol_v1_4_1.py": "100755",
    "tools/agent_protocol_v1_4_2.py": "100755",
    "tools/agent_protocol_v1_4_2_ops.py": "100644",
    "tools/agent_protocol_v1_4_9.py": "100644",
}
MANIFEST_PATH = ".github/agent-protocol/vendor-v1.4.2.json"
PROVENANCE_PATH = "docs/agent-development-v1.4.2-provenance.md"
TERMINAL = {"SUCCESS", "FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED",
            "NEUTRAL", "SKIPPED", "STALE", "STARTUP_FAILURE"}
CI_EVENTS = {"pull_request", "pull_request_target", "push", "merge_group",
             "workflow_dispatch", "workflow_run", "schedule", "release", "dynamic",
             "pull_request_review"}
_WORK_INSTRUCTIONS: ContextVar[dict | None] = ContextVar(
    "protocol143_trusted_work_instructions", default=None,
)
_PROTOCOL_SCOPE: ContextVar[dict | None] = ContextVar(
    "protocol147_trusted_consumer_scope", default=None,
)
_NESTED_PROTOCOL_SCOPES: ContextVar[dict | None] = ContextVar(
    "protocol147_trusted_nested_consumer_scopes", default=None,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def obj(value: Any, keys: str, label: str) -> dict:
    require(isinstance(value, dict) and set(value) == set(keys.split()),
            f"{label}: missing or extra fields")
    return value


def array(value: Any, label: str) -> list:
    require(isinstance(value, list), f"{label}: expected list")
    return value


def text(value: Any, label: str) -> str:
    require(isinstance(value, str) and bool(value.strip()) and value == value.strip()
            and "\n" not in value and "\r" not in value, f"{label}: invalid text")
    return value


def number(value: Any, label: str) -> int:
    require(type(value) is int and value > 0, f"{label}: expected positive integer")
    return value


def instruction_text(value: Any, label: str) -> str:
    """Bound a real instruction while preserving all verbatim whitespace."""
    require(isinstance(value, str) and bool(value.strip()) and len(value) <= 10000,
            f"{label}: expected bounded nonempty instruction")
    return value


def sha(value: Any, length: int = 40) -> str:
    require(isinstance(value, str) and re.fullmatch(f"[0-9a-f]{{{length}}}", value) is not None,
            "invalid commit/blob/digest")
    return value


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


@contextmanager
def trusted_protocol_scope(profile: Any, expected_digest: str):
    """Bind a caller-selected accepted-base profile; never discover it in a PR.

    The host reads the policy file at the independently observed accepted base,
    then binds its repository, path and base here. The digest is integrity only.
    This context changes no workflow, review, effect or lifecycle requirement.
    """
    require(digest(profile) == sha(expected_digest, 64), "changed trusted Protocol scope")
    obj(profile, "schema repository base_sha policy_path paths", "Protocol scope")
    require(profile["schema"] == "agent-protocol-scope/v1", "Protocol scope schema")
    require(profile["repository"] in PROFILES and profile["repository"] != "gabned/nexus",
            "Protocol scope repository")
    sha(profile["base_sha"])
    policy_path = path(profile["policy_path"])
    policy_roots = (".github/agent-protocol/", "docs/agent-development-v",
                    "docs/runbooks/agent-development-v")
    require(policy_path.startswith(policy_roots) and policy_path.endswith(".json") and
            not any(char in policy_path for char in "*?[]"),
            "Protocol scope policy path")
    rows = array(profile["paths"], "Protocol scope paths")
    require(0 < len(rows) <= 64, "bounded Protocol scope paths")
    roots = {"IMPLEMENTATION": ("tools/", "scripts/"), "TEST": ("tests/",),
             "NORMATIVE_DOC": ("docs/",)}
    names = []
    for row in rows:
        obj(row, "path role", "Protocol scope entry")
        name = path(row["path"])
        require(not any(char in name for char in "*?[]"), "exact Protocol scope paths required")
        require(row["role"] in roots and name.startswith(roots[row["role"]]),
                "Protocol scope role/path mismatch")
        names.append(name)
    require(names == sorted(set(names)), "sorted unique Protocol scope paths required")
    token = _PROTOCOL_SCOPE.set(deepcopy(profile))
    try:
        yield
    finally:
        _PROTOCOL_SCOPE.reset(token)


@contextmanager
def trusted_nested_protocol_scopes(profiles: Any, expected_digest: str):
    """Bind independently accepted historical bases; never inherit the outer scope."""
    require(digest(profiles) == sha(expected_digest, 64), "changed trusted nested Protocol scopes")
    rows = array(profiles, "nested Protocol scope inventory")
    require(0 < len(rows) <= 128, "bounded nested Protocol scope inventory")
    selected = {}
    for profile in rows:
        with trusted_protocol_scope(profile, digest(profile)):
            pass
        key = (profile["repository"], profile["base_sha"])
        require(key not in selected, "duplicate nested Protocol scope base")
        selected[key] = deepcopy(profile)
    token = _NESTED_PROTOCOL_SCOPES.set(selected)
    try:
        yield
    finally:
        _NESTED_PROTOCOL_SCOPES.reset(token)


def work_instruction_records(value: Any) -> dict[str, dict]:
    """Validate caller-selected authority, never discover approval in PR evidence.

    The caller must independently observe the actual user instruction and decide
    that it covers this exact delta. Content addressing is integrity, not identity
    or permission. No Work task UUID or creation timestamp is inferred.
    """
    records = array(value, "trusted Work instructions")
    require(len(records) <= 1000, "trusted Work instruction limit")
    result = {}
    for raw in records:
        item = obj(raw, "schema source actor instruction authorized_request repository pr "
                   "base_sha head_sha paths_sha256 patch_sha256 authority_envelope "
                   "workstream_class effect_policy", "Work instruction")
        require(item["schema"] == "agent-work-instruction/v1" and
                item["source"] == "CURRENT_USER_CONVERSATION", "invalid instruction source")
        require(len(text(item["actor"], "actor")) <= 10000, "instruction actor limit")
        for key in ("instruction", "authorized_request"):
            instruction_text(item[key], key)
        require(item["repository"] in PROFILES, "unknown instruction repository")
        number(item["pr"], "instruction PR")
        for key in ("base_sha", "head_sha"):
            sha(item[key])
        for key in ("paths_sha256", "patch_sha256"):
            sha(item[key], 64)
        require(item["authority_envelope"] == "THROUGH_MERGE" and
                item["workstream_class"] == "PROTOCOL" and
                item["effect_policy"] == "NO_PRODUCTION", "instruction exceeds Protocol scope")
        identity = digest(item)
        require(identity not in result, "duplicate trusted Work instruction")
        result[identity] = deepcopy(item)
    return result


@contextmanager
def trusted_work_instructions(records: Any):
    """Scope explicit host authority outside candidate-controlled observations."""
    token = _WORK_INSTRUCTIONS.set(work_instruction_records(records))
    try:
        yield
    finally:
        _WORK_INSTRUCTIONS.reset(token)


def blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def timestamp(value: Any) -> datetime:
    require(isinstance(value, str) and re.fullmatch(
        r"20\d\d-\d\d-\d\dT\d\d:\d\d:\d\dZ", value) is not None, "invalid UTC timestamp")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def observation(value: dict, now: datetime | None = None) -> None:
    require(value["source"] == "GITHUB_CONNECTOR", "evidence must be connector-observed")
    age = (now or datetime.now(UTC)) - timestamp(value["observed_at"])
    require(-timedelta(seconds=30) <= age <= timedelta(minutes=15), "stale observation")


def path(value: Any) -> str:
    # Git names are atomic JSON strings, not lines of human-readable text.
    require(isinstance(value, str) and bool(value) and "\0" not in value, "invalid path")
    require("\\" not in value and ":" not in value and not value.startswith("/"),
            "path must be repository-relative")
    require(all(part not in {"", ".", ".."} for part in value.split("/")), "unsafe path")
    require(str(PurePosixPath(value)) == value, "noncanonical path")
    return value


def paths(value: Any) -> list[str]:
    rows = array(value, "paths")
    checked = [path(item) for item in rows]
    require(checked == sorted(set(checked)), "paths must be sorted, unique and complete")
    return checked


def validate_pr(value: Any, now: datetime | None = None) -> dict:
    p = obj(value, "repository number base_sha head_sha tree_sha body changed_paths "
            "paths_complete file_patches state draft mergeable source observed_at", "PR")
    require(p["state"] in {"OPEN", "CLOSED"} and type(p["draft"]) is bool and
            (p["mergeable"] is None or type(p["mergeable"]) is bool), "invalid PR state")
    require(p["repository"] in PROFILES, "unknown repository")
    number(p["number"], "PR number")
    for key in ("base_sha", "head_sha", "tree_sha"):
        sha(p[key])
    observation(p, now)
    require(p["paths_complete"] is True, "incomplete changed-file evidence")
    require(bool(paths(p["changed_paths"])), "empty PR delta")
    require(isinstance(p["file_patches"], dict) and
            sorted(p["file_patches"]) == p["changed_paths"] and
            all(isinstance(v, str) and v for v in p["file_patches"].values()),
            "complete exact-head patches required")
    require(isinstance(p["body"], str), "PR body missing")
    for key, expected in (("HEAD_SHA", p["head_sha"]), ("BASE_SHA", p["base_sha"]),
                          ("TREE_SHA", p["tree_sha"]),
                          ("WORKSTREAM_CLASS", "PROTOCOL"),
                          ("CHANGED_PATHS_COMPLETE", "TRUE")):
        found = re.findall(rf"(?m)^{key}:[ \t]*([^\r\n]+?)[ \t]*$", p["body"])
        require(found == [expected], f"{key}: missing, duplicate or stale declaration")
    return p


def render_pr_identity(value: Any) -> dict:
    p = deepcopy(value)
    require(isinstance(p, dict) and isinstance(p.get("body"), str), "PR snapshot missing")
    for key, actual in (("BASE_SHA", p["base_sha"]), ("HEAD_SHA", p["head_sha"]),
                        ("TREE_SHA", p["tree_sha"]), ("CHANGED_PATHS_COMPLETE", "TRUE")):
        p["body"] = re.sub(rf"(?m)^{key}:[^\r\n]*(?:\r?\n|$)", "", p["body"])
        p["body"] = p["body"].rstrip() + f"\n{key}: {actual}\n"
    validate_pr(p)
    return p


def validate_ci(value: Any, repository: str, head: str, *, now: datetime | None = None,
                require_success: bool = True) -> dict:
    c = obj(value, "repository head_sha source observed_at applicability policy_ref "
            "required_workflows runs runs_complete", "CI")
    observation(c, now)
    require(c["repository"] == repository and c["head_sha"] == head, "CI identity mismatch")
    sha(head)
    sha(c["policy_ref"])
    require(c["runs_complete"] is True, "partial workflow-run pagination")
    required = array(c["required_workflows"], "required workflows")
    require(required == sorted(set(required)), "duplicate or unordered required workflow")
    for name in required:
        text(name, "workflow identity")
        require("@" in name and name.rsplit("@", 1)[1] in CI_EVENTS,
                "required workflow must include its trigger identity")
    runs = array(c["runs"], "runs")
    require(c["applicability"] in {"REQUIRED", "NOT_APPLICABLE"}, "unknown CI applicability")
    if c["applicability"] == "NOT_APPLICABLE":
        require(repository == "gabned/nexus" and not runs and not required,
                "inapplicable CI cannot conceal workflows")
        return c
    require(bool(required) and bool(runs), "applicable CI evidence is empty")
    ids: set[int] = set()
    latest: dict[str, dict] = {}
    for raw in runs:
        r = obj(raw, "run_id workflow event head_sha latest_attempt attempts", "run")
        run_id = number(r["run_id"], "run id")
        require(run_id not in ids and r["head_sha"] == head, "duplicate run or wrong head")
        ids.add(run_id)
        text(r["workflow"], "workflow identity")
        require("@" not in r["workflow"] and r["event"] in CI_EVENTS,
                "unknown or ambiguous workflow trigger")
        require((r["event"] == "dynamic") == r["workflow"].startswith("dynamic/"),
                "dynamic trigger requires its GitHub-managed workflow path")
        if r["event"] == "dynamic":
            path(r["workflow"])
        attempts = array(r["attempts"], "attempts")
        require(number(r["latest_attempt"], "latest attempt") == len(attempts),
                "attempt history incomplete or latest attempt hidden")
        for index, raw_attempt in enumerate(attempts, 1):
            a = obj(raw_attempt, "run_attempt status conclusion jobs_complete jobs", "attempt")
            require(type(a["run_attempt"]) is int and a["run_attempt"] == index,
                    "attempt history must be contiguous")
            require(a["status"] in {"QUEUED", "IN_PROGRESS", "COMPLETED"}, "unknown run status")
            if index < len(attempts):
                require(a["status"] == "COMPLETED", "retained attempts must be terminal")
            if a["status"] != "COMPLETED":
                require(a["conclusion"] == "NONE", "live attempt cannot have a conclusion")
            else:
                require(a["conclusion"] in TERMINAL, "unknown terminal conclusion")
            require(a["jobs_complete"] is True, "partial job pagination")
            jobs = array(a["jobs"], "jobs")
            job_ids: set[int] = set()
            for job in jobs:
                obj(job, "id name status conclusion", "job")
                jid = number(job["id"], "job id")
                require(jid not in job_ids, "duplicate job")
                job_ids.add(jid)
                text(job["name"], "job name")
                require(job["status"] in {"QUEUED", "IN_PROGRESS", "COMPLETED"},
                        "unknown job status")
                require(job["conclusion"] in (TERMINAL if job["status"] == "COMPLETED"
                                               else {"NONE"}), "invalid job conclusion")
            if a["status"] == "COMPLETED":
                require(all(j["status"] == "COMPLETED" for j in jobs),
                        "terminal attempt contains a live job")
            if a["conclusion"] == "SUCCESS":
                require(bool(jobs) and all(j["status"] == "COMPLETED" and
                        j["conclusion"] in {"SUCCESS", "SKIPPED", "NEUTRAL"} for j in jobs),
                        "successful attempt conflicts with job evidence")
        workflow_key = f"{r['workflow']}@{r['event']}"
        old = latest.get(workflow_key)
        if old is None or old["run_id"] < run_id:
            latest[workflow_key] = r
    require(set(required) <= set(latest), "required workflow evidence missing")
    if require_success:
        require(all(r["attempts"][-1]["conclusion"] == "SUCCESS" for r in latest.values()),
                "latest applicable attempt is not successful")
    return c


def validate_ci_append_only(
    previous: dict, successor: dict, *, now: datetime | None = None,
) -> None:
    validate_ci(previous, previous["repository"], previous["head_sha"],
                now=timestamp(previous["observed_at"]), require_success=False)
    validate_ci(successor, successor["repository"], successor["head_sha"],
                now=now, require_success=False)
    require(timestamp(successor["observed_at"]) >= timestamp(previous["observed_at"]),
            "CI observation moved backwards")
    for key in ("repository", "head_sha", "applicability", "policy_ref", "required_workflows"):
        require(previous[key] == successor[key], "CI history identity/policy changed")
    after = {r["run_id"]: r for r in successor["runs"]}
    for before in previous["runs"]:
        require(before["run_id"] in after, "CI history dropped a run")
        new = after[before["run_id"]]
        require(new["workflow"] == before["workflow"] and new["event"] == before["event"] and
                len(new["attempts"]) >=
                len(before["attempts"]), "CI run identity/history rewritten")
        for index, attempt in enumerate(before["attempts"]):
            if attempt["status"] == "COMPLETED":
                require(new["attempts"][index] == attempt, "terminal attempt rewritten")
            else:
                require(new["attempts"][index]["run_attempt"] == attempt["run_attempt"],
                        "live attempt replaced")
                jobs = {j["id"]: j for j in new["attempts"][index]["jobs"]}
                for job in attempt["jobs"]:
                    require(job["id"] in jobs, "retained job disappeared")
                    if job["status"] == "COMPLETED":
                        require(jobs[job["id"]] == job, "terminal job rewritten")


def validate_wait(value: Any, now: datetime | None = None) -> dict:
    w = obj(value, "repository run_id run_attempt head_sha status conclusion source "
            "observed_at deadline handle", "wait")
    require(w["source"] == "GITHUB_CONNECTOR", "evidence must be connector-observed")
    require(w["repository"] in PROFILES, "unknown wait repository")
    number(w["run_id"], "wait run")
    number(w["run_attempt"], "wait attempt")
    sha(w["head_sha"])
    require(w["status"] in {"QUEUED", "IN_PROGRESS"} and w["conclusion"] == "NONE",
            "only an observed live run can be waited on")
    expected = f"https://api.github.com/repos/{w['repository']}/actions/runs/{w['run_id']}/attempts/{w['run_attempt']}"
    require(w["handle"] == expected, "wait handle does not bind the observed attempt")
    duration = timestamp(w["deadline"]) - timestamp(w["observed_at"])
    require(timedelta(seconds=1) <= duration <= timedelta(hours=1), "unbounded wait")
    clock = now or datetime.now(UTC)
    expired = clock >= timestamp(w["deadline"])
    if not expired:
        observation(w, clock)
    return {"outcome": "WAIT_EVENT", "next_action": "REOBSERVE_SAME_HANDLE" if expired
            else "WAIT_SAME_HANDLE", "handle": expected, "campaign_transition": False,
            "polling": "DISABLED", "automatic_retry": False}


def validate_scope(
    value: Any, pr: dict, baseline: Any, now: datetime | None = None,
) -> None:
    initial = paths(baseline)
    require(set(initial) <= set(pr["changed_paths"]), "baseline contains absent paths")
    profile = _PROTOCOL_SCOPE.get()
    if profile is not None:
        require(profile["repository"] == pr["repository"] and
                profile["base_sha"] == pr["base_sha"],
                "Protocol scope base/repository mismatch")
        require(profile["policy_path"] not in pr["changed_paths"],
                "Protocol scope cannot qualify its own policy change")
    if pr["repository"] != "gabned/nexus":
        exact = {"AGENTS.md", ".github/pull_request_template.md", ".github/workflows/ci.yml",
                 "tools/agent-check", "tools/agent-protocol",
                 "scripts/agent/change_control_contract_v1_2_1.py",
                 "scripts/agent/change_control_v1_2_1.py",
                 "scripts/agent/agent_change_control_v1_2_1_profile.py",
                 "docs/runbooks/agent-development.md"}
        if pr["repository"] == "brickms/brickms":
            exact.add("scripts/agent/protocol-v1-2.py")
            exact.add("tools/agent-preflight")
            exact.add(".github/workflows/php-runtime-contract.yml")
        if pr["repository"] == "gabned/provelume.com":
            exact.add("tools/agent-preflight")
        prefixes = ("tools/agent_protocol", "tests/test_agent_protocol_",
                    "tests/agent_protocol_", "tests/agent_change_control_",
                    "docs/agent-development-v", "docs/runbooks/agent-development-v",
                    ".github/agent-protocol/")
        if profile is not None:
            exact.update(row["path"] for row in profile["paths"])
        require(all(name in exact or name.startswith(prefixes) for name in initial),
                "baseline includes a non-Protocol surface")
    else:
        require(len(initial) == 1 and initial[0].endswith(".md") and
                PurePosixPath(initial[0]).name not in {"AGENT_STATUS.md", "CHANGELOG.md"},
                "descriptive registry scope must be one Markdown document")
    extra = sorted(set(pr["changed_paths"]) - set(initial))
    if not extra:
        require(value is None, "unused scope exception")
        return
    s = obj(value, "repository pr base_sha head_sha paths_sha256 patch_sha256 patch "
            "actor actor_role authorization_source authorization_ref authorization_text "
            "decision source observed_at", "scope exception")
    observation(s, now)
    require(extra == ["CHANGELOG.md"], "only a technical changelog exception is supported")
    require(s["repository"] == pr["repository"] and s["pr"] == pr["number"] and
            s["base_sha"] == pr["base_sha"] and s["head_sha"] == pr["head_sha"],
            "scope authorization does not bind this exact PR")
    require(s["paths_sha256"] == digest(pr["changed_paths"]), "scope path digest mismatch")
    require(s["actor_role"] == "VERIFIED_HUMAN_MAINTAINER" and s["decision"] == "APPROVED",
            "scope requires verified explicit human authorization")
    text(s["actor"], "maintainer")
    if s["authorization_source"] == "WORK_USER_INSTRUCTION":
        instruction_text(s["authorization_text"], "verbatim Work instruction")
    else:
        text(s["authorization_text"], "verbatim authorization instruction")
    if s["authorization_source"] == "GITHUB_COMMENT":
        pattern = (rf"https://github[.]com/{re.escape(pr['repository'])}/"
                   rf"(?:pull|issues)/{pr['number']}#issuecomment-[1-9][0-9]*")
    elif s["authorization_source"] == "USER_INSTRUCTION":
        # A user-authorized goal is an existing instruction, not a GitHub comment
        # authored by the agent on the user's behalf. The caller verifies scope
        # against the retained instruction; this receipt binds its exact delta.
        pattern = (r"codex-goal:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
                   r"[0-9a-f]{4}-[0-9a-f]{12}:[1-9][0-9]*")
    elif s["authorization_source"] == "WORK_USER_INSTRUCTION":
        prefix = "work-instruction:sha256:"
        require(isinstance(s["authorization_ref"], str) and
                s["authorization_ref"].startswith(prefix), "invalid Work instruction reference")
        identity = sha(s["authorization_ref"][len(prefix):], 64)
        record = (_WORK_INSTRUCTIONS.get() or {}).get(identity)
        require(record is not None and digest(record) == identity,
                "Work instruction requires independently supplied caller authority")
        for key in ("repository", "pr", "base_sha", "head_sha", "paths_sha256", "patch_sha256",
                    "actor"):
            require(record[key] == s[key], "Work instruction does not bind exact authorized delta")
        require(record["instruction"] == s["authorization_text"], "Work instruction text mismatch")
        pattern = r"work-instruction:sha256:[0-9a-f]{64}"
    else:
        raise ValueError("unknown authorization source")
    require(re.fullmatch(pattern, s["authorization_ref"]) is not None,
            "unbound authorization reference")
    patch = s["patch"]
    require(patch == pr["file_patches"].get("CHANGELOG.md"),
            "authorized patch differs from observed exact-head patch")
    require(isinstance(patch, str) and hashlib.sha256(patch.encode()).hexdigest() ==
            s["patch_sha256"], "scope patch digest mismatch")
    lines = patch.splitlines()
    require(lines[:3] == ["diff --git a/CHANGELOG.md b/CHANGELOG.md",
                         "--- a/CHANGELOG.md", "+++ b/CHANGELOG.md"], "wrong patch target")
    additions = [line[1:] for line in lines[3:] if line.startswith("+")]
    require(len(additions) == 1 and "Protocol" in additions[0] and
            not any(line.startswith("-") for line in lines[3:]),
            "exception must append exactly one technical Protocol changelog line")
    if not additions[0].startswith("- "):
        index = lines.index("+" + additions[0], 3)
        identity = r"^ - .*?\bProtocol\b.*?\bv?1\.4\.2\b(?=[ :;,.]|$)"
        require(additions[0].startswith("  Agent Development Protocol ") and
                re.search(r"\bProtocol v?1\.4\.2\b", additions[0]) is not None and
                index > 3 and re.match(identity, lines[index - 1]) is not None,
                "continuation must follow the existing Protocol 1.4.2 entry")
    require(all(line.startswith(("@@ ", " ", "+")) for line in lines[3:]), "invalid patch")


def validate_merge(value: Any, pr: dict, now: datetime | None = None) -> dict:
    m = obj(value, "merged state merge_sha method commit default_sha ancestry source observed_at",
            "merge")
    observation(m, now)
    require(m["merged"] is True and m["state"] == "CLOSED", "provisional merge is not evidence")
    sha(m["merge_sha"])
    commit = obj(m["commit"], "sha tree_sha parents", "merge commit")
    require(commit["sha"] == m["merge_sha"] and commit["tree_sha"] == pr["tree_sha"],
            "actual merge commit/tree differs from accepted content")
    require(m["method"] in {"SQUASH", "MERGE"}, "unsupported merge method")
    expected = [pr["base_sha"]] if m["method"] == "SQUASH" else [pr["base_sha"], pr["head_sha"]]
    require(commit["parents"] == expected, "actual merge parents do not bind accepted base/head")
    chain = array(m["ancestry"], "default ancestry")
    sha(m["default_sha"])
    expected_sha = m["default_sha"]
    seen: set[str] = set()
    for item in chain:
        obj(item, "sha tree_sha parents", "ancestry commit")
        sha(item["sha"])
        sha(item["tree_sha"])
        require(item["sha"] == expected_sha and item["sha"] not in seen, "broken ancestry chain")
        seen.add(item["sha"])
        parents = array(item["parents"], "commit parents")
        for parent in parents:
            sha(parent)
        if item["sha"] == m["merge_sha"]:
            require(item == commit and item == chain[-1], "ancestry endpoint mismatch")
        else:
            require(bool(parents), "default is not descended from the merge")
            expected_sha = parents[0]
    require(bool(chain) and chain[-1] == commit, "actual merge is absent from default ancestry")
    return m


def validate_operations(
    value: Any, *, nested: bool = False, now: datetime | None = None,
    archived_receipt: bool = False,
) -> dict:
    require(not archived_receipt or now is not None, "archived receipt requires observation anchor")
    legacy = archived_receipt and isinstance(value, dict) and "default_branch" not in value
    fields = "" if legacy else "default_branch "
    e = obj(value, "protocol_version phase pr " + fields + "baseline_paths scope_exception ci "
            "reviews merge post_merge_ci late_findings late_findings_complete effect_policy",
            "operations")
    require(e["protocol_version"] == VERSION and e["effect_policy"] == "NO_PRODUCTION",
            "wrong version or operational scope")
    require(e["phase"] in {"PRE_MERGE", "POST_MERGE"}, "unknown operational phase")
    p = validate_pr(e["pr"], now)
    default = None
    if not legacy:
        default = obj(e["default_branch"], "repository name sha source observed_at",
                      "default branch")
        observation(default, now)
        sha(default["sha"])
        require((default["repository"], default["name"]) ==
                (p["repository"], PROFILES[p["repository"]][0]), "default branch identity mismatch")
    # Embedded origin/correction proofs may only use their separately selected
    # accepted-base profile. The outer operation never supplies implicit authority.
    selected = (_NESTED_PROTOCOL_SCOPES.get() or {}).get((p["repository"], p["base_sha"]))
    token = _PROTOCOL_SCOPE.set(selected) if nested else None
    try:
        validate_scope(e["scope_exception"], p, e["baseline_paths"], now)
    finally:
        if token is not None:
            _PROTOCOL_SCOPE.reset(token)
    validate_ci(e["ci"], p["repository"], p["head_sha"], now=now)
    require(e["ci"]["policy_ref"] == p["base_sha"], "CI policy is not bound to trusted base")
    r = obj(e["reviews"], "repository pr head_sha requirement state unresolved_threads "
            "current_findings complete source observed_at", "reviews")
    observation(r, now)
    require(r["complete"] is True and e["late_findings_complete"] is True,
            "incomplete review/finding inventory")
    require((r["repository"], r["pr"], r["head_sha"]) ==
            (p["repository"], p["number"], p["head_sha"]), "review identity mismatch")
    require((r["requirement"], r["state"]) in {("NONE", "NOT_APPLICABLE"),
            ("REPOSITORY", "SATISFIED"), ("EXPLICIT_MAINTAINER", "SATISFIED")},
            "required reviews not satisfied")
    require(r["unresolved_threads"] == [] and r["current_findings"] == [],
            "unresolved current finding or thread")
    if e["phase"] == "POST_MERGE":
        require(p["state"] == "CLOSED" and not p["draft"], "merged PR state mismatch")
        m = validate_merge(e["merge"], p, now)
        require(legacy or default["sha"] == m["default_sha"],
                "reconciliation differs from observed default")
        validate_ci(e["post_merge_ci"], p["repository"], m["default_sha"], now=now)
        require(e["post_merge_ci"]["policy_ref"] == m["default_sha"],
                "post-merge CI policy is not bound to the audited default")
    else:
        require(legacy or default["sha"] == p["base_sha"],
                "accepted base differs from observed default")
        require(p["state"] == "OPEN" and not p["draft"] and p["mergeable"] is True,
                "pre-merge PR must be open, ready and mergeable")
        require(e["merge"] is None and e["post_merge_ci"] is None,
                "pre-merge input cannot claim reconciliation")
    findings = array(e["late_findings"], "late findings")
    require(not (nested and findings), "nested correction findings are not allowed")
    ids: set[str] = set()
    for finding in findings:
        f = obj(finding, "id origin_pr origin_merge_sha thread_ref state correction "
                "origin resolution prior_ledger retained_ledger", "late finding")
        text(f["id"], "finding id")
        require(f["id"] not in ids, "duplicate late finding")
        ids.add(f["id"])
        require(f["state"] == "RESOLVED", "late finding remains open")
        number(f["origin_pr"], "original PR")
        sha(f["origin_merge_sha"])
        origin = validate_operations(f["origin"], nested=True, now=now,
                                     archived_receipt=archived_receipt)
        require(origin["phase"] == "POST_MERGE" and
                origin["pr"]["repository"] == p["repository"] and
                origin["pr"]["number"] == f["origin_pr"] and
                origin["merge"]["merge_sha"] == f["origin_merge_sha"],
                "finding origin is not an observed merged PR/build")
        correction = validate_operations(f["correction"], nested=True, now=now,
                                         archived_receipt=archived_receipt)
        cp = correction["pr"]
        require(correction["phase"] == "POST_MERGE" and cp["repository"] == p["repository"]
                and cp["number"] != f["origin_pr"], "correction not reconciled in same repository")
        require(correction["merge"]["merge_sha"] != f["origin_merge_sha"],
                "correction cannot reuse the original merge")
        require(correction["merge"]["commit"] in origin["merge"]["ancestry"][:-1],
                "correction must descend from the original merge in observed default ancestry")
        require(re.fullmatch(rf"https://github[.]com/{re.escape(p['repository'])}/pull/"
                             rf"{f['origin_pr']}#discussion_r[1-9][0-9]*", f["thread_ref"])
                is not None, "finding thread is not bound to origin PR")
        resolution = obj(f["resolution"], "repository origin_pr origin_head_sha thread_ref "
                         "is_resolved correction_pr correction_head_sha correction_merge_sha "
                         "source observed_at", "finding resolution")
        observation(resolution, now)
        require(resolution["is_resolved"] is True and
                resolution["repository"] == p["repository"] and
                resolution["origin_pr"] == f["origin_pr"] and
                resolution["origin_head_sha"] == origin["pr"]["head_sha"] and
                resolution["thread_ref"] == f["thread_ref"] and
                resolution["correction_pr"] == cp["number"] and
                resolution["correction_head_sha"] == cp["head_sha"] and
                resolution["correction_merge_sha"] == correction["merge"]["merge_sha"],
                "thread resolution does not prove this corrective merge")
        ledger = array(f["retained_ledger"], "correction ledger")
        require(len(ledger) >= 2, "correction must retain origin history")
        prior = array(f["prior_ledger"], "prior correction ledger")
        require(prior == ledger[:-1], "correction rewrites prior terminal ledger")
        numbers = []
        for entry in ledger:
            obj(entry, "pr head_sha merge_sha state", "retained PR")
            numbers.append(number(entry["pr"], "retained PR number"))
            sha(entry["head_sha"])
            require(entry["state"] in {"MERGED", "CLOSED"}, "retained history is not terminal")
            if entry["state"] == "MERGED":
                sha(entry["merge_sha"])
            else:
                require(entry["merge_sha"] == "NONE", "unmerged PR claims merge")
        require(len(numbers) == len(set(numbers)), "duplicate retained PR")
        require(any(x["pr"] == f["origin_pr"] and x["merge_sha"] == f["origin_merge_sha"]
                    and x["head_sha"] == origin["pr"]["head_sha"] and x["state"] == "MERGED"
                    for x in ledger[:-1]), "origin history rewritten")
        require(ledger[-1] == {"pr": cp["number"], "head_sha": cp["head_sha"],
                               "merge_sha": correction["merge"]["merge_sha"], "state": "MERGED"},
                "correction ledger does not bind actual corrective merge")
    return e


def manifest(source: Path, commit: str) -> dict:
    sha(commit)
    source = source.resolve(strict=True)

    def git(*args: str) -> bytes:
        # Fixed read-only local commands; no fetch, hooks, filters or shell.
        result = subprocess.run(
            ["git", "--no-replace-objects", "-c", f"safe.directory={source.as_posix()}",
             "-c", "core.fsmonitor=false",
             "-c", "protocol.allow=never", "-C", str(source), *args],
            capture_output=True, check=False,
            env={**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_ALLOW_PROTOCOL": "",
                 "GIT_OPTIONAL_LOCKS": "0"},
        )
        require(result.returncode == 0, "canonical Git source verification failed")
        return result.stdout

    require(Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve() == source,
            "source must be the canonical repository root")
    require(git("rev-parse", "--verify", "HEAD^{commit}").decode().strip() == commit,
            "source checkout differs from the canonical commit")
    require(git("config", "--get", "remote.origin.url").decode().strip() in {
        "https://github.com/gabned/provelume", "https://github.com/gabned/provelume.git",
        "git@github.com:gabned/provelume.git", "ssh://git@github.com/gabned/provelume.git",
    }, "source repository is not canonical Core")
    require(not git("status", "--porcelain=v1", "--untracked-files=normal").strip(),
            "canonical source checkout is dirty")
    entries = {}
    tree = git("ls-tree", "-r", "--full-tree", commit, "--", *VENDOR_FILES)
    for line in tree.decode().splitlines():
        metadata, name = line.split("\t", 1)
        mode, kind, oid = metadata.split()
        require(kind == "blob", "canonical source entry is not a blob")
        entries[name] = (mode, oid)
    rows = []
    for relative, mode in VENDOR_FILES.items():
        target = safe_file(source, relative)
        require(target.is_file(), f"missing canonical file: {relative}")
        data = target.read_bytes()
        require(entries.get(relative) == (mode, blob(data)) and
                git("cat-file", "blob", f"{commit}:{relative}") == data,
                f"source bytes/mode differ from canonical commit: {relative}")
        rows.append({"path": relative, "mode": mode, "sha256": hashlib.sha256(data).hexdigest(),
                     "git_blob": blob(data)})
    return {"protocol_version": VERSION, "source_repository": "gabned/provelume",
            "source_commit": commit, "files": rows}


def validate_manifest(value: Any) -> dict:
    m = obj(value, "protocol_version source_repository source_commit files", "vendor manifest")
    require(m["protocol_version"] == VERSION and m["source_repository"] == "gabned/provelume",
            "wrong canonical source")
    sha(m["source_commit"])
    rows = array(m["files"], "vendor files")
    require(len(rows) == len(VENDOR_FILES), "incomplete vendor manifest")
    require([r.get("path") for r in rows] == list(VENDOR_FILES), "wrong vendor paths/order")
    for row in rows:
        obj(row, "path mode sha256 git_blob", "vendor file")
        require(row["mode"] == VENDOR_FILES[row["path"]], "vendor mode mismatch")
        sha(row["sha256"], 64)
        sha(row["git_blob"])
    return m


def safe_file(root: Path, relative: str) -> Path:
    path(relative)
    root = root.resolve(strict=True)
    target = root / relative
    cursor = target
    while cursor != root:
        require(not cursor.is_symlink(), "symlink target is forbidden")
        cursor = cursor.parent
    require(target.resolve().is_relative_to(root), "path escapes repository root")
    require(not target.exists() or target.is_file(), "target is not a regular file")
    return target


def provenance_files(m: dict) -> dict[str, bytes]:
    validate_manifest(m)
    planned = {MANIFEST_PATH: (json.dumps(m, indent=2, ensure_ascii=False) + "\n").encode()}
    lines = ["# Agent Development Protocol 1.4.2 — canonical provenance", "",
             "Generated by the offline canonical synchronizer; do not edit by hand.", "",
             f"Source: gabned/provelume@{m['source_commit']}", "",
             "| File | SHA-256 | Git blob | Mode |", "| --- | --- | --- | --- |"]
    lines.extend(f"| `{r['path']}` | `{r['sha256']}` | `{r['git_blob']}` | `{r['mode']}` |"
                 for r in m["files"])
    planned[PROVENANCE_PATH] = ("\n".join(lines) + "\n").encode()
    return planned


def sync_vendor(source: Path, target: Path, commit: str, *, check: bool = False) -> dict:
    m = manifest(source, commit)
    planned = {relative: safe_file(source, relative).read_bytes() for relative in VENDOR_FILES}
    require(all(blob(planned[row["path"]]) == row["git_blob"] for row in m["files"]),
            "canonical source changed during synchronization")
    planned.update(provenance_files(m))
    destinations = {name: safe_file(target, name) for name in planned}
    executable = {name: VENDOR_FILES.get(name, "100644") == "100755" for name in planned}
    changed = [name for name, dest in destinations.items()
               if not dest.exists() or dest.read_bytes() != planned[name] or
               (os.name != "nt" and bool(dest.stat().st_mode & stat.S_IXUSR) != executable[name])]
    if check:
        require(not changed, "canonical vendor/provenance drift: " + ", ".join(changed))
    elif changed:
        originals = {name: destinations[name].read_bytes() if destinations[name].exists()
                     else None for name in changed}
        original_modes = {name: stat.S_IMODE(destinations[name].stat().st_mode)
                          for name in changed if destinations[name].exists()}
        applied = []
        with tempfile.TemporaryDirectory(prefix=".protocol142-", dir=target) as tmp:
            try:
                for index, name in enumerate(changed):
                    staged = Path(tmp) / str(index)
                    staged.write_bytes(planned[name])
                    if os.name != "nt":
                        # Preserve checkout restrictions; Git tracks only owner execution.
                        mode = original_modes.get(name, stat.S_IMODE(staged.stat().st_mode))
                        mode = mode | stat.S_IXUSR if executable[name] else mode & ~stat.S_IXUSR
                        staged.chmod(mode)
                    dest = destinations[name]
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(staged, dest)
                    applied.append(name)
                    require(dest.read_bytes() == planned[name] and
                            (os.name == "nt" or stat.S_IMODE(dest.stat().st_mode) == mode),
                            "installed vendor bytes/mode verification failed")
            except (OSError, ValueError):
                for name in reversed(applied):
                    if originals[name] is None:
                        destinations[name].unlink()
                    else:
                        restored = Path(tmp) / ("restore-" + str(len(applied)))
                        restored.write_bytes(originals[name])
                        if os.name != "nt":
                            restored.chmod(original_modes[name])
                        os.replace(restored, destinations[name])
                raise
    return {"result": "PASS", "manifest": m, "changed_paths": changed, "check_only": check}


def validate_audit_input(
    value: Any, *, now: datetime | None = None,
    expected_repositories: frozenset[str] | None = None,
    operation_validator=None,
) -> dict:
    a = obj(value, "protocol_version campaign_ref canonical source observed_at repositories",
            "five-repository audit")
    observation(a, now)
    require(a["protocol_version"] == VERSION, "wrong audit protocol")
    require(re.fullmatch(r"https://github[.]com/gabned/provelume/issues/[1-9][0-9]*",
                         a["campaign_ref"]) is not None, "unbound campaign")
    canonical_manifest = validate_manifest(a["canonical"])
    rows = array(a["repositories"], "repositories")
    expected = set(PROFILES) if expected_repositories is None else expected_repositories
    require(isinstance(expected, set | frozenset) and "gabned/provelume" in expected
            and expected <= set(PROFILES), "invalid independently selected audit scope")
    require(len(rows) == len(expected) and {r.get("repository") for r in rows} == expected,
            "audit must cover exactly the five repositories" if expected_repositories is None
            else "audit must cover exactly the authorized repositories")
    for raw in rows:
        r = obj(raw, "repository default_branch profile default_sha operations vendor_manifest "
                "vendor_files provenance_files registry open_campaign_prs unresolved_threads",
                "audit repository")
        require((r["default_branch"], r["profile"]) == PROFILES[r["repository"]],
                "repository profile/default branch drift")
        sha(r["default_sha"])
        require(r["open_campaign_prs"] == [] and r["unresolved_threads"] == [],
                "campaign still has open PRs or unresolved threads")
        operations = array(r["operations"], "operation history")
        require(bool(operations), "missing repository integration evidence")
        for operation in operations:
            e = (validate_operations(operation, now=now) if operation_validator is None
                 else operation_validator(operation, now=now))
            integrations = [e] + [f[key] for f in e["late_findings"]
                                  for key in ("origin", "correction")]
            for integration in integrations:
                references = re.findall(r"(?m)^CAMPAIGN_REF:[ \t]*([^\r\n]+?)[ \t]*$",
                                        integration["pr"]["body"])
                require(references == [a["campaign_ref"]],
                        "integration operation does not bind the audited campaign")
            require(e["phase"] == "POST_MERGE" and e["pr"]["repository"] == r["repository"]
                    and e["merge"]["default_sha"] == r["default_sha"], "unreconciled repository")
        if r["repository"] == "gabned/nexus":
            require(r["vendor_manifest"] is None and r["vendor_files"] == [] and
                    r["provenance_files"] == [],
                    "Nexus cannot become a runtime vendor")
            registry = obj(r["registry"], "path commit_sha git_blob content", "Nexus registry")
            path(registry["path"])
            require(any(registry["path"] in e["pr"]["changed_paths"] for e in operations),
                    "registry path does not bind the audited integration")
            require(registry["commit_sha"] == r["default_sha"] and
                    isinstance(registry["content"], str),
                    "wrong Nexus registry")
            require(blob(registry["content"].encode()) == registry["git_blob"],
                    "registry content/blob mismatch")
            for marker in (VERSION, canonical_manifest["source_commit"], a["campaign_ref"]):
                require(marker in registry["content"], "registry lacks final provenance")
            for integrated in rows:
                if integrated["repository"] == "gabned/nexus":
                    continue
                require(integrated["repository"] in registry["content"] and
                        integrated["default_sha"] in registry["content"],
                        "registry lacks a final repository/default identity")
                for operation in integrated["operations"]:
                    ref = (f"https://github.com/{integrated['repository']}/pull/"
                           f"{operation['pr']['number']}")
                    require(ref in registry["content"], "registry lacks an integration PR")
        else:
            require(r["registry"] is None and r["vendor_manifest"] == canonical_manifest,
                    "canonical manifest drift")
            files = array(r["vendor_files"], "observed vendor files")
            require(len(files) == len(VENDOR_FILES), "missing observed vendor bytes")
            require([f.get("path") for f in files] == list(VENDOR_FILES), "wrong observed paths")
            for f, expected in zip(files, canonical_manifest["files"], strict=True):
                obj(f, "path commit_sha mode git_blob content", "observed vendor")
                require(f["commit_sha"] == r["default_sha"], "vendor observed at wrong commit")
                require(isinstance(f["content"], str), "vendor content missing")
                data = f["content"].encode()
                require(f["mode"] == expected["mode"] and f["git_blob"] == expected["git_blob"]
                        and blob(data) == expected["git_blob"] and
                        hashlib.sha256(data).hexdigest() == expected["sha256"], "vendor byte drift")
            provenance = array(r["provenance_files"], "observed provenance files")
            if r["repository"] == "gabned/provelume":
                require(not provenance, "Core source cannot claim self-referential provenance")
            else:
                expected_files = provenance_files(canonical_manifest)
                require([f.get("path") for f in provenance] == list(expected_files),
                        "missing or unexpected observed provenance paths")
                for f in provenance:
                    obj(f, "path commit_sha mode git_blob content", "observed provenance")
                    expected_content = expected_files[f["path"]]
                    require(f["commit_sha"] == r["default_sha"] and f["mode"] == "100644" and
                            isinstance(f["content"], str) and
                            f["content"].encode() == expected_content and
                            f["git_blob"] == blob(expected_content),
                            "default-commit provenance drift")
    core = next(r for r in rows if r["repository"] == "gabned/provelume")
    require(any(e["merge"]["merge_sha"] == canonical_manifest["source_commit"]
                for e in core["operations"]), "canonical source is not an audited Core merge")
    return a


def generate_audit(value: Any) -> dict:
    a = validate_audit_input(value)
    # Generation and archive replay must agree on the same observation window.
    validate_audit_input(a, now=timestamp(a["observed_at"]))
    return {"protocol_version": VERSION, "result": "PASS", "evidence": deepcopy(a),
            "evidence_sha256": digest(a)}


def validate_audit(value: Any) -> dict:
    r = obj(value, "protocol_version result evidence evidence_sha256", "closure receipt")
    require(r["protocol_version"] == VERSION and r["result"] == "PASS", "invalid closure outcome")
    require(r["evidence_sha256"] == digest(r["evidence"]), "closure receipt rewritten")
    validate_audit_input(r["evidence"], now=timestamp(r["evidence"]["observed_at"]))
    return r


def command(args: Any) -> dict:
    if args.command == "sync-vendor":
        return sync_vendor(args.source, args.target, args.commit, check=args.check)
    value = json.loads(args.path.read_text(encoding="utf-8"))
    handlers = {"validate-operations": validate_operations, "generate-audit": generate_audit,
                "validate-audit": validate_audit, "validate-wait": validate_wait,
                "render-pr-identity": render_pr_identity}
    result = handlers[args.command](value)
    if args.command in {"generate-audit", "validate-audit"}:
        return result
    return {"protocol_version": VERSION, "result": "PASS", "value": result}
