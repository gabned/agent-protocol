from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import agent_protocol as protocol

BASE = "a" * 40
HEAD = "b" * 40
MOVED_HEAD = "c" * 40


def make_event(
    *,
    workstream_class: str | None = "PROTOCOL",
    escalation: str = "NONE",
    head_sha: str = HEAD,
    extra_body: str = "",
    sender_login: str = "gabned",
    sender_type: str = "User",
    author_login: str = "gabned",
) -> dict[str, object]:
    marker = (
        f"WORKSTREAM_CLASS: {workstream_class}\n"
        if workstream_class is not None
        else ""
    )
    return {
        "number": 46,
        "repository": {"full_name": protocol.REPOSITORY},
        "sender": {"login": sender_login, "type": sender_type},
        "pull_request": {
            "body": (
                marker
                + f"PROTOCOL_ESCALATION: {escalation}\n"
                + extra_body
            ),
            "author_association": "OWNER",
            "user": {"login": author_login, "type": "User"},
            "base": {"sha": BASE},
            "head": {"sha": head_sha},
        },
    }


def make_report(
    event: dict[str, object],
    paths: list[str],
    *,
    head_sha: str = HEAD,
    credentials_accessed: bool | None = False,
    production_environment_accessed: bool | None = False,
) -> dict[str, object]:
    return protocol.build_change_control_report(
        event=event,
        changed_paths=paths,
        expected_base_sha=BASE,
        expected_head_sha=head_sha,
        complete=True,
        credentials_accessed=credentials_accessed,
        production_environment_accessed=production_environment_accessed,
    )


def current_pr(*, body: str, base_sha: str = BASE, head_sha: str = HEAD) -> dict[str, object]:
    return {
        "number": 46,
        "body": body,
        "base": {"sha": base_sha},
        "head": {"sha": head_sha},
    }


def waiver_body(*, head_sha: str = HEAD, approver_login: str = "gabned") -> str:
    waiver = {
        "active": True,
        "approver_login": approver_login,
        "approver_type": "User",
        "change_control_version": protocol.CHANGE_CONTROL_VERSION,
        "credentials_accessed": False,
        "head_sha": head_sha,
        "human_only": True,
        "mode": "EMERGENCY_WAIVER",
        "owner_pr": "#46",
        "production_environment_accessed": False,
        "reason_code": "EMERGENCY_SECURITY_RESPONSE",
        "repository": protocol.REPOSITORY,
        "schema_version": protocol.CHANGE_CONTROL_SCHEMA_VERSION,
        "source": "GITHUB_CONNECTOR",
        "static": True,
        "waived_blocker_codes": [
            "MIXED_SCOPE",
            "PROTOCOL_TOUCHES_PRODUCT",
        ],
    }
    return (
        "<!-- PROTOCOL_EMERGENCY_WAIVER\n"
        + json.dumps(waiver, indent=2, sort_keys=True)
        + "\nPROTOCOL_EMERGENCY_WAIVER -->\n"
    )


def test_change_control_accepts_protocol_only_pr() -> None:
    event = make_event()
    paths = [
        ".github/pull_request_template.md",
        "AGENTS.md",
        "docs/agent-development-v1.2.1.md",
        "tests/test_agent_protocol_v1_2_1.py",
        "tools/agent_protocol.py",
    ]
    report = make_report(event, paths)
    assert report["workstream_class"] == "PROTOCOL"
    assert report["observed_path_categories"] == ["PROTOCOL_SURFACE"]
    assert report["blocker_codes"] == []
    assert report["merge_allowed"] is True
    protocol.verify_change_control_report(
        report,
        event=event,
        changed_paths=paths,
        expected_base_sha=BASE,
        expected_head_sha=HEAD,
        complete=True,
        credentials_accessed=False,
        production_environment_accessed=False,
    )


def test_pr_class_is_mandatory_and_closed() -> None:
    missing = make_report(make_event(workstream_class=None), ["AGENTS.md"])
    assert missing["blocker_codes"] == ["PR_CLASS_MISSING"]
    assert missing["merge_allowed"] is False

    invalid = make_report(make_event(workstream_class="MAINTENANCE"), ["AGENTS.md"])
    assert invalid["blocker_codes"] == ["PR_CLASS_INVALID"]
    assert invalid["merge_allowed"] is False


