"""Offline trusted-base scope guard: a candidate never selects its own registry."""

import argparse
import json
import re
import subprocess
from pathlib import Path

FROZEN = frozenset(
    {
        "AGENTS.md",
        ".github/workflows/ci.yml",
        "tools/guard.py",
        "tools/check.py",
        ".github/agent-protocol/bootstrap.json",
        "requirements-test.txt",
        ".ruff.toml",
        ".gitattributes",
        "LICENSE",
        "COMMERCIAL-LICENSE.md",
        "THIRD_PARTY_NOTICES.md",
        "docs/agent-protocol/bootstrap.md",
    }
)


def check_repository(event, registry):
    actual = event["repository"]
    if (actual["full_name"], actual["id"]) != (
        registry["repository"],
        registry["repository_id"],
    ):
        raise ValueError("Stable repository identity mismatch")


def introduced_commits(base, head):
    """Require complete, unmodified Git ancestry, bounded by the accepted base."""
    git = ["git", "--no-replace-objects"]
    if (
        subprocess.check_output([*git, "rev-parse", "--is-shallow-repository"]).strip()
        != b"false"
    ):
        raise ValueError("Complete history required")
    grafts = Path(
        subprocess.check_output([*git, "rev-parse", "--git-path", "info/grafts"])
        .decode()
        .strip()
    )
    if (
        grafts.exists()
        or subprocess.check_output([*git, "for-each-ref", "refs/replace/"]).strip()
    ):
        raise ValueError("Replaced history is not accepted")
    rows = (
        subprocess.check_output(
            [
                *git,
                "rev-list",
                "--reverse",
                "--topo-order",
                "--parents",
                head,
                "^" + base,
            ]
        )
        .decode()
        .splitlines()
    )
    previous, commits = base, []
    for row in rows:
        fields = row.split()
        if len(fields) != 2 or fields[1] != previous:
            raise ValueError(
                "Candidate requires a complete linear chain from accepted base"
            )
        commits.append((previous, fields[0]))
        previous = fields[0]
    if not commits or previous != head:
        raise ValueError("No introduced candidate history")
    return commits


def inspect(base, head, body, registry):
    if not all(re.fullmatch("[0-9a-f]{40}", sha) for sha in (base, head)):
        raise ValueError("Exact commit identities required")
    if re.findall(r"(?m)^WORKSTREAM_CLASS:[ \t]*([^\r\n]+?)\r?$", body) != ["PROTOCOL"]:
        raise ValueError("Exactly one PROTOCOL workstream marker required")
    allowed = set(registry["paths"])
    modes = registry["modes"]
    if set(modes) != allowed or any(
        value not in {"100644", "100755"} for value in modes.values()
    ):
        raise ValueError("Incomplete accepted mode inventory")
    changed = set()
    commits = introduced_commits(base, head)
    for parent, commit in commits:
        changed.update(inspect_delta(parent, commit, allowed, modes))
    if not changed:
        raise ValueError("Empty candidate scope")
    return {
        "result": "PASS",
        "base": base,
        "head": head,
        "commits": [commit for _, commit in commits],
        "paths": sorted(changed),
        "effects": "NO_PRODUCTION",
        "new_capabilities": [],
    }


def inspect_delta(base, head, allowed, modes):
    raw = subprocess.check_output(
        [
            "git",
            "--no-replace-objects",
            "diff",
            "--name-status",
            "-z",
            "--find-renames",
            base,
            head,
        ]
    )
    fields = raw.decode("utf-8", errors="strict").split("\0")
    changed = set()
    index = 0
    while fields[index]:
        status = fields[index]
        count = 2 if status.startswith(("R", "C")) else 1
        changed.update(fields[index + 1 : index + 1 + count])
        index += 1 + count
    if not changed <= allowed:
        raise ValueError("Unregistered scope: " + repr(sorted(changed - allowed)))
    if changed & FROZEN or any(path.startswith("compat/legacy/") for path in changed):
        raise ValueError("GATE_CHANGE_REQUIRES_PREDECESSOR_QUALIFICATION")
    tree = subprocess.check_output(
        ["git", "--no-replace-objects", "ls-tree", "-r", "-z", head]
    )
    names = set()
    for record in tree.split(b"\0"):
        if not record:
            continue
        meta, name = record.split(b"\t", 1)
        if meta.split()[0] not in {b"100644", b"100755"}:
            raise ValueError("Symlink or submodule is not an approved file")
        if name.decode() not in allowed:
            raise ValueError("Unregistered tree entry")
        if meta.split()[0].decode() != modes[name.decode()]:
            raise ValueError("Registered file mode mismatch")
        folded = name.decode().casefold()
        if folded in names:
            raise ValueError("Case-insensitive path collision")
        names.add(folded)
    return changed


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--event", type=Path, required=True)
    args = p.parse_args()
    event = json.loads(args.event.read_text(encoding="utf-8"))
    pr = event["pull_request"]
    base, head = pr["base"]["sha"], pr["head"]["sha"]
    registry = json.loads(
        subprocess.check_output(
            [
                "git",
                "--no-replace-objects",
                "show",
                base + ":.github/agent-protocol/bootstrap.json",
            ]
        )
    )
    check_repository(event, registry)
    observed = (
        subprocess.check_output(["git", "rev-parse", "FETCH_HEAD"]).decode().strip()
    )
    if observed != head:
        raise ValueError("PR ref moved since event")
    print(json.dumps(inspect(base, head, pr.get("body") or "", registry)))


if __name__ == "__main__":
    main()
