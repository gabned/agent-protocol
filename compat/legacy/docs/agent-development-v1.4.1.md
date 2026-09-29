# Agent Development Protocol 1.4.1 — Auditable Continuation and Portable Release Profiles

This release hardens the v1.4.0 orchestration overlay without changing any
v1.3.0 review gate or any v1.2/v1.2.1 lifecycle, effect, binding,
trusted-base change-control, release, publication, production, waiver, or
post-merge reconciliation gate.

The executable v2 contract is `tools/agent_protocol_v1_4_1.py`. The immutable
v1.4.0 compatibility validator remains `tools/agent_protocol_v1_4.py`.
Both are offline, stateless, connector-input-only tools. Neither can poll,
dispatch a workflow, enable auto-merge, access credentials, publish, deploy, or
run in the background.

## Contract versions

- `AGENT_DEVELOPMENT_PROTOCOL: 1.4.1`
- `LIFECYCLE_SCHEMA: 1.2`
- `CAMPAIGN_SCHEMA: 2`
- `HANDOFF_SCHEMA: 2`
- compatible input: `1.4.0 / CAMPAIGN_SCHEMA: 1`

Schema v2 adds history and identity; it does not turn a campaign into merge,
release, or production authority. Every critical `UNKNOWN` remains blocking.

## Corrected failure mode

The read-only S04 evidence demonstrates the v1 limitation:

1. owner PR #172 merged as
   `d63c1028b4f3751f752359f8b0f94a4d93bfe6dd`;
2. corrective PR #173 then merged as
   `8649b98aad969b32767f2a90492e4ce5d5969bd2`;
3. the schema v1 slice snapshot retained only #173, so the owner/correction
   lineage was overwritten even though the issue still described both.

Schema v2 replaces the singular PR fields with an ordered ledger. Issue #171,
the two merged PRs, campaign #160, and active S05 issue #174 are evidence only;
v1.4.1 does not edit them.

## Ordered owner/correction ledger

Every slice contains `pull_requests`, whose entries have exact keys:

```json
{
  "sequence": 1,
  "role": "OWNER",
  "pr": "#172",
  "state": "MERGED",
  "head_sha": "d1153d3038e3456faa1279d3187994528dffaf01",
  "merge_sha": "d63c1028b4f3751f752359f8b0f94a4d93bfe6dd"
}
```

The first entry is always `OWNER`; later entries are `CORRECTION`. Sequences
are contiguous, PR references are unique, and merged entries retain exact head
and merge SHAs. Closed, unmerged attempts remain `CLOSED`; they are not removed.
Only the final ledger entry may be `OPEN`, and a campaign may contain at most
one open owner or correction PR across all slices. A correction therefore
extends history instead of replacing it. `PR_OPENED` appends exactly the new
open entry and cannot update an existing one. A new commit on that one open PR
updates only its `head_sha` through a distinct `PR_SYNCHRONIZED` receipt; that
event cannot append an entry, and the PR number and role remain immutable. The
final head is recorded before the entry can become `MERGED` or `CLOSED`. An
unmerged close uses `PR_CLOSED`; the next correction is then appended without
deleting the closed attempt.

## Append-only transition receipts

Every schema v2 campaign contains at least one receipt. A receipt records:

- a contiguous sequence and closed operation (`INITIALIZE`,
  `SCHEMA_MIGRATION`, or `STATE_TRANSITION`);
- one closed real GitHub resource event: issue, pull request, commit, workflow
  run, release, or deployment, plus its closed action and applicable terminal
  conclusion;
- SHA-256 of the predecessor and successor campaign state, where state excludes
  only the receipt list to avoid a circular digest;
- for every new state transition, the exact predecessor and successor state
  snapshots whose canonical bytes produce those two digests;
- the previous receipt digest, deterministic idempotency key, and its own
  canonical digest.

The first native v2 receipt starts at the fixed genesis digest. A migrated
receipt starts at the canonical digest of its exact schema v1 input. Each later
predecessor digest must equal the previous successor, and each
`previous_receipt_sha256` must equal the prior receipt digest. The final
successor must equal the current campaign-state digest.

