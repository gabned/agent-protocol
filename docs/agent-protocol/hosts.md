# Authorized hosts

Run the accepted, byte-verified package outside the candidate checkout. The engine
has no credential store and performs no network or Git effects. An authorized host
authenticates its account, exact repository ID, accepted policy and signer registry
separately from candidate inputs. Tokens must never enter Git, logs, remote URLs,
images, artifacts or handoffs. Repository access is not authority for every action.

The Git journal host uses accepted public SSH signer lines and the operator's
supported Git signing configuration. It does not generate/enroll keys or infer
capabilities. Signer enrollment or replacement needs an independently accepted
local authority decision. Candidate tests run without the operator's signer,
GitHub credentials, Docker socket or other repositories. Synthetic tests create
temporary keys solely inside disposable test directories.

The host collects real external objects, preserves raw evidence and verifies
identity/completeness before passing normalized observations to the engine.
User-editable JSON and self-computed digests do not authenticate observations.
Explain can operate offline and never authorizes a write. Before signing an event
the host refreshes the same observations and reevaluates the typed request.
An unchanged deterministic error is not a reason for equivalent retries.

Publication of journal events requires verified fast-forward ancestry and an
exact old-ref Git lease. The lease is compare-and-swap, never authorization for
non-fast-forward history; deletion or concurrent advancement rejects the push.
An absent remote with retained local history is not a new journal. Only this
host process's fresh, unattempted initial START may create the ref. A lost initial
publication response must be reconciled from the remote or retained external
evidence; absence cannot authorize recreation. Recovery enrollment retains an
independently observed ancestor. Candidate branches cannot use the journal namespace.
Reobserve the
remote ref after an uncertain result and reconcile the existing operation ID.
Recovery refuses shallow history, grafts, replacements, missing signatures and
divergence. No candidate code runs in the credentialed host during collection.

The persistent laboratory is an optional host, not authority or an execution
prerequisite. A stopped machine does not imply live processes. Codespaces creation,
paid resources and account login are distinct from configuration verification;
their real state must be reported explicitly. An external chat does not gain
automatic control of a cloud terminal.

## Native GitHub entrypoint

The native Protocol adapter uses the supported `gh` login on an enrolled operator
host. `node tools/collect.mjs --github OWNER/REPOSITORY REPOSITORY_ID PR_NUMBER`
performs bounded read-only collection. It checks repository IDs, all review and
nested thread-comment pages, run attempts/jobs and retained candidate trees. Work
uses `collectLifecycle` with authenticated connector functions and the same
`qualify-pr` engine. Collected JSON is evidence input, never write authorization.
The optional `fetchViewer` callback reads the authenticated account through the
same credential context as the review list; it is a host capability, never a
candidate-supplied account claim. Missing viewer evidence cannot establish a
mandatory human reviewer's private draft state. Native `gh` binds that context.

`agent-protocol start --enrollment /operator/enrollment.json` reads one typed
request from standard input. The other write commands are `refresh`, `interrupt`,
`resume`, `handoff`, `qualify`, `integrate`, `reconcile`, `reconcile-not-applied`,
`close` and `abandon`. `explain --enrollment ...` evaluates the identical live
preconditions; `state --enrollment ...` restores and reports the selected journal.
Without enrollment, `explain` remains an offline engine command and write commands
refuse input. Requests contain only operation, stable operation ID, expected journal
tip, expected candidate head and the operation's closed parameter schema.

Enrollment is a separately approved operator installation artifact, outside
candidate checkouts. It has schema `agent-host-enrollment/v1` and contains:

- `identity`: immutable repository ID, PR, branch, workstream/class and origin owner;
- `authority`: independently approved principal, operations, unchanged local
  policy, capabilities, source pin, public signer registry identity and exact grants;
- `account`: GitHub numeric account ID and login observed by the operator;
- `profile_revision`, `profile_path`, `profile_blob`: accepted repository profile
  selected under predecessor change control, never a file from the PR;
- `journal_directory`, `required_ancestor`, `public_signers`: isolated operator
  Git directory, independently retained recovery anchor and approved public keys;
- `source_bundle`: original source archive path/digest and exact release manifest/digest,
  selected from the authenticated release. Installed bytes and archive modes are
  checked against this artifact, including Windows and wheel installations.

These fields do not enroll themselves. The authorized native adapter or operator
establishes their authority before invocation. The package does not generate keys,
enroll accounts, broaden permissions or create approval grants. It binds the existing
enrolled account's supported `gh auth token --user` credential in operator memory
(or verifies the supplied host environment credential). The same bound environment
serves reads, collection, HTTPS journal pushes and integration; changing the ambient
active gh account cannot switch the actor mid-operation. Credentials never enter
command arguments, journal events or artifacts. Fresh account identity is checked
at collection and integration boundaries. A connector
without signed-journal host capabilities can collect and explain; it must hand the
typed operation to an enrolled host and cannot substitute unsigned Git commits.

The accepted `agent-host-profile/v1` defines exact repository identity, registered
`paths` and modes, `frozen_paths`, required pre/post-merge workflows, reviewers,
review activity providers, runtime identity and live production-trigger conditions.
Its introduction/change must pass the predecessor's local gates. The native
Protocol host requires CI, native CI, reviews, effects, ancestry, source and authority
evidence. It does not replace PRODUCT qualification: PRODUCT adapters retain their
accepted local policy and use the shared `ProtocolHost` evaluator/executor boundary.

The adapter integrates only its enrolled PR and publishes its signed journal.
Journal pushes use the same bound GitHub credential over HTTPS, with no URL secrets.
Integration uses GitHub's normal pull-request merge endpoint with the exact
expected candidate SHA and merge method. It never updates the default ref directly,
requires protections to be absent, bypasses server policy or modifies repository
protections. After the durable intent, it recollects the full qualification and
compares all coordinates again immediately before dispatch. Provider rejection
does not authorize a different effect mechanism.

The API atomically guards the candidate head and enforces configured server gates.
It does not expose a transaction over the qualified base and every external review
observation. Freshness is the accepted observation-boundary contract, not a claim
that independently mutable external evidence is locked. An independently accepted
policy requiring stronger atomic guarantees needs a supported server mechanism;
this adapter cannot certify that stronger guarantee. Reconciliation checks actual
parents/tree/default and post-merge CI; a mismatch cannot be turned into PASS.
See the [normal merge API](https://docs.github.com/en/rest/pulls/pulls#merge-a-pull-request).

Merge intent is durable first; a retry of that intent never sends another merge.
Live production conditions are checked again immediately before dispatch. Reopening
a host after integration can read the accepted profile from verified default-branch
ancestry, while reconciliation checks the exact original merge parents/tree and
post-merge CI separately. A previous head's CI cannot close the lifecycle.
