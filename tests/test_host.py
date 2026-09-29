import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import copy
import subprocess
import tempfile
import unittest

from test_ledger import IDENTITY, event, start

from agent_protocol.host import GitJournal


class SignedJournalTests(unittest.TestCase):
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
            result = host.commit_plan(plan, refresh_and_plan=lambda state: plan)
            self.assertEqual(result["state"], "APPLIED_LOCAL")
            first = result["tip"]
            self.assertEqual(
                host.commit_plan(
                    plan, refresh_and_plan=lambda state: self.fail("Must reconcile first")
                )["state"],
                "ALREADY_APPLIED",
            )
            self.assertEqual(host.publish()["state"], "DURABLE")
            command("git", "clone", "-q", "--no-checkout", str(remote), str(restored))
            fresh = GitJournal(restored, IDENTITY, signers)
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


if __name__ == "__main__":
    unittest.main()