Validation reconstructs the state after every receipt, verifies the snapshots
against both digests, and applies the immutable-identity, ordered-ledger, frozen
scope, exact-event binding, and event-owned mutation checks to every adjacent
pair. Digest continuity alone is never transition evidence. A
`SCHEMA_MIGRATION` receipt always carries both its exact schema v1 source and
deterministic schema v2 result snapshots; omitting either fails closed even when
the migration is the final receipt. A legacy final
transition remains readable when its predecessor and current successor are
uniquely reconstructible. After continuation, the next receipt's predecessor
snapshot supplies that same legacy successor. Consecutive missing intermediate
states remain ambiguous and fail closed.

Native `INITIALIZE` also binds the exact owner `ISSUE/OPENED` event and
establishes an uneffected campaign: all slices planned with empty PR ledgers,
no candidate, deployed or published build, no checkpoint, and exactly one
executable next-slice action. Its receipt carries the canonical initial-state
snapshot, whose digest must equal the first successor in every later receipt
chain; the idea inbox is empty so every idea requires its own `ISSUE/OPENED`
transition. The snapshot's immutable campaign identity, ordered slice IDs and
retained slice issues must match the enclosing campaign for the entire chain.
Immutable identity includes the train ID and target version, the inbox policy,
and the profile-bound upstream repository.
Effects require later `STATE_TRANSITION` receipts.

`append_transition_receipt()` accepts only an exact retained prefix, frozen
campaign identity and slice order, a valid successor snapshot, and a new GitHub
event. Replaying the already-applied final event against the unchanged state is
an idempotent no-op. Reusing it for different state, altering history, adding
two receipts at once, or supplying time/polling text as an event fails closed.
`validate_append_only()` compares predecessor and successor snapshots directly.
GitHub publication and later release verification are separate evidence:
publication consumes the exact `RELEASE` event, while verification consumes an
exact-head `WORKFLOW_RUN`, so neither receipt reuses the other event.

The receipt's event also owns a closed mutation surface. Pull-request and gate
events can change only their identified slice; `ISSUE/CLOSED` can cancel only
its identified slice. `SLICE_ISSUE_OPENED` consumes exactly one
`ISSUE/OPENED` event to assign its reference to one issue-less `PLANNED` slice
and activate only that slice; it cannot rewrite a retained issue, choose an
ambiguous slice, change a PR ledger, train, checkpoint, or inbox, or reuse the
event. Outside that transition, `ISSUE/OPENED` may append exactly its own
reference to the idea inbox without changing frozen scope. Candidate, publication,
upstream verification, deployment, and terminal verification events can change
only their corresponding train or checkpoint fields plus orchestration status.
One event therefore cannot cancel unrelated slices or invent later release,
deployment, verification, or checkpoint state. Upstream verification also
requires both the stored observation and release event to equal the recorded
`release:v{published_version}` exactly.

Workflow conclusions are a closed registry. `GATES_PASSED`, release
verification, deployment, and production verification require `SUCCESS`, while
`GATES_FAILED` requires a terminal non-success conclusion. A
`DEPLOYMENT/CREATED` event is non-terminal and cannot satisfy
`PRODUCTION_DEPLOYED` or `PRODUCTION_VERIFIED`; deployment evidence is either a
successful completed workflow run or `DEPLOYMENT/STATUS_SUCCEEDED`. Production
verification consumes a second successful GitHub event. Event reuse is checked
without the conclusion field, so rewriting only an outcome cannot create new
evidence.
Candidate qualification binds both `observed_event_ref` and the commit event's
reference/SHA to `candidate_build_sha`. Deployment binds both
`observed_event_ref` and the successful workflow or deployment event SHA to
`deployed_build_sha`; terminal verification uses a distinct event carrying that
same exact build. An unrelated successful SHA cannot qualify, deploy, complete,
or checkpoint the train.

