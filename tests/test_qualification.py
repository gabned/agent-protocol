import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import copy
import unittest
from datetime import UTC, datetime

from test_lifecycle import fixture

from agent_protocol.qualification import ci_evidence, policy_decision
from agent_protocol.source import legacy


def inventory():
    return {
        "repository": "example/synthetic",
        "head_sha": "a" * 40,
        "source": "GITHUB_CONNECTOR",
        "observed_at": "2026-01-01T00:00:00Z",
        "applicability": "REQUIRED",
        "policy_ref": "b" * 40,
        "required_workflows": [".github/workflows/ci.yml@pull_request"],
        "runs_complete": True,
        "runs": [
            {
                "run_id": 1,
                "workflow": ".github/workflows/ci.yml",
                "event": "pull_request",
                "head_sha": "a" * 40,
                "latest_attempt": 1,
                "attempts": [
                    {
                        "run_attempt": 1,
                        "status": "COMPLETED",
                        "conclusion": "SUCCESS",
                        "jobs_complete": True,
                        "jobs": [
                            {
                                "id": 1,
                                "name": "native",
                                "status": "COMPLETED",
                                "conclusion": "SUCCESS",
                            }
                        ],
                    }
                ],
            }
        ],
    }


class QualificationTests(unittest.TestCase):
    def verify(self, value):
        return ci_evidence(
            value,
            repository="example/synthetic",
            head="a" * 40,
            accepted_policy={
                "source_commit": "b" * 40,
                "required_workflows": [".github/workflows/ci.yml@pull_request"],
            },
            now=datetime(2026, 1, 1, tzinfo=UTC),
        )

    def test_ci_history_and_native_policy_cannot_be_replaced(self):
        self.assertEqual(self.verify(inventory())["result"], "PASS")
        for attack in ("policy", "head", "attempt", "jobs", "page", "omitted", "skipped"):
            value = inventory()
            if attack == "policy":
                value["required_workflows"] = []
            elif attack == "head":
                value["runs"][0]["head_sha"] = "f" * 40
            elif attack == "attempt":
                value["runs"][0]["latest_attempt"] = 2
            elif attack == "jobs":
                value["runs"][0]["attempts"][0]["jobs_complete"] = False
            elif attack == "page":
                value["runs_complete"] = False
            elif attack == "omitted":
                value["runs"] = []
            else:
                value["applicability"] = "NOT_APPLICABLE"
            with self.subTest(attack=attack), self.assertRaises(ValueError):
                self.verify(value)

    def test_failed_attempt_is_retained_after_real_success(self):
        value = inventory()
        run = value["runs"][0]
        failed = copy.deepcopy(run["attempts"][0])
        failed.update(conclusion="FAILURE")
        failed["jobs"][0]["conclusion"] = "FAILURE"
        run["attempts"] = [failed]
        self.assertEqual(self.verify(value)["result"], "FAIL")
        success = inventory()["runs"][0]["attempts"][0]
        success["run_attempt"] = 2
        success["jobs"][0]["id"] = 2
        run["attempts"].append(success)
        run["latest_attempt"] = 2
        result = self.verify(value)
        self.assertEqual(result["result"], "PASS")
        self.assertEqual(result["inventory"]["runs"][0]["attempts"][0]["conclusion"], "FAILURE")

    def test_product_policy_is_preserved_and_resolved_before_binding(self):
        state, _, _, authority = fixture()
        policy = authority["policy"]
        identity = {**state["identity"], "workstream_class": "PRODUCT"}
        policy["contract"]["routing"] = "PRODUCT/v2"
        policy["contract_digest"] = legacy("agent_protocol_v1_4_9").digest(policy["contract"])
        with self.assertRaises(ValueError):
            policy_decision(policy, identity, "NO_PRODUCTION", authority["capabilities"])
        policy["selected"] = "REPOSITORY_POLICY"
        result = policy_decision(policy, identity, "NO_PRODUCTION", authority["capabilities"])
        self.assertTrue(result["allowed"])
        self.assertEqual(result["new_capabilities"], [])


if __name__ == "__main__":
    unittest.main()
