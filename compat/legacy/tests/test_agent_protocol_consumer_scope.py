"""Consumer scope cases kept separate from measured historical test modules."""

from copy import deepcopy

import pytest
from test_agent_protocol_v1_4_2_ops import (
    BASE,
    REPO,
    attempt,
    execution147,
    operations,
    ops,
    resolved_finding,
)


def consumer_scope_case():
    value = operations()
    name = "tools/consumer-governance.py"  # Synthetic fixture, not a consumer path.
    value["baseline_paths"] = value["pr"]["changed_paths"] = [name]
    value["pr"]["file_patches"] = {name: "+verified governance repair\n"}
    policy = {"schema": "agent-repository-policy/v1", "repository": REPO,
              "required_workflows": value["ci"]["required_workflows"],
              "post_merge_required_workflows": value["post_merge_ci"]["required_workflows"],
              "review_requirement": "NONE"}
    profile = {"schema": "agent-protocol-scope/v1", "repository": REPO, "base_sha": BASE,
               "policy_path": ".github/agent-protocol/consumer-scope.json",
               "paths": [{"path": name, "role": "IMPLEMENTATION"}]}
    return value, policy, profile


def qualify_consumer(value, policy, profile):
    new = execution147()
    return new.validate_qualification(
        value, policy, new.digest(policy), scope_profile=profile,
        expected_scope_digest=new.digest(profile))


def test_accepted_consumer_scope_is_exact_bound_and_does_not_leak():
    value, policy, profile = consumer_scope_case()
    new = execution147()
    with pytest.raises(ValueError, match="non-Protocol"):
        new.validate_qualification(value, policy, new.digest(policy))
    result = qualify_consumer(value, policy, profile)
    assert result["result"] == "PASS"
    assert result["scope_profile_sha256"] == new.digest(profile)
    assert result["merge_performed"] is False
    with pytest.raises(ValueError, match="non-Protocol"):
        new.validate_qualification(value, policy, new.digest(policy))


@pytest.mark.parametrize("damage", ["repository", "base", "policy_change", "unregistered",
                                  "ci", "threads", "ancestry", "effects", "stale"])
def test_consumer_scope_keeps_every_other_gate(damage):
    value, policy, profile = consumer_scope_case()
    if damage == "repository":
        profile["repository"] = "brickms/brickms"
    elif damage == "base":
        profile["base_sha"] = "f" * 40
    elif damage == "policy_change":
        name = profile["policy_path"]
        value["pr"]["changed_paths"] = sorted([*value["pr"]["changed_paths"], name])
        value["baseline_paths"] = value["pr"]["changed_paths"].copy()
        value["pr"]["file_patches"][name] = "+candidate policy\n"
    elif damage == "unregistered":
        name = "tools/unregistered-governance.py"
        value["pr"]["changed_paths"] = value["baseline_paths"] = [name]
        value["pr"]["file_patches"] = {name: "+unregistered\n"}
    elif damage == "ci":
        value["ci"]["runs"][0]["attempts"][-1] = attempt(conclusion="FAILURE")
    elif damage == "threads":
        value["reviews"]["unresolved_threads"] = ["unresolved"]
    elif damage == "ancestry":
        value["merge"]["ancestry"] = []
    elif damage == "effects":
        value["effect_policy"] = "REPOSITORY_POLICY"
    else:
        value["pr"]["observed_at"] = "2020-01-01T00:00:00Z"
    with pytest.raises(ValueError):
        qualify_consumer(value, policy, profile)


@pytest.mark.parametrize("damage", ["wildcard", "duplicate", "traversal", "product",
                                  "workflow", "role", "empty", "extra", "policy_path"])
def test_consumer_scope_rejects_open_or_malformed_registration(damage):
    value, policy, profile = consumer_scope_case()
    row = profile["paths"][0]
    if damage == "wildcard":
        row["path"] = "tools/*"
    elif damage == "duplicate":
        profile["paths"].append(deepcopy(row))
    elif damage == "traversal":
        row["path"] = "tools/../core/application.py"
    elif damage == "product":
        row["path"] = "core/application.py"
    elif damage == "workflow":
        row["path"] = ".github/workflows/release.yml"
    elif damage == "role":
        row["role"] = "PRODUCT"
    elif damage == "empty":
        profile["paths"] = []
    elif damage == "extra":
        profile["approved"] = True
    else:
        profile["policy_path"] = "docs/candidate.json"
    with pytest.raises(ValueError):
        qualify_consumer(value, policy, profile)


def test_consumer_scope_requires_independent_unchanged_digest():
    value, policy, profile = consumer_scope_case()
    new = execution147()
    for supplied, expected in ((profile, None), (None, new.digest(profile)),
                               (profile, "0" * 64)):
        with pytest.raises(ValueError):
            new.validate_qualification(value, policy, new.digest(policy),
                                       scope_profile=supplied, expected_scope_digest=expected)
    value["scope_profile"] = profile
    with pytest.raises(ValueError):
        new.validate_qualification(value, policy, new.digest(policy))


def test_consumer_scope_cannot_bind_descriptive_registry_operations():
    _, _, profile = consumer_scope_case()
    value = operations("gabned/nexus")
    with (ops.trusted_protocol_scope(profile, ops.digest(profile)),
          pytest.raises(ValueError, match="base/repository mismatch")):
        ops.validate_operations(value)
    ops.validate_operations(value)  # Failure must also restore the prior context.