Earlier schema v2 receipts without `conclusion` remain readable when the event
kind is non-ambiguous. Missing workflow or successful-deployment conclusions
fail closed, while predecessor/successor pairs containing non-ambiguous legacy
events remain append-only auditable. A deterministic schema 1 migration may
preserve `UNKNOWN` only on its single `SCHEMA_MIGRATION` receipt and never
converts it into passed-gate, deployment, or verification evidence.

A schema v1 snapshot can name a passed or verified state without retaining the
terminal workflow conclusion. Migration preserves that historical observation
but replaces any success-dependent next action with `WAITING_EVENT`. Only a
later, distinct exact-head `WORKFLOW_RUN/COMPLETED/SUCCESS` receipt may restore
the merge or checkpoint action.

## Joint campaign and handoff

Schema v2 handoffs carry `campaign_sha256`, the digest of the complete campaign
including its receipt chain. `build_bundle()` validates or migrates the
campaign, derives the handoff, binds its digest, renders the canonical report,
and validates the two together. `validate_bundle()` rejects a changed outcome,
release status, action, prompt, resume state, or campaign digest.
The public `validate-handoff` command requires `--campaign <path>` and performs
the same joint bundle validation; structural handoff validation alone is not a
portable proof of conformance.

The human report remains exactly five lines, no more than 120
whitespace-delimited words, and contains exactly one `Next action`:

```text
Outcome: DELIVERED | BLOCKED | CAMPAIGN_COMPLETE | RESUME_REQUIRED.
Delivered: <one compact result>
Release: <one closed release status>.
Next action [<one closed type>]: <exactly one action>
Prompt: <exact prompt only for USER_ACTION_REQUIRED; otherwise NONE>
```

`RESUME_REQUIRED` is allowed only with machine reason `SESSION_LIMIT` and next
type `RESUME_SESSION`. It changes no campaign state and creates no receipt,
because a session boundary is not a GitHub event. It has no prompt and cannot
replace `BLOCKED`, `HUMAN_GATE`, or `CAMPAIGN_COMPLETE`. Resuming consumes the
same exact campaign and last receipt, so session exhaustion is distinct from a
technical blocker or a human decision.

## Portable closed release profiles

The profile is selected by exact repository identity. It is a ceiling and
cannot waive local gates.

| Repository | Closed profile | State model | Maximum envelope | Terminal boundary |
| --- | --- | --- | --- | --- |
| `gabned/provelume` | `GITHUB_ARTIFACT` | PR-local | `THROUGH_RELEASE` | exact GitHub version/build published and verified |
| `brickms/brickms` | `CODE_ONLY_PRODUCTION_B` | persistent checkpoint | `THROUGH_PRODUCTION_B` | exact reversible candidate deployed and verified |
| `maxithlon/maxithlon` | `DEPLOYMENT_LEVEL_C` | persistent checkpoint | `THROUGH_PRODUCTION_B` | explicit human Level C authorization, then exact deployment verification |
| `gabned/provelume.com` | `UPSTREAM_RELEASE_VERIFIED` | PR-local | `THROUGH_PRODUCTION_B` | exact upstream Core release verified before local candidate deployment |

The Maxithlon profile deliberately has no autonomous Level C envelope.
`DEPLOY_PRODUCTION_C` is valid only in `HUMAN_GATE` with
`LEVEL_C_AUTHORIZATION` and one exact human prompt. The BrickMS and site
production B profiles require `REVERSIBLE_PRODUCTION`. The site profile also
requires exact upstream repository, published version, published build SHA, and
`VERIFIED` state before its production B action; the proving release event must
use the exact recorded `release:v{published_version}` reference. Core rejects
every deployment identity and production action.

The committed fixture
`.github/agent-protocol/conformance-v1.4.1.json` records the four profiles and
their exact GitHub heads observed read-only on 2026-09-03. It also retains the
#172 owner → #173 correction regression. The fixture is sanitized historical
conformance evidence, not a live checkpoint or authority source. Its
`writes_performed` value is `false` for every other repository.

## Train, versions, and builds

Schema v2 keeps six identities independently verifiable:

