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
        "version": "1.5.2",
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


def git_fixture():
    import base64

    from agent_protocol.source import _git_tree

    content, manifest = fixture()
    tree = _git_tree(manifest)
    base = "1" * 40
    identity = (
        "author Synthetic <test@example.invalid> 0 +0000\n"
        "committer Synthetic <test@example.invalid> 0 +0000\n"
    )
    head_data = (f"tree {tree}\nparent {base}\n" + identity + "\nhead\n").encode()
    head = hashlib.sha1(b"commit " + str(len(head_data)).encode() + b"\0" + head_data).hexdigest()
    merge_data = (f"tree {tree}\nparent {base}\nparent {head}\n" + identity + "\nmerge\n").encode()
    revision = hashlib.sha1(
        b"commit " + str(len(merge_data)).encode() + b"\0" + merge_data
    ).hexdigest()
    manifest["revision"] = revision
    origin = {
        "schema": "agent-protocol-git-origin/v1",
        "repository": manifest["repository"],
        "repository_id": manifest["repository_id"],
        "revision": revision,
        "tree": tree,
        "base": base,
        "head": head,
        "acceptance": {
            "pull_request": 1,
            "receipt_url": "https://github.com/gabned/agent-protocol/pull/1#issuecomment-1",
            "receipt_sha256": "2" * 64,
        },
    }
    proof = {
        "schema": "agent-protocol-git-provenance/v1",
        "origin": origin,
        "commits": [
            {"revision": sha, "object": base64.b64encode(data).decode()}
            for sha, data in ((head, head_data), (revision, merge_data))
        ],
    }
    return content, manifest, proof


