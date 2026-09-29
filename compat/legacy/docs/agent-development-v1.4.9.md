# Agent Development Protocol 1.4.9

This is the authoritative delta for policy coherence, bounded policy compensation
and evidence dependencies. The [1.4.8 cross-cutting contract](agent-development-v1.4.8.md)
continues to govern authority, acquisition, communication, qualification and closure.
Lifecycle schema 1.2, campaign schema 2, operational schema 1.4.2 and Level C do not
change. Historical receipts retain their original version, validator and outcome.

## Policy before BOUND

Before a claim or binding can persist BOUND, its native adapter must invoke
`require_policy_coherence` in the pinned Core `tools/agent_protocol_v1_4_9.py`.
`resolve_policy` supplies the identical deterministic decision for diagnostics and
`explain-before-bind`. A successful explanation alone never creates a binding.
The stateless Core `tools/agent_protocol.py bind` invokes this guard before emitting
any BOUND receipt. Persistent consumer adapters must guard before writing their
checkpoint, using the same function rather than a second policy resolver.

The host selects the actual adopted contract from the verified pin, provenance,
current instruction routing and local workstream class. The exact contract object
has `schema: agent-policy-contract/v1`, `repository`, `source_commit`, `reference`
(the authoritative document/routing location), and `routing`. These are evidence
of an independently established route, not user-selectable policy overrides.
The initial supported routes are:

| Adopted route | Workstream class | Required policy |
| --- | --- | --- |
| PRODUCT/v2 | PRODUCT | REPOSITORY_POLICY |
| PRODUCT/v1 (original lifecycle policy semantics) | PRODUCT | NO_PRODUCTION or REPOSITORY_POLICY |
| PROTOCOL/v1 | PROTOCOL | NO_PRODUCTION |

PRODUCT/v1 names the original lifecycle's two-policy contract; it is not a
downgrade route for a consumer already adopting PRODUCT/v2. Select it only when
current verified routing retains that original contract. Explain returns both
admissible policies there, and recovery cannot manufacture a uniquely required
replacement. This preserves coherent existing lifecycles without silent fallback.

An unsupported route is `EXTERNAL_DEPENDENCY`: establish its authoritative Core
contract through the ordinary PROTOCOL lifecycle before enabling it. Do not guess
from a branch name, selected policy, previous conversation or desired gate result.

Three independent inputs remain distinct:

1. Workstream policy determines the checks required by the adopted routing.
2. Observed delta effects come from the existing native classifier over the complete
   actual base-to-head delta, including both sides of renames. They never come from
   the selected policy. Documentation can remain `NO_PRODUCTION` under
   `REPOSITORY_POLICY`; incomplete or `UNKNOWN` effects cannot bind.
3. Production capability comes only from independently established authority. The
   decision preserves the `production`, `deploy`, `migrate` capabilities supplied by
   the host and always grants zero new capabilities. A PRODUCT production delta
   still requires all existing product, release and authority gates. Binding is
   not permission to execute those effects. Level C consent remains separate.

The decision includes workstream, supplied/resolved class, route, contract digest,
expected/selected policy, observed effects, existing authority, incompatibilities
and the next action. For PRODUCT/v2 with NO_PRODUCTION, the guard reports the
received PRODUCT/NO_PRODUCTION and expected PRODUCT/REPOSITORY_POLICY, names the
adopted contract, and directs the operator to recompute effects under the correct
route. There is no fallback or automatic conversion of the selected policy.

```bash
python tools/agent_protocol_v1_4_9.py explain-before-bind \
  --input .agent/policy-input.json --trusted .agent/policy-trust.json
python tools/agent_protocol.py bind --report .agent/effects.json --pr '#123' \
  --workstream protocol-adoption --workstream-class PROTOCOL \
  --adopted-contract .agent/adopted-contract.json \
  --trusted-contract "$ADOPTED_CONTRACT_SHA256" \
  --production-authority .agent/production-authority.json \
  --output .agent/binding.json
```

`policy-input.json` contains `contract`, `workstream`, `workstream_class`,
`selected_policy`, `observed_effects`, `production_authority`; the independently
retained trust file contains `trusted_contract`. Canonical digests use Core
`digest()`. Digests bind bytes; they do not authenticate their origin or grant
authority. Never derive the trusted value from an unverified candidate payload.
Native adapters gather these inputs in their existing claim/bind operation; a
coherent consumer does not need a separate recovery or a second lifecycle.

Existing coherent bindings are not rewritten. Every ordinary fresh snapshot and
reconciliation observation, for both new and legacy stateless receipts, includes
`policy_context` with `contract`, `trusted_contract`, `workstream_class` and
`production_authority`; validation supplies workstream/policy/effects from the
original binding. The host selects this context independently of the candidate;
an embedded decision and a recomputable seal cannot supply current authority.
Missing context is stale evidence, not permission to rebind. A retained decision
is checked for internal consistency only after the independent current guard.

## Narrow recovery allow-list

