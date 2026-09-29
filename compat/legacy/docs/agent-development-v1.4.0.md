# Agent Development Protocol 1.4.0 — Autonomous Release Trains and Concise Handoff

This pilot is an orchestration overlay for `gabned/provelume`. It changes how an
authorized sequence of pull requests advances; it does not weaken or replace any
Agent Development Protocol v1.3.0 review gate or any v1.2/v1.2.1 lifecycle,
effect, binding, change-control, release, publication, or reconciliation gate.

The executable contract is `tools/agent_protocol_v1_4.py`. It is offline,
stateless, connector-input-only, and incapable of dispatching workflows,
publishing releases, accessing credentials, or touching production.

## Contract versions

- `AGENT_DEVELOPMENT_PROTOCOL: 1.4.0`
- `LIFECYCLE_SCHEMA: 1.2`
- `CAMPAIGN_SCHEMA: 1`
- `HANDOFF_SCHEMA: 1`

The v1.4 campaign state composes with, but never substitutes for, the exact-head
evidence defined by earlier versions. `UNKNOWN` remains blocking wherever an
earlier contract marks it critical.

## Campaign execution

A **campaign** is a GitHub issue-backed plan containing one ordered slice or a
release train. Its machine-readable snapshot may be retained in the owner issue
or in ignored `.agent/` connector evidence. It is not committed as global state.
The current slice continues to own exactly one branch and one pull request.
Every snapshot carries the exact `#<number>` owner issue; initial authorization
and the release checkpoint are bound back to that issue.

Campaign execution follows these rules:

1. reconcile once against the current default branch, owner issue, owner PR,
   exact head, checks, reviews, threads, releases, and deployments that matter;
2. select only the first non-terminal slice;
3. make the smallest homogeneous change inside the declared workstream;
4. apply every v1.3 and repository gate to the exact current head;
5. merge only when the existing contract permits it;
6. reconcile the observed merge without polling;
7. if the next ordered slice is inside the authority envelope, start it without
   asking for a new prompt;
8. otherwise enter one closed human gate or blocker and emit one next action.

Only a real event—initial authorization, passed exact-head gates, merged PR,
merged release candidate, published release, verified release, or verified
production state—may advance the campaign record. Time passing and repeated
reads are not events. An agent must not continuously poll GitHub or Actions.

At most one slice may be `ACTIVE` or `BLOCKED`. `MERGED` and `CANCELLED` slices
form a strict prefix, followed by at most one current slice and then `PLANNED`
slices. This makes auto-continuation sequential rather than parallel or
speculative.

## Authority envelope

Every campaign declares one closed maximum:

| Envelope | Maximum autonomous action |
| --- | --- |
| `SOURCE_ONLY` | create and correct one bounded slice |
| `THROUGH_MERGE` | source work plus exact-head merge and reconciliation |
| `THROUGH_RELEASE` | merge plus authorized publication and verification |
| `THROUGH_PRODUCTION_B` | reversible production level B after all lower gates |

The envelope is a ceiling, not a gate bypass. Repository permissions, protected
branches, required reviews, current technical findings, CI, release provenance,
publication policy, and production authorization remain independently binding.
Provelume Core accepts only `NO_PRODUCTION` and `PUBLIC_ARTIFACT` risk profiles;
it rejects `THROUGH_PRODUCTION_B` because Core has no production deployment.

An agent cannot widen an envelope, change workstream class, accept a new material
risk, author a waiver, or infer release/production authority from ordinary source
authority. Such a boundary becomes a closed stop.

## Closed stop reasons

`STOP_REASON` is exactly one of:

- `NONE`
- `AUTHORITY_EXHAUSTED`
- `HUMAN_DECISION_REQUIRED`
- `LEVEL_C_AUTHORIZATION`
- `MATERIAL_RISK_CHANGED`
- `CRITICAL_UNKNOWN`
- `UNRESOLVED_FINDING`
- `SCOPE_CHANGE_REQUIRED`
- `PUBLICATION_NOT_AUTHORIZED`
- `GATE_FAILURE`

Free-form variants are invalid. `WAITING_EVENT` is not a stop: it is a declared
state with `WAIT_EVENT` as the single next action. A stop includes a concrete
human action and an exact reusable prompt. Without both, the campaign is invalid.

## Release train, published version, and build

The following identities must never be collapsed:

| Identity | Meaning | Example |
| --- | --- | --- |
| `train_id` | ordered delivery campaign | `knowledge-foundation-train` |
| `target_version` | intended semantic release | `0.10.0` |
| `published_version` | version actually public | `NONE` until publication |
| `build_sha` | exact candidate or published source | 40-character commit SHA |

