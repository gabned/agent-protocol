# Protocol 1.4.3: verifiable Work sources and host authority

## Current operational entrypoint — 1.4.8

The historical 1.4.3 contract below is preserved. Version 1.4.4 fixes its host
integration: Work's generic `github_fetch` and `github_fetch_blob` can return
decoded text for a blob URL, not GitHub's raw base64 JSON envelope. Passing that
text to the old collector produces `lossless blob unavailable`. Successful
vendor distribution does not establish cold-session source acquisition.

Use this complete bootstrap in Work's JavaScript host. Set the two absolute
paths to the already verified accepted dependency and a **new** evidence directory;
set the actual repository. The provided host exposes `tools.exec_command`,
`tools.apply_patch` and the advertised GitHub tools. Work's isolate has no native
filesystem/module loader, so this recipe verifies the acquired collector bytes
before loading its exports. It does not replace the collector's transport logic.
The pinned digest below identifies the current collector, including incremental
observation persistence and verified evidence reuse. See [durable recovery](agent-development-v1.4.5-work.md)
for exporting and restoring evidence across workspace loss, and the
[1.4.6 evidence guide](agent-development-v1.4.6-work.md) for operational CI collection.

```javascript
const canonicalRoot = "/absolute/canonical-core";
const evidenceRoot = "/absolute/evidence/new-work-startup";
const repository = "gabned/provelume";
const shellQuote = value => "'" + value.replace(/'/g, "'\\''") + "'";
const bootstrap = [
  "import hashlib,pathlib,sys",
  "data=pathlib.Path(sys.argv[1]).read_bytes()",
  "if hashlib.sha256(data).hexdigest()!='ada703e75c7e80f2cb32d8c1302d04da83cab2a6c191cded1900662b4deb9f1a': raise ValueError('collector digest mismatch')",
  "pathlib.Path(sys.argv[2]).mkdir(parents=True,exist_ok=False)",
  "sys.stdout.write(data.decode('utf-8'))",
].join("\n");
const loaded = await tools.exec_command({
  cmd: "python3 -B -c " + shellQuote(bootstrap) + " " +
    shellQuote(canonicalRoot + "/tools/agent_protocol_work_collect.mjs") + " " + shellQuote(evidenceRoot),
  max_output_tokens: 12000,
});
if (loaded.exit_code !== 0) throw Error("verified collector bootstrap failed");
const {createWorkConnector, collectWorkSession, createEvidenceCollector} = new Function(
  loaded.output.replace(/^export /gm, "") + "\nreturn {createWorkConnector, collectWorkSession, createEvidenceCollector};",
)();
const saveRecord = async (relative, value) => {
  const result = await tools.apply_patch("*** Begin Patch\n*** Add File: " + evidenceRoot + "/" + relative +
    "\n+" + JSON.stringify(value) + "\n*** End Patch");
  if (result?.isError) throw Error("evidence persistence failed");
};
let observationNumber = 0;
const connector = createWorkConnector({
  fetch: args => tools.mcp__codex_apps__github_fetch(args),
  fetchFile: args => tools.mcp__codex_apps__github_fetch_file(args),
});
const persistObservation = record => saveRecord("observations/" +
  String(observationNumber++).padStart(6, "0") + ".json", record);
const evidence = await createEvidenceCollector({repository, ...connector, persistObservation});
const session = await collectWorkSession({
  repository, ...connector, readTree: evidence.readTree,
  saveBlob: (sha, record) => saveRecord("records/" + sha + ".json", record),
  persistObservation,
  activePr: null, // select the actual PRODUCT owner when one exists
});
for (const [name, value] of Object.entries(session)) await saveRecord(name + ".json", value);
```

This cold-start example defines every variable except the actual provided host
`tools`. It refuses an existing evidence directory and verifies the exact module
bytes before evaluating them; no tokens, native Git emulation or HTTP fallback.
On a host with native ES modules, an explicit import of the same verified file
may load the three exports instead; do not assume they already exist in a new cell.

