import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("protocol_packaging", ROOT / "tools/package.py")
packaging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packaging)


class PackagingTests(unittest.TestCase):
    def files(self):
        # Test the real distribution loader from an isolated fresh directory,
        # without importing application libraries or depending on a Git checkout.
        names = [p.relative_to(ROOT).as_posix() for p in (ROOT / "src/agent_protocol").glob("*.py")]
        names += [
            "LICENSE",
            "COMMERCIAL-LICENSE.md",
            "THIRD_PARTY_NOTICES.md",
            "compat/legacy/tools/agent_protocol_v1_4_9.py",
            "compat/legacy/tools/agent_protocol_v1_4_2_ops.py",
        ]
        files = {}
        for name in names:
            data = (ROOT / name).read_bytes()
            blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            files[name] = ("100644", data, blob)
        return files

    def test_clean_source_restore_rebuilds_identical_wheel_without_git(self):
        files = self.files()
        name = ".github/agent-protocol/bootstrap.json"
        registry = {
            "paths": sorted([*files, name]),
            "modes": dict.fromkeys([*files, name], "100644"),
        }
        data = json.dumps(registry).encode()
        files[name] = (
            "100644",
            data,
            hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
        )
        archive = packaging.source_bytes(files, "a" * 40)
        with tempfile.TemporaryDirectory() as temporary:
            with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as source:
                source.extractall(temporary, filter="data")
            restored = Path(temporary) / "agent-protocol-1.5.0"
            actual, revision = packaging.restored_files(restored)
            self.assertEqual(revision, "a" * 40)
            self.assertEqual(packaging.wheel_bytes(actual), packaging.wheel_bytes(files))
            self.assertFalse((restored / ".git").exists())
            (restored / "LICENSE").write_bytes(b"altered")
            with self.assertRaisesRegex(ValueError, "Restored source bytes"):
                packaging.restored_files(restored)

    def test_deterministic_archives_preserve_notices_modes_and_standalone_policy(self):
        files = self.files()
        wheel = packaging.wheel_bytes(files)
        self.assertEqual(wheel, packaging.wheel_bytes(files))
        archive = packaging.source_bytes(files)
        self.assertEqual(archive, packaging.source_bytes(files))
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as source:
            self.assertEqual(len(source.getmembers()), len(files))
            self.assertTrue(all(row.isfile() and row.mode == 0o644 for row in source.getmembers()))
        with tempfile.TemporaryDirectory() as temporary:
            with zipfile.ZipFile(io.BytesIO(wheel)) as zipped:
                self.assertIn(
                    packaging.DIST + "/licenses/THIRD_PARTY_NOTICES.md", zipped.namelist()
                )
                zipped.extractall(temporary)
            code = (
                "import sys,json;sys.path.insert(0,sys.argv[1]);"
                "from agent_protocol.source import legacy;"
                "print(json.dumps(sorted(legacy('agent_protocol_v1_4_9').ROUTES)))"
            )
            result = subprocess.run(
                [sys.executable, "-I", "-c", code, temporary],
                cwd=temporary,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("PRODUCT/v2", json.loads(result.stdout))


if __name__ == "__main__":
    unittest.main()
