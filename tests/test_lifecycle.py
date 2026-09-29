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
