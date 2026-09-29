import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import copy
import unittest
from datetime import UTC, datetime

from test_ledger import IDENTITY

from agent_protocol.ledger import digest, replay
from agent_protocol.lifecycle import COORDINATES, DEPENDENCIES, evaluate, freshness
from agent_protocol.source import legacy

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def fixture():
    state = replay([], identity=IDENTITY, authenticated_commits={})
    authority = {
        "identity": IDENTITY,
        "principal": "owner-a",
        "operations": [
            "START",
            "QUALIFY",
            "REFRESH",
            "INTERRUPT",
            "RESUME",
            "INTEGRATE",
            "RECONCILE",
            "CLOSE",
        ],
        "capabilities": {"production": False, "deploy": False, "migrate": False},
        "policy": {
            "contract": {
                "schema": "agent-policy-contract/v1",
                "repository": IDENTITY["repository"],
                "source_commit": "d" * 40,
                "reference": "synthetic/contract.md",
                "routing": "PROTOCOL/v1",
            },
            "contract_digest": None,
            "selected": "NO_PRODUCTION",
            "required_gates": ["CI", "EFFECTS"],
        },
        "pin": "d" * 40,
        "grants": {},
        "signer_registry": "accepted-signers:synthetic",
    }
    authority["policy"]["contract_digest"] = legacy("agent_protocol_v1_4_9").digest(
        authority["policy"]["contract"]
    )
    coords = dict.fromkeys(COORDINATES, "synthetic")
    coords.update(
        HEAD="a" * 40,
        BASE="b" * 40,
        MASTER="b" * 40,
        PIN=authority["pin"],
        PR_STATE="OPEN",
        POLICY=digest(authority["policy"]),
        REPOSITORY=digest(IDENTITY),
        AUTHORITY=digest(
            {
                k: authority[k]
                for k in ("identity", "principal", "operations", "capabilities", "signer_registry")
            }
        ),
    )
    gates = [
        {
            "id": name.lower(),
            "gate": name,
            "dependencies": sorted(DEPENDENCIES[name]),
            "coordinates": {k: coords[k] for k in DEPENDENCIES[name]},
            "result": "PASS",
            "source": "authenticated:synthetic",
        }
        for name in ["CI", "EFFECTS"]
    ]
    observation = {
        "identity": IDENTITY,
        "head": coords["HEAD"],
        "coordinates": coords,
        "observed_at": "2026-01-01T00:00:00Z",
        "effects": "NO_PRODUCTION",
        "gates": gates,
        "history": {"source": "authenticated:synthetic"},
        "material": {"restored": True, "source": "artifact:synthetic"},
        "merge": None,
        "post_merge": None,
    }
    request = {
        "operation": "START",
        "operation_id": "operation-start",
        "expected_tip": None,
        "expected_head": coords["HEAD"],
        "parameters": {},
    }
    return state, request, observation, authority


