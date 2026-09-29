# Qualification and evidence

The host selects accepted local policy before binding and uses the preserved
policy resolver. PRODUCT routes retain their own repository policy even when a
particular change has no production effects. NO_PRODUCTION effects do not create
deploy/migration capabilities. Unknown effects refuse binding.

Evidence identifies the exact code head, base/default, reviews, source pin,
policy, runtime, authority and stable repository identity. Dependency sets cannot
omit mandatory invalidators. Only affected evidence becomes stale; its original
PASS/FAIL/NOT_RUN/DEFERRED result is retained. Qualification depends on every
coordinate. Runtime, dependency or validator changes cannot silently reuse an
incompatible result. Existing CI equivalence rules remain mandatory.

CI observations contain complete runs, attempts and jobs, including failed and
superseded attempts. Required workflow/trigger identities come from accepted
policy. A candidate cannot remove a required lane, select only successful runs,
hide attempts or declare CI inapplicable. Review/thread inventories must be
complete, with current applicable review requirements fulfilled. A pending review
is not complete, and a resolved thread does not erase its original finding.

Qualify the candidate that will actually merge. Refresh the default and candidate
head immediately before integration, use a normal expected-head merge and inspect
the resulting parents/tree and applicable post-merge checks. A PR opening, copied
file or changed pin proves neither integration nor delivery. Preserve unrelated
PRODUCT work, authorizations and checkpoints; use a supported coordinated path
where synchronization is indispensable.

Required automated coverage is not optional because a user's PC is unavailable.
Use a qualified agent environment, reproducible container or independent CI.
Platform-specific behavior needs its native lane. Manual validation is reserved
for a concrete non-reproducible requirement and needs a private preview, minimal
scenario and expected result. Unperformed work remains NOT_RUN or authorized
DEFERRED. Linux evidence cannot certify native Windows behavior.