The sole recoverable class is a selected policy inconsistent with the policy
deterministically derived from the adopted workstream route, with unchanged and
verifiable immutable identity and a completely reconstructed nonproduction delta.
Both historical and current observed effects must be NO_PRODUCTION. Other errors
are not made recoverable by this release. Recovery does not qualify the workstream.

`plan_policy_recovery` accepts only the typed request
`{operation: RECOVER_BOUND_POLICY, owner, expected_head}`. There is no patch map,
replacement owner, new branch, force policy, rebind or checkpoint editor. Extra
fields are rejected. `recover-rejected-handoff` retains its separate semantics.

The host must save original source observations before normalization and prove:

- Effective authenticated owner and authorization for the exact repository/PR;
  expected branch; clean tracked and untracked working tree; still-open PR; exact
  current head; expected base and master; valid native Git ancestry.
- Original binding, BOUND checkpoint and complete history from the checkpoint
  commit to current head, including intermediate commits and checkpoint contents
at every commit. No hidden alteration, incomplete clone, graft, replacement,
  omitted merge parent or unexplained head movement is acceptable.
- Current applicable contract, verified adopted pin, workstream class, complete
  actual delta and its native classifications; complete historical event and gate
  inventories, including failed qualifications and their original timestamps.

The strict normalized observations accepted by the Core are defined by
`plan_policy_recovery` and exercised by `tests/test_agent_protocol_v1_4_9.py`.
Boolean completeness/ancestry values must summarize retained raw proofs, never
replace them. `checkpoint_id` identifies the original checkpoint commit;
`checkpoint_basis` and `binding_basis` retain the original lifecycle identities.
The normalized checkpoint includes every immutable field and only state, policy
and observed effects as additional fields. Native metadata outside that projection
must be byte-for-byte preserved and checked by the adapter. A projection that hides
a changed native field is invalid. The independently retained observation digest
must cover the complete normalized inventory linked to its retained raw sources.
Live observations expire after 15 minutes; resample changed remote state before
mutation. A native adapter unable to prove this contract must refuse recovery as
`EXTERNAL_DEPENDENCY`, retain the checkpoint, and complete independent adoption.

History is a complete acyclic ancestry graph, including both branches of a merge,
with exact parent lists and no orphan rows. Traversal may stop only at the proven
binding/checkpoint basis or exact current base/master anchors; those upstream
objects retain their separately verified ancestry. Missing intermediate or merge
parents cannot be replaced with a completeness assertion or an unknown boundary.

Owner, repository, PR, branch, workstream, class, binding basis, checkpoint basis,
checkpoint identity, all previous commits/ancestry, authorizations and Level C
consent are immutable. Wrong identity, closed PR, dirty tree, unexpected head,
base/master drift, incomplete/tampered history, unknown effects, authority
escalation or any attempt to grant production/deploy/migration/Level C is terminal
for this recovery. Preserve evidence and follow the ordinary abandonment/escalation
and lifecycle rules; do not try another payload to bypass a deterministic rejection.

## Compensative transaction

A recoverable BOUND error is corrected by new compensative evidence, never by
retroactive mutation. Keep the original checkpoint, error and failed qualifications
observable. The planner derives the correct policy itself, recomputes the full
delta effects, checks no escalation and returns the only allowed change:
`effect_policy`. It binds the complete history, events, gate inventory, source
contract, coordinates and observations into a retained plan. It does not edit files.

```bash
python tools/agent_protocol_v1_4_9.py plan-policy-recovery \
  --input .agent/recovery-input.json --trusted .agent/recovery-trust.json \
  > .agent/policy-compensation-plan.json
```

Input contains `request`, `evidence`, `contract`; independently retained trust
contains `trusted_evidence` and `trusted_contract`. A BLOCKED response/exit 2 is not
a plan. The native adapter must reread/recheck the exact owner, clean branch, open
PR, head and plan before applying only the derived policy correction. Retain its
operation evidence in the existing ledger. Create a new direct-child compensation
commit whose subject is the planner's exact `Protocol policy compensation <digest>`.
Never amend, reset, squash prior events, replace the checkpoint's original identity,
absorb other changes or manufacture PASS. The existing ordinary final integration
method remains subject to its own qualified history-preservation requirements.

After the actual commit, independently read its parents, subject and exact tree
delta, the before/after checkpoint, unchanged native metadata and retained history.
Recalculate effects over the entire new base-to-head delta, not just the policy
line. Feed those observations to:

```bash
python tools/agent_protocol_v1_4_9.py verify-policy-compensation \
  --input .agent/compensation-observations.json \
  --trusted .agent/compensation-trust.json
```

Input keys are `plan`, `compensation`, `previous_evidence`, `current_dimensions`;
trust keys are `trusted_plan`, `trusted_compensation`. The verifier requires the
exact planned direct child, unchanged immutable state, only the policy correction,
complete preserved history/events/gates and no effects/authority escalation. It
returns `POLICY_COMPENSATED`, a new head and `qualification: REQUIRED`, never PASS.
If the branch already moved, the proof expired or another change exists, refuse
the transaction and reconcile; do not roll back or rewrite existing history.

