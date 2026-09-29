# Historical compatibility

`compat/legacy/` retains original Protocol modules, fixtures, tests, document
registries and the historical CI file consumed by those tests. That nested workflow
is fixture material, not an active workflow. Relative paths are intentionally
preserved because imports, document selectors and receipt validators depend on
them. Notices, copyright and licensing remain applicable and unchanged.

Old receipts retain their original schema, validator and result. The new scoped
audit does not extend the historical audit's repository universe or fetch excluded
repositories. Only the current host's accepted exact scope may be observed. The
current policy and CI qualifiers reuse preserved pure validators; they do not
modify the historical modules or their scope rules.

Keep legacy consumer pins usable throughout migration. A qualified authority
transfer preserves source commit, destination commit/tree, source-to-destination
file map, digest, executable mode and complete bootstrap history separately from
functional changes. No application Git history is imported and Git is not rewritten.

Compatibility removal requires proof that no operational import, native wrapper,
receipt, recovery route or open owner still needs it. Recoverable historical Git
objects may support old receipts only when their exact validators/dependencies
remain documented and obtainable. Moving everything into an undifferentiated
history or backup directory is not a valid cleanup method.
