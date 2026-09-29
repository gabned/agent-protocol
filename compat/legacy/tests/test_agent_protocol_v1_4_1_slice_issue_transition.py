from __future__ import annotations

import importlib.util
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "agent_protocol_v1_4_1_late_findings",
    ROOT / "tools" / "agent_protocol_v1_4_1.py",
)
assert SPEC is not None and SPEC.loader is not None
protocol = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(protocol)


def expect_contract_error(fragment: str, operation: Callable[[], object]) -> None:
    try:
        operation()
    except protocol.ContractError as exc:
        assert fragment in str(exc), str(exc)
    else:
        raise AssertionError(f"expected ContractError containing {fragment!r}")


def profile_campaign(
    repository: str,
    *,
    issue: str = "#165",
) -> dict[str, object]:
    profile = protocol.REPOSITORY_PROFILES[repository]
    if repository == "gabned/provelume":
        workstream, authority, risk = "PRODUCT", "THROUGH_RELEASE", "PUBLIC_ARTIFACT"
    elif repository == "maxithlon/maxithlon":
        workstream, authority, risk = (
            "PRODUCT",
            "THROUGH_PRODUCTION_B",
            "CRITICAL_PRODUCTION",
        )
    elif repository in {"brickms/brickms", "gabned/provelume.com"}:
        workstream, authority, risk = (
            "PRODUCT",
            "THROUGH_PRODUCTION_B",
            "REVERSIBLE_PRODUCTION",
        )
    else:  # pragma: no cover - the closed profile registry owns this branch
        raise AssertionError(repository)
    value = {
        "schema_version": 2,
        "protocol_version": "1.4.1",
        "repository": repository,
        "campaign_id": repository.replace("/", "-") + "-late-findings",
        "owner_issue": "#164",
        "campaign_mode": "RELEASE_TRAIN",
        "campaign_state": "ACTIVE",
        "workstream_class": workstream,
        "authority_envelope": authority,
        "risk_profile": risk,
        "release_profile": profile["release_profile"],
        "auto_continuation": "SEQUENTIAL",
        "checkpoint": {
            "policy": "RELEASE_BOUNDARY",
            "state": "NOT_DUE",
            "reference": "NONE",
        },
        "idea_inbox": {
            "mode": "GITHUB_ISSUES_ONLY",
            "scope": "FROZEN_UNTIL_RELEASE_BOUNDARY",
            "items": [],
        },
        "train": {
            "train_id": repository.replace("/", "-") + "-train",
            "target_version": "1.4.1",
            "publication_state": "UNPUBLISHED",
            "published_version": "NONE",
            "candidate_build_sha": "NONE",
            "deployed_build_sha": "NONE",
            "published_build_sha": "NONE",
            "upstream": {
                "repository": profile["upstream_repository"],
                "published_version": "NONE",
                "published_build_sha": "NONE",
                "verification_state": (
                    "PENDING"
                    if profile["release_profile"] == "UPSTREAM_RELEASE_VERIFIED"
                    else "NOT_APPLICABLE"
                ),
            },
        },
        "slices": [
            {
                "id": "pilot/S01",
                "state": "PLANNED",
                "issue": issue,
                "pull_requests": [],
            }
        ],
        "receipts": [],
        "observed_event": "INITIAL_AUTHORIZATION",
        "observed_event_ref": "#164",
        "pending_action": {"kind": "START_NEXT_SLICE", "slice_id": "pilot/S01"},
        "stop_reason": "NONE",
        "next_action": {
            "type": "AUTO_CONTINUE",
            "summary": "Start pilot/S01 from the exact owner issue.",
            "prompt": "NONE",
        },
    }
    value["receipts"] = [
        protocol.build_receipt(
            sequence=1,
            operation="INITIALIZE",
            campaign_id=value["campaign_id"],
            github_event={
                "kind": "ISSUE",
                "action": "OPENED",
                "repository": repository,
                "reference": "#164",
                "sha": "NONE",
                "conclusion": "NOT_APPLICABLE",
            },
            previous_state_sha256=protocol.GENESIS_STATE_SHA256,
            successor_state_sha256=protocol.campaign_state_sha256(value),
            previous_receipt_sha256="NONE",
            initial_state=protocol.campaign_state_payload(value),
        )
    ]
    protocol.validate_campaign_v2(value)
    return value