`saveBlob` above retains each normalized base64 JSON record outside source.
Before materialization, use the canonical `decode_blob(response)` verifier and
store its verified raw bytes as `<blob-directory>/<sha>`. For a resume, supply
`hasBlob(sha)` only after independently rehashing cached raw Git blobs; reuse the
blob directory while giving each attempt a new evidence directory. Omitting
`hasBlob` gives a cold acquisition. Never infer original bytes from decoded text,
partial archives or memory. Local preflight and full checks below remain required.

The adapter unwraps supported tool envelopes and uses typed file reads with an
exact repository/path/commit and explicit base64 encoding. Each raw tool result
and its actual arguments remain in acquisition observations. The derived blob
record takes size from the independent tree; it is not labelled a raw GitHub
response. SHA identity, encoding, base64 shape and byte count are checked before
saving. Empty content is valid only for a zero-byte tree entry. Missing or
truncated binary content is a capability gap, never repaired or silently skipped.
All blobs, including cache hits, still undergo canonical offline blob/subtree/
root/mode verification. The generic raw-JSON collector interface remains valid
for hosts that actually expose that response shape; no automatic retry occurs.

Persist `session.snapshot`, `session.anchor` and `session.observations` outside
source. Materialize and verify with the unchanged `agent_protocol_work_source.py`,
then run the repository's accepted local preflight and full-check entrypoints.
For BrickMS, retain the materialized tree as an immutable baseline and copy it
to a separate candidate directory before invoking the candidate's
`scripts/agent/protocol-v1-2.py work-preflight`. Pass the baseline path through
`--baseline`; executing that script from the baseline itself fails the existing
separation check. The full PROTOCOL wrapper validates a real proposed Protocol
delta, including the required technical changelog entry; an empty delta is not
a qualified adoption. Do not add a dummy change merely to test the baseline.
`session.local_preflight` is always `NOT_RUN`: collection is not execution.
The wrapper also rejects a moved default between acquisition and observations.
Policy/review/CI UNKNOWN remains UNKNOWN and cannot authorize publication.
Active-PR supplementary identity/ancestry proof required by the local preflight
must still be collected. This wrapper does not create owners or update checkpoints.

For an interrupted acquisition, keep the saved blobs, begin a fresh session call,
rehash cache entries and recollect source/default/policy observations. No old
15-minute authority window or local check receipt is renewed by resuming.
This avoids repeated downloads without adding another campaign or state store.
Operational receipts retain the 1.4.2 engine and discriminator. Use its existing
`render-pr-identity` and repository review-body validator before publication;
do not hand-author SHA declarations or treat example review fields as approvals.

Acceptance requires synthetic transport/error/tampering regressions and an
actual cold-source acquisition followed by native preflight and full checks in
each adopted profile. Until local acceptance, PRODUCT keeps its previous stop.
Historical missing execution logs remain EVIDENCE_GAP. No product release,
deployment, broader profile, weaker test gate or retroactive receipt is implied.

This common overlay defines an authorized Work host plus a completely verified
source tree as an alternative representation of the preliminary source
obligations below. Repository-local adoption must name the exact canonical
commands and preserve every stronger local gate before PRODUCT uses that path.
An unmerged candidate, source receipt or Protocol-only test does not establish
adoption, close EVIDENCE_GAP or authorize a GitHub mutation.

Lifecycle remains 1.2 and campaign/handoff schema remains 2. The operational
engine and its receipt discriminator remain 1.4.2; its new explicitly selected
host-instruction input is described below. Existing 1.4.2 receipts and the
1.4.0/1.4.1 validators are preserved. Source and authority representations do
not create another lifecycle, ownership model or global checkpoint.

## Problem and historical boundary

An authorized connector can read complete GitHub objects while its host's
temporary execution workspace has no authenticated Git checkout. Requiring a
local Git index for source identity and executable modes unnecessarily couples
those proofs to one transport. Publication success alone does not prove that
the required preliminary checks ran. Missing historical logs remain a separate
EVIDENCE_GAP; the proposal does not rewrite that history.

## Source equivalence

