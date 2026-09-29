from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "agent_protocol_v1_4",
    ROOT / "tools" / "agent_protocol_v1_4.py",
)
assert SPEC is not None and SPEC.loader is not None
protocol = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(protocol)


def campaign() -> dict[str, object]:
    return deepcopy(protocol.sample_campaign())


def handoff() -> dict[str, object]:
    return deepcopy(protocol.sample_handoff())


def test_sequential_auto_continuation_follows_observed_merge() -> None:
    value = protocol.validate_campaign(campaign())

    assert value["next_action"]["type"] == "AUTO_CONTINUE"
    assert value["pending_action"]["slice_id"] == "pilot/S02"


def test_first_slice_can_start_from_initial_authorization() -> None:
    value = campaign()
    value["campaign_mode"] = "SINGLE_SLICE"
    value["slices"] = [value["slices"][1]]
    value["observed_event"] = "INITIAL_AUTHORIZATION"
    value["observed_event_ref"] = "#164"

    protocol.validate_campaign(value)


def test_terminal_slices_must_form_a_prefix() -> None:
    value = campaign()
    value["slices"].reverse()

    with pytest.raises(protocol.ContractError, match="strict campaign prefix"):
        protocol.validate_campaign(value)


def test_merge_requires_exact_head_gate_event() -> None:
    value = campaign()
    value["slices"][0]["state"] = "ACTIVE"
    value["slices"][0]["merge_sha"] = "NONE"
    value["slices"] = [value["slices"][0], value["slices"][1]]
    value["pending_action"] = {
        "kind": "MERGE_ACTIVE_SLICE",
        "slice_id": "pilot/S01",
    }
    value["next_action"]["summary"] = "Merge pilot/S01 after exact-head gates."
    value["observed_event"] = "PR_MERGED"

    with pytest.raises(protocol.ContractError, match="passed-gate evidence"):
        protocol.validate_campaign(value)


def test_merge_event_must_equal_the_active_head() -> None:
    value = campaign()
    value["slices"][0]["state"] = "ACTIVE"
    value["slices"][0]["merge_sha"] = "NONE"
    value["pending_action"] = {
        "kind": "MERGE_ACTIVE_SLICE",
        "slice_id": "pilot/S01",
    }
    value["next_action"]["summary"] = "Merge pilot/S01 after exact-head gates."
    value["observed_event"] = "GATES_PASSED"
    value["observed_event_ref"] = "9" * 40

    with pytest.raises(protocol.ContractError, match="exact-head"):
        protocol.validate_campaign(value)


def test_authority_boundary_must_be_an_explicit_human_gate() -> None:
    value = campaign()
    value["campaign_state"] = "ACTIVE"
    value["authority_envelope"] = "SOURCE_ONLY"
    value["slices"][0]["state"] = "ACTIVE"
    value["slices"][0]["merge_sha"] = "NONE"
    value["pending_action"] = {
        "kind": "MERGE_ACTIVE_SLICE",
        "slice_id": "pilot/S01",
    }
    value["next_action"]["summary"] = "Merge pilot/S01 after exact-head gates."
    value["observed_event"] = "GATES_PASSED"
    value["observed_event_ref"] = value["slices"][0]["head_sha"]

    with pytest.raises(protocol.ContractError, match="closed human gate"):
        protocol.validate_campaign(value)


def test_closed_human_gate_requires_one_exact_prompt() -> None:
    value = campaign()
    value["campaign_state"] = "HUMAN_GATE"
    value["authority_envelope"] = "SOURCE_ONLY"
    value["slices"][0]["state"] = "ACTIVE"
    value["slices"][0]["merge_sha"] = "NONE"
    value["pending_action"] = {
        "kind": "MERGE_ACTIVE_SLICE",
        "slice_id": "pilot/S01",
    }
    value["observed_event"] = "GATES_PASSED"
    value["observed_event_ref"] = value["slices"][0]["head_sha"]
    value["stop_reason"] = "AUTHORITY_EXHAUSTED"
    value["next_action"] = {
        "type": "USER_ACTION_REQUIRED",
        "summary": "Authorize merge of pilot/S01 on the exact reviewed head.",
        "prompt": "Authorize merge of pilot/S01 on its unchanged reviewed head.",
    }

    protocol.validate_campaign(value)


def test_authority_exhausted_cannot_stop_authorized_work() -> None:
    value = campaign()
    value["campaign_state"] = "HUMAN_GATE"
    value["stop_reason"] = "AUTHORITY_EXHAUSTED"
    value["next_action"] = {
        "type": "USER_ACTION_REQUIRED",
        "summary": "Authorize the already-authorized pilot/S02 start.",
        "prompt": "Authorize pilot/S02.",
    }

    with pytest.raises(protocol.ContractError, match="beyond the envelope"):
        protocol.validate_campaign(value)


def test_stop_reason_registry_fails_closed() -> None:
    value = campaign()
    value["stop_reason"] = "PLEASE_DECIDE"

    with pytest.raises(protocol.ContractError, match="closed registry"):
        protocol.validate_campaign(value)


