# Protocol 1.4.5 — durable Work recovery and coherent adoption

This overlay keeps the 1.4.2 operational engine, lifecycle 1.2 and campaign/handoff
schema 2. Historical validators and receipts keep their original identities.
Recovery is integrity evidence, never authentication, authority or a passed gate.
The local effect profile adds only the three exact new recovery helper/test/guide
paths; unknown paths keep their previous fail-closed classification.

## Capture before continuing

Use the complete current bootstrap in [the Work source guide](agent-development-v1.4.3-work.md).
Its `persistObservation` callback saves each original connector response before
the next read, including an unavailable-response record when a connector throws.
Typed-file envelopes are saved before their contents are validated. If persistence
fails, collection stops; it cannot return a successful result with missing evidence.
The callback is optional for historical callers; the 1.4.5 entrypoint supplies it.

Each attempt owns a fresh external evidence directory. Do not overwrite a prior
attempt. `progress` is an optional host callback after blob saving; it is display
information, carries `push_qualified: false`, and cannot authorize continuation.
The host should throttle progress messages to a useful cadence. Original timestamps
never change when files are restored or reused.

## Export and restore

`tools/agent_protocol_work_recovery.py` supplies offline `export`, `verify` and
`restore` commands using only Python's standard library and the accepted canonical
siblings. Pass an explicit sorted JSON list of relative file names in `files.json`.
Select source observations, immutable blob/cache records, check outputs, actual
campaign receipts and handoff material needed for the current workstream. Keep
the archive and output paths outside the candidate source tree.

```bash
python3 -B /accepted/core/tools/agent_protocol_work_recovery.py export \
  --root /external/evidence --files /external/files.json \
  --output /external/recovery-001.zip
```

The result reports the archive SHA-256 and `durable_host_save: REQUIRED`. The host
must save the archive through its durable file capability and retain the digest
and returned file identity separately before declaring a durable handoff. A ZIP
left only in temporary workspace is not resilient to workspace loss. This command
does not upload, discover accounts, send messages or copy evidence into a repository.
Do not put private evidence in public source or public campaign issues.

After retrieving the saved file in a new session:

```bash
python3 -B /accepted/core/tools/agent_protocol_work_recovery.py verify \
  --archive /external/recovery-001.zip --sha256 <independently-retained-sha256>
python3 -B /accepted/core/tools/agent_protocol_work_recovery.py restore \
  --archive /external/recovery-001.zip --sha256 <independently-retained-sha256> \
  --destination /external/new-restored-evidence
```

Export never overwrites an archive; restore requires a new directory. Verification
checks member inventory, file sizes/digests and modes before extraction. Traversal,
links, duplicate names, case aliases, encryption, unsupported modes and expansion
past the bounded limits fail closed. A failed restore removes only its own new
destination. No restored script is executed. Records are not interpreted as fresh
GitHub state, and no receipt is rewritten or upgraded.

Human instruction records must originate from actual user messages and stay
separate from PR-controlled observations. An archived instruction's hash proves
only byte integrity. The caller must independently establish its source and exact
scope before selecting it through the unchanged `--work-instructions` interface.
Never discover authorization by scanning candidate files or treat an archive as a
new approval. If the original source cannot be recovered, report that evidence gap.

Then independently rehash cached Git blobs, collect fresh default/policy/PR/CI
observations and run the adopted native preflight and full checks. Prior failed
attempts remain history. An advanced default invalidates the previous binding;
stale green runs cannot qualify a new head. Do not automatically retry a workflow
or production operation while recovering. Wait only on a live observed handle
with its existing bounded deadline.

## One adopter synchronization

After Core has been accepted on its real default branch, use its clean native
checkout and the existing adopter checkout:

```bash
python3 -B /accepted/core/tools/agent_protocol_work_recovery.py sync-adopter \
  --source /accepted/core --commit <accepted-core-commit> \
  --target /adopter --repository <owner/repository> --check
```

`--check` returns the complete planned changed paths without writing. Remove it to
apply the same plan. The synchronizer uses the unchanged canonical operational
manifest/provenance functions, verifies the Work dependency blobs/modes and updates
the literal manifest and Work pins and generated current sections of the existing
AGENTS/runbook files. BrickMS keeps its Work pin in the execution adapter and its
inventory assertion in the vendor test; both are synchronized. Earlier sections
and receipts remain unchanged. Edited current
generated sections require explicit reconciliation instead of silent replacement.
Repeating the same accepted synchronization is a no-op.

For an adopter using its existing Work source route, keep the immutable baseline
and candidate without Git metadata. Add `--work-snapshot /external/source.json`,
`--work-baseline /external/baseline` and `--work-anchor /external/fresh-anchor.json`
together. The synchronizer verifies the complete baseline and candidate inventory,
repository identity and fresh default anchor before planning writes. The canonical
Core dependency still uses its verified native checkout. This explicit route does
not create Git metadata or grant connector authentication. Repeating a synchronization
still requires a fresh anchor and the unchanged independently verified baseline.

Writes are staged per file and rolled back on a reported error. This is not a
multi-file filesystem transaction across host termination: after a killed process,
inspect the Git diff and rerun the complete plan before checks/publication. No ref,
commit, changelog, checkpoint, release, deploy or production state is written by
the synchronizer. The host retains the complete delta and then applies all local
scope/effect, full-check, exact-head CI/review, merge and post-merge gates. Required
technical changelog entries remain repository-specific and user-authorized.

The dependency pin covers the complete canonical Work helper/test inventory,
including the recovery helper and its conformance tests. Nexus remains descriptive only; it never becomes
a runtime vendor or an authority source. Complete verified native Git/bundle input
remains supported when original binary bytes cannot be acquired through the
advertised connector. No file is excluded and no alternative transport is guessed.

## Acceptance

The pinned recovery conformance file is a standalone standard-library unittest
suite. Execute it with `python3 -I -B tests/test_agent_protocol_work_recovery.py`
inside the isolated dependency tree; importing or copying it is not a test run.
Stage the complete hash-verified Work inventory together with all four operational
siblings verified against the accepted canonical manifest, including their Git
blob identities and executable modes. Recheck copied bytes before execution.
The isolated tree must contain only these explicitly verified dependencies.
The recovery suite needs no pytest installation. The Work check suite uses real
pytest from the verified runtime with self-contained synthetic plugin and namespace
fixtures; it requires no application source or editable Core installation. Verify
the loaded fixture paths. Actual Core application integration remains covered by
the native Core and Windows CI gates; these fixtures do not qualify it.

Work runners execute source, check and recovery suites explicitly and propagate
every nonzero exit. Core also runs the same recovery cases under its full suite,
plus an isolated subprocess regression that proves the complete suite executes and an
injected recovery defect fails. The Core-only effect-profile assertion stays in
the Core contract tests; no recovery case is omitted downstream. Each adopter
must qualify its own runner and retain the original and corrective integrations
for any late finding before the final audit can close.

Synthetic tests cover loss of the original workspace, preserved raw instruction
and observation bytes, corrupt archives, unsafe paths/links, duplicate members,
expansion limits, failed persistence, changed current documentation, interrupted
adoption rollback, repeat synchronization and new policy observations on resume.
The full Core suite executes these and the displayed fresh-host bootstrap.
Each adopter still requires its own complete source, native/full checks and exact
integration gates before 1.4.5 is declared adopted. Final distribution requires
the canonical five-repository audit; candidate tests alone are insufficient.
