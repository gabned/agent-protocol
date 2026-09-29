"""Shared policy/evidence qualification for CLI, adapters and event collectors.

Accepted host configuration supplies policy and authority. Neither a PR body nor
an evidence digest selects those inputs. The historical validators are preserved
and reused verbatim; new repositories do not expand the historical audit scope.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from .ledger import digest, exact, require, sha
from .source import legacy, safe_path


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


def normalize_ci(history, *, accepted_policy, observed_at):
    """Normalize the shared collector's complete raw history without losing attempts."""
    require(
        history["schema"] == "agent-work-ci-history/v1" and history["complete"] is True,
        "Incomplete collector CI history",
    )
    head, repository = sha(history["head_sha"]), history["repository"]
    raw_runs, expected_count = [], None
    for page in history["inventory"]:
        count = page["response"]["total_count"]
        require(expected_count is None or expected_count == count, "Run inventory changed")
        expected_count = count
        raw_runs.extend(page["response"]["workflow_runs"])
    require(
        expected_count == len(raw_runs) and len({r["id"] for r in raw_runs}) == len(raw_runs),
        "Incomplete or duplicated run pages",
    )
    attempts = {}
    for entry in history["histories"]:
        run = entry["attempt"]["response"]
        key = (run["id"], run["run_attempt"])
        require(key not in attempts and run["head_sha"] == head, "Duplicate or wrong-head attempt")
        jobs, count = [], None
        for page in entry["jobs"]:
            require(
                count is None or count == page["response"]["total_count"], "Job inventory changed"
            )
            count = page["response"]["total_count"]
            jobs.extend(page["response"]["jobs"])
        require(
            len(jobs) == count and len({j["id"] for j in jobs}) == len(jobs), "Incomplete job pages"
        )
        require(
            all(
                j["head_sha"] == head
                and j["run_id"] == run["id"]
                and j.get("run_attempt", run["run_attempt"]) == run["run_attempt"]
                for j in jobs
            ),
            "Job identity changed",
        )
        attempts[key] = {
            "run_attempt": run["run_attempt"],
            "status": run["status"].upper(),
            "conclusion": (run["conclusion"] or "NONE").upper(),
            "jobs_complete": True,
            "jobs": [
                {
                    k: ((j[k] or "NONE").upper() if k in {"status", "conclusion"} else j[k])
                    for k in ("id", "name", "status", "conclusion")
                }
                for j in jobs
            ],
        }
    runs, used = [], set()
    for run in raw_runs:
        require(
            run["repository"]["full_name"] == repository and run["head_sha"] == head,
            "Run repository/head mismatch",
        )
        keys = [(run["id"], i) for i in range(1, run["run_attempt"] + 1)]
        require(all(k in attempts for k in keys), "Attempt history gap")
        retained = [attempts[k] for k in keys]
        require(
            retained[-1]["status"] == run["status"].upper()
            and retained[-1]["conclusion"] == (run["conclusion"] or "NONE").upper(),
            "Run changed during collection",
        )
        used.update(keys)
        runs.append(
            {
                "run_id": run["id"],
                "workflow": run["path"],
                "event": run["event"],
                "head_sha": head,
                "latest_attempt": run["run_attempt"],
                "attempts": retained,
            }
        )
    require(used == set(attempts), "Unexpected unbound attempt")
    return {
        "repository": repository,
        "head_sha": head,
        "source": "GITHUB_CONNECTOR",
        "observed_at": observed_at,
        "applicability": "REQUIRED",
        "policy_ref": accepted_policy["source_commit"],
        "required_workflows": accepted_policy["required_workflows"],
        "runs_complete": True,
        "runs": runs,
    }


