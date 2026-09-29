"""Synthetic policy, compensation and evidence dependency conformance."""

import copy
import json
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from tools import agent_protocol_v1_4_9 as p


def fixture():
    contract = {
        "schema": "agent-policy-contract/v1",
        "repository": "example/project",
        "source_commit": "a" * 40,
        "reference": "accepted-contract",
        "routing": "PRODUCT/v2",
    }
    checkpoint = {
        "owner": "alice",
        "repository": "example/project",
        "pr": 7,
        "branch": "product/example",
        "workstream": "example",
        "workstream_class": "PRODUCT",
        "binding_basis": "b" * 40,
        "checkpoint_basis": "a" * 40,
        "checkpoint_id": "c" * 40,
        "authority": {"deploy": False, "migrate": False, "production": False},
        "level_c_consent": None,
        "state": "BOUND",
        "effect_policy": "NO_PRODUCTION",
        "observed_effects": "NO_PRODUCTION",
    }
    dimensions = {d: d.lower() for d in p.DIMENSIONS}
    dimensions.update(
        HEAD="e" * 40,
        BASE="a" * 40,
        MASTER="a" * 40,
        POLICY="NO_PRODUCTION",
        REPOSITORY="example/project",
        PR_STATE="OPEN",
        PIN=contract["source_commit"],
        AUTHORITY=p.digest(
            {"authority": checkpoint["authority"], "level_c_consent": checkpoint["level_c_consent"]}
        ),
    )
    history = [
        {"commit": head * 40, "parents": [parent * 40], "checkpoint_sha256": p.digest(checkpoint)}
        for head, parent in [("c", "b"), ("d", "c"), ("e", "d")]
    ]
    evidence = {
        "checkpoint": checkpoint,
        "original_checkpoint": copy.deepcopy(checkpoint),
        "repository": "example/project",
        "branch": "product/example",
        "head": "e" * 40,
        "base": "a" * 40,
        "master": "a" * 40,
        "expected_base": "a" * 40,
        "expected_master": "a" * 40,
        "pr": 7,
        "pr_state": "OPEN",
        "viewer": "alice",
        "clean": True,
        "binding": {k: checkpoint[k] for k in p.IDENTITY},
        "history": history,
        "history_complete": True,
        "ancestry": dict.fromkeys(
            ["basis_to_head", "checkpoint_basis_to_head", "base_to_head", "base_to_master"], True
        ),
        "delta": {
            "base": "a" * 40,
            "head": "e" * 40,
            "complete": True,
            "changes": [{"path": "docs/guide.md", "effect": "NO_PRODUCTION"}],
        },
        "events": [
            {"type": "QUALIFICATION", "head": "d" * 40, "result": "FAIL"},
            {"type": "QUALIFICATION", "head": "e" * 40, "result": "FAIL"},
        ],
        "dimensions": dimensions,
        "evidence": [],
        "events_complete": True,
        "observed_at": datetime.now(UTC).isoformat(),
    }
    request = {"operation": "RECOVER_BOUND_POLICY", "owner": "alice", "expected_head": "e" * 40}
    return request, evidence, contract


def plan(request, evidence, contract):
    return p.plan_policy_recovery(
        request=request,
        evidence=evidence,
        trusted_evidence=p.digest(evidence),
        contract=contract,
        trusted_contract=p.digest(contract),
    )


def receipt(gate, dimensions, identity=None):
    deps = sorted(p.MINIMUM_DEPENDENCIES[gate])
    return {
        "id": identity or gate,
        "gate": gate,
        "dependencies": deps,
        "coordinates": {k: dimensions[k] for k in deps},
        "result": "PASS",
    }


