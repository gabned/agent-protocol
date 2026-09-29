"""Phase/host/workstream document selection from one accepted topic contract."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .ledger import digest, exact, require
from .source import safe_path

PHASES = {"START", "IMPLEMENT", "QUALIFY", "INTEGRATE", "RECOVER", "CLOSE", "ADOPT", "PUBLISH"}
HOSTS = {"CLI", "CONNECTOR", "CI", "BROWSER"}
WORKSTREAMS = {"PROTOCOL", "PRODUCT"}


def select(root, manifest, *, accepted_digest, phase, host, workstream):
    require(digest(manifest) == accepted_digest, "Document registry not independently selected")
    exact(manifest, "schema documents", "document registry")
    require(manifest["schema"] == "agent-protocol-documents/v2", "Unsupported document schema")
    require(
        phase in PHASES and host in HOSTS and workstream in WORKSTREAMS,
        "Unknown phase/host/workstream",
    )
    root, seen, selected = Path(root).resolve(), set(), []
    for row in manifest["documents"]:
        exact(row, "path sha256 phases hosts workstreams", "document record")
        name = safe_path(row["path"])
        require(
            name not in seen and name.startswith("docs/agent-protocol/"), "Document path collision"
        )
        seen.add(name)
        require(
            set(row["phases"]) <= PHASES
            and set(row["hosts"]) <= HOSTS
            and set(row["workstreams"]) <= WORKSTREAMS,
            "Unknown document routing",
        )
        if (
            phase not in row["phases"]
            or host not in row["hosts"]
            or workstream not in row["workstreams"]
        ):
            continue
        path = root / name
        require(not any(p.is_symlink() for p in (path, *path.parents)), "Symlink document refused")
        data = path.read_bytes()
        require(hashlib.sha256(data).hexdigest() == row["sha256"], "Document bytes changed")
        selected.append({"path": name, "sha256": row["sha256"], "bytes": len(data)})
    require(selected, "No accepted documents for this context")
    return {
        "phase": phase,
        "host": host,
        "workstream": workstream,
        "documents": selected,
        "model_text_bytes": sum(row["bytes"] for row in selected),
        "tokens": "UNKNOWN",
        "cost": "UNKNOWN",
    }