class PreconditionsTests(unittest.TestCase):
    def evaluate(self, state, request, observation, authority):
        return evaluate(state, request, observation, authority, now=NOW)

    def test_non_execution_requires_exact_quiescent_host_proof_and_retains_history(self):
        state, request, obs, auth = fixture()
        auth["operations"].append("RECONCILE_NOT_APPLIED")
        obs["coordinates"]["AUTHORITY"] = digest(
            {
                k: auth[k]
                for k in ("identity", "principal", "operations", "capabilities", "signer_registry")
            }
        )
        events = []
        for index, operation in enumerate(["START", "QUALIFY", "INTEGRATE"], 1):
            request.update(
                operation=operation,
                operation_id="recovery-" + operation.lower(),
                expected_tip=state["tip"],
            )
            plan = self.evaluate(state, request, obs, auth)
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
                authenticated_commits={e["commit"]: "owner-a" for e in events},
            )
        request.update(
            operation="RECONCILE_NOT_APPLIED",
            operation_id="recovery-not-applied",
            expected_tip=state["tip"],
            parameters={"grant": "host-refusal"},
        )
        proof = {
            "operation": "RECONCILE_NOT_APPLIED",
            "identity": IDENTITY,
            "intent_tip": state["tip"],
            "intent_operation": "recovery-integrate",
            "intent_head": "a" * 40,
            "kind": "DEFINITIVELY_REJECTED",
            "source": "authenticated:api-rejection",
            "quiescent": True,
        }
        for change in ({"kind": "TIMEOUT"}, {"intent_tip": "f" * 40}, {"quiescent": False}):
            auth["grants"]["host-refusal"] = {**proof, **change}
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.evaluate(state, request, obs, auth)
        auth["grants"]["host-refusal"] = proof
        plan = self.evaluate(state, request, obs, auth)
        events.append({"commit": "4" * 40, "parents": [state["tip"]], "event": plan["event"]})
        state = replay(
            events,
            identity=IDENTITY,
            authenticated_commits={e["commit"]: "owner-a" for e in events},
        )
        self.assertEqual(state["status"], "ACTIVE")
        self.assertIsNone(state["qualification"])
        self.assertEqual(len(state["events"]), 4)
        self.assertEqual(self.evaluate(state, request, obs, auth), plan)
        request.update(
            operation="QUALIFY",
            operation_id="recovery-unchanged",
            expected_tip=state["tip"],
            parameters={},
        )
        with self.assertRaisesRegex(ValueError, "Unchanged deterministic"):
            self.evaluate(state, request, obs, auth)

    def test_exact_retry_reconciles_before_freshness_or_terminal_state(self):
        state, request, obs, auth = fixture()
        plan = self.evaluate(state, request, obs, auth)
        state = replay(
            [{"commit": "1" * 40, "parents": [], "event": plan["event"]}],
            identity=IDENTITY,
            authenticated_commits={"1" * 40: "owner-a"},
        )
        self.assertEqual(self.evaluate(state, request, {}, auth), plan)
        request["parameters"]["force"] = True
        with self.assertRaisesRegex(ValueError, "different request"):
            self.evaluate(state, request, {}, auth)

    def test_rejected_integration_recovers_moved_head_and_closed_pr_without_rewriting_intent(self):
        for pr_state in ("OPEN", "CLOSED"):
            with self.subTest(pr_state=pr_state):
                state, request, obs, auth = fixture()
                auth["operations"] += ["RECONCILE_NOT_APPLIED", "ABANDON"]
                obs["coordinates"]["AUTHORITY"] = digest(
                    {
                        k: auth[k]
                        for k in (
                            "identity",
                            "principal",
                            "operations",
                            "capabilities",
                            "signer_registry",
                        )
                    }
                )
                events = []

                def append(
                    operation,
                    index,
                    parameters=None,
                    *,
                    request=request,
                    obs=obs,
                    auth=auth,
                    events=events,
                ):
                    nonlocal state
                    request.update(
                        operation=operation,
                        operation_id="moved-" + operation.lower(),
                        expected_tip=state["tip"],
                        expected_head=obs["head"],
                        parameters=parameters or {},
                    )
                    plan = self.evaluate(state, request, obs, auth)
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
                        authenticated_commits={e["commit"]: "owner-a" for e in events},
                    )
                    return plan

                for index, operation in enumerate(("START", "QUALIFY", "INTEGRATE"), 1):
                    append(operation, index)
                original = copy.deepcopy(state["events"][2])
                auth["grants"]["rejected"] = {
                    "operation": "RECONCILE_NOT_APPLIED",
                    "identity": IDENTITY,
                    "intent_tip": state["tip"],
                    "intent_operation": "moved-integrate",
                    "intent_head": "a" * 40,
                    "kind": "DEFINITIVELY_REJECTED",
                    "source": "authenticated:atomic-ref-rejection",
                    "quiescent": True,
                }
                obs["head"] = obs["coordinates"]["HEAD"] = "f" * 40
                obs["coordinates"]["PR_STATE"] = pr_state
                plan = append("RECONCILE_NOT_APPLIED", 4, {"grant": "rejected"})
                self.assertEqual(state["head"], "f" * 40)
                self.assertEqual(state["status"], "ACTIVE")
                self.assertIsNone(state["qualification"])
                self.assertEqual(state["events"][2], original)
                self.assertEqual(self.evaluate(state, request, {}, auth), plan)
                if pr_state == "CLOSED":
                    auth["grants"]["abandon"] = {
                        "operation": "ABANDON",
                        "identity": IDENTITY,
                        "owner": "owner-a",
                        "tip": state["tip"],
                        "head": state["head"],
                        "observed_head": obs["head"],
                    }
                    append(
                        "ABANDON", 5, {"reason": "Closed without integration", "grant": "abandon"}
                    )
                    self.assertEqual(state["status"], "ABANDONED")

    def test_start_qualify_integration_reconciliation_close(self):
        state, request, obs, authority = fixture()
        events = []
        for index, operation in enumerate(
            ["START", "QUALIFY", "INTEGRATE", "RECONCILE", "CLOSE"], 1
        ):
            request.update(
                operation=operation,
                operation_id="operation-" + operation.lower(),
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
                    "evidence": ["authenticated:post-merge"],
                }
                request["parameters"] = {
                    "next_action": "Review proposed next objective",
                    "next_location": "new conversation",
                }
            plan = self.evaluate(state, request, obs, authority)
            events.append(
                {
                    "commit": str(index) * 40,
                    "parents": [state["tip"]] if state["tip"] else [],
                    "event": copy.deepcopy(plan["event"]),
                }
            )
            state = replay(
                events,
                identity=IDENTITY,
                authenticated_commits={e["commit"]: "owner-a" for e in events},
            )
        self.assertEqual(state["status"], "CLOSED")
        self.assertEqual(len(state["events"]), 5)

    def test_closed_moved_head_can_be_abandoned_only_with_exact_observed_head_grant(self):
        for previous_status in ("ACTIVE", "QUALIFIED", "INTERRUPTED"):
            state, request, obs, auth = fixture()
            auth["operations"].append("ABANDON")
            obs["coordinates"]["AUTHORITY"] = digest(
                {
                    k: auth[k]
                    for k in (
                        "identity",
                        "principal",
                        "operations",
                        "capabilities",
                        "signer_registry",
                    )
                }
            )
            events = []
            operations = ["START"] + (
                {"ACTIVE": [], "QUALIFIED": ["QUALIFY"], "INTERRUPTED": ["INTERRUPT"]}[
                    previous_status
                ]
            )
            for index, operation in enumerate(operations, 1):
                request.update(
                    operation=operation,
                    operation_id="closed-" + operation.lower(),
                    expected_tip=state["tip"],
                    parameters={"reason": "stop"} if operation == "INTERRUPT" else {},
                )
                plan = self.evaluate(state, request, obs, auth)
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
                    authenticated_commits={r["commit"]: "owner-a" for r in events},
                )
            self.assertEqual(state["status"], previous_status)
            obs["head"] = obs["coordinates"]["HEAD"] = "f" * 40
            obs["coordinates"]["PR_STATE"] = "CLOSED"
            request.update(
                operation="ABANDON",
                operation_id="closed-abandon",
                expected_tip=state["tip"],
                expected_head="f" * 40,
                parameters={"reason": "Authorized closure", "grant": "cancel"},
            )
            grant = {
                "operation": "ABANDON",
                "identity": IDENTITY,
                "owner": "owner-a",
                "tip": state["tip"],
                "head": "a" * 40,
                "observed_head": "f" * 40,
            }
            auth["grants"]["cancel"] = {**grant, "observed_head": "a" * 40}
            with self.assertRaisesRegex(ValueError, "abandonment authority"):
                self.evaluate(state, request, obs, auth)
            auth["grants"]["cancel"] = grant
            plan = self.evaluate(state, request, obs, auth)
            events.append({"commit": "3" * 40, "parents": [state["tip"]], "event": plan["event"]})
            final = replay(
                events,
                identity=IDENTITY,
                authenticated_commits={r["commit"]: "owner-a" for r in events},
            )
            self.assertEqual(final["status"], "ABANDONED")
            self.assertEqual(final["head"], "f" * 40)
            self.assertEqual(final["events"][:-1], state["events"])
            self.assertEqual(self.evaluate(final, request, {}, auth), plan)

    def test_candidate_cannot_override_authority_identity_head_or_effects(self):
        for kind in ["head", "owner", "repository", "effects", "escalation", "stale", "extra"]:
            state, request, obs, auth = fixture()
            if kind == "head":
                request["expected_head"] = "f" * 40
            elif kind == "owner":
                auth["principal"] = "other"
            elif kind == "repository":
                obs["identity"] = {**IDENTITY, "repository_id": 99}
            elif kind == "effects":
                obs["effects"] = "UNKNOWN"
            elif kind == "escalation":
                auth["capabilities"]["deploy"] = True
            elif kind == "stale":
                obs["observed_at"] = "2025-12-31T23:00:00Z"
            else:
                request["parameters"] = {"force": True}
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.evaluate(state, request, obs, auth)

    def test_selective_dependency_invalidation_never_changes_original_result(self):
        _, _, obs, _ = fixture()
        evidence = obs["gates"][0]
        evidence["result"] = "FAIL"
        for key in COORDINATES:
            current = copy.deepcopy(obs["coordinates"])
            current[key] = (
                "f" * 40
                if key in {"HEAD", "BASE", "MASTER", "PIN"}
                else "CLOSED"
                if key == "PR_STATE"
                else "changed"
            )
            result = freshness(evidence, current)
            self.assertEqual(result["result"], "FAIL")
            self.assertEqual(
                result["state"], "STALE_EVIDENCE" if key in DEPENDENCIES["CI"] else "REUSABLE"
            )
        evidence["dependencies"].remove("RUNTIME")
        with self.assertRaisesRegex(ValueError, "dependency omitted"):
            freshness(evidence, obs["coordinates"])


if __name__ == "__main__":
    unittest.main()
