#!/usr/bin/env python3
"""Run an explicitly selected canonical local check with durable raw evidence.

The caller owns authorization and runtime preparation. No GitHub operation,
CI substitution, credential acquisition or application-test authorization is
provided here. FULL is for an adopted/authorized workflow, never the active stop.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

import agent_protocol_work_source as source


def run_check(
    snapshot_path: Path,
    baseline: Path,
    candidate: Path,
    output: Path,
    *,
    workstream: str,
    suite: str,
    timeout: int = 900,
    canonical_snapshot: Path | None = None,
    canonical_anchor: Path | None = None,
    adapter_root: Path | None = None,
) -> tuple[dict, int]:
    source.require(os.name == "posix", "canonical Work check requires a POSIX execution host")
    source.require(workstream in {"PROTOCOL", "PRODUCT", "CHECKPOINT_ONLY"},
                   "explicit supported workstream required")
    source.require(suite in {"PROTOCOL_ONLY", "FULL"}, "explicit canonical suite required")
    source.require(workstream != "CHECKPOINT_ONLY" or suite == "FULL",
                   "checkpoint-only publication requires the full canonical check")
    source.require(type(timeout) is int and 1 <= timeout <= 3600, "bounded check timeout required")
    started_clock = datetime.now(UTC)
    canonical_source = None
    source.require((canonical_snapshot is None) == (canonical_anchor is None),
                   "canonical vendor snapshot and live anchor must be supplied together")
    if canonical_snapshot is not None:
        source.require(workstream == "PROTOCOL", "canonical vendor adoption requires PROTOCOL")
        canonical_source = source.canonical_input(canonical_snapshot, canonical_anchor,
                                                  now=started_clock)
    baseline, candidate = baseline.resolve(), candidate.resolve()
    source.require(baseline != candidate, "baseline and candidate must be separate")
    source.require(
        not output.exists() and not output.is_symlink(),
        "output already exists; preserve earlier evidence",
    )
    source.require(
        not output.resolve().is_relative_to(candidate)
        and not output.resolve().is_relative_to(baseline),
        "evidence must be outside source directories",
    )
    snapshot = source.read_json(snapshot_path)
    delta = source.candidate_delta(
        snapshot, baseline, candidate, snapshot["repository"], snapshot["commit_sha"]
    )
    source.require(
        snapshot["repository"] == "brickms/brickms",
        "canonical check profile not adopted for this repository",
    )
    if workstream == "CHECKPOINT_ONLY":
        paths = {entry["path"] for entry in delta["changes"]}
        source.require("AGENT_STATUS.md" in paths
                       and paths <= {"AGENT_STATUS.md", "CHANGELOG.md"},
                       "checkpoint-only delta must contain only checkpoint and optional changelog")
        # The adopted local wrapper still verifies the transition, append-only
        # changelog and baseline scope. This precheck cannot authorize them.
    command = [
        "bash",
        "tools/agent-check",
        "--work-source",
        str(snapshot_path.resolve()),
        "--work-baseline",
        str(baseline),
        "--workstream-class",
        workstream,
    ]
    if adapter_root is not None:
        source.require(adapter_root.is_dir(), "pinned Work adapter directory unavailable")
        source.require(not adapter_root.resolve().is_relative_to(candidate)
                       and not adapter_root.resolve().is_relative_to(baseline),
                       "external Work adapter must remain outside source directories")
        command += ["--work-tools", str(adapter_root.resolve())]
    if canonical_snapshot is not None:
        command += ["--work-canonical-source", str(canonical_snapshot.resolve()),
                    "--work-canonical-anchor", str(canonical_anchor.resolve())]
    command.append("--protocol-only" if suite == "PROTOCOL_ONLY" else "--full")
    output.mkdir(mode=0o700, parents=False)
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "COMPOSER_HOME": str(output / "composer-home"),
    }
    started = started_clock.isoformat()
    timed_out = False
    launch_error = None
    exit_code = None
    with (output / "stdout.log").open("xb") as stdout, (output / "stderr.log").open("xb") as stderr:
        try:
            process = subprocess.Popen(
                command,
                cwd=candidate,
                env=environment,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
            try:
                exit_code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                # Stop the private check process group, retaining the real code.
                import signal

                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    exit_code = process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    with suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    exit_code = process.wait()
        except OSError as exc:
            launch_error = str(exc)
    source_error = None
    after = None
    try:
        after = source.tree_identity(source.inventory(candidate), verify=True)
        source.verify_source(snapshot, baseline, snapshot["repository"], snapshot["commit_sha"])
        if canonical_source is not None:
            # Replay freshness at the actual check start; do not manufacture a
            # new observation after a long process. Exact input bytes must stay.
            source.require(source.canonical_input(canonical_snapshot, canonical_anchor,
                                                  now=started_clock) == canonical_source,
                           "canonical check input changed during execution")
    except (source.EvidenceError, OSError) as exc:
        source_error = str(exc)
    unchanged = source_error is None and after == delta["candidate_tree_sha"]
    result = {
        "schema": "agent-work-check/v1",
        "repository": snapshot["repository"],
        "base_commit_sha": snapshot["commit_sha"],
        "candidate_tree_sha": delta["candidate_tree_sha"],
        "canonical_source": canonical_source,
        "candidate_tree_after": after,
        "source_unchanged": unchanged,
        "suite": suite,
        "command": command,
        "command_digest": source.digest(command),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "launch_error": launch_error,
        "source_error": source_error,
        "started_at": started,
        "completed_at": datetime.now(UTC).isoformat(),
        "push_qualified": False,
    }
    for stream in ("stdout", "stderr"):
        result[stream + "_sha256"] = hashlib.sha256(
            (output / (stream + ".log")).read_bytes()
        ).hexdigest()
    code = 0 if exit_code == 0 and unchanged and not timed_out and launch_error is None else 2
    result["adapter_exit_code"] = code
    (output / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result, code


WINDOWS_CI_TIMEOUT = 540
WINDOWS_CI_SHARDS = 4


def windows_identity(root: Path, expected: dict) -> dict:
    """Bind CI records to the actual unchanged checkout, never a supplied tree."""
    def git(*args):
        return subprocess.check_output(
            ["git", "-C", str(root), *args], text=True,
            env={**os.environ, "GIT_NO_REPLACE_OBJECTS": "1"},
        ).strip()
    source.require(Path(git("rev-parse", "--show-toplevel")).resolve() == root.resolve(),
                   "CI root mismatch")
    source.require(not git("status", "--porcelain", "--untracked-files=no"),
                   "CI source changed")
    commit, tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")
    source.require(commit == expected["commit"], "CI commit mismatch")
    if "tree" in expected:
        source.require(tree == expected["tree"], "CI tree mismatch")
    source.require(expected["event"] in {"pull_request", "push"}, "unsupported CI event")
    source.require(all(type(expected[key]) is str and expected[key].isdigit()
                       and int(expected[key]) > 0 for key in ("run_id", "run_attempt")),
                   "CI run identity missing")
    return {**expected, "tree": tree, "platform": sys.platform,
            "python": platform.python_version()}


class _WindowsRecorder:
    """Observe pytest's full collection, selection and real phase reports."""

    def __init__(self, identity, mode, shard):
        self.identity, self.mode, self.shard = identity, mode, shard
        self.inventory, self.selected, self.outcomes, self.errors = [], [], {}, []
        self.cases, self._ids = [], {}

    def pytest_collection_modifyitems(self, items):
        for item in items:
            callspec = getattr(item, "callspec", None)
            descriptor = {"parent": item.parent.nodeid,
                          "originalname": getattr(item, "originalname", None) or item.name,
                          "indices": sorted([name, index] for name, index in
                                            (callspec.indices.items() if callspec else []))}
            identity = _windows_case_id(descriptor)
            if identity in self.inventory or item.nodeid in self._ids:
                self.errors.append("duplicate pytest case or raw node identity")
            self.inventory.append(identity)
            self.cases.append({"id": identity, "descriptor": descriptor,
                               "raw_nodeid": item.nodeid})
            self._ids[item.nodeid] = identity

    def pytest_collection_finish(self, session):
        for item in session.items:
            identity = self._ids.get(item.nodeid)
            if identity is None:
                self.errors.append("selected pytest node missing from collection")
            else:
                self.selected.append(identity)

    def pytest_runtest_logreport(self, report):
        identity = self._ids.get(report.nodeid)
        if identity is None:
            self.errors.append("pytest phase missing from raw node map")
            return
        phases = self.outcomes.setdefault(identity, {})
        if (identity not in self.selected or report.when in phases
                or report.when not in {"setup", "call", "teardown"}):
            self.errors.append("unexpected or duplicate pytest phase")
        phases[report.when] = report.outcome

    def record(self, exit_code):
        return {"schema": "agent-windows-ci-pytest/v2", "identity": self.identity,
                "mode": self.mode, "shard": self.shard, "inventory": self.inventory,
                "cases": self.cases, "selected": self.selected, "outcomes": self.outcomes,
                "exit_code": int(exit_code), "errors": self.errors}