def verify_reviews(collection, *, required_reviewers, now=None, review_head=None):
    """Thread completeness is cross-checked against actual REST comment identities."""
    now = now or datetime.now(UTC)
    settling_head = review_head
    review_head = review_head or collection["head"]
    active = collection["preflight"]["active_pull_request"]
    pr = active["pr"]["response"]
    require(
        active["reviews"]["complete"] and active["threads"]["status"] == "OBSERVED",
        "Incomplete reviews/threads",
    )
    instant = datetime.fromisoformat(active["threads"]["observed_at"].replace("Z", "+00:00"))
    require(0 <= (now - instant).total_seconds() <= 900, "Review observation stale")
    response = active["threads"]["response"]
    threads = response.get("review_threads", response.get("threads"))
    require(
        response.get("complete") is True and isinstance(threads, list), "Unproved thread pagination"
    )
    comments = collection["reviewComments"]
    require(len(comments) == pr["review_comments"], "Review comment inventory mismatch")
    ids = [c.get("database_id", c.get("id")) for t in threads for c in t["comments"]]
    require(
        len(ids) == len(set(ids)) == len(comments) and set(ids) == {c["id"] for c in comments},
        "Thread history omits review comments",
    )
    unresolved = [t["id"] for t in threads if not t["is_resolved"]]
    latest = {}
    require(
        len({r["id"] for r in active["reviews"]["items"]}) == len(active["reviews"]["items"]),
        "Duplicated review records",
    )
    for review in active["reviews"]["items"]:
        if settling_head is not None and review["commit_id"] != settling_head:
            continue
        if review["state"] not in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
            continue
        author = review["user"]["login"]
        if author not in latest or latest[author]["id"] < review["id"]:
            latest[author] = review
    approved = all(
        name in latest
        and latest[name]["state"] == "APPROVED"
        and latest[name]["commit_id"] == review_head
        for name in required_reviewers
    )
    blocked = any(r["state"] == "CHANGES_REQUESTED" for r in latest.values())
    pending = any(
        r["state"] == "PENDING" and r["user"]["login"] in required_reviewers
        for r in active["reviews"]["items"]
    )
    # GitHub only exposes draft reviews to their author. A complete paginated
    # list from another account is not proof that a required reviewer is idle.
    viewer = collection.get("reviewViewer")
    visible = not required_reviewers
    if required_reviewers and viewer:
        instant = datetime.fromisoformat(viewer["observed_at"].replace("Z", "+00:00"))
        visible = (
            viewer.get("status") == "OBSERVED"
            and viewer.get("url") == "https://api.github.com/user"
            and type(viewer["response"].get("id")) is int
            and viewer["response"]["id"] > 0
            and 0 <= (now - instant).total_seconds() <= 900
            and set(required_reviewers) == {viewer["response"].get("login")}
        )
    return {
        "result": "PASS"
        if visible and approved and not blocked and not pending and not unresolved
        else "FAIL",
        "unresolved": unresolved,
        "visibility": "OBSERVED" if visible else "REVIEWER_SESSION_UNOBSERVABLE",
        "digest": digest(
            {
                "reviews": active["reviews"]["items"],
                "head": review_head,
                "threads": threads,
                "viewer": viewer.get("response") if viewer else None,
            }
        ),
    }


def verify_settlement_reviews(collection, state, *, now=None):
    """Preserve signed qualification; observe current threads and original-head findings.

    New source-head reviews and editable provider summaries cannot erase the
    accepted candidate's retained evidence. This is never a qualification route.
    """
    qualification = state["qualification"]
    require(
        state["status"] in {"INTEGRATING", "INTEGRATED", "CLOSED"}
        and qualification is not None
        and qualification["result"] == "PASS"
        and qualification["coordinates"] == state["coordinates"],
        "Settlement requires retained exact qualification",
    )
    retained = [g for g in qualification["evidence"] if g["gate"] == "REVIEWS"]
    require(
        len(retained) == 1
        and retained[0]["result"] == "PASS"
        and retained[0]["coordinates"]["HEAD"] == state["head"]
        and retained[0]["coordinates"]["REVIEWS"] == state["coordinates"]["REVIEWS"],
        "Retained review evidence does not bind the merged candidate",
    )
    current = verify_reviews(collection, required_reviewers=[], now=now, review_head=state["head"])
    evidence = {"retained": retained[0], "current": current}
    return {**current, "digest": digest(evidence), "activity": evidence}


