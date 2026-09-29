"""Shared policy/evidence qualification for CLI, adapters and event collectors.

Accepted host configuration supplies policy and authority. Neither a PR body nor
an evidence digest selects those inputs. The historical validators are preserved
and reused verbatim; new repositories do not expand the historical audit scope.
"""

from __future__ import annotations

from .ledger import exact, require
from .source import legacy


def policy_decision(policy, identity, effects, capabilities):
    exact(policy, "contract contract_digest selected required_gates", "accepted policy")
    require(
        policy["contract"]["repository"] == identity["repository"],
        "Policy belongs to another repository",
    )
    decision = legacy("agent_protocol_v1_4_9").require_policy_coherence(
        contract=policy["contract"],
        trusted_contract=policy["contract_digest"],
        workstream=identity["workstream"],
        workstream_class=identity["workstream_class"],
        selected_policy=policy["selected"],
        observed_effects=effects,
        production_authority=capabilities,
    )
    return {"allowed": decision["bind_allowed"], "new_capabilities": decision["new_capabilities"]}


def ci_evidence(inventory, *, repository, head, accepted_policy, now=None):
    """Validate full runs, attempts and jobs under independently selected policy."""
    exact(accepted_policy, "source_commit required_workflows", "accepted CI policy")
    require(inventory["applicability"] == "REQUIRED", "CI cannot be made optional")
    require(inventory["policy_ref"] == accepted_policy["source_commit"], "CI policy changed")
    require(
        inventory["required_workflows"] == accepted_policy["required_workflows"],
        "Candidate cannot select required workflows",
    )
    validator = legacy("agent_protocol_v1_4_2_ops")
    validator.validate_ci(inventory, repository, head, now=now, require_success=False)
    latest = {}
    for run in inventory["runs"]:
        key = (run["workflow"], run["event"])
        if key not in latest or run["run_id"] > latest[key]["run_id"]:
            latest[key] = run
    success = all(run["attempts"][-1]["conclusion"] == "SUCCESS" for run in latest.values())
    return {"result": "PASS" if success else "FAIL", "inventory": inventory}
