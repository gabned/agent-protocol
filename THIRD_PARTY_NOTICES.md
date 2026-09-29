# Third-party notices

Provelume's public license does not replace the licenses of third-party dependencies.

Direct runtime dependencies in the current Python package include:

| Component | Purpose | License |
| --- | --- | --- |
| FastAPI | Knowledge API and web routing | MIT |
| Jinja2 | server-side Knowledge Browser templates | BSD-3-Clause |
| pypdf | local PDF text extraction | BSD-3-Clause |
| PyYAML | Instance configuration | MIT |
| Uvicorn | local ASGI server | BSD-3-Clause |
| qrcode 8.2 | local single-use pairing QR encoding | BSD-3-Clause AND inherited MIT notice |

Capture uses qrcode's pure SVG encoder; it does not bundle an image decoder or invoke
an external QR service. The complete unchanged upstream license, including Lincoln
Loop (2011) and Kazuhiko Arase (2009) notices, is packaged at
`provelume/notices/qrcode-LICENSE.txt`. Pillow remains an explicitly installed external
component for the optional Capture PNG/JPEG decoder; its existing notices below apply.

Release-build tooling includes:

| Component | Purpose | License |
| --- | --- | --- |
| build | Python wheel/source distribution build frontend | MIT |
| Hatchling | pinned Python build backend and reproducible archive support | MIT |
| CycloneDX Python (`cyclonedx-bom`) | release SBOM generation | Apache-2.0 |
| GitHub Actions checkout/setup/upload/attest actions | public CI and release automation | licenses published by their respective repositories |

These components have their own copyright notices and license terms. Transitive dependencies retain their own terms as well. Published release SBOMs are the machine-readable dependency inventory for the built Python environment; this file is a human-readable summary, not a substitute for that SBOM.

## Cura UI icons — vendored Lucide subset in 0.11/S02