def merged_waiting_campaign(repository: str) -> dict[str, object]:
    initial = profile_campaign(repository)
    opened = deepcopy(initial)
    opened["slices"][0].update(
        {
            "state": "ACTIVE",
            "pull_requests": [
                {
                    "sequence": 1,
                    "role": "OWNER",
                    "pr": "#166",
                    "state": "OPEN",
                    "head_sha": "5" * 40,
                    "merge_sha": "NONE",
                }
            ],
        }
    )
    opened["observed_event"] = "PR_OPENED"
    opened["observed_event_ref"] = "#166"
    opened["pending_action"] = {
        "kind": "CONTINUE_ACTIVE_SLICE",
        "slice_id": "pilot/S01",
    }
    opened["next_action"]["summary"] = "Continue pilot/S01 on its exact owner PR."
    opened = protocol.append_transition_receipt(
        initial,
        opened,
        {
            "kind": "PULL_REQUEST",
            "action": "OPENED",
            "repository": repository,
            "reference": "#166",
            "sha": "5" * 40,
            "conclusion": "NOT_APPLICABLE",
        },
    )

    gated = deepcopy(opened)
    gated["observed_event"] = "GATES_PASSED"
    gated["observed_event_ref"] = "5" * 40
    gated["pending_action"] = {
        "kind": "MERGE_ACTIVE_SLICE",
        "slice_id": "pilot/S01",
    }
    gated["next_action"]["summary"] = "Merge pilot/S01 at its exact passed head."
    gated = protocol.append_transition_receipt(
        opened,
        gated,
        {
            "kind": "WORKFLOW_RUN",
            "action": "COMPLETED",
            "repository": repository,
            "reference": "run:440",
            "sha": "5" * 40,
            "conclusion": "SUCCESS",
        },
    )

    merged = deepcopy(gated)
    merged["campaign_state"] = "WAITING_EVENT"
    merged["slices"][0]["state"] = "MERGED"
    merged["slices"][0]["pull_requests"][0].update(
        {"state": "MERGED", "merge_sha": "6" * 40}
    )
    merged["observed_event"] = "PR_MERGED"
    merged["observed_event_ref"] = "6" * 40
    merged["pending_action"] = {"kind": "WAIT_FOR_EVENT", "slice_id": "NONE"}
    merged["next_action"] = {
        "type": "WAIT_EVENT",
        "summary": "Wait for the exact qualified candidate commit.",
        "prompt": "NONE",
    }
    return protocol.append_transition_receipt(
        gated,
        merged,
        {
            "kind": "PULL_REQUEST",
            "action": "MERGED",
            "repository": repository,
            "reference": "#166",
            "sha": "6" * 40,
            "conclusion": "NOT_APPLICABLE",
        },
    )


def candidate_campaign(
    repository: str,
    *,
    candidate_sha: str = "7" * 40,
    observed_sha: str | None = None,
) -> dict[str, object]:
    before = merged_waiting_campaign(repository)
    after = deepcopy(before)
    observed = candidate_sha if observed_sha is None else observed_sha
    after["campaign_state"] = "ACTIVE"
    after["train"]["publication_state"] = "CANDIDATE"
    after["train"]["candidate_build_sha"] = candidate_sha
    after["observed_event"] = "RELEASE_CANDIDATE_MERGED"
    after["observed_event_ref"] = observed
    if repository == "gabned/provelume":
        action = "PUBLISH_RELEASE"
        summary = "Publish the exact candidate as the target release."
    elif repository == "gabned/provelume.com":
        action = "VERIFY_UPSTREAM_RELEASE"
        summary = "Verify the exact upstream release before site deployment."
    else:
        action = "DEPLOY_PRODUCTION_B"
        summary = "Deploy the exact candidate through production B."
    after["pending_action"] = {"kind": action, "slice_id": "NONE"}
    after["next_action"] = {
        "type": "AUTO_CONTINUE",
        "summary": summary,
        "prompt": "NONE",
    }
    return protocol.append_transition_receipt(
        before,
        after,
        {
            "kind": "COMMIT",
            "action": "CREATED",
            "repository": repository,
            "reference": observed,
            "sha": observed,
            "conclusion": "NOT_APPLICABLE",
        },
    )


