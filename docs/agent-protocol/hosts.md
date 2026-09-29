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

Publication of journal events is an ordinary fast-forward push. Reobserve the
remote ref after an uncertain result and reconcile the existing operation ID.
Recovery refuses shallow history, grafts, replacements, missing signatures and
divergence. No candidate code runs in the credentialed host during collection.

The persistent laboratory is an optional host, not authority or an execution
prerequisite. A stopped machine does not imply live processes. Codespaces creation,
paid resources and account login are distinct from configuration verification;
their real state must be reported explicitly. An external chat does not gain
automatic control of a cloud terminal.
