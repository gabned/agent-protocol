# Release publication

Publish one Protocol release after the functional candidate has passed all accepted
gates, complete reviews, expected-head normal integration and post-merge checks.
Bootstrap acceptance is not a Protocol release. No application release or deploy
is implied by Protocol publication or consumer adoption.

The accepted revision, release identity, package metadata, conformance evidence,
file/mode manifest and distributed source must agree. Bind the revision in the
external artifact manifest; do not create an impossible self-referencing commit
field inside that same commit. Preserve an independently authenticated release
record, tag target and artifact digests. A self-hashed manifest is integrity only.

Required artifacts include the complete source archive, exact file/mode inventory,
digest list and conformance report. Preserve applicable licenses and attribution
inside distributions. Build in a clean environment from exact committed bytes;
do not include host keys, caches, private observations or product files. Reacquire
published artifacts and verify their bytes and tag/commit identity. Reconcile an
uncertain publication before retrying; never silently retag or replace history.

Final delivery separately reports CORE, five-consumer rollout, workspace
configuration and workspace runtime. Configuration must be verified even if paid
cloud provisioning is not authorized. NOT_PROVISIONED is a truthful runtime state,
not a substitute for configuration tests or evidence of an operational Codespace.
