# Current Agent Protocol contract

This topic contract governs only an independently accepted distribution. A
candidate is not its own authority. The host first authenticates the repository,
accepted source revision, local policy, exact scope and current workstream owner.
Then it verifies package bytes/modes and selects documents by phase and host.
Application architecture, release cadence and PRODUCT policies remain local.

One durable append-only journal belongs to each PR/workstream. Its immutable
identity includes the stable repository ID, PR, branch, workstream class and
original owner. Git history and independently accepted signer identities protect
the journal; an editable PR body or content digest cannot replace those proofs.
The current state is derived from that complete history. Local `.agent/` files
are ignored caches, never a second operational authority. A pre-existing
AGENT_STATUS cache keeps useful release/epic/slice information without becoming
a second lifecycle. An actual legacy checkpoint keeps its original validator.

The engine evaluates policy, observed effects and capabilities separately, before
binding. It cannot create credentials, grant capabilities, authorize production,
change ownership implicitly or weaken local policy. The accepted host collects
fresh observations and performs authorized writes with expected heads. A missing
access or 404 is unresolved, not evidence that a repository does not exist.

Operations are START, REFRESH, INTERRUPT, RESUME, HANDOFF, QUALIFY, INTEGRATE,
RECONCILE, CLOSE and ABANDON. Explain evaluates the same preconditions without a
write. See [lifecycle](lifecycle.md), [qualification](qualification.md) and
[hosts](hosts.md). Unknown effects, incomplete history, stale dependent evidence,
unexpected heads and mismatched identities fail closed. Errors remain evidence.

No orchestrator, always-on service or global cross-repository checkpoint is
required. [Adoption](adoption.md) distinguishes engine deployment, state migration
and compatibility cleanup. [Compatibility](compatibility.md) preserves receipts.
[Publication](publication.md) binds one release to its accepted revision.
[Communication](communication.md) defines milestone and handoff behavior.
