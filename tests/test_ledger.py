import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import copy
import unittest

from agent_protocol.ledger import replay

IDENTITY = {
    "repository": "example/synthetic",
    "repository_id": 17,
    "pr": 4,
    "branch": "work/example",
    "workstream": "synthetic",
    "workstream_class": "PROTOCOL",
    "origin_owner": "owner-a",
}


def event(operation, index, payload, actor="owner-a"):
    return {
        "schema": "agent-lifecycle-event/v2",
        "operation_id": "synthetic-" + str(index),
        "request_sha256": "f" * 64,
        "operation": operation,
        "actor": actor,
        "expected_previous": str(index - 1) * 40 if index > 1 else None,
        "expected_head": "a" * 40,
        "observed_at": "2026-01-01T00:00:00Z",
        "payload": payload,
    }


def rows(events):
    return [
        {"commit": str(i) * 40, "parents": [str(i - 1) * 40] if i > 1 else [], "event": e}
        for i, e in enumerate(events, 1)
    ]


def start():
    return event(
        "START",
        1,
        {
            "identity": copy.deepcopy(IDENTITY),
            "coordinates": {"HEAD": "a" * 40},
            "policy": "NO_PRODUCTION",
            "capabilities": {"deploy": False},
        },
    )


class ReplayTests(unittest.TestCase):
    def verify(self, events, signers=None):
        data = rows(events)
        return replay(
            data,
            identity=IDENTITY,
            authenticated_commits=signers or {r["commit"]: r["event"]["actor"] for r in data},
        )

    def test_interrupted_owner_resume_preserves_origin_and_events(self):
        events = [
            start(),
            event("INTERRUPT", 2, {"reason": "host stopped", "material": "artifact:synthetic"}),
            event("RESUME", 3, {"restoration": "restored:synthetic"}),
        ]
        state = self.verify(events)
        self.assertEqual(state["status"], "ACTIVE")
        self.assertEqual(state["owner"], IDENTITY["origin_owner"])
        self.assertEqual(len(state["events"]), 3)

    def test_handoff_is_distinct_from_same_owner_resume(self):
        events = [
            start(),
            event("INTERRUPT", 2, {"reason": "handoff", "material": "artifact:synthetic"}),
            event(
                "HANDOFF",
                3,
                {
                    "new_owner": "owner-b",
                    "authorization": "grant:synthetic",
                    "material": "artifact:synthetic",
                },
            ),
            event("RESUME", 4, {"restoration": "restored:synthetic"}, actor="owner-b"),
        ]
        state = self.verify(events)
        self.assertEqual(state["owner"], "owner-b")
        self.assertEqual(state["identity"]["origin_owner"], "owner-a")
        events[-1]["actor"] = "owner-a"
        with self.assertRaisesRegex(ValueError, "current authenticated owner"):
            self.verify(events)

    def test_signature_identity_and_complete_ancestry_required(self):
        events = [
            start(),
            event("INTERRUPT", 2, {"reason": "pause", "material": "artifact:synthetic"}),
        ]
        for mutation in ("wrong-signer", "missing-row", "extra-parent", "altered-origin"):
            with self.subTest(mutation=mutation):
                data = rows(copy.deepcopy(events))
                signers = {r["commit"]: "owner-a" for r in data}
                if mutation == "wrong-signer":
                    signers["1" * 40] = "attacker"
                elif mutation == "missing-row":
                    data.pop(0)
                    signers.pop("1" * 40)
                elif mutation == "extra-parent":
                    data[-1]["parents"].append("f" * 40)
                else:
                    data[0]["event"]["payload"]["identity"]["pr"] = 5
                with self.assertRaises(ValueError):
                    replay(data, identity=IDENTITY, authenticated_commits=signers)

    def test_failed_qualification_is_retained_and_cannot_integrate(self):
        events = [
            start(),
            event(
                "QUALIFY",
                2,
                {
                    "result": "FAIL",
                    "coordinates": {"HEAD": "a" * 40},
                    "evidence": ["failed:synthetic"],
                },
            ),
        ]
        state = self.verify(events)
        self.assertEqual(state["events"][-1]["event"]["payload"]["result"], "FAIL")
        events.append(
            event(
                "INTEGRATE",
                3,
                {"qualification_operation": "synthetic-2", "expected_base": "b" * 40},
            )
        )
        with self.assertRaisesRegex(ValueError, "qualification required"):
            self.verify(events)

    def test_terminal_state_is_never_reopened_and_operations_never_duplicated(self):
        events = [
            start(),
            event(
                "ABANDON",
                2,
                {
                    "reason": "authorized cancellation",
                    "material": "artifact:synthetic",
                    "authorization": "grant:synthetic",
                },
            ),
        ]
        self.assertEqual(self.verify(events)["status"], "ABANDONED")
        events.append(event("RESUME", 3, {"restoration": "restored:synthetic"}))
        with self.assertRaisesRegex(ValueError, "Terminal"):
            self.verify(events)
        events = [start(), start()]
        with self.assertRaisesRegex(ValueError, "Duplicated"):
            self.verify(events)

    def test_unexpected_head_and_unknown_operations_refused(self):
        for change in (
            {"expected_head": "b" * 40},
            {"operation": "EDIT_CHECKPOINT"},
            {"extra": True},
        ):
            e = event("INTERRUPT", 2, {"reason": "pause", "material": "artifact:synthetic"})
            e.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.verify([start(), e])


if __name__ == "__main__":
    unittest.main()
