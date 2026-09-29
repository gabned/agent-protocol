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
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

from test_ledger import IDENTITY, event, start
from test_lifecycle import fixture
from test_qualification import protocol_fixture

from agent_protocol.host import GitHubCLI, GitJournal, NativeGitHubHost, ProtocolHost
from agent_protocol.ledger import digest


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
        pr = collection["preflight"]["active_pull_request"]["pr"]["response"]
        pr["head"].update(ref=IDENTITY["branch"], repo={"id": 17})
        pr["base"].update(ref="main", repo={"id": 17, "full_name": IDENTITY["repository"]})
        pr["merge_commit_sha"] = "e" * 40
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
            "reviewers": [],
            "review_activity": [],
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

        def atomic(**kwargs):
            mutations.append(kwargs)
            return {"state": "REFS_UPDATED_RECONCILIATION_REQUIRED"}

        native = NativeGitHubHost.__new__(NativeGitHubHost)
        native.identity = IDENTITY
        native.binding = {
            "authority": authority,
            "profile_revision": "b" * 40,
            "profile_path": ".github/agent-protocol/host.json",
            "profile_blob": profile_blob,
            "account": {"id": 19, "login": "synthetic-operator"},
        }
        native.api = SimpleNamespace(request=api, assert_account=lambda: None, atomic_merge=atomic)
        native.source_receipt = {"result": "BYTES_VERIFIED", "revision": authority["pin"]}
        native.journal = SimpleNamespace(read=lambda: state)
        native.collect_raw = lambda identity: copy.deepcopy(collection)
        native.profile = native.load_profile()
        first, second = native.observe(IDENTITY), native.observe(IDENTITY)
        self.assertEqual(first["gates"], second["gates"])
        self.assertEqual(
            {g["gate"] for g in first["gates"]}, set(authority["policy"]["required_gates"])
        )
        self.assertTrue(all(g["result"] == "PASS" for g in first["gates"]))
        self.assertEqual(first["coordinates"]["POLICY"], digest(authority["policy"]))
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
            read=lambda: {
                "status": "INTEGRATING",
                "head": "a" * 40,
                "coordinates": {"BASE": "b" * 40},
                "tip": "c" * 40,
            }
        )
        self.assertEqual(native.merge(**args)["state"], "REFS_UPDATED_RECONCILIATION_REQUIRED")
        self.assertEqual(mutations[0]["expected_base"], "b" * 40)
        self.assertEqual(mutations[0]["expected_head"], "a" * 40)
        for route, replacement in (
            ("/rules/branches/main", [{"type": "pull_request"}]),
            ("/branches/main", {"commit": {"sha": "b" * 40}, "protected": True}),
            (
                "/git/commits/" + "e" * 40,
                {"parents": [{"sha": "0" * 40}], "tree": {"sha": "f" * 40}},
            ),
        ):
            native.api.request = lambda suffix, route=route, replacement=replacement: (
                replacement if suffix == route else api(suffix)
            )
            with self.subTest(route=route), self.assertRaises(ValueError):
                native.merge(**args)
        native.api.request = api
        count = len(mutations)
        enabled[0] = True
        with self.assertRaisesRegex(ValueError, "production-trigger"):
            native.merge(**args)
        self.assertEqual(len(mutations), count)

    def test_native_gh_transport_has_no_generic_write_or_cross_repository_route(self):
        calls = []
        account = {"id": 19, "login": "synthetic-operator"}
        remote = {"refs/heads/main": "b" * 40, "refs/heads/candidate": "a" * 40}

        def execute(args, **kwargs):
            calls.append((args, kwargs))
            self.assertEqual(kwargs["env"]["GH_TOKEN"], "synthetic-token")
            if args[-1] == "user":
                return SimpleNamespace(returncode=0, stdout=json.dumps(account))
            payload = json.loads(kwargs["input"])["variables"]["input"]
            updates = payload["refUpdates"]
            self.assertTrue(all(row["force"] is False for row in updates))
            if any(remote[row["name"]] != row["beforeOid"] for row in updates):
                return SimpleNamespace(
                    returncode=0, stdout='{"errors":[{"message":"reference changed"}]}'
                )
            remote.update({row["name"]: row["afterOid"] for row in updates})
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {"data": {"updateRefs": {"clientMutationId": payload["clientMutationId"]}}}
                ),
            )

        with patch.dict(os.environ, {"GH_TOKEN": "synthetic-token"}):
            api = GitHubCLI(
                "example/synthetic", directory=Path.cwd(), expected_account=account, execute=execute
            )
        # Ambient auth switch cannot replace the enrolled transport's credential.
        with patch.dict(os.environ, {"GH_TOKEN": "other-token"}):
            api.assert_account()
        args = dict(
            repository_node_id="synthetic-node",
            base_ref="refs/heads/main",
            head_ref="refs/heads/candidate",
            expected_base="b" * 40,
            expected_head="a" * 40,
            merge_sha="e" * 40,
            intent_id="c" * 40,
        )
        for ref in remote:
            original = remote[ref]
            remote[ref] = "f" * 40
            before = dict(remote)
            with (
                self.subTest(ref=ref),
                self.assertRaisesRegex(ValueError, "reconcile existing intent"),
            ):
                api.atomic_merge(**args)
            self.assertEqual(remote, before)
            remote[ref] = original
        self.assertEqual(api.atomic_merge(**args)["merge_sha"], "e" * 40)
        self.assertEqual(remote, {"refs/heads/main": "e" * 40, "refs/heads/candidate": "a" * 40})
        account["id"] = 20
        before = len(calls)
        with self.assertRaisesRegex(ValueError, "account changed"):
            api.atomic_merge(**args)
        self.assertEqual(len(calls), before + 1)  # Only authentication read, no mutation.
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


if __name__ == "__main__":
    unittest.main()
