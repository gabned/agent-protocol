"""Build deterministic source/wheel artifacts from one exact committed revision.

Packaging proves bytes, never authority or release qualification. The authorized
publisher separately verifies its accepted revision, reviews and conformance.
This dependency-free PEP 517 backend also preserves legacy validators and notices.
"""

from __future__ import annotations

import argparse
import base64
import csv
import gzip
import hashlib
import io
import json
import re
import subprocess
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = "agent_protocol_core-1.5.0.dist-info"
NAME = "agent_protocol_core-1.5.0-py3-none-any.whl"


def committed_files(root, revision):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Exact immutable packaging revision required")
    git = ["git", "--no-replace-objects", "-C", str(root)]
    files = {}
    for record in subprocess.check_output([*git, "ls-tree", "-rz", revision]).split(b"\0"):
        if not record:
            continue
        metadata, name = record.split(b"\t", 1)
        mode, kind, blob = metadata.decode().split()
        path = name.decode()
        if mode not in {"100644", "100755"} or kind != "blob":
            raise ValueError("Unapproved distribution mode/type")
        if (
            path.startswith("/")
            or "\\" in path
            or any(p in {"", ".", ".."} for p in path.split("/"))
        ):
            raise ValueError("Unsafe artifact path")
        data = subprocess.check_output([*git, "cat-file", "blob", blob])
        files[path] = (mode, data, blob)
    registry = json.loads(files[".github/agent-protocol/bootstrap.json"][1])
    if set(files) != set(registry["paths"]) or any(
        files[p][0] != registry["modes"][p] for p in files
    ):
        raise ValueError("Packaging requires the complete registered file/mode inventory")
    return files


def wheel_bytes(files):
    """Assemble exact source bytes; no build hooks or candidate dependencies run."""
    members = {}
    for name, (mode, data, _blob) in files.items():
        target = name[4:] if name.startswith("src/") else "agent_protocol/_distribution/" + name
        members[target] = (mode, data)
        if name in {"LICENSE", "COMMERCIAL-LICENSE.md", "THIRD_PARTY_NOTICES.md"}:
            members[DIST + "/licenses/" + name] = (mode, data)
    metadata = (
        "Metadata-Version: 2.3\nName: agent-protocol-core\nVersion: 1.5.0\n"
        "Summary: Independent Agent Protocol Core\nRequires-Python: >=3.12\n\n"
        "Original LICENSE, COMMERCIAL-LICENSE.md and THIRD_PARTY_NOTICES.md apply.\n"
    )
    members[DIST + "/METADATA"] = ("100644", metadata.encode())
    members[DIST + "/WHEEL"] = (
        "100644",
        b"Wheel-Version: 1.0\nGenerator: agent-protocol\n"
        b"Root-Is-Purelib: true\nTag: py3-none-any\n",
    )
    members[DIST + "/entry_points.txt"] = (
        "100644",
        b"[console_scripts]\nagent-protocol = agent_protocol.cli:main\n",
    )
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for path, (_mode, data) in sorted(members.items()):
        encoded = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        writer.writerow([path, "sha256=" + encoded, len(data)])
    writer.writerow([DIST + "/RECORD", "", ""])
    members[DIST + "/RECORD"] = ("100644", record.getvalue().encode())
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, (mode, data) in sorted(members.items()):
            info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = int(mode, 8) << 16
            info.create_system = 3
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
    return output.getvalue()


def source_bytes(files):
    output = io.BytesIO()
    with (
        gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive,
    ):
        for path, (mode, data, _blob) in sorted(files.items()):
            member = tarfile.TarInfo("agent-protocol-1.5.0/" + path)
            member.size, member.mode, member.mtime = len(data), int(mode, 8) & 0o777, 0
            archive.addfile(member, io.BytesIO(data))
    return output.getvalue()


def current_revision():
    return subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"]).decode().strip()


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    revision = current_revision()
    target = Path(wheel_directory) / NAME
    target.write_bytes(wheel_bytes(committed_files(ROOT, revision)))
    return NAME


def build_sdist(sdist_directory, config_settings=None):
    name = "agent_protocol_core-1.5.0.tar.gz"
    (Path(sdist_directory) / name).write_bytes(
        source_bytes(committed_files(ROOT, current_revision()))
    )
    return name


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    files = committed_files(ROOT, args.revision)
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "agent-protocol-source/v1",
        "repository": "gabned/agent-protocol",
        "repository_id": 1393711644,
        "revision": args.revision,
        "version": "1.5.0",
        "files": [
            {"path": p, "mode": m, "blob": b, "sha256": hashlib.sha256(d).hexdigest()}
            for p, (m, d, b) in sorted(files.items())
        ],
    }
    artifacts = {
        "source.tar.gz": source_bytes(files),
        NAME: wheel_bytes(files),
        "source-manifest.json": (json.dumps(manifest, indent=2) + "\n").encode(),
    }
    for name, data in artifacts.items():
        target = args.output / name
        if target.exists() and target.read_bytes() != data:
            raise ValueError("Existing different artifact preserved; use another output directory")
        target.write_bytes(data)
    sums = "".join(
        hashlib.sha256(data).hexdigest() + "  " + name + "\n"
        for name, data in sorted(artifacts.items())
    )
    sums_path = args.output / "SHA256SUMS"
    if sums_path.exists() and sums_path.read_text(encoding="utf-8") != sums:
        raise ValueError("Existing digest list differs")
    sums_path.write_text(sums, encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {
                "revision": args.revision,
                "result": "BYTES_PACKAGED",
                "publication_authorized": False,
                "conformance_report": "REQUIRED_FROM_ACCEPTED_HOST",
                "files": len(files),
            }
        )
    )


if __name__ == "__main__":
    main()
