# Provelume Core agent entry

AGENT_DEVELOPMENT_PROTOCOL: 1.4.9
LIFECYCLE_SCHEMA: 1.2
CAMPAIGN_SCHEMA: 2

These instructions apply to all of `gabned/provelume`. GitHub is the executable
source of repository, branch, commit, PR, checks, tag and release identity.

## Core boundaries

- This public clean-room Core and self-hosted Instance must work without Nexus,
  Provelume Cloud, GitHub at runtime or an external AI provider. Never transplant
  private code, paths, fixtures, data, operational state or Git history. Use public
  requirements and synthetic fixtures; no private dependency is required here.
- Keep one PR-local owner per homogeneous workstream. Core has no `AGENT_STATUS.md`,
  committed global lock or second checkpoint. Do not interfere with another owner.
- Separate PRODUCT and PROTOCOL. A PRODUCT Protocol defect stops that workstream
  and follows the separate escalation path. Never weaken a gate, fabricate authority
  or author a waiver. Explicit user authorization persists within its actual scope.
- Keep credentials and private data out of source, logs, public evidence and CI.
  No untrusted artifact or candidate code enters a secret-bearing context.
- Preserve offline verification, deterministic builds, least privilege and the
  existing independent release/publication gates. Normal CI does not publish.
  Release identity, package metadata and actual reviewed `main` commit must agree.

## Read and execute

Start with one bounded GitHub reconciliation and verify complete source identity.
Read [the current cross-cutting contract](docs/agent-development-v1.4.9.md) always.
Then use `tools/agent_protocol_v1_4_7.py select-documents` with the independently
selected accepted-base `.github/agent-protocol/documents-v1.4.9.json`, its verified
canonical JSON digest, and actual workstream/phase/host. Integrity failures stop;
uncertain selection loads the full inventory. Candidate routing cannot qualify
its own adoption. Historical receipts use their matching historical validator.

The current contract owns authority, required reading, communication and closure.
Its manifest routes Work source, recovery and operational evidence procedures.
For a new product area, read its owning architecture/release documentation and
relevant code; roadmap and changelog retain their separate functions. Use narrow
searches before large reads. Original complete evidence stays outside source;
normal model output contains compact references, findings and uncertainty.
Resume from the existing checkpoint; use the current contract's context-delta and
checkpoint-handoff routes for retained text, measurements and the single next step.

## Native checks

Use Python 3.12 or newer and the supplied Node runtime. Reuse valid dependencies;
when missing, run `python scripts/bootstrap.py`. Before publication run the full
native checks on the unchanged candidate:

```bash
.venv/bin/python -m ruff check core tests scripts tools
.venv/bin/python -m pytest -q
git diff --check
```

On Windows use `.venv\Scripts\python.exe`. Release-chain changes additionally run
the checked-in release dry-run/offline-verifier paths. Local success is not remote
qualification. Use permanent workflows, complete exact-head CI/reviews, baseline
scope/effect binding and normal expected-head GitHub merge. Reconcile actual merge
identity and required post-merge checks before claiming delivery.
