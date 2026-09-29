"""Credential-free Git journal plumbing for an independently authorized host.

The caller runs this accepted package outside the candidate checkout. SSH signing
keys remain in the host's existing signer/agent; only approved public signer lines
are supplied here. No signing key is generated, copied or granted by this module.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from .ledger import canonical, exact, replay, require, sha


class GitJournal:
    def __init__(self, directory, identity, allowed_signers):
        self.directory = Path(directory).resolve()
        self.identity = identity
        self.ref = f"refs/heads/agent-protocol/work/pr-{identity['pr']}"
        require(
            isinstance(allowed_signers, str) and allowed_signers.strip(),
            "Accepted public signer registry required",
        )
        self.allowed_signers = allowed_signers
        require(
            self.git("rev-parse", "--is-shallow-repository").strip() == b"false",
            "Shallow journal cannot prove complete history",
        )
        require(
            not self.git("for-each-ref", "--format=%(refname)", "refs/replace").strip(),
            "Replacement history refused",
        )
        git_dir = Path(self.git("rev-parse", "--absolute-git-dir").decode().strip())
        require(not (git_dir / "info/grafts").exists(), "Grafted history refused")

    def git(self, *argv, data=None, config=(), allow_failure=False):
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("GIT_") or k in {"GIT_SSH", "GIT_SSH_COMMAND", "GIT_ASKPASS"}
        }
        env["GIT_NO_REPLACE_OBJECTS"] = "1"
        command = ["git", "--no-replace-objects", "-C", str(self.directory)]
        for key, value in config:
            command += ["-c", key + "=" + value]
        process = subprocess.run([*command, *argv], input=data, capture_output=True, env=env)
        if not allow_failure:
            require(
                process.returncode == 0,
                "Git operation failed: " + process.stderr.decode(errors="replace"),
            )
        return process if allow_failure else process.stdout

    def tip(self):
        result = self.git("show-ref", "--verify", "--quiet", self.ref, allow_failure=True)
        if result.returncode == 1:
            return None
        require(result.returncode == 0, "Cannot observe journal; absence is not established")
        return sha(self.git("show-ref", "--verify", "--hash", self.ref).decode().strip())

    def read(self):
        tip = self.tip()
        if tip is None:
            return replay([], identity=self.identity, authenticated_commits={})
        commits = self.git("rev-list", "--reverse", "--topo-order", tip).decode().splitlines()
        rows, principals = [], {}
        with tempfile.TemporaryDirectory(prefix="protocol-signers-") as temporary:
            trusted = Path(temporary) / "allowed_signers"
            trusted.write_text(self.allowed_signers, encoding="utf-8")
            config = [("gpg.format", "ssh"), ("gpg.ssh.allowedSignersFile", str(trusted))]
            for commit in commits:
                verified = self.git("verify-commit", commit, config=config, allow_failure=True)
                require(verified.returncode == 0, "Untrusted or missing journal signature")
                signer = (
                    self.git("log", "-1", "--format=%GS", commit, config=config).decode().strip()
                )
                require(signer and "\n" not in signer, "Ambiguous signer identity")
                principals[commit] = signer
                parents = self.git("show", "-s", "--format=%P", commit).decode().split()
                tree = self.git("ls-tree", "-r", commit).decode().splitlines()
                require(
                    len(tree) == 1
                    and re.fullmatch(r"100644 blob [0-9a-f]{40}\tevent.json", tree[0]),
                    "Journal commit contains unexpected files or mode",
                )
                event = json.loads(self.git("show", commit + ":event.json"))
                rows.append({"commit": commit, "parents": parents, "event": event})
        require(commits[-1] == tip, "Incomplete journal traversal")
        return replay(rows, identity=self.identity, authenticated_commits=principals)

    def commit_plan(self, plan, *, refresh_and_plan):
        """Only a fresh deterministic plan may be signed and CAS-appended.

        refresh_and_plan is the accepted host's observation/engine entrypoint. It
        rechecks real PR/head/authority and returns the same typed plan or refuses.
        The public CLI does not expose an arbitrary journal writer.
        """
        exact(plan, "event expected_tip", "host write plan")
        current = self.read()
        prior = current["operations"].get(plan["event"]["operation_id"])
        if prior is not None:
            require(prior == plan["event"], "Operation ID reused for different content")
            return {"state": "ALREADY_APPLIED", "tip": current["tip"]}
        require(current["tip"] == plan["expected_tip"], "Concurrent journal head changed")
        require(refresh_and_plan(current) == plan, "Preconditions changed before signing")
        event = plan["event"]
        # Replay the new event before write. Authentication below is independently
        # verified again from the newly signed commit, before its ref is advanced.
        blob = self.git("hash-object", "-w", "--stdin", data=canonical(event)).decode().strip()
        tree = (
            self.git("mktree", data=f"100644 blob {blob}\tevent.json\n".encode()).decode().strip()
        )
        argv = ["commit-tree", "-S", tree]
        if current["tip"] is not None:
            argv += ["-p", current["tip"]]
        commit = (
            self.git(*argv, data=("Agent Protocol " + event["operation_id"] + "\n").encode())
            .decode()
            .strip()
        )
        # Verify the whole prospective chain under an isolated ref-free read.
        original_tip = self.tip
        try:
            self.tip = lambda: commit
            self.read()
        finally:
            self.tip = original_tip
        result = self.git(
            "update-ref", self.ref, commit, current["tip"] or "0" * 40, allow_failure=True
        )
        if result.returncode:
            # Do not repeat an uncertain write. The caller inspects this same ID.
            actual = self.read()
            if actual["operations"].get(event["operation_id"]) == event:
                return {"state": "APPLIED_RECONCILED", "tip": actual["tip"]}
            raise ValueError("Concurrent write refused; reconcile existing journal")
        return {"state": "APPLIED_LOCAL", "tip": commit, "publication": "REQUIRED"}

    def publish(self):
        """Normal fast-forward Git push only; a remote concurrent append refuses."""
        self.synchronize()
        self.read()
        tip = self.tip()
        require(tip is not None, "No durable event to publish")
        result = self.git("push", "origin", tip + ":" + self.ref, allow_failure=True)
        observed = self.git("ls-remote", "--refs", "origin", self.ref).decode().split()
        if observed and observed[0] == tip:
            return {"state": "DURABLE", "tip": tip}
        require(
            result.returncode == 0,
            "Publication uncertain or concurrent; fetch and reconcile, never force",
        )
        raise ValueError("Published identity not observed; reconcile before retry")

    def synchronize(self):
        """Reconcile one remote branch without resetting work or guessing absence."""
        before = self.read()
        observed = self.git("ls-remote", "--refs", "origin", self.ref).decode().splitlines()
        if not observed:
            return {"state": "NOT_PUBLISHED", "tip": before["tip"]}
        require(len(observed) == 1, "Ambiguous remote journal")
        remote_tip, remote_ref = observed[0].split()
        sha(remote_tip)
        require(remote_ref == self.ref, "Remote journal identity mismatch")
        if remote_tip == before["tip"]:
            return {"state": "CURRENT", "tip": remote_tip}
        self.git("fetch", "--no-tags", "origin", self.ref)
        fetched = self.git("rev-parse", "FETCH_HEAD").decode().strip()
        require(fetched == remote_tip, "Remote journal changed while fetching; reconcile again")
        original_tip = self.tip
        try:
            self.tip = lambda: remote_tip
            remote_state = self.read()
        finally:
            self.tip = original_tip
        local_commits = [row["commit"] for row in before["events"]]
        remote_commits = [row["commit"] for row in remote_state["events"]]
        if remote_commits == local_commits[: len(remote_commits)]:
            return {"state": "LOCAL_PENDING", "tip": before["tip"], "remote_tip": remote_tip}
        require(
            local_commits == remote_commits[: len(local_commits)],
            "Divergent journal history; no reset, force push or automatic ownership change",
        )
        result = self.git(
            "update-ref", self.ref, remote_tip, before["tip"] or "0" * 40, allow_failure=True
        )
        require(result.returncode == 0, "Local journal changed during reconciliation")
        return {"state": "RESTORED", "tip": remote_tip}
