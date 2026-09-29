"""Offline execution contracts. Caller-selected trusted inputs never grant authority."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from contextlib import ExitStack
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "protocol147_ops", Path(__file__).with_name("agent_protocol_v1_4_2_ops.py")
)
ops = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ops)

VERSION = "1.4.7"
PHASES = {"START", "RESUME", "IMPLEMENT", "QUALIFY", "POST_MERGE", "CLOSE"}
WORKSTREAMS = {"PRODUCT", "PROTOCOL", "CHECKPOINT_ONLY"}
ROLES = {"ALWAYS", "PROCEDURE", "HISTORICAL"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(ops.canonical(value)).hexdigest()


def read_bound(root, name):
    """Resolve only regular, non-symlink repository paths, including parents."""
    ops.path(name)
    root = Path(root).absolute()
    path = root / name
    require(not any(p.is_symlink() for p in (path, *path.parents)), "symlink document")
    require(path.is_file(), "missing document: " + name)
    return path.read_bytes()


def select_documents(root, manifest, expected_digest, *, workstream, phase, host="WORK"):
    """Trust comes from the independently selected accepted manifest, not its hash."""
    require(digest(manifest) == expected_digest, "untrusted or changed document manifest")
    ops.obj(manifest, "schema protocol_version documents repository_policy", "manifest")
    require(
        manifest["schema"] == "agent-documents/v1"
        and manifest["protocol_version"] in {VERSION, "1.4.8", "1.4.9"},
        "document contract version",
    )
    rows = manifest["documents"]
    require(isinstance(rows, list) and 0 < len(rows) <= 100, "bounded document inventory")
    inventory, content = {}, {}
    for row in rows:
        ops.obj(row, "id path sha256 role workstreams phases hosts requires", "document")
        identity = ops.text(row["id"], "document id")
        require(identity not in inventory, "duplicate document id")
        require(
            row["path"] not in {r["path"] for r in inventory.values()}, "duplicate document path"
        )
        require(row["role"] in ROLES, "unknown document role")
        for key, allowed in (
            ("workstreams", WORKSTREAMS),
            ("phases", PHASES),
            ("hosts", {"WORK", "GIT"}),
        ):
            require(
                isinstance(row[key], list)
                and bool(row[key])
                and len(set(row[key])) == len(row[key])
                and set(row[key]) <= allowed,
                "unknown or duplicate reading condition",
            )
        require(
            isinstance(row["requires"], list)
            and all(isinstance(v, str) for v in row["requires"])
            and len(set(row["requires"])) == len(row["requires"]),
            "invalid references",
        )
        data = read_bound(root, row["path"])
        require(
            hashlib.sha256(data).hexdigest() == ops.sha(row["sha256"], 64),
            "document integrity: " + row["path"],
        )
        content[identity] = data.decode("utf-8")
        inventory[identity] = row
    require(any(r["role"] == "ALWAYS" for r in rows), "cross-cutting rules missing")
    visiting, visited = set(), set()

    def visit(identity):
        require(identity in inventory, "missing document reference: " + identity)
        require(identity not in visiting, "document dependency cycle")
        if identity in visited:
            return
        visiting.add(identity)
        for dependency in inventory[identity]["requires"]:
            visit(dependency)
        visiting.remove(identity)
        visited.add(identity)

    for identity in sorted(inventory):
        visit(identity)
    fallback = workstream not in WORKSTREAMS or phase not in PHASES or host not in {"WORK", "GIT"}
    selected = set()

    def include(identity):
        if identity in selected:
            return
        selected.add(identity)
        for dependency in inventory[identity]["requires"]:
            include(dependency)

    for identity, row in inventory.items():
        if (
            fallback
            or row["role"] == "ALWAYS"
            or (
                row["role"] != "HISTORICAL"
                and (
                    fallback
                    or (
                        workstream in row["workstreams"]
                        and phase in row["phases"]
                        and host in row["hosts"]
                    )
                )
            )
        ):
            include(identity)
    documents = [
        {
            "id": identity,
            "path": inventory[identity]["path"],
            "sha256": inventory[identity]["sha256"],
            "content": content[identity],
        }
        for identity in sorted(selected)
    ]
    return {
        "schema": "agent-document-selection/v1",
        "protocol_version": manifest["protocol_version"],
        "manifest_sha256": expected_digest,
        "selection": "FULL_FALLBACK" if fallback else "EXACT",
        "documents": documents,
        "document_count": len(documents),
        "model_bytes": sum(len(d["content"].encode()) for d in documents),
        "verified_inventory_bytes": sum(len(c.encode()) for c in content.values()),
        "push_qualified": False,
    }


def context_delta(selection, retained, *, trusted_selection, trusted_retained, context_id):
    """Suppress only text the host confirms is still available in this context.

    Run select_documents first: this view never substitutes for inventory integrity.
    The host selects the retained receipt independently; a digest is not provenance.
    """
    require(digest(selection) == trusted_selection, "changed verified selection")
    require(selection.get("schema") == "agent-document-selection/v1", "selection schema")
    ops.text(context_id, "current context identity")
    require(digest(retained) == trusted_retained, "changed retained context")
    ops.obj(retained, "context_id manifest_sha256 documents", "retained context")
    require(isinstance(retained["documents"], dict), "retained documents")
    for path, sha in retained["documents"].items():
        ops.path(path)
        ops.sha(sha, 64)
    reusable = (
        retained["context_id"] == context_id
        and retained["manifest_sha256"] == selection["manifest_sha256"]
        and selection["selection"] == "EXACT"
    )
    result = deepcopy(selection)
    result["schema"] = "agent-document-context/v1"
    result["documents"] = [
        row for row in selection["documents"]
        if not reusable or retained["documents"].get(row["path"]) != row["sha256"]
    ]
    result["selected_document_count"] = selection["document_count"]
    result["document_count"] = len(result["documents"])
    result["model_bytes"] = sum(len(row["content"].encode()) for row in result["documents"])
    result["retained_model_bytes"] = selection["model_bytes"] - result["model_bytes"]
    result["context_receipt"] = {
        "context_id": context_id,
        "manifest_sha256": selection["manifest_sha256"],
        "documents": {
            **(retained["documents"] if reusable else {}),
            **{row["path"]: row["sha256"] for row in selection["documents"]},
        },
    }
    result["push_qualified"] = False
    return result


def validate_qualification(operation, policy, expected_digest, *, now=None,
                           scope_profile=None, expected_scope_digest=None,
                           nested_scope_profiles=None, expected_nested_scope_digest=None):
    """Apply the accepted repository policy without querying remote administration APIs."""
    require(digest(policy) == expected_digest, "changed trusted repository policy")
    ops.obj(
        policy,
        "schema repository required_workflows post_merge_required_workflows review_requirement",
        "policy",
    )
    require(policy["schema"] == "agent-repository-policy/v1", "policy schema")
    require(policy["repository"] == operation["pr"]["repository"], "policy repository")
    required = policy["required_workflows"]
    require(
        isinstance(required, list) and bool(required) and required == sorted(set(required)),
        "closed required workflow inventory",
    )
    require(operation["ci"]["required_workflows"] == required, "required CI policy mismatch")
    post_required = policy["post_merge_required_workflows"]
    require(
        isinstance(post_required, list)
        and bool(post_required)
        and post_required == sorted(set(post_required)),
        "closed post-merge workflow inventory",
    )
    if operation["phase"] == "POST_MERGE":
        require(
            operation["post_merge_ci"]["required_workflows"] == post_required,
            "required post-merge CI policy mismatch",
        )
    require(policy["review_requirement"] in {"NONE", "REPOSITORY"}, "unknown review policy")
    require(
        operation["reviews"]["requirement"] == policy["review_requirement"]
        or (
            policy["review_requirement"] == "NONE"
            and operation["reviews"]["requirement"] == "EXPLICIT_MAINTAINER"
        ),
        "required review policy mismatch",
    )
    require((scope_profile is None) == (expected_scope_digest is None),
            "complete independent Protocol scope authority required")
    require((nested_scope_profiles is None) == (expected_nested_scope_digest is None),
            "complete independent nested Protocol scope authority required")
    with ExitStack() as contexts:
        if scope_profile is not None:
            contexts.enter_context(ops.trusted_protocol_scope(scope_profile, expected_scope_digest))
        if nested_scope_profiles is not None:
            contexts.enter_context(ops.trusted_nested_protocol_scopes(
                nested_scope_profiles, expected_nested_scope_digest))
            nested_bases = {
                (finding[key]["pr"]["repository"], finding[key]["pr"]["base_sha"])
                for finding in operation["late_findings"] for key in ("origin", "correction")
            }
            require(all((p["repository"], p["base_sha"]) in nested_bases
                        for p in nested_scope_profiles), "unused nested Protocol scope base")
        ops.validate_operations(operation, now=now)
    result = {
        "schema": "agent-qualification/v1",
        "protocol_version": VERSION,
        "repository": policy["repository"],
        "base_sha": operation["pr"]["base_sha"],
        "head_sha": operation["pr"]["head_sha"],
        "result": "PASS",
        "policy_sha256": expected_digest,
        "operation_sha256": digest(operation),
        "remote_enforcement": "GITHUB_DECIDES_AT_NORMAL_MERGE",
        "ruleset_observation_required": False,
        "merge_performed": False,
    }
    if scope_profile is not None:
        result["scope_profile_sha256"] = expected_scope_digest
    if nested_scope_profiles is not None:
        result["nested_scope_profiles_sha256"] = expected_nested_scope_digest
    return result


def campaign_audit(
    evidence, scope, policies, adoption, adoptions, *,
    trusted_scope, trusted_policies, trusted_adoption,
):
    """Reuse all operational audit checks with an independently selected campaign scope.

    The historical five-repository CLI and receipts keep their original semantics.
    No row, current gate or integration is synthesized for a descriptive registry.
    """
    require(digest(scope) == trusted_scope, "changed campaign scope")
    ops.obj(scope, "schema campaign_ref repositories", "campaign scope")
    require(scope["schema"] == "agent-campaign-scope/v1", "campaign scope schema")
    require(scope["campaign_ref"] == evidence["campaign_ref"], "campaign scope reference")
    repositories = scope["repositories"]
    require(isinstance(repositories, list) and repositories == sorted(set(repositories)),
            "exact campaign repository inventory")
    require("gabned/provelume" in repositories and len(repositories) >= 2
            and set(repositories) <= set(ops.PROFILES), "campaign scope repositories")
    accepted = frozenset(repositories)
    require(digest(policies) == trusted_policies, "changed campaign policies")
    require(isinstance(policies, list), "campaign policy inventory")
    bindings = {}
    for item in policies:
        ops.obj(item, "repository pr base_sha head_sha default_sha policy scope_profile",
                "campaign policy")
        key = tuple(item[k] for k in ("repository", "pr", "base_sha", "head_sha", "default_sha"))
        require(key not in bindings, "duplicate campaign policy")
        bindings[key] = item
    used = set()

    def integration_binding(integration):
        pr = integration["pr"]
        key = (pr["repository"], pr["number"], pr["base_sha"], pr["head_sha"],
               integration["merge"]["default_sha"])
        require(key in bindings, "missing independently selected integration policy")
        return key, bindings[key]

    def qualify_operation(operation, *, now=None):
        integrations = [operation] + [finding[key] for finding in operation["late_findings"]
                                      for key in ("origin", "correction")]
        for integration in integrations:
            key, binding = integration_binding(integration)
            policy, profile = binding["policy"], binding["scope_profile"]
            nested_profiles = {}
            for finding in integration["late_findings"]:
                for part in ("origin", "correction"):
                    _, nested_binding = integration_binding(finding[part])
                    nested = nested_binding["scope_profile"]
                    if nested is not None:
                        scope_key = (nested["repository"], nested["base_sha"])
                        require(scope_key not in nested_profiles
                                or nested_profiles[scope_key] == nested,
                                "conflicting independently selected nested scope")
                        nested_profiles[scope_key] = nested
            extra = {}
            if nested_profiles:
                profiles = [nested_profiles[k] for k in sorted(nested_profiles)]
                extra = {"nested_scope_profiles": profiles,
                         "expected_nested_scope_digest": digest(profiles)}
            if profile is not None:
                require(hasattr(ops, "trusted_protocol_scope"),
                        "accepted operational engine lacks Protocol scope profiles")
                extra.update(scope_profile=profile, expected_scope_digest=digest(profile))
            validate_qualification(integration, policy, digest(policy), now=now, **extra)
            used.add(key)
        return operation

    ops.validate_audit_input(evidence, expected_repositories=accepted,
                             operation_validator=qualify_operation)
    ops.validate_audit_input(evidence, now=ops.timestamp(evidence["observed_at"]),
                             expected_repositories=accepted, operation_validator=qualify_operation)
    require(used == set(bindings), "unused campaign policy")
    # The operational manifest covers its versioned engine inventory.
    # Current Work bytes, actual pin and instruction routing need separate proof.
    require(digest(adoption) == trusted_adoption, "changed accepted adoption contract")
    ops.obj(adoption, "schema protocol_version source_repository source_commit "
            "work_files documents_manifest", "accepted adoption")
    require(adoption["schema"] == "agent-campaign-adoption/v1"
            and adoption["protocol_version"] in {"1.4.8", "1.4.9"}
            and adoption["source_repository"] == "gabned/provelume"
            and adoption["source_commit"] == evidence["canonical"]["source_commit"],
            "campaign adoption identity")
    recovery_spec = importlib.util.spec_from_file_location(
        "campaign_recovery", Path(__file__).with_name("agent_protocol_work_recovery.py"))
    recovery = importlib.util.module_from_spec(recovery_spec)
    recovery_spec.loader.exec_module(recovery)
    expected_files = adoption["work_files"]
    require(isinstance(expected_files, list)
            and [f.get("path") for f in expected_files] == list(recovery.WORK_FILES),
            "complete accepted Work inventory required")
    for item in expected_files:
        ops.obj(item, "path mode git_blob sha256", "accepted Work file")
        require(item["mode"] == "100644", "accepted Work mode")
        ops.sha(item["git_blob"])
        ops.sha(item["sha256"], 64)
    manifest = adoption["documents_manifest"]
    ops.obj(manifest, "schema protocol_version documents repository_policy", "accepted routing")
    require(manifest["schema"] == "agent-documents/v1"
            and manifest["protocol_version"] == adoption["protocol_version"],
            "accepted routing version")
    guide = f"docs/agent-development-v{adoption['protocol_version']}.md"
    manifest_path = f".github/agent-protocol/documents-v{adoption['protocol_version']}.json"
    documents = manifest["documents"]
    require(isinstance(documents, list)
            and len({r["path"] for r in documents}) == len(documents), "accepted routing inventory")
    for path in ("AGENTS.md", guide):
        require(sum(r["path"] == path and r["role"] == "ALWAYS" for r in documents) == 1,
                "accepted current instruction route")
    require(isinstance(adoptions, list) and len(adoptions) == len(accepted - {"gabned/nexus"})
            and {r.get("repository") for r in adoptions} == accepted - {"gabned/nexus"},
            "exact executable adoption inventory")
    expected_pin = {"source_repository": adoption["source_repository"],
                    "source_commit": adoption["source_commit"], "files": expected_files}

    def observed_file(item, default):
        ops.obj(item, "path commit_sha mode git_blob content", "observed adoption file")
        ops.path(item["path"])
        require(item["commit_sha"] == default and item["mode"] in {"100644", "100755"}
                and isinstance(item["content"], str), "observed adoption identity")
        require(ops.blob(item["content"].encode()) == item["git_blob"],
                "observed adoption bytes")
        return item["content"]

    defaults = {r["repository"]: r["default_sha"] for r in evidence["repositories"]}
    for row in adoptions:
        ops.obj(row, "repository default_sha files pin_file routing_files", "observed adoption")
        repository = row["repository"]
        default = defaults[repository]
        core = repository == "gabned/provelume"
        require(row["default_sha"] == default, "adoption observed at another default")
        require(isinstance(row["files"], list)
                and [f.get("path") for f in row["files"]]
                == (list(recovery.WORK_FILES) if core else []),
                "complete observed Work inventory required")
        for item, expected in zip(row["files"], expected_files if core else [], strict=True):
            content = observed_file(item, default)
            require(item["mode"] == expected["mode"] and item["git_blob"] == expected["git_blob"]
                    and hashlib.sha256(content.encode()).hexdigest() == expected["sha256"],
                    "observed Work byte or mode drift")
        routes = row["routing_files"]
        runbook = "docs/agent-development-v1.4.2.md" if repository == "gabned/provelume.com" \
            else "docs/runbooks/agent-development-v1.4.2.md"
        expected_routes = ["AGENTS.md", guide, manifest_path] if core else ["AGENTS.md", runbook]
        require(isinstance(routes, list) and [r.get("path") for r in routes] == expected_routes,
                "complete observed instruction routing required")
        for item in routes:
            content = observed_file(item, default)
            require(item["mode"] == "100644", "instruction route mode")
            if core:
                if item["path"] == manifest_path:
                    require(json.loads(content) == manifest, "Core routing manifest drift")
                else:
                    expected = next(r for r in documents if r["path"] == item["path"])
                    require(hashlib.sha256(content.encode()).hexdigest() == expected["sha256"],
                            "Core instruction byte drift")
            else:
                marker = f"## Current execution — Protocol {adoption['protocol_version']}"
                require(re.findall(r"(?m)^## Current execution — Protocol (\S+)$", content)
                        == [adoption["protocol_version"]], "consumer current instruction route")
                current = content.split(marker)[1]
                boundary = re.search(r"(?m)^## ", current)
                generated = marker + (current[:boundary.start()] if boundary else current)
                expected = recovery.adoption_guidance(repository, adoption["protocol_version"])
                separator = generated[len(expected):]
                require(generated.startswith(expected) and (
                    not separator or (boundary is not None and not separator.strip("\n"))),
                        "consumer instruction provenance drift")
        if core:
            require(row["pin_file"] is None, "Core cannot self-adopt")
        else:
            import ast
            item = row["pin_file"]
            pin_path = "scripts/agent/protocol-v1-2.py" if repository == "brickms/brickms" \
                else "tests/agent_protocol_v1_4_2_vendor_test.py"
            require(item["path"] == pin_path and item["mode"] == (
                "100755" if repository == "brickms/brickms" else "100644"),
                "consumer actual pin location/mode")
            try:
                tree = ast.parse(observed_file(item, default))
            except SyntaxError as error:
                raise ValueError("consumer actual Work pin syntax") from error
            pins = [node.value for node in tree.body if isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "WORK_ADAPTER_PIN"
                            for t in node.targets)]
            require(len(pins) == 1 and ast.literal_eval(pins[0]) == expected_pin,
                    "consumer actual Work pin drift")
    return {"schema": "agent-campaign-audit/v1", "protocol_version": adoption["protocol_version"],
            "result": "PASS", "scope": deepcopy(scope), "scope_sha256": trusted_scope,
            "evidence": deepcopy(evidence), "evidence_sha256": digest(evidence),
            "policies_sha256": trusted_policies, "adoption_sha256": trusted_adoption,
            "adoptions_sha256": digest(adoptions)}


def verify_merge_response(response, expected_head, observed_head):
    """A normal GitHub merge denial is terminal for this attempt, never bypassed."""
    ops.sha(expected_head)
    require(expected_head == ops.sha(observed_head), "head moved before merge")
    require(
        isinstance(response, dict) and response.get("merged") is True,
        "GitHub denied or did not prove merge",
    )
    return {"merge_sha": ops.sha(response.get("sha")), "post_merge_verification": "REQUIRED"}


def evidence_summary(observation, reference, *, now=None):
    """Inventory summaries preserve uncertainty and cannot become gate receipts."""
    ops.obj(reference, "id sha256", "evidence reference")
    ops.text(reference["id"], "evidence id")
    require(reference["sha256"] == digest(observation), "evidence summary digest mismatch")
    require(isinstance(observation, dict), "observation object required")
    status = observation.get("status", "UNKNOWN")
    require(status in {"OBSERVED", "UNKNOWN"}, "unknown observation state")
    stamp = observation.get("observed_at")
    try:
        observed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        require(observed.tzinfo is not None, "observation timezone missing")
        age = ((now or datetime.now(UTC)) - observed).total_seconds()
        freshness = "FRESH" if -30 <= age <= 900 else "STALE"
    except (AttributeError, TypeError, ValueError):
        freshness = "UNKNOWN"
    raw = observation.get("response")
    response = raw if isinstance(raw, dict) else {}
    failed = bool(response.get("error")) or (
        isinstance(response.get("status"), int) and response["status"] >= 400
    )
    if failed or raw is None:
        status = "UNKNOWN"
    identity = {
        k: response[k]
        for k in ("full_name", "number", "sha", "head_sha", "run_attempt", "id")
        if isinstance(response.get(k), (str, int)) and not isinstance(response.get(k), bool)
    }
    for field in ("base", "head"):
        nested = response.get(field)
        if isinstance(nested, dict) and isinstance(nested.get("sha"), str):
            identity[field + "_sha"] = nested["sha"]
    endpoint = re.match(
        r"^https://api[.]github[.]com/repos/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?:/|$)",
        observation.get("url", ""),
    )
    if endpoint:
        identity["repository"] = endpoint[1]
    annotations = {}
    for field in ("findings", "uncertainties"):
        values = observation.get(field, [])
        require(isinstance(values, list), "summary annotations must be scalar text lists")
        # Never copy nested tool responses or logs. Longer details belong in
        # the integrity-bound original; the entire transport view is bounded.
        annotations[field] = [
            ops.text(value, "summary text or evidence reference") for value in values
        ]
    result = {
        "schema": "agent-evidence-summary/v1",
        "evidence": deepcopy(reference),
        "status": status,
        "freshness": freshness,
        "observed_at": stamp,
        "complete": observation.get("complete") is True,
        "identity": identity,
        "state": {
            k: response[k]
            for k in ("state", "draft", "merged", "status", "conclusion")
            if k in response
        },
        "findings": annotations["findings"],
        "reused": observation.get("reused") is True,
        "uncertainties": annotations["uncertainties"],
        "qualification": "NOT_EVALUATED",
        "push_qualified": False,
    }
    require(
        len(ops.canonical(result)) <= 8192,
        "summary exceeds transport budget; reference the complete original evidence",
    )
    return result


def reconcile_checkpoint(cache, pr, merge, followups, *, now=None):
    """Derive a view from real merged identity; never rewrite cache or old receipts."""
    # This read-only identity view also covers historical PRODUCT checkpoints.
    # It grants no qualification and does not demand Protocol-only PR body fields
    # or replay an entire product patch merely to establish an observed merge.
    require(isinstance(pr, dict) and pr.get("repository") in ops.PROFILES, "checkpoint repository")
    ops.number(pr.get("number"), "PR number")
    for key in ("base_sha", "head_sha", "tree_sha"):
        ops.sha(pr.get(key))
    ops.observation(pr, now)
    require(pr.get("state") == "CLOSED" and pr.get("draft") is False, "merged PR identity required")
    ops.validate_merge(merge, pr, now)
    require(isinstance(cache, dict) and isinstance(followups, list), "checkpoint inputs")
    open_items, resolved_items, seen = [], [], set()
    for item in followups:
        ops.obj(item, "id owner origin_head state evidence resolution", "follow-up")
        identity = ops.text(item["id"], "finding id")
        require(identity not in seen, "duplicate finding")
        seen.add(identity)
        require(item["origin_head"] == pr["head_sha"], "finding origin mismatch")
        ops.text(item["owner"], "follow-up owner")
        ops.text(item["evidence"], "finding evidence")
        require(item["state"] in {"OPEN", "RESOLVED"}, "unknown follow-up state")
        if item["state"] == "OPEN":
            require(item["resolution"] is None, "open finding claims resolution")
            open_items.append(deepcopy(item))
        else:
            resolution = item["resolution"]
            ops.obj(resolution, "operation thread_ref thread_resolved", "finding resolution")
            ops.validate_operations(resolution["operation"], now=now)
            require(
                resolution["operation"]["phase"] == "POST_MERGE"
                and resolution["thread_resolved"] is True,
                "unverified corrective integration",
            )
            ops.text(resolution["thread_ref"], "resolved thread")
            retained = resolution["operation"]["late_findings"]
            matched = [
                f
                for f in retained
                if (
                    f["id"] == identity
                    and f["thread_ref"] == resolution["thread_ref"]
                    and f["origin"]["pr"]["head_sha"] == pr["head_sha"]
                    and f["origin_pr"] == pr["number"]
                    and f["origin_merge_sha"] == merge["merge_sha"]
                )
            ]
            require(
                len(matched) == 1,
                "complete origin/correction/thread proof required",
            )
            correction = matched[0]["correction"]["merge"]["merge_sha"]
            chain = [c["sha"] for c in merge["ancestry"]]
            require(
                correction in chain and chain.index(correction) < chain.index(merge["merge_sha"]),
                "correction must follow origin in default ancestry",
            )
            resolved_items.append(
                {
                    "id": identity,
                    "owner": item["owner"],
                    "correction_merge_sha": correction,
                    "thread_ref": resolution["thread_ref"],
                    "resolution_sha256": digest(resolution),
                }
            )
    return {
        "schema": "agent-checkpoint-view/v1",
        "repository": pr["repository"],
        "pr": pr["number"],
        "head_sha": pr["head_sha"],
        "merge_sha": merge["merge_sha"],
        "state": "MERGED",
        "followups": open_items,
        "resolved_followups": resolved_items,
        "closure": "FOLLOW_UP_REQUIRED" if open_items else "QUALIFICATION_REQUIRED",
        "cache_sha256": digest(cache),
        "observed_merge_sha256": digest(merge),
        "cache_overridden": cache.get("state") != "MERGED",
        "cache_mutated": False,
        "receipts_rewritten": False,
        "push_qualified": False,
    }


def handoff(view, *, blocker, references, next_action):
    require(isinstance(view, dict) and isinstance(references, list), "handoff inputs")
    require(view.get("state") in {"OPEN", "MERGED", "BLOCKED", "RESUME_REQUIRED"}, "handoff state")
    for value in (blocker, next_action, *references):
        ops.text(value, "handoff text")
    return {
        "schema": "agent-handoff/v3",
        "state_sha256": digest(view),
        "text": (
            f"{view['repository']} #{view['pr']} · {view['state']}\n"
            f"Head: {view['head_sha']}\nBlocker: {blocker}\n"
            f"Evidence: {', '.join(references)}\nNext action: {next_action}"
        ),
        "state_mutated": False,
    }


def checkpoint_metrics(metrics):
    """Validate a small host-measured record kept inside the existing checkpoint."""
    ops.obj(
        metrics,
        "kind window source elapsed_seconds tool_calls github_calls repeated_reads "
        "repeated_checks input_tokens output_tokens",
        "checkpoint metrics",
    )
    require(metrics["kind"] in {"ACTUAL", "REPLAY", "SYNTHETIC"}, "measurement kind")
    for key in ("window", "source"):
        ops.text(metrics[key], "measurement provenance")
    for key in set(metrics) - {"kind", "window", "source"}:
        value = metrics[key]
        require(
            value is None or (type(value) is int and value >= 0),
            "measurement must be an observed nonnegative integer or null: " + key,
        )
    return deepcopy(metrics)


def execution_step(checkpoint, *, trusted_checkpoint):
    """Derive continuation from the single host-selected ledger; never run an effect.

    Coordinates bind observations, not authority. The host establishes actual
    authorization, useful progress and supported recovery before calling this view.
    A blocked step cannot conceal independent ready work.
    """
    require(digest(checkpoint) == trusted_checkpoint, "changed execution checkpoint")
    ops.obj(checkpoint, "schema scope_sha256 steps", "execution checkpoint")
    require(checkpoint["schema"] == "agent-execution/v1", "execution schema")
    ops.sha(checkpoint["scope_sha256"], 64)
    steps = checkpoint["steps"]
    require(isinstance(steps, list) and 0 < len(steps) <= 1000, "bounded execution steps")
    indexed = {}
    for step in steps:
        ops.obj(step, "id state dependencies action observations recovery blocker",
                "execution step")
        identity = ops.text(step["id"], "step identity")
        require(identity not in indexed, "duplicate execution step")
        require(step["state"] in {"PENDING", "COMPLETE"}, "execution step state")
        indexed[identity] = step
    for step in steps:
        dependencies = step["dependencies"]
        require(isinstance(dependencies, list) and len(dependencies) == len(set(dependencies)),
                "execution dependencies")
        require(all(d in indexed and d != step["id"] for d in dependencies),
                "unknown or self dependency")
    visiting, visited = set(), set()

    def visit(identity):
        require(identity not in visiting, "execution dependency cycle")
        if identity in visited:
            return
        visiting.add(identity)
        for dependency in indexed[identity]["dependencies"]:
            visit(dependency)
        visiting.remove(identity)
        visited.add(identity)

    for identity in indexed:
        visit(identity)

    def action(value):
        ops.obj(value, "repository operation head_sha inputs_sha256 event authorization", "action")
        for key in ("repository", "operation", "event"):
            ops.text(value[key], "action coordinate")
        ops.sha(value["head_sha"])
        ops.sha(value["inputs_sha256"], 64)
        require(value["authorization"] in {"GRANTED", "MISSING"}, "action authorization")
        return {k: value[k] for k in value if k != "authorization"}

    blocked, ready = [], []
    for step in steps:
        if step["state"] == "COMPLETE":
            require(all(indexed[d]["state"] == "COMPLETE" for d in step["dependencies"]),
                    "completion precedes dependency")
            continue
        coordinate = action(step["action"])
        observations = step["observations"]
        require(isinstance(observations, list) and len(observations) <= 1000,
                "bounded iteration history")
        counts, last_causes = {}, {}
        for row in observations:
            ops.obj(row, "coordinates_sha256 result_sha256 progress cause", "iteration")
            for key in ("coordinates_sha256", "result_sha256"):
                ops.sha(row[key], 64)
            require(row["progress"] in {
                "NONE", "ADVANCE", "NEW_EVIDENCE", "CAUSE_FIXED", "DEPENDENCY"},
                    "iteration progress")
            require(row["cause"] in {"NONE", "DETERMINISTIC", "TRANSIENT", "RATE_LIMIT",
                                     "CAPABILITY_MISSING", "EXTERNAL", "UNKNOWN"},
                    "iteration cause")
            identity = row["coordinates_sha256"]
            history = counts.setdefault(identity, {})
            if row["progress"] != "NONE":
                history.clear()
            else:
                result = row["result_sha256"]
                history[result] = history.get(result, 0) + 1
            if row["progress"] == "CAUSE_FIXED" or last_causes.get(identity) != "DETERMINISTIC":
                last_causes[identity] = row["cause"]

        def halted(candidate, histories=counts, causes=last_causes):
            identity = digest(candidate)
            return (max(histories.get(identity, {}).values(), default=0) >= 2
                    or causes.get(identity) == "DETERMINISTIC")

        recovery = step["recovery"]
        stopped, recovery_stopped = halted(coordinate), False
        if recovery is not None:
            recovered = action(recovery)
            require(recovery["authorization"] == "GRANTED", "recovery lacks authorization")
            require(digest(recovered) != digest(coordinate), "retry requires changed coordinates")
            require(recovered["repository"] == coordinate["repository"], "recovery repository")
            recovery_stopped = halted(recovered)
        blocker = step["blocker"]
        if blocker is not None:
            ops.obj(blocker, "kind reference reason prepared_result action", "external blocker")
            require(blocker["kind"] in {"WAIT_EXTERNAL", "HUMAN_ACTION_REQUIRED"}, "blocker kind")
            for key in ("reference", "reason", "prepared_result", "action"):
                ops.text(blocker[key], "concrete blocker")
        require(not stopped or recovery is not None or blocker is not None,
                "equivalent observations require classified supported recovery or dependency")
        require(not recovery_stopped or blocker is not None,
                "failed recovery requires changed conditions or a concrete dependency")
        require(step["action"]["authorization"] == "GRANTED" or (
            blocker is not None and blocker["kind"] == "HUMAN_ACTION_REQUIRED"
        ), "missing authority requires a concrete human action")
        if any(indexed[d]["state"] != "COMPLETE" for d in step["dependencies"]):
            continue
        if recovery is not None and not recovery_stopped:
            ready.append({"step": step["id"], "action": recovery, "recovery": True})
        elif blocker is None and not stopped:
            ready.append({"step": step["id"], "action": step["action"], "recovery": False})
        else:
            blocked.append({"step": step["id"], **blocker,
                            "loop_stopped": stopped or recovery_stopped})
    complete = all(s["state"] == "COMPLETE" for s in steps)
    require(complete or ready or blocked, "no executable frontier")
    chosen = ready[0] if ready else blocked[0] if blocked else None
    return {
        "schema": "agent-execution-result/v1", "checkpoint_sha256": trusted_checkpoint,
        "state": "TERMINAL" if complete else "CONTINUE_NOW" if ready else chosen["kind"],
        "next": chosen, "blocked": blocked, "prompt_required": False,
        "state_mutated": False, "push_qualified": False,
    }


def checkpoint_handoff(
    checkpoint, roadmap, recommendation, *, trusted_checkpoint, trusted_roadmap,
    model_availability, trusted_models, now=None,
):
    """Render host-selected checkpoint projections; never grant or broaden authority."""
    require(digest(checkpoint) == trusted_checkpoint, "changed checkpoint")
    require(digest(roadmap) == trusted_roadmap, "changed roadmap")
    ops.obj(
        checkpoint,
        "repository pr head_sha state scope result checks residuals next metrics",
        "checkpoint projection",
    )
    ops.sha(checkpoint["head_sha"])
    ops.number(checkpoint["pr"], "PR number")
    require(checkpoint["state"] in {"OPEN", "MERGED", "BLOCKED", "COMPLETE"}, "checkpoint state")
    for key in ("repository", "scope", "result", "checks", "residuals"):
        ops.text(checkpoint[key], "checkpoint text")
    ops.obj(roadmap, "repository steps reference", "roadmap projection")
    require(roadmap["repository"] == checkpoint["repository"], "roadmap repository")
    ops.text(roadmap["reference"], "roadmap reference")
    require(isinstance(roadmap["steps"], list) and roadmap["steps"], "roadmap steps")
    pending, seen = [], set()
    for step in roadmap["steps"]:
        ops.obj(step, "id state", "roadmap step")
        identity = ops.text(step["id"], "roadmap step id")
        require(identity not in seen, "duplicate roadmap step")
        seen.add(identity)
        require(step["state"] in {"COMPLETE", "PENDING"}, "roadmap step state")
        if step["state"] == "PENDING":
            pending.append(identity)
    next_step = checkpoint["next"]
    ops.obj(next_step, "roadmap_step kind action prompt authorization", "next step")
    require(pending and next_step["roadmap_step"] == pending[0], "next step must follow roadmap")
    require(next_step["kind"] in {"CONTINUE", "RECOVER", "DECISION"}, "continuation kind")
    require(next_step["authorization"] in {"GRANTED", "MISSING"}, "next authorization")
    require(
        next_step["kind"] == "DECISION" or next_step["authorization"] == "GRANTED",
        "decision must identify missing authority",
    )
    ops.text(next_step["action"], "next step action")
    ops.instruction_text(next_step["prompt"], "complete next prompt")
    ops.obj(
        recommendation,
        "environment model reasoning workload rationale uncertainty",
        "recommendation",
    )
    require(recommendation["workload"] in {"LOW", "MEDIUM", "HIGH"}, "workload estimate")
    for key in ("environment", "rationale", "uncertainty"):
        ops.text(recommendation[key], "recommendation text")
    model, reasoning = recommendation["model"], recommendation["reasoning"]
    if model_availability is None:
        require(trusted_models is None and model is None and reasoning is None, "unverified model")
        require(recommendation["uncertainty"] != "NONE", "model availability uncertainty required")
    else:
        require(digest(model_availability) == trusted_models, "changed model availability")
        ops.obj(
            model_availability,
            "environment source observed_at valid_until models",
            "model availability",
        )
        ops.text(model_availability["source"], "model source")
        observed = checked_time(model_availability["observed_at"])
        expiry = checked_time(model_availability["valid_until"])
        current = now or datetime.now(UTC)
        require(observed <= current < expiry, "model availability expired or future")
        require(
            model_availability["environment"] == recommendation["environment"], "model environment"
        )
        require(isinstance(model_availability["models"], dict), "model inventory")
        for name, efforts in model_availability["models"].items():
            ops.text(name, "model name")
            require(isinstance(efforts, list) and efforts, "supported reasoning efforts")
            for effort in efforts:
                ops.text(effort, "reasoning effort")
        require(model in model_availability["models"], "unsupported model")
        require(reasoning in model_availability["models"][model], "unsupported reasoning")
    metrics = checkpoint_metrics(checkpoint["metrics"])
    execution = "DECISION_REQUIRED" if next_step["kind"] == "DECISION" else "CONTINUE_IN_SESSION"
    selection = f"Model: {model or 'UNVERIFIED'}; reasoning: {reasoning or 'UNVERIFIED'}"
    prompt = (
        next_step["prompt"] + "\n\n"
        f"Scope: {checkpoint['scope']}\nRoadmap: {roadmap['reference']}\n"
        "Resume from the existing checkpoint and verified roadmap. Revalidate changed or "
        "expired evidence and mandatory decision-boundary checks. Preserve the actual "
        "authorization scope; this handoff grants no additional authority. Complete already "
        "authorized work without requesting another prompt."
    )
    return {
        "schema": "agent-checkpoint-handoff/v1",
        "checkpoint_sha256": trusted_checkpoint,
        "roadmap_sha256": trusted_roadmap,
        "kind": next_step["kind"],
        "execution": execution,
        "next_action": next_step["action"],
        "recommendation": deepcopy(recommendation),
        "metrics": metrics,
        "text": (
            f"{checkpoint['result']}\nChecks: {checkpoint['checks']}\n"
            f"Residuals: {checkpoint['residuals']}\n"
            f"{checkpoint['repository']} #{checkpoint['pr']} · {checkpoint['head_sha']}\n"
            f"Next action: {next_step['action']}\n{selection}\n"
            f"Workload: {recommendation['workload']} — {recommendation['rationale']}\n"
            f"Uncertainty: {recommendation['uncertainty']}\n"
            f"Select before the next step (not changed): {selection}\n{prompt}"
        ),
        "prompt": prompt,
        "state_mutated": False,
        "model_changed": False,
        "push_qualified": False,
    }


def ci_plan(changed_paths, suites, *, complete, merge_equivalent=False):
    """Select from accepted exact dependency paths; uncertainty runs the full set."""
    require(
        type(complete) is bool and type(merge_equivalent) is bool,
        "CI completeness must be explicit",
    )
    require(isinstance(suites, dict) and bool(suites), "suite inventory required")
    for name, dependencies in suites.items():
        ops.text(name, "suite name")
        require(isinstance(dependencies, list) and bool(dependencies), "suite dependencies")
        for dependency in dependencies:
            ops.path(dependency)
    paths = ops.paths(changed_paths)
    known = set().union(*(set(dependencies) for dependencies in suites.values()))
    fallback = not complete or not paths or not set(paths) <= known
    selected = (
        sorted(suites)
        if fallback
        else sorted(name for name, dependencies in suites.items() if set(paths) & set(dependencies))
    )
    # Equivalence is reported only; this selector never certifies a reused run.
    return {
        "schema": "agent-ci-plan/v1",
        "suites": selected,
        "full_fallback": fallback,
        "merge_tests": "REQUIRED",
        "equivalence_supplied": merge_equivalent is True,
        "required_check_completion": "EXPLICIT_RESULT_REQUIRED",
        "push_qualified": False,
    }


def storage_summary(artifacts, *, complete):
    """Actual bytes only; no inferred account billing or automatic deletion."""
    require(type(complete) is bool, "artifact completeness must be an explicit boolean")
    require(isinstance(artifacts, list), "artifact inventory required")
    seen, total = set(), 0
    for row in artifacts:
        require(
            isinstance(row, dict)
            and type(row.get("id")) is int
            and row["id"] > 0
            and row["id"] not in seen
            and type(row.get("size_in_bytes")) is int
            and row["size_in_bytes"] >= 0
            and type(row.get("expired")) is bool,
            "incomplete or duplicate artifact identity",
        )
        seen.add(row["id"])
        if not row["expired"]:
            total += row["size_in_bytes"]
    return {
        "artifact_count": len(artifacts),
        "current_bytes": total,
        "inventory": "COMPLETE" if complete else "BOUNDED_SAMPLE",
        "account_billing": "NOT_OBSERVED",
        "deletion_authorized": False,
    }


def checked_time(value):
    require(isinstance(value, str), "timestamp required")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(result.tzinfo is not None, "timezone required")
    return result


def trusted_record(record, trusted_digests, label):
    """The host selects trust independently; a candidate cannot select this set."""
    require(isinstance(record, dict), label + " object required")
    require(digest(record) in trusted_digests, "untrusted " + label)
    return record


def exact_items(items):
    require(isinstance(items, list) and bool(items), "nonempty batch required")
    keys = []
    for item in items:
        ops.obj(item, "id kind language source text dependencies fallback", "catalog item")
        require(item["kind"] in {"SOURCE", "TRANSLATION"}, "item kind")
        for field in ("id", "language"):
            ops.text(item[field], field)
        for field in ("source", "text"):
            require(isinstance(item[field], str) and item[field].strip(), "missing " + field)
        require(item["fallback"] is False, "fallback is not a completed translation")
        require(isinstance(item["dependencies"], dict), "dependency inventory required")
        for key, value in item["dependencies"].items():
            ops.text(key, "dependency id")
            ops.sha(value, 64)
        keys.append((item["id"], item["language"], item["kind"]))
    require(keys == sorted(set(keys)), "items must be unique and sorted")
    return [
        {"id": i["id"], "language": i["language"], "kind": i["kind"], "sha256": digest(i)}
        for i in items
    ]


def validate_editorial_batch(batch, checks, trusted_checks):
    """Consumer checks implement locale/markup semantics; their full proof is bound."""
    ops.obj(batch, "repository catalog release revision items", "catalog batch")
    for key in ("repository", "catalog", "release", "revision"):
        ops.text(batch[key], key)
    identities = exact_items(batch["items"])
    trusted_record(checks, trusted_checks, "consumer checks")
    ops.obj(checks, "batch_sha256 checker provenance coverage results exceptions", "checks")
    require(checks["batch_sha256"] == digest(batch), "checks bind different content")
    for key in ("checker", "provenance"):
        ops.text(checks[key], key)
    require(checks["coverage"] == identities, "coverage incomplete or stale")
    names = {
        "coverage",
        "placeholders",
        "markup",
        "escaping",
        "pluralization",
        "terminology",
        "context",
    }
    require(
        isinstance(checks["results"], dict) and set(checks["results"]) == names,
        "complete consumer validation required",
    )
    require(all(v == "PASS" for v in checks["results"].values()), "invalid catalog")
    require(isinstance(checks["exceptions"], list), "linguistic exceptions required")
    for value in checks["exceptions"]:
        ops.text(value, "linguistic ambiguity or limitation")
    return identities


def delegated_approval(
    batch,
    checks,
    grant,
    policy,
    *,
    trusted_grants,
    trusted_checks,
    policy_digest,
    executor,
    now=None,
):
    """Validate an adopted delegation. Never record this as a human review or publish."""
    identities = validate_editorial_batch(batch, checks, trusted_checks)
    require(digest(policy) == policy_digest, "changed accepted editorial policy")
    ops.obj(policy, "repository delegated_editorial delegants", "editorial policy")
    require(
        policy["repository"] == batch["repository"] and policy["delegated_editorial"] is True,
        "prior policy adoption required",
    )
    require(
        isinstance(policy["delegants"], list) and bool(policy["delegants"]),
        "authorized delegants required",
    )
    trusted_record(grant, trusted_grants, "delegation")
    ops.obj(
        grant,
        "id purpose repository catalog release revision batch_sha256 items "
        "checks_sha256 policy_sha256 delegant executor provenance not_before expires_at "
        "revoked conditions accepted_exceptions",
        "delegation",
    )
    require(grant["purpose"] == "DELEGATED_EDITORIAL_APPROVAL", "editorial consent required")
    for key in ("repository", "catalog", "release", "revision"):
        require(grant[key] == batch[key], "delegation outside " + key)
    require(
        grant["items"] == identities and grant["batch_sha256"] == digest(batch),
        "delegation content or languages changed",
    )
    require(
        grant["checks_sha256"] == digest(checks) and grant["policy_sha256"] == policy_digest,
        "delegation conditions changed",
    )
    require(grant["delegant"] in policy["delegants"], "delegant role unavailable")
    require(grant["executor"] == ops.text(executor, "executor"), "wrong executor")
    for key in ("id", "provenance"):
        ops.text(grant[key], key)
    current = now or datetime.now(UTC)
    require(
        checked_time(grant["not_before"]) <= current < checked_time(grant["expires_at"]),
        "delegation expired or not active",
    )
    require(grant["revoked"] is False, "delegation revoked")
    require(
        grant["conditions"] == {"valid_complete_batch": True, "no_publication": True},
        "unsupported delegation conditions",
    )
    require(grant["accepted_exceptions"] == checks["exceptions"], "exceptions not accepted")
    return {
        "schema": "agent-editorial-approval/v1",
        "state": "APPROVED_AUTOMATIC_DELEGATED",
        "batch_sha256": digest(batch),
        "items": identities,
        "grant_sha256": digest(grant),
        "delegant": grant["delegant"],
        "executor": executor,
        "provenance": grant["provenance"],
        "human_review": False,
        "publication_authorized": False,
    }


def preserved_approvals(previous_items, current_items, approvals):
    """Per-item dependency hashes invalidate exactly the affected approval, never all."""
    old = {tuple(r[k] for k in ("id", "language", "kind")): r for r in exact_items(previous_items)}
    new = {tuple(r[k] for k in ("id", "language", "kind")): r for r in exact_items(current_items)}
    require(isinstance(approvals, list), "approval inventory")
    retained, invalidated, seen = [], [], set()
    for row in approvals:
        ops.obj(row, "item approval_reference", "prior approval")
        item = row["item"]
        key = tuple(item[k] for k in ("id", "language", "kind"))
        require(key not in seen and old.get(key) == item, "invalid prior approval binding")
        seen.add(key)
        ops.text(row["approval_reference"], "existing approval reference")
        (retained if new.get(key) == item else invalidated).append(deepcopy(row))
    return {"retained": retained, "invalidated": invalidated, "new_approvals": []}


def release_identity(identity):
    ops.obj(
        identity,
        "repository release candidate_sha artifact_sha256 effects_sha256 "
        "inputs_sha256 audience shared_impacts_sha256",
        "release identity",
    )
    for key in ("repository", "release", "audience"):
        ops.text(identity[key], key)
    ops.sha(identity["candidate_sha"])
    for key in ("artifact_sha256", "effects_sha256", "inputs_sha256", "shared_impacts_sha256"):
        ops.sha(identity[key], 64)
    return identity


def authorization_reuse(
    identity, conditions, grant, *, trusted_grants, now=None, prior_effects="NONE"
):
    release_identity(identity)
    trusted_record(grant, trusted_grants, "production authorization")
    ops.obj(
        grant,
        "id purpose identity allowed_conditions_sha256 not_before expires_at revoked "
        "partial_retry procedure provenance",
        "production authorization",
    )
    require(grant["purpose"] == "PRODUCTION", "editorial approval cannot authorize deployment")
    require(
        grant["identity"] == identity, "candidate, artifact, effects, audience or inputs changed"
    )
    require(
        isinstance(grant["allowed_conditions_sha256"], list)
        and bool(grant["allowed_conditions_sha256"]),
        "operational conditions required",
    )
    for value in grant["allowed_conditions_sha256"]:
        ops.sha(value, 64)
    require(
        digest(conditions) in grant["allowed_conditions_sha256"],
        "operational change outside authorization",
    )
    require(grant["revoked"] is False, "authorization revoked")
    current = now or datetime.now(UTC)
    require(
        checked_time(grant["not_before"]) <= current < checked_time(grant["expires_at"]),
        "authorization expired or not active",
    )
    require(prior_effects in {"NONE", "PARTIAL", "COMPLETED", "UNKNOWN"}, "effect state")
    require(type(grant["partial_retry"]) is bool, "partial retry must be explicit")
    require(prior_effects not in {"UNKNOWN", "COMPLETED"}, "reconcile or verify; do not repeat")
    if prior_effects == "PARTIAL":
        require(grant["partial_retry"] is True, "partial retry needs covered recovery")
    for key in ("id", "procedure", "provenance"):
        ops.text(grant[key], key)
    return {
        "authorization": "COVERED",
        "grant_sha256": digest(grant),
        "identity_sha256": digest(identity),
        "conditions_sha256": digest(conditions),
        "production_readiness": "NOT_EVALUATED",
        "operation_performed": False,
    }


def readiness(identity, observations, *, trusted_observations, trusted_deferrals=(), now=None):
    """Aggregate independent read-only diagnoses; this never invokes production."""
    release_identity(identity)
    phases = {
        "CODE",
        "DATA",
        "CONFIGURATION",
        "ARTIFACT",
        "MIGRATIONS",
        "WORKFLOW_INPUTS",
        "AUTHORIZATION",
        "EXECUTION",
        "VERIFICATION",
        "CERTIFICATION",
    }
    require(isinstance(observations, list), "readiness observations")
    seen, blockers, states = set(), [], {}
    for row in observations:
        trusted_record(row, trusted_observations, "readiness observation")
        ops.obj(
            row,
            "phase identity_sha256 status cause elements effects next_action "
            "evidence event_at observed_at recorded_at"
            + (" deferral" if row.get("status") == "DEFERRED" else ""),
            "readiness observation",
        )
        phase = row["phase"]
        require(phase in phases and phase not in seen, "duplicate or unknown phase")
        seen.add(phase)
        require(row["identity_sha256"] == digest(identity), "readiness candidate mismatch")
        require(
            row["status"] in {
                "PASS", "BLOCKED", "PENDING", "UNKNOWN", "NOT_APPLICABLE", "DEFERRED"
            },
            "readiness status",
        )
        for field in ("cause", "effects", "next_action", "evidence"):
            ops.text(row[field], field)
        require(isinstance(row["elements"], list), "affected elements required")
        for value in row["elements"]:
            ops.text(value, "element")
        if row["status"] == "DEFERRED":
            require(phase in {"VERIFICATION", "CERTIFICATION"}, "only acceptance can be deferred")
            grant = row["deferral"]
            trusted_record(grant, trusted_deferrals, "acceptance deferral")
            ops.obj(grant, "id identity_sha256 phase elements authorization_ref sequence "
                    "not_before expires_at revoked", "acceptance deferral")
            require(grant["identity_sha256"] == digest(identity), "deferral candidate mismatch")
            require(grant["phase"] == phase and grant["elements"] == row["elements"]
                    and bool(row["elements"]), "deferral acceptance scope mismatch")
            for key in ("id", "authorization_ref"):
                ops.text(grant[key], key)
            require(isinstance(grant["sequence"], list) and len(grant["sequence"]) >= 2,
                    "explicit authorized acceptance sequence required")
            for step in grant["sequence"]:
                ops.text(step, "acceptance sequence step")
            require(grant["revoked"] is False, "acceptance deferral revoked")
            require(checked_time(grant["not_before"]) <= (now or datetime.now(UTC))
                    < checked_time(grant["expires_at"]), "acceptance deferral expired or inactive")
        require(
            checked_time(row["event_at"])
            <= checked_time(row["observed_at"])
            <= checked_time(row["recorded_at"]),
            "event/observation/recording order",
        )
        states[phase] = row["status"]
        if row["status"] not in {"PASS", "NOT_APPLICABLE"}:
            blockers.append(deepcopy(row))
    for phase in sorted(phases - seen):
        states[phase] = "UNKNOWN"
        blockers.append({"phase": phase, "status": "UNKNOWN", "cause": "missing evidence"})
    prepared = {"CODE", "DATA", "CONFIGURATION", "ARTIFACT", "MIGRATIONS", "WORKFLOW_INPUTS"}
    return {
        "schema": "agent-readiness/v1",
        "identity_sha256": digest(identity),
        "phases": states,
        "blockers": blockers,
        "ready_for_final_consent": all(states[k] in {"PASS", "NOT_APPLICABLE"} for k in prepared),
        "production_executed": states["EXECUTION"] == "PASS",
        "certified": all(states[k] in {"PASS", "NOT_APPLICABLE"} for k in phases),
        "mutation_authorized": False,
    }


def human_intervention(request):
    ops.obj(
        request,
        "kind reason rule_source action url navigation inputs expected_result "
        "prepared_result agent_can_execute",
        "human intervention",
    )
    require(
        request["kind"] in {"AUTHORIZATION", "AUTHENTICATION", "CONFIGURATION", "MATERIAL"},
        "intervention kind",
    )
    require(request["agent_can_execute"] is False, "do not ask for available autonomous work")
    for key in ("reason", "rule_source", "action", "expected_result", "prepared_result"):
        ops.text(request[key], key)
    from urllib.parse import urlsplit

    url = urlsplit(request["url"])
    require(
        url.scheme == "https"
        and url.hostname
        and not url.username
        and not url.password
        and not url.query,
        "observed entry/deep link without secrets required",
    )
    require(
        isinstance(request["navigation"], list) and isinstance(request["inputs"], dict),
        "navigation and exact inputs required",
    )
    for value in request["navigation"]:
        ops.text(value, "navigation")
    return {**deepcopy(request), "after_done": "OBSERVE_RESULT_BOUNDED", "performed": False}


def environment_plan(environment):
    ops.obj(
        environment,
        "staging staging_result target audience server_authorization "
        "shared_impacts ui_capabilities emergency_procedure",
        "environment",
    )
    require(environment["staging"] in {"CONFIGURED", "ABSENT"}, "staging unknown")
    require(environment["target"] in {"PRODUCTION", "USER_PC"}, "target")
    require(environment["audience"] in {"STAFF", "ALL"}, "audience")
    require(isinstance(environment["ui_capabilities"], dict), "early UI inventory required")
    for phase in ("pre_deploy", "post_deploy"):
        require(isinstance(environment["ui_capabilities"].get(phase), list), "UI phase inventory")
    for key in ("shared_impacts", "emergency_procedure"):
        ops.text(environment[key], key)
    if environment["audience"] == "STAFF":
        require(
            environment["server_authorization"] == "VERIFIED", "hidden links are not access control"
        )
    if environment["staging"] == "CONFIGURED":
        require(environment["staging_result"] == "PASS", "configured staging cannot be skipped")
    else:
        require(environment["staging_result"] == "NOT_APPLICABLE", "absent staging is not PASS")
    return {
        "target": environment["target"],
        "audience": environment["audience"],
        "staff_is_production": environment["target"] == "PRODUCTION",
        "next": "PREPARE_BUILD_AND_INSTRUCTIONS"
        if environment["target"] == "USER_PC"
        else "QUALIFY_NORMAL_PRODUCTION",
        "ui": deepcopy(environment["ui_capabilities"]),
        "authorization_required": "EXISTING_BOUND_CONTRACT",
        "rollback_assumed": False,
    }


def recovery_plan(operation, *, trusted_observations):
    trusted_record(operation, trusted_observations, "effect reconciliation")
    ops.obj(
        operation,
        "identity state completed remaining reconciled bookkeeping "
        "procedure event_at observed_at recorded_at",
        "recovery",
    )
    release_identity(operation["identity"])
    require(
        operation["state"] in {"BEFORE_EFFECTS", "PARTIAL", "MONITORING_FAILED", "UNKNOWN"},
        "unknown failure class",
    )
    require(type(operation["reconciled"]) is bool, "reconciliation must be explicit")
    require(operation["bookkeeping"] in {"PASS", "FAILED", "UNKNOWN"}, "bookkeeping")
    for key in ("completed", "remaining"):
        require(
            isinstance(operation[key], list) and operation[key] == sorted(set(operation[key])),
            "effect inventory",
        )
        for value in operation[key]:
            ops.text(value, "effect id")
    require(not set(operation["completed"]) & set(operation["remaining"]), "duplicate effect")
    ops.text(operation["procedure"], "existing recovery procedure")
    require(
        checked_time(operation["event_at"])
        <= checked_time(operation["observed_at"])
        <= checked_time(operation["recorded_at"]),
        "recovered event time order",
    )
    state = operation["state"]
    if state == "BEFORE_EFFECTS":
        require(not operation["completed"], "before-effects claim contradicts completed effects")
    if state == "PARTIAL":
        require(bool(operation["completed"]) and bool(operation["remaining"]), "partial inventory")
    if state == "MONITORING_FAILED":
        require(bool(operation["completed"]) and not operation["remaining"], "success inventory")
    action = "RECONCILE_READ_ONLY"
    remaining = []
    if operation["bookkeeping"] != "PASS":
        action = "REPAIR_BOOKKEEPING_BEFORE_DEPENDENT_MUTATIONS"
    elif operation["reconciled"] and state != "UNKNOWN":
        action = "VERIFY_COMPLETED" if state == "MONITORING_FAILED" else "QUALIFY_REMAINING_EFFECTS"
        remaining = operation["remaining"]
    return {
        "next_action": action,
        "eligible_for_qualification": remaining,
        "never_repeat": operation["completed"],
        "procedure": operation["procedure"],
        "mutation_authorized": False,
        "retroactive_approval": False,
    }


def closure_plan(scope, evidence, *, trusted_scope, trusted_evidence, completed_keys):
    trusted_record(scope, trusted_scope, "delivery scope")
    trusted_record(evidence, trusted_evidence, "closure evidence")
    ops.obj(scope, "repository release identity issues steps inapplicable", "closure scope")
    release_identity(scope["identity"])
    require(
        scope["repository"] == scope["identity"]["repository"]
        and scope["release"] == scope["identity"]["release"],
        "scope identity",
    )
    ops.obj(evidence, "scope_sha256 identity_sha256 criteria issues steps", "closure evidence")
    require(
        evidence["scope_sha256"] == digest(scope)
        and evidence["identity_sha256"] == digest(scope["identity"]),
        "closure binding",
    )
    criteria = evidence["criteria"]
    require(isinstance(criteria, dict) and bool(criteria), "acceptance criteria required")
    require(all(v == "PASS" for v in criteria.values()), "unmet acceptance criteria")
    order = ["POST_DEPLOY", "CERTIFY", "CHECKPOINT", "ROADMAP", "ISSUES", "HANDOFF"]
    require(scope["steps"] == order, "complete delivery sequence required")
    require(
        isinstance(scope["inapplicable"], dict)
        and set(scope["inapplicable"]) <= set(order) - {"HANDOFF"},
        "scope-bound applicability reasons required",
    )
    for reason in scope["inapplicable"].values():
        ops.text(reason, "accepted applicability reason")
    require(
        isinstance(scope["issues"], list) and scope["issues"] == sorted(set(scope["issues"])),
        "exact scope issues",
    )
    require(set(evidence["issues"]) == set(scope["issues"]), "issue scope mismatch")
    for issue in scope["issues"]:
        ops.text(issue, "scope issue")
        require(evidence["issues"][issue] == "CRITERIA_MET", "issue requirements pending")
    require(set(evidence["steps"]) == set(order), "complete delivery evidence")
    actions = []
    for step in order:
        require(
            evidence["steps"][step] in {"VERIFIED", "PENDING", "NOT_APPLICABLE"}, "closure step"
        )
        require(
            (evidence["steps"][step] == "NOT_APPLICABLE") == (step in scope["inapplicable"]),
            "cannot skip an applicable delivery step",
        )
        key = digest({"scope": digest(scope), "step": step})
        if key in completed_keys:
            require(evidence["steps"][step] == "VERIFIED", "receipt without observed completion")
        elif evidence["steps"][step] == "PENDING":
            actions.append({"step": step, "idempotency_key": key})
    return {
        "complete": not actions,
        "next_action": actions[:1],
        "remaining": actions,
        "issues": scope["issues"],
        "next_release_authorized": False,
        "receipt_write_before_dependents": True,
    }


def review_inventory(pr, threads, comment_pages, review_pages):
    """Prove completeness from REST counts and IDs, not an empty normalized list."""
    require(isinstance(pr, dict) and type(pr.get("review_comments")) is int, "PR count missing")
    require(isinstance(threads, list), "thread list required")

    def complete_pages(pages):
        require(
            isinstance(pages, list) and bool(pages) and len(pages) <= 100,
            "bounded pagination required",
        )
        require(
            all(isinstance(page, list) and len(page) == 100 for page in pages[:-1])
            and isinstance(pages[-1], list)
            and len(pages[-1]) < 100,
            "terminal REST page missing",
        )
        rows = [row for page in pages for row in page]
        ids = [row.get("id") for row in rows]
        require(
            all(type(i) is int and i > 0 for i in ids) and len(ids) == len(set(ids)),
            "missing or duplicate REST IDs",
        )
        return rows

    comments = complete_pages(comment_pages)
    reviews = complete_pages(review_pages)
    require(len(comments) == pr["review_comments"], "PR count drift or incomplete comments")
    ids, thread_ids, unresolved = [], set(), []
    for thread in threads:
        require(
            thread.get("id") not in thread_ids and isinstance(thread.get("id"), str),
            "thread identity",
        )
        thread_ids.add(thread["id"])
        require(type(thread.get("is_resolved")) is bool, "unknown thread resolution")
        require(
            isinstance(thread.get("comments"), list) and bool(thread["comments"]),
            "empty thread is not complete evidence",
        )
        ids.extend(c.get("database_id") for c in thread["comments"])
        if not thread["is_resolved"]:
            unresolved.append(thread["id"])
    require(
        len(ids) == len(set(ids)) and set(ids) == {c["id"] for c in comments},
        "thread comments incomplete",
    )
    return {
        "complete": True,
        "unresolved": unresolved,
        "reviews": reviews,
        "evidence_sha256": digest([pr, threads, comment_pages, review_pages]),
        "qualification": "NOT_EVALUATED",
    }


def classify_document_effects(changed_paths, registry, registry_digest):
    require(digest(registry) == registry_digest, "untrusted document registry")
    require(isinstance(registry, dict), "exact accepted path registry required")
    allowed = {"PLANNING", "DOCUMENTATION", "POLICY", "RUNTIME"}
    for path, role in registry.items():
        ops.path(path)
        require(role in allowed, "unknown document role")
    paths = ops.paths(changed_paths)
    require(bool(paths), "empty delta")
    roles = {path: registry.get(path, "UNKNOWN") for path in paths}
    # Preserve a known runtime effect even when another path needs classification.
    known_effect = "PRODUCTION" if "RUNTIME" in roles.values() else "NO_PRODUCTION"
    return {
        "roles": roles,
        "known_effect": known_effect,
        "effect": "UNKNOWN" if "UNKNOWN" in roles.values() else known_effect,
        "scope": "NOT_INFERRED",
        "authorization": "NOT_INFERRED",
    }


def retention_plan(artifacts, policy, policy_digest):
    require(digest(policy) == policy_digest, "untrusted retention policy")
    ops.obj(policy, "minimum_days cache_authoritative deletion_authorized", "retention policy")
    require(policy["cache_authoritative"] is False, "cache cannot be sole authoritative copy")
    require(policy["deletion_authorized"] is False, "this planner never authorizes deletion")
    require(isinstance(policy["minimum_days"], dict), "retention classes required")
    for purpose, days in policy["minimum_days"].items():
        require(
            purpose in {"TRANSIENT", "FAILURE", "RELEASE", "ROLLBACK", "RECOVERY", "AUDIT"}
            and type(days) is int
            and days > 0,
            "retention class or duration",
        )
    require(isinstance(artifacts, list), "artifact inventory")
    seen = set()
    for row in artifacts:
        ops.obj(row, "id purpose retention_days durable_copy", "artifact retention")
        require(row["id"] not in seen, "duplicate artifact")
        seen.add(row["id"])
        require(row["purpose"] in policy["minimum_days"], "missing purpose retention")
        require(
            type(row["retention_days"]) is int
            and row["retention_days"] >= policy["minimum_days"][row["purpose"]],
            "retention below recovery/audit policy",
        )
        require(row["durable_copy"] is True, "authoritative copy missing")
    return {
        "artifact_count": len(artifacts),
        "policy_sha256": policy_digest,
        "deletions": [],
        "existing_artifacts_mutated": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    select = sub.add_parser("select-documents")
    select.add_argument("--root", type=Path, required=True)
    select.add_argument("--manifest", type=Path, required=True)
    select.add_argument("--manifest-sha256", required=True)
    select.add_argument("--workstream", required=True)
    select.add_argument("--phase", required=True)
    select.add_argument("--host", default="WORK")
    for command in (
        "delegated-approval",
        "authorization-reuse",
        "readiness",
        "recovery-plan",
        "closure-plan",
        "human-intervention",
        "environment-plan",
        "review-inventory",
        "context-delta",
        "checkpoint-handoff",
        "execution-step",
        "campaign-audit",
    ):
        entry = sub.add_parser(command)
        entry.add_argument("--input", type=Path, required=True)
        entry.add_argument("--trusted", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command != "select-documents":
            data = json.loads(args.input.read_text())
            # Supplied explicitly by the host; never discover trust in candidate input.
            trust = json.loads(args.trusted.read_text())
            if args.command == "delegated-approval":
                result = delegated_approval(**data, **trust)
            elif args.command == "authorization-reuse":
                result = authorization_reuse(**data, **trust)
            elif args.command == "readiness":
                result = readiness(**data, **trust)
            elif args.command == "recovery-plan":
                result = recovery_plan(**data, **trust)
            elif args.command == "closure-plan":
                result = closure_plan(**data, **trust)
            elif args.command == "context-delta":
                result = context_delta(**data, **trust)
            elif args.command == "checkpoint-handoff":
                result = checkpoint_handoff(**data, **trust)
            elif args.command == "execution-step":
                result = execution_step(**data, **trust)
            elif args.command == "campaign-audit":
                result = campaign_audit(**data, **trust)
            else:
                require(trust == {}, "unexpected trust arguments")
                function = {
                    "human-intervention": human_intervention,
                    "environment-plan": environment_plan,
                    "review-inventory": review_inventory,
                }[args.command]
                result = function(**data)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        manifest = json.loads(args.manifest.read_text())
        result = select_documents(
            args.root,
            manifest,
            args.manifest_sha256,
            workstream=args.workstream,
            phase=args.phase,
            host=args.host,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({"result": "BLOCKED", "reason": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