def verify_review_activity(collection, requirements, *, now=None, review_head=None):
    """Use authenticated provider comments and GitHub resolution of abbreviated refs.

    An edited PR body is never review evidence. Unknown provider formats fail closed.
    Short SHAs are resolved independently by GitHub, not merely prefix-compared.
    """
    now = now or datetime.now(UTC)
    review_head = review_head or collection["head"]
    comments, evidence = collection["issueComments"], []
    pr = collection["preflight"]["active_pull_request"]["pr"]["response"]
    require(
        len(comments) == pr["comments"] and len({c["id"] for c in comments}) == len(comments),
        "Incomplete review activity comments",
    )
    for rule in requirements:
        exact(rule, "provider author_id kind", "accepted review activity")
        require(
            rule["provider"] == "CODEX_SUMMARY_V1"
            and type(rule["author_id"]) is int
            and rule["kind"] in {"CODE", "SECURITY"},
            "Unknown review provider/requirement",
        )
        summaries = [
            c
            for c in comments
            if c["user"]["id"] == rule["author_id"]
            and c["user"].get("type") == "Bot"
            and "<!-- codex-pull-request-review-summary -->" in c["body"]
        ]
        if len(summaries) != 1:
            return {
                "result": "NOT_RUN",
                "evidence": evidence,
                "reason": "Provider summary missing or ambiguous",
            }
        summary = summaries[0]
        label = "Code Review" if rule["kind"] == "CODE" else "Security Review"
        rows = [line for line in summary["body"].splitlines() if "**" + label + "**" in line]
        if len(rows) != 1 or "**Completed**" not in rows[0]:
            return {
                "result": "NOT_RUN",
                "evidence": evidence,
                "reason": "Required review not completed",
            }
        match = re.search(r"\|\s*`([0-9a-f]{7,40})`\s*\|", rows[0])
        require(match is not None, "Unknown provider commit identity format")
        url = f"https://api.github.com/repos/{collection['repository']}/commits/{match[1]}"
        resolved = [r for r in collection["reviewReferences"] if r["url"] == url]
        require(
            len(resolved) == 1 and resolved[0]["status"] == "OBSERVED",
            "Review reference was not independently resolved",
        )
        instant = datetime.fromisoformat(resolved[0]["observed_at"].replace("Z", "+00:00"))
        require(0 <= (now - instant).total_seconds() <= 900, "Review reference observation stale")
        if resolved[0]["response"]["sha"] != review_head:
            return {
                "result": "NOT_RUN",
                "evidence": evidence,
                "reason": "Review targets a previous candidate",
            }
        if rule["kind"] == "SECURITY":
            metadata = re.findall(
                r"<!-- codex-security-review:v1 (\{[^\n]+\}) -->", summary["body"]
            )
            require(len(metadata) == 1, "Security review identity missing")
            meta = json.loads(metadata[0])
            require(
                meta["repository"] == collection["repository"]
                and meta["pullRequestNumber"] == collection["pr"]
                and meta["headSha"] == review_head
                and meta["status"] == "completed",
                "Security review identity/status differs",
            )
        evidence.append(
            {
                "kind": rule["kind"],
                "comment_id": summary["id"],
                "author_id": rule["author_id"],
                "head": review_head,
                "summary": summary["body"],
                "resolved": resolved[0]["response"]["sha"],
            }
        )
    return {"result": "PASS", "evidence": evidence}


def verify_all_reviews(collection, profile, *, now=None, review_head=None):
    reviews = verify_reviews(
        collection, required_reviewers=profile["reviewers"], now=now, review_head=review_head
    )
    activities = (
        verify_review_activity(
            collection, profile["review_activity"], now=now, review_head=review_head
        )
        if profile["review_activity"]
        else {"result": "PASS", "evidence": []}
    )
    return {
        "result": "PASS" if reviews["result"] == activities["result"] == "PASS" else "FAIL",
        "digest": digest({"reviews": reviews["digest"], "activity": activities}),
        "unresolved": reviews["unresolved"],
        "activity": activities,
    }


