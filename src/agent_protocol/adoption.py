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
    accepted_previous_files_digest,
    observed_modes,
):
    validate_inventory(manifest, accepted_manifest_digest)
    require(digest(profile) == accepted_profile_digest, "Local adoption profile not accepted")
    require(
        digest(previous_files) == accepted_previous_files_digest,
        "Previous managed inventory differs from independently retained state",
    )
    require(
        isinstance(previous_files, dict) and isinstance(observed_modes, dict),
        "Complete prior managed files and observed Git modes required",
    )
    for name, previous in previous_files.items():
        safe_path(name)
        exact(previous, "sha256 mode", "previous managed file")
        require(previous["mode"] in {"100644", "100755"}, "Unsafe previous mode")
        require(
            isinstance(previous["sha256"], str)
            and len(previous["sha256"]) == 64
            and all(c in "0123456789abcdef" for c in previous["sha256"]),
            "Invalid previous file digest",
        )
    require(
        len({name.casefold() for name in previous_files}) == len(previous_files),
        "Case-insensitive previous inventory collision",
    )
    require(
        all(mode in {"100644", "100755"} for mode in observed_modes.values()),
        "Unsupported observed destination mode",
    )
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
        all(name.startswith(prefix + "/") for name in previous_files),
        "Previous managed inventory escapes accepted vendor prefix",
    )
    require(
        not {part.casefold() for part in prefix.split("/")} & {".git", ".agent"}
        and isinstance(profile["entrypoints"], list)
        and profile["entrypoints"],
        "Accepted durable vendor location and native entrypoints required",
    )
    for entrypoint in profile["entrypoints"]:
        entrypoint = safe_path(entrypoint).casefold()
        require(
            entrypoint != prefix.casefold() and not entrypoint.startswith(prefix.casefold() + "/"),
            "Native adapter cannot overlap the canonical vendor package",
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
        mode = observed_modes.get(relative)
        require(
            (before is None and mode is None)
            or (before is not None and mode in {"100644", "100755"}),
            "Missing or inconsistent observed destination Git mode",
        )
        current = {"sha256": before, "mode": mode}
        canonical_file = {"sha256": record["sha256"], "mode": record["mode"]}
        if before is not None and current != canonical_file:
            require(
                current == previous_files.get(relative),
                "Local vendor edits or unmanaged file preserved",
            )
        rows.append(
            {
                "source": name,
                "destination": relative,
                "before": before,
                "before_mode": mode,
                "after": record["sha256"],
                "mode": record["mode"],
                "action": "KEEP" if current == canonical_file else "COPY_CANONICAL",
            }
        )
        paths.add(relative)
    require(set(observed_modes) <= paths | set(previous_files), "Unmanaged mode inventory")
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