def issue_transition() -> tuple[
    dict[str, object], dict[str, object], dict[str, object]
]:
    before = profile_campaign("gabned/provelume", issue="NONE")
    after = deepcopy(before)
    after["slices"][0].update({"state": "ACTIVE", "issue": "#196"})
    after["observed_event"] = "SLICE_ISSUE_OPENED"
    after["observed_event_ref"] = "#196"
    after["pending_action"] = {
        "kind": "CONTINUE_ACTIVE_SLICE",
        "slice_id": "pilot/S01",
    }
    after["next_action"]["summary"] = "Continue pilot/S01 from its exact opened issue."
    event = {
        "kind": "ISSUE",
        "action": "OPENED",
        "repository": "gabned/provelume",
        "reference": "#196",
        "sha": "NONE",
        "conclusion": "NOT_APPLICABLE",
    }
    return before, after, event


def test_planned_slice_issue_opening_has_a_closed_observed_event() -> None:
    assert "SLICE_ISSUE_OPENED" in protocol.OBSERVED_EVENTS


def test_planned_slice_may_still_start_without_a_preassigned_issue() -> None:
    value = profile_campaign("gabned/provelume", issue="NONE")
    assert value["slices"][0]["issue"] == "NONE"


def test_exact_issue_event_assigns_and_activates_only_one_planned_slice() -> None:
    before, after, event = issue_transition()
    result = protocol.append_transition_receipt(before, after, event)
    assert result["slices"][0]["issue"] == "#196"
    assert result["slices"][0]["state"] == "ACTIVE"
    assert result["receipts"][-1]["github_event"] == event


def test_slice_issue_event_is_idempotent_only_for_its_exact_final_state() -> None:
    before, after, event = issue_transition()
    result = protocol.append_transition_receipt(before, after, event)
    assert protocol.append_transition_receipt(result, deepcopy(result), event) == result


def test_slice_issue_event_rejects_retained_issue_rewrite() -> None:
    before = profile_campaign("gabned/provelume")
    after = deepcopy(before)
    after["slices"][0].update({"state": "ACTIVE", "issue": "#196"})
    after["observed_event"] = "SLICE_ISSUE_OPENED"
    after["observed_event_ref"] = "#196"
    after["pending_action"] = {
        "kind": "CONTINUE_ACTIVE_SLICE",
        "slice_id": "pilot/S01",
    }
    after["next_action"]["summary"] = "Continue pilot/S01 from a rewritten issue."
    event = {
        "kind": "ISSUE",
        "action": "OPENED",
        "repository": "gabned/provelume",
        "reference": "#196",
        "sha": "NONE",
        "conclusion": "NOT_APPLICABLE",
    }
    expect_contract_error(
        "retained slice issue",
        lambda: protocol.append_transition_receipt(before, after, event),
    )


def test_slice_issue_event_rejects_unrelated_campaign_mutation() -> None:
    before, after, event = issue_transition()
    after["idea_inbox"]["items"].append("#999")
    expect_contract_error(
        "cannot mutate unrelated",
        lambda: protocol.append_transition_receipt(before, after, event),
    )


def test_slice_issue_event_rejects_pull_request_ledger_mutation() -> None:
    before, after, event = issue_transition()
    after["slices"][0]["pull_requests"] = [
        {
            "sequence": 1,
            "role": "OWNER",
            "pr": "#197",
            "state": "OPEN",
            "head_sha": "1" * 40,
            "merge_sha": "NONE",
        }
    ]
    expect_contract_error(
        "activate only that slice",
        lambda: protocol.append_transition_receipt(before, after, event),
    )


def test_slice_issue_event_rejects_train_mutation() -> None:
    before, after, event = issue_transition()
    after["train"]["target_version"] = "1.4.2"
    expect_contract_error(
        "identity or authority",
        lambda: protocol.append_transition_receipt(before, after, event),
    )


def test_slice_issue_event_rejects_checkpoint_mutation() -> None:
    before, after, event = issue_transition()
    after["checkpoint"]["state"] = "DUE"
    expect_contract_error(
        "cannot mutate unrelated",
        lambda: protocol.append_transition_receipt(before, after, event),
    )


