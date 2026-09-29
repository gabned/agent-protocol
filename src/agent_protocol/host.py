"""Credential-free Git journal plumbing for an independently authorized host.

The caller runs this accepted package outside the candidate checkout. SSH signing
keys remain in the host's existing signer/agent; only approved public signer lines
are supplied here. No signing key is generated, copied or granted by this module.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import tempfile
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, unquote

from .ledger import canonical, digest, exact, replay, require, sha, validate_identity
from .lifecycle import DEPENDENCIES, evaluate
from .qualification import ci_evidence, normalize_ci, verify_all_reviews, verify_protocol_candidate
from .source import ROOT, safe_path, verify_installation


def same_plan(left, right):
    """Fresh collection time may advance; operation and material preconditions may not."""

    def stable(plan):
        return {
            "expected_tip": plan["expected_tip"],
            "event": {k: v for k, v in plan["event"].items() if k != "observed_at"},
        }

    return stable(left) == stable(right)


class GitJournal:
    def __init__(
        self,
        directory,
        identity,
        allowed_signers,
        *,
        required_ancestor=None,
        environment=None,
        git_config=(),
    ):
        self.directory = Path(directory).resolve()
        self.identity = identity
        self.environment = dict(os.environ if environment is None else environment)
        self.git_config = tuple(git_config)
        self.ref = f"refs/heads/agent-protocol/work/pr-{identity['pr']}"
        require(
            isinstance(allowed_signers, str) and allowed_signers.strip(),
            "Accepted public signer registry required",
        )
        self.allowed_signers = allowed_signers
        # Process-local cache of already verified immutable commits. Live refs and
        # complete ancestry are reread on every operation; cache is never authority.
        self._verified = {}
        self.required_ancestor = sha(required_ancestor) if required_ancestor is not None else None
        keys = set()
        for line in allowed_signers.splitlines():
            fields = line.split()
            require(
                len(fields) >= 3
                and re.fullmatch(r"[A-Za-z0-9_.:@/-]+", fields[0])
                and fields[1]
                in {
                    "ssh-ed25519",
                    "ssh-rsa",
                    "ecdsa-sha2-nistp256",
                    "ecdsa-sha2-nistp384",
                    "ecdsa-sha2-nistp521",
                },
                "Exact public signer principal/key required; no wildcard enrollment",
            )
            key = base64.b64decode(fields[2], validate=True)
            require(
                key and key not in keys,
                "One public signing key cannot impersonate multiple principals",
            )
            keys.add(key)
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
            for k, v in self.environment.items()
            if not k.startswith("GIT_") or k in {"GIT_SSH", "GIT_SSH_COMMAND", "GIT_ASKPASS"}
        }
        env["GIT_NO_REPLACE_OBJECTS"] = "1"
        command = ["git", "--no-replace-objects", "-C", str(self.directory)]
        for key, value in (*self.git_config, *config):
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
            require(
                self.required_ancestor is None, "Known journal missing; synchronize durable history"
            )
            return replay([], identity=self.identity, authenticated_commits={})
        commits = self.git("rev-list", "--reverse", "--topo-order", tip).decode().splitlines()
        rows, principals = [], {}
        with tempfile.TemporaryDirectory(prefix="protocol-signers-") as temporary:
            trusted = Path(temporary) / "allowed_signers"
            trusted.write_text(self.allowed_signers, encoding="utf-8")
            config = [("gpg.format", "ssh"), ("gpg.ssh.allowedSignersFile", str(trusted))]
            for commit in commits:
                cache_key = (commit, digest(self.allowed_signers))
                if cache_key in self._verified:
                    row, signer = self._verified[cache_key]
                    rows.append(deepcopy(row))
                    principals[commit] = signer
                    continue
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
                row = {"commit": commit, "parents": parents, "event": event}
                rows.append(row)
                self._verified[cache_key] = (deepcopy(row), signer)
        require(commits[-1] == tip, "Incomplete journal traversal")
        require(
            self.required_ancestor is None or self.required_ancestor in commits,
            "Journal omits independently retained recovery anchor",
        )
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
            require(
                same_plan({"event": prior, "expected_tip": prior["expected_previous"]}, plan),
                "Operation ID reused for different content",
            )
            return {"state": "ALREADY_APPLIED", "tip": current["tip"]}
        require(current["tip"] == plan["expected_tip"], "Concurrent journal head changed")
        refreshed = refresh_and_plan(current)
        require(same_plan(refreshed, plan), "Preconditions changed before signing")
        event = refreshed["event"]
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
        before = (
            self.read()
            if self.tip()
            else replay([], identity=self.identity, authenticated_commits={})
        )
        observed = self.git("ls-remote", "--refs", "origin", self.ref).decode().splitlines()
        if not observed:
            require(self.required_ancestor is None, "Previously observed remote journal is missing")
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


class ProtocolHost:
    """Typed execution boundary for an authenticated native or connector host.

    The enclosing accepted host binds collect/authority/merge capabilities, never
    the candidate or request JSON. collect returns normalized real observations
    after raw-object qualification. authority independently authenticates policy,
    signer enrollment and exact operation grants. merge is an expected-head normal
    merge API. No arbitrary checkpoint mutation or command callback is exposed.
    """

    def __init__(self, journal, *, collect, authority, merge):
        require(
            all(callable(f) for f in (collect, authority, merge)),
            "Authenticated host capabilities required",
        )
        self.journal, self.collect, self.authority, self.merge = journal, collect, authority, merge

    def explain(self, request):
        self.journal.synchronize()
        state = self.journal.read()
        observation = (
            {}
            if request["operation_id"] in state["operations"]
            else self.collect(state["identity"])
        )
        return evaluate(state, request, observation, self.authority(state))

    def operate(self, request):
        self.journal.synchronize()
        state = self.journal.read()
        request = deepcopy(request)
        already_applied = request["operation_id"] in state["operations"]
        observation = {} if already_applied else self.collect(state["identity"])
        authority = self.authority(state)
        plan = evaluate(state, request, observation, authority)

        def refresh(current):
            return evaluate(
                current, request, self.collect(current["identity"]), self.authority(current)
            )

        written = self.journal.commit_plan(plan, refresh_and_plan=refresh)
        durable = self.journal.publish()
        if request["operation"] != "INTEGRATE":
            return {"operation": request["operation"], "write": written, "journal": durable}
        # An existing intent may represent a successful, failed or uncertain API
        # call. Never issue that write again merely because the client retried.
        if already_applied:
            return {
                "operation": "INTEGRATE",
                "journal": durable,
                "state": "RECONCILIATION_REQUIRED",
                "next_operation": "RECONCILE",
            }
        fresh = self.collect(state["identity"])
        current_authority = self.authority(state)
        refreshed = evaluate(state, request, fresh, current_authority)
        require(same_plan(refreshed, plan), "Merge preconditions changed after durable intent")
        require(
            self.journal.read()["tip"] == durable["tip"], "Concurrent integration intent changed"
        )
        try:
            response = self.merge(
                identity=state["identity"],
                expected_head=request["expected_head"],
                expected_base=fresh["coordinates"]["BASE"],
                method="merge",
            )
        except Exception as error:
            # The durable operation is retained. A host must reobserve the PR;
            # neither this exception nor a repeated request proves non-execution.
            raise ValueError(
                "Merge outcome uncertain; reconcile the existing PR before any retry"
            ) from error
        return {
            "operation": "INTEGRATE",
            "journal": durable,
            "remote_response": response,
            "state": "RECONCILIATION_REQUIRED",
            "next_operation": "RECONCILE",
        }


class GitHubCLI:
    """Supported gh authentication with a closed repository and one merge capability."""

    def __init__(self, repository, *, directory, expected_account, execute=None):
        require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository), "Invalid repository")
        self.repository, self.directory = repository, Path(directory).resolve()
        self.execute = execute or subprocess.run
        exact(expected_account, "id login", "enrolled GitHub account")
        self.expected_account = deepcopy(expected_account)
        self.environment = dict(os.environ)
        self.environment.pop("GH_DEBUG", None)
        token = self.environment.get("GH_TOKEN") or self.environment.get("GITHUB_TOKEN")
        if not token:
            selected = self.execute(
                [
                    "gh",
                    "auth",
                    "token",
                    "--hostname",
                    "github.com",
                    "--user",
                    expected_account["login"],
                ],
                capture_output=True,
                text=True,
                cwd=self.directory,
                timeout=120,
                env=self.environment,
            )
            require(
                selected.returncode == 0 and selected.stdout.strip(),
                "Enrolled GitHub login unavailable",
            )
            token = selected.stdout.strip()
        # The supported credential is kept only in the trusted operator process
        # and child gh/Git environment. It never enters argv, files or receipts.
        self.environment["GH_TOKEN"] = token
        self.environment.pop("GITHUB_TOKEN", None)
        self.assert_account()

    def request(self, suffix, *, method="GET", payload=None):
        require(
            isinstance(suffix, str)
            and (suffix == "" or suffix.startswith("/"))
            and not any(part in {".", ".."} for part in unquote(suffix.split("?")[0]).split("/"))
            and "\\" not in suffix
            and "#" not in suffix,
            "Invalid scoped GitHub route",
        )
        require(method == "GET" and payload is None, "Only scoped reads supported by this route")
        args = [
            "gh",
            "api",
            "--hostname",
            "github.com",
            "--method",
            method,
            "repos/" + self.repository + suffix,
        ]
        if payload is not None:
            args += ["--input", "-"]
        result = self.execute(
            args,
            input=json.dumps(payload) if payload is not None else None,
            capture_output=True,
            text=True,
            cwd=self.directory,
            timeout=120,
            env=self.environment,
        )
        # gh may include diagnostic context. Do not expose auth environment or raw stderr.
        require(result.returncode == 0, "GitHub operation unavailable; reconcile before retry")
        return json.loads(result.stdout)

    def account(self):
        result = self.execute(
            ["gh", "api", "--hostname", "github.com", "user"],
            capture_output=True,
            text=True,
            cwd=self.directory,
            timeout=120,
            env=self.environment,
        )
        require(result.returncode == 0, "Supported GitHub login required on the operator host")
        return json.loads(result.stdout)

    def assert_account(self):
        account = self.account()
        require(
            {"id": account["id"], "login": account["login"]} == self.expected_account,
            "Authenticated account changed from enrollment",
        )

    def atomic_merge(
        self,
        *,
        repository_node_id,
        base_ref,
        head_ref,
        expected_base,
        expected_head,
        merge_sha,
        intent_id,
    ):
        self.assert_account()
        require(
            base_ref != head_ref
            and all(
                isinstance(ref, str) and ref.startswith("refs/heads/")
                for ref in (base_ref, head_ref)
            ),
            "Exact distinct branch refs required",
        )
        require(
            all(sha(value) != "0" * 40 for value in (expected_base, expected_head, merge_sha)),
            "Ref creation/deletion is not an integration capability",
        )
        require(merge_sha not in {expected_base, expected_head}, "Normal merge commit required")
        mutation = "mutation($input:UpdateRefsInput!){updateRefs(input:$input){clientMutationId}}"
        payload = {
            "query": mutation,
            "variables": {
                "input": {
                    "repositoryId": repository_node_id,
                    "clientMutationId": intent_id,
                    "refUpdates": [
                        {
                            "name": base_ref,
                            "beforeOid": expected_base,
                            "afterOid": merge_sha,
                            "force": False,
                        },
                        {
                            "name": head_ref,
                            "beforeOid": expected_head,
                            "afterOid": expected_head,
                            "force": False,
                        },
                    ],
                }
            },
        }
        result = self.execute(
            ["gh", "api", "--hostname", "github.com", "graphql", "--input", "-"],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            cwd=self.directory,
            timeout=120,
            env=self.environment,
        )
        require(
            result.returncode == 0,
            "Atomic integration response unavailable; reconcile existing intent",
        )
        response = json.loads(result.stdout)
        require(
            not response.get("errors")
            and response.get("data", {}).get("updateRefs", {}).get("clientMutationId") == intent_id,
            "Atomic integration not confirmed; reconcile existing intent",
        )
        return {
            "state": "REFS_UPDATED_RECONCILIATION_REQUIRED",
            "merge_sha": merge_sha,
            "intent": intent_id,
        }


class NativeGitHubHost:
    """Operator-enrolled native adapter; its binding is never loaded from the candidate.

    The operator supplies an independently approved enrollment outside all candidate
    checkouts. The enrollment pins an accepted repository profile by commit and blob,
    plus the existing account, per-workstream authority and public signer registry.
    It is installation/authorization material, not a checkpoint or a candidate input.
    All dynamic state remains in the signed per-PR journal.
    """

    def __init__(self, enrollment, *, api=None, collect_raw=None):
        exact(
            enrollment,
            "schema identity authority account profile_revision profile_path "
            "profile_blob journal_directory required_ancestor public_signers source_bundle",
            "host enrollment",
        )
        require(enrollment["schema"] == "agent-host-enrollment/v1", "Unknown host enrollment")
        self.binding = deepcopy(enrollment)
        self.source_receipt = verify_installation(
            enrollment["source_bundle"], revision=enrollment["authority"]["pin"]
        )
        self.identity = enrollment["identity"]
        validate_identity(self.identity)
        require(
            self.identity["workstream_class"] == "PROTOCOL",
            "Use the accepted native PRODUCT adapter",
        )
        self.api = api or GitHubCLI(
            self.identity["repository"],
            directory=enrollment["journal_directory"],
            expected_account=enrollment["account"],
        )
        account = self.api.account()
        require(
            {"id": account["id"], "login": account["login"]} == enrollment["account"],
            "Authenticated account differs from independent enrollment",
        )
        self.journal = GitJournal(
            enrollment["journal_directory"],
            self.identity,
            enrollment["public_signers"],
            required_ancestor=enrollment["required_ancestor"],
            environment=self.api.environment,
            git_config=(
                ("credential.helper", ""),
                ("credential.https://github.com.helper", "!gh auth git-credential"),
                ("credential.interactive", "false"),
            ),
        )
        remotes = self.journal.git("remote", "get-url", "--all", "origin").decode().splitlines()
        repository = self.identity["repository"]
        permitted = {f"https://github.com/{repository}.git"}
        require(
            len(remotes) == 1 and remotes[0] in permitted,
            "Journal origin must identify the exact enrolled repository without URL credentials",
        )
        push = (
            self.journal.git("remote", "get-url", "--push", "--all", "origin").decode().splitlines()
        )
        require(push == remotes, "Separate journal push target refused")
        self.profile = self.load_profile()
        require(
            set(enrollment["authority"]["policy"]["required_gates"])
            == {"CI", "NATIVE", "REVIEWS", "EFFECTS", "ANCESTRY", "SOURCE", "AUTHORIZATION"},
            "Native host requires its complete gate inventory",
        )
        self.collect_raw = collect_raw or self.native_collection
        self.host = ProtocolHost(
            self.journal, collect=self.observe, authority=self.authority, merge=self.merge
        )

    def load_profile(self):
        binding = self.binding
        revision, path = sha(binding["profile_revision"]), safe_path(binding["profile_path"])
        repository = self.api.request("")
        require(
            (repository["full_name"], repository["id"])
            == (self.identity["repository"], self.identity["repository_id"]),
            "Repository identity changed",
        )
        branch = self.api.request("/branches/" + quote(repository["default_branch"], safe=""))
        if branch["commit"]["sha"] != revision:
            ancestry = self.api.request(
                "/compare/" + revision + "..." + sha(branch["commit"]["sha"])
            )
            require(
                ancestry["merge_base_commit"]["sha"] == revision and ancestry["status"] == "ahead",
                "Enrollment profile is not on accepted default ancestry",
            )
        record = self.api.request("/contents/" + quote(path, safe="/") + "?ref=" + revision)
        require(
            record["sha"] == sha(binding["profile_blob"]) and record["encoding"] == "base64",
            "Accepted profile blob differs from enrollment",
        )
        raw = base64.b64decode("".join(record["content"].split()), validate=True)
        import hashlib

        require(
            hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
            == record["sha"],
            "Profile bytes differ from Git identity",
        )
        profile = json.loads(raw)
        exact(
            profile,
            "schema repository repository_id paths frozen_paths required_workflows "
            "post_merge_workflows reviewers review_activity runtime effect_conditions",
            "native host profile",
        )
        require(
            profile["schema"] == "agent-host-profile/v1"
            and (profile["repository"], profile["repository_id"])
            == (self.identity["repository"], self.identity["repository_id"]),
            "Wrong accepted profile",
        )
        require(
            profile["required_workflows"] and profile["post_merge_workflows"],
            "CI cannot be optional",
        )
        self.check_effects(profile)
        return profile

    def check_effects(self, profile):
        # Each condition was qualified against real triggers under predecessor
        # change control. Unknown/inaccessible variables are never read as false.
        for condition in profile["effect_conditions"]:
            exact(condition, "repository_variable expected_value", "live effect condition")
            name = condition["repository_variable"]
            require(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name), "Invalid variable identity")
            actual = self.api.request("/actions/variables/" + name)
            require(
                actual["name"] == name and actual["value"] == condition["expected_value"],
                "Live production-trigger condition changed; no write authorized",
            )

    def authority(self, state):
        # Exact handoff/non-execution grants are externally authenticated enrollment
        # updates. The engine checks their identity, tip and allowed delta afresh.
        require(
            self.binding["authority"]["identity"] == state["identity"],
            "Enrollment identity changed",
        )
        return deepcopy(self.binding["authority"])

    def native_collection(self, identity):
        result = subprocess.run(
            [
                "node",
                str(ROOT / "tools/collect.mjs"),
                "--github",
                identity["repository"],
                str(identity["repository_id"]),
                str(identity["pr"]),
            ],
            cwd=self.journal.directory,
            capture_output=True,
            text=True,
            timeout=600,
            env=self.api.environment,
        )
        require(
            result.returncode == 0, "Complete native collection failed; inspect operator evidence"
        )
        return json.loads(result.stdout)["collection"]

    def scope(self):
        return {
            "repository": self.identity["repository"],
            "repository_id": self.identity["repository_id"],
            "source_commit": self.binding["profile_revision"],
            "workstream_class": "PROTOCOL",
            "effects": "NO_PRODUCTION",
            "paths": self.profile["paths"],
            "frozen_paths": self.profile["frozen_paths"],
            "reviewers": self.profile["reviewers"],
            "review_activity": self.profile["review_activity"],
            "ci": {
                "source_commit": self.binding["profile_revision"],
                "required_workflows": self.profile["required_workflows"],
            },
        }

    def observe(self, identity):
        require(identity == self.identity, "Host identity changed")
        self.api.assert_account()
        self.check_effects(self.profile)
        collection = self.collect_raw(identity)
        active = collection["preflight"]["active_pull_request"]
        pr = active["pr"]["response"]
        require(
            pr["number"] == identity["pr"]
            and pr["head"]["ref"] == identity["branch"]
            and pr["head"]["repo"]["id"] == identity["repository_id"],
            "Candidate identity changed",
        )
        state = self.journal.read()
        authority = self.authority(state)
        merged = pr.get("merged") is True
        require(pr["state"] in {"open", "closed"}, "Unknown PR state")
        reviews = verify_all_reviews(collection, self.profile)
        coords = {
            "HEAD": collection["head"],
            "BASE": pr["base"]["sha"],
            "MASTER": collection["final"][1]["response"]["commit"]["sha"],
            "REVIEWS": reviews["digest"],
            "PIN": authority["pin"],
            "POLICY": digest(authority["policy"]),
            "RUNTIME": digest(self.profile["runtime"]),
            "REPOSITORY": digest(identity),
            "PR_STATE": "MERGED" if merged else pr["state"].upper(),
            "AUTHORITY": digest(
                {
                    k: authority[k]
                    for k in (
                        "identity",
                        "principal",
                        "operations",
                        "capabilities",
                        "signer_registry",
                    )
                }
            ),
        }
        observation = {
            "identity": identity,
            "head": coords["HEAD"],
            "coordinates": coords,
            "observed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "effects": "NO_PRODUCTION",
            "gates": [],
            "history": {"journal_tip": state["tip"], "source": "verified-signed-journal"},
            "material": {
                "restored": True,
                "source": "signed-git-journal",
                "head": coords["HEAD"],
                "pin": coords["PIN"],
            },
            "merge": None,
            "post_merge": None,
        }
        if not merged and pr["state"] == "open":
            scope = self.scope()
            checked = verify_protocol_candidate(
                collection,
                accepted_profile=scope,
                expected_profile_digest=digest(scope),
                observe_unready=True,
            )
            results = {
                "CI": checked["ci"]["result"],
                "NATIVE": checked["ci"]["result"],
                "REVIEWS": checked["reviews"]["result"],
                "EFFECTS": "PASS",
                "ANCESTRY": "PASS",
                "SOURCE": "PASS",
                "AUTHORIZATION": "PASS",
            }
            ci_source = {k: v for k, v in checked["ci"]["inventory"].items() if k != "observed_at"}
            sources = {
                "CI": ci_source,
                "NATIVE": ci_source,
                "REVIEWS": {
                    "reviews": active["reviews"]["items"],
                    "threads": active["threads"]["response"],
                    "activity": reviews["activity"],
                },
                "EFFECTS": {
                    "profile_blob": self.binding["profile_blob"],
                    "paths": checked["paths"],
                },
                "ANCESTRY": {"commits": checked["commits"], "tree": checked["tree"]},
                "SOURCE": self.source_receipt,
                "AUTHORIZATION": {"account": self.binding["account"], "authority": authority},
            }
            for gate in authority["policy"]["required_gates"]:
                require(gate in results, "Native gate has no qualified adapter")
                observation["gates"].append(
                    {
                        "id": digest({"gate": gate, "source": sources[gate]}),
                        "gate": gate,
                        "dependencies": sorted(DEPENDENCIES[gate]),
                        "coordinates": {k: coords[k] for k in DEPENDENCIES[gate]},
                        "result": results[gate],
                        "source": sources[gate],
                    }
                )
        elif merged:
            require(
                state["status"] in {"INTEGRATING", "INTEGRATED", "CLOSED"},
                "Merge occurred outside the retained lifecycle intent",
            )
            actual = self.api.request("/git/commits/" + sha(pr["merge_commit_sha"]))
            candidate = self.api.request("/git/commits/" + sha(state["head"]))
            observation["merge"] = {
                "merge_sha": actual["sha"],
                "base_sha": state["coordinates"]["BASE"],
                "head_sha": state["head"],
                "tree_sha": actual["tree"]["sha"],
                "parents": [p["sha"] for p in actual["parents"]],
                "qualified_tree": candidate["tree"]["sha"],
            }
            require(collection["postMerge"] is not None, "Post-merge collection missing")
            policy = {
                "source_commit": self.binding["profile_revision"],
                "required_workflows": self.profile["post_merge_workflows"],
            }
            times = [row["observed_at"] for row in collection["postMerge"]["inventory"]]
            require(times, "Post-merge run inventory not observed")
            inventory = normalize_ci(
                collection["postMerge"],
                accepted_policy=policy,
                observed_at=min(times).split(".")[0].rstrip("Z") + "Z",
            )
            if inventory["runs"]:
                checked = ci_evidence(
                    inventory,
                    repository=identity["repository"],
                    head=actual["sha"],
                    accepted_policy=policy,
                )
                observation["post_merge"] = {
                    "head": actual["sha"],
                    "result": "PASS"
                    if checked["result"] == reviews["result"] == "PASS"
                    else "FAIL",
                    "complete": True,
                    "evidence": [inventory, reviews],
                }
            else:
                observation["post_merge"] = {
                    "head": actual["sha"],
                    "result": "NOT_RUN",
                    "complete": False,
                    "evidence": [inventory],
                }
        return observation

    def merge(self, *, identity, expected_head, expected_base, method):
        require(identity == self.identity and method == "merge", "Unknown merge authority")
        self.api.assert_account()
        self.check_effects(self.profile)
        state = self.journal.read()
        require(
            state["status"] == "INTEGRATING"
            and state["head"] == expected_head
            and state["coordinates"]["BASE"] == expected_base,
            "Exact durable integration intent required",
        )
        repository = self.api.request("")
        require(
            (repository["full_name"], repository["id"])
            == (identity["repository"], identity["repository_id"]),
            "Repository identity changed",
        )
        pr = self.api.request(f"/pulls/{identity['pr']}")
        require(
            pr["state"] == "open"
            and not pr["draft"]
            and pr["mergeable"] is True
            and pr["head"]["sha"] == expected_head
            and pr["base"]["sha"] == expected_base
            and pr["head"]["ref"] == identity["branch"]
            and pr["base"]["ref"] == repository["default_branch"]
            and pr["head"]["repo"]["id"] == pr["base"]["repo"]["id"] == identity["repository_id"],
            "Merge coordinates changed before write",
        )
        base_name = quote(repository["default_branch"], safe="")
        branch = self.api.request("/branches/" + base_name)
        # Indirect merge must never be an escape from PR protections/rulesets.
        # Unknown/inaccessible rule inventory also refuses this transport.
        require(
            branch["protected"] is False and self.api.request("/rules/branches/" + base_name) == [],
            "Protected integration requires an accepted atomic native adapter",
        )
        require(branch["commit"]["sha"] == expected_base, "Base advanced before integration")
        merged = self.api.request("/git/commits/" + sha(pr["merge_commit_sha"]))
        candidate = self.api.request("/git/commits/" + sha(expected_head))
        require(
            [p["sha"] for p in merged["parents"]] == [expected_base, expected_head]
            and merged["tree"]["sha"] == candidate["tree"]["sha"],
            "GitHub merge preview differs from qualified parents/tree",
        )
        # REST merge's `sha` guards only the PR head. GitHub updateRefs guards
        # both refs atomically, without force, using the existing two-parent
        # merge object. The head no-op is an expected-value guard, not a rewrite.
        # Only subsequent actual PR/commit/post-CI observation establishes merge.
        return self.api.atomic_merge(
            repository_node_id=repository["node_id"],
            base_ref="refs/heads/" + repository["default_branch"],
            head_ref="refs/heads/" + identity["branch"],
            expected_base=expected_base,
            expected_head=expected_head,
            merge_sha=merged["sha"],
            intent_id=state["tip"],
        )
