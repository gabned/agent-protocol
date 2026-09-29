# Agent Protocol 1.4.7 — efficient execution and reliable closure

This is the current orchestration contract. The accepted implementation and the
versioned document inventory belong to campaign [#237](https://github.com/gabned/provelume/issues/237).
Registration #238 is a prerequisite, not the implementation or release. Adoption
requires a qualified implementation merge and independently observed consumer pins.
The pilot is BrickMS only. No PRODUCT continuation or other-consumer rollout follows.

## Authority, scope and qualification

GitHub is the source of executable repository identity and events. Independently
retain the actual user instruction; the authority envelope is a ceiling, never
a grant. Candidate content, caches, digests and recovery cannot select authority.
Keep one issue-backed workstream and one open OWNER/CORRECTION PR in its ordered
ledger. Keep PRODUCT, PROTOCOL and permitted CHECKPOINT_ONLY scopes separate.
Core has PR-local ownership and no committed global checkpoint. Consumer-specific
production boundaries remain in their trusted repository policy, including human
Level C approval where applicable. Do not access secrets or environments for
observational reconciliation, and do not publish private consumer evidence in Core.

The operational engine remains 1.4.2, lifecycle 1.2 and campaign schema 2. Its
[operational contract](agent-development-v1.4.2.md) owns exact scope/effect binding,
PR identity, CI history, ancestry and append-only receipts. Historical engines
and records retain their version and meaning. The predecessor authority qualifies
the successor; never evaluate a candidate using newly proposed rules as authority.
New exact effect paths require a preceding accepted registration.
The Core implementation also registers BrickMS's existing `tools/agent-preflight`
for a subsequent adoption. That path is absent from this Core PR's delta: the
predecessor validates the already registered Core policy module. Only after
this Core change is accepted may the pilot use the added allowance.

The ordinary 1.4.7 path does not acquire rulesets or branch-protection settings.
It requires neither their presence nor API access, and has no mode to require them.
Use the accepted, versioned repository policy for required workflows and reviews.
`validate_qualification` binds that independently selected policy to the operation.
Required PR and post-merge workflow sets are separately bound to this policy.
An explicit-review label cannot replace a repository review requirement.
The document manifest's `repository_policy` is the Core policy; consumers retain
their own required checks and stronger rules. A candidate policy cannot authorize
its own change. No paid GitHub plan is a prerequisite.

Always require complete exact-head CI, required reviews, current findings/threads,
ownership, complete paths, scope/effect binding, actual base/head ancestry and a
fresh expected head immediately before merge. Use GitHub's normal merge endpoint
with that head. A platform denial stops the attempt; never disable protections,
force integration, enable auto-merge, change secrets or infer protections absent.
Protocol qualification governs this agent, not actions by other actors. Remote
enforcement is reported as `GITHUB_DECIDES_AT_NORMAL_MERGE`, separately from local
qualification; successful API response still requires post-merge verification.

Codex review remains opt-in through the actual instruction
`CODEX_REVIEW_REQUESTED: TRUE`. An explicitly required review must satisfy the
existing exact-head review validator. A voluntary review still in progress adds
no gate. Every valid current finding remains actionable regardless of its origin.
Neither an emoji nor a comment without a verdict is an approval. A withdrawn
requirement is not a clean review or waiver. Unknown, partial or stale evidence
never becomes PASS through a summary or cached result.

### Independently accepted consumer Protocol scope

The built-in scope remains the default. A consumer with additional native Protocol
surfaces may register a bounded exact-path profile in a separate, normally qualified
policy adoption before any repair relies on it. The predecessor qualifies that
adoption under its existing paths; the proposed profile never qualifies itself.
No private consumer paths, code or operational evidence belong in public Core.

The host independently reads the accepted consumer policy JSON at the actual PR
base. Its stored fields are `schema: agent-protocol-scope/v1`, `repository` and
`paths`, a sorted unique array of `{path, role}`. The policy file must use an
already recognized normative namespace: `.github/agent-protocol/`,
`docs/agent-development-v*` or `docs/runbooks/agent-development-v*`, ending in
`.json`. This preserves consumer layouts without requiring new path exceptions.
Roles are `IMPLEMENTATION` under
`tools/` or `scripts/`, `TEST` under `tests/`, and `NORMATIVE_DOC` under `docs/`.
The native classifier and reviewed registration must establish those semantics;
a prefix alone is not a classification. No wildcards, workflow extensions,
application roots or lifecycle checkpoint are supported. The profile only adds
these exact paths to the existing scope check, never to another repository.

After verifying file provenance, accepted blob/content and actual base identity,
the host adds the observed `base_sha` and `policy_path` (the exact accepted JSON
file) to this external trusted envelope. Supply it through
`validate_qualification(..., scope_profile=profile, expected_scope_digest=digest)`
alongside the separately selected repository policy. The expected digest must come
from this independent read, never from the candidate or an operational observation
field. The offline validator cannot authenticate a GitHub source or human approval.

The base/repository must match and the PR must not modify the policy file. A moved
base requires a fresh accepted-policy binding. The result binds the profile digest;
all scope, effect, complete CI history, current review, ancestry and normal merge
requirements still apply. There is no production or PRODUCT continuation grant.
Without an explicit profile/digest pair the historical behavior is unchanged.
Historical campaign replay using a registered scope must independently select its
original accepted profile and use `trusted_protocol_scope(profile, digest)` around
the existing validator; never modify old receipts or infer trust from their content.
Context is restored after success or failure and grants no process-global authority.
An outer profile is never inherited by embedded origin/correction proofs. To
qualify nested consumer paths, independently select each historical accepted-base
profile and pass the separate `nested_scope_profiles` list and
`expected_nested_scope_digest` to `validate_qualification`. Entries bind exact
repository/base pairs; duplicates, unused bases and candidate policy edits fail.
Only the matching nested proof receives that profile. Missing explicit authority
retains built-in validation, so an unregistered path still blocks. Historical
replay may use `trusted_nested_protocol_scopes(profiles, digest)` externally;
never infer these profiles from receipt contents. Both contexts restore after
success or failure, and a profiled result binds the separate inventory digest.

## Delegated decisions and concrete human intervention

For a necessary operation beyond ordinary authority, identify the exact rule and
source, check existing consent, finish preparation and independent permitted work,
then request only the remaining decision against a reviewable result. Distinguish
already authorized work, delegable decisions, prior policy adoption, user-only
material action, and constraints that consent cannot override. Consent never
creates credentials/roles, bypasses GitHub, or supersedes higher instructions.
Project policy changes are explicit reviewed changes, not hidden gate exceptions.
After consent, execute and verify within its binding without asking again.

`human-intervention` records AUTHORIZATION, AUTHENTICATION, CONFIGURATION or MATERIAL,
the rule/source, prepared result, exact action, observed HTTPS deep link (or entry
and minimal navigation), inputs and expected result. The host verifies links and
UI labels; the offline validator cannot establish their existence. Keep secrets
out of messages. Do not ask for work the agent can perform. After “done”, observe
the existing run/result through one bounded lookup; do not request already
observable IDs. Combine independent requests when their dependencies remain clear.

## Editorial delegation

Generation, automatic verification, delegated automatic approval, actual human
review and publication are distinct stages. `delegated-approval` emits only
`APPROVED_AUTOMATIC_DELEGATED`, with `human_review: false` and no publication
authority. It never updates a catalog or impersonates a reviewer.

Before requesting consent, complete the authorized source/translation batch and
obtain consumer-specific coverage, placeholder, markup, escaping, pluralization,
terminology and contextual checks. Generic Protocol code does not claim linguistic
competence or implement every consumer's string grammar. The trusted host selects
the complete checker evidence by digest independently of candidate input. Its
coverage enumerates every exact item, language and kind; its batch digest includes
all text and dependency hashes. Missing, invalid, unchecked or fallback content
cannot be approved. Summarize the batch and list ambiguities/linguistic limitations;
the delegant explicitly accepts those exceptions, never an invalid string.

A prior adopted consumer policy must permit delegation and identify authorized
delegants. Bind the actual grant to project, catalog, release, revision, complete
batch/item hashes, checks, accepted policy, delegant, executor, provenance,
conditions and validity interval. Host trust is independent: select live grants
and check revocation/roles at the decision boundary; do not trust a PR's digest
allowlist or restored authority. Unknown revocation/access blocks. A policy or
content change requires new binding, never automatic extension to future releases.

Per-item approval reuse compares source, destination, context and dependency
hashes; preserve valid unchanged approvals and invalidate only changed items and
their actual dependents. Consumer adapters must enumerate transitive semantic
dependencies before hashing. A recovered record cannot become prior consent.
Editorial and production grants remain separate; request them together only when
both prepared scopes are explicit. Existing consumer bans remain effective until
their separate policy and implementation adoption. No real catalog is approved
by this Protocol release; private release procedures are research inputs, not
authorization to mutate them.

## Release readiness, authorization and effects

`readiness` keeps CODE, DATA, CONFIGURATION, ARTIFACT, MIGRATIONS, WORKFLOW_INPUTS,
AUTHORIZATION, EXECUTION, VERIFICATION and CERTIFICATION separate. Before final
consent prepare the candidate, exact CI, effect/migration manifest, artifact,
workflow inputs and every independently observable prerequisite. CI success cannot
prove productive data readiness. Use only existing authorized diagnostics for
production-dependent facts, never introduce direct production access.

Collect independent blockers together where safe; stop dependent or risky checks.
Every diagnosis records phase, cause, affected elements, known effects, evidence
and next action without secrets. Unknown stays unknown. Do not propose a generic
rerun for missing configuration, data or approvals. A red monitoring workflow
does not prove no effects occurred. Store actual event time, observation time and
registration time separately; restored observations retain their original times.

`authorization-reuse` binds code SHA, artifact, effect manifest, exact workflow
inputs, audience and shared impacts independently. Operational conditions have an
explicit set of authorized digests: the host must validate their semantics, not
infer equivalence from an unchanged SHA. A failed run does not revoke all consent;
a changed candidate/effect/audience/input does not inherit an exact grant. Explain
the changed binding and provide the exact confirmation text when needed. Partial
retry additionally needs explicit coverage and the established recovery procedure.
This validator establishes coverage only, never readiness or platform permission.

`recovery-plan` distinguishes BEFORE_EFFECTS, PARTIAL, MONITORING_FAILED after
successful effects, and UNKNOWN. Reconcile uncertain outcomes before mutations;
completed migrations/publications are never repeated by default. Preserve their
idempotency receipts and qualify only remaining effects through existing recovery.
Mandatory bookkeeping failure stops dependent mutations. Monitoring failure after
completion calls for verification, not repetition. Use the existing emergency
procedure; code rollback is not assumed to reverse database or publication state.

## Environments, audience and complete delivery

Inventory UI capabilities early and record pre-deploy versus post-deploy checks.
With configured staging, require its successful verification before promotion;
failure cannot silently turn into “no staging”. With staging absent, proceed
through normal productive gates without a recurring waiver. USER_PC targets need
a prepared build and exact instructions before a necessary material user test.
STAFF is an audience, not a non-production environment: enforce server access,
record shared impacts, verify, then separately qualify wider opening. Hidden links
do not restrict access. Preserve valid visual deferrals within their exact runtime
scope and duration; DEFERRED is never PASS and new visual changes need reassessment.

An authorized delivery includes post-deploy verification, required certification,
checkpoint reconciliation, roadmap state, closure of satisfied in-scope issues,
and final handoff. A merged PR alone cannot close a release or broad tracker.
`closure-plan` binds the original scope and acceptance evidence, emits the first
pending step and stable idempotency keys, and checks observed completions against
retained keys. Execution uses the existing ledger and APIs: persist successful
receipts before dependent writes; reconcile uncertain writes before repeating.
Do not duplicate comments, issue closures, receipts or checkpoint PRs. Unmet
criteria retain explicit ownership. No next release is started by closure.

## Trusted evidence inputs

The public CLI commands use `--input` and a separate explicit `--trusted` file.
The host derives trust from actual user instructions, accepted policy and fresh
authorized observations, never from input/candidate content or self-signed JSON.
Digests provide binding only. `review-inventory` can prove thread coverage by
matching every normalized thread-comment database ID against complete REST comment
pages and the actual PR review-comment count, plus complete review pages. Retain
the original responses, reconcile drift, and use 100-item pages with an observed
short terminal page. A normalized empty list or missing page metadata alone proves
nothing. Review findings and requirements still use the existing review validator.

## Deterministic reading

`AGENTS.md` is the entry and contains only Core boundaries plus routing. The
manifest `.github/agent-protocol/documents-v1.4.7.json` records each document's
role, content digest, dependencies and workstream/phase/host conditions. Verify
its provenance against the actual accepted base before selecting it. The caller
supplies its independently computed canonical JSON digest to `select-documents`;
that digest authenticates neither its origin nor the actor by itself.

The selector verifies the whole local inventory, missing references, cycles,
duplicate IDs, conditions, UTF-8 and file integrity before presenting selected
text. It never traverses symlinks. ALWAYS rules load for every context. EXACT
selection loads the matching procedures and transitive dependencies; uncertain
context loads the full inventory. Invalid integrity or topology stops explicitly.
Verification reads bytes locally; only selected text enters model context. Report
those as different measurements. Workstream-specific product documentation still
comes from the owning repository and relevant source area.

After integrity verification, `context-delta` can suppress selected text already
retained in the same host context. Context loss, uncertain selection or changed
manifest restores full selected text. The accepted selection and retained receipt
are independent host inputs, never candidate authority. See the
[execution and handoff procedure](agent-development-v1.4.6-work.md#checkpoint-driven-execution).

### Scope-first / lazy repository acquisition

Repository acquisition MUST be scope-first and lazy. An agent MUST NOT materialize,
download, enumerate in depth, or read the complete repository unless a concrete
task or mandatory gate strictly requires it.

Default acquisition order:

1. repository identity and default branch metadata;
2. exact current head / expected head;
3. applicable `AGENTS.md` and directly relevant governance files;
4. owner/roadmap issue and relevant checkpoint/PR state;
5. diff from the last known-valid or relevant baseline;
6. paths/files directly implicated by the requested scope;
7. additional files only when required by implementation, dependency tracing, test
   failure or a concrete release gate.

Binary assets, generated artifacts, vendor content, media, archives and other
non-source blobs MUST NOT be downloaded or read by default. When only repository
integrity or identity is required, prefer Git tree metadata, blob/tree SHA,
path/mode/type metadata and exact-head comparison instead of blob contents. Binary
contents MAY be acquired only when directly in scope, required for inspection or
modification, needed to resolve a failing gate that metadata cannot resolve, or
explicitly required for content-level release qualification.

Previously acquired or validated repository state MUST be reused while still valid.
Do not repeat repository-wide reads, unchanged file reads, binary downloads,
duplicate GitHub queries, duplicate test runs or duplicate CI qualification unless
state changed, a concrete inconsistency invalidates the prior evidence, or the
applicable contract requires a fresh/non-reusable decision-boundary check. Mandatory
freshness checks and local checks explicitly classified as non-reusable still run.

If scope-first acquisition is insufficient, expand it incrementally and record the
concrete dependency or gate requiring the expansion. Full repository acquisition is
an exception, not a preflight default. Retrieved content MUST be minimized to what
is necessary for the current decision or implementation step: do not place large
unchanged repository contents, complete trees, binary representations or unrelated
files into model context when hashes, metadata, targeted reads or diffs are enough.

This rule strengthens, but does not weaken, exact-head qualification, release
identity, evidence integrity, recovery, checkpoint discipline, complete delivery or
required HUMAN GATEs. Older wording that appears to require complete repository
materialization merely to establish verifiability means verifiable repository
identity plus sufficient task-local source evidence, not unconditional retrieval of
every blob.

For adoption, this is a clarification of Protocol 1.4.7, not a new version or a
consumer rollout. Repositories already declaring 1.4.7 apply it on their next normal
agent execution unless a verbatim local Protocol copy genuinely requires later
synchronization. Do not create application releases, version bumps, changelog
entries or deployments solely to propagate this clarification.

Old overlay documents are historical unless selected as a current component:
the 1.4.2 operations guide owns operational schemas; the Work source guide owns
source materialization/runtime execution; the recovery guide owns archive format
and verification. Their older rollout inventories and ruleset acquisition text
are historical and superseded only for new 1.4.7 operations. Do not relabel an
archived observation as a current v2 preflight. Roadmaps describe product plans;
changelogs describe delivered changes. Neither is a second Protocol manual.

## Work sources, evidence and resume

Use the [canonical Work source recipe](agent-development-v1.4.3-work.md), pinned
to the accepted Core. `collectPreflight` now emits `agent-work-preflight/v2` with
`policy_source` and `remote_enforcement`, without a rulesets field or API call.
Consumers must explicitly adopt this shape; a legacy parser must not silently
accept it. Existing v1 evidence stays replayable under its matching validator.
Source acquisition preserves every blob/tree/mode and checks the default again.
Full local checks still run through the accepted source-bound supervisor.

Persist complete original observations outside source before continuing. Present
`evidence_summary` output normally: identity, state, original timestamp, freshness,
completeness, findings, uncertainty and an integrity-bound evidence reference.
Finding and uncertainty entries use scalar text or evidence references.
Nested responses/logs are rejected. The transport view is bounded at 8 KiB;
excess detail must reference the complete original instead of being truncated.
This is not a human-response word limit or a qualification gate. Full original
observations remain recoverable and may be loaded for the actual decision.
It always reports qualification NOT_EVALUATED. Load full payloads for diagnosis
or decisions requiring them; do not repeatedly print repository/user metadata,
encoded blobs, complete acquisition histories or whole job logs. Do not confuse
the evidence collector's narrow cache metrics with all host/tool calls.

The [1.4.6 reuse contract](agent-development-v1.4.6-work.md) continues to own cache
identity, immutable object reuse and complete terminal CI histories. Refresh the
exact-head inventory first; preserve failures, cancellations, every attempt and
all job pages. Each reuse retains the original observation timestamp and writes
a separate reuse record. Do not reuse policy, reviews, current PR identity or
local checks. New attempts, changed conclusions or live jobs invalidate affected
terminal cache entries. Reuse valid runtimes and rehashed dependency bytes.

On interruption, retain the ordered receipts, raw evidence, source identities,
blob/cache digests, actual authority input and one next action. Follow the existing
[recovery archive contract](agent-development-v1.4.5-work.md) for durable saving and
independent restore verification. A temporary archive alone is not a completed
handoff. Restore does not execute scripts or renew observations. Recollect fresh
anchors and native preflight before resuming. If cold acquisition outlives the
freshness window, retain it and use the verified cache with a new bounded read;
never edit timestamps to rescue the old attempt.

## Checkpoints and late findings

Keep one writable source of operational state: the existing campaign/receipt
ledger or repository checkpoint contract. `reconcile_checkpoint` derives a view
without mutating that source. A verified actual merge overrides a cached Draft
view; it does not erase the stale cache, authorize its manual replacement, or
pretend post-merge CI/deploy was certified. The result remains
QUALIFICATION_REQUIRED, or FOLLOW_UP_REQUIRED when a finding is open.

After merge, collect actual PR state, merge tree/parents/default ancestry, the
applicable exact-default CI and reviews arriving since qualification. A required
deploy has its own terminal successful event and distinct verification event;
never create a fake PRODUCT change to demonstrate deployment. For a valid late
finding, retain origin PR/head/merge/thread and assign an explicit follow-up
owner. A correction is a separate correctly classified PR appended to history.
Closure requires the existing operational origin/correction/thread proof,
qualified corrective integration, current ancestry and resolved finding evidence.
A resolved label, closed issue or later green run alone is insufficient.

BrickMS CHECKPOINT_ONLY Work maintenance already has a FULL supervisor path:
use that accepted route and its baseline lifecycle validator. Protocol adoption
ownership stays in its issue/PR ledger and cannot seize a PRODUCT checkpoint.
Do not keep a separately editable JSON and Markdown checkpoint. A human handoff
is generated from its bound state and gives repository/PR/head, state, blocker,
evidence and one next action. The new compact view does not modify old schema-2
handoffs or receipts and imposes no arbitrary word limit on new prose.

## CI and artifact storage

Inventory permanent triggers, suite dependencies, cache keys, artifact consumers
and timings before changing them. `ci_plan` accepts only complete exact dependency
inventories; unknown paths or scope select the full required suite set. It never
qualifies a skipped check or promotes artifacts. Every required check needs an
explicit terminal result. Merge tests remain required: even an equivalence input
does not alone establish source/configuration/environment equivalence or reuse.

The first demonstrated workflow change is KEEP_AND_HARDEN for `ci.yml`: cancel
superseded `pull_request` code runs in an event/PR-specific group. Keep the same
check names, full suites, permissions, trusted-base jobs and default-branch runs.
Never cancel deployment/publication work or reuse a PR artifact in a secret-bearing
context. Only a current successful run can qualify the head; retain canceled
history. Other suite-selection changes require measured dependency evidence first.
The Windows Node subprocess uses the same bounded 120-second limit as downstream
Work conformance; its assertions and required execution remain unchanged. This
addresses an observed 30-second subprocess timeout, not a correctness exemption.

Artifact retention is purpose-specific. Inventory current bytes and expiration,
then distinguish transient reports, failed-attempt diagnostics and release/recovery
evidence. `storage_summary` never infers account billing from a bounded run sample
and never authorizes deletion. Shorter retention affects future uploads; deletion
does not erase accrued storage usage. Compression can retain exact original bytes;
report compaction needs schema/version compatibility and reconstructible evidence.
Preserve required release/recovery artifacts before any authorized cleanup. Do not
delete whole workflow histories merely to remove redundant report archives.

Core Windows CI uses two isolated Windows runners, each executing two of the four
existing pytest shard indices. Every runner first records a separate full Windows
collection. The existing shard selector, full test inventory, assertions, Python
runtime and 540-second execution bound remain unchanged. No partial runner result
is a Windows suite approval. The canonical `tools/agent_protocol_work_check.py`
supervisor retains independent state, raw logs and actual phase outcomes outside
source; this CI route is separate from its existing Work repository supervisor.

The required `Core tests (windows-latest)` gate verifies both successful runner
jobs and their exact commit/tree, run/attempt, event, Windows OS and runtime. It
requires four distinct shards whose actually completed nodes form a disjoint,
complete union of the independent Windows inventories. Missing artifacts,
unknown exits, unsuccessful phases, changed source or an exceeded bound fail the
gate. Pytest case identity binds the parent node, original test name and every
parameter index sorted by parameter name to the verified source. Version 2 case
records retain the complete raw node labels and their bijection with those
structural identities; duplicate, missing or unknown mappings fail. This identifies
each parametrized case even when a generated ZIP timestamp changes its display
label between processes; it does not assert equality of generated parameter bytes.
The aggregate verifier uses only the Python standard library on Linux;
Windows execution evidence must still come from the Windows runner jobs. Artifacts
are confined to the same run and attempt and retain their complete reports/logs.
The full Linux suite and the trusted-base `pull_request_target` guard are unchanged.

## Measurement and communication

Use the same fixed scenarios before/after: startup, unchanged resume, candidate
change, qualification, post-merge, checkpoint close and unavailable ruleset API.
Record documents/model bytes separately from locally verified bytes; GitHub calls
and pages, downloaded/reused blobs, executed suites/duration, duplicated jobs and
manual interventions. Label actual runs, historical replay and synthetic tests.
No conversion to tokens, credits or money. Keep this evidence in the campaign's
existing artifacts, not a separate analytics system or new narrative report.

Final responses give outcome, essential checks, material limits/blocker and next
action derived from the existing checkpoint and verified roadmap. Every closure
also recommends an exact supported model and reasoning level, low/medium/high
workload with rationale and uncertainty, and one complete copyable prompt preceded
by the settings to select. Recommendations do not change models or grant authority.
Use `checkpoint-handoff` and the linked procedure; keep model availability and
session measurements in the checkpoint, not in permanent instructions.
Issue/PR/checkpoint prose references existing evidence instead of repeating
the prompt, rules or history. Updates communicate meaningful findings and decisions
at the host's required cadence. Concision never hides failed checks, unknowns,
required fields, authority boundaries or unresolved findings.