| Obligation | Work representation | Failure behavior |
| --- | --- | --- |
| Current base identity | Fresh connector repository/default-ref/commit observations before and after acquisition | Moved, stale or unavailable base blocks |
| Complete source | Full tree and all referenced blob bytes, recomputed blob/subtree/root IDs | Missing entries, truncation or hash mismatch blocks |
| Executable modes | Observed Git tree mode plus POSIX owner-execute bit and exact working bytes | Mode/content drift blocks; no fake index |
| Pending delta | Complete independent baseline/candidate inventories and candidate tree ID | No fabricated commit SHA; additions/deletions/mode changes retained |
| Workstream separation | Explicit class evaluated by the verified baseline guard | Candidate scope policy cannot authorize itself |
| Local checks | Existing canonical command and actual exit code, bound to candidate tree | Failed, missing or stale-by-source receipts cannot be reused |
| GitHub authorization/policy | Actual authorized-host connector observations | A JSON label or integrity digest is never authentication |
| CI/review/merge | Existing exact-head operational validators and required repository gates | No replacement by local tests or old green runs |

The source-only checker returns `push_qualified: false` even on successful
integrity verification. It does not contain a publication command. The host
must establish actual connector provenance; the offline verifier cannot sign
or authenticate GitHub responses. Observations expire for new actions after
15 minutes, allowing at most 30 seconds of clock skew. Archived evidence may
still document an earlier result, but cannot establish current readiness.

## Collector and complete source format

`tools/agent_protocol_work_collect.mjs` receives an authorized `fetchJson` GET
function and a local blob sink from its Work host. It does not discover tokens,
invoke HTTP independently, install tools or retry authorization failures.
It reads the observed default branch, exact commit and root tree. A truncated
recursive tree is expanded through nonrecursive subtree requests. Requests,
entries and bytes are bounded. Source blobs use lossless base64 transport.
Existing verified content-addressed data can be reused, followed by complete
offline hashing; cache existence alone is never proof.

`collectPreflight` v2 records complete bounded open-PR pages, details only for the
selected owner and bounded recent Actions. It does not acquire rulesets. Trusted
versioned repository policy supplies agent gates; missing thread completeness
remains UNKNOWN. Historical v1 observations retain their original ruleset field. Recent Actions are an inventory,
not final-head CI certification. Protected environments are not accessed.
The independent existing operational collector/validator must still obtain
all critical PR, policy, ancestry, CI attempt/job and review evidence.

The `agent-work-source/v1` document contains repository, exact commit/tree IDs
and the complete Git tree response. The source directory contains only source;
evidence, runtime, caches and generated state must live outside it. File bytes
and directory names are verified without Git. Valid UTF-8 whitespace and
newline names are preserved; traversal, NUL and noncanonical paths are rejected.
The initial materializer supports regular files/directories on POSIX. Symlinks,
submodules, nested empty trees, unresolved LFS pointers and platforms unable to prove modes fail
with an explicit capability gap. They are never silently omitted or expanded.
Materialization creates a new private directory and preserves existing work.

## Runtime contract

Work execution and GitHub observation are separate capabilities. Use managed
runtime paths first. A workspace-local runtime may be prepared only with
existing permission and approved official sources/checksums; preserve older
runtimes and do not modify global configuration. A temporary runtime's presence
is not a persistence guarantee. Runtime inventory/platform satisfaction and
application tests are separate results. The collector requires the host's
JavaScript capability; Node is used only by its offline conformance tests.
The full Core pytest suite invokes the collector's Node conformance suite, so
the Node runtime supplied by Work or the standard CI runner must be available.
No workflow is replaced and no missing runtime is turned into a skipped gate.

BrickMS has already demonstrated PHP 8.5.10 with its twelve declared extensions
and Composer 2.10.3 in a temporary Work workspace. Those observations do not
establish availability in a later session, qualify full checks or certify a
different repository's runtime. Source preparation must stop with a concrete
missing-capability error when the required runtime cannot be prepared.

## Adoption and trust boundary