def test_pr_markers_accept_github_api_crlf_bodies() -> None:
    event = make_event()
    event["pull_request"]["body"] = (
        "WORKSTREAM_CLASS: PRODUCT\r\nPROTOCOL_ESCALATION: NONE\r\n"
    )
    report = make_report(event, ["core/provelume/cli.py"])
    assert report["workstream_class"] == "PRODUCT"
    assert report["protocol_escalation"] == "NONE"
    assert report["blocker_codes"] == []
    assert report["merge_allowed"] is True


def test_current_public_pr_body_is_bound_only_to_the_exact_event_identity() -> None:
    event = make_event(workstream_class=None)
    body = "WORKSTREAM_CLASS: PRODUCT\nPROTOCOL_ESCALATION: NONE\n"
    bound = protocol.bind_current_pr_body(event, current_pr(body=body))
    assert bound["pull_request"]["body"] == body
    assert event["pull_request"]["body"] == "PROTOCOL_ESCALATION: NONE\n"

    for mismatch in (
        current_pr(body=body, base_sha="c" * 40),
        current_pr(body=body, head_sha="c" * 40),
        {**current_pr(body=body), "number": 47},
    ):
        with pytest.raises(protocol.ContractError, match="does not match"):
            protocol.bind_current_pr_body(event, mismatch)

    with pytest.raises(protocol.ContractError, match="body must be a string"):
        protocol.bind_current_pr_body(event, current_pr(body=None))  # type: ignore[arg-type]


def test_mixed_scope_guard_fails_closed() -> None:
    report = make_report(
        make_event(),
        ["AGENTS.md", "core/provelume/cli.py"],
    )
    assert report["observed_path_categories"] == [
        "PRODUCT_SURFACE",
        "PROTOCOL_SURFACE",
    ]
    assert report["blocker_codes"] == [
        "MIXED_SCOPE",
        "PROTOCOL_TOUCHES_PRODUCT",
    ]
    assert report["required_action"] == "PROTOCOL_ESCALATION"
    assert report["merge_allowed"] is False


def test_product_protocol_finding_stops_and_emits_escalation() -> None:
    event = make_event(
        workstream_class="PRODUCT",
        escalation="PROTOCOL_DEFECT_SUSPECTED",
    )
    report = make_report(event, ["core/provelume/cli.py"])
    assert report["blocker_codes"] == ["PROTOCOL_ESCALATION_REQUIRED"]
    assert report["required_action"] == "PROTOCOL_ESCALATION"

    escalation = protocol.build_protocol_escalation(
        event=event,
        finding_code="PROTOCOL_DEFECT_SUSPECTED",
        expected_head_sha=HEAD,
        credentials_accessed=False,
        production_environment_accessed=False,
    )
    assert escalation["mode"] == "PROTOCOL_ESCALATION"
    assert escalation["result"] == "STOPPED"
    assert escalation["required_action"] == "OPEN_SEPARATE_PROTOCOL_PR"
    assert escalation["agents_may_modify_protocol_in_current_pr"] is False


def test_static_human_exact_head_waiver_can_cover_only_declared_blockers() -> None:
    event = make_event(extra_body=waiver_body())
    report = make_report(event, ["AGENTS.md", "core/provelume/cli.py"])
    assert report["active_blocker_codes"] == [
        "MIXED_SCOPE",
        "PROTOCOL_TOUCHES_PRODUCT",
    ]
    assert report["waiver_status"] == "VALID"
    assert report["waived_blocker_codes"] == [
        "MIXED_SCOPE",
        "PROTOCOL_TOUCHES_PRODUCT",
    ]
    assert report["blocker_codes"] == []
    assert report["merge_allowed"] is True


def test_moved_head_invalidates_static_waiver() -> None:
    event = make_event(head_sha=MOVED_HEAD, extra_body=waiver_body())
    report = make_report(
        event,
        ["AGENTS.md", "core/provelume/cli.py"],
        head_sha=MOVED_HEAD,
    )
    assert report["waiver_status"] == "INVALID"
    assert "WAIVER_HEAD_MISMATCH" in report["blocker_codes"]
    assert report["merge_allowed"] is False


