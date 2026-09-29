"""Bootstrap isolation and trusted-base guard conformance using synthetic Git."""

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("guard", ROOT / "tools/guard.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
check_spec = importlib.util.spec_from_file_location("check", ROOT / "tools/check.py")
checker = importlib.util.module_from_spec(check_spec)
check_spec.loader.exec_module(checker)


def registry_for(paths):
    return {"paths": paths, "modes": {path: "100644" for path in paths}}


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.history = patch.object(
            guard, "introduced_commits", side_effect=lambda base, head: [(base, head)]
        )
        self.history.start()
        self.addCleanup(self.history.stop)

    def test_all_retained_commits_are_checked(self):
        self.history.stop()
        original = subprocess.check_output
        for attack in (
            "hidden",
            "frozen",
            "mode",
            "diverged",
            "merge",
            "shallow",
            "replacement",
        ):
            with self.subTest(attack=attack), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)

                def git(*args, root=root):
                    return original(["git", "-C", str(root), *args]).decode().strip()

                git("init", "-q")
                git("config", "user.name", "Synthetic")
                git("config", "user.email", "synthetic@example.invalid")
                (root / "allowed.md").write_text("base")
                (root / "AGENTS.md").write_text("accepted policy")
                git("add", ".")
                git("commit", "-qm", "base")
                base = git("rev-parse", "HEAD")
                if attack == "hidden":
                    (root / "unapproved.txt").write_text("synthetic forbidden material")
                    git("add", ".")
                elif attack == "frozen":
                    (root / "AGENTS.md").write_text("unaccepted policy")
                    git("add", ".")
                elif attack == "mode":
                    git("update-index", "--chmod=+x", "allowed.md")
                else:
                    (root / "allowed.md").write_text("intermediate")
                    git("add", ".")
                git("commit", "-qm", "intermediate")
                middle = git("rev-parse", "HEAD")
                if attack == "hidden":
                    (root / "unapproved.txt").unlink()
                if attack == "mode":
                    git("update-index", "--chmod=-x", "allowed.md")
                (root / "AGENTS.md").write_text("accepted policy")
                (root / "allowed.md").write_text("final")
                git("add", ".")
                git("commit", "-qm", "final")
                head = git("rev-parse", "HEAD")
                if attack == "diverged":
                    base = git("commit-tree", base + "^{tree}", "-m", "unrelated")
                elif attack == "merge":
                    head = git(
                        "commit-tree",
                        head + "^{tree}",
                        "-p",
                        head,
                        "-p",
                        base,
                        "-m",
                        "merge",
                    )
                elif attack == "shallow":
                    (root / ".git/shallow").write_text(base + "\n")
                elif attack == "replacement":
                    git("replace", middle, base)

                def invoke(argv, root=root):
                    return original(argv, cwd=root)

                with (
                    patch.object(guard.subprocess, "check_output", side_effect=invoke),
                    self.assertRaises(ValueError),
                ):
                    guard.inspect(
                        base,
                        head,
                        "WORKSTREAM_CLASS: PROTOCOL",
                        registry_for(["allowed.md", "AGENTS.md"]),
                    )

    def test_linear_multicommit_history_preserved(self):
        self.history.stop()
        original = subprocess.check_output
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def git(*args):
                return original(["git", "-C", str(root), *args]).decode().strip()

            git("init", "-q")
            git("config", "user.name", "Synthetic")
            git("config", "user.email", "synthetic@example.invalid")
            commits = []
            for text in ("base", "first", "second"):
                (root / "allowed.md").write_text(text)
                git("add", ".")
                git("commit", "-qm", text)
                commits.append(git("rev-parse", "HEAD"))

            def invoke(argv):
                return original(argv, cwd=root)

            with patch.object(guard.subprocess, "check_output", side_effect=invoke):
                result = guard.inspect(
                    commits[0],
                    commits[-1],
                    "WORKSTREAM_CLASS: PROTOCOL",
                    registry_for(["allowed.md"]),
                )
            self.assertEqual(result["commits"], commits[1:])

    def test_current_collector_failure_reaches_native_runner(self):
        original_run = subprocess.run
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = json.loads(
                (ROOT / ".github/agent-protocol/bootstrap.json").read_text()
            )
            for name in registry["paths"]:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("")
            (root / ".github/agent-protocol/bootstrap.json").write_text(
                json.dumps(registry)
            )
            (root / "tests/test_collect.mjs").write_text(
                "throw new Error('synthetic rejection');\n"
            )
            executed = []

            def invoke(argv, **kwargs):
                executed.append(argv)
                if argv == ["node", "--test", "tests/test_collect.mjs"]:
                    return original_run(argv, **kwargs, capture_output=True)
                return SimpleNamespace(returncode=0)

            with (
                patch.object(checker, "ROOT", root),
                patch.object(checker.subprocess, "run", side_effect=invoke),
            ):
                self.assertNotEqual(checker.main(), 0)
            self.assertIn(["node", "--test", "tests/test_collect.mjs"], executed)
            self.assertIn("src", executed[0])

    def test_partial_functional_inventory_is_not_bootstrap_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("")
            registry = root / ".github/agent-protocol/bootstrap.json"
            registry.parent.mkdir(parents=True)
            registry.write_text(
                json.dumps({"paths": ["pyproject.toml", "tests/test_collect.mjs"]})
            )
            with (
                patch.object(checker, "ROOT", root),
                patch.object(checker.subprocess, "run") as run,
            ):
                self.assertEqual(checker.main(), 2)
                run.assert_not_called()

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
