"""Bootstrap isolation and trusted-base guard conformance using synthetic Git."""

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("guard", ROOT / "tools/guard.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def registry_for(paths):
    return {"paths": paths, "modes": {path: "100644" for path in paths}}


class GuardTest(unittest.TestCase):
    def test_mode_only_change_and_incomplete_registration_fail(self):
        with (
            patch.object(
                guard.subprocess,
                "check_output",
                side_effect=[
                    b"M\0module.py\0",
                    b"100755 blob " + b"a" * 40 + b"\tmodule.py\0",
                ],
            ),
            self.assertRaisesRegex(ValueError, "Registered file mode"),
        ):
            guard.inspect(
                "a" * 40,
                "b" * 40,
                "WORKSTREAM_CLASS: PROTOCOL",
                registry_for(["module.py"]),
            )
        with self.assertRaisesRegex(ValueError, "Incomplete accepted mode"):
            guard.inspect(
                "a" * 40,
                "b" * 40,
                "WORKSTREAM_CLASS: PROTOCOL",
                {"paths": ["module.py"], "modes": {}},
            )

    def test_gate_changes_cannot_qualify_themselves(self):
        for path in sorted(guard.FROZEN | {"compat/legacy/pytest.ini"}):
            with (
                self.subTest(path=path),
                patch.object(
                    guard.subprocess,
                    "check_output",
                    return_value=("M\0" + path + "\0").encode(),
                ),
                self.assertRaisesRegex(ValueError, "PREDECESSOR_QUALIFICATION"),
            ):
                guard.inspect(
                    "a" * 40,
                    "b" * 40,
                    "WORKSTREAM_CLASS: PROTOCOL",
                    registry_for([path]),
                )

    def test_repository_recreation_is_not_the_same_destination(self):
        registry = {"repository": "example/protocol", "repository_id": 42}
        guard.check_repository(
            {"repository": {"full_name": "example/protocol", "id": 42}}, registry
        )
        for name, identity in [("example/protocol", 43), ("example/other", 42)]:
            with self.assertRaisesRegex(ValueError, "Stable repository"):
                guard.check_repository(
                    {"repository": {"full_name": name, "id": identity}}, registry
                )

    def test_closed_scope_and_both_rename_sides(self):
        registry = registry_for(["docs/old.md", "docs/new.md"])
        with patch.object(
            guard.subprocess,
            "check_output",
            side_effect=[
                b"R100\0docs/old.md\0docs/new.md\0",
                b"100644 blob " + b"a" * 40 + b"\tdocs/new.md\0",
            ],
        ):
            result = guard.inspect(
                "a" * 40, "b" * 40, "WORKSTREAM_CLASS: PROTOCOL", registry
            )
        self.assertEqual(result["paths"], ["docs/new.md", "docs/old.md"])
        with (
            patch.object(
                guard.subprocess,
                "check_output",
                return_value=b"R100\0private.md\0docs/new.md\0",
            ),
            self.assertRaises(ValueError),
        ):
            guard.inspect("a" * 40, "b" * 40, "WORKSTREAM_CLASS: PROTOCOL", registry)

    def test_symlinks_and_unknown_effects_refused(self):
        with (
            patch.object(
                guard.subprocess,
                "check_output",
                side_effect=[
                    b"A\0docs/new.md\0",
                    b"120000 blob " + b"a" * 40 + b"\tdocs/new.md\0",
                ],
            ),
            self.assertRaises(ValueError),
        ):
            guard.inspect(
                "a" * 40,
                "b" * 40,
                "WORKSTREAM_CLASS: PROTOCOL",
                registry_for(["docs/new.md"]),
            )
        with self.assertRaises(ValueError):
            guard.inspect(
                "a" * 40, "b" * 40, "WORKSTREAM_CLASS: PRODUCT", registry_for([])
            )

    def test_real_git_delta_and_candidate_registration_do_not_grant_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def git(*args):
                return (
                    subprocess.check_output(["git", "-C", str(root), *args])
                    .decode()
                    .strip()
                )

            git("init", "-q")
            git("config", "user.name", "Synthetic")
            git("config", "user.email", "synthetic@example.invalid")
            (root / "allowed.md").write_text("first")
            git("add", ".")
            git("commit", "-qm", "base")
            base = git("rev-parse", "HEAD")
            (root / "unapproved.md").write_text("candidate")
            git("add", ".")
            git("commit", "-qm", "candidate")
            head = git("rev-parse", "HEAD")
            original = subprocess.check_output

            def invoke(argv):
                return original(argv, cwd=root)

            with (
                patch.object(guard.subprocess, "check_output", side_effect=invoke),
                self.assertRaises(ValueError),
            ):
                guard.inspect(
                    base,
                    head,
                    "WORKSTREAM_CLASS: PROTOCOL",
                    registry_for(["allowed.md"]),
                )

    def test_runtime_has_no_application_dependency(self):
        registry = json.loads(
            (ROOT / ".github/agent-protocol/bootstrap.json").read_text()
        )
        self.assertEqual(registry["repository"], "gabned/agent-protocol")
        self.assertEqual(set(registry["paths"]), set(registry["modes"]))
        self.assertFalse(
            any(
                p.startswith(("core/provelume/", "public/", "app/"))
                for p in registry["paths"]
            )
        )


if __name__ == "__main__":
    unittest.main()
