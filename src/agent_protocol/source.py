"""Load the preserved validators without a product checkout or import path mutation."""

from __future__ import annotations

import base64
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
    require(manifest["version"] == "1.5.2", "Unsupported current distribution identity")
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
        "version": "1.5.2",
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


def verify_installation(
    bundle, *, revision, distribution_root=ROOT, source_root=None, authenticate_origin=None
):
    """Compare installed bytes/modes to an independently authenticated release archive.

    Enrollment selects the original release digest. No candidate-supplied hash
    grants authority. Archive mode validation works on Windows and POSIX alike.
    """
    require(isinstance(bundle, dict), "Source bundle must be an object")
    if bundle.get("schema") == "agent-protocol-source-bundle/v2":
        exact(
            bundle,
            "schema kind archive_path archive_sha256 manifest manifest_digest provenance",
            "Git source bundle",
        )
        require(bundle["kind"] == "CANONICAL_GIT", "Unknown source acquisition kind")
        checked = verify_git_provenance(
            bundle["provenance"], bundle["manifest"], authenticate_origin=authenticate_origin
        )
        legacy_bundle = {
            key: bundle[key]
            for key in ("archive_path", "archive_sha256", "manifest", "manifest_digest")
        }
        result = verify_installation(
            legacy_bundle,
            revision=revision,
            distribution_root=distribution_root,
            source_root=source_root,
        )
        return {
            **result,
            "kind": "CANONICAL_GIT",
            "tree": checked["tree"],
            "origin_digest": checked["origin_digest"],
        }
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


def _git_tree(manifest):
    """Reconstruct the complete Git root tree without Git or a network."""
    root = {}
    for row in manifest["files"]:
        parts = row["path"].split("/")
        node = root
        for part in parts[:-1]:
            require(part not in node or isinstance(node[part], dict), "File/directory collision")
            node = node.setdefault(part, {})
        require(parts[-1] not in node, "File/directory collision")
        node[parts[-1]] = (row["mode"], row["blob"])

    def tree(node):
        records = []
        for name, value in node.items():
            directory = isinstance(value, dict)
            mode, blob = ("40000", tree(value)) if directory else value
            key = name.encode() + (b"/" if directory else b"")
            records.append(
                (key, mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(blob))
            )
        data = b"".join(record for _, record in sorted(records))
        return hashlib.sha1(b"tree " + str(len(data)).encode() + b"\0" + data).hexdigest()

    return tree(root)


def validate_git_origin(origin):
    exact(
        origin, "schema repository repository_id revision tree base head acceptance", "Git origin"
    )
    require(origin["schema"] == "agent-protocol-git-origin/v1", "Unknown Git origin")
    require(
        origin["repository"] == "gabned/agent-protocol" and origin["repository_id"] == 1393711644,
        "Canonical Git repository identity changed",
    )
    for field in ("revision", "tree", "base", "head"):
        sha(origin[field])
    require(len({origin[k] for k in ("revision", "base", "head")}) == 3, "Ambiguous Git ancestry")
    acceptance = origin["acceptance"]
    exact(acceptance, "pull_request receipt_url receipt_sha256", "source acceptance locator")
    number = acceptance["pull_request"]
    require(type(number) is int and number > 0, "Exact acceptance PR required")
    require(
        isinstance(acceptance["receipt_url"], str)
        and re.fullmatch(
            rf"https://github.com/gabned/agent-protocol/pull/{number}#issuecomment-[1-9][0-9]*",
            acceptance["receipt_url"],
        ),
        "Canonical independent acceptance receipt required",
    )
    require(
        isinstance(acceptance["receipt_sha256"], str)
        and re.fullmatch(r"[0-9a-f]{64}", acceptance["receipt_sha256"]),
        "Original acceptance receipt digest required",
    )
    return origin


def verify_git_provenance(provenance, manifest, *, authenticate_origin):
    """Integrity bound to a host capability, never to a candidate's JSON assertion.

    The callback takes no candidate input. Its accepted origin must already have
    been independently authenticated under predecessor/local change control.
    Offline hosts may restore that authority from their accepted enrollment/pin.
    """
    exact(provenance, "schema origin commits", "Git provenance")
    require(provenance["schema"] == "agent-protocol-git-provenance/v1", "Unknown Git proof")
    require(callable(authenticate_origin), "Independent source authentication capability required")
    origin = validate_git_origin(provenance["origin"])
    require(origin == authenticate_origin(), "Git origin differs from independent host authority")
    validate_inventory(manifest, hashlib.sha256(canonical(manifest)).hexdigest())
    require(manifest["revision"] == origin["revision"], "Git proof/source revision mismatch")
    require(_git_tree(manifest) == origin["tree"], "Incomplete or altered canonical Git tree")
    commits = provenance["commits"]
    require(
        isinstance(commits, list) and 2 <= len(commits) <= 10000, "Complete Git ancestry required"
    )
    previous, seen, head_tree = origin["base"], set(), None
    for index, row in enumerate(commits):
        exact(row, "revision object", "original Git commit")
        revision = sha(row["revision"])
        require(revision not in seen and revision != origin["base"], "Duplicate Git ancestry")
        seen.add(revision)
        require(
            isinstance(row["object"], str) and len(row["object"]) <= 2**20, "Invalid Git object"
        )
        try:
            data = base64.b64decode(row["object"], validate=True)
        except (ValueError, TypeError) as error:
            raise ValueError("Invalid original Git commit encoding") from error
        require(
            hashlib.sha1(b"commit " + str(len(data)).encode() + b"\0" + data).hexdigest()
            == revision,
            "Original Git commit identity differs",
        )
        headers, separator, _message = data.partition(b"\n\n")
        require(separator, "Incomplete original Git commit")
        lines = headers.split(b"\n")
        trees = [line[5:].decode("ascii") for line in lines if line.startswith(b"tree ")]
        parents = [line[7:].decode("ascii") for line in lines if line.startswith(b"parent ")]
        require(len(trees) == 1, "Ambiguous commit tree")
        sha(trees[0])
        for parent in parents:
            sha(parent)
        final = index == len(commits) - 1
        if final:
            require(
                revision == origin["revision"]
                and previous == origin["head"]
                and parents == [origin["base"], origin["head"]]
                and trees[0] == head_tree == origin["tree"],
                "Accepted normal merge identity/parents/tree differ",
            )
        else:
            require(parents == [previous], "Source branch must retain its complete linear ancestry")
            previous, head_tree = revision, trees[0]
    return {
        "result": "BYTES_VERIFIED",
        "kind": "CANONICAL_GIT",
        "revision": origin["revision"],
        "tree": origin["tree"],
        "origin_digest": hashlib.sha256(canonical(origin)).hexdigest(),
        "authority": "REQUIRES_INDEPENDENTLY_AUTHENTICATED_HOST_CONTEXT",
    }


