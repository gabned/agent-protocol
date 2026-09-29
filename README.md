# Agent Protocol

Independent Protocol engine, authenticated per-workstream lifecycle, host adapters,
preserved legacy validators and deterministic distribution tooling. Acceptance
and release identity come from the authenticated release and its external manifest;
a checkout or package version alone does not establish publication or authority.

Start with [the current contract](docs/agent-protocol/contract.md), then select
documents by phase and host using `.github/agent-protocol/documents.json`.
[Bootstrap authority](docs/agent-protocol/bootstrap.md) and
[source provenance](.github/agent-protocol/source.json) retain the extraction proof.
No product checkout, product libraries, private inventory or running service is required.

For development, use Python 3.12+, Node and Git, install `requirements-test.txt`,
then run `python tools/check.py`. Linux and Windows CI are independent required lanes.
`python tools/package.py --revision FULL_SHA --output OUTPUT_DIRECTORY` builds exact
committed source/wheel artifacts; an extracted source artifact also builds through
PEP 517 without Git or network dependencies. Packaging is not release authorization.

[Host setup and commands](docs/agent-protocol/hosts.md) describe read-only collection,
explain and enrolled write operations. Authentication, signer enrollment, policy and
production authority belong to the authorized host; the Core stores no credentials.
[Recovery](docs/agent-protocol/lifecycle.md) preserves identities, failures and history.
Original licensing, copyright and attribution remain in the included notices.
