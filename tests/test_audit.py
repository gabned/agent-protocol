import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import copy
import unittest
from datetime import UTC, datetime

from test_lifecycle import fixture

from agent_protocol.audit import DIMENSIONS, reconcile
from agent_protocol.ledger import digest, replay
from agent_protocol.lifecycle import evaluate


class AuditTests(unittest.TestCase):
    def test_blocked_consumer_stays_in_denominator_and_pin_alone_is_insufficient(self):
        scope = {
            "schema": "agent-protocol-audit-scope/v2",
            "repositories": [
                {"repository": "example/first", "id": 1, "role": "CONSUMER"},
                {"repository": "example/second", "id": 2, "role": "CONSUMER"},
            ],
        }
        rows = [
            {
                "repository": "example/first",
                "id": 1,
                "revision": "a" * 40,
                "owner": "synthetic",
                "ledger": "synthetic:ledger",
                "evidence": {},
                "dimensions": dict.fromkeys(DIMENSIONS, "NOT_RUN"),
            }
        ]
        args = {"accepted_scope_digest": digest(scope), "release_revision": "a" * 40}
        result = reconcile(scope, rows, **args)
        self.assertEqual(
            (result["rollout"], result["complete"], result["denominator"]), ("PARTIAL", 0, 2)
        )
        rows[0]["dimensions"]["adoption"] = "VERIFIED"
        with self.assertRaises(ValueError):
            reconcile(scope, rows, **args)
        with self.assertRaises(ValueError):
            reconcile(scope, [{**rows[0], "repository": "example/outside"}], **args)
        rows[0]["evidence"] = dict.fromkeys(DIMENSIONS, "x")
        rows[0]["ledger"] = "x"
        with self.assertRaisesRegex(ValueError, "Authenticated ledger host"):
            reconcile(scope, rows, **args)

    def test_completion_replays_history_and_binds_every_delivery_claim(self):
        state, request, obs, authority = fixture()
        identity = state["identity"]
        scope = {
            "schema": "agent-protocol-audit-scope/v2",
            "repositories": [
                {
                    "repository": identity["repository"],
                    "id": identity["repository_id"],
                    "role": "CONSUMER",
                }
            ],
        }
        row = {
            "repository": identity["repository"],
            "id": identity["repository_id"],
            "revision": authority["pin"],
            "owner": "owner-a",
            "ledger": {"repository": identity["repository"], "pr": identity["pr"], "tip": "5" * 40},
            "evidence": {name: {"synthetic_receipt": name} for name in DIMENSIONS},
            "dimensions": dict.fromkeys(DIMENSIONS, "VERIFIED"),
        }
        events = []
        obs["observed_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        for index, operation in enumerate(
            ("START", "QUALIFY", "INTEGRATE", "RECONCILE", "CLOSE"), 1
        ):
            request.update(
                operation=operation,
                operation_id="audit-" + operation.lower(),
                expected_tip=state["tip"],
            )
            if operation == "RECONCILE":
                obs["coordinates"]["PR_STATE"] = "MERGED"
                obs["merge"] = {
                    "merge_sha": "e" * 40,
                    "base_sha": "b" * 40,
                    "head_sha": "a" * 40,
                    "tree_sha": "f" * 40,
                    "parents": ["b" * 40, "a" * 40],
                    "qualified_tree": "f" * 40,
                }
            if operation == "CLOSE":
                obs["post_merge"] = {
                    "head": "e" * 40,
                    "result": "PASS",
                    "complete": True,
                    "evidence": [{"delivery": {k: v for k, v in row.items() if k != "ledger"}}],
                }
                request["parameters"] = {"next_action": "Continue rollout", "next_location": "here"}
            event = evaluate(state, request, obs, authority)["event"]
            events.append(
                {
                    "commit": str(index) * 40,
                    "parents": [state["tip"]] if state["tip"] else [],
                    "event": event,
                }
            )
            state = replay(
                events,
                identity=identity,
                authenticated_commits={e["commit"]: "owner-a" for e in events},
            )
        proof = {
            "rows": events,
            "identity": identity,
            "authenticated_commits": {e["commit"]: "owner-a" for e in events},
        }
        args = {
            "accepted_scope_digest": digest(scope),
            "release_revision": authority["pin"],
            "authenticate_ledger": lambda _: proof,
        }
        self.assertEqual(reconcile(scope, [row], **args)["rollout"], "COMPLETE")
        for field, replacement in (
            ("owner", "impostor"),
            ("revision", "f" * 40),
            ("evidence", dict.fromkeys(DIMENSIONS, "forged")),
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                reconcile(scope, [{**row, field: replacement}], **args)
        incomplete = copy.deepcopy(proof)
        incomplete["rows"].pop(1)
        with self.assertRaises(ValueError):
            reconcile(scope, [row], **{**args, "authenticate_ledger": lambda _: incomplete})
        wrong_signer = copy.deepcopy(proof)
        wrong_signer["authenticated_commits"]["5" * 40] = "impostor"
        with self.assertRaises(ValueError):
            reconcile(scope, [row], **{**args, "authenticate_ledger": lambda _: wrong_signer})


if __name__ == "__main__":
    unittest.main()