def _windows_case_id(descriptor):
    """Identify the source-bound pytest case, not its possibly volatile display label."""
    source.require(isinstance(descriptor, dict)
                   and set(descriptor) == {"parent", "originalname", "indices"}
                   and all(type(descriptor[key]) is str and descriptor[key]
                           for key in ("parent", "originalname")), "invalid CI case descriptor")
    indices = descriptor["indices"]
    source.require(isinstance(indices, list)
                   and all(isinstance(pair, list) and len(pair) == 2
                           and type(pair[0]) is str and pair[0]
                           and type(pair[1]) is int and pair[1] >= 0 for pair in indices),
                   "invalid CI parameter indices")
    names = [pair[0] for pair in indices]
    source.require(names == sorted(set(names)), "duplicate or unordered CI parameter names")
    return source.digest(descriptor)


def _windows_case_catalog(value, inventory):
    source.require(isinstance(value, list), "CI case catalog missing")
    identities, raw_nodes = set(), set()
    for case in value:
        source.require(isinstance(case, dict)
                       and set(case) == {"id", "descriptor", "raw_nodeid"}, "invalid CI case")
        identity = _windows_case_id(case["descriptor"])
        raw = case["raw_nodeid"]
        source.require(case["id"] == identity and identity not in identities,
                       "duplicate or mismatched CI case identity")
        source.require(type(raw) is str and raw and raw not in raw_nodes,
                       "duplicate or missing CI raw node identity")
        identities.add(identity)
        raw_nodes.add(raw)
    source.require(identities == inventory, "CI case catalog does not cover collection")


