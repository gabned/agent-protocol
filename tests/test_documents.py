import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import hashlib
import tempfile
import unittest

from agent_protocol.documents import select
from agent_protocol.ledger import digest


class DocumentsTests(unittest.TestCase):
    def test_selects_only_context_and_refuses_changed_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "docs/agent-protocol/contract.md"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"synthetic contract")
            manifest = {
                "schema": "agent-protocol-documents/v2",
                "documents": [
                    {
                        "path": "docs/agent-protocol/contract.md",
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "phases": ["START"],
                        "hosts": ["CLI"],
                        "workstreams": ["PROTOCOL"],
                    }
                ],
            }
            args = {
                "accepted_digest": digest(manifest),
                "phase": "START",
                "host": "CLI",
                "workstream": "PROTOCOL",
            }
            self.assertEqual(select(root, manifest, **args)["model_text_bytes"], 18)
            with self.assertRaises(ValueError):
                select(root, manifest, **{**args, "phase": "PUBLISH"})
            path.write_bytes(b"candidate authority")
            with self.assertRaises(ValueError):
                select(root, manifest, **args)


if __name__ == "__main__":
    unittest.main()