def verify_protocol_candidate(
    collection, *, accepted_profile, expected_profile_digest, now=None, observe_unready=False
):
    """Bounded Protocol collection gate, selected by accepted local change control.

    PRODUCT qualification remains the native accepted policy; this function cannot
    reclassify it or infer production safety from a PR label/body. The authenticated
    host establishes profile provenance and real trigger effects before selection.
    """
    require(digest(accepted_profile) == expected_profile_digest, "Accepted scope profile changed")
    exact(
        accepted_profile,
        "repository repository_id source_commit workstream_class effects "
        "paths frozen_paths ci reviewers review_activity",
        "accepted Protocol scope",
    )
    profile = accepted_profile
    require(
        profile["workstream_class"] == "PROTOCOL" and profile["effects"] == "NO_PRODUCTION",
        "Protocol scope cannot replace PRODUCT policy or production authority",
    )
    require(
        collection["schema"] == "agent-lifecycle-collection/v2"
        and (collection["repository"], collection["repository_id"])
        == (profile["repository"], profile["repository_id"]),
        "Collection repository changed",
    )
    active = collection["preflight"]["active_pull_request"]
    pr = active["pr"]["response"]
    require(
        pr["number"] == collection["pr"] and pr["head"]["sha"] == collection["head"],
        "PR/head identity mismatch",
    )
    for observed_pr in (pr, collection["final"][0]["response"]):
        require(
            re.findall(
                r"(?m)^WORKSTREAM_CLASS:[ \t]*([^\r\n]+?)\r?$", observed_pr.get("body") or ""
            )
            == ["PROTOCOL"],
            "Exactly one PROTOCOL workstream marker required",
        )
    # This marker is a required declaration, never identity, history or authority.
    # Scope and effects below still come from independently accepted policy and Git.
    require(
        pr["base"]["repo"]["id"] == profile["repository_id"]
        and pr["base"]["repo"]["full_name"] == profile["repository"],
        "PR targets another repository",
    )
    repository = collection["preflight"]["repo"]["response"]
    require(
        (repository["full_name"], repository["id"])
        == (profile["repository"], profile["repository_id"]),
        "Authenticated repository differs",
    )
    base = sha(profile["source_commit"])
    require(
        pr["base"]["sha"] == base
        and collection["preflight"]["default_branch"]["response"]["commit"]["sha"] == base,
        "Accepted base/default changed",
    )
    final_pr = collection["final"][0]["response"]
    for snapshot in (pr, final_pr):
        require(
            snapshot["number"] == collection["pr"]
            and snapshot["base"]["ref"] == repository["default_branch"]
            and snapshot["base"]["sha"] == base
            and (snapshot["base"]["repo"]["id"], snapshot["base"]["repo"]["full_name"])
            == (profile["repository_id"], profile["repository"])
            and snapshot["head"]["sha"] == collection["head"]
            and snapshot["head"]["ref"] == pr["head"]["ref"]
            and (snapshot["head"]["repo"]["id"], snapshot["head"]["repo"]["full_name"])
            == (pr["head"]["repo"]["id"], pr["head"]["repo"]["full_name"]),
            "PR endpoint identity changed during collection",
        )
    ready = all(
        snapshot["state"] == "open" and snapshot["draft"] is False and snapshot["mergeable"] is True
        for snapshot in (pr, final_pr)
    )
    require(
        pr["state"] == final_pr["state"] == "open" and (ready or observe_unready),
        "Candidate not ready for normal integration",
    )
    now = now or datetime.now(UTC)
    for row in [active["pr"], *collection["final"]]:
        instant = datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00"))
        require(0 <= (now - instant).total_seconds() <= 900, "Live candidate observations stale")
    require(
        collection["final"][0]["response"]["head"]["sha"] == collection["head"]
        and collection["final"][1]["response"]["commit"]["sha"] == base,
        "Candidate/default moved during collection",
    )

    def tree(record):
        commit, value = record["commit"]["response"], record["tree"]["response"]
        require(
            commit["tree"]["sha"] == value["sha"] and value["truncated"] is False,
            "Tree identity or completeness mismatch",
        )
        result = {}
        for row in value["tree"]:
            if row["type"] == "tree":
                continue
            name = safe_path(row["path"])
            require(name not in result, "Duplicate tree path")
            result[name] = (row["mode"], row["sha"], row["type"])
        return commit, result

    prior, previous = tree(collection["base"])
    original_tree = dict(previous)
    require(prior["sha"] == base, "Wrong base tree")
    require(
        len(collection["trees"]) == len(collection["commits"]) == pr["commits"] > 0,
        "Incomplete introduced history",
    )
    changed, commits = set(), []
    for record, listed in zip(collection["trees"], collection["commits"], strict=True):
        current, actual = tree(record)
        require(
            current["sha"] == listed["sha"]
            and [p["sha"] for p in current["parents"]] == [prior["sha"]],
            "Candidate history must be complete and linear from accepted base",
        )
        delta = {p for p in set(previous) | set(actual) if previous.get(p) != actual.get(p)}
        require(
            delta <= set(profile["paths"]) and not delta.intersection(profile["frozen_paths"]),
            "Unclassified or frozen path in retained history",
        )
        for name in delta:
            if name in actual:
                require(
                    actual[name][0] == profile["paths"][name] and actual[name][2] == "blob",
                    "Unregistered mode/symlink/submodule",
                )
        require(
            len({p.casefold() for p in actual}) == len(actual), "Case-insensitive file collision"
        )
        changed.update(delta)
        commits.append(current["sha"])
        prior, previous = current, actual
    require(prior["sha"] == collection["head"] and changed, "Wrong or empty candidate tip")
    require(len(collection["files"]) == pr["changed_files"], "Incomplete endpoint file inventory")
    endpoint = {safe_path(f["filename"]) for f in collection["files"]}
    endpoint.update(
        safe_path(f["previous_filename"]) for f in collection["files"] if "previous_filename" in f
    )
    actual_delta = {
        p for p in set(original_tree) | set(previous) if original_tree.get(p) != previous.get(p)
    }
    require(endpoint == actual_delta, "Endpoint diff differs from complete candidate trees")
    reviews = verify_all_reviews(collection, profile, now=now)
    if not ready:
        reviews["result"] = "NOT_RUN"
    require(profile["ci"]["source_commit"] == base, "CI policy is not selected from accepted base")
    inventory_times = [
        datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00"))
        for row in collection["ci"]["inventory"]
    ]
    require(
        inventory_times
        and all(0 <= (now - instant).total_seconds() <= 900 for instant in inventory_times),
        "Live CI run inventory stale",
    )
    inventory = normalize_ci(
        collection["ci"],
        accepted_policy=profile["ci"],
        observed_at=min(inventory_times).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    present = {run["workflow"] + "@" + run["event"] for run in inventory["runs"]}
    if observe_unready and not set(profile["ci"]["required_workflows"]) <= present:
        ci = {"result": "NOT_RUN", "inventory": inventory}
    else:
        ci = ci_evidence(
            inventory,
            repository=profile["repository"],
            head=collection["head"],
            accepted_policy=profile["ci"],
            now=now,
        )
    return {
        "result": "PASS" if reviews["result"] == ci["result"] == "PASS" else "FAIL",
        "base": base,
        "head": collection["head"],
        "tree": prior["tree"]["sha"],
        "effects": "NO_PRODUCTION",
        "paths": sorted(changed),
        "commits": commits,
        "reviews": reviews,
        "ci": ci,
        "write_authorized": False,
    }