def _windows_nodes(value):
    source.require(isinstance(value, list) and all(type(v) is str and v for v in value)
                   and len(value) == len(set(value)), "duplicate or invalid CI node inventory")
    return set(value)


def _validate_windows_record(record, identity, inventory, mode, index):
    source.require(isinstance(record, dict)
                   and record.get("schema") == "agent-windows-ci-pytest/v2"
                   and record.get("identity") == identity
                   and record.get("mode") == mode and record.get("shard") == index,
                   "CI record identity mismatch")
    source.require(type(record.get("exit_code")) is int and record["exit_code"] == 0
                   and record.get("errors") == [], "CI pytest execution failed or unknown")
    source.require(_windows_nodes(record.get("inventory")) == inventory,
                   "CI full collection mismatch")
    _windows_case_catalog(record.get("cases"), inventory)
    selected = _windows_nodes(record.get("selected"))
    outcomes = record.get("outcomes")
    source.require(isinstance(outcomes, dict), "CI execution outcomes missing")
    if mode == "inventory":
        source.require(selected == inventory and outcomes == {}, "invalid independent inventory")
        return selected
    source.require(selected <= inventory and set(outcomes) == selected,
                   "CI selected node was not executed")
    for phases in outcomes.values():
        source.require(isinstance(phases, dict)
                       and set(phases) <= {"setup", "call", "teardown"}
                       and phases.get("teardown") == "passed"
                       and ((phases.get("setup") == "passed"
                             and phases.get("call") in {"passed", "skipped"})
                            or (phases.get("setup") == "skipped" and "call" not in phases)),
                       "CI node has incomplete or unsuccessful phases")
    return selected


