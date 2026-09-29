# Protocol 1.4.6 — verified evidence reuse

This orchestration overlay reduces duplicate connector reads while keeping engine
1.4.2, lifecycle 1.2, campaign/handoff schema 2 and every existing gate. It changes
neither test selection nor production authority. The Work dependency inventory
remains eight files; the implementation and tests extend the existing collector.

## Reuse contract

| Evidence | Collection rule |
| --- | --- |
| Git commits and complete trees | Exact repository, object SHA and query shape; original observation retained |
| Source commit anchor and default refs | Fresh reads on every source acquisition; unchanged offline tree/blob verification |
| Terminal CI attempts and jobs | Fresh complete exact-head run inventory first; exact run/attempt/head and complete job pages |
| Running CI, unavailable responses or truncated trees | Never installed as reusable evidence |
| PR identity/files, policy, reviews and required-check selection | Fresh through the existing operational flow |
| Authority, local checks, binding, merge and post-merge readiness | Existing independent validation and execution; never inferred from cache |

Use the complete bootstrap in [the Work guide](agent-development-v1.4.3-work.md).
It creates `evidence` with `createEvidenceCollector` and passes its `readTree` to
source collection. Keep that collector for the bounded operation. All actual
responses are persisted before validation or caching. Each hit persists a separate
reuse record containing the original observation and a distinct `reused_at`;
the original `observed_at` never changes. Storage failure stops the operation.

For operational CI collection, call `await evidence.collectRuns(exactHeadSha)`.
This reads every run page, then every attempt from 1 through the observed current
attempt and every jobs page. It retains failed, cancelled and successful histories.
Only complete terminal histories enter the cache. A new attempt always receives
its own observations. If the current attempt becomes live or its conclusion
changes, its cached entry is discarded. Malformed identity, duplicates, incomplete
pagination and exhausted bounds fail explicitly; there is no automatic retry.

The result has `history_only: true` and `push_qualified: false`. Its inventory and
original attempt/jobs observations feed the unchanged operational validator;
collection itself cannot establish which workflows are required, qualify a head,
replace trusted-base or candidate CI, or authorize a merge. Observe the live gate
again at the existing decision boundary. A run starting after an observation
does not make older history proof of current readiness.

`readImmutable("commits", sha)` and `readTree(sha, recursive)` return
`{observation, reused}`. They accept no branch names or arbitrary endpoints.
The source path deliberately keeps its commit anchor fresh, even when an
operational caller separately reuses the same commit as historical evidence.
Typed file/blob acquisition retains the existing independently rehashed blob
cache; this overlay does not add decoded-file or PR-file caching.

## Resume and provenance

`evidence.snapshot()` returns the cache as a JSON string. Save these exact bytes
with the raw observation history using the [recovery archive](agent-development-v1.4.5-work.md),
and independently retain their SHA-256 and provenance outside candidate content.
Before loading a restored snapshot, establish the actual authorized host origin.
An archive hash or self-declared provenance is insufficient to authenticate data.

Pass the exact `cacheSnapshot` string, `expectedCacheSha256` and a trusted host
`sha256(text)` callback into `await createEvidenceCollector(...)`. The callback
must calculate SHA-256 over the UTF-8 bytes using the host's standard cryptographic
runtime. No crypto implementation or network fallback is embedded in this module.
Digest, repository, schema, key, timestamp, object and complete terminal-history
validation precedes insertion. A corrupt or mismatched snapshot fails closed;
explicitly starting a new cold collection is a separate host decision.
The host selects the snapshot and expected digest independently of candidate
files, just as it independently selects original user authority.

In-memory entries are immutable serialized strings; returned objects are copies.
Cache state is observational only. It cannot store policy, reviews, PRs, local
test receipts or authorization. Restoring it does not refresh those gates or
execute scripts. Limits remain finite: 10,000 calls/entries maximum, 100 pages
and attempts maximum, and a 64 MiB imported snapshot limit.

## Checkpoint-driven execution

This procedure applies when selected by the accepted current manifest. Historical receipt and handoff
schemas keep their original meaning; the original `handoff` helper remains
available for replay. New closures use `checkpoint-handoff`.

The existing campaign/receipt ledger or repository checkpoint is the sole writable
resume state. Core uses its issue/PR-local ledger, never `AGENT_STATUS.md`. Read it
once, reconcile only changed facts against the current owner/roadmap and retain the
source reference and observation time. A projection, context receipt or rendered
prompt is derived evidence, not another editable checkpoint. Do not copy the whole
conversation, repository contract or ledger into each issue, PR and final answer.

Before a read/check/write, identify what current decision needs it. Reuse applicable
evidence while its source, scope, dependencies, completeness and validity hold.
Record the specific changed input, inconsistency or mandatory freshness rule when
repeating work. Immutable source reuse, context retention and operational evidence
reuse are different: none replaces exact-head CI, fresh policy/reviews/PR identity,
non-reusable local checks, expected-head merge or post-merge verification. Expand
acquisition only for a named dependency or gate. Reconcile an uncertain successful
write through its existing idempotency receipt before attempting it again.

For context delivery, first run the accepted `select-documents` with its independently
verified manifest. It still verifies the complete inventory and topology. Then run:

```text
python tools/agent_protocol_v1_4_7.py context-delta --input selection-input.json --trusted host-context.json
python tools/agent_protocol_v1_4_7.py checkpoint-handoff --input handoff-input.json --trusted host-state.json
```

