from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools import agent_protocol as protocol

BASE = "a" * 40
HEAD = "b" * 40


def policy_context():
    contract = {"schema": "agent-policy-contract/v1", "repository": protocol.REPOSITORY,
                "source_commit": BASE, "reference": "synthetic accepted contract",
                "routing": "PROTOCOL/v1"}
    return {"contract": contract, "trusted_contract": protocol.policy_module().digest(contract),
            "workstream_class": "PROTOCOL",
            "production_authority": dict.fromkeys(["production", "deploy", "migrate"], False)}


def test_binding_cli_rejects_incoherent_route_before_output(tmp_path):
    report = make_safe_report()
    contract = {"schema": "agent-policy-contract/v1", "repository": protocol.REPOSITORY,
                "source_commit": BASE, "reference": "accepted PRODUCT/v2 fixture",
                "routing": "PRODUCT/v2"}
    inputs = {"effects": report, "contract": contract,
              "authority": dict.fromkeys(["production", "deploy", "migrate"], False)}
    for name, value in inputs.items():
        (tmp_path / f"{name}.json").write_text(json.dumps(value))
    output = tmp_path / "binding.json"
    command = [sys.executable, str(Path(protocol.__file__)), "bind", "--report",
               str(tmp_path / "effects.json"), "--pr", "#45", "--workstream", "example",
               "--workstream-class", "PRODUCT", "--adopted-contract",
               str(tmp_path / "contract.json"), "--trusted-contract",
               protocol.policy_module().digest(contract), "--production-authority",
               str(tmp_path / "authority.json"), "--output", str(output)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode != 0 and not output.exists()
    assert "INPUT_MISMATCH" in result.stdout + result.stderr
    assert "PRODUCT/REPOSITORY_POLICY" in result.stdout + result.stderr


def test_legacy_coherent_binding_uses_fresh_context_without_rewriting():
    report = make_safe_report()
    binding = make_binding(report)
    decision = binding.pop("policy_resolution")
    contract = binding.pop("adopted_contract")
    binding = protocol.seal(binding)
    before = copy.deepcopy(binding)
    context = {"contract": contract, "trusted_contract": decision["contract_sha256"],
               "workstream_class": "PROTOCOL",
               "production_authority": decision["production_authority"]}
    protocol.validate_binding(binding, context)
    assert binding == before
    with pytest.raises(protocol.ContractError, match="STALE_EVIDENCE"):
        protocol.validate_binding(binding)
    context["workstream_class"] = "PRODUCT"
    with pytest.raises(protocol.ContractError, match="INPUT_MISMATCH"):
        protocol.validate_binding(binding, context)


def make_safe_report() -> dict[str, object]:
    return protocol.build_effect_report(
        base_sha=BASE,
        head_sha=HEAD,
        changed_paths=sorted(protocol.SAFE_PROTOCOL_PATHS),
        policy="NO_PRODUCTION",
        source="GITHUB_CONNECTOR",
        complete=True,
        observed_at=protocol.now_utc(),
    )


def make_binding(report: dict[str, object]) -> dict[str, object]:
    contract = {"schema": "agent-policy-contract/v1", "repository": protocol.REPOSITORY,
                "source_commit": BASE, "reference": "synthetic accepted contract",
                "routing": "PROTOCOL/v1"}
    return protocol.build_binding(
        report,
        active_pr="#45",
        workstream="agent-protocol-v1.2-subset",
        workstream_class="PROTOCOL", adopted_contract=contract,
        trusted_contract=protocol.policy_module().digest(contract),
        production_authority={"production": False, "deploy": False, "migrate": False},
    )


def make_snapshot(
    report: dict[str, object],
    *,
    owner_pr: str = "#45",
    checks: str = "SUCCESS",
    review: str = "UNKNOWN",
    requires_approval: str = "FALSE",
) -> dict[str, object]:
    return protocol.seal(
        {
            "policy_context": policy_context(),
            "schema_version": protocol.SCHEMA_VERSION,
            "protocol_version": protocol.PROTOCOL_VERSION,
            "mode": "SNAPSHOT",
            "source": "GITHUB_CONNECTOR",
            "repository": protocol.REPOSITORY,
            "observed_at": protocol.now_utc(),
            "default_branch": protocol.DEFAULT_BRANCH,
            "default_sha": BASE,
            "owner_pr": owner_pr,
            "base_sha": BASE,
            "head_sha": HEAD,
            "binding_basis_sha": HEAD,
            "effect_report_sha256": report["report_sha256"],
            "pr_state": "OPEN",
            "draft": "FALSE",
            "checks": checks,
            "review": review,
            "requires_approval": requires_approval,
            "unresolved_threads": 0,
            "mergeability": "MERGEABLE",
            "base_ancestry": "TRUE",
            "binding_basis_ancestor": "TRUE",
            "credentials_accessed": False,
            "production_environment_accessed": False,
        }
    )


def test_protocol_self_test() -> None:
    protocol.self_test()


def test_resealed_binding_cannot_replace_independent_current_route():
    report = make_safe_report()
    binding = make_binding(report)
    untrusted = binding["adopted_contract"] | {"routing": "PRODUCT/v1"}
    binding["adopted_contract"] = untrusted
    binding["policy_resolution"] = protocol.policy_module().resolve_policy(
        contract=untrusted, trusted_contract=protocol.policy_module().digest(untrusted),
        workstream=binding["workstream"], workstream_class="PRODUCT",
        selected_policy="NO_PRODUCTION", observed_effects="NO_PRODUCTION",
        production_authority=policy_context()["production_authority"],
    )
    binding = protocol.seal(binding)
    context = policy_context()
    context["contract"]["routing"] = "PRODUCT/v2"
    context["workstream_class"] = "PRODUCT"
    context["trusted_contract"] = protocol.policy_module().digest(context["contract"])
    snapshot = make_snapshot(report)
    snapshot["policy_context"] = context
    snapshot = protocol.seal(snapshot)
    result = protocol.preflight(snapshot, binding)
    assert not result["merge_ready"]
    assert any("PRODUCT/REPOSITORY_POLICY" in error for error in result["errors"])
    with pytest.raises(protocol.ContractError, match="STALE_EVIDENCE"):
        protocol.validate_binding(binding)


def test_exact_safe_delta_round_trip(tmp_path: Path) -> None:
    # Successor routing is registered before its files or rules can be adopted.
    for name in (
        ".github/agent-protocol/documents-v1.4.9.json",
        "docs/agent-development-v1.4.9.md",
        "tools/agent_protocol_v1_4_9.py",
        "tests/test_agent_protocol_v1_4_9.py",
        ".github/agent-protocol/documents-v1.4.8.json",
        "docs/agent-development-v1.4.8.md",
    ):
        assert protocol.classify_path(name) == ("NO_PRODUCTION", None)
    for name in (
        "docs/agent-development-v1.4.8-extra.md",
        ".github/agent-protocol/documents-v1.4.10.json",
        "docs/agent-development-v1.4.9-extra.md",
        "tools/agent_protocol_v1_4_9_extra.py",
        "tools/agent_protocol_v1_4_8.py",
    ):
        assert protocol.classify_path(name)[0] == "PRODUCTION"
    report = make_safe_report()
    path = tmp_path / "effect.json"
    protocol.write_object(path, report)
    reloaded = json.loads(path.read_text(encoding="utf-8"))
    protocol.verify_effect_report(
        reloaded,
        base_sha=BASE,
        head_sha=HEAD,
        policy="NO_PRODUCTION",
    )
    assert reloaded["effect"] == "NO_PRODUCTION"
    assert reloaded["bind_allowed"] is True
    assert len(reloaded["report_sha256"]) == 64


def test_unclassified_path_fails_closed_under_no_production_policy() -> None:
    report = protocol.build_effect_report(
        base_sha=BASE,
        head_sha=HEAD,
        changed_paths=["compose.yml"],
        policy="NO_PRODUCTION",
        source="GITHUB_CONNECTOR",
        complete=True,
        observed_at=protocol.now_utc(),
    )
    assert report["effect"] == "PRODUCTION"
    assert report["bind_allowed"] is False
    assert report["matches"] == [{"identifier": "UNCLASSIFIED_PATH", "path": "compose.yml"}]


def test_verification_recomputes_effect_and_authorization() -> None:
    report = protocol.build_effect_report(
        base_sha=BASE,
        head_sha=HEAD,
        changed_paths=["core/provelume/cli.py"],
        policy="REPOSITORY_POLICY",
        source="GITHUB_CONNECTOR",
        complete=True,
        observed_at=protocol.now_utc(),
    )
    tampered = dict(report)
    tampered["effect"] = "NO_PRODUCTION"
    tampered["matches"] = []
    tampered = protocol.seal(tampered)
    with pytest.raises(protocol.ContractError, match="classifications"):
        protocol.verify_effect_report(
            tampered,
            base_sha=BASE,
            head_sha=HEAD,
            policy="REPOSITORY_POLICY",
        )


def test_rename_connector_evidence_includes_both_paths() -> None:
    paths = protocol.connector_paths(
        {"changed_files": [{"previous_path": "core/old.py", "filename": "docs/new.md"}]}
    )
    assert paths == ["core/old.py", "docs/new.md"]


def test_connector_snapshot_is_cross_bound_to_owner_and_shas() -> None:
    report = make_safe_report()
    binding = make_binding(report)
    ready = protocol.preflight(make_snapshot(report), binding)
    assert ready["merge_ready"] is True

    unrelated = protocol.preflight(make_snapshot(report, owner_pr="#999"), binding)
    assert unrelated["merge_ready"] is False
    assert any("owner_pr" in error for error in unrelated["errors"])


def test_unknown_required_gate_is_fail_closed() -> None:
    report = make_safe_report()
    binding = make_binding(report)
    blocked = protocol.preflight(make_snapshot(report, checks="UNKNOWN"), binding)
    assert blocked["merge_ready"] is False
    assert any("checks" in error for error in blocked["errors"])


def test_advisory_unknown_review_is_allowed_only_when_approval_not_required() -> None:
    report = make_safe_report()
    binding = make_binding(report)
    advisory = protocol.preflight(
        make_snapshot(report, review="UNKNOWN", requires_approval="FALSE"), binding
    )
    assert advisory["merge_ready"] is True

    required = protocol.preflight(
        make_snapshot(report, review="UNKNOWN", requires_approval="TRUE"), binding
    )
    assert required["merge_ready"] is False


def test_reconciliation_accepts_newer_default_tip_without_inferring_release() -> None:
    report = make_safe_report()
    binding = make_binding(report)
    evidence = protocol.seal(
        {
            "schema_version": protocol.SCHEMA_VERSION,
            "protocol_version": protocol.PROTOCOL_VERSION,
            "mode": "RECONCILE_EVIDENCE",
            "policy_context": policy_context(),
            "source": "GITHUB_CONNECTOR",
            "repository": protocol.REPOSITORY,
            "observed_at": protocol.now_utc(),
            "default_branch": protocol.DEFAULT_BRANCH,
            "default_sha": "d" * 40,
            "active_pr": "#45",
            "pr_state": "MERGED",
            "binding_basis_sha": HEAD,
            "binding_basis_ancestor": "TRUE",
            "effect_report_sha256": report["report_sha256"],
            "merge_sha": "c" * 40,
            "merge_sha_on_default": "TRUE",
            "workflow_status": "UNKNOWN",
            "release_status": "NOT_APPLICABLE",
            "production_action_performed": False,
        }
    )
    reconciled = protocol.reconcile(evidence, binding)
    assert evidence["default_sha"] != evidence["merge_sha"]
    assert reconciled["release_allowed"] is True
    assert reconciled["result"] == "UNKNOWN"
    assert reconciled["observational_only"] is True
    assert reconciled["production_action_performed"] is False


def test_recovery_effect_profile_is_exact_and_keeps_unknown_paths_closed():
    for path in (
        "docs/agent-development-v1.4.6-work.md",
        "docs/agent-development-v1.4.5-work.md",
        "tests/test_agent_protocol_work_recovery.py",
        "tools/agent_protocol_work_recovery.py",
    ):
        assert protocol.classify_path(path) == ("NO_PRODUCTION", None)
        assert protocol.classify_path(path + ".extra")[0] == "PRODUCTION"


def test_recovery_conformance_runs_in_isolation_and_propagates_failure(tmp_path):
    import shutil
    import subprocess
    import sys

    from tools import agent_protocol_work_recovery as recovery

    root = Path(__file__).resolve().parents[1]
    for name in (*recovery.WORK_FILES, *recovery.ops.VENDOR_FILES):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
        target.chmod(0o755 if recovery.ops.VENDOR_FILES.get(name) == "100755" else 0o644)
    command = [
        sys.executable,
        "-I",
        "-B",
        str(tmp_path / "tests/test_agent_protocol_work_recovery.py"),
    ]
    result = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Ran 38 tests" in result.stderr

    helper = tmp_path / "tools/agent_protocol_work_recovery.py"
    original = helper.read_text()
    assert '"authority": "NOT_GRANTED"' in original
    helper.write_text(original.replace('"authority": "NOT_GRANTED"', '"authority": "APPROVED"'))
    broken = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert broken.returncode != 0
    assert "FAILED" in broken.stderr