def verify_windows_reports(groups: list, expected: dict) -> dict:
    """One mandatory Windows gate: exact source plus complete disjoint execution."""
    source.require(isinstance(groups, list) and len(groups) == 2, "two CI groups required")
    seen_groups, seen_shards, executed = set(), set(), set()
    inventory, identity = None, None
    for group in groups:
        source.require(isinstance(group, dict)
                       and group.get("schema") == "agent-windows-ci-group/v1",
                       "invalid CI group")
        index = group.get("group")
        source.require(type(index) is int and index in {0, 1} and index not in seen_groups,
                       "duplicate or missing CI group")
        seen_groups.add(index)
        observed = group.get("identity")
        source.require(isinstance(observed, dict)
                       and all(observed.get(k) == v for k, v in expected.items())
                       and observed.get("platform") == "win32"
                       and type(observed.get("python")) is str
                       and observed["python"].startswith("3.12."), "CI source/event/OS mismatch")
        if identity is None:
            identity = observed
            independent = group.get("inventory")
            source.require(isinstance(independent, dict), "independent CI inventory missing")
            inventory = _windows_nodes(independent.get("inventory"))
            source.require(bool(inventory), "empty global CI inventory")
        source.require(observed == identity, "CI runner identities differ")
        source.require(group.get("timed_out") is False
                       and type(group.get("exit_code")) is int and group["exit_code"] == 0
                       and group.get("timeout_seconds") == WINDOWS_CI_TIMEOUT,
                       "CI group failed, timed out or changed its limit")
        duration = group.get("duration_seconds")
        source.require(type(duration) in {int, float} and math.isfinite(duration)
                       and 0 <= duration < WINDOWS_CI_TIMEOUT, "CI group exceeded its deadline")
        _validate_windows_record(group.get("inventory"), identity, inventory, "inventory", None)
        shards = group.get("shards")
        source.require(isinstance(shards, list) and len(shards) == 2, "two CI shards per runner")
        for record in shards:
            shard = record.get("shard") if isinstance(record, dict) else None
            source.require(type(shard) is int and shard in {index * 2, index * 2 + 1}
                           and shard not in seen_shards, "duplicate or misplaced CI shard")
            selected = _validate_windows_record(record, identity, inventory, "shard", shard)
            source.require(not executed.intersection(selected), "overlapping CI execution")
            executed.update(selected)
            seen_shards.add(shard)
    source.require(seen_shards == set(range(WINDOWS_CI_SHARDS)) and executed == inventory,
                   "CI execution does not cover the full inventory")
    return {"result": "PASS", "identity": identity, "node_count": len(inventory),
            "shard_count": WINDOWS_CI_SHARDS, "inventory_sha256": source.digest(sorted(inventory))}


def windows_pytest(root, output, expected, *, mode, shard=None):
    import pytest

    identity = windows_identity(root, expected)
    recorder = _WindowsRecorder(identity, mode, shard)
    pytest.hookimpl(tryfirst=True)(_WindowsRecorder.pytest_collection_modifyitems)
    args = ["-q", f"--rootdir={root}"]
    if mode == "inventory":
        args.append("--collect-only")
    else:
        args += [f"--provelume-shard-index={shard}", "--provelume-shard-count=4",
                 "-vv", "--durations=10", "-o", f"cache_dir={output.parent / 'pytest-cache'}",
                 f"--basetemp={output.parent / 'pytest-tmp'}"]
    code = int(pytest.main(args, plugins=[recorder]))
    source.require(windows_identity(root, expected) == identity, "CI source changed during pytest")
    output.write_text(json.dumps(recorder.record(code), ensure_ascii=True) + "\n", encoding="utf-8")
    return code