@pytest.mark.parametrize("name", ["docs/agent-development-v1.4.7-scope.json",
                                 "docs/runbooks/agent-development-v1.4.7-scope.json"])
def test_consumer_scope_reuses_registered_normative_policy_namespaces(name):
    value, policy, profile = consumer_scope_case()
    profile["policy_path"] = name
    assert qualify_consumer(value, policy, profile)["result"] == "PASS"


def test_profiled_operation_preserves_resolved_historical_findings():
    value, policy, profile = consumer_scope_case()
    value["late_findings"] = [resolved_finding()]
    assert qualify_consumer(value, policy, profile)["result"] == "PASS"


def test_nested_operation_cannot_borrow_outer_profile_authority():
    value, _, profile = consumer_scope_case()
    with (ops.trusted_protocol_scope(profile, ops.digest(profile)),
          pytest.raises(ValueError, match="non-Protocol")):
        ops.validate_operations(value, nested=True)


def profiled_finding_case():
    finding = resolved_finding()
    _, policy, template = consumer_scope_case()
    profiles = []
    for key in ("origin", "correction"):
        operation = finding[key]
        name = template["paths"][0]["path"]
        operation["baseline_paths"] = operation["pr"]["changed_paths"] = [name]
        operation["pr"]["file_patches"] = {name: "+synthetic accepted governance\n"}
        profile = deepcopy(template)
        profile["base_sha"] = operation["pr"]["base_sha"]
        profiles.append(profile)
    parent = deepcopy(finding["origin"])
    parent["late_findings"] = [finding]
    return parent, policy, profiles


def qualify_profiled_finding(value, policy, profiles):
    new = execution147()
    outer = deepcopy(consumer_scope_case()[2])
    return new.validate_qualification(
        value, policy, new.digest(policy), scope_profile=outer,
        expected_scope_digest=new.digest(outer), nested_scope_profiles=profiles,
        expected_nested_scope_digest=new.digest(profiles))


def test_nested_finding_profiles_bind_each_accepted_base_without_inheritance():
    value, policy, profiles = profiled_finding_case()
    for key, profile in zip(("origin", "correction"), profiles, strict=True):
        assert qualify_consumer(value["late_findings"][0][key], policy, profile)["result"] == "PASS"
    with pytest.raises(ValueError, match="non-Protocol"):
        qualify_consumer(value, policy, profiles[0])
    result = qualify_profiled_finding(value, policy, profiles)
    assert result["result"] == "PASS"
    assert result["nested_scope_profiles_sha256"] == execution147().digest(profiles)
    with pytest.raises(ValueError, match="non-Protocol"):
        qualify_consumer(value, policy, profiles[0])  # Successful context never leaks.


@pytest.mark.parametrize("damage", ["missing_origin", "missing_correction", "wrong_base",
                                  "wrong_repository", "duplicate", "unused", "no_finding",
                                  "policy_edit", "ci", "resolution"])
def test_nested_finding_profiles_cannot_borrow_authority_or_skip_gates(damage):
    value, policy, profiles = profiled_finding_case()
    finding = value["late_findings"][0]
    if damage == "missing_origin":
        profiles.pop(0)
    elif damage == "missing_correction":
        profiles.pop()
    elif damage == "wrong_base":
        profiles[1]["base_sha"] = "f" * 40
    elif damage == "wrong_repository":
        profiles[1]["repository"] = "brickms/brickms"
    elif damage == "duplicate":
        profiles.append(deepcopy(profiles[0]))
    elif damage == "unused":
        extra = deepcopy(profiles[0])
        extra["base_sha"] = "f" * 40
        profiles.append(extra)
    elif damage == "no_finding":
        value["late_findings"] = []
    elif damage == "policy_edit":
        operation = finding["correction"]
        path = profiles[1]["policy_path"]
        operation["pr"]["changed_paths"] = sorted([*operation["pr"]["changed_paths"], path])
        operation["baseline_paths"] = operation["pr"]["changed_paths"].copy()
        operation["pr"]["file_patches"][path] = "+candidate scope\n"
    elif damage == "ci":
        finding["correction"]["ci"]["runs"][0]["attempts"][-1] = attempt(conclusion="FAILURE")
    else:
        finding["resolution"]["is_resolved"] = False
    with pytest.raises(ValueError):
        qualify_profiled_finding(value, policy, profiles)
    clean, policy, profiles = profiled_finding_case()
    with pytest.raises(ValueError, match="non-Protocol"):
        qualify_consumer(clean, policy, profiles[0])  # Failure restores both contexts too.


def test_nested_finding_profiles_require_independent_complete_unchanged_trust():
    value, policy, profiles = profiled_finding_case()
    new = execution147()
    for supplied, expected in ((profiles, None), (None, new.digest(profiles)),
                               (profiles, "0" * 64)):
        with pytest.raises(ValueError):
            new.validate_qualification(
                value, policy, new.digest(policy), scope_profile=profiles[0],
                expected_scope_digest=new.digest(profiles[0]), nested_scope_profiles=supplied,
                expected_nested_scope_digest=expected)
    value["nested_scope_profiles"] = profiles
    with pytest.raises(ValueError, match="missing or extra fields"):
        qualify_consumer(value, policy, profiles[0])