This COMMON_CONTRACT overlay requires repository-local integration. Once
adopted, an authenticated checkout and an authorized connector with verified
source are distinct supported representations of the same source obligations.
Neither representation waives local checks, actual authorization, checkpoint,
effect binding, current-head CI, review, ownership, ancestry or reconciliation.

The exact safe-path registrations describe only the listed
read-only Protocol files. No blanket prefix, workflow name, permission, branch
protection or production rule is relaxed. New effect paths are registered
only through a preceding accepted change. Therefore:

1. Review/register the exact new common paths through a separate PROTOCOL delta
   on already recognized contract surfaces, under current trusted-base gates.
2. Qualify and integrate the common implementation against that accepted base.
3. Adopt the canonical accepted bytes and explicit local runbook integration;
   generate real vendor provenance only after the canonical commit exists.
4. Complete required local/full checks, exact-head CI/review and reconciliation
   for each adopting repository. Current source-only tests cannot replace them.

No canonical commit, manifest, owner issue/PR, campaign or closure receipt may
be fabricated. Cross-repository distribution can be declared
complete only under the existing complete five-repository audit. This overlay
does not expand the authorized rollout beyond the repositories actually named
and approved by the maintainer.

A local adoption may use a workspace dependency pinned to accepted Core bytes
instead of adding newly classified paths. The local guard must verify the
pin before importing external code; `--adapter-root` selects that external
directory explicitly and never grants it trust. Existing local Protocol paths
can host the integration and its conformance tests. A separately authorized
PROTOCOL candidate may exercise its proposed canonical route for pre-publication
validation after common acceptance, provided the unchanged trusted-base scope
and effect guards accept its entire delta and every full check actually runs.
This is candidate validation, not PRODUCT adoption or permission to skip an
existing obligation. PRODUCT uses the route only after qualified local merge.

## Cross-repository impact

| Profile | Effect of this common change | Required local adoption |
| --- | --- | --- |
| Core | Public source can use a real unauthenticated read-only clone; writes use the authorized connector | Existing full Python/Git checks remain unchanged |
| BrickMS | POSIX snapshots can preserve complete source and executable modes | Explicit Work preflight/full-check route, accepted vendor provenance and all PHP/database gates |
| Maxithlon | No local execution route is adopted here | Separate PROTOCOL integration; level C remains human-only |
| provelume.com | No site delivery or deployment route changes | Separate local integration and existing upstream/deployment gates |
| Descriptive registry | No executable source or approval authority is introduced | Existing registry distribution audit only |

No change here claims five-repository distribution or grants an unimplemented
repository profile. The initial Work process supervisor rejects repositories
other than BrickMS and rejects non-POSIX execution before creating output.
Portable object-validation tests run on Windows; POSIX process/materialization
tests run only on their supported host. Unsupported hosts fail explicitly.

## Explicit Work instruction provenance

Some Work hosts expose neither the authoritative task UUID nor its creation
timestamp. A terminal thread ID is not assumed to be that task. The existing
`GITHUB_COMMENT` and `USER_INSTRUCTION` references keep their original strict
semantics; no `codex-goal:` identifier may be invented or derived from a path.

`WORK_USER_INSTRUCTION` is an additional explicit representation. The trusted
caller must first observe the actual user instruction and its authorized
request outside the repository, verify the human maintainer through the
connector, and verify that the instruction covers the exact proposed delta.
It retains an `agent-work-instruction/v1` record with the verbatim instruction
and request, actor, repository, PR, exact base/head, complete-path digest and
technical-patch digest. Its scope is fixed to PROTOCOL, THROUGH_MERGE and
NO_PRODUCTION. It contains no inferred task ID or creation time.

Instruction/request strings may contain line breaks and surrounding whitespace;
their original bytes are preserved within the bounded nonempty-string contract.
Actor identifiers and the existing non-Work instruction formats retain their
original single-line validation.

The reference `work-instruction:sha256:<digest>` addresses those exact canonical
bytes. A digest proves integrity, never user identity or approval. The record
must be supplied independently by that authorized host, under ignored external
evidence, not discovered in a PR body, candidate file, proposed receipt or a
self-described approval flag. The default trusted instruction set is empty.

