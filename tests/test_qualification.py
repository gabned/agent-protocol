import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import copy
import unittest
from datetime import UTC, datetime

from test_lifecycle import fixture

from agent_protocol.ledger import digest
from agent_protocol.qualification import (
    ci_evidence,
    normalize_ci,
    policy_decision,
    verify_protocol_candidate,
    verify_review_activity,
    verify_reviews,
)
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


def protocol_fixture():
    stamp = "2026-01-01T00:00:00Z"
    repo = {"full_name": "example/synthetic", "id": 17}
    head, base, base_tree, head_tree = (c * 40 for c in "abcd")
    pr = {
        "number": 4,
        "head": {"sha": head},
        "base": {"sha": base, "repo": repo},
        "state": "open",
        "draft": False,
        "mergeable": True,
        "commits": 1,
        "changed_files": 1,
        "review_comments": 0,
    }

    def observed(value):
        return {"response": value, "observed_at": stamp}

    def tree_record(commit, parents, tree, entries):
        return {
            "commit": observed(
                {"sha": commit, "parents": [{"sha": p} for p in parents], "tree": {"sha": tree}}
            ),
            "tree": observed({"sha": tree, "truncated": False, "tree": entries}),
        }

    run = {
        "id": 1,
        "repository": repo,
        "head_sha": head,
        "run_attempt": 1,
        "status": "completed",
        "conclusion": "success",
        "path": ".github/workflows/ci.yml",
        "event": "pull_request",
    }
    job = {
        "id": 1,
        "name": "native",
        "head_sha": head,
        "run_id": 1,
        "status": "completed",
        "conclusion": "success",
    }
    collection = {
        "schema": "agent-lifecycle-collection/v2",
        "repository": repo["full_name"],
        "repository_id": 17,
        "pr": 4,
        "head": head,
        "preflight": {
            "repo": observed(repo),
            "default_branch": observed({"commit": {"sha": base}}),
            "active_pull_request": {
                "pr": observed(pr),
                "reviews": {"complete": True, "items": []},
                "threads": {
                    "observed_at": stamp,
                    "status": "OBSERVED",
                    "response": {"complete": True, "threads": []},
                },
            },
        },
        "reviewComments": [],
        "files": [{"filename": "protocol.py"}],
        "commits": [{"sha": head}],
        "base": tree_record(base, [], base_tree, []),
        "trees": [
            tree_record(
                head,
                [base],
                head_tree,
                [{"path": "protocol.py", "type": "blob", "mode": "100644", "sha": "e" * 40}],
            )
        ],
        "final": [observed(pr), observed({"commit": {"sha": base}})],
        "ci": {
            "schema": "agent-work-ci-history/v1",
            "complete": True,
            "repository": repo["full_name"],
            "head_sha": head,
            "inventory": [observed({"total_count": 1, "workflow_runs": [run]})],
            "histories": [
                {
                    "attempt": observed(run),
                    "jobs": [observed({"total_count": 1, "jobs": [job]})],
                }
            ],
        },
    }
    profile = {
        "repository": repo["full_name"],
        "repository_id": 17,
        "source_commit": base,
        "workstream_class": "PROTOCOL",
        "effects": "NO_PRODUCTION",
        "paths": {"protocol.py": "100644"},
        "frozen_paths": [],
        "reviewers": [],
        "review_activity": [],
        "ci": {
            "source_commit": base,
            "required_workflows": [".github/workflows/ci.yml@pull_request"],
        },
    }
    return collection, profile


