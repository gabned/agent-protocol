"""Offline trusted-base scope guard: a candidate never selects its own registry."""

import argparse
import json
import re
import subprocess
from pathlib import Path

FROZEN = frozenset(
    {
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


def inspect(base, head, body, registry):
    if not all(re.fullmatch("[0-9a-f]{40}", sha) for sha in (base, head)):
        raise ValueError("Exact commit identities required")
    if re.findall(r"(?m)^WORKSTREAM_CLASS:[ \t]*([^\r\n]+?)\r?$", body) != ["PROTOCOL"]:
        raise ValueError("Exactly one PROTOCOL workstream marker required")
    allowed = set(registry["paths"])
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
    if not changed or not changed <= allowed:
        raise ValueError("Unregistered scope: " + repr(sorted(changed - allowed)))
    if changed & FROZEN or any(path.startswith("compat/legacy/") for path in changed):
        raise ValueError("GATE_CHANGE_REQUIRES_PREDECESSOR_QUALIFICATION")
    tree = subprocess.check_output(
        ["git", "--no-replace-objects", "ls-tree", "-r", "-z", head]
    )
    for record in tree.split(b"\0"):
        if not record:
            continue
        meta, name = record.split(b"\t", 1)
        if meta.split()[0] not in {b"100644", b"100755"}:
            raise ValueError("Symlink or submodule is not an approved file")
        if name.decode() not in allowed:
            raise ValueError("Unregistered tree entry")
    return {
        "result": "PASS",
        "base": base,
        "head": head,
        "paths": sorted(changed),
        "effects": "NO_PRODUCTION",
        "new_capabilities": [],
    }


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
