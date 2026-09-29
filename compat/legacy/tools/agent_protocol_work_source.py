#!/usr/bin/env python3
"""Proposed Work source adapter. Offline integrity is never GitHub authority.

No Git, shell, credentials, repository mutation or application execution.
Connector observations must be collected by an authorized caller, independently
of this verifier. A digest proves integrity, not authentication or freshness.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import re
import stat
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

SCHEMA = "agent-work-source/v1"
MAX_ENTRIES = 100_000
MAX_BLOB = 100 * 1024 * 1024
MAX_TOTAL = 512 * 1024 * 1024
SHA = re.compile(r"[0-9a-f]{40}\Z")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


class EvidenceError(ValueError):
    """Evidence is incomplete, inconsistent or outside the supported profile."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()


def object_sha(kind: str, data: bytes) -> str:
    return hashlib.sha1(kind.encode() + b" " + str(len(data)).encode() + b"\0" + data).hexdigest()


def valid_sha(value: Any) -> str:
    require(
        isinstance(value, str) and SHA.fullmatch(value) is not None,
        "expected exact SHA-1 object identity",
    )
    return value


def valid_path(value: Any) -> str:
    require(isinstance(value, str) and bool(value), "empty or non-string path")
    require(
        not value.startswith("/") and "\\" not in value and "\0" not in value,
        "absolute, NUL or noncanonical path",
    )
    parts = value.split("/")
    require(all(part not in ("", ".", "..") for part in parts), "path traversal")
    require(all(part.casefold() != ".git" for part in parts), "Git metadata is not a source file")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise EvidenceError("non-UTF-8 path unsupported by connector") from exc
    return value


def validate_entries(raw: Any) -> dict[str, dict]:
    require(isinstance(raw, list) and len(raw) <= MAX_ENTRIES, "tree entry limit or type")
    entries: dict[str, dict] = {}
    total = 0
    for row in raw:
        require(isinstance(row, dict), "invalid tree entry")
        name = valid_path(row.get("path"))
        require(name not in entries, "duplicate tree path")
        mode, kind = row.get("mode"), row.get("type")
        require(
            (mode, kind) in {("100644", "blob"), ("100755", "blob"), ("040000", "tree")},
            "unsupported source mode: symlinks/submodules require a qualified adapter",
        )
        valid_sha(row.get("sha"))
        entry = {key: row[key] for key in ("path", "mode", "type", "sha")}
        if kind == "blob":
            size = row.get("size")
            require(type(size) is int and 0 <= size <= MAX_BLOB, "invalid or oversized blob")
            total += size
            require(total <= MAX_TOTAL, "source size limit exceeded")
            entry["size"] = size
        entries[name] = entry
    for name in entries:
        if "/" in name:
            parent = name.rsplit("/", 1)[0]
            require(parent in entries and entries[parent]["type"] == "tree", "missing parent tree")
    return entries


def tree_identity(entries: dict[str, dict], *, verify: bool, hashes_out: dict | None = None) -> str:
    children: dict[str, list[dict]] = {"": []}
    for name, entry in entries.items():
        parent = name.rsplit("/", 1)[0] if "/" in name else ""
        children.setdefault(parent, []).append(entry)
        if entry["type"] == "tree":
            children.setdefault(name, [])
    hashes = {}
    for parent in sorted(children, key=lambda x: x.count("/") + bool(x), reverse=True):

        def sort_key(entry: dict) -> bytes:
            suffix = "/" if entry["type"] == "tree" else ""
            return (entry["path"].rsplit("/", 1)[-1] + suffix).encode("utf-8")

        body = b""
        for entry in sorted(children[parent], key=sort_key):
            name = entry["path"].rsplit("/", 1)[-1].encode("utf-8")
            sha = hashes[entry["path"]] if entry["type"] == "tree" else entry["sha"]
            if verify and entry["type"] == "tree":
                require(sha == entry["sha"], "subtree hash mismatch")
            body += entry["mode"].lstrip("0").encode() + b" " + name + b"\0" + bytes.fromhex(sha)
        hashes[parent] = object_sha("tree", body)
    if hashes_out is not None:
        hashes_out.update(hashes)
    return hashes[""]


def require_representable_trees(entries: dict[str, dict]) -> None:
    # Git's file-path diff/index cannot represent nested empty trees. A source
    # adapter must not claim a complete path delta after silently dropping them.
    parents = {name.rpartition("/")[0] for name in entries}
    require(all(row["type"] != "tree" or name in parents for name, row in entries.items()),
            "empty source subtrees require a qualified path-delta adapter")


