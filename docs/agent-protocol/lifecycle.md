# Lifecycle and recovery

The journal is append-only and local to one workstream. START changes NEW to
ACTIVE and records the selected policy, capabilities and exact observations.
REFRESH records material coordinate changes and invalidates qualification; it
cannot manufacture progress when nothing changed. QUALIFY records PASS or FAIL
with the complete evidence inventory. FAIL never becomes PASS by editing history.
A later successful qualification needs new observed evidence. Repeating an
unchanged deterministic failure under a new operation ID is refused.

INTEGRATE requires the exact current successful qualification and fresh matching
evidence. It records intent before the authorized host requests a normal merge
with expected candidate head. RECONCILE inspects the existing PR and merge commit:
ordered parents, qualified tree, base and head must match. A network error after
the write is not permission to repeat it. CLOSE requires observed post-merge
delivery and one next action/location. The same operation ID/request reconciles
to its existing event even after closure; changed content under that ID fails.

INTERRUPT preserves owner and durable recovery material, invalidates qualification
and records the reason. RESUME verifies restoration from durable material and
keeps the same owner. HANDOFF requires an interrupted state, exact independent
grant naming both owners, workstream, journal tip and candidate head, plus retained
material. It changes only the current owner; the original identity remains.
The recipient subsequently resumes under their own accepted signing identity.
ABANDON requires explicit scoped authority and retained material; it cannot conceal
an uncertain integration. Terminal journals cannot be reopened or reset.

Before every write the host rereads the journal, reobserves external preconditions
and evaluates the same request. The signed event records its expected predecessor
and candidate head. Ref advancement uses compare-and-swap. Concurrent/divergent
history is reconciled or reported; no force push, generic checkpoint editor,
history reset or implicit ownership takeover is supported.

Remote recovery fetches only the selected journal ref, verifies its full signature
and ancestry chain before advancing local state, preserves unpublished local
events and refuses divergence. A fresh host must obtain accepted public signer
records and durable material independently. A cache or PR description is not
enough. No process/test is assumed alive merely because a host was persistent.
