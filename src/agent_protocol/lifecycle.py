"""Typed preconditions and plans; no credentials, Git writes or network effects."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

from .ledger import apply, digest, exact, require, sha
from .qualification import policy_decision

COORDINATES = frozenset(
    {
        "HEAD",
        "BASE",
        "MASTER",
        "REVIEWS",
        "PIN",
        "POLICY",
        "RUNTIME",
        "AUTHORITY",
        "REPOSITORY",
        "PR_STATE",
    }
)
DEPENDENCIES = {
    "CI": {"HEAD", "BASE", "RUNTIME", "REPOSITORY"},
    "EFFECTS": {"HEAD", "BASE", "POLICY", "REPOSITORY"},
    "REVIEWS": {"HEAD", "REVIEWS", "PR_STATE", "POLICY", "REPOSITORY"},
    "ANCESTRY": {"HEAD", "BASE", "MASTER", "REPOSITORY"},
    "SOURCE": {"PIN", "REPOSITORY"},
    "AUTHORIZATION": {"AUTHORITY", "REPOSITORY"},
    "NATIVE": {"HEAD", "BASE", "RUNTIME", "POLICY", "REPOSITORY"},
    "QUALIFICATION": COORDINATES,
}


def coordinates(value):
    exact(value, " ".join(COORDINATES), "coordinates")
    require(
        all(isinstance(v, str) and v and v != "UNKNOWN" for v in value.values()),
        "Unknown evidence coordinate",
    )
    for field in ("HEAD", "BASE", "MASTER", "PIN"):
        sha(value[field])
    require(value["PR_STATE"] in {"OPEN", "MERGED", "CLOSED"}, "Unknown PR state")
    return value


def freshness(evidence, current):
    coordinates(current)
    exact(evidence, "id gate dependencies coordinates result source", "gate evidence")
    require(evidence["gate"] in DEPENDENCIES, "Unknown gate cannot be declared independent")
    deps = evidence["dependencies"]
    require(
        isinstance(deps, list)
        and len(set(deps)) == len(deps)
        and DEPENDENCIES[evidence["gate"]] <= set(deps) <= COORDINATES,
        "Mandatory evidence dependency omitted",
    )
    require(set(evidence["coordinates"]) == set(deps), "Incomplete evidence coordinates")
    require(evidence["result"] in {"PASS", "FAIL", "NOT_RUN", "DEFERRED"}, "Unknown gate result")
    invalidators = sorted(k for k in deps if evidence["coordinates"][k] != current[k])
    return {
        "state": "STALE_EVIDENCE" if invalidators else "REUSABLE",
        "result": evidence["result"],
        "invalidators": invalidators,
    }


def validate_observation(state, observation, authority, now):
    """Authority is separately authenticated/selected by the accepted host.

    A candidate cannot supply this object through event payload or PR body. The
    host retains raw authenticated API/Git/signature sources, with exact grants.
    The pure engine deliberately cannot establish authentication by hashing JSON.
    """
    exact(
        authority,
        "identity principal operations capabilities policy pin grants signer_registry",
        "host authority",
    )
    require(authority["identity"] == state["identity"], "Authority targets another workstream")
    require(authority["principal"] == state["owner"], "Host principal does not own this workstream")
    require(authority["signer_registry"], "Independent signer authority required")
    exact(
        observation,
        "identity head coordinates observed_at effects gates history material merge post_merge",
        "observation",
    )
    require(observation["identity"] == state["identity"], "Observed identity changed")
    current = coordinates(observation["coordinates"])
    require(observation["head"] == current["HEAD"], "Observed head ambiguity")
    instant = datetime.strptime(observation["observed_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=UTC
    )
    require(
        0 <= (now - instant).total_seconds() <= 900, "Live observations expired or from the future"
    )
    require(authority["pin"] == current["PIN"], "Accepted pin differs from observations")
    require(digest(authority["policy"]) == current["POLICY"], "Policy coordinates differ")
    require(
        digest(
            {
                k: authority[k]
                for k in ("identity", "principal", "operations", "capabilities", "signer_registry")
            }
        )
        == current["AUTHORITY"],
        "Authority coordinates differ",
    )
    require(digest(authority["identity"]) == current["REPOSITORY"], "Repository coordinates differ")
    require(
        observation["effects"] in {"NO_PRODUCTION", "PRODUCTION"}, "Unknown effects refuse binding"
    )
    require(
        observation["history"] and observation["material"],
        "Complete authenticated history and durable material required",
    )
    if state["status"] != "NEW":
        require(
            authority["capabilities"] == state["capabilities"],
            "Lifecycle cannot grant or change capabilities",
        )
        require(
            authority["policy"] == state["policy"],
            "Policy change needs separately qualified migration",
        )
    return current


def evaluate(state, request, observation, authority, *, now=None):
    """Explain is this same evaluation without committing the returned event."""
    now = now or datetime.now(UTC)
    exact(request, "operation operation_id expected_tip expected_head parameters", "request")
    prior = state["operations"].get(request["operation_id"])
    if prior is not None:
        require(
            authority["identity"] == state["identity"] and authority["principal"] == prior["actor"],
            "Retry principal changed",
        )
        require(
            prior["request_sha256"] == digest(request), "Operation ID reused for different request"
        )
        return {"event": deepcopy(prior), "expected_tip": prior["expected_previous"]}
    require(request["expected_tip"] == state["tip"], "Concurrent ledger head changed")
    operation = request["operation"]
    require(operation in authority["operations"], "Host lacks explicit operation authority")
    current = validate_observation(state, observation, authority, now)
    require(request["expected_head"] == observation["head"], "Unexpected remote candidate head")
    allowed_pr_states = (
        {"MERGED"}
        if operation in {"RECONCILE", "CLOSE"}
        else {"OPEN", "CLOSED"}
        if operation == "ABANDON"
        else {"OPEN"}
    )
    require(current["PR_STATE"] in allowed_pr_states, "Unexpected PR state for operation")
    # One preserved policy resolver serves explain and every write path.
    decision = policy_decision(
        authority["policy"],
        state["identity"],
        observation["effects"],
        authority["capabilities"],
    )
    require(
        decision["allowed"] is True and not decision["new_capabilities"],
        "Policy/effect/capability mismatch",
    )
    p = request["parameters"]
    if operation == "START":
        exact(p, "", "start parameters")
        payload = {
            "identity": state["identity"],
            "coordinates": current,
            "policy": authority["policy"],
            "capabilities": authority["capabilities"],
        }
    elif operation == "REFRESH":
        exact(p, "", "refresh parameters")
        payload = {"previous_head": state["head"], "coordinates": current}
    else:
        require(
            state["coordinates"] == current
            or operation in {"RECONCILE", "RECONCILE_NOT_APPLIED", "CLOSE", "ABANDON"},
            "Changed coordinates require typed refresh before continuing",
        )
        if operation == "INTERRUPT":
            exact(p, "reason", "interrupt parameters")
            payload = {"reason": p["reason"], "material": observation["material"]}
        elif operation == "RESUME":
            exact(p, "", "resume parameters")
            require(
                observation["material"]["restored"] is True,
                "Durable material not restored and verified",
            )
            payload = {"restoration": observation["material"]}
        elif operation == "HANDOFF":
            exact(p, "new_owner grant", "handoff parameters")
            grant = authority["grants"].get(p["grant"])
            require(
                grant
                == {
                    "operation": "HANDOFF",
                    "identity": state["identity"],
                    "from": state["owner"],
                    "to": p["new_owner"],
                    "tip": state["tip"],
                    "head": state["head"],
                },
                "Missing exact independently authenticated handoff grant",
            )
            payload = {
                "new_owner": p["new_owner"],
                "authorization": grant,
                "material": observation["material"],
            }
        elif operation == "QUALIFY":
            exact(p, "", "qualification parameters")
            gates = observation["gates"]
            required = set(authority["policy"]["required_gates"])
            require(
                required and required <= set(DEPENDENCIES) - {"QUALIFICATION"},
                "Unknown or empty gate policy",
            )
            require(
                len({g["id"] for g in gates}) == len(gates)
                and {g["gate"] for g in gates} == required,
                "Incomplete or duplicated qualifying inventory",
            )
            checks = [freshness(g, current) for g in gates]
            require(all(c["state"] == "REUSABLE" for c in checks), "Stale evidence cannot qualify")
            result = "PASS" if all(c["result"] == "PASS" for c in checks) else "FAIL"
            payload = {"result": result, "coordinates": current, "evidence": deepcopy(gates)}
            require(
                not any(
                    e["event"]["operation"] == "QUALIFY" and e["event"]["payload"] == payload
                    for e in state["events"]
                ),
                "Unchanged deterministic qualification cannot be retried",
            )
        elif operation == "INTEGRATE":
            exact(p, "", "integration parameters")
            require(
                state["qualification"] and state["qualification"]["result"] == "PASS",
                "Qualification missing",
            )
            require(
                state["qualification"]["evidence"] == observation["gates"],
                "Qualification evidence changed",
            )
            operation_id = next(
                e["event"]["operation_id"]
                for e in reversed(state["events"])
                if e["event"]["operation"] == "QUALIFY"
            )
            payload = {"qualification_operation": operation_id, "expected_base": current["BASE"]}
        elif operation == "RECONCILE":
            exact(p, "", "reconciliation parameters")
            merge = exact(
                observation["merge"],
                "merge_sha base_sha head_sha tree_sha parents qualified_tree",
                "actual merge",
            )
            require(
                merge["parents"] == [state["coordinates"]["BASE"], state["head"]]
                and merge["base_sha"] == state["coordinates"]["BASE"]
                and merge["head_sha"] == state["head"]
                and merge["tree_sha"] == merge["qualified_tree"],
                "Actual normal merge differs from qualified candidate",
            )
            payload = {k: merge[k] for k in ("merge_sha", "base_sha", "head_sha", "tree_sha")}
        elif operation == "RECONCILE_NOT_APPLIED":
            exact(p, "grant", "non-execution parameters")
            intent = next(
                (
                    row
                    for row in reversed(state["events"])
                    if row["event"]["operation"] == "INTEGRATE"
                ),
                None,
            )
            require(intent is not None, "Integration intent missing")
            grant = authority["grants"].get(p["grant"])
            exact(
                grant,
                "operation identity intent_tip intent_operation kind source quiescent",
                "independently authenticated non-execution",
            )
            require(
                grant["operation"] == operation
                and grant["identity"] == state["identity"]
                and grant["intent_tip"] == intent["commit"]
                and grant["intent_operation"] == intent["event"]["operation_id"]
                and grant["kind"] in {"NOT_DISPATCHED", "DEFINITIVELY_REJECTED"}
                and grant["source"]
                and grant["quiescent"] is True
                and observation["merge"] is None,
                "An open PR or timeout alone cannot prove non-execution",
            )
            payload = {
                "intent_operation": intent["event"]["operation_id"],
                "non_execution": deepcopy(grant),
                "coordinates": current,
            }
        elif operation == "CLOSE":
            exact(p, "next_action next_location", "closure parameters")
            post = observation["post_merge"]
            require(
                post["head"] == state["merge"]["merge_sha"]
                and post["result"] == "PASS"
                and post["complete"] is True
                and post["evidence"],
                "Post-merge delivery not verified",
            )
            payload = {"post_merge_evidence": post, **p}
        elif operation == "ABANDON":
            exact(p, "reason grant", "abandonment parameters")
            grant = authority["grants"].get(p["grant"])
            require(
                grant
                == {
                    "operation": "ABANDON",
                    "identity": state["identity"],
                    "owner": state["owner"],
                    "tip": state["tip"],
                    "head": state["head"],
                },
                "Explicit abandonment authority missing",
            )
            payload = {
                "reason": p["reason"],
                "authorization": grant,
                "material": observation["material"],
            }
        else:
            raise ValueError("Unknown operation")
    event = {
        "schema": "agent-lifecycle-event/v2",
        "operation_id": request["operation_id"],
        "request_sha256": digest(request),
        "operation": operation,
        "actor": authority["principal"],
        "expected_previous": state["tip"],
        "expected_head": request["expected_head"],
        "observed_at": observation["observed_at"],
        "payload": payload,
    }
    preview = deepcopy(state)
    apply(preview, event)
    return {"event": event, "expected_tip": state["tip"]}
