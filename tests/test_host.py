import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import copy
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime

from test_ledger import IDENTITY, event, start
from test_lifecycle import fixture

from agent_protocol.host import GitJournal, ProtocolHost


class SignedJournalTests(unittest.TestCase):
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