def test_non_human_sender_cannot_activate_waiver() -> None:
    event = make_event(extra_body=waiver_body(), sender_type="Bot")
    report = make_report(event, ["AGENTS.md", "core/provelume/cli.py"])
    assert report["waiver_status"] == "INVALID"
    assert "WAIVER_NOT_HUMAN" in report["blocker_codes"]
    assert report["merge_allowed"] is False


def test_sender_cannot_inherit_the_pr_authors_trusted_association() -> None:
    event = make_event(
        extra_body=waiver_body(approver_login="outsider"),
        sender_login="outsider",
        author_login="gabned",
    )
    report = make_report(event, ["AGENTS.md", "core/provelume/cli.py"])
    assert report["waiver_status"] == "INVALID"
    assert "WAIVER_NOT_HUMAN" in report["blocker_codes"]
    assert report["merge_allowed"] is False


def test_connector_only_evidence_is_explicit_and_fail_closed() -> None:
    event = make_event(workstream_class="PRODUCT")
    ready = make_report(event, ["core/provelume/cli.py"])
    assert ready["source"] == "GITHUB_CONNECTOR"
    assert ready["connector_only"] is True
    assert ready["credentials_accessed"] is False
    assert ready["production_environment_accessed"] is False
    assert ready["merge_allowed"] is True

    accessed = make_report(
        event,
        ["core/provelume/cli.py"],
        credentials_accessed=True,
    )
    assert accessed["blocker_codes"] == ["CONNECTOR_EVIDENCE_INVALID"]
    assert accessed["merge_allowed"] is False


def test_name_status_rename_preserves_source_and_destination(tmp_path: Path) -> None:
    evidence = tmp_path / "name-status.z"
    evidence.write_bytes(b"R100\0AGENTS.md\0README.md\0M\0core/provelume/cli.py\0")
    assert protocol.read_name_status(evidence) == [
        "AGENTS.md",
        "README.md",
        "core/provelume/cli.py",
    ]


def test_authoritative_workflow_uses_the_trusted_base_guard() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "pull_request_target:" in workflow
    target = workflow.split("  agent-change-control:", 1)[1].split(
        "  core-tests:", 1
    )[0]
    assert "permissions: {}" in target
    assert "actions/checkout@" not in target
    assert 'git checkout --detach "$BASE_SHA"' in target
    assert "refs/pull/${PR_NUMBER}/head" in target
    assert 'test "$observed_head" = "$HEAD_SHA"' in target
    assert "python tools/agent_protocol.py change-control" in target
    assert workflow.count("python tools/agent_protocol.py change-control") == 1


def test_global_checkpoint_path_is_never_waivable() -> None:
    report = make_report(make_event(), ["AGENT_STATUS.md"])
    assert report["observed_path_categories"] == ["FORBIDDEN_GLOBAL_STATE"]
    assert report["blocker_codes"] == ["GLOBAL_STATE_FORBIDDEN"]
    assert report["merge_allowed"] is False


def review_common() -> dict[str, object]:
    return {
        "repository": protocol.REPOSITORY,
        "owner_pr": "#48",
        "current_head": HEAD,
        "repository_review": "NOT_APPLICABLE",
        "technical_finding": "NONE",
    }


def test_v1_3_unrequested_codex_review_is_not_a_gate() -> None:
    assert protocol.GOVERNANCE_RELEASE == "1.4.2"
    assert protocol.PROTOCOL_VERSION == "1.2"
    result = protocol.evaluate_review_gate(
        source="NONE",
        codex_state="NOT_REQUESTED",
        **review_common(),
    )
    assert result["merge_allowed"] is True
    assert result["codex_gate"] == "NOT_APPLICABLE"