Provelume includes 18 unchanged SVG sources from [Lucide 1.45.0](https://github.com/lucide-icons/lucide/releases/tag/1.45.0),
commit `b998e2892b90b88004d62da2d0b64dab9959a520`, for decorative icons beside visible
navigation and status labels. Lucide's ISC license and the applicable MIT notices for its
Feather-derived icons are both retained: the aggregate subset is **ISC AND MIT**, not MIT-only
and not a choice between ISC and MIT. Copyright holders are Lucide Icons and Contributors
(2026) and Cole Bemis (2013-present, Feather-derived list).

The complete, unchanged upstream [LICENSE](core/provelume/notices/lucide-LICENSE.txt),
including both permission/disclaimer blocks and the Feather icon list, is packaged at
`provelume/notices/lucide-LICENSE.txt`. Its SHA-256 is
`b495047bd93a9b06913511076f504daba17d5bbeb3e0650f3bb53a4220329c57`.
The [subset manifest](core/provelume/static/icons/lucide/subset.json) records every
source byte identity and upstream reference. `triangle-alert` retains its upstream
`alert-triangle` alias reference for the Feather-list attribution. No exhaustive individual
copyright history is inferred from icon names or geometry.

The installed component catalogue and release SBOM consume that same verified manifest.
Updates require a reviewed Provelume source/release change with license, hash and artifact
verification. No icon framework, npm runtime, CDN or runtime network service is required.
Provelume's own license does not replace these third-party terms. See [ADR 0028](docs/adr/0028-cura-icons-and-provenance.md).

## Qualified optional OCR baseline — external in 0.9/S02

The `0.9/S02` implementation can execute the Tesseract CLI through a replaceable local process
adapter and uses PDFium/Pillow through a separate renderer/decoder process. It adds adapter code,
not native payloads: the base wheel, source distribution and Windows installer still contain no OCR
engine, language model, PDF renderer, image decoder or optional Python wheel. These components are
installed and configured separately by the operator and are **not bundled by Provelume**:

| Component | Intended purpose | License | S02 distribution |
| --- | --- | --- | --- |
| Tesseract 5.5.3 | local printed-text OCR engine | Apache-2.0 | not bundled |
| Leptonica | Tesseract image decoding and processing | BSD-2-Clause | not bundled |
| `tessdata_fast` language packs | explicit local OCR language data | Apache-2.0 | not bundled |
| pypdfium2 5.13.0 | Python binding and external-wheel delivery of PDFium | Apache-2.0 OR BSD-3-Clause, plus dependency licenses | not bundled |
| PDFium 153.0.7999.0 | PDF rasterization in the qualified Linux wheel | BSD-3-Clause and dependency licenses | not bundled |
| Pillow 12.3.0 | TIFF, PNG, JPEG and BMP decode/render boundary | MIT-CMU and applicable wheel dependency terms | not bundled |

The qualified Ubuntu x86_64 CI job provisions the two Python wheels by exact version and SHA-256,
records the distribution-provided Tesseract, Leptonica and `eng` pack identities, then runs with no
runtime installer or fallback. The pypdfium2 wheel carries `LICENSES` and platform-specific
`BUILD_LICENSES` for PDFium and its native dependencies; those files remain authoritative for that
external wheel. [`packaging/ocr/qualified-local-components.cdx.json`](packaging/ocr/qualified-local-components.cdx.json)
is a machine-readable inventory of the qualified external path, not the SBOM of a Provelume release
artifact.

Before Provelume redistributes any of these components, the release must carry every applicable
license and attribution, enumerate every binary, codec and language pack in the release manifest
and release CycloneDX SBOM, publish exact checksums, and prove an offline installation with
networking denied. The S02 Windows model therefore remains explicit external local installation;
there is no offline installer component yet. Provelume's public or commercial license does not
replace any third-party term.

## Qualified local email baseline — runtime standard library in 0.9/S03

The `0.9/S03` EML and Maildir baseline adds no Python dependency, native parser, provider SDK,
language pack or remote service. MIME parsing uses the `email` package supplied by the qualified
CPython 3.12 runtime, under the Python Software Foundation License, behind a replaceable Provelume
parser interface. Exact message bytes are read by Provelume's bounded local adapters before parsing;
the Python `mailbox` package was evaluated but is not used for message reading or delimitation.

The wheel and source distribution do not copy the CPython standard library. The Windows frozen
application continues to carry its existing Python runtime; S03 adds no separate email component or
payload. [`packaging/email/qualified-local-components.cdx.json`](packaging/email/qualified-local-components.cdx.json)
is the machine-readable inventory for this development qualification, not the SBOM of a published
Provelume release. No `0.9.0` release artifact is created by S03.

## Local transcript profiles — first-party parser in 0.9/S05

The `0.9/S05` SRT and WebVTT baseline adds no Python dependency, native parser,
provider SDK, media codec, model or remote service. Parsing is implemented by
first-party bounded code behind a replaceable provider-neutral contract and uses only
the CPython 3.12 standard library, under the Python Software Foundation License.
The wheel and source distribution contain no transcript payload or private fixture.

[`packaging/transcript/qualified-local-components.cdx.json`](packaging/transcript/qualified-local-components.cdx.json)
records the runtime-provided standard-library boundary for permanent synthetic local
conformance. It is not the aggregate release SBOM and makes no cloud-provider, audio,
video, speech-to-text or real-data qualification claim. S05 itself created no release artifact;
the baseline is included in the later `0.9.0` release boundary.

## Qualified optional local audio baseline — external in 0.10/S04

The `0.10/S04` profile can invoke one explicitly configured local path: `whisper.cpp` 1.9.2 at
source commit `306c88f4d1286aec1bf96e544632897886af5501` with the multilingual Whisper tiny `q5_1`
GGML model. Both are licensed under MIT terms and remain **not bundled by Provelume**. The operator
supplies absolute paths and exact binary/model identity; the installer and runtime never discover,
download, update or remotely replace either component.

[`packaging/audio/qualified-local-components.cdx.json`](packaging/audio/qualified-local-components.cdx.json)
records this qualified optional path and its model checksum. It is not the aggregate release SBOM.
The Python wheel, source distribution and Windows installer include only Provelume's bounded
adapter, schema and manifest; they contain no speech engine, model, codec or private audio fixture.

## Qualified optional local video baseline — external in 0.10/S05

The `0.10/S05` profile can invoke one explicitly configured FFmpeg/ffprobe 9.0.1 pair built from
the official source archive. The pair is governed by FFmpeg's LGPL 2.1-or-later baseline when built
without optional GPL or nonfree components and remains **not bundled by Provelume**. The operator
supplies absolute paths, the declared version and exact hashes for both binaries; Provelume never
discovers, downloads, updates or remotely replaces them.

[`packaging/video/qualified-local-components.cdx.json`](packaging/video/qualified-local-components.cdx.json)
records the qualified optional Ubuntu path and source checksum. It is not the aggregate release
SBOM. The Python wheel, source distribution and Windows installer contain no FFmpeg binary, codec,
model, media payload or private fixture. Any future redistribution must inventory the exact build
configuration and all applicable component licenses first.
