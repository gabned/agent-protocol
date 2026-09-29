"""Verify and plan byte-identical vendoring under an accepted local adapter profile.

The plan is read-only. The repository's authorized host applies it through normal
change control. Native wrappers, policy, PRODUCT state and pins are separately
qualified; a file copy alone is never reported as completed adoption.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from .ledger import digest, exact, require
from .source import safe_path, validate_inventory


def plan(
    source_root,
    target_root,
    manifest,
    profile,
    *,
    accepted_manifest_digest,
    accepted_profile_digest,
    previous_files,
):
    validate_inventory(manifest, accepted_manifest_digest)
    require(digest(profile) == accepted_profile_digest, "Local adoption profile not accepted")
    exact(
        profile,
        "schema repository repository_id source_repository prefix entrypoints",
        "adapter profile",
    )
    require(
        profile["schema"] == "agent-protocol-adapter/v2"
        and profile["source_repository"] == manifest["repository"],
        "Adapter source mismatch",
    )
    prefix = safe_path(profile["prefix"])
    require(
        prefix.startswith(".github/agent-protocol/") and profile["entrypoints"],
        "Accepted canonical vendor location and native entrypoints required",
    )
    source_root, target_root = Path(source_root).resolve(), Path(target_root).resolve()
    rows, paths = [], set()
    for record in manifest["files"]:
        name = record["path"]
        source, destination = source_root / name, target_root / prefix / name
        require(
            not any(
                p.is_symlink() for p in (source, *source.parents, destination, *destination.parents)
            ),
            "Symlink vendor path refused",
        )
        data = source.read_bytes()
        require(
            hashlib.sha256(data).hexdigest() == record["sha256"], "Canonical source bytes changed"
        )
        relative = prefix + "/" + name
        before = (
            hashlib.sha256(destination.read_bytes()).hexdigest() if destination.exists() else None
        )
        if before != record["sha256"]:
            require(
                before == previous_files.get(relative),
                "Local vendor edits or unmanaged file preserved",
            )
        rows.append(
            {
                "source": name,
                "destination": relative,
                "before": before,
                "after": record["sha256"],
                "mode": record["mode"],
                "action": "KEEP" if before == record["sha256"] else "COPY_CANONICAL",
            }
        )
        paths.add(relative)
    # Historical receipt material and removed files need an explicit compatibility
    # decision; this operation cannot silently delete them.
    retained = sorted(set(previous_files) - paths)
    return {
        "schema": "agent-protocol-adoption-plan/v2",
        "revision": manifest["revision"],
        "repository": profile["repository"],
        "files": rows,
        "retained_for_compatibility_review": retained,
        "entrypoints": profile["entrypoints"],
        "adoption": "REQUIRES_NATIVE_CONFORMANCE",
        "migration": "NOT_PERFORMED",
        "cleanup": "REQUIRES_REFERENCE_AND_RECEIPT_AUDIT",
    }


def assess_migration(legacy, *, accepted_validator_result, active_owner, coordinated_grant):
    """Preserve legacy identity/results; never edit or relabel a historical receipt."""
    exact(
        legacy,
        "schema role owner state receipt_reference receipt_sha256",
        "legacy state observation",
    )
    require(
        accepted_validator_result == "PASS", "Legacy state has not passed its original validator"
    )
    if legacy["role"] == "CACHE":
        return {
            "migration": "NOT_REQUIRED",
            "treatment": "KEEP_USEFUL_CACHE_INFORMATION",
            "legacy": legacy,
        }
    require(legacy["role"] == "AUTHORITATIVE", "Unknown legacy authority")
    require(
        legacy["receipt_reference"] and len(legacy["receipt_sha256"]) == 64,
        "Recoverable original receipt required",
    )
    if active_owner:
        require(legacy["owner"] == active_owner, "Owner observation inconsistent")
        return {
            "migration": "BLOCKED",
            "dependency": "COORDINATED_LEGACY_OWNER_OPERATION",
            "grant_observed": bool(coordinated_grant),
            "legacy": legacy,
        }
    return {
        "migration": "NEW_WORKSTREAM_ONLY",
        "treatment": "PRESERVE_ORIGINAL_VALIDATOR_AND_RESULT",
        "legacy": legacy,
    }