| Field | Meaning |
| --- | --- |
| `train_id` | delivery campaign identity |
| `target_version` | intended semantic version |
| `published_version` | version actually public, or `NONE` |
| `candidate_build_sha` | exact qualified candidate, or `NONE` |
| `deployed_build_sha` | exact deployed source, or `NONE` |
| `published_build_sha` | exact source of the public artifact, or `NONE` |

For `GITHUB_ARTIFACT`, candidate and published builds must match and deployment
must remain `NONE`. Deployment profiles may have a candidate and deployed build
without claiming a GitHub publication; deployed must equal the qualified
candidate. `UPSTREAM_RELEASE_VERIFIED` records upstream version/build in a
separate nested identity and never conflates it with the site build.

A release train is not a release, a semantic version is not a build, and a
candidate is neither deployed nor published merely because its gates passed.

## Deterministic schema 1 → 2 migration

`migrate_campaign()` first validates the exact v1.4.0 schema. It then:

1. preserves campaign identity, order, authority, scope, checkpoint, inbox, and
   event; a success-dependent pending action is closed to `WAITING_EVENT` until
   new exact-head `SUCCESS` workflow evidence arrives;
2. maps the singular recorded PR into the first `OWNER` ledger entry;
3. maps legacy `build_sha` only to the identity justified by the legacy
   publication state;
4. assigns the repository's closed release profile;
5. emits one deterministic `SCHEMA_MIGRATION` receipt bound to the legacy
   GitHub resource, exact legacy source and migrated state snapshots, and their
   predecessor/successor digests.

No timestamp, network response, random value, or local path enters the result.
Repeated migration of the same v1 input produces identical bytes; migrating an
already-valid v2 campaign is an idempotent no-op.

Migration cannot recreate history already overwritten in schema v1. It retains
the recorded PR as `OWNER` and does not guess that it was a correction. Adding
older owner/correction entries requires separate, authorized reconciliation
against real GitHub issue and PR evidence. This release intentionally does not
migrate or modify #160.

Schema v1 handoffs remain valid through the unchanged v1.4.0 tool. They are not
independently upgraded: a v2 handoff is regenerated jointly from the migrated
campaign so its digest and one action cannot drift.

## Preserved v1.3 and repository gates

Before merge, the unchanged exact head still requires:

- exact base/head/path binding, ancestry, and mergeability;
- trusted-base v1.2.1 change control and exact effect prediction;
- final-head permanent CI and repository-required reviews;
- zero current technical findings and zero unresolved review threads;
- the opt-in-only v1.3 Codex review state machine;
- clean-room, deterministic build, release, publication, deployment, and
  production gates applicable to the repository profile;
- no agent-authored waiver;
- observational post-merge reconciliation.

`.github/workflows/ci.yml` is classified `KEEP_AND_HARDEN`: all existing job and
check names remain, while the clean-room job also executes the v1.4.1 self-test
and read-only conformance validation. No second workflow or background executor
is introduced.

## Offline commands

```bash
python tools/agent_protocol_v1_4.py self-test
python tools/agent_protocol_v1_4_1.py self-test
python tools/agent_protocol_v1_4_1.py validate-conformance \
  .github/agent-protocol/conformance-v1.4.1.json
python tools/agent_protocol_v1_4_1.py migrate-campaign \
  .agent/campaign-v1.json --output .agent/campaign-v2.json
python tools/agent_protocol_v1_4_1.py generate-bundle \
  .agent/campaign-v2.json --delivered "<one compact result>" \
  --output .agent/handoff-bundle.json
python tools/agent_protocol_v1_4_1.py validate-bundle \
  .agent/handoff-bundle.json
python tools/agent_protocol_v1_4_1.py verify-continuation \
  .agent/campaign-before.json .agent/campaign-after.json
```

All generated operational evidence remains under ignored `.agent/`. Unknown
keys, open registry values, invalid identities, missing digests, rewritten
receipts, multiple open PRs, mismatched profiles, over-authority actions, or
overlong/drifted handoffs exit fail-closed with status 2.
