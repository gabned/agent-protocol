# Agent Development Protocol v1.3.0 — review governance

This governance overlay preserves `LIFECYCLE_SCHEMA: 1.2`, PR-local ownership, the absence of a global checkpoint, exact effect/reconciliation reports, trusted-base change control and all clean-room, deterministic build, publication and production gates.

## Closed domains

- `REVIEW_REQUIREMENT_SOURCE: REPOSITORY | EXPLICIT_MAINTAINER | NONE | UNKNOWN`
- `CODEX_REVIEW_STATE: NOT_REQUESTED | PENDING | CLEAN | FINDINGS | WITHDRAWN | UNAVAILABLE | UNKNOWN`

The ordinary instruction declares `CODEX_REVIEW_REQUESTED: FALSE`, yielding `NONE / NOT_REQUESTED`. Only the exact current maintainer instruction `CODEX_REVIEW_REQUESTED: TRUE` makes Codex review a gate.

| Requirement source | Codex state | Additional evidence | Result |
| --- | --- | --- | --- |
| `NONE` | `NOT_REQUESTED` | no current finding | Codex gate not applicable |
| `REPOSITORY` | `NOT_REQUESTED` | GitHub-required review satisfied | allowed by the review gate |
| `REPOSITORY` | any | GitHub-required review missing or unknown | blocked |
| `EXPLICIT_MAINTAINER` | `PENDING`, `UNAVAILABLE`, `UNKNOWN` | any | blocked |
| `EXPLICIT_MAINTAINER` | `FINDINGS` | any | blocked until corrected or proved not applicable |
| `EXPLICIT_MAINTAINER` | `CLEAN` | verdict bound to current exact head | allowed by the review gate |
| `EXPLICIT_MAINTAINER` | `WITHDRAWN` | immutable exact-head maintainer withdrawal record | request removed; no clean signal and no waiver |

A moved head invalidates `CLEAN`. 👀 is acknowledgement only. `COMMENTED` without a verdict remains pending. An unsolicited current technical finding blocks. The review contract never creates, extends or reuses an emergency waiver.