A null final repository diff does not erase a nonempty commit/checkpoint history.
Reconstruct that history and retain the failed event; the compensation commit is
still mandatory. Where checkpoint state is PR-local and no tracked tree change is
necessary, a recognizable empty direct-child commit plus the retained new ledger
event is required. The adapter must prove the effective before/after policy; an
empty diff is not evidence that recovery already occurred.

## Freshness and selective reuse

`evidence_freshness` classifies retained gate results against explicit dependency
coordinates. It never replaces their timestamps/results or converts FAIL to PASS.
Coordinates are HEAD, BASE, MASTER, PR_STATE, REVIEWS_THREADS, POLICY, PIN,
ENVIRONMENT, AUTHORITY and REPOSITORY. Missing/unknown coordinates cannot establish
reuse. PIN is the adopted source commit; AUTHORITY binds existing capabilities and
Level C consent; PR_STATE is the currently observed state. Other coordinates bind
the actual relevant observation/configuration, not a convenient label.

| Gate | Minimum dependencies |
| --- | --- |
| QUALIFICATION | All coordinates |
| CI | HEAD, BASE, ENVIRONMENT, REPOSITORY |
| EFFECTS | HEAD, BASE, POLICY, REPOSITORY |
| REVIEWS | HEAD, PR_STATE, REVIEWS_THREADS, POLICY, REPOSITORY |
| ANCESTRY | HEAD, BASE, MASTER, REPOSITORY |
| SOURCE_INTEGRITY | PIN, REPOSITORY |
| AUTHORIZATION | AUTHORITY, REPOSITORY |
| REPOSITORY_IDENTITY | REPOSITORY |
| MASTER_INTEGRITY | MASTER, REPOSITORY |
| PR_STATE | PR_STATE, REPOSITORY |

Adapters add dependencies when their gate actually uses more inputs. They cannot
remove mandatory dependencies or classify an unknown gate as independent. A gate
row contains `id`, `gate`, `dependencies`, `coordinates`, `result`. Any changed
dependency automatically yields STALE_EVIDENCE; otherwise the original result is
REUSABLE, including a reusable FAIL. Only demonstrably independent evidence remains
valid. New qualifying HEAD always invalidates every previous head-bound gate.
MASTER movement does not invalidate an independent repository identity check;
review/thread movement invalidates review-dependent gates; pin/authority changes
invalidate their respective dependents. Reusing repository-bound observations does
not excuse refreshing live PR/review inventories required by the existing lifecycle.

The compensation verifier applies this classifier to the entire retained gate
inventory automatically. Other head/base/master/review/pin/environment/authority
changes use the same classifier before gate reuse:

```bash
python tools/agent_protocol_v1_4_9.py evidence-freshness \
  --input .agent/freshness-input.json --trusted .agent/empty-trust.json
```

Here input keys are `evidence` and `current`; the trust object is `{}` because the
host has already established their provenance. Rerun stale native effects, exact
head CI, qualification, reviews/threads and ancestry as their dependencies require.
The ordinary exact-head merge and actual-main post-merge checks remain mandatory.

## Diagnostics, release and adoption order

INPUT_MISMATCH identifies incompatible unbound input; BOUND_RECOVERABLE identifies
only an eligible compensation plan; BOUND_TERMINAL refuses identity/history/state
errors; STALE_EVIDENCE requires resampling or rerunning the affected gate;
AUTHORITY_BLOCKED refuses capability/effect escalation; EXTERNAL_DEPENDENCY names
missing adopted route, adapter support or upstream proof. These are diagnostics,
not new permissions or general mutable lifecycle states.

A Protocol, adapter, policy or pin change cannot retroactively turn the workstream
that exposed the defect into PASS. First implement and qualify the separate Core
PROTOCOL change using its accepted predecessor. Integrate Core and make its exact
commit available through the normal adoption mechanism. Then adopt that commit in
each independently authorized current consumer, qualify/integrate its minimal
adoption PR, and reconcile its main pin and CI. Only then resume an affected active
workstream through this typed recovery and qualify the new candidate. No consumer
exception, local-policy weakening, unrelated product change or production authority
follows from adoption. Report blocked consumers separately and continue independent
ones; a remaining blocked consumer makes the overall rollout PARTIAL.

The existing `agent_protocol_work_recovery.py sync-adopter` transaction now accepts
the 1.4.8-to-1.4.9 transition and adds the policy module to the operational vendor
inventory. The ten Work dependency files retain their separate pin. Generated
provenance and the operational manifest are derived from the same accepted Core
commit. Native consumer entry points must invoke the pinned resolver before BOUND;
where necessary that minimal adapter wiring belongs to the dedicated adoption PR.
Neither copying the module nor updating a version marker alone proves execution.