def test_idea_inbox_accepts_only_unique_github_issues() -> None:
    value = campaign()
    value["idea_inbox"]["items"] = ["free-form idea"]

    with pytest.raises(protocol.ContractError, match="exact issue/PR"):
        protocol.validate_campaign(value)


def test_campaign_requires_an_exact_owner_issue() -> None:
    value = campaign()
    value["owner_issue"] = "remembered-in-chat"

    with pytest.raises(protocol.ContractError, match="exact issue/PR"):
        protocol.validate_campaign(value)


def test_active_slice_cannot_skip_an_earlier_planned_slice() -> None:
    value = campaign()
    value["slices"][0] = {
        "id": "pilot/S01",
        "state": "PLANNED",
        "issue": "#1",
        "pr": "NONE",
        "head_sha": "NONE",
        "merge_sha": "NONE",
    }
    value["slices"][1] = {
        "id": "pilot/S02",
        "state": "ACTIVE",
        "issue": "#3",
        "pr": "#4",
        "head_sha": "4" * 40,
        "merge_sha": "NONE",
    }
    value["pending_action"] = {
        "kind": "CONTINUE_ACTIVE_SLICE",
        "slice_id": "pilot/S02",
    }
    value["next_action"]["summary"] = "Continue pilot/S02."

    with pytest.raises(protocol.ContractError, match="first nonterminal"):
        protocol.validate_campaign(value)


def test_publication_event_must_equal_the_candidate_build() -> None:
    value = campaign()
    value["authority_envelope"] = "THROUGH_RELEASE"
    value["slices"][1] = {
        "id": "pilot/S02",
        "state": "MERGED",
        "issue": "#3",
        "pr": "#4",
        "head_sha": "4" * 40,
        "merge_sha": "5" * 40,
    }
    value["train"]["publication_state"] = "CANDIDATE"
    value["train"]["build_sha"] = "6" * 40
    value["pending_action"] = {"kind": "PUBLISH_RELEASE", "slice_id": "NONE"}
    value["observed_event"] = "RELEASE_CANDIDATE_MERGED"
    value["observed_event_ref"] = "7" * 40
    value["next_action"]["summary"] = "Publish the exact release candidate."

    with pytest.raises(protocol.ContractError, match="exact-build"):
        protocol.validate_campaign(value)


@pytest.mark.parametrize(
    ("publication_state", "published_version", "build_sha"),
    [
        ("UNPUBLISHED", "1.0.0", "NONE"),
        ("CANDIDATE", "NONE", "NONE"),
        ("PUBLISHED", "0.9.0", "3" * 40),
    ],
)
def test_train_version_and_build_claims_are_distinct_and_consistent(
    publication_state: str,
    published_version: str,
    build_sha: str,
) -> None:
    value = campaign()
    value["train"]["publication_state"] = publication_state
    value["train"]["published_version"] = published_version
    value["train"]["build_sha"] = build_sha

    with pytest.raises(protocol.ContractError):
        protocol.validate_campaign(value)


def test_complete_train_requires_published_build_and_release_checkpoint() -> None:
    value = campaign()
    value["campaign_state"] = "COMPLETE"
    value["slices"] = [value["slices"][0]]
    value["pending_action"] = {"kind": "NO_ACTION", "slice_id": "NONE"}
    value["next_action"] = {
        "type": "CAMPAIGN_COMPLETE",
        "summary": "Campaign complete; open the next planned train when authorized.",
        "prompt": "NONE",
    }

    with pytest.raises(protocol.ContractError, match="published build"):
        protocol.validate_campaign(value)


def test_single_slice_can_complete_without_a_release() -> None:
    value = campaign()
    value["campaign_mode"] = "SINGLE_SLICE"
    value["campaign_state"] = "COMPLETE"
    value["slices"] = [value["slices"][0]]
    value["pending_action"] = {"kind": "NO_ACTION", "slice_id": "NONE"}
    value["next_action"] = {
        "type": "CAMPAIGN_COMPLETE",
        "summary": "The bounded single-slice campaign is complete.",
        "prompt": "NONE",
    }

    protocol.validate_campaign(value)


def test_handoff_is_canonical_and_at_most_120_words() -> None:
    value = handoff()

    protocol.validate_handoff(value)
    assert protocol.word_count(value["human_report"]) <= 120
    assert value["human_report"].count("Next action [") == 1


def test_handoff_rejects_a_second_next_action() -> None:
    value = handoff()
    value["human_report"] += "\nNext action [AUTO_CONTINUE]: Do something else."

    with pytest.raises(protocol.ContractError, match="canonical"):
        protocol.validate_handoff(value)


def test_handoff_user_action_requires_exact_prompt() -> None:
    value = handoff()
    value["outcome"] = "BLOCKED"
    value["next_action_type"] = "USER_ACTION_REQUIRED"
    value["next_prompt"] = "NONE"
    value["human_report"] = protocol.render_handoff(value)

    with pytest.raises(protocol.ContractError, match="exact next prompt"):
        protocol.validate_handoff(value)