class QualificationTests(unittest.TestCase):
    def test_provider_review_must_resolve_to_exact_candidate_with_authenticated_author(self):
        stamp = "2026-01-01T00:00:00Z"
        head = "a" * 40
        body = (
            "<!-- codex-pull-request-review-summary -->\n"
            "| **Code Review** | **Completed** | `aaaaaaa` | Manual |\n"
            "| **Security Review** | **Completed** | `aaaaaaa` | Manual |\n"
            '<!-- codex-security-review:v1 {"headSha":"' + head + '",'
            '"repository":"example/synthetic","pullRequestNumber":4,"status":"completed"} -->'
        )
        collection = {
            "repository": "example/synthetic",
            "pr": 4,
            "head": head,
            "preflight": {"active_pull_request": {"pr": {"response": {"comments": 1}}}},
            "issueComments": [{"id": 1, "user": {"id": 123, "type": "Bot"}, "body": body}],
            "reviewReferences": [
                {
                    "url": "https://api.github.com/repos/example/synthetic/commits/aaaaaaa",
                    "status": "OBSERVED",
                    "observed_at": stamp,
                    "response": {"sha": head},
                }
            ],
        }
        requirements = [
            {"provider": "CODEX_SUMMARY_V1", "author_id": 123, "kind": kind}
            for kind in ("CODE", "SECURITY")
        ]
        args = {"now": datetime(2026, 1, 1, tzinfo=UTC)}
        self.assertEqual(verify_review_activity(collection, requirements, **args)["result"], "PASS")
        for attack in ("author", "head", "unfinished"):
            changed = copy.deepcopy(collection)
            if attack == "author":
                changed["issueComments"][0]["user"]["id"] = 124
            elif attack == "head":
                changed["reviewReferences"][0]["response"]["sha"] = "a" * 7 + "b" * 33
            else:
                changed["issueComments"][0]["body"] = body.replace("**Completed**", "**Running**")
            with self.subTest(attack=attack):
                self.assertNotEqual(
                    verify_review_activity(changed, requirements, **args)["result"], "PASS"
                )
        collection["reviewReferences"] = []
        with self.assertRaisesRegex(ValueError, "independently resolved"):
            verify_review_activity(collection, requirements, **args)

    def test_protocol_raw_objects_bind_scope_history_identity_ci_and_reviews(self):
        collection, profile = protocol_fixture()
        args = {
            "accepted_profile": profile,
            "expected_profile_digest": digest(profile),
            "now": datetime(2026, 1, 1, tzinfo=UTC),
        }
        result = verify_protocol_candidate(collection, **args)
        self.assertEqual(result["result"], "PASS")
        self.assertFalse(result["write_authorized"])
        for attack in ("mode", "scope", "parent", "repository", "stale-ci", "endpoint"):
            value = copy.deepcopy(collection)
            if attack == "mode":
                value["trees"][0]["tree"]["response"]["tree"][0]["mode"] = "120000"
            elif attack == "scope":
                value["trees"][0]["tree"]["response"]["tree"][0]["path"] = "unapproved.py"
            elif attack == "parent":
                value["trees"][0]["commit"]["response"]["parents"] = []
            elif attack == "repository":
                value["preflight"]["repo"]["response"]["id"] = 99
            elif attack == "stale-ci":
                value["ci"]["inventory"][0]["observed_at"] = "2025-12-31T00:00:00Z"
            else:
                value["files"][0]["filename"] = "different.py"
            with self.subTest(attack=attack), self.assertRaises(ValueError):
                verify_protocol_candidate(value, **args)

    def test_collector_normalization_rejects_missing_attempts_and_unbound_jobs(self):
        normalized = inventory()
        run = {
            "id": 1,
            "repository": {"full_name": "example/synthetic"},
            "head_sha": "a" * 40,
            "run_attempt": 1,
            "status": "completed",
            "conclusion": "success",
            "path": ".github/workflows/ci.yml",
            "event": "pull_request",
        }
        job = {
            "id": 1,
            "name": "native",
            "head_sha": "a" * 40,
            "run_id": 1,
            "run_attempt": 1,
            "status": "completed",
            "conclusion": "success",
        }
        history = {
            "schema": "agent-work-ci-history/v1",
            "complete": True,
            "head_sha": "a" * 40,
            "repository": "example/synthetic",
            "inventory": [{"response": {"total_count": 1, "workflow_runs": [run]}}],
            "histories": [
                {
                    "attempt": {"response": run},
                    "jobs": [{"response": {"total_count": 1, "jobs": [job]}}],
                }
            ],
        }
        args = {
            "accepted_policy": {
                "source_commit": "b" * 40,
                "required_workflows": normalized["required_workflows"],
            },
            "observed_at": "2026-01-01T00:00:00Z",
        }
        self.assertEqual(normalize_ci(history, **args), normalized)
        for attack in ("attempt", "job", "total"):
            value = copy.deepcopy(history)
            if attack == "attempt":
                value["histories"] = []
            elif attack == "job":
                value["histories"][0]["jobs"][0]["response"]["jobs"][0]["run_id"] = 2
            else:
                value["inventory"][0]["response"]["total_count"] = 2
            with self.subTest(attack=attack), self.assertRaises(ValueError):
                normalize_ci(value, **args)

    def test_comment_cannot_erase_requested_changes_and_thread_completeness_is_independent(self):
        reviews = [
            {
                "id": 1,
                "user": {"login": "reviewer"},
                "state": "CHANGES_REQUESTED",
                "commit_id": "a" * 40,
            },
            {"id": 2, "user": {"login": "reviewer"}, "state": "COMMENTED", "commit_id": "a" * 40},
        ]
        collection = {
            "head": "a" * 40,
            "reviewComments": [{"id": 5}],
            "preflight": {
                "active_pull_request": {
                    "pr": {"response": {"review_comments": 1}},
                    "reviews": {"complete": True, "items": reviews},
                    "threads": {
                        "status": "OBSERVED",
                        "observed_at": "2026-01-01T00:00:00Z",
                        "response": {
                            "complete": True,
                            "threads": [
                                {
                                    "id": "thread",
                                    "is_resolved": True,
                                    "comments": [{"database_id": 5}],
                                }
                            ],
                        },
                    },
                }
            },
        }
        args = {"required_reviewers": ["reviewer"], "now": datetime(2026, 1, 1, tzinfo=UTC)}
        self.assertEqual(verify_reviews(collection, **args)["result"], "FAIL")
        reviews.append(
            {"id": 3, "user": {"login": "reviewer"}, "state": "APPROVED", "commit_id": "a" * 40}
        )
        self.assertEqual(verify_reviews(collection, **args)["result"], "PASS")
        collection["preflight"]["active_pull_request"]["threads"]["response"]["threads"] = []
        with self.assertRaises(ValueError):
            verify_reviews(collection, **args)

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
