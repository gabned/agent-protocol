import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import unittest

from agent_protocol.audit import DIMENSIONS, reconcile
from agent_protocol.ledger import digest


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


if __name__ == "__main__":
    unittest.main()
