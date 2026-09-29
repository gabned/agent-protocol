import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import copy
import hashlib
import tempfile
import unittest

from agent_protocol.ledger import digest
from agent_protocol.source import validate_inventory, verify_files


def fixture():
    content = b"synthetic canonical bytes\n"
    manifest = {
        "schema": "agent-protocol-source/v1",
        "repository": "gabned/agent-protocol",
        "repository_id": 1393711644,
        "revision": "a" * 40,
        "version": "1.5.0",
        "files": [
            {
                "path": "src/example.py",
                "mode": "100644",
                "blob": hashlib.sha1(
                    b"blob " + str(len(content)).encode() + b"\0" + content
                ).hexdigest(),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ],
    }
    return content, manifest


class SourceTests(unittest.TestCase):
    def test_bytes_mode_identity_and_traversal(self):
        content, manifest = fixture()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "src/example.py"
            path.parent.mkdir()
            path.write_bytes(content)
            args = {
                "expected_digest": digest(manifest),
                "observed_modes": {"src/example.py": "100644"},
            }
            self.assertEqual(verify_files(root, manifest, **args)["result"], "BYTES_VERIFIED")
            with self.assertRaises(ValueError):
                verify_files(
                    root, manifest, **{**args, "observed_modes": {"src/example.py": "100755"}}
                )
            path.write_bytes(b"changed")
            with self.assertRaises(ValueError):
                verify_files(root, manifest, **args)
        for attack in ("traversal", "duplicate", "mode", "identity", "self-digest"):
            value = copy.deepcopy(manifest)
            if attack == "traversal":
                value["files"][0]["path"] = "../secret"
            elif attack == "duplicate":
                value["files"].append({**value["files"][0], "path": "SRC/example.py"})
            elif attack == "mode":
                value["files"][0]["mode"] = "120000"
            elif attack == "identity":
                value["repository_id"] += 1
            else:
                value["files"][0]["sha256"] = "f" * 64
            with self.subTest(attack=attack), self.assertRaises(ValueError):
                validate_inventory(
                    value, digest(manifest) if attack == "self-digest" else digest(value)
                )


if __name__ == "__main__":
    unittest.main()