def run_windows_group(root, output, expected, group):
    source.require(sys.platform == "win32", "Windows CI execution requires Windows")
    source.require(group in {0, 1}, "invalid Windows CI group")
    source.require(not output.exists() and not output.resolve().is_relative_to(root.resolve()),
                   "new external CI evidence directory required")
    identity = windows_identity(root, expected)
    started = time.monotonic()
    deadline = started + WINDOWS_CI_TIMEOUT
    output.mkdir(parents=True)
    processes, handles, reports = [], [], []
    timed_out = False

    def start(mode, index, destination):
        state = output / ("inventory-state" if index is None else f"state-{index}")
        state.mkdir()
        environment = {**os.environ, "PYTHONPATH": os.pathsep.join(
            (str(root / "core"), str(root), str(root / "tools"))), "PYTHONIOENCODING": "utf-8",
            "PROVELUME_WINDOWS_SHARD_CHILD": "1", "LOCALAPPDATA": str(state)}
        environment.pop("PROVELUME_WINDOWS_SHARD_FORCE", None)
        command = [sys.executable, str(Path(__file__).resolve()), "windows-" + mode,
                   "--root", str(root), "--output", str(destination),
                   "--commit", expected["commit"], "--run-id", expected["run_id"],
                   "--run-attempt", expected["run_attempt"], "--event", expected["event"]]
        if index is not None:
            command += ["--shard", str(index)]
        handle = destination.with_suffix(".log").open("xb")
        handles.append(handle)
        process = subprocess.Popen(command, cwd=root, env=environment, stdin=subprocess.DEVNULL,
                                   stdout=handle, stderr=subprocess.STDOUT)
        processes.append(process)
        return process

    inventory_path = output / f"inventory-{group}.json"
    try:
        inventory_process = start("inventory", None, inventory_path)
        inventory_process.wait(timeout=max(0.01, deadline - time.monotonic()))
        source.require(inventory_process.returncode == 0, "independent Windows collection failed")
        inventory = source.read_json(inventory_path)
        for index in (group * 2, group * 2 + 1):
            # Reports/logs stay outside each distinct pytest state directory.
            state = output / f"shard-{index}"
            state.mkdir()
            report = state / f"shard-{index}.json"
            reports.append(report)
            start("shard", index, report)
        for process in processes[1:]:
            process.wait(timeout=max(0.01, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        timed_out = True
    except (source.EvidenceError, OSError, ValueError) as error:
        print(f"Windows CI group failed: {error}")
    finally:
        for process in processes:
            if process.poll() is None:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               check=False, timeout=10)
                process.wait(timeout=10)
        for handle in handles:
            handle.close()
    unchanged = windows_identity(root, expected) == identity
    shards = [source.read_json(p) for p in reports if p.exists()]
    inventory = source.read_json(inventory_path) if inventory_path.exists() else None
    succeeded = (len(processes) == 3 and all(p.returncode == 0 for p in processes)
                 and len(shards) == 2 and unchanged and not timed_out
                 and time.monotonic() < deadline)
    result = {"schema": "agent-windows-ci-group/v1", "identity": identity, "group": group,
              "inventory": inventory, "shards": shards, "timed_out": timed_out,
              "exit_code": 0 if succeeded else 1, "timeout_seconds": WINDOWS_CI_TIMEOUT,
              "duration_seconds": time.monotonic() - started}
    (output / f"group-{group}.json").write_text(json.dumps(result) + "\n", encoding="utf-8")
    for log in output.rglob("*.log"):
        data = log.read_bytes()
        replay = data[-2 * 1024 * 1024:].decode("utf-8", errors="replace")
        if len(data) > 2 * 1024 * 1024:
            replay = "[bounded output; complete log retained in artifact]\n" + replay
        encoding = sys.stdout.encoding or "utf-8"
        print(replay.encode(encoding, errors="backslashreplace").decode(encoding))
    return result["exit_code"]


def windows_main(argv):
    parser = argparse.ArgumentParser(description="Exact-source Windows CI coverage")
    parser.add_argument("command", choices=["windows-group", "windows-inventory",
                                           "windows-shard", "windows-verify"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    for name in ("commit", "run-id", "run-attempt", "event"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--group", type=int)
    parser.add_argument("--shard", type=int)
    parser.add_argument("--groups-result")
    args = parser.parse_args(argv)
    expected = {k: getattr(args, k) for k in ("commit", "run_id", "run_attempt", "event")}
    root = args.root.resolve()
    if args.command == "windows-group":
        return run_windows_group(root, args.output.resolve(), expected, args.group)
    if args.command == "windows-verify":
        source.require(args.groups_result == "success", "Windows runner jobs did not all succeed")
        identity = windows_identity(root, expected)
        expected["tree"] = identity["tree"]
        groups = [source.read_json(p) for p in sorted(args.output.glob("**/group-*.json"))]
        print(json.dumps(verify_windows_reports(groups, expected), indent=2))
        return 0
    source.require(not args.output.exists(), "preserve prior CI observation")
    return windows_pytest(root, args.output, expected,
                          mode="inventory" if args.command == "windows-inventory" else "shard",
                          shard=args.shard)


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1].startswith("windows-"):
        try:
            return windows_main(sys.argv[1:])
        except (source.EvidenceError, OSError, ValueError, TypeError, KeyError) as exc:
            print(json.dumps({"result": "BLOCKED", "reason": str(exc)}))
            return 2
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("snapshot", "baseline", "candidate", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--workstream", choices=["PROTOCOL", "PRODUCT", "CHECKPOINT_ONLY"],
                        required=True)
    parser.add_argument("--suite", choices=["PROTOCOL_ONLY", "FULL"], required=True)
    parser.add_argument("--canonical-snapshot", type=Path)
    parser.add_argument("--canonical-anchor", type=Path)
    parser.add_argument("--adapter-root", type=Path)
    args = parser.parse_args()
    try:
        result, code = run_check(
            args.snapshot,
            args.baseline,
            args.candidate,
            args.output,
            workstream=args.workstream,
            suite=args.suite,
            canonical_snapshot=args.canonical_snapshot,
            canonical_anchor=args.canonical_anchor,
            adapter_root=args.adapter_root,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return code
    except (source.EvidenceError, OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"result": "BLOCKED", "reason": str(exc), "push_qualified": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