def test_v1_3_explicit_review_pending_clean_and_findings() -> None:
    pending = protocol.evaluate_review_gate(
        source="EXPLICIT_MAINTAINER",
        codex_state="PENDING",
        **review_common(),
    )
    assert pending["merge_allowed"] is False
    clean = protocol.evaluate_review_gate(
        source="EXPLICIT_MAINTAINER",
        codex_state="CLEAN",
        reviewed_head=HEAD,
        **review_common(),
    )
    assert clean["merge_allowed"] is True
    assert clean["clean_review_signal"] is True
    findings = protocol.evaluate_review_gate(
        source="EXPLICIT_MAINTAINER",
        codex_state="FINDINGS",
        **review_common(),
    )
    assert findings["merge_allowed"] is False


def test_v1_3_moved_head_invalidates_clean_review() -> None:
    state = protocol.derive_codex_review_state(
        requested=True,
        available=True,
        signal="CLEAN",
        reviewed_head=HEAD,
        current_head=MOVED_HEAD,
    )
    assert state == "UNKNOWN"
    assert protocol.evaluate_review_gate(
        source="EXPLICIT_MAINTAINER",
        codex_state=state,
        reviewed_head=HEAD,
        **(review_common() | {"current_head": MOVED_HEAD}),
    )["merge_allowed"] is False


def test_v1_3_withdrawal_has_no_clean_signal_and_is_not_a_waiver() -> None:
    withdrawal = {
        "repository": protocol.REPOSITORY,
        "owner_pr": "#48",
        "owner_head_sha": HEAD,
        "withdrawn_by": "gabned",
        "comment_reference": f"{protocol.REPOSITORY}#48@comment-1",
        "maintainer_verified": True,
    }
    result = protocol.evaluate_review_gate(
        source="EXPLICIT_MAINTAINER",
        codex_state="WITHDRAWN",
        withdrawal=withdrawal,
        **review_common(),
    )
    assert result["merge_allowed"] is True
    assert result["clean_review_signal"] is False
    assert result["waiver_applied"] is False
    unrelated = dict(withdrawal)
    unrelated["comment_reference"] = "other/repository#9@comment-1"
    assert protocol.evaluate_review_gate(
        source="EXPLICIT_MAINTAINER",
        codex_state="WITHDRAWN",
        withdrawal=unrelated,
        **review_common(),
    )["merge_allowed"] is False


def test_v1_3_advisory_signals_and_availability_are_normalized() -> None:
    for signal in ("EYES", "COMMENTED"):
        assert protocol.derive_codex_review_state(
            requested=True,
            available=True,
            signal=signal,
            current_head=HEAD,
        ) == "PENDING"
    assert protocol.derive_codex_review_state(
        requested=False,
        available=False,
        signal="NONE",
        current_head=HEAD,
    ) == "NOT_REQUESTED"
    assert protocol.derive_codex_review_state(
        requested=True,
        available=False,
        signal="NONE",
        current_head=HEAD,
    ) == "UNAVAILABLE"


def test_v1_3_repository_review_and_unknown_fields_fail_closed() -> None:
    repository_required = review_common()
    repository_required["repository_review"] = "SATISFIED"
    assert protocol.evaluate_review_gate(
        source="REPOSITORY",
        codex_state="NOT_REQUESTED",
        **repository_required,
    )["merge_allowed"] is True
    repository_required["repository_review"] = "BLOCKED"
    assert protocol.evaluate_review_gate(
        source="REPOSITORY",
        codex_state="NOT_REQUESTED",
        **repository_required,
    )["merge_allowed"] is False
    assert protocol.evaluate_review_gate(
        source="EXPLICIT_MAINTAINER",
        codex_state="CLEAN",
        reviewed_head=HEAD,
        **repository_required,
    )["merge_allowed"] is False
    assert protocol.evaluate_review_gate(
        source="UNKNOWN",
        codex_state="UNKNOWN",
        **review_common(),
    )["merge_allowed"] is False


def test_v1_3_current_finding_blocks_and_review_cannot_reuse_waiver() -> None:
    finding = review_common()
    finding["technical_finding"] = "CURRENT"
    assert protocol.evaluate_review_gate(
        source="NONE",
        codex_state="NOT_REQUESTED",
        **finding,
    )["merge_allowed"] is False
    assert protocol.evaluate_review_gate(
        source="NONE",
        codex_state="NOT_REQUESTED",
        waiver={"reuse": True},
        **review_common(),
    )["merge_allowed"] is False
