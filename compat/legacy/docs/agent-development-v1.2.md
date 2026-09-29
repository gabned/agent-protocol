# Agent Development Protocol v1.2 — Core subset

This repository adopts the common v1.2 contract through lightweight, pull-request-local ownership. GitHub remains the executable source of truth. No `AGENT_STATUS.md`, global lock, private checkpoint, second lifecycle store or runtime dependency on Nexus is introduced.

The protocol does not replace clean-room, Linux/Windows, deterministic-build, no-network, release, least-privilege or publication controls. It makes discovery, identity binding, effect classification and post-merge reconciliation explicit and fail-closed.

## One bounded reconciliation

At the beginning of a new or resumed workstream, observe once:

1. current `main` SHA and the proposed branch merge base;
2. the single owner pull request and exact head SHA;
3. CI, required-review policy, review verdict, unresolved threads and mergeability;
4. package version, tag/release state and relevant roadmap issue;
5. the last relevant workflow outcome when the workstream can affect a release.

Observe again only after a real head, CI, review/thread, merge, tag, release or publication event. An inaccessible fact is `UNKNOWN`; it is never inferred from absence and blocks every gate that requires it.

## PR-local lifecycle

The lifecycle is deliberately light:

- `CLAIMED`: a real branch exists from the verified base; no owner PR exists yet;
- `BOUND`: exactly one owner PR exists and an exact effect report is bound to one candidate head;
- `MERGED`: GitHub proves the owner PR merged and proves binding/default ancestry;
- `RELEASED`: a separate authorized release workflow proves the tag and publication state.

The branch and PR are the shared state. Reports, bindings and connector snapshots stay under ignored `.agent/`; they are never committed as a second checkpoint.

Identifiers are closed and undecorated. PRs use `#N`, SHAs use complete lowercase 40-character values, report identities use complete lowercase SHA-256 values, and unavailable values use a closed sentinel such as `NONE`, `UNBOUND`, `UNASSIGNED`, `NOT_APPLICABLE`, `PENDING` or `UNKNOWN`.

## Exact effect report and binding

Generate a report from the exact connector-provided changed-file list:

```bash
python tools/agent_protocol.py effects \
  --connector-files .agent/changed-files.json \
  --source GITHUB_CONNECTOR \
  --base-sha <exact-main-sha> \
  --head-sha <exact-candidate-sha> \
  --policy NO_PRODUCTION \
  --complete \
  --output .agent/effect-report.json
```

The report is canonical schema-2 JSON with a self-verifying `report_sha256`. Copy/rename evidence includes both source and destination. Verification recomputes effect, matches, errors and authorization from the normalized path set; editing the claimed effect or hash cannot turn a production-capable delta into a safe one.

Effects are:

- `NO_PRODUCTION`: only the six explicitly allowlisted rollout paths;
- `PRODUCTION`: Core source, dependency/version/release identity, release scripts, every non-CI workflow/reusable action and every unclassified path;
- `UNKNOWN`: incomplete, empty, invalid or open path evidence.

`NO_PRODUCTION` authorizes only `NO_PRODUCTION`. `REPOSITORY_POLICY` can admit a known `PRODUCTION` delta only to the repository's stronger existing product/release gates; it never publishes or grants release authority. `UNKNOWN` cannot bind.

Bind the exact report to one PR-local owner:

```bash
python tools/agent_protocol.py bind \
  --report .agent/effect-report.json \
  --pr '#45' \
  --workstream agent-protocol-v1.2-subset \
  --output .agent/binding.json
```

A later material head movement requires a new effect report and binding. A merge snapshot may use a newer PR head only when it explicitly proves that the binding basis is its ancestor.

## Connector-only merge evidence

A fresh schema-2 connector snapshot is cross-bound to the exact owner PR, base SHA, binding-basis SHA and effect-report SHA-256:

```bash
python tools/agent_protocol.py preflight \
  --snapshot .agent/connector-snapshot.json \
  --binding .agent/binding.json \
  --output .agent/preflight.json
```

The snapshot must prove an open non-draft owner PR, successful required checks, zero unresolved threads, mergeability, base ancestry and binding-basis ancestry. Required-review policy itself must be known. An advisory review with no verdict may remain `UNKNOWN` only when GitHub proves approval is not required; an observed `CHANGES_REQUESTED` always blocks.

The connector process supplies evidence but this tool makes no network request and must explicitly record that credentials and production environments were not accessed. It cannot dispatch/rerun workflows, create tags, publish artifacts, deploy, migrate or write runtime data.

## Observational post-merge reconciliation

After a real merge event, reconcile once:

```bash
python tools/agent_protocol.py reconcile \
  --evidence .agent/reconcile-evidence.json \
  --binding .agent/binding.json \
  --output .agent/reconciliation.json
```

Identity proof requires owner PR `MERGED`, binding-basis ancestry, merge SHA presence on `main` and the exact current default SHA. The current default may legitimately be newer than the merge SHA; ancestry/presence, not tip equality, is authoritative.

Workflow, release or publication evidence that is not exposed remains `UNKNOWN`. Identity can still be proven without inventing a successful outcome. Reconciliation is observational only and cannot trigger or modify anything.

## Workflow decision matrix

No workflow is removed, replaced or renamed in this rollout.

| Workflow | Classification | Rationale |
| --- | --- | --- |
| `.github/workflows/ci.yml` | `KEEP_AND_HARDEN` | retain clean-room, Linux/Windows tests and deterministic dry run; add the offline v1.2 contract inside the existing CI and preserve check names |
| `.github/workflows/refresh-build-input-lock.yml` | `KEEP` | preserve the repository-local build-input lock lifecycle |
| `.github/workflows/release-dry-run.yml` | `KEEP` | preserve release rehearsal and no-publication controls |
| `.github/workflows/release-pipeline.yml` | `KEEP` | preserve the specialist release pipeline |
| `.github/workflows/release-publish.yml` | `KEEP` | preserve protected publication controls |
| `.github/workflows/release.yml` | `KEEP` | preserve current release orchestration and check names |
| `REPLACE` | none | no duplicate workflow is introduced |
| `REMOVE_AS_OBSOLETE` | none | future removal requires origin, useful-delta preservation and replacement/obsolescence evidence |

## Verification

```bash
python tools/agent_protocol.py self-test
python -m ruff check core tests scripts tools
python -m pytest -q
git diff --check
```

`tools/agent_protocol.py` remains Git mode `100755`. CI verifies its mode, confirms `.agent/` is ignored, rejects a global `AGENT_STATUS.md`, and preserves all clean-room, Linux, Windows and deterministic release-dry-run jobs.

## Product boundary

Protocol rollout and product development never share a PR. Product PR `#37` is not modified by this rollout. Its current head, divergence, CI, review/thread state and roadmap disposition must be reconciled once after the transverse protocol layer is clean; cached historical coordinates are not treated as current evidence.