def git_provenance(repository, origin, *, authenticate_origin):
    """Observe original committed objects only; do not execute acquired source."""
    validate_git_origin(origin)
    require(callable(authenticate_origin), "Independent source authentication capability required")
    require(origin == authenticate_origin(), "Git origin differs from independent host authority")
    command = ["git", "--no-replace-objects", "-C", str(repository)]

    def git(*args):
        return subprocess.check_output([*command, *args])

    require(
        git("rev-parse", "--is-shallow-repository").strip() == b"false",
        "Full source history required",
    )
    grafts = Path(
        git("rev-parse", "--path-format=absolute", "--git-path", "info/grafts").decode().strip()
    )
    require(
        not grafts.exists() and not git("for-each-ref", "refs/replace/").strip(),
        "Replaced source history refused",
    )
    manifest = git_inventory(repository, origin["revision"])
    registry = json.loads(
        git("show", origin["revision"] + ":.github/agent-protocol/bootstrap.json")
    )
    require(
        {row["path"]: row["mode"] for row in manifest["files"]} == registry["modes"]
        and set(registry["paths"]) == set(registry["modes"]),
        "Complete registered canonical inventory required",
    )
    revisions = (
        git("rev-list", "--reverse", "--topo-order", origin["revision"], "^" + origin["base"])
        .decode()
        .splitlines()
    )
    proof = {
        "schema": "agent-protocol-git-provenance/v1",
        "origin": origin,
        "commits": [
            {
                "revision": revision,
                "object": base64.b64encode(git("cat-file", "commit", revision)).decode(),
            }
            for revision in revisions
        ],
    }
    verify_git_provenance(proof, manifest, authenticate_origin=authenticate_origin)
    return proof, manifest


def acquire_git_source(repository, directory, origin, *, authenticate_origin):
    """Build a deterministic cache from authenticated immutable Git objects.

    The authorized CLI/Work adapter selects authenticate_origin from independently
    accepted local change control. This API does not enroll an origin, update a
    consumer pin, publish artifacts or complete adoption.
    """
    proof, manifest = git_provenance(repository, origin, authenticate_origin=authenticate_origin)
    # Load only this installed, accepted packager, never one from acquired source.
    spec = importlib.util.spec_from_file_location(
        "agent_protocol_packager", ROOT / "tools/package.py"
    )
    packager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(packager)
    files = packager.committed_files(repository, origin["revision"])
    require(
        packager.source_manifest(files, origin["revision"]) == manifest,
        "Independent inventories differ",
    )
    artifacts = {
        "source.tar.gz": packager.source_bytes(files, origin["revision"]),
        packager.NAME: packager.wheel_bytes(files),
        "source-manifest.json": (json.dumps(manifest, indent=2) + "\n").encode(),
        "git-provenance.json": (json.dumps(proof, indent=2) + "\n").encode(),
    }
    artifacts["SHA256SUMS"] = "".join(
        hashlib.sha256(data).hexdigest() + "  " + name + "\n"
        for name, data in sorted(artifacts.items())
    ).encode()
    directory = Path(directory).absolute()
    require(
        not any(p.is_symlink() for p in (directory, *directory.parents)), "Cache symlink refused"
    )
    if directory.exists():
        require(
            directory.is_dir() and {p.name for p in directory.iterdir()} == set(artifacts),
            "Incomplete or unmanaged Git cache preserved",
        )
        for name, data in artifacts.items():
            path = directory / name
            require(
                path.is_file() and not path.is_symlink() and path.read_bytes() == data,
                "Altered Git cache preserved",
            )
    else:
        # Exclusive creation. An uncertain/partial write is preserved for diagnosis.
        directory.mkdir(parents=True, exist_ok=False)
        for name, data in artifacts.items():
            with (directory / name).open("xb") as stream:
                stream.write(data)
    return {
        "schema": "agent-protocol-source-bundle/v2",
        "kind": "CANONICAL_GIT",
        "archive_path": str(directory / "source.tar.gz"),
        "archive_sha256": hashlib.sha256(artifacts["source.tar.gz"]).hexdigest(),
        "manifest": manifest,
        "manifest_digest": hashlib.sha256(canonical(manifest)).hexdigest(),
        "provenance": proof,
    }
