"""Load the preserved validators without a product checkout or import path mutation."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
import tarfile
from functools import cache
from pathlib import Path

from .ledger import canonical, exact, require, sha

ROOT = Path(__file__).resolve().parents[2]
if not (ROOT / "compat/legacy/tools").is_dir():
    ROOT = Path(__file__).resolve().parent / "_distribution"
LEGACY = ROOT / "compat/legacy/tools"
MODULES = frozenset({"agent_protocol_v1_4_9", "agent_protocol_v1_4_2_ops"})


@cache
def legacy(name):
    require(name in MODULES, "Unregistered compatibility validator")
    path = LEGACY / (name + ".py")
    require(path.is_file() and not path.is_symlink(), "Compatibility validator missing")
    spec = importlib.util.spec_from_file_location("agent_protocol_compat_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def safe_path(value):
    require(
        isinstance(value, str) and value and "\\" not in value and ":" not in value,
        "Invalid distribution path",
    )
    require(
        not value.startswith("/") and all(p not in {"", ".", ".."} for p in value.split("/")),
        "Distribution path escapes root",
    )
    require(all(ord(c) >= 32 for c in value), "Invalid control character in path")
    return value


def validate_inventory(manifest, expected_digest):
    require(
        hashlib.sha256(canonical(manifest)).hexdigest() == expected_digest,
        "Inventory differs from independently selected release record",
    )
    exact(manifest, "schema repository repository_id revision version files", "source inventory")
    require(manifest["schema"] == "agent-protocol-source/v1", "Unsupported source schema")
    sha(manifest["revision"])
    require(
        manifest["repository"] == "gabned/agent-protocol"
        and manifest["repository_id"] == 1393711644,
        "Canonical source identity changed",
    )
    require(manifest["version"] == "1.5.0", "Unsupported current distribution identity")
    require(isinstance(manifest["files"], list) and manifest["files"], "Empty source inventory")
    folded, names = set(), set()
    for row in manifest["files"]:
        exact(row, "path mode blob sha256", "file record")
        name = safe_path(row["path"])
        require(
            name not in names and name.casefold() not in folded, "Duplicate/colliding source path"
        )
        require(row["mode"] in {"100644", "100755"}, "Unsafe source mode")
        sha(row["blob"])
        require(re.fullmatch(r"[0-9a-f]{64}", row["sha256"]), "Invalid file digest")
        names.add(name)
        folded.add(name.casefold())
    return manifest


def git_inventory(repository, revision):
    """Inventory exact committed bytes; never import from or execute the candidate."""
    sha(revision)
    command = ["git", "--no-replace-objects", "-C", str(repository)]

    def git(*args):
        return subprocess.check_output([*command, *args])

    require(
        git("rev-parse", "--is-shallow-repository").strip() == b"false",
        "Full source history required",
    )
    rows = []
    for record in git("ls-tree", "-rz", revision).split(b"\0"):
        if not record:
            continue
        metadata, name = record.split(b"\t", 1)
        mode, kind, blob = metadata.decode().split()
        require(kind == "blob", "Submodules are not distribution content")
        content = git("cat-file", "blob", blob)
        rows.append(
            {
                "path": name.decode(),
                "mode": mode,
                "blob": blob,
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    manifest = {
        "schema": "agent-protocol-source/v1",
        "repository": "gabned/agent-protocol",
        "repository_id": 1393711644,
        "revision": revision,
        "version": "1.5.0",
        "files": rows,
    }
    return validate_inventory(manifest, hashlib.sha256(canonical(manifest)).hexdigest())


def verify_files(root, manifest, *, expected_digest, observed_modes):
    """Verify bytes and independently observed Git/archive modes; no trust is granted."""
    validate_inventory(manifest, expected_digest)
    root = Path(root).resolve()
    require(
        set(observed_modes) == {row["path"] for row in manifest["files"]},
        "Incomplete or unexpected mode inventory",
    )
    for row in manifest["files"]:
        file = root / row["path"]
        require(not any(p.is_symlink() for p in (file, *file.parents)), "Symlink source refused")
        require(
            file.is_file() and file.resolve().is_relative_to(root), "Source path missing/escaped"
        )
        content = file.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
        require(
            blob == row["blob"] and hashlib.sha256(content).hexdigest() == row["sha256"],
            "Source bytes differ from accepted inventory",
        )
        require(observed_modes[row["path"]] == row["mode"], "Source mode differs")
    return {
        "result": "BYTES_VERIFIED",
        "revision": manifest["revision"],
        "files": len(manifest["files"]),
        "authority": "REQUIRES_AUTHENTICATED_RELEASE",
    }


def verify_installation(bundle, *, revision, distribution_root=ROOT, source_root=None):
    """Compare installed bytes/modes to an independently authenticated release archive.

    Enrollment selects the original release digest. No candidate-supplied hash
    grants authority. Archive mode validation works on Windows and POSIX alike.
    """
    exact(bundle, "archive_path archive_sha256 manifest manifest_digest", "enrolled source bundle")
    manifest = validate_inventory(bundle["manifest"], bundle["manifest_digest"])
    require(manifest["revision"] == sha(revision), "Installed source pin differs")
    archive = Path(bundle["archive_path"])
    require(
        hashlib.sha256(archive.read_bytes()).hexdigest() == bundle["archive_sha256"],
        "Release artifact differs from independently selected digest",
    )
    root = Path(distribution_root).resolve()
    src = Path(source_root).resolve() if source_root else Path(__file__).resolve().parents[1]
    expected = {row["path"]: row for row in manifest["files"]}
    with tarfile.open(archive, "r:gz") as source:
        entries = source.getmembers()
        require(
            entries and all(member.isfile() and "/" in member.name for member in entries),
            "Unsupported archive member",
        )
        names = [member.name.split("/", 1)[1] for member in entries]
        require(
            len(names) == len(set(names))
            and set(names) == set(expected) | {"SOURCE-MANIFEST.json"},
            "Incomplete or unexpected release archive inventory",
        )
        for member, name in zip(entries, names, strict=True):
            safe_path(member.name)
            data = source.extractfile(member).read()
            if name == "SOURCE-MANIFEST.json":
                require(json.loads(data) == manifest, "Embedded release inventory differs")
                continue
            row = expected[name]
            blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            require(
                member.mode == int(row["mode"][-3:], 8)
                and hashlib.sha256(data).hexdigest() == row["sha256"]
                and blob == row["blob"],
                "Artifact bytes/mode differ",
            )
            location = src / name[4:] if name.startswith("src/") else root / name
            require(
                not any(p.is_symlink() for p in (location, *location.parents)),
                "Installed symlink refused",
            )
            require(
                location.is_file() and location.read_bytes() == data,
                "Installed bytes differ from release",
            )
    return {
        "result": "BYTES_VERIFIED",
        "revision": revision,
        "manifest_digest": bundle["manifest_digest"],
        "archive_sha256": bundle["archive_sha256"],
        "files": len(expected),
    }