Use `with trusted_work_instructions(records):` around the existing 1.4.2
operational/campaign APIs, or `--work-instructions trusted-input.json` before
the CLI command. The file has the exact shape `{"instructions": [record]}`.
The caller must never build this trusted input solely from the evidence being
validated. A copied record is scoped to that call and resets afterward. It is
not serialized as a new grant inside a receipt; archived receipts require their
independently retained original authority input for replay.

Every existing technical changelog restriction still applies: the actual
observed patch must match; exactly one technical line may be appended; no
deletion, extra product path, weaker effect policy, current-head mismatch,
unknown review, CI failure, stale observation or gate waiver is permitted.
Changed heads need a new exact-delta binding to an instruction that already
covers the work; they do not require duplicate user consent. Source/authority
data cannot authorize itself, and no agent-authored GitHub comment is presented
as a human instruction.

## Acceptance tests and remaining proof

The Python and JavaScript conformance suites use synthetic/public fixtures.
They test integrity, tree completeness, lossless blobs, restrictive modes,
source drift, incomplete pagination, moved/default observations, and fail-closed
capability gaps. The BrickMS integration reuses its canonical vendor/hash,
checkpoint and change-control checks. It must retain old Git behavior when the
new mode is not selected, and no source receipt may claim remote authorization.

Required adoption proof still includes a fresh full canonical check using the
accepted adapter, trusted-base scope/effect checks, final-head CI and review,
and an independently observed publication/reconciliation of the accepted tree.
It cannot be manufactured in a local candidate without an actual authorized PR.

References: [GitHub trees](https://docs.github.com/en/rest/git/trees),
[GitHub blobs](https://docs.github.com/en/rest/git/blobs),
[Git object modes](https://git-scm.com/docs/git-fast-import).

## Source-bound local check supervisor

The supervisor accepts the existing `CHECKPOINT_ONLY` class for the adopted
BrickMS profile only, with `--suite FULL`. The delta must include
`AGENT_STATUS.md` and may additionally include `CHANGELOG.md`; the unchanged
repository-local baseline validators still enforce the lifecycle transition and
technical append-only changelog contract. Application, Protocol implementation,
workflow and vendor-adoption changes are rejected in this class. A local adapter
must explicitly adopt this support before use; a successful supervisor result
still cannot qualify publication or grant ownership, review or production rights.

`tools/agent_protocol_work_check.py` invokes the selected existing canonical
BrickMS check, preserves stdout/stderr and the actual process exit code in a
new external evidence directory, and verifies source identity again afterward.
It does not overwrite previous reports. Source drift, timeout or process-launch
failure cannot produce a successful adapter result. It inherits only the tool
PATH and a minimal environment, with an isolated Composer home. Runtime setup
remains a separate approved workspace operation; no dependency is installed.
`PROTOCOL_ONLY` and `FULL` are distinct explicit suites. FULL is not authorized
by the active diagnostic stop or by successful Protocol conformance. The
supervisor contains no GitHub write operation or CI substitution.

A Protocol vendor update may additionally select `--canonical-snapshot` and
`--canonical-anchor` together. They must prove the complete accepted Core tree
and a fresh exact-default observation before execution. PRODUCT cannot select
this adoption input. The local vendor guard must then bind the manifest's
canonical commit and every updated vendor byte/mode to that independent tree;
the existence of a candidate manifest is insufficient. Without these inputs,
the baseline vendor identity remains mandatory. This does not permit unmerged
canonical bytes or relax current-head scope, full checks or review.

For canonical vendor checks, the receipt additionally binds the canonical
repository, commit, tree and digests of both snapshot and live-anchor evidence.
The supervisor verifies those inputs again after execution. Receipt verification
requires the independently retained snapshot/anchor files and compares their
content identities, not just their command-line paths. Missing, replaced or
modified canonical input cannot validate a successful check. Archived freshness
is evaluated at the recorded actual check start; it never represents a new
live observation or replaces the host's current-main observation before action.