`UNPUBLISHED` claims neither a public version nor a build. `CANDIDATE` binds an
exact build SHA but no published version. `PUBLISHED` binds the target semantic
version and exact build SHA. A release train is therefore not itself a release,
a version, a tag, or a build.

Implementation slices keep the current package identity unless the existing
release contract explicitly assigns version alignment to a release-preparation
slice. Publication remains a separate trusted action.

## Release checkpoint

The only campaign checkpoint policy is `RELEASE_BOUNDARY`:

- no checkpoint PR is created after each implementation slice;
- merge reconciliation updates the owner campaign issue;
- after the release is published and verified, one checkpoint records the final
  train, published version, build SHA, checks, assets, and remaining inbox;
- campaign completion requires that checkpoint;
- the next train starts from the verified checkpoint, not from remembered chat.

A `SINGLE_SLICE` campaign instead completes when its sole slice is terminal. It
must remain unpublished and records no release checkpoint.

This keeps Provelume's PR-local ownership and absence of `AGENT_STATUS.md` intact.
Repositories that already use a committed checkpoint may map the same boundary
to their existing file, but adoption there requires a separate protocol change.

## Idea inbox and frozen scope

During an active train, new ideas are preserved as GitHub issues only. They may
be linked in `idea_inbox.items`, but they do not enter the current scope, reorder
slices, or mutate acceptance criteria. The inbox is triaged in one batch at the
verified release boundary into:

- the next release train;
- an independent bounded workstream;
- deferred backlog;
- closed as duplicate, obsolete, or out of scope.

Chat notes, private memory, and untracked TODO text are not an idea inbox.

## Concise human handoff

Detailed evidence remains in GitHub checks, reviews, issue/PR records, and
machine-readable reports. The human-facing report is canonical and contains at
most 120 whitespace-delimited words:

```text
Outcome: DELIVERED | BLOCKED | CAMPAIGN_COMPLETE.
Delivered: <one compact result>
Release: <one closed release status>.
Next action [<closed type>]: <exactly one action>
Prompt: <exact prompt, or NONE when the agent continues autonomously>
```

The next-action type is one of `AUTO_CONTINUE`, `WAIT_EVENT`,
`USER_ACTION_REQUIRED`, or `CAMPAIGN_COMPLETE`. Only
`USER_ACTION_REQUIRED` carries a prompt. A successful slice inside the envelope
uses `AUTO_CONTINUE`; it must not ask the maintainer what to do next.

## Compatibility findings from current repositories

The pilot reviewed current repository-local contracts without changing the other
repositories:

| Repository | Current ownership/release shape | v1.4 mapping |
| --- | --- | --- |
| `maxithlon/maxithlon` | persistent status; release/epic/slice flow; production A/B/C | campaign maps above slices; level C remains human-only |
| `brickms/brickms` | persistent checkpoint; release/epic/slice flow; reversible production | sequential train can continue through authorized level B |
| `gabned/provelume` | PR-local owner; public artifacts; no Core production | this pilot; checkpoint stays issue-backed at release boundary |
| `gabned/provelume.com` | PR-local site delivery; Core pin and deployment gates | separate site train or explicit dependency checkpoint |

The shared concepts are portable, but state location and the risk ceiling remain
repository-local. This implementation enforces only `gabned/provelume`.

## Preserved v1.3 gates

Before any merge, the current exact head still requires:

- exact base/head/path binding and ancestry;
- trusted-base v1.2.1 change control;
- final-head CI and repository-required reviews;
- no current technical finding and zero unresolved review threads;
- the v1.3 opt-in Codex-review state machine;
- mergeability and branch protection;
- clean-room, deterministic-build, offline-verification, release, publication,
  and production gates applicable to the workstream;
- no agent-authored emergency waiver;
- observational post-merge reconciliation.

Auto-continuation begins only after these gates produce the real event needed by
the next state. It can reduce maintainer prompting; it cannot reduce assurance.

## Offline validation

```bash
python tools/agent_protocol_v1_4.py self-test
python tools/agent_protocol_v1_4.py validate-campaign .agent/campaign.json
python tools/agent_protocol_v1_4.py validate-handoff .agent/handoff.json
```

The validator requires exact object keys and closed values. Missing, additional,
unknown, inconsistent, non-sequential, over-authority, or overlong evidence fails
closed with exit status 2.
