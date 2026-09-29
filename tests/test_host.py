import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import base64
import copy
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from test_ledger import IDENTITY, event, start
from test_lifecycle import fixture
from test_qualification import protocol_fixture

from agent_protocol.host import GitHubCLI, GitJournal, NativeGitHubHost, ProtocolHost, same_plan
from agent_protocol.ledger import digest, replay
from agent_protocol.lifecycle import evaluate


class SignedJournalTests(unittest.TestCase):
    def test_native_adapter_keeps_evidence_stable_and_rechecks_production_conditions(self):
        state, _, _, authority = fixture()
        collection, scope = protocol_fixture()
        stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        def fresh(value):
            if isinstance(value, dict):
                return {k: stamp if k == "observed_at" else fresh(v) for k, v in value.items()}
            return [fresh(v) for v in value] if isinstance(value, list) else value

        collection = fresh(collection)
        collection["preflight"]["repo"]["response"]["default_branch"] = "main"
        pr = collection["preflight"]["active_pull_request"]["pr"]["response"]
        pr["head"].update(ref=IDENTITY["branch"], repo={"id": 17})
        pr["base"].update(ref="main", repo={"id": 17, "full_name": IDENTITY["repository"]})
        pr["merge_commit_sha"] = "e" * 40
        pr["comments"] = 1

        def provider_summary(head):
            return (
                "<!-- codex-pull-request-review-summary -->\n"
                f"| **Code Review** | **Completed** | `{head[:7]}` | Manual |\n"
                f"| **Security Review** | **Completed** | `{head[:7]}` | Manual |\n"
                "<!-- codex-security-review:v1 "
                + json.dumps(
                    {
                        "headSha": head,
                        "repository": IDENTITY["repository"],
                        "pullRequestNumber": 4,
                        "status": "completed",
                    }
                )
                + " -->"
            )

        collection["issueComments"] = [
            {"id": 9, "user": {"id": 123, "type": "Bot"}, "body": provider_summary("a" * 40)}
        ]
        collection["reviewReferences"] = [
            {
                "url": f"https://api.github.com/repos/{IDENTITY['repository']}/commits/aaaaaaa",
                "status": "OBSERVED",
                "observed_at": stamp,
                "response": {"sha": "a" * 40},
            }
        ]
        collection["reviewViewer"] = {
            "url": "https://api.github.com/user",
            "status": "OBSERVED",
            "observed_at": stamp,
            "response": {"id": 19, "login": "reviewer"},
        }
        collection["preflight"]["active_pull_request"]["reviews"]["items"] = [
            {"id": 1, "user": {"login": "reviewer"}, "state": "APPROVED", "commit_id": "a" * 40}
        ]
        authority["policy"]["required_gates"] = [
            "CI",
            "NATIVE",
            "REVIEWS",
            "EFFECTS",
            "ANCESTRY",
            "SOURCE",
            "AUTHORIZATION",
        ]
        profile = {
            "schema": "agent-host-profile/v1",
            "repository": IDENTITY["repository"],
            "repository_id": 17,
            "paths": scope["paths"],
            "frozen_paths": [],
            "reviewers": ["reviewer"],
            "review_activity": [
                {"provider": "CODEX_SUMMARY_V1", "author_id": 123, "kind": kind}
                for kind in ("CODE", "SECURITY")
            ],
            "required_workflows": scope["ci"]["required_workflows"],
            "post_merge_workflows": [".github/workflows/ci.yml@push"],
            "runtime": {"python": "synthetic-runtime"},
            "effect_conditions": [
                {"repository_variable": "SYNTHETIC_DEPLOY", "expected_value": "false"}
            ],
        }
        blob = json.dumps(profile).encode()
        profile_blob = hashlib.sha1(b"blob " + str(len(blob)).encode() + b"\0" + blob).hexdigest()
        enabled = [False]
        calls = []

        def api(suffix, **kwargs):
            calls.append((suffix, kwargs))
            if suffix == "":
                return {
                    "full_name": IDENTITY["repository"],
                    "id": 17,
                    "default_branch": "main",
                    "node_id": "synthetic-node",
                }
            if suffix == "/branches/main":
                return {"commit": {"sha": "b" * 40}, "protected": False}
            if suffix == "/rules/branches/main":
                return []
            if suffix.startswith("/git/commits/"):
                return {
                    "sha": suffix.rsplit("/", 1)[1],
                    "tree": {"sha": "f" * 40},
                    "parents": [{"sha": "b" * 40}, {"sha": "a" * 40}],
                }
            if suffix.startswith("/contents/"):
                return {
                    "sha": profile_blob,
                    "encoding": "base64",
                    "content": base64.b64encode(blob).decode(),
                }
            if suffix == "/actions/variables/SYNTHETIC_DEPLOY":
                return {"name": "SYNTHETIC_DEPLOY", "value": str(enabled[0]).lower()}
            if suffix == "/pulls/4":
                return pr
            self.fail("Unexpected API route: " + suffix)

        mutations = []

        def normal_merge(**kwargs):
            mutations.append(kwargs)
            return {"state": "MERGED_RECONCILIATION_REQUIRED"}

        native = NativeGitHubHost.__new__(NativeGitHubHost)
        native.identity = IDENTITY
        native.binding = {
            "authority": authority,
            "profile_revision": "b" * 40,
            "profile_path": ".github/agent-protocol/host.json",
            "profile_blob": profile_blob,
            "account": {"id": 19, "login": "synthetic-operator"},
        }
        native.api = SimpleNamespace(
            request=api, assert_account=lambda: None, merge_pull_request=normal_merge
        )
        native.source_receipt = {"result": "BYTES_VERIFIED", "revision": authority["pin"]}
        native.journal = SimpleNamespace(read=lambda: state, synchronize=lambda: None)
        native.collect_raw = lambda identity: copy.deepcopy(collection)
        native.profile = native.load_profile()
        first, second = native.observe(IDENTITY), native.observe(IDENTITY)
        self.assertEqual(first["gates"], second["gates"])
        self.assertEqual(
            {g["gate"] for g in first["gates"]}, set(authority["policy"]["required_gates"])
        )
        self.assertTrue(all(g["result"] == "PASS" for g in first["gates"]))
        self.assertEqual(first["coordinates"]["POLICY"], digest(authority["policy"]))
        original_body = pr["body"]
        pr["body"] = ""
        with self.assertRaisesRegex(ValueError, "workstream marker"):
            native.observe(IDENTITY)
        self.assertEqual(native.observe(IDENTITY, recovery=True)["gates"], [])
        pr["body"] = original_body
        pr["draft"] = True
        draft = native.observe(IDENTITY)
        self.assertEqual(
            next(g["result"] for g in draft["gates"] if g["gate"] == "REVIEWS"), "NOT_RUN"
        )
        pr["draft"] = False
        args = {
            "identity": IDENTITY,
            "expected_head": "a" * 40,
            "expected_base": "b" * 40,
            "method": "merge",
        }
        with self.assertRaisesRegex(ValueError, "durable integration intent"):
            native.merge(**args)
        native.journal = SimpleNamespace(
            synchronize=lambda: None,
            read=lambda: {
                **state,
                "status": "INTEGRATING",
                "head": "a" * 40,
                "coordinates": first["coordinates"],
                "tip": "c" * 40,
            },
        )
        self.assertEqual(native.merge(**args)["state"], "MERGED_RECONCILIATION_REQUIRED")
        self.assertEqual(mutations[0]["number"], 4)
        self.assertEqual(mutations[0]["expected_head"], "a" * 40)
        original_journal = native.journal
        retained_intent = copy.deepcopy(native.journal.read())
        synchronized = []

        def competing_settlement():
            synchronized.append(True)
            if len(synchronized) == 2:
                retained_intent.update(tip="7" * 40, status="ACTIVE")

        native.journal = SimpleNamespace(
            read=lambda: retained_intent, synchronize=competing_settlement
        )
        count = len(mutations)
        with self.assertRaisesRegex(ValueError, "Remote integration intent changed"):
            native.merge(**args)
        self.assertEqual(len(mutations), count)
        native.journal = original_journal
        synchronized.clear()

        def change_effect_during_sync():
            synchronized.append(True)
            if len(synchronized) == 2:
                enabled[0] = True

        native.journal = SimpleNamespace(
            read=original_journal.read, synchronize=change_effect_during_sync
        )
        with self.assertRaisesRegex(ValueError, "production-trigger"):
            native.merge(**args)
        self.assertEqual(len(mutations), count)
        enabled[0] = False
        native.journal = original_journal
        native.api.request = lambda suffix: (
            {"commit": {"sha": "0" * 40}, "protected": True}
            if suffix == "/branches/main"
            else api(suffix)
        )
        with self.assertRaisesRegex(ValueError, "Base advanced"):
            native.merge(**args)
        native.api.request = api
        # A late mutable qualification failure prevents the provider call.
        original_observe = native.observe
        observed = copy.deepcopy(first)
        observed["gates"][0]["result"] = "FAIL"
        native.observe = lambda identity: observed
        count = len(mutations)
        with self.assertRaisesRegex(ValueError, "Qualification no longer complete"):
            native.merge(**args)
        self.assertEqual(len(mutations), count)
        native.observe = original_observe
        count = len(mutations)
        enabled[0] = True
        with self.assertRaisesRegex(ValueError, "production-trigger"):
            native.merge(**args)
        self.assertEqual(len(mutations), count)

        # Exercise the actual native recovery collection and typed explain path.
        enabled[0] = False
        authority["operations"].append("RECONCILE_NOT_APPLIED")
        native.journal = SimpleNamespace(read=lambda: state, synchronize=lambda: None)
        events = []
        for index, operation in enumerate(("START", "QUALIFY", "INTEGRATE"), 1):
            request = dict(
                operation=operation,
                operation_id="native-" + operation.lower(),
                expected_tip=state["tip"],
                expected_head="a" * 40,
                parameters={},
            )
            plan = evaluate(state, request, native.observe(IDENTITY), authority)
            events.append(
                {
                    "commit": str(index) * 40,
                    "parents": [state["tip"]] if state["tip"] else [],
                    "event": plan["event"],
                }
            )
            state = replay(
                events,
                identity=IDENTITY,
                authenticated_commits={row["commit"]: "owner-a" for row in events},
            )
        authority["grants"]["rejected"] = dict(
            operation="RECONCILE_NOT_APPLIED",
            identity=IDENTITY,
            intent_tip=state["tip"],
            intent_operation="native-integrate",
            intent_head="a" * 40,
            kind="DEFINITIVELY_REJECTED",
            source="authenticated:synthetic-rejection",
            quiescent=True,
        )
        request.update(
            operation="RECONCILE_NOT_APPLIED",
            operation_id="native-recovery",
            expected_tip=state["tip"],
            expected_head="f" * 40,
            parameters={"grant": "rejected"},
        )
        collection["head"] = pr["head"]["sha"] = "f" * 40
        pr["body"] = "invalid candidate marker"
        collection["trees"][0]["commit"]["response"]["parents"] = []
        original_collect = native.collect_raw
        native.collect_raw = lambda identity: self.fail("Recovery must not collect reviews or CI")
        enabled[0] = True
        before_recovery_reads = len(calls)
        native.api.request = lambda suffix: (
            {"commit": {"sha": "7" * 40}} if suffix == "/branches/main" else api(suffix)
        )
        host = ProtocolHost(
            native.journal,
            collect=native.observe,
            authority=native.authority,
            merge=lambda **kw: self.fail("Recovery must never merge"),
            collect_recovery=lambda identity: native.observe(identity, recovery=True),
        )
        plan = host.explain(request)
        self.assertEqual(plan["event"]["payload"]["intent_head"], "a" * 40)
        self.assertEqual(plan["event"]["expected_head"], "f" * 40)
        self.assertEqual(plan["event"]["payload"]["coordinates"]["MASTER"], "7" * 40)
        native.api.request = api
        self.assertTrue(
            all(
                not any(part in suffix for part in ("reviews", "comments", "actions/runs"))
                for suffix, _ in calls
            )
        )
        self.assertFalse(
            any("/actions/variables/" in suffix for suffix, _ in calls[before_recovery_reads:])
        )
        # A fresh host can load the accepted profile even when the live variable
        # changed. Only candidate-effect operations need that condition.
        native.load_profile()
        native.collect_raw = original_collect
        with self.assertRaisesRegex(ValueError, "production-trigger"):
            native.observe(IDENTITY)
        enabled[0] = False

        # The real post-merge native collector may run in different seconds.
        collection["head"] = pr["head"]["sha"] = "9" * 40
        pr.update(merged=True, state="closed", body=original_body)
        enabled[0] = True  # Current trigger configuration cannot block journal-only settlement.
        collection["issueComments"][0]["body"] = provider_summary("9" * 40)
        collection["reviewReferences"] = []  # Old mutable provider summary is no longer available.
        collection["preflight"]["active_pull_request"]["reviews"]["items"].append(
            {
                "id": 2,
                "user": {"login": "reviewer"},
                "state": "CHANGES_REQUESTED",
                "commit_id": "9" * 40,
            }
        )
        collection["postMerge"] = copy.deepcopy(collection["ci"])
        post = collection["postMerge"]
        post["head_sha"] = "e" * 40
        for run in post["inventory"][0]["response"]["workflow_runs"]:
            run.update(head_sha="e" * 40, event="push")
        for history in post["histories"]:
            history["attempt"]["response"].update(head_sha="e" * 40, event="push")
            for job_page in history["jobs"]:
                for job in job_page["response"]["jobs"]:
                    job["head_sha"] = "e" * 40
        stamp = (datetime.now(UTC) - timedelta(seconds=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        post["inventory"][0]["observed_at"] = stamp
        request.update(
            operation="RECONCILE",
            operation_id="native-reconcile",
            expected_head="9" * 40,
            parameters={},
        )
        plan = evaluate(state, request, native.observe(IDENTITY), authority)
        events.append({"commit": "4" * 40, "parents": [state["tip"]], "event": plan["event"]})
        state = replay(
            events,
            identity=IDENTITY,
            authenticated_commits={row["commit"]: "owner-a" for row in events},
        )
        self.assertEqual(state["head"], "a" * 40)
        self.assertEqual(state["merge"]["head_sha"], "a" * 40)
        collection["head"] = pr["head"]["sha"] = "8" * 40
        request.update(
            operation="CLOSE",
            operation_id="native-close",
            expected_tip=state["tip"],
            expected_head="8" * 40,
            parameters={"next_action": "Review the next objective", "next_location": "here"},
        )
        first_close = evaluate(state, request, native.observe(IDENTITY), authority)
        post["inventory"][0]["observed_at"] = (datetime.now(UTC) - timedelta(seconds=5)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        second_close = evaluate(state, request, native.observe(IDENTITY), authority)
        self.assertTrue(same_plan(first_close, second_close))
        wrong_merge = native.observe(IDENTITY)
        wrong_merge["merge"]["merge_sha"] = "7" * 40
        with self.assertRaisesRegex(ValueError, "reconciled merge identity"):
            evaluate(state, request, wrong_merge, authority)
        reviews = collection["preflight"]["active_pull_request"]["reviews"]["items"]
        reviews[0]["state"] = "CHANGES_REQUESTED"
        with self.assertRaisesRegex(ValueError, "Post-merge delivery"):
            evaluate(state, request, native.observe(IDENTITY), authority)
        reviews[0]["state"] = "APPROVED"
        retained_gate = state["qualification"]["evidence"][2]
        self.assertEqual(retained_gate["gate"], "REVIEWS")
        self.assertEqual(
            {row["head"] for row in retained_gate["source"]["activity"]["evidence"]}, {"a" * 40}
        )
        post["histories"][0]["jobs"][0]["response"]["jobs"][0]["conclusion"] = "failure"
        post["histories"][0]["attempt"]["response"]["conclusion"] = "failure"
        post["inventory"][0]["response"]["workflow_runs"][0]["conclusion"] = "failure"
        with self.assertRaisesRegex(ValueError, "Post-merge delivery"):
            evaluate(state, request, native.observe(IDENTITY), authority)

    def test_native_gh_transport_has_no_generic_write_or_cross_repository_route(self):
        calls = []
        account = {"id": 19, "login": "synthetic-operator"}
        remote = {"head": "a" * 40, "gate": True, "merged": False}

        def execute(args, **kwargs):
            calls.append((args, kwargs))
            self.assertEqual(kwargs["env"]["GH_TOKEN"], "synthetic-token")
            if args[-1] == "user":
                return SimpleNamespace(returncode=0, stdout=json.dumps(account))
            self.assertEqual(
                args,
                [
                    "gh",
                    "api",
                    "--hostname",
                    "github.com",
                    "--method",
                    "PUT",
                    "repos/example/synthetic/pulls/4/merge",
                    "--input",
                    "-",
                ],
            )
            payload = json.loads(kwargs["input"])
            self.assertEqual(payload, {"sha": "a" * 40, "merge_method": "merge"})
            if remote["head"] != payload["sha"] or not remote["gate"]:
                return SimpleNamespace(returncode=1, stdout="{}")
            remote["merged"] = True
            return SimpleNamespace(
                returncode=0, stdout=json.dumps({"merged": True, "sha": "e" * 40})
            )

        with patch.dict(os.environ, {"GH_TOKEN": "synthetic-token"}):
            api = GitHubCLI(
                "example/synthetic", directory=Path.cwd(), expected_account=account, execute=execute
            )
        with patch.dict(os.environ, {"GH_TOKEN": "other-token"}):
            api.assert_account()
        args = dict(number=4, expected_head="a" * 40)
        for key, value in (("head", "f" * 40), ("gate", False)):
            before = remote[key]
            remote[key] = value
            with (
                self.subTest(key=key),
                self.assertRaisesRegex(ValueError, "reconcile existing intent"),
            ):
                api.merge_pull_request(**args)
            self.assertFalse(remote["merged"])
            remote[key] = before
        self.assertEqual(api.merge_pull_request(**args)["merge_sha"], "e" * 40)
        self.assertTrue(remote["merged"])
        account["id"] = 20
        before = len(calls)
        with self.assertRaisesRegex(ValueError, "account changed"):
            api.merge_pull_request(**args)
        self.assertEqual(len(calls), before + 1)
        before = len(calls)
        for suffix, method in (
            ("/../other", "GET"),
            ("/%2e%2e/other", "GET"),
            ("/issues/4", "PUT"),
            ("/pulls/4/merge", "DELETE"),
        ):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                api.request(
                    suffix, method=method, payload={"sha": "a" * 40, "merge_method": "merge"}
                )
        self.assertEqual(len(calls), before)

    def test_typed_host_never_repeats_uncertain_merge_and_closes_idempotently(self):
        with tempfile.TemporaryDirectory(prefix="protocol-host-") as temporary:
            root = Path(temporary)
            key, directory, remote = root / "key", root / "host", root / "remote.git"

            def run(*args):
                result = subprocess.run(args, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

            run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key))
            run("git", "init", "--bare", "-q", str(remote))
            run("git", "init", "-q", str(directory))
            for name, value in {
                "user.name": "Synthetic",
                "user.email": "synthetic@example.invalid",
                "gpg.format": "ssh",
                "user.signingkey": str(key),
            }.items():
                run("git", "-C", str(directory), "config", name, value)
            run("git", "-C", str(directory), "remote", "add", "origin", str(remote))
            journal = GitJournal(
                directory, IDENTITY, "owner-a " + key.with_suffix(".pub").read_text()
            )
            _state, request, observation, authority = fixture()
            merge_calls = []

            def collect(identity):
                self.assertEqual(identity, IDENTITY)
                fresh = copy.deepcopy(observation)
                fresh["observed_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                return fresh

            def merge(**arguments):
                merge_calls.append(arguments)
                self.assertEqual(arguments["method"], "merge")
                self.assertEqual(arguments["expected_head"], "a" * 40)
                self.assertEqual(arguments["expected_base"], "b" * 40)
                # Model a real remote write whose successful response was lost.
                observation["coordinates"]["PR_STATE"] = "MERGED"
                observation["merge"] = {
                    "merge_sha": "e" * 40,
                    "base_sha": "b" * 40,
                    "head_sha": "a" * 40,
                    "tree_sha": "f" * 40,
                    "parents": ["b" * 40, "a" * 40],
                    "qualified_tree": "f" * 40,
                }
                raise ConnectionError("synthetic interrupted response")

            host = ProtocolHost(
                journal, collect=collect, authority=lambda state: authority, merge=merge
            )
            self.assertEqual(host.explain(request)["event"]["operation"], "START")
            self.assertIsNone(journal.tip())
            host.operate(request)
            request.update(
                operation="QUALIFY", operation_id="operation-qualify", expected_tip=journal.tip()
            )
            host.operate(request)
            request.update(
                operation="INTEGRATE",
                operation_id="operation-integrate",
                expected_tip=journal.tip(),
            )
            with self.assertRaisesRegex(ValueError, "outcome uncertain"):
                host.operate(request)
            self.assertEqual(journal.read()["status"], "INTEGRATING")
            self.assertEqual(host.operate(request)["state"], "RECONCILIATION_REQUIRED")
            self.assertEqual(len(merge_calls), 1)
            request.update(
                operation="RECONCILE",
                operation_id="operation-reconcile",
                expected_tip=journal.tip(),
            )
            host.operate(request)
            observation["post_merge"] = {
                "head": "e" * 40,
                "result": "PASS",
                "complete": True,
                "evidence": ["synthetic:post-merge"],
            }
            request.update(
                operation="CLOSE",
                operation_id="operation-close",
                expected_tip=journal.tip(),
                parameters={
                    "next_action": "Review next objective",
                    "next_location": "new conversation",
                },
            )
            host.operate(request)
            terminal_tip = journal.tip()
            host.collect = lambda identity: self.fail(
                "An exact applied retry must reconcile before API reads"
            )
            host.operate(request)
            self.assertEqual(journal.tip(), terminal_tip)
            self.assertEqual(journal.read()["status"], "CLOSED")
            self.assertEqual(len(journal.read()["events"]), 5)

    def test_signed_cas_idempotence_and_recovery_from_fresh_clone(self):
        with tempfile.TemporaryDirectory(prefix="protocol-journal-") as temporary:
            root = Path(temporary)
            key, repo, remote, restored = (
                root / "synthetic-key",
                root / "host",
                root / "remote.git",
                root / "restored",
            )

            def command(*args):
                result = subprocess.run(args, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return result.stdout.strip()

            command(
                "ssh-keygen",
                "-q",
                "-t",
                "ed25519",
                "-N",
                "",
                "-C",
                "synthetic-test",
                "-f",
                str(key),
            )
            command("git", "init", "--bare", "-q", str(remote))
            command("git", "init", "-q", str(repo))
            command("git", "-C", str(repo), "config", "user.name", "Synthetic Test")
            command("git", "-C", str(repo), "config", "user.email", "synthetic@example.invalid")
            command("git", "-C", str(repo), "config", "gpg.format", "ssh")
            command("git", "-C", str(repo), "config", "user.signingkey", str(key))
            command("git", "-C", str(repo), "remote", "add", "origin", str(remote))
            signers = "owner-a " + key.with_suffix(".pub").read_text()
            host = GitJournal(repo, IDENTITY, signers)
            plan = {"event": start(), "expected_tip": None}
            fresh_plan = copy.deepcopy(plan)
            fresh_plan["event"]["observed_at"] = "2026-01-01T00:00:01Z"
            result = host.commit_plan(plan, refresh_and_plan=lambda state: fresh_plan)
            self.assertEqual(result["state"], "APPLIED_LOCAL")
            first = result["tip"]
            self.assertEqual(
                host.read()["events"][0]["event"]["observed_at"], "2026-01-01T00:00:01Z"
            )
            self.assertEqual(
                host.commit_plan(
                    plan, refresh_and_plan=lambda state: self.fail("Must reconcile first")
                )["state"],
                "ALREADY_APPLIED",
            )
            self.assertEqual(host.publish()["state"], "DURABLE")
            command("git", "clone", "-q", "--no-checkout", str(remote), str(restored))
            fresh = GitJournal(restored, IDENTITY, signers, required_ancestor=first)
            with self.assertRaisesRegex(ValueError, "Known journal missing"):
                fresh.read()
            self.assertEqual(fresh.synchronize()["state"], "RESTORED")
            state = fresh.read()
            self.assertEqual(state["tip"], first)
            self.assertEqual(state["owner"], "owner-a")
            self.assertEqual(state["status"], "ACTIVE")
            second = event(
                "INTERRUPT", 2, {"reason": "host stopped", "material": "artifact:synthetic"}
            )
            second["expected_previous"] = first
            plan2 = {"event": second, "expected_tip": first}
            self.assertEqual(
                host.commit_plan(plan2, refresh_and_plan=lambda state: plan2)["state"],
                "APPLIED_LOCAL",
            )
            stale = copy.deepcopy(plan2)
            stale["event"]["operation_id"] = "concurrent-other"
            with self.assertRaisesRegex(ValueError, "Concurrent"):
                host.commit_plan(stale, refresh_and_plan=lambda state: stale)
            # A hostile event cannot spoof owner-a with a differently registered signer.
            with self.assertRaisesRegex(ValueError, "Actor differs"):
                GitJournal(repo, IDENTITY, signers.replace("owner-a ", "owner-b ")).read()
            self.assertFalse((restored / "synthetic-key").exists())
            self.assertEqual(host.publish()["state"], "DURABLE")
            self.assertEqual(fresh.synchronize()["state"], "RESTORED")
            self.assertEqual(fresh.read()["status"], "INTERRUPTED")
            self.assertEqual(fresh.synchronize()["state"], "CURRENT")
            with self.assertRaisesRegex(ValueError, "recovery anchor"):
                GitJournal(restored, IDENTITY, signers, required_ancestor="f" * 40).read()
            with self.assertRaisesRegex(ValueError, "wildcard"):
                GitJournal(restored, IDENTITY, signers.replace("owner-a ", "* "))
            collision = {**IDENTITY, "branch": "agent-protocol/work/pr-4"}
            with self.assertRaisesRegex(ValueError, "reserved journal namespace"):
                GitJournal(repo, collision, signers)
            # A retained local copy with its original enrollment cannot recreate
            # deleted durable history, including after constructing a fresh host.
            original_git = host.git

            def delete_before_push(*args, **kwargs):
                if args[0] == "push":
                    command("git", "--git-dir", str(remote), "update-ref", "-d", host.ref)
                return original_git(*args, **kwargs)

            host.git = delete_before_push
            with self.assertRaisesRegex(ValueError, "Publication uncertain or concurrent"):
                host.publish()
            host.git = original_git
            for retained in (host, GitJournal(repo, IDENTITY, signers)):
                with self.assertRaisesRegex(ValueError, "remote journal is missing"):
                    retained.publish()
            self.assertEqual(command("git", "--git-dir", str(remote), "for-each-ref", host.ref), "")


if __name__ == "__main__":
    unittest.main()
