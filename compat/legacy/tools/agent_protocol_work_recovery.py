"""Offline Work recovery and explicit adopter synchronization; never grants authority."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path


def sibling(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


source = sibling("agent_protocol_work_source")
ops = sibling("agent_protocol_v1_4_2_ops")
SCHEMA = "agent-work-recovery/v1"
WORK_FILES = (
    "tools/agent_protocol_v1_4_7.py",
    "tests/test_agent_protocol_v1_4_7.py",
    "tools/agent_protocol_work_source.py",
    "tools/agent_protocol_work_check.py",
    "tools/agent_protocol_work_collect.mjs",
    "tools/agent_protocol_work_recovery.py",
    "tests/test_agent_protocol_work_source.py",
    "tests/test_agent_protocol_work_check.py",
    "tests/test_agent_protocol_work_collect.mjs",
    "tests/test_agent_protocol_work_recovery.py",
)


def regular(root, relative):
    source.valid_path(relative)
    source.require(":" not in relative, "nonportable path")
    target = root / relative
    source.require(not any(p.is_symlink() for p in (target, *target.parents)), "symlink path")
    return target


def entries(names):
    source.require(
        isinstance(names, list) and 0 < len(names) <= source.MAX_ENTRIES,
        "explicit bounded file list required",
    )
    source.require(names == sorted(set(names)), "file list must be sorted and unique")
    folded = set()
    prefixes = {}
    for name in names:
        source.valid_path(name)
        source.require(":" not in name and name.casefold() not in folded, "nonportable alias")
        folded.add(name.casefold())
        parts = name.split("/")
        for index, part in enumerate(parts, 1):
            source.require(
                not re.search(r'[<>:"|?*\x00-\x1f]', part)
                and not part.endswith((".", " "))
                and not re.fullmatch(
                    r"(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?", part, re.I
                ),
                "nonportable path component",
            )
            prefix = "/".join(parts[:index])
            key = prefix.casefold()
            source.require(prefixes.get(key, prefix) == prefix, "case-aliased directory")
            prefixes[key] = prefix
    source.require(
        not any(
            "/".join(n.split("/")[:i]).casefold() in folded
            for n in names
            for i in range(1, len(n.split("/")))
        ),
        "file/directory collision",
    )
    return names


def recovery_export(root, names, destination):
    """Export caller-selected evidence only; freshness and authority are not inferred."""
    root = root.absolute()
    rows, payloads, total = [], [], 0
    for name in entries(names):
        path = regular(root, name)
        data = source.read_regular(path)
        total += len(data)
        source.require(total <= source.MAX_TOTAL, "recovery size limit")
        rows.append(
            {
                "path": name,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "mode": "100755" if path.stat().st_mode & stat.S_IXUSR else "100644",
            }
        )
        payloads.append(data)
    manifest = {
        "schema": SCHEMA,
        "files": rows,
        "authority": "NOT_GRANTED",
        "fresh_observations_required": True,
        "push_qualified": False,
    }
    manifest_bytes = ops.canonical(manifest)
    source.require(
        len(manifest_bytes) <= source.MAX_BLOB and total + len(manifest_bytes) <= source.MAX_TOTAL,
        "expanded size limit",
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", manifest_bytes)
        for index, data in enumerate(payloads):
            archive.writestr(f"objects/{index}", data)
    data = buffer.getvalue()
    source.require(len(data) <= source.MAX_TOTAL, "archive size limit")
    destination = destination.absolute()
    regular(destination.parent, destination.name)
    # Exclusive creation never overwrites a former durable checkpoint.
    with destination.open("xb") as stream:
        try:
            os.chmod(destination, 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            destination.unlink()
            raise
    return {
        "archive_sha256": hashlib.sha256(data).hexdigest(),
        "files": len(rows),
        "push_qualified": False,
        "durable_host_save": "REQUIRED",
    }


def recovery_verify(archive_path, expected_sha256):
    """An independently retained digest detects replacement; it is not authentication."""
    source.require(
        isinstance(expected_sha256, str) and re.fullmatch(r"[0-9a-f]{64}", expected_sha256),
        "archive digest required",
    )
    regular(archive_path.absolute().parent, archive_path.name)
    # Bound the compressed input separately; individual payload limits are checked below.
    source.require(archive_path.stat().st_size <= source.MAX_TOTAL, "archive size limit")
    with archive_path.open("rb") as stream:
        raw = stream.read(source.MAX_TOTAL + 1)
    source.require(
        len(raw) <= source.MAX_TOTAL and hashlib.sha256(raw).hexdigest() == expected_sha256,
        "archive digest mismatch",
    )
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        info = archive.infolist()
        source.require(
            0 < len(info) <= source.MAX_ENTRIES + 1
            and len({i.filename for i in info}) == len(info),
            "duplicate/archive entry limit",
        )
        source.require(
            all(
                not i.is_dir() and not i.flag_bits & 1 and not stat.S_ISLNK(i.external_attr >> 16)
                for i in info
            ),
            "encrypted, directory or linked entry",
        )
        source.require(
            all(i.file_size <= source.MAX_BLOB for i in info)
            and sum(i.file_size for i in info) <= source.MAX_TOTAL,
            "expanded size limit",
        )
        manifest = json.loads(archive.read("manifest.json"), object_pairs_hook=source.unique_object)
        ops.obj(
            manifest,
            "schema files authority fresh_observations_required push_qualified",
            "recovery manifest",
        )
        source.require(
            manifest["schema"] == SCHEMA
            and manifest["authority"] == "NOT_GRANTED"
            and manifest["fresh_observations_required"] is True
            and manifest["push_qualified"] is False,
            "recovery cannot grant authority",
        )
        rows = manifest["files"]
        entries([r["path"] for r in rows])
        source.require(
            {i.filename for i in info}
            == {"manifest.json"} | {f"objects/{i}" for i in range(len(rows))},
            "unexpected archive members",
        )
        data = []
        for index, row in enumerate(rows):
            ops.obj(row, "path size sha256 mode", "recovery file")
            source.require(row["mode"] in {"100644", "100755"}, "invalid recovery mode")
            payload = archive.read(f"objects/{index}")
            source.require(
                type(row["size"]) is int
                and row["size"] == len(payload)
                and row["sha256"] == hashlib.sha256(payload).hexdigest(),
                "recovery file digest/size mismatch",
            )
            data.append(payload)
    return manifest, data


def recovery_restore(archive_path, expected_sha256, destination):
    manifest, data = recovery_verify(archive_path, expected_sha256)
    destination = destination.absolute()
    regular(destination.parent, destination.name)
    # Validate everything before creating anything; exclusively own a fresh directory.
    destination.mkdir(mode=0o700)
    try:
        for row, payload in zip(manifest["files"], data, strict=True):
            path = regular(destination, row["path"])
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(payload)
            path.chmod(0o700 if row["mode"] == "100755" else 0o600)
    except BaseException:
        shutil.rmtree(destination)
        raise
    return {
        "restored_files": len(data),
        "authority": "NOT_GRANTED",
        "fresh_observations_required": True,
        "push_qualified": False,
    }


def git(root, *args):
    result = subprocess.run(
        [
            "git",
            "--no-replace-objects",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "protocol.allow=never",
            "-C",
            str(root),
            *args,
        ],
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_ALLOW_PROTOCOL": "",
            "GIT_OPTIONAL_LOCKS": "0",
        },
    )
    return result.stdout


def replace_assignment(text, name, value):
    matches = [
        node
        for node in ast.parse(text).body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)
    ]
    source.require(
        len(matches) == 1 and len(matches[0].targets) == 1,
        "one literal vendor assignment required: " + name,
    )
    node = matches[0]
    ast.literal_eval(node.value)
    lines = text.splitlines(keepends=True)
    lines[node.lineno - 1 : node.end_lineno] = [name + " = " + repr(value) + "\n"]
    return "".join(lines)


def accepted_routing(canonical, commit):
    """Read current guidance only from the selected immutable canonical source."""
    def committed(path):
        data = source.read_regular(regular(canonical, path))
        entry = git(canonical, "ls-tree", commit, "--", path).decode().split()
        source.require(len(entry) == 4 and entry[:2] == ["100644", "blob"]
                       and entry[2] == ops.blob(data), "canonical routing bytes/mode drift")
        return data

    agents = committed("AGENTS.md").decode()
    versions = re.findall(r"(?m)^AGENT_DEVELOPMENT_PROTOCOL: (1[.]4[.][789])$", agents)
    source.require(len(versions) == 1, "one supported accepted Protocol version required")
    version = versions[0]
    guide = f"docs/agent-development-v{version}.md"
    manifest_path = f".github/agent-protocol/documents-v{version}.json"
    source.require(guide in agents and manifest_path in agents, "accepted instruction routing")
    manifest = json.loads(committed(manifest_path))
    source.require(manifest.get("protocol_version") == version, "accepted routing version")
    execution = sibling("agent_protocol_v1_4_7")
    selected = execution.select_documents(
        canonical, manifest, ops.digest(manifest), workstream="PROTOCOL", phase="IMPLEMENT")
    for row in manifest["documents"]:
        committed(row["path"])
    source.require({"AGENTS.md", guide} <= {r["path"] for r in selected["documents"]}
                   and all(any(r["path"] == path and r["role"] == "ALWAYS"
                               for r in manifest["documents"]) for path in ("AGENTS.md", guide)),
                   "accepted current contract must always route")
    return version, guide


def adoption_guidance(repository, version="1.4.8"):
    """Stable routing; adopted identities belong to the verified pins, not prose."""
    pin_path = "scripts/agent/protocol-v1-2.py" if repository == "brickms/brickms" \
        else "tests/agent_protocol_v1_4_2_vendor_test.py"
    return (
        f"## Current execution — Protocol {version}\n\n"
        f"AGENT_DEVELOPMENT_PROTOCOL: {version}\n\n"
        f"Resolve `WORK_ADAPTER_PIN` in `{pin_path}` and the operational manifest\n"
        "`.github/agent-protocol/vendor-v1.4.2.json` to the same immutable `source_commit`.\n"
        "Verify the pinned bytes; read Core `AGENTS.md` and its document manifest at\n"
        "that commit. Follow that current contract and the accepted local policy.\n"
        "Preserve existing owners and checkpoints; adoption grants no PRODUCT\n"
        "continuation or production authority. Keep actual state and evidence in\n"
        "the existing workstream ledger.\n"
    )


def adoption_plan(canonical, target, commit, repository, *, work=None):
    source.require(
        repository in ops.PROFILES and repository not in {"gabned/provelume", "gabned/nexus"},
        "executable adopter required",
    )
    if work is None:
        source.require(
            git(target, "config", "--get", "remote.origin.url").decode().strip()
            in {
                f"https://github.com/{repository}",
                f"https://github.com/{repository}.git",
                f"git@github.com:{repository}.git",
            },
            "target repository mismatch",
        )
    else:
        snapshot, baseline, anchor = work
        source.require(target.resolve() != baseline.resolve(), "distinct Work candidate required")
        source.verify_live_anchor(snapshot, anchor)
        source.candidate_delta(snapshot, baseline, target, repository, snapshot["commit_sha"])
    manifest = ops.manifest(canonical, commit)
    version, _ = accepted_routing(canonical, commit)
    work = []
    for path in WORK_FILES:
        data = source.read_regular(regular(canonical, path))
        observed = git(canonical, "ls-tree", commit, "--", path).decode().split()
        source.require(
            len(observed) == 4
            and observed[:2] == ["100644", "blob"]
            and observed[2] == ops.blob(data),
            "canonical Work bytes/mode drift",
        )
        work.append(
            {
                "path": path,
                "mode": "100644",
                "git_blob": ops.blob(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    pin = {"source_repository": "gabned/provelume", "source_commit": commit, "files": work}
    planned = {p: source.read_regular(regular(canonical, p)) for p in ops.VENDOR_FILES}
    source.require(
        all(ops.blob(planned[row["path"]]) == row["git_blob"] for row in manifest["files"]),
        "canonical source changed during synchronization",
    )
    planned.update(ops.provenance_files(manifest))
    guard = "tests/agent_protocol_v1_4_2_vendor_test.py"
    text = source.read_regular(regular(target, guard)).decode()
    text = replace_assignment(text, "EXPECTED_MANIFEST", manifest)
    if repository == "brickms/brickms":
        old_counts = [f'    assert len(local.WORK_ADAPTER_PIN["files"]) == {n}'
                      for n in (6, 8, 10)]
        new_count = old_counts[-1]
        source.require(
            sum(text.splitlines().count(line) for line in old_counts) == 1,
            "one exact BrickMS dependency inventory assertion required",
        )
        for old_count in old_counts:
            text = text.replace(old_count, new_count)
        adapter_path = "scripts/agent/protocol-v1-2.py"
        adapter_text = source.read_regular(regular(target, adapter_path)).decode()
        planned[adapter_path] = replace_assignment(adapter_text, "WORK_ADAPTER_PIN", pin).encode()
    else:
        text = replace_assignment(text, "WORK_ADAPTER_PIN", pin)
    planned[guard] = text.encode()
    runbook = (
        "docs/agent-development-v1.4.2.md"
        if repository == "gabned/provelume.com"
        else "docs/runbooks/agent-development-v1.4.2.md"
    )
    ownership = (
        "This authorized PROTOCOL adoption retains PR-local ownership and uses\n"
        if repository == "gabned/provelume.com"
        else "This authorized PROTOCOL adoption retains the valid product checkpoint and uses\n"
    )
    legacy_block = (
        "## Current execution — Protocol 1.4.7\n\nAGENT_DEVELOPMENT_PROTOCOL: 1.4.7\n\n"
        f"Accepted Core: `{commit}`. This current section supersedes earlier Work\n"
        "startup/pin descriptions; historical receipts and their identities stay unchanged.\n"
        "Use the canonical evidence collector for immutable Git objects and terminal CI\n"
        "history; retain original timestamps and refresh every live inventory and gate.\n"
        "Ordinary preflight v2 never reads rulesets; trusted repository policy supplies\n"
        "the agent gates, and normal GitHub merge retains remote enforcement.\n"
        "The ten Work dependency files, operational manifest and generated provenance\n"
        "are synchronized from the same accepted commit. Operational helper bytes/modes\n"
        "are verified independently; engine 1.4.2, lifecycle 1.2 and schema 2 remain.\n\n"
        f"Follow the [canonical evidence guide](https://github.com/gabned/provelume/blob/{commit}/"
        "docs/agent-development-v1.4.7.md). Persist each observation before continuing;\n"
        "save and independently verify the explicit evidence archive outside the source tree.\n"
        "Restoration recovers historical bytes only: select actual user authority independently,\n"
        "then collect fresh default/policy/review/CI evidence and run unchanged native gates.\n"
        "A complete verified native Git checkout/bundle remains valid when connector binary\n"
        "transport is unavailable. Missing bytes are never excluded or inferred.\n\n"
        f"{ownership}"
        "campaign issue/owner-PR ownership. Full local checks, exact scope/effect, CI, review,\n"
        "merge and post-merge verification remain required. No PRODUCT continuation,\n"
        "production effect or Level C authority follows from recovery or adoption.\n"
    )
    block = legacy_block if version == "1.4.7" else adoption_guidance(repository, version)
    for path in ("AGENTS.md", runbook):
        text = source.read_regular(regular(target, path)).decode()
        current_versions = re.findall(r"(?m)^## Current execution — Protocol (\S+)\r?$", text)
        source.require(len(current_versions) <= 1, "duplicate current recovery section")
        if current_versions:
            previous_version = current_versions[0]
            source.require(previous_version == version
                           or (previous_version, version) in {("1.4.7", "1.4.8"),
                                                            ("1.4.8", "1.4.9")},
                           "unsupported adoption guidance transition")
            previous_marker = f"## Current execution — Protocol {previous_version}"
            source.require(text.count(previous_marker) == 1, "duplicate current recovery section")
            before, current = text.split(previous_marker)
            expected = block
            if previous_version == "1.4.8":
                expected = adoption_guidance(repository, previous_version)
            if previous_version == "1.4.7":
                previous = re.search(r"Accepted Core: `([0-9a-f]{40})`", current)
                source.require(previous is not None, "missing previous accepted Core identity")
                expected = legacy_block.replace(commit, previous[1])
            boundary = re.search(r"(?m)^## ", current)
            generated = previous_marker + (current[:boundary.start()] if boundary else current)
            separator = generated[len(expected):]
            source.require(
                generated.startswith(expected)
                and (not separator or (boundary is not None and not separator.strip("\n"))),
                "edited current recovery section requires explicit reconciliation",
            )
            tail = separator + current[boundary.start():] if boundary else ""
            planned[path] = (before + block + tail).encode()
        else:
            separator = "\n" if text.endswith("\n") else "\n\n"
            planned[path] = (text + separator + block).encode()
    return manifest, planned


def sync_adopter(canonical, target, commit, repository, *, check=False, work=None):
    """One planned transaction; rollback on error, never publishes a ref or modifies history."""
    manifest, planned = adoption_plan(canonical, target, commit, repository, work=work)
    originals = {p: source.read_regular(regular(target, p))
                 if regular(target, p).exists() else None for p in planned}
    modes = {p: stat.S_IMODE(regular(target, p).stat().st_mode)
             if regular(target, p).exists() else 0o644 for p in planned}
    wanted = {
        p: ops.VENDOR_FILES.get(p, "100755" if modes[p] & stat.S_IXUSR else "100644")
        for p in planned
    }
    changed = [
        p
        for p in planned
        if planned[p] != originals[p]
        or (os.name != "nt" and bool(modes[p] & stat.S_IXUSR) != (wanted[p] == "100755"))
    ]
    if check:
        return {
            "changed_paths": changed,
            "source_commit": manifest["source_commit"],
            "check_only": True,
            "push_qualified": False,
        }
    applied = []
    with tempfile.TemporaryDirectory(prefix=".agent-adoption-", dir=target) as temp:
        try:
            for index, path in enumerate(changed):
                dest = regular(target, path)
                actual = source.read_regular(dest) if dest.exists() else None
                source.require(actual == originals[path], "target changed")
                # Stage on the target filesystem for atomic per-file replacement.
                fd, name = tempfile.mkstemp(prefix=".agent-adoption-", dir=dest.parent)
                try:
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(planned[path])
                    os.chmod(
                        name,
                        (modes[path] | stat.S_IXUSR)
                        if wanted[path] == "100755"
                        else modes[path] & ~stat.S_IXUSR,
                    )
                    os.replace(name, dest)
                    applied.append(path)
                finally:
                    Path(name).unlink(missing_ok=True)
                if originals[path] is not None:
                    Path(temp, str(index)).write_bytes(originals[path])
        except BaseException:
            for path in reversed(applied):
                dest = regular(target, path)
                if originals[path] is None:
                    dest.unlink()
                    continue
                fd, name = tempfile.mkstemp(prefix=".agent-restore-", dir=dest.parent)
                try:
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(originals[path])
                    os.chmod(name, modes[path])
                    os.replace(name, dest)
                finally:
                    Path(name).unlink(missing_ok=True)
            raise
    return {
        "changed_paths": changed,
        "source_commit": commit,
        "check_only": False,
        "push_qualified": False,
        "full_local_checks": "REQUIRED",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("--root", type=Path, required=True)
    export.add_argument("--files", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    for name in ("verify", "restore"):
        item = commands.add_parser(name)
        item.add_argument("--archive", type=Path, required=True)
        item.add_argument("--sha256", required=True)
        if name == "restore":
            item.add_argument("--destination", type=Path, required=True)
    sync = commands.add_parser("sync-adopter")
    sync.add_argument("--source", type=Path, required=True)
    sync.add_argument("--target", type=Path, required=True)
    sync.add_argument("--commit", required=True)
    sync.add_argument("--repository", required=True)
    sync.add_argument("--check", action="store_true")
    sync.add_argument("--work-snapshot", type=Path)
    sync.add_argument("--work-baseline", type=Path)
    sync.add_argument("--work-anchor", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "export":
            result = recovery_export(args.root, source.read_json(args.files), args.output)
        elif args.command == "restore":
            result = recovery_restore(args.archive, args.sha256, args.destination)
        elif args.command == "verify":
            manifest, _ = recovery_verify(args.archive, args.sha256)
            result = {
                "files": len(manifest["files"]),
                "integrity": "VERIFIED",
                "authority": "NOT_GRANTED",
                "push_qualified": False,
            }
        else:
            work = None
            if any((args.work_snapshot, args.work_baseline, args.work_anchor)):
                source.require(
                    all((args.work_snapshot, args.work_baseline, args.work_anchor)),
                    "complete Work source/baseline/anchor required",
                )
                work = (
                    source.read_json(args.work_snapshot),
                    args.work_baseline,
                    source.read_json(args.work_anchor),
                )
            result = sync_adopter(
                args.source, args.target, args.commit, args.repository, check=args.check, work=work
            )
        print(json.dumps(result, indent=2))
        return 0
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        zipfile.BadZipFile,
        subprocess.CalledProcessError,
    ) as error:
        print(json.dumps({"result": "BLOCKED", "reason": str(error), "push_qualified": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