class PolicyTests(unittest.TestCase):
    def test_real_git_null_diff_history_and_compensation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def git(*args):
                return subprocess.check_output(["git", "-C", directory, *args]).decode().strip()

            git("init", "-q")
            git("config", "user.name", "Synthetic fixture")
            git("config", "user.email", "fixture@example.invalid")
            git("config", "core.autocrlf", "false")
            file = root / "checkpoint.json"
            file.write_text('{"effect_policy":"NO_PRODUCTION"}\n')
            git("add", ".")
            git("commit", "-qm", "original basis")
            basis = git("rev-parse", "HEAD")
            git("commit", "--allow-empty", "-qm", "BOUND with policy error")
            checkpoint_id = git("rev-parse", "HEAD")
            doc = root / "guide.md"
            doc.write_text("temporary documentation\n")
            git("add", ".")
            git("commit", "-qm", "intermediate documentation; qualification failed")
            failed = git("rev-parse", "HEAD")
            doc.unlink()
            git("add", "-u")
            git("commit", "-qm", "restore final tree; qualification still failed")
            head = git("rev-parse", "HEAD")
            assert git("diff", "--name-only", basis, head) == ""
            request, evidence, contract = fixture()
            checkpoint = evidence["checkpoint"]
            checkpoint.update(
                binding_basis=basis, checkpoint_basis=basis, checkpoint_id=checkpoint_id
            )
            evidence["original_checkpoint"] = copy.deepcopy(checkpoint)
            evidence["binding"] = {k: checkpoint[k] for k in p.IDENTITY}
            evidence.update(
                head=head, base=basis, master=basis, expected_base=basis, expected_master=basis
            )
            evidence["dimensions"].update(HEAD=head, BASE=basis, MASTER=basis)
            request["expected_head"] = head
            commits = git("rev-list", "--reverse", f"{basis}..{head}").splitlines()
            evidence["history"] = [
                {
                    "commit": c,
                    "parents": git("show", "-s", "--format=%P", c).split(),
                    "checkpoint_sha256": p.digest(checkpoint),
                }
                for c in commits
            ]
            for c in commits:
                assert (
                    json.loads(git("show", f"{c}:checkpoint.json"))["effect_policy"]
                    == "NO_PRODUCTION"
                )
            evidence["events"] = [{"head": c, "result": "FAIL"} for c in (failed, head)]
            evidence["delta"] = {"base": basis, "head": head, "complete": True, "changes": []}
            evidence["evidence"] = [receipt("QUALIFICATION", evidence["dimensions"])]
            planned = plan(request, evidence, contract)
            before_history = git("log", "--format=%H:%s", head)
            file.write_text('{"effect_policy":"REPOSITORY_POLICY"}\n')
            git("add", "checkpoint.json")
            git("commit", "-qm", planned["commit_subject"])
            new_head = git("rev-parse", "HEAD")
            assert git("log", "--format=%H:%s", head) == before_history
            assert git("diff", "--name-only", head, new_head) == "checkpoint.json"
            after = copy.deepcopy(checkpoint)
            after["effect_policy"] = json.loads(git("show", f"{new_head}:checkpoint.json"))[
                "effect_policy"
            ]
            compensation = {
                "head": new_head,
                "parents": git("show", "-s", "--format=%P", new_head).split(),
                "subject": git("show", "-s", "--format=%s", new_head),
                "before": checkpoint,
                "after": after,
                "changed_fields": ["effect_policy"],
                "other_changes": [],
                "history_sha256": p.digest(evidence["history"]),
                "events_sha256": p.digest(evidence["events"]),
                "full_effects": "NO_PRODUCTION",
                "observed_at": datetime.now(UTC).isoformat(),
            }
            verified = p.verify_policy_compensation(
                plan=planned,
                trusted_plan=p.digest(planned),
                compensation=compensation,
                trusted_compensation=p.digest(compensation),
                previous_evidence=evidence["evidence"],
                current_dimensions=evidence["dimensions"]
                | {"HEAD": new_head, "POLICY": "REPOSITORY_POLICY"},
            )
            assert verified["evidence"][0]["reuse"] == "STALE_EVIDENCE"
            assert not verified["qualified"] and new_head != head

    def test_coherence_table_and_explain_parity(self):
        for routing, selected, effect, expected in [
            ("PRODUCT/v1", "NO_PRODUCTION", "NO_PRODUCTION", True),
            ("PRODUCT/v1", "REPOSITORY_POLICY", "NO_PRODUCTION", True),
            ("PRODUCT/v1", "NO_PRODUCTION", "PRODUCTION", False),
            ("PRODUCT/v2", "REPOSITORY_POLICY", "NO_PRODUCTION", True),
            ("PRODUCT/v2", "NO_PRODUCTION", "NO_PRODUCTION", False),
            ("PRODUCT/v2", "REPOSITORY_POLICY", "PRODUCTION", True),
            ("PRODUCT/v2", "REPOSITORY_POLICY", "UNKNOWN", False),
            ("PROTOCOL/v1", "NO_PRODUCTION", "NO_PRODUCTION", True),
            ("PROTOCOL/v1", "REPOSITORY_POLICY", "NO_PRODUCTION", False),
            ("PROTOCOL/v1", "NO_PRODUCTION", "PRODUCTION", False),
        ]:
            with self.subTest(routing=routing, selected=selected, effect=effect):
                _, evidence, contract = fixture()
                contract["routing"] = routing
                kwargs = {
                    "contract": contract,
                    "trusted_contract": p.digest(contract),
                    "workstream": "example",
                    "workstream_class": p.ROUTES[routing][0],
                    "selected_policy": selected,
                    "observed_effects": effect,
                    "production_authority": evidence["checkpoint"]["authority"],
                }
                decision = p.resolve_policy(**kwargs)
                self.assertEqual(decision["bind_allowed"], expected)
                self.assertEqual(decision["observed_effects"], effect)
                self.assertEqual(decision["new_capabilities"], [])
                self.assertFalse(any(decision["production_authority"].values()))
                if expected:
                    self.assertEqual(p.require_policy_coherence(**kwargs), decision)
                else:
                    with self.assertRaisesRegex(p.PolicyError, "INPUT_MISMATCH.*expected"):
                        p.require_policy_coherence(**kwargs)

    def test_legacy_route_does_not_invent_a_unique_recovery_policy(self):
        request, evidence, contract = fixture()
        contract["routing"] = "PRODUCT/v1"
        with self.assertRaisesRegex(p.PolicyError, "no allow-listed policy mismatch"):
            plan(request, evidence, contract)

    def test_minimal_recovery_preserves_history_and_identity(self):
        request, evidence, contract = fixture()
        original = copy.deepcopy(evidence)
        result = plan(request, evidence, contract)
        self.assertEqual(evidence, original)
        self.assertEqual(result["diagnostic"], "BOUND_RECOVERABLE")
        corrected = result["corrected_checkpoint"]
        self.assertEqual(corrected["effect_policy"], "REPOSITORY_POLICY")
        self.assertEqual(
            {k for k in corrected if corrected[k] != evidence["checkpoint"][k]}, {"effect_policy"}
        )
        self.assertTrue(result["commit_required"])
        self.assertFalse(result["qualified"])
        self.assertEqual(result["events_sha256"], p.digest(original["events"]))

    def test_all_immutable_fields_rejected(self):
        for field in sorted(p.IDENTITY):
            with self.subTest(field=field):
                request, evidence, contract = fixture()
                evidence["checkpoint"][field] = "altered"
                with self.assertRaises(p.PolicyError):
                    plan(request, evidence, contract)

    def test_terminal_observations_table(self):
        changes = [
            ("viewer", "bob"),
            ("repository", "other/project"),
            ("branch", "wrong"),
            ("pr", 9),
            ("head", "f" * 40),
            ("base", "b" * 40),
            ("master", "b" * 40),
            ("clean", False),
            ("pr_state", "CLOSED"),
            ("history_complete", False),
            ("binding", {}),
            ("history", []),
            ("ancestry", {}),
            ("events", None),
        ]
        for key, value in changes:
            with self.subTest(key=key):
                request, evidence, contract = fixture()
                evidence[key] = value
                with self.assertRaises(p.PolicyError):
                    plan(request, evidence, contract)

    def test_missing_proof_and_delta_damage(self):
        for field in fixture()[1]:
            with self.subTest(missing=field):
                request, evidence, contract = fixture()
                del evidence[field]
                with self.assertRaises(p.PolicyError):
                    plan(request, evidence, contract)
        for key, value in [
            ("complete", False),
            ("head", "f" * 40),
            ("base", "f" * 40),
            ("changes", [{"path": "unknown", "effect": "UNKNOWN"}]),
            ("changes", [{"path": "runtime", "effect": "PRODUCTION"}]),
        ]:
            with self.subTest(delta=key, value=value):
                request, evidence, contract = fixture()
                evidence["delta"][key] = value
                with self.assertRaises(p.PolicyError):
                    plan(request, evidence, contract)

    def test_unknown_operations_and_arbitrary_patch_rejected(self):
        for field in ["patch", "owner_override", "binding_basis", "level_c", "deploy", "migrate"]:
            with self.subTest(field=field):
                request, evidence, contract = fixture()
                request[field] = True
                with self.assertRaises(p.PolicyError):
                    plan(request, evidence, contract)

    def test_history_damage_and_null_final_delta(self):
        for damage in ["gap", "tamper", "missing", "duplicate", "head"]:
            with self.subTest(damage=damage):
                request, evidence, contract = fixture()
                if damage == "gap":
                    evidence["history"][1]["parents"] = []
                elif damage == "tamper":
                    evidence["history"][1]["checkpoint_sha256"] = "f" * 64
                elif damage == "missing":
                    evidence["history"].pop(1)
                elif damage == "duplicate":
                    evidence["history"].insert(1, evidence["history"][0])
                else:
                    evidence["history"].pop()
                with self.assertRaises(p.PolicyError):
                    plan(request, evidence, contract)
        request, evidence, contract = fixture()
        evidence["delta"]["changes"] = []
        result = plan(request, evidence, contract)
        self.assertTrue(result["commit_required"])
        self.assertEqual(result["history_sha256"], p.digest(evidence["history"]))

    def test_complete_merge_dag_and_missing_parent_cycle_or_orphan(self):
        request, evidence, contract = fixture()
        side = {
            "commit": "f" * 40,
            "parents": ["c" * 40],
            "checkpoint_sha256": p.digest(evidence["checkpoint"]),
        }
        evidence["history"].insert(2, side)
        evidence["history"][-1]["parents"].append(side["commit"])
        result = plan(request, evidence, contract)
        assert result["history_sha256"] == p.digest(evidence["history"])
        for damage in ("missing", "cycle", "orphan", "unproved_boundary"):
            with self.subTest(damage=damage):
                altered = copy.deepcopy(evidence)
                if damage == "missing":
                    altered["history"].pop(2)
                elif damage == "cycle":
                    altered["history"][1]["parents"] = [evidence["head"]]
                elif damage == "orphan":
                    altered["history"][-1]["parents"].remove(side["commit"])
                else:
                    altered["history"][-1]["parents"].append("9" * 40)
                with self.assertRaises(p.PolicyError):
                    plan(request, altered, contract)

    def test_compensation_requires_exact_child_and_fresh_gates(self):
        request, evidence, contract = fixture()
        evidence["evidence"] = [
            receipt("QUALIFICATION", evidence["dimensions"]),
            receipt("REPOSITORY_IDENTITY", evidence["dimensions"]),
        ]
        planned = plan(request, evidence, contract)
        compensation = {
            "head": "f" * 40,
            "parents": [evidence["head"]],
            "subject": planned["commit_subject"],
            "before": evidence["checkpoint"],
            "after": planned["corrected_checkpoint"],
            "changed_fields": ["effect_policy"],
            "other_changes": [],
            "history_sha256": planned["history_sha256"],
            "events_sha256": planned["events_sha256"],
            "full_effects": "NO_PRODUCTION",
            "observed_at": datetime.now(UTC).isoformat(),
        }
        current = evidence["dimensions"] | {"HEAD": "f" * 40, "POLICY": "REPOSITORY_POLICY"}
        prior = copy.deepcopy(evidence["evidence"])

        def verify(candidate):
            return p.verify_policy_compensation(
                plan=planned,
                trusted_plan=p.digest(planned),
                compensation=candidate,
                trusted_compensation=p.digest(candidate),
                previous_evidence=prior,
                current_dimensions=current,
            )

        result = verify(compensation)
        self.assertEqual(result["qualification"], "REQUIRED")
        self.assertEqual([r["reuse"] for r in result["evidence"]], ["STALE_EVIDENCE", "REUSABLE"])
        for key, value in [
            ("head", evidence["head"]),
            ("parents", []),
            ("subject", "ordinary"),
            ("after", evidence["checkpoint"]),
            ("other_changes", ["runtime"]),
            ("full_effects", "PRODUCTION"),
            ("history_sha256", "f" * 64),
            ("events_sha256", "f" * 64),
            ("observed_at", "2000-01-01T00:00:00Z"),
        ]:
            with self.subTest(key=key), self.assertRaises(p.PolicyError):
                verify(compensation | {key: value})
        prior.pop()
        with self.assertRaisesRegex(p.PolicyError, "inventory changed or omitted"):
            verify(compensation)
        prior[:] = evidence["evidence"]
        original_plan = copy.deepcopy(planned)
        for key in sorted(p.IDENTITY | {"state", "observed_effects"}):
            with self.subTest(planned_immutable=key):
                planned.clear()
                planned.update(copy.deepcopy(original_plan))
                planned["corrected_checkpoint"][key] = "altered"
                planned["plan_sha256"] = p.digest(
                    {k: v for k, v in planned.items() if k not in {"plan_sha256", "commit_subject"}}
                )
                planned["commit_subject"] = "Protocol policy compensation " + planned["plan_sha256"]
                forged = compensation | {
                    "after": planned["corrected_checkpoint"],
                    "subject": planned["commit_subject"],
                }
                with self.assertRaisesRegex(p.PolicyError, "immutable fields or effects"):
                    verify(forged)

    def test_freshness_all_dimensions_and_independent_reuse(self):
        _, evidence, _ = fixture()
        current = evidence["dimensions"]
        prior = [receipt(gate, current) for gate in p.MINIMUM_DEPENDENCIES]
        for dimension in p.DIMENSIONS:
            with self.subTest(dimension=dimension):
                result = p.evidence_freshness(prior, current | {dimension: "changed"})
                for original, row in zip(prior, result, strict=True):
                    self.assertEqual(
                        row["reuse"] == "STALE_EVIDENCE", dimension in original["dependencies"]
                    )
                    self.assertEqual(row["result"], original["result"])
        prior[0]["result"] = "FAIL"
        self.assertEqual(p.evidence_freshness(prior, current)[0]["result"], "FAIL")

    def test_missing_head_dependency_cannot_preserve_gate(self):
        _, evidence, _ = fixture()
        row = receipt("QUALIFICATION", evidence["dimensions"])
        row["dependencies"].remove("HEAD")
        del row["coordinates"]["HEAD"]
        with self.assertRaisesRegex(p.PolicyError, "STALE_EVIDENCE"):
            p.evidence_freshness([row], evidence["dimensions"])

    def test_identical_unknown_coordinates_never_prove_reuse(self):
        _, evidence, _ = fixture()
        for unknown in (None, "UNKNOWN", "UNAVAILABLE", "UNBOUND", "", {}, False):
            current = evidence["dimensions"] | {"HEAD": unknown}
            row = receipt("QUALIFICATION", current)
            result = p.evidence_freshness([row], current)
            assert result[0]["reuse"] == "STALE_EVIDENCE"
            assert result[0]["invalidators"] == ["HEAD"]


if __name__ == "__main__":
    unittest.main()