All input files are temporary external evidence. `context-delta` input contains the
actual `selection` output and `retained` context receipt; trust contains their
independently retained `trusted_selection` and `trusted_retained` digests plus the
current host `context_id`. Start with an empty retained `documents` map. A receipt
contains only `context_id`, `manifest_sha256` and a path-to-content-digest map.
The host must know the text is still available in that exact model context. After
compaction, a new chat/model context or any uncertainty, change the context identity
or clear retention. A saved file alone does not mean the model retains its text.
Changed manifest/context or uncertain selection resends all selected text; a corrupt
binding stops. New phases deliver newly required text. No file acquisition, integrity
verification, authority or operational qualification is skipped by this renderer.

`checkpoint-handoff` input contains `checkpoint`, `roadmap` and `recommendation`.
The host independently derives these projections from existing state and retains
their digests in `trusted_checkpoint` and `trusted_roadmap`. Digests bind bytes;
they do not authenticate a user instruction or prove semantic authorization.

- Checkpoint fields: repository, PR, exact head, state, actual authorized scope,
  result, checks, residuals, next step and metrics. Its `next` contains
  `roadmap_step`, `kind`, `action`, one complete `prompt`, and `authorization`.
- Roadmap fields: repository, original reference and ordered steps with `id` and
  `state` (`COMPLETE` or `PENDING`). The next step must be the first pending step.
  A recovery action remains attached to that step; do not skip it for a new release.
- `CONTINUE` and `RECOVER` require `GRANTED` and return `CONTINUE_IN_SESSION`:
  finish the authorized work now. A handoff is not a reason to stop or request a
  replacement prompt. `DECISION` identifies the concrete outstanding user decision;
  retain `GRANTED` when authority exists, or `MISSING` when that decision is consent.
  Prepare all independently authorized work before asking. An adoption
  pilot outside this task is a proposal requiring a new instruction, never a rollout
  authorization inherited from a generated prompt.

The recommendation records target `environment`, exact `model`, supported
`reasoning`, estimated `workload` (`LOW`, `MEDIUM`, `HIGH`), concise `rationale` and
principal `uncertainty`. Choose the lowest expected total time/cost compatible with
quality, including correction risk: consider complexity, risk, context and required
tools. Do not default to the strongest model or maximum reasoning. Workload is an
estimate, distinct from the model's reasoning setting and measured duration.

Reuse still-valid model availability in the same checkpoint. The independent host
input `model_availability` binds environment, actual source, original observation,
host-established `valid_until` and exact model-to-supported-efforts mapping through
`trusted_models`. Verify again only after expiry, client/tool incompatibility,
rollout/access change or conflicting evidence. The host establishes validity from
the source and target environment, never from candidate wishes; this is not the
15-minute operational qualification clock. Client/account access may remain unknown
despite public documentation. If unverifiable, supply null availability/digest and
null model/reasoning with explicit uncertainty; never invent names or settings.
The renderer recommends selection and always reports `model_changed: false`.

Every closing response includes brief result/checks/residuals, exactly one next
action, model and reasoning, workload rationale/uncertainty and one complete prompt
preceded by settings to select. The host checks that the action/prompt actually
matches the checkpoint, verified roadmap and user's scope. The offline renderer
cannot determine semantic authorization, optimal model cost or real client access.
No new gate, approval, release, consumer or product scope arises from this output.

Store lightweight `metrics` inside the same checkpoint: `kind` (`ACTUAL`, `REPLAY`,
`SYNTHETIC`), observation `window`, measurement `source`, `elapsed_seconds`,
`tool_calls`, `github_calls`, `repeated_reads`, `repeated_checks`, `input_tokens`,
`output_tokens`. Counts are measured nonnegative integers or null when unavailable;
null is not zero. Preserve raw counters and their scope, distinguish required
freshness repetitions from avoidable repeats in the source evidence. Record tools
called outside the collector separately before forming a host total. Use reported
token usage only; do not convert file bytes into tokens, cost or savings. Compare
the same scenarios with compatible measurement boundaries; workload estimates and
synthetic improvements are not measured whole-session savings. Do not add an
analytics service, extra CI suite or parallel checkpoint just for these counters.

## Measurement and adoption

`evidence.metrics()` reports actual `connector_reads`, `reused_reads`, and
`100 * reused_reads / (connector_reads + reused_reads)`. The denominator is the
same sequence of logical reads without reuse. Cache verification, persistence,
fresh inventories, source checks and CI execution remain real work. A synthetic
two-pass terminal-history scenario performs four connector reads instead of six
(33.3%); that narrow fixture is not a prediction for a complete campaign.

Measure the actual workload separately. Report connector counts and payload
volume as such; do not relabel them as token, active-model-time or credit savings.
Historical replay stays outside public source unless all inputs are synthetic
or public. Workloads with few repeats may save little or nothing.

After canonical acceptance, run the unchanged `sync-adopter` entrypoint from
the accepted revision. It synchronizes all eight Work pins, four operational
helpers, manifest/provenance and the generated current 1.4.6 sections. Previous
1.4.5 sections and receipts remain historical; repeating 1.4.6 synchronization
is a no-op, while edited generated sections require explicit reconciliation.
Every adopter runs its existing complete local checks and final integration
gates. The campaign closes only after the canonical five-repository audit.