class GitSourceTests(unittest.TestCase):
    def test_malformed_source_and_host_enrollment_fail_before_host_effects(self):
        from agent_protocol.host import NativeGitHubHost
        from agent_protocol.source import verify_installation

        for malformed in (None, [], "candidate-selected"):
            with self.subTest(value=malformed), self.assertRaises(ValueError):
                verify_installation(malformed, revision="a" * 40)
            with self.subTest(value=malformed), self.assertRaises(ValueError):
                NativeGitHubHost(malformed)

    def test_original_commit_graph_and_complete_tree_verify_without_git(self):
        from unittest.mock import patch

        from agent_protocol.source import verify_git_provenance

        _content, manifest, proof = git_fixture()
        authority = copy.deepcopy(proof["origin"])
        with patch("subprocess.check_output", side_effect=AssertionError("offline")):
            result = verify_git_provenance(proof, manifest, authenticate_origin=lambda: authority)
        self.assertEqual(result["result"], "BYTES_VERIFIED")
        self.assertEqual(result["tree"], authority["tree"])
        self.assertEqual(result["kind"], "CANONICAL_GIT")

    def test_json_and_self_digests_do_not_enroll_source_or_allow_ambiguous_history(self):
        from agent_protocol.source import verify_git_provenance

        _content, original_manifest, original = git_fixture()
        authority = copy.deepcopy(original["origin"])
        with self.assertRaisesRegex(ValueError, "authentication capability"):
            verify_git_provenance(original, original_manifest, authenticate_origin=None)
        for attack in (
            "repository",
            "tree",
            "base",
            "head",
            "receipt",
            "commit",
            "missing",
            "extra",
            "order",
            "incomplete-tree",
            "mode",
        ):
            proof, manifest = copy.deepcopy(original), copy.deepcopy(original_manifest)
            if attack == "repository":
                proof["origin"]["repository_id"] += 1
            elif attack in {"tree", "base", "head"}:
                proof["origin"][attack] = "f" * 40
            elif attack == "receipt":
                proof["origin"]["acceptance"]["receipt_sha256"] = "f" * 64
            elif attack == "commit":
                proof["commits"][0]["object"] += "AAAA"
            elif attack == "missing":
                proof["commits"].pop(0)
            elif attack == "extra":
                proof["commits"].insert(0, copy.deepcopy(proof["commits"][0]))
            elif attack == "order":
                proof["commits"].reverse()
            elif attack == "incomplete-tree":
                manifest["files"][0]["path"] = "other.py"
            else:
                manifest["files"][0]["mode"] = "100755"
            with self.subTest(attack=attack), self.assertRaises(ValueError):
                verify_git_provenance(proof, manifest, authenticate_origin=lambda: authority)

    def test_real_acquisition_independent_rebuild_offline_install_and_cache_preservation(self):
        import json
        import subprocess
        from unittest.mock import patch

        from agent_protocol.source import acquire_git_source, verify_installation

        with tempfile.TemporaryDirectory(prefix="protocol-git-source-") as temporary:
            root = Path(temporary) / "source"
            root.mkdir()

            def git(*args, input=None):
                return (
                    subprocess.check_output(
                        [
                            "git",
                            "-c",
                            "user.name=Synthetic",
                            "-c",
                            "user.email=test@example.invalid",
                            "-C",
                            str(root),
                            *args,
                        ],
                        input=input,
                        stderr=subprocess.PIPE,
                    )
                    .decode()
                    .strip()
                )

            git("init", "--initial-branch=main")
            (root / "src").mkdir()
            (root / "src/example.py").write_bytes(b"base\n")
            registry_dir = root / ".github/agent-protocol"
            registry_dir.mkdir(parents=True)
            paths = [".github/agent-protocol/bootstrap.json", "src/example.py"]
            (registry_dir / "bootstrap.json").write_text(
                json.dumps({"paths": paths, "modes": dict.fromkeys(paths, "100644")}),
                encoding="utf-8",
            )
            git("add", ".")
            git("commit", "-m", "base")
            base = git("rev-parse", "HEAD")
            (root / "src/example.py").write_bytes(b"accepted source\n")
            git("add", ".")
            git("commit", "-m", "source")
            head, tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")
            revision = git("commit-tree", tree, "-p", base, "-p", head, input=b"normal merge\n")
            git("update-ref", "refs/heads/main", revision)
            _data, _manifest, synthetic = git_fixture()
            origin = {
                **synthetic["origin"],
                "revision": revision,
                "tree": tree,
                "base": base,
                "head": head,
            }
            authority = copy.deepcopy(origin)
            output = Path(temporary) / "first"
            first = acquire_git_source(root, output, origin, authenticate_origin=lambda: authority)
            clone = Path(temporary) / "independent"
            subprocess.check_output(
                ["git", "clone", "--no-local", str(root), str(clone)], stderr=subprocess.PIPE
            )
            second_dir = Path(temporary) / "second"
            second = acquire_git_source(
                clone, second_dir, origin, authenticate_origin=lambda: authority
            )
            self.assertEqual(first["manifest"], second["manifest"])
            self.assertEqual(
                {p.name: p.read_bytes() for p in output.iterdir()},
                {p.name: p.read_bytes() for p in second_dir.iterdir()},
            )
            with patch("subprocess.check_output", side_effect=AssertionError("offline")):
                checked = verify_installation(
                    first,
                    revision=revision,
                    distribution_root=root,
                    source_root=root / "src",
                    authenticate_origin=lambda: authority,
                )
            self.assertEqual(checked["kind"], "CANONICAL_GIT")
            with self.assertRaisesRegex(ValueError, "authentication capability"):
                verify_installation(
                    first, revision=revision, distribution_root=root, source_root=root / "src"
                )
            with self.assertRaisesRegex(ValueError, "independent host authority"):
                verify_installation(
                    first,
                    revision=revision,
                    distribution_root=root,
                    source_root=root / "src",
                    authenticate_origin=lambda: {**authority, "tree": "f" * 40},
                )
            self.assertEqual(
                acquire_git_source(root, output, origin, authenticate_origin=lambda: authority),
                first,
            )
            damaged = output / "source.tar.gz"
            damaged.write_bytes(b"original corrupt cache")
            with self.assertRaisesRegex(ValueError, "Altered Git cache preserved"):
                acquire_git_source(root, output, origin, authenticate_origin=lambda: authority)
            self.assertEqual(damaged.read_bytes(), b"original corrupt cache")
            git("replace", head, base)
            with self.assertRaisesRegex(ValueError, "Replaced source history"):
                acquire_git_source(
                    root, Path(temporary) / "refused", origin, authenticate_origin=lambda: authority
                )


if __name__ == "__main__":
    unittest.main()
