"""Core policy coherence, bounded compensation and evidence freshness.

Host-selected contracts and observations require independent provenance. Digests
bind retained bytes, not authority. No function executes an effect or edits state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

DIMENSIONS = frozenset(
    {
        "HEAD",
        "BASE",
        "MASTER",
        "PR_STATE",
        "REVIEWS_THREADS",
        "POLICY",
        "PIN",
        "ENVIRONMENT",
        "AUTHORITY",
        "REPOSITORY",
    }
)
ROUTES = {
    "PRODUCT/v2": ("PRODUCT", "REPOSITORY_POLICY"),
    # The original lifecycle permits both policies, with effects and stronger
    # product gates remaining independent. Only the adopted v2 narrows this.
    "PRODUCT/v1": ("PRODUCT", ("NO_PRODUCTION", "REPOSITORY_POLICY")),
    "PROTOCOL/v1": ("PROTOCOL", "NO_PRODUCTION"),
}
IDENTITY = frozenset(
    {
        "owner",
        "repository",
        "pr",
        "branch",
        "workstream",
        "workstream_class",
        "binding_basis",
        "checkpoint_basis",
        "checkpoint_id",
        "authority",
        "level_c_consent",
    }
)
CHECKPOINT_FIELDS = IDENTITY | {"state", "effect_policy", "observed_effects"}
MINIMUM_DEPENDENCIES = {
    "QUALIFICATION": {
        "HEAD",
        "BASE",
        "MASTER",
        "PR_STATE",
        "REVIEWS_THREADS",
        "POLICY",
        "PIN",
        "ENVIRONMENT",
        "AUTHORITY",
        "REPOSITORY",
    },
    "CI": {"HEAD", "BASE", "ENVIRONMENT", "REPOSITORY"},
    "EFFECTS": {"HEAD", "BASE", "POLICY", "REPOSITORY"},
    "REVIEWS": {"HEAD", "PR_STATE", "REVIEWS_THREADS", "POLICY", "REPOSITORY"},
    "ANCESTRY": {"HEAD", "BASE", "MASTER", "REPOSITORY"},
    "SOURCE_INTEGRITY": {"PIN", "REPOSITORY"},
    "AUTHORIZATION": {"AUTHORITY", "REPOSITORY"},
    "REPOSITORY_IDENTITY": {"REPOSITORY"},
    "MASTER_INTEGRITY": {"MASTER", "REPOSITORY"},
    "PR_STATE": {"PR_STATE", "REPOSITORY"},
}


class PolicyError(ValueError):
    def __init__(self, category, message):
        self.category = category
        super().__init__(f"{category}: {message}")


def require(condition, message, category="BOUND_TERMINAL"):
    if not condition:
        raise PolicyError(category, message)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def exact(value, fields, label):
    require(
        isinstance(value, dict) and set(value) == set(fields),
        f"{label}: incomplete or unsupported fields",
    )
    return value


def trusted(value, expected, label):
    require(
        isinstance(expected, str) and digest(value) == expected,
        f"{label}: independently selected evidence missing or changed",
    )


def sha(value, label):
    require(
        isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None,
        f"{label}: exact commit required",
    )
    return value


def require_fresh_observation(value):
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(timestamp.tzinfo is not None, "timezone required", "STALE_EVIDENCE")
        age = (datetime.now(UTC) - timestamp).total_seconds()
    except (TypeError, AttributeError, ValueError) as exc:
        raise PolicyError("STALE_EVIDENCE", "invalid live observation time") from exc
    require(-30 <= age <= 900, "live recovery observations expired", "STALE_EVIDENCE")


def validate_contract(contract, expected_digest):
    trusted(contract, expected_digest, "adopted routing")
    exact(
        contract,
        {"schema", "repository", "source_commit", "reference", "routing"},
        "adopted contract",
    )
    require(contract["schema"] == "agent-policy-contract/v1", "adopted contract schema")
    require(contract["routing"] in ROUTES, "unsupported adopted route", "EXTERNAL_DEPENDENCY")
    require(
        all(
            isinstance(contract[k], str) and contract[k]
            for k in ("repository", "source_commit", "reference")
        ),
        "contract identity missing",
    )
    sha(contract["source_commit"], "adopted source")
    return ROUTES[contract["routing"]]


def resolve_policy(
    *,
    contract,
    trusted_contract,
    workstream,
    workstream_class,
    selected_policy,
    observed_effects,
    production_authority,
):
    """One decision for explain and bind; effects/capability are independent inputs."""
    expected_class, expected_policy = validate_contract(contract, trusted_contract)
    require(
        isinstance(workstream, str) and bool(workstream), "workstream missing", "INPUT_MISMATCH"
    )
    require(
        selected_policy in {"NO_PRODUCTION", "REPOSITORY_POLICY"},
        "unsupported selected policy",
        "INPUT_MISMATCH",
    )
    require(
        observed_effects in {"NO_PRODUCTION", "PRODUCTION", "UNKNOWN"},
        "unsupported observed effects",
        "INPUT_MISMATCH",
    )
    require(
        isinstance(production_authority, dict)
        and set(production_authority) == {"production", "deploy", "migrate"}
        and all(type(v) is bool for v in production_authority.values()),
        "complete independent production capability required",
        "AUTHORITY_BLOCKED",
    )
    incompatibilities = []
    allowed = (expected_policy,) if isinstance(expected_policy, str) else expected_policy
    if workstream_class != expected_class or selected_policy not in allowed:
        incompatibilities.append("POLICY_ROUTING_MISMATCH")
    if observed_effects == "UNKNOWN":
        incompatibilities.append("UNKNOWN_EFFECTS")
    if selected_policy == "NO_PRODUCTION" and observed_effects == "PRODUCTION":
        incompatibilities.append("PRODUCTION_EFFECTS_BLOCKED")
    return {
        "schema": "agent-policy-decision/v1",
        "workstream": workstream,
        "workstream_class": workstream_class,
        "resolved_class": expected_class,
        "routing": contract["routing"],
        "contract": contract["reference"],
        "contract_sha256": trusted_contract,
        "expected_policy": expected_policy
        if isinstance(expected_policy, str)
        else list(expected_policy),
        "selected_policy": selected_policy,
        "observed_effects": observed_effects,
        "production_authority": deepcopy(production_authority),
        "new_capabilities": [],
        "bind_allowed": not incompatibilities,
        "incompatibilities": incompatibilities,
        "next_action": "BIND"
        if not incompatibilities
        else "Use the adopted route and its derived policy; recompute the complete delta. "
        "For an existing BOUND checkpoint use only the typed policy recovery.",
    }


def require_policy_coherence(**kwargs):
    decision = resolve_policy(**kwargs)
    require(
        decision["bind_allowed"],
        f"received {decision['workstream_class']}/{decision['selected_policy']}; "
        f"expected {decision['resolved_class']}/{decision['expected_policy']} via "
        f"{decision['routing']} ({decision['contract']}); "
        f"effects={decision['observed_effects']}; {decision['next_action']}",
        "INPUT_MISMATCH",
    )
    return decision


def evidence_freshness(evidence, current):
    """Retain every original result; classify reuse without manufacturing PASS."""
    require(
        isinstance(current, dict) and set(current) == DIMENSIONS,
        "complete current dependency coordinates required",
        "STALE_EVIDENCE",
    )
    require(isinstance(evidence, list), "evidence inventory required", "STALE_EVIDENCE")
    results, seen = [], set()

    def known(coordinate):
        return (
            isinstance(coordinate, str)
            and bool(coordinate.strip())
            and coordinate not in {"UNKNOWN", "UNBOUND", "UNASSIGNED", "UNAVAILABLE"}
        )

    for row in evidence:
        exact(row, {"id", "gate", "dependencies", "coordinates", "result"}, "evidence")
        require(
            isinstance(row["id"], str) and row["id"] not in seen,
            "duplicate evidence identity",
            "STALE_EVIDENCE",
        )
        seen.add(row["id"])
        require(row["gate"] in MINIMUM_DEPENDENCIES, "unclassified gate", "STALE_EVIDENCE")
        deps = row["dependencies"]
        require(
            isinstance(deps, list)
            and all(isinstance(d, str) for d in deps)
            and len(deps) == len(set(deps))
            and set(deps) <= DIMENSIONS
            and MINIMUM_DEPENDENCIES[row["gate"]] <= set(deps),
            "missing mandatory gate dependencies",
            "STALE_EVIDENCE",
        )
        require(
            isinstance(row["coordinates"], dict) and set(row["coordinates"]) == set(deps),
            "incomplete evidence coordinates",
            "STALE_EVIDENCE",
        )
        changed = sorted(
            d
            for d in deps
            if not known(current[d])
            or not known(row["coordinates"][d])
            or row["coordinates"][d] != current[d]
        )
        results.append(
            {
                "id": row["id"],
                "result": deepcopy(row["result"]),
                "reuse": "STALE_EVIDENCE" if changed else "REUSABLE",
                "invalidators": changed,
            }
        )
    return results


def plan_policy_recovery(*, request, evidence, trusted_evidence, contract, trusted_contract):
    """Allow only a policy mismatch; the host supplies verified complete observations.

    Host provenance must establish actual Git objects/history, native classification
    and live PR state. A candidate's booleans or this digest cannot establish them.
    """
    exact(request, {"operation", "owner", "expected_head"}, "recovery request")
    require(request["operation"] == "RECOVER_BOUND_POLICY", "unsupported recovery operation")
    trusted(evidence, trusted_evidence, "complete recovery observations")
    exact(
        evidence,
        {
            "checkpoint",
            "original_checkpoint",
            "repository",
            "branch",
            "head",
            "base",
            "master",
            "expected_base",
            "expected_master",
            "pr",
            "pr_state",
            "viewer",
            "clean",
            "binding",
            "history",
            "history_complete",
            "ancestry",
            "delta",
            "events",
            "events_complete",
            "observed_at",
            "dimensions",
            "evidence",
        },
        "observations",
    )
    require_fresh_observation(evidence["observed_at"])
    original = exact(evidence["original_checkpoint"], CHECKPOINT_FIELDS, "original checkpoint")
    checkpoint = exact(evidence["checkpoint"], CHECKPOINT_FIELDS, "current checkpoint")
    require(
        all(
            isinstance(checkpoint[k], str)
            and checkpoint[k].strip()
            and checkpoint[k] not in {"UNKNOWN", "UNBOUND", "UNASSIGNED"}
            for k in ("owner", "repository", "branch", "workstream", "workstream_class")
        ),
        "incomplete checkpoint identity",
    )
    require(
        type(checkpoint["pr"]) is int and checkpoint["pr"] > 0, "exact original PR number required"
    )
    require(original["state"] == checkpoint["state"] == "BOUND", "BOUND required")
    require(checkpoint == original, "checkpoint altered after original binding")
    require(request["owner"] == evidence["viewer"] == checkpoint["owner"], "owner mismatch")
    for field in ("repository", "branch", "pr"):
        require(evidence[field] == checkpoint[field], f"{field} mismatch")
    require(request["expected_head"] == evidence["head"], "unexpected head")
    for field in ("head", "base", "master", "expected_base", "expected_master"):
        sha(evidence[field], field)
    for field in ("binding_basis", "checkpoint_basis", "checkpoint_id"):
        sha(checkpoint[field], field)
    require(evidence["clean"] is True, "dirty working tree")
    require(evidence["pr_state"] == "OPEN", "owner PR must be open")
    require(
        evidence["base"] == evidence["expected_base"]
        and evidence["master"] == evidence["expected_master"],
        "base/master drift",
    )
    require(
        evidence["binding"] == {k: checkpoint[k] for k in IDENTITY},
        "original binding or immutable identity mismatch",
    )
    require(contract["repository"] == checkpoint["repository"], "contract repository mismatch")
    ancestry = exact(
        evidence["ancestry"],
        {"basis_to_head", "checkpoint_basis_to_head", "base_to_head", "base_to_master"},
        "ancestry",
    )
    require(all(value is True for value in ancestry.values()), "incompatible ancestry")
    require(evidence["history_complete"] is True, "incomplete checkpoint history")
    history = evidence["history"]
    require(
        isinstance(history, list) and 0 < len(history) <= 100000,
        "bounded complete history required",
    )
    nodes = {}
    for row in history:
        exact(row, {"commit", "parents", "checkpoint_sha256"}, "historical commit")
        sha(row["commit"], "historical commit")
        require(row["commit"] not in nodes, "duplicate historical commit")
        nodes[row["commit"]] = row
        require(row["checkpoint_sha256"] == digest(original), "checkpoint history tampered")
        require(
            isinstance(row["parents"], list) and bool(row["parents"]),
            "historical parents missing",
        )
        for parent in row["parents"]:
            sha(parent, "historical parent")
        require(len(set(row["parents"])) == len(row["parents"]), "duplicate historical parent")
    require(
        checkpoint["checkpoint_id"] in nodes
        and evidence["head"] in nodes
        and checkpoint["binding_basis"] in nodes[checkpoint["checkpoint_id"]]["parents"],
        "history endpoints mismatch",
    )
    # Full DAG, not a linear ordering: retain both sides of a merge. Only exact
    # independently proved original/upstream anchors can terminate the inventory.
    boundaries = {
        checkpoint["binding_basis"],
        checkpoint["checkpoint_basis"],
        evidence["base"],
        evidence["master"],
    } - nodes.keys()
    children = {commit: [] for commit in nodes}
    indegree = {}
    for commit, row in nodes.items():
        require(
            all(parent in nodes or parent in boundaries for parent in row["parents"]),
            "history gap or omitted merge parent",
        )
        indegree[commit] = sum(parent in nodes for parent in row["parents"])
        for parent in row["parents"]:
            if parent in nodes:
                children[parent].append(commit)
    queue = [commit for commit, count in indegree.items() if count == 0]
    processed = 0
    while queue:
        commit = queue.pop()
        processed += 1
        for child in children[commit]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    require(processed == len(nodes), "cyclic checkpoint history")
    reachable, queue = set(), [evidence["head"]]
    while queue:
        commit = queue.pop()
        if commit in reachable:
            continue
        reachable.add(commit)
        queue.extend(p for p in nodes[commit]["parents"] if p in nodes)
    require(reachable == nodes.keys(), "unrelated or orphan historical commits")
    delta = exact(evidence["delta"], {"base", "head", "complete", "changes"}, "current delta")
    require(
        delta["base"] == evidence["base"]
        and delta["head"] == evidence["head"]
        and delta["complete"] is True,
        "incomplete or stale full delta",
    )
    require(isinstance(delta["changes"], list), "delta paths missing")
    effects, paths = [], set()
    for change in delta["changes"]:
        exact(change, {"path", "effect"}, "delta change")
        require(
            isinstance(change["path"], str) and change["path"] and change["path"] not in paths,
            "invalid/duplicate delta path",
        )
        paths.add(change["path"])
        require(change["effect"] in {"NO_PRODUCTION", "PRODUCTION"}, "UNKNOWN effects")
        effects.append(change["effect"])
    observed = "PRODUCTION" if "PRODUCTION" in effects else "NO_PRODUCTION"
    decision = resolve_policy(
        contract=contract,
        trusted_contract=trusted_contract,
        workstream=checkpoint["workstream"],
        workstream_class=checkpoint["workstream_class"],
        selected_policy=checkpoint["effect_policy"],
        observed_effects=observed,
        production_authority=checkpoint["authority"],
    )
    require(
        decision["resolved_class"] == checkpoint["workstream_class"], "workstream class mismatch"
    )
    require(
        "POLICY_ROUTING_MISMATCH" in decision["incompatibilities"]
        and isinstance(decision["expected_policy"], str),
        "no allow-listed policy mismatch",
    )
    require(
        observed == checkpoint["observed_effects"] == "NO_PRODUCTION",
        "recovery cannot introduce production effects or authority",
        "AUTHORITY_BLOCKED",
    )
    corrected = deepcopy(checkpoint)
    corrected["effect_policy"] = decision["expected_policy"]
    require_policy_coherence(
        contract=contract,
        trusted_contract=trusted_contract,
        workstream=corrected["workstream"],
        workstream_class=corrected["workstream_class"],
        selected_policy=corrected["effect_policy"],
        observed_effects=observed,
        production_authority=corrected["authority"],
    )
    require(
        isinstance(evidence["events"], list) and evidence["events_complete"] is True,
        "complete historical event inventory required",
    )
    require(
        evidence["dimensions"].get("HEAD") == evidence["head"]
        and evidence["dimensions"].get("BASE") == evidence["base"]
        and evidence["dimensions"].get("MASTER") == evidence["master"]
        and evidence["dimensions"].get("POLICY") == checkpoint["effect_policy"]
        and evidence["dimensions"].get("REPOSITORY") == checkpoint["repository"]
        and evidence["dimensions"].get("PR_STATE") == "OPEN"
        and evidence["dimensions"].get("PIN") == contract["source_commit"]
        and evidence["dimensions"].get("AUTHORITY")
        == digest(
            {"authority": checkpoint["authority"], "level_c_consent": checkpoint["level_c_consent"]}
        ),
        "recovery dependency coordinates mismatch",
        "STALE_EVIDENCE",
    )
    evidence_freshness(evidence["evidence"], evidence["dimensions"])
    plan = {
        "schema": "agent-bound-policy-compensation/v1",
        "diagnostic": "BOUND_RECOVERABLE",
        "operation": "RECOVER_BOUND_POLICY",
        "reason": "POLICY_ROUTING_MISMATCH",
        "original_checkpoint": deepcopy(original),
        "corrected_checkpoint": corrected,
        "parent_head": evidence["head"],
        "base": evidence["base"],
        "master": evidence["master"],
        "contract_sha256": trusted_contract,
        "observations_sha256": trusted_evidence,
        "contract": deepcopy(contract),
        "delta_sha256": digest(delta),
        "history_sha256": digest(history),
        "events_sha256": digest(evidence["events"]),
        "evidence_sha256": digest(evidence["evidence"]),
        "dimensions": deepcopy(evidence["dimensions"]),
        "new_capabilities": [],
        "commit_required": True,
        "qualified": False,
    }
    plan["plan_sha256"] = digest(plan)
    plan["commit_subject"] = "Protocol policy compensation " + plan["plan_sha256"]
    return plan


def verify_policy_compensation(
    *, plan, trusted_plan, compensation, trusted_compensation, previous_evidence, current_dimensions
):
    """The host proves actual bytes/objects; only the exact planned child is accepted."""
    trusted(plan, trusted_plan, "recovery plan")
    exact(
        plan,
        {
            "schema",
            "diagnostic",
            "operation",
            "reason",
            "original_checkpoint",
            "corrected_checkpoint",
            "parent_head",
            "base",
            "master",
            "contract_sha256",
            "observations_sha256",
            "contract",
            "delta_sha256",
            "history_sha256",
            "events_sha256",
            "evidence_sha256",
            "dimensions",
            "new_capabilities",
            "commit_required",
            "qualified",
            "plan_sha256",
            "commit_subject",
        },
        "typed recovery plan",
    )
    unsigned = {k: v for k, v in plan.items() if k not in {"plan_sha256", "commit_subject"}}
    require(
        digest(unsigned) == plan["plan_sha256"]
        and plan["commit_subject"] == "Protocol policy compensation " + plan["plan_sha256"],
        "recovery plan identity changed",
    )
    require(
        plan["schema"] == "agent-bound-policy-compensation/v1"
        and plan["operation"] == "RECOVER_BOUND_POLICY"
        and plan["reason"] == "POLICY_ROUTING_MISMATCH"
        and plan["diagnostic"] == "BOUND_RECOVERABLE"
        and plan["new_capabilities"] == []
        and plan["commit_required"] is True
        and plan["qualified"] is False,
        "invalid recovery plan semantics",
    )
    before = exact(plan["original_checkpoint"], CHECKPOINT_FIELDS, "planned original checkpoint")
    after = exact(plan["corrected_checkpoint"], CHECKPOINT_FIELDS, "planned corrected checkpoint")
    require(
        {k for k in before if before[k] != after[k]} == {"effect_policy"}
        and before["state"] == after["state"] == "BOUND"
        and before["observed_effects"] == after["observed_effects"] == "NO_PRODUCTION",
        "recovery plan changes immutable fields or effects",
    )
    require(plan["contract"]["repository"] == before["repository"], "plan repository mismatch")
    decision = require_policy_coherence(
        contract=plan["contract"],
        trusted_contract=plan["contract_sha256"],
        workstream=after["workstream"],
        workstream_class=after["workstream_class"],
        selected_policy=after["effect_policy"],
        observed_effects=after["observed_effects"],
        production_authority=after["authority"],
    )
    require(isinstance(decision["expected_policy"], str), "no deterministic recovery policy")
    trusted(compensation, trusted_compensation, "observed compensation")
    require(
        digest(previous_evidence) == plan["evidence_sha256"],
        "historical gate inventory changed or omitted",
        "STALE_EVIDENCE",
    )
    exact(
        compensation,
        {
            "head",
            "parents",
            "subject",
            "before",
            "after",
            "changed_fields",
            "other_changes",
            "history_sha256",
            "events_sha256",
            "full_effects",
            "observed_at",
        },
        "compensation",
    )
    require_fresh_observation(compensation["observed_at"])
    sha(compensation["head"], "compensation head")
    require(
        compensation["head"] != plan["parent_head"]
        and compensation["parents"] == [plan["parent_head"]],
        "new direct-child compensation commit required",
    )
    require(compensation["subject"] == plan["commit_subject"], "compensation marker mismatch")
    require(
        compensation["before"] == plan["original_checkpoint"]
        and compensation["after"] == plan["corrected_checkpoint"]
        and compensation["changed_fields"] == ["effect_policy"]
        and compensation["other_changes"] == [],
        "nonminimal or immutable field change",
    )
    require(
        compensation["history_sha256"] == plan["history_sha256"]
        and compensation["events_sha256"] == plan["events_sha256"],
        "historical evidence missing or rewritten",
    )
    require(
        compensation["full_effects"] == "NO_PRODUCTION",
        "compensation authority/effect escalation",
        "AUTHORITY_BLOCKED",
    )
    require(
        current_dimensions["HEAD"] == compensation["head"]
        and current_dimensions["BASE"] == plan["base"]
        and current_dimensions["MASTER"] == plan["master"]
        and current_dimensions["POLICY"] == plan["corrected_checkpoint"]["effect_policy"]
        and all(
            current_dimensions[d] == plan["dimensions"][d]
            for d in ("REPOSITORY", "AUTHORITY", "PIN", "PR_STATE")
        ),
        "new candidate coordinate mismatch",
        "STALE_EVIDENCE",
    )
    return {
        "operation": "POLICY_COMPENSATED",
        "head": compensation["head"],
        "plan_sha256": plan["plan_sha256"],
        "original_checkpoint_preserved": True,
        "evidence": evidence_freshness(previous_evidence, current_dimensions),
        "qualification": "REQUIRED",
        "qualified": False,
        "new_capabilities": [],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "explain-before-bind",
            "guard-before-bind",
            "plan-policy-recovery",
            "verify-policy-compensation",
            "evidence-freshness",
        ],
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--trusted", type=Path, required=True)
    args = parser.parse_args()
    try:
        data = json.loads(args.input.read_text(encoding="utf-8"))
        trust = json.loads(args.trusted.read_text(encoding="utf-8"))
        require(isinstance(data, dict) and isinstance(trust, dict), "object input required")
        require(not set(data) & set(trust), "candidate cannot override host-selected trust")
        function = {
            "explain-before-bind": resolve_policy,
            "guard-before-bind": require_policy_coherence,
            "plan-policy-recovery": plan_policy_recovery,
            "verify-policy-compensation": verify_policy_compensation,
            "evidence-freshness": evidence_freshness,
        }[args.command]
        result = function(**data, **trust)
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(
            json.dumps(
                {
                    "result": "BLOCKED",
                    "diagnostic": getattr(error, "category", "INPUT_MISMATCH"),
                    "reason": str(error),
                    "qualified": False,
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