def validate_snapshot(snapshot: Any, repository: str, commit: str) -> dict[str, dict]:
    require(REPOSITORY.fullmatch(repository) is not None, "invalid repository")
    valid_sha(commit)
    require(
        isinstance(snapshot, dict) and snapshot.get("schema") == SCHEMA, "source schema mismatch"
    )
    require(snapshot.get("repository") == repository, "repository mismatch")
    require(snapshot.get("commit_sha") == commit, "base commit mismatch")
    valid_sha(snapshot.get("tree_sha"))
    tree = snapshot.get("tree")
    require(isinstance(tree, dict) and tree.get("truncated") is False, "incomplete tree")
    require(tree.get("sha") == snapshot["tree_sha"], "root tree identity mismatch")
    entries = validate_entries(tree.get("tree"))
    require_representable_trees(entries)
    require(tree_identity(entries, verify=True) == snapshot["tree_sha"], "root tree hash mismatch")
    return entries


def read_regular(path: Path) -> bytes:
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode), "source is not a regular file")
    require(before.st_size <= MAX_BLOB, "file size limit")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        require(
            (before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino),
            "file changed while opening",
        )
        data = stream.read(MAX_BLOB + 1)
        after = os.fstat(stream.fileno())
    require(len(data) <= MAX_BLOB, "file size limit")
    require(
        (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
        == (after.st_size, after.st_mtime_ns, after.st_ctime_ns),
        "file changed while reading",
    )
    require(
        not data.startswith(b"version https://git-lfs.github.com/spec/v1\n"),
        "Git LFS pointer requires separately verified LFS objects",
    )
    return data


def inventory(root: Path) -> dict[str, dict]:
    require(os.name == "posix", "POSIX mode verification unavailable; no inferred executable modes")
    require(root.is_dir() and not root.is_symlink(), "source must be a real directory")
    entries = {}
    total = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in sorted(dirs + files):
            path = Path(directory) / name
            relative = valid_path(path.relative_to(root).as_posix())
            mode = path.lstat().st_mode
            require(not stat.S_ISLNK(mode), "symlink in source")
            if stat.S_ISDIR(mode):
                entries[relative] = {
                    "path": relative,
                    "mode": "040000",
                    "type": "tree",
                    "sha": "0" * 40,
                }
            else:
                data = read_regular(path)
                total += len(data)
                require(total <= MAX_TOTAL, "source size limit exceeded")
                entries[relative] = {
                    "path": relative,
                    "mode": "100755" if mode & stat.S_IXUSR else "100644",
                    "type": "blob",
                    "sha": object_sha("blob", data),
                    "size": len(data),
                }
            require(len(entries) <= MAX_ENTRIES, "source entry limit exceeded")
    # Compute every directory exactly once; avoid quadratic subtree rescans.
    require_representable_trees(entries)
    hashes: dict[str, str] = {}
    tree_identity(entries, verify=False, hashes_out=hashes)
    for name, entry in entries.items():
        if entry["type"] == "tree":
            entry["sha"] = hashes[name]
    return entries


def verify_source(snapshot: dict, root: Path, repository: str, commit: str) -> dict:
    expected = validate_snapshot(snapshot, repository, commit)
    actual = inventory(root)
    require(actual == expected, "source content, file modes or complete path set differs from tree")
    return {
        "schema": SCHEMA,
        "repository": repository,
        "commit_sha": commit,
        "tree_sha": snapshot["tree_sha"],
        "files": sum(e["type"] == "blob" for e in actual.values()),
        "directories": sum(e["type"] == "tree" for e in actual.values()),
        "source_integrity": "VERIFIED",
        "authentication": "CALLER_MUST_VERIFY",
        "push_qualified": False,
        "application_checks_run": False,
    }


def materialize(snapshot: dict, blobs: Path, parent: Path, repository: str, commit: str) -> Path:
    require(os.name == "posix", "POSIX source materialization unavailable; no inferred file modes")
    entries = validate_snapshot(snapshot, repository, commit)
    require(blobs.is_dir() and not blobs.is_symlink(), "blob cache must be a real directory")
    # Validate the complete input before writing; files are raw Git blob bytes.
    for entry in entries.values():
        if entry["type"] == "blob":
            data = read_regular(blobs / entry["sha"])
            require(
                len(data) == entry["size"] and object_sha("blob", data) == entry["sha"],
                "blob cache mismatch",
            )
    require(parent.is_dir() and not parent.is_symlink(), "destination parent unavailable")
    destination = Path(tempfile.mkdtemp(prefix="work-source-", dir=parent))
    # A failed partial reconstruction is retained as evidence, never reported ready.
    for entry in sorted(entries.values(), key=lambda e: (e["path"].count("/"), e["path"])):
        target = destination / entry["path"]
        if entry["type"] == "tree":
            target.mkdir(mode=0o700)
        else:
            data = read_regular(blobs / entry["sha"])
            require(
                object_sha("blob", data) == entry["sha"],
                "blob cache changed during materialization",
            )
            with target.open("xb") as stream:
                stream.write(data)
            target.chmod(0o700 if entry["mode"] == "100755" else 0o600)
    verify_source(snapshot, destination, repository, commit)
    return destination


def decode_blob(response: dict) -> bytes:
    require(response.get("encoding") == "base64", "lossless base64 blob response required")
    encoded = response.get("content")
    require(isinstance(encoded, str), "missing blob content")
    try:
        data = base64.b64decode(encoded.replace("\n", "").replace("\r", ""), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise EvidenceError("invalid blob base64") from exc
    require(
        type(response.get("size")) is int and len(data) == response["size"] <= MAX_BLOB,
        "blob size mismatch",
    )
    require(
        object_sha("blob", data) == valid_sha(response.get("sha")), "downloaded blob hash mismatch"
    )
    return data


def candidate_delta(
    snapshot: dict, baseline: Path, candidate: Path, repository: str, commit: str
) -> dict:
    verify_source(snapshot, baseline, repository, commit)
    before = validate_snapshot(snapshot, repository, commit)
    after = inventory(candidate)
    changed = []
    for name in sorted(set(before) | set(after)):
        old, new = before.get(name), after.get(name)
        old = old if old and old["type"] == "blob" else None
        new = new if new and new["type"] == "blob" else None
        if old == new:
            continue
        changed.append({"path": name, "before": old, "after": new})
    return {
        "schema": "agent-work-delta/v1",
        "repository": repository,
        "base_commit_sha": commit,
        "base_tree_sha": snapshot["tree_sha"],
        "candidate_tree_sha": tree_identity(after, verify=True),
        "candidate_commit_sha": None,
        "changes": changed,
        "changed_paths_complete": True,
        "push_qualified": False,
    }


def verify_live_anchor(snapshot: dict, observations: dict, *, now: datetime | None = None) -> None:
    """Check content/freshness of caller-collected observations; no authentication claim."""
    clock = now or datetime.now(UTC)
    repository = snapshot["repository"]
    branch = observations.get("default_branch")
    require(isinstance(branch, str) and bool(branch), "missing observed default branch")
    prefix = f"https://api.github.com/repos/{repository}"
    for label, endpoint in [
        ("repository", ""),
        ("before", f"/git/ref/heads/{quote(branch, safe='')}"),
        ("after", f"/git/ref/heads/{quote(branch, safe='')}"),
        ("commit", f"/git/commits/{snapshot['commit_sha']}"),
    ]:
        item = observations.get(label)
        require(
            isinstance(item, dict) and item.get("url") == prefix + endpoint,
            "observation endpoint mismatch",
        )
        try:
            timestamp = datetime.fromisoformat(item["observed_at"].replace("Z", "+00:00"))
            require(timestamp.tzinfo is not None, "timestamp needs timezone")
            age = (clock - timestamp).total_seconds()
        except (KeyError, TypeError, ValueError) as exc:
            raise EvidenceError("invalid observation timestamp") from exc
        require(-30 <= age <= 900, "stale/future observation requires a new bounded connector read")
        value = item.get("response", {})
        if label == "repository":
            require(
                value.get("full_name") == repository and value.get("default_branch") == branch,
                "repository/default branch mismatch",
            )
        elif label == "commit":
            require(
                value.get("sha") == snapshot["commit_sha"]
                and value.get("tree", {}).get("sha") == snapshot["tree_sha"],
                "observed commit/tree mismatch",
            )
        else:
            require(
                value.get("ref") == "refs/heads/" + branch
                and value.get("object", {}).get("type") == "commit"
                and value.get("object", {}).get("sha") == snapshot["commit_sha"],
                "default branch moved or mismatched",
            )
    before = datetime.fromisoformat(observations["before"]["observed_at"].replace("Z", "+00:00"))
    after = datetime.fromisoformat(observations["after"]["observed_at"].replace("Z", "+00:00"))
    metadata = datetime.fromisoformat(
        observations["repository"]["observed_at"].replace("Z", "+00:00")
    )
    commit = datetime.fromisoformat(observations["commit"]["observed_at"].replace("Z", "+00:00"))
    require(metadata <= before <= commit <= after, "observation order mismatch")


def canonical_input(snapshot_path: Path, anchor_path: Path, *, now: datetime | None = None) -> dict:
    snapshot, anchor = read_json(snapshot_path), read_json(anchor_path)
    require(snapshot.get("repository") == "gabned/provelume",
            "canonical vendor repository mismatch")
    validate_snapshot(snapshot, "gabned/provelume", snapshot.get("commit_sha"))
    verify_live_anchor(snapshot, anchor, now=now)
    return {"repository": snapshot["repository"], "commit_sha": snapshot["commit_sha"],
            "tree_sha": snapshot["tree_sha"], "snapshot_sha256": digest(snapshot),
            "anchor_sha256": digest(anchor)}


def verify_receipt(
    receipt: dict, delta: dict, *, suite: str, command_digest: str,
    canonical_snapshot: Path | None = None, canonical_anchor: Path | None = None,
) -> None:
    """A locally produced check receipt is not an external gate/CI receipt."""
    require(receipt.get("schema") == "agent-work-check/v1", "check receipt schema mismatch")
    require(
        receipt.get("repository") == delta["repository"]
        and receipt.get("base_commit_sha") == delta["base_commit_sha"]
        and receipt.get("candidate_tree_sha") == delta["candidate_tree_sha"],
        "check receipt source drift",
    )
    require(
        receipt.get("suite") == suite and receipt.get("command_digest") == command_digest,
        "check receipt command/profile mismatch",
    )
    require(
        type(receipt.get("exit_code")) is int and receipt["exit_code"] == 0, "check did not succeed"
    )
    require(receipt.get("source_unchanged") is True, "source changed during check")
    require(
        receipt.get("timed_out") is False
        and receipt.get("launch_error") is None
        and receipt.get("source_error") is None
        and receipt.get("adapter_exit_code") == 0,
        "incomplete or interrupted check receipt",
    )
    require(receipt.get("push_qualified") is False, "local test cannot qualify publication")
    require("canonical_source" in receipt, "check receipt lacks canonical input binding")
    require((canonical_snapshot is None) == (canonical_anchor is None),
            "canonical snapshot and anchor must be supplied together")
    if receipt["canonical_source"] is None:
        require(canonical_snapshot is None, "unexpected canonical input for ordinary check")
    else:
        require(canonical_snapshot is not None,
                "canonical check requires retained independent inputs")
        checked_at = datetime.fromisoformat(receipt["started_at"].replace("Z", "+00:00"))
        require(checked_at.tzinfo is not None, "check start timestamp needs timezone")
        expected = canonical_input(canonical_snapshot, canonical_anchor, now=checked_at)
        require(receipt["canonical_source"] == expected, "canonical check input identity changed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["verify", "materialize", "delta", "anchor"])
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--blobs", type=Path)
    parser.add_argument("--parent", type=Path)
    parser.add_argument("--observations", type=Path)
    args = parser.parse_args()
    try:
        snapshot = read_json(args.snapshot)
        validate_snapshot(snapshot, args.repository, args.commit)
        if args.command == "verify":
            require(args.source is not None, "--source required")
            result = verify_source(snapshot, args.source, args.repository, args.commit)
        elif args.command == "materialize":
            require(
                args.blobs is not None and args.parent is not None, "--blobs and --parent required"
            )
            path = materialize(snapshot, args.blobs, args.parent, args.repository, args.commit)
            result = {"source_path": str(path), "push_qualified": False}
        elif args.command == "delta":
            require(
                args.source is not None and args.candidate is not None,
                "--source and --candidate required",
            )
            result = candidate_delta(
                snapshot, args.source, args.candidate, args.repository, args.commit
            )
        else:
            require(args.observations is not None, "--observations required")
            verify_live_anchor(snapshot, read_json(args.observations))
            result = {
                "anchor_consistency": "VERIFIED",
                "authentication": "CALLER_MUST_VERIFY",
                "push_qualified": False,
            }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (EvidenceError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"result": "BLOCKED", "reason": str(exc), "push_qualified": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
