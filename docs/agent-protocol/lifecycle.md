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

The source branch may advance after a successful merge. RECONCILE and CLOSE
record the freshly observed source head in the event without replacing the
retained qualified head, its qualification or integration intent. Merge parents,
tree and reviews still bind that retained candidate; post-merge checks bind the
actual merge commit. CLOSE reobserves the same reconciled merge identity. New
source commits receive no qualification or integration authority from settlement.
Settlement uses the original successful review gate retained in the signed journal,
including its complete provider evidence. A newer review or updated provider summary
for a later source head cannot replace that historical proof. Fresh complete thread
and review inventories still reject unresolved threads and changes requested on the
integrated candidate. Historical qualification is never rerun against mutable PR
prose, relabeled or used to qualify the newer head.
The merged collector omits newer-head CI, source-file/commit trees and mutable
provider summaries. Its fresh complete review/thread inventory, actual merge
identity and post-merge CI remain mandatory. Live production-trigger variables
gate candidate operations and merge dispatch; they do not block journal-only
settlement of an already observed merge.

RECONCILE_NOT_APPLIED settles an integration intent only with an independently
authenticated NOT_DISPATCHED or DEFINITIVELY_REJECTED receipt. The receipt names
the exact intent commit, operation, original head and workstream and establishes that no request
remains in flight. An open PR, timeout, elapsed time or repeated error is not that
proof. The operation retains the intent and receipt, returns to ACTIVE and clears
qualification. The current observed head may have advanced since the rejected
intent; recovery records that new head while retaining the old intent head and
history. A closed, unmerged PR can also settle conclusive non-execution before a
separately authorized abandonment. Neither case grants integration. A new
integration needs new qualifying evidence; unchanged
deterministic evidence still fails the anti-loop check. An uncertain dispatch
stays INTEGRATING until an actual merge or a conclusive non-execution receipt is
observed. No generic reset or user-supplied success override exists.

The native recovery collector for RECONCILE_NOT_APPLIED and ABANDON still verifies
the live repository, PR, branch, account and current head, but does not require the
new candidate to qualify. Missing classification, forbidden changes or non-linear
candidate history cannot prevent a conclusively authorized journal-only recovery.
This route emits no qualification evidence and cannot integrate the candidate.
Its raw collection reads only repository identity, PR identity/state/head and the
default branch, with a final PR comparison. Review/thread pagination, CI access
and candidate source traversal are absent from this typed recovery route.
Live production-trigger variables are also irrelevant to these journal-only
operations. A fresh host can load the independently accepted profile without
reading those variables; ordinary candidate observation and integration still
require every live effect condition. Recovery grants do not acquire deploy rights.

INTERRUPT preserves owner and durable recovery material, invalidates qualification
and records the reason. RESUME verifies restoration from durable material and
keeps the same owner. HANDOFF requires an interrupted state, exact independent
grant naming both owners, workstream, journal tip and candidate head, plus retained
material. It changes only the current owner; the original identity remains.
The recipient subsequently resumes under their own accepted signing identity.
ABANDON requires explicit scoped authority and retained material; it cannot conceal
an uncertain integration. It accepts an open or closed unmerged PR and preserves
both the retained head and the freshly observed head in its exact grant and event.
A head change before closure cannot prevent authorized abandonment; no earlier
event is rewritten. Terminal journals cannot be reopened or reset.

Before every write the host rereads the journal, reobserves external preconditions
and evaluates the same request. The host synchronizes the remote journal again after final collection, before
dispatching integration. A changed or missing intent refuses dispatch. This check
does not claim an atomic transaction between GitHub's journal ref and PR merge;
non-execution grants must independently establish that the original host is quiescent.
The event records its expected predecessor
and candidate head. Ref advancement uses compare-and-swap. Concurrent/divergent
history is reconciled or reported; no force push, generic checkpoint editor,
history reset or implicit ownership takeover is supported.

Remote recovery fetches only the selected journal ref, verifies its full signature
and ancestry chain before advancing local state, preserves unpublished local
events and refuses divergence. A fresh host must obtain accepted public signer
records and durable material independently. A cache or PR description is not
enough. No process/test is assumed alive merely because a host was persistent.