def test_slice_issue_event_rejects_ambiguous_slice_selection() -> None:
    before = profile_campaign("gabned/provelume", issue="NONE")
    before["slices"].append(
        {
            "id": "pilot/S02",
            "state": "PLANNED",
            "issue": "#196",
            "pull_requests": [],
        }
    )
    before["receipts"][0]["initial_state"] = protocol.campaign_state_payload(before)
    before["receipts"][0]["successor_state_sha256"] = protocol.campaign_state_sha256(
        before
    )
    first = before["receipts"][0]
    first["idempotency_key"] = protocol.receipt_idempotency_key(
        campaign_id=before["campaign_id"],
        operation=first["operation"],
        github_event=first["github_event"],
        previous_state_sha256=first["previous_state_sha256"],
        successor_state_sha256=first["successor_state_sha256"],
    )
    first["receipt_sha256"] = protocol.receipt_sha256(first)
    protocol.validate_campaign_v2(before)
    after = deepcopy(before)
    after["slices"][0].update({"state": "ACTIVE", "issue": "#196"})
    after["observed_event"] = "SLICE_ISSUE_OPENED"
    after["observed_event_ref"] = "#196"
    after["pending_action"] = {
        "kind": "CONTINUE_ACTIVE_SLICE",
        "slice_id": "pilot/S01",
    }
    after["next_action"]["summary"] = "Continue pilot/S01 from its opened issue."
    event = {
        "kind": "ISSUE",
        "action": "OPENED",
        "repository": "gabned/provelume",
        "reference": "#196",
        "sha": "NONE",
        "conclusion": "NOT_APPLICABLE",
    }
    expect_contract_error(
        "exactly one mutable slice",
        lambda: protocol.append_transition_receipt(before, after, event),
    )


def test_slice_issue_event_cannot_be_reused_for_a_different_transition() -> None:
    before, after, event = issue_transition()
    recorded = protocol.append_transition_receipt(before, after, event)
    reused = deepcopy(recorded)
    reused["idea_inbox"]["items"].append("#196")
    expect_contract_error(
        "cannot be reused",
        lambda: protocol.append_transition_receipt(recorded, reused, event),
    )


def test_snapshotless_terminal_migration_receipt_fails_closed() -> None:
    value = protocol.migrate_campaign(protocol.sample_campaign_v1())
    receipt = value["receipts"][0]
    del receipt["previous_state"]
    del receipt["successor_state"]
    receipt["receipt_sha256"] = protocol.receipt_sha256(receipt)
    expect_contract_error(
        "exact source and result snapshots",
        lambda: protocol.validate_campaign_v2(value),
    )


def test_candidate_event_and_observed_reference_bind_the_candidate_build() -> None:
    value = candidate_campaign("gabned/provelume.com")
    assert value["observed_event_ref"] == value["train"]["candidate_build_sha"]


def test_candidate_event_cannot_qualify_a_different_recorded_build() -> None:
    expect_contract_error(
        "exact candidate build",
        lambda: candidate_campaign(
            "gabned/provelume.com",
            candidate_sha="7" * 40,
            observed_sha="8" * 40,
        ),
    )


def test_deployment_event_and_observed_reference_bind_the_deployed_build() -> None:
    before = candidate_campaign("brickms/brickms")
    after = deepcopy(before)
    after["train"]["deployed_build_sha"] = "7" * 40
    after["observed_event"] = "PRODUCTION_DEPLOYED"
    after["observed_event_ref"] = "7" * 40
    after["pending_action"] = {"kind": "VERIFY_PRODUCTION", "slice_id": "NONE"}
    after["next_action"]["summary"] = "Verify the exact deployed build."
    result = protocol.append_transition_receipt(
        before,
        after,
        {
            "kind": "DEPLOYMENT",
            "action": "STATUS_SUCCEEDED",
            "repository": "brickms/brickms",
            "reference": "deployment:451",
            "sha": "7" * 40,
            "conclusion": "SUCCESS",
        },
    )
    assert result["train"]["deployed_build_sha"] == result["observed_event_ref"]


def test_deployment_event_cannot_record_a_different_deployed_build() -> None:
    before = candidate_campaign("brickms/brickms")
    after = deepcopy(before)
    after["campaign_state"] = "WAITING_EVENT"
    after["train"]["deployed_build_sha"] = "7" * 40
    after["observed_event"] = "PRODUCTION_DEPLOYED"
    after["observed_event_ref"] = "8" * 40
    after["pending_action"] = {"kind": "WAIT_FOR_EVENT", "slice_id": "NONE"}
    after["next_action"] = {
        "type": "WAIT_EVENT",
        "summary": "Wait after recording deployment evidence.",
        "prompt": "NONE",
    }
    expect_contract_error(
        "exact deployed build",
        lambda: protocol.append_transition_receipt(
            before,
            after,
            {
                "kind": "WORKFLOW_RUN",
                "action": "COMPLETED",
                "repository": "brickms/brickms",
                "reference": "run:452",
                "sha": "8" * 40,
                "conclusion": "SUCCESS",
            },
        ),
    )


def run_tests() -> None:
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            value()


if __name__ == "__main__":
    run_tests()
