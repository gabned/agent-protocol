"""Synthetic Protocol conformance; no repository, application or GitHub writes."""

import base64
import copy
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "adapter", Path(__file__).resolve().parents[1] / "tools/agent_protocol_work_source.py"
)
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


class PortableContractTests(unittest.TestCase):
    def test_known_git_vectors(self):
        self.assertEqual(
            adapter.object_sha("blob", b"hello\n"), "ce013625030ba8dba906f756967f9e9ca394464a"
        )
        self.assertEqual(
            adapter.tree_identity({}, verify=True), "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
        )

    def test_unsupported_host_cannot_infer_modes_or_materialize(self):
        root = Path("unused-synthetic-path")
        with patch.object(adapter, "os", SimpleNamespace(name="nt")):
            with self.assertRaisesRegex(adapter.EvidenceError, "POSIX"):
                adapter.inventory(root)
            with self.assertRaisesRegex(adapter.EvidenceError, "POSIX"):
                adapter.materialize({}, root, root, "example/public", "a" * 40)

    def test_empty_tree_integrity_is_portable(self):
        sha = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
        snapshot = {
            "schema": adapter.SCHEMA,
            "repository": "example/public",
            "commit_sha": "a" * 40,
            "tree_sha": sha,
            "tree": {"sha": sha, "truncated": False, "tree": []},
        }
        self.assertEqual(adapter.validate_snapshot(snapshot, "example/public", "a" * 40), {})

    def test_nested_empty_tree_is_an_explicit_capability_gap(self):
        entries = {"empty": {"path": "empty", "mode": "040000", "type": "tree",
                             "sha": "4b825dc642cb6eb9a060e54bf8d69288fbee4904"}}
        tree = adapter.tree_identity(entries, verify=True)
        snapshot = {"schema": adapter.SCHEMA, "repository": "example/public",
                    "commit_sha": "a" * 40, "tree_sha": tree,
                    "tree": {"sha": tree, "truncated": False, "tree": list(entries.values())}}
        with self.assertRaisesRegex(adapter.EvidenceError, "empty source subtrees"):
            adapter.validate_snapshot(snapshot, "example/public", "a" * 40)


# Only the POSIX materializer is supported. Windows still verifies the portable
# object contract above and proves that unsupported mode inference fails closed.
@unittest.skipUnless(os.name == "posix", "POSIX source materializer conformance")
class SourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.parent = Path(self.tmp.name)
        self.root = self.parent / "source"
        self.root.mkdir()
        (self.root / "tools").mkdir()
        (self.root / "tools/run").write_bytes(b"#!/bin/sh\nexit 0\n")
        (self.root / "tools/run").chmod(0o700)
        (self.root / "hello.txt").write_bytes(b"hello\n")
        (self.root / "hello.txt").chmod(0o600)
        self.repo = "example/public"
        self.commit = "a" * 40
        self.refresh()

    def refresh(self):
        self.entries = adapter.inventory(self.root)
        sha = adapter.tree_identity(self.entries, verify=True)
        self.snapshot = {
            "schema": adapter.SCHEMA,
            "repository": self.repo,
            "commit_sha": self.commit,
            "tree_sha": sha,
            "tree": {"sha": sha, "truncated": False, "tree": list(self.entries.values())},
        }

    def verify(self):
        return adapter.verify_source(self.snapshot, self.root, self.repo, self.commit)

    def blocked(self):
        with self.assertRaises(adapter.EvidenceError):
            self.verify()

    def test_exact_snapshot(self):
        result = self.verify()
        self.assertEqual(result["files"], 2)
        self.assertFalse(result["push_qualified"])
        self.assertFalse(result["application_checks_run"])

    def test_restrictive_permissions_preserved(self):
        self.assertEqual(self.entries["tools/run"]["mode"], "100755")
        self.verify()
        self.assertEqual((self.root / "tools/run").stat().st_mode & 0o777, 0o700)

    def test_git_owner_bit_only(self):
        (self.root / "hello.txt").chmod(0o610)
        self.verify()

    def test_changed_file(self):
        (self.root / "hello.txt").write_text("changed")
        self.blocked()

    def test_changed_mode(self):
        (self.root / "tools/run").chmod(0o600)
        self.blocked()

    def test_missing_file(self):
        (self.root / "hello.txt").unlink()
        self.blocked()

    def test_extra_file(self):
        (self.root / "extra").write_text("extra")
        self.blocked()

    def test_extra_empty_directory(self):
        (self.root / "extra").mkdir()
        self.blocked()

    def test_empty_directory_changes_cannot_claim_complete_delta(self):
        candidate = self.parent / "candidate"
        shutil.copytree(self.root, candidate)
        empty = candidate / "empty"
        empty.mkdir()
        with self.assertRaisesRegex(adapter.EvidenceError, "empty source subtrees"):
            adapter.candidate_delta(self.snapshot, self.root, candidate, self.repo, self.commit)
        empty.rename(candidate / "renamed-empty")
        with self.assertRaisesRegex(adapter.EvidenceError, "empty source subtrees"):
            adapter.candidate_delta(self.snapshot, self.root, candidate, self.repo, self.commit)
        (candidate / "renamed-empty").rmdir()
        (self.root / "empty").mkdir()
        entries = copy.deepcopy(self.entries)
        entries["empty"] = {"path": "empty", "type": "tree", "mode": "040000",
                            "sha": "4b825dc642cb6eb9a060e54bf8d69288fbee4904"}
        tree = adapter.tree_identity(entries, verify=True)
        snapshot = copy.deepcopy(self.snapshot)
        snapshot["tree_sha"] = snapshot["tree"]["sha"] = tree
        snapshot["tree"]["tree"] = list(entries.values())
        with self.assertRaisesRegex(adapter.EvidenceError, "empty source subtrees"):
            adapter.candidate_delta(snapshot, self.root, candidate, self.repo, self.commit)

    def test_no_implicit_ignored_directory(self):
        (self.root / ".agent").mkdir()
        self.blocked()

    def test_git_metadata_is_rejected_in_manifest(self):
        self.snapshot["tree"]["tree"][0]["path"] = ".git/config"
        self.blocked()

    def test_symlink_file(self):
        (self.root / "hello.txt").unlink()
        (self.root / "hello.txt").symlink_to(self.parent / "outside")
        self.blocked()

    def test_symlink_directory(self):
        (self.root / "alias").symlink_to(self.parent, target_is_directory=True)
        self.blocked()

    def test_symlink_root(self):
        alias = self.parent / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(adapter.EvidenceError):
            adapter.verify_source(self.snapshot, alias, self.repo, self.commit)

    def test_lfs_is_explicit_gap(self):
        (self.root / "hello.txt").write_text(
            "version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 1\n"
        )
        self.blocked()

    def test_truncated_tree(self):
        self.snapshot["tree"]["truncated"] = True
        self.blocked()

    def test_absent_complete_flag(self):
        del self.snapshot["tree"]["truncated"]
        self.blocked()

    def test_root_hash_mismatch(self):
        self.snapshot["tree_sha"] = self.snapshot["tree"]["sha"] = "b" * 40
        self.blocked()

    def test_subtree_hash_mismatch(self):
        next(x for x in self.snapshot["tree"]["tree"] if x["type"] == "tree")["sha"] = "b" * 40
        self.blocked()

    def test_omitted_subtree_content(self):
        self.snapshot["tree"]["tree"] = [
            x for x in self.snapshot["tree"]["tree"] if x["path"] != "tools/run"
        ]
        self.blocked()

    def test_duplicate_path(self):
        self.snapshot["tree"]["tree"].append(self.snapshot["tree"]["tree"][0])
        self.blocked()

    def test_duplicate_json_key(self):
        with self.assertRaises(adapter.EvidenceError):
            json.loads('{"sha":1,"sha":2}', object_pairs_hook=adapter.unique_object)

    def test_missing_parent(self):
        self.snapshot["tree"]["tree"] = [
            x for x in self.snapshot["tree"]["tree"] if x["path"] != "tools"
        ]
        self.blocked()

    def test_invalid_paths(self):
        for name in ("/root", "a/../b", "a/./b", "a//b", "a\\b", "a\0b", ".GiT/index", ""):
            with self.subTest(path=repr(name)), self.assertRaises(adapter.EvidenceError):
                adapter.valid_path(name)

    def test_whitespace_and_unicode_names(self):
        (self.root / "à file\nname.txt").write_text("source")
        self.refresh()
        self.verify()

    def test_unsupported_modes(self):
        for mode, kind in [("120000", "blob"), ("160000", "commit")]:
            with self.subTest(mode=mode), self.assertRaises(adapter.EvidenceError):
                adapter.validate_entries(
                    [{"path": "link", "mode": mode, "type": kind, "sha": "a" * 40, "size": 0}]
                )

    def test_wrong_repository_and_commit(self):
        for repo, commit in [("other/public", self.commit), (self.repo, "b" * 40)]:
            with self.assertRaises(adapter.EvidenceError):
                adapter.verify_source(self.snapshot, self.root, repo, commit)

    def test_lossless_binary_blob(self):
        data = bytes(range(256))
        response = {
            "encoding": "base64",
            "content": base64.b64encode(data).decode(),
            "size": len(data),
            "sha": adapter.object_sha("blob", data),
        }
        self.assertEqual(adapter.decode_blob(response), data)
        for key, value in [
            ("encoding", "utf-8"),
            ("size", 2),
            ("sha", "a" * 40),
            ("content", "!!!!"),
        ]:
            with self.subTest(key=key), self.assertRaises(adapter.EvidenceError):
                adapter.decode_blob({**response, key: value})

    def test_materialize_new_directory_preserves_previous(self):
        cache = self.parent / "cache"
        cache.mkdir()
        for e in self.entries.values():
            if e["type"] == "blob":
                (cache / e["sha"]).write_bytes((self.root / e["path"]).read_bytes())
        dest = adapter.materialize(self.snapshot, cache, self.parent, self.repo, self.commit)
        self.assertNotEqual(dest, self.root)
        adapter.verify_source(self.snapshot, dest, self.repo, self.commit)
        self.verify()

    def test_corrupt_cache_does_not_create_destination(self):
        cache = self.parent / "cache"
        cache.mkdir()
        for e in self.entries.values():
            if e["type"] == "blob":
                (cache / e["sha"]).write_bytes(b"wrong")
        with self.assertRaises(adapter.EvidenceError):
            adapter.materialize(self.snapshot, cache, self.parent, self.repo, self.commit)
        self.assertEqual(list(self.parent.glob("work-source-*")), [])

    def test_complete_delta_add_modify_delete_and_mode(self):
        candidate = self.parent / "candidate"
        shutil.copytree(self.root, candidate)
        (candidate / "hello.txt").unlink()
        (candidate / "tools/run").chmod(0o600)
        (candidate / "new").mkdir()
        (candidate / "new/entry").write_bytes(b"new")
        d = adapter.candidate_delta(self.snapshot, self.root, candidate, self.repo, self.commit)
        self.assertEqual([x["path"] for x in d["changes"]], ["hello.txt", "new/entry", "tools/run"])
        self.assertIsNone(d["candidate_commit_sha"])
        self.assertFalse(d["push_qualified"])

    def test_anchor_drift_staleness_and_identity(self):
        clock = datetime.now(UTC)
        prefix = f"https://api.github.com/repos/{self.repo}"
        ref = {"ref": "refs/heads/main", "object": {"type": "commit", "sha": self.commit}}
        observation = {
            "url": prefix + "/git/ref/heads/main",
            "observed_at": clock.isoformat(),
            "response": ref,
        }
        observations = {
            "default_branch": "main",
            "repository": {
                "url": prefix,
                "observed_at": clock.isoformat(),
                "response": {"full_name": self.repo, "default_branch": "main"},
            },
            "before": copy.deepcopy(observation),
            "after": copy.deepcopy(observation),
            "commit": {
                "url": prefix + "/git/commits/" + self.commit,
                "observed_at": clock.isoformat(),
                "response": {"sha": self.commit, "tree": {"sha": self.snapshot["tree_sha"]}},
            },
        }
        adapter.verify_live_anchor(self.snapshot, observations, now=clock)
        for name in ("repository", "before", "after", "commit"):
            broken = copy.deepcopy(observations)
            broken[name]["observed_at"] = (clock - timedelta(minutes=16)).isoformat()
            with self.subTest(observation=name), self.assertRaises(adapter.EvidenceError):
                adapter.verify_live_anchor(self.snapshot, broken, now=clock)
        broken = copy.deepcopy(observations)
        broken["after"]["response"]["object"]["sha"] = "b" * 40
        with self.assertRaises(adapter.EvidenceError):
            adapter.verify_live_anchor(self.snapshot, broken, now=clock)
        broken = copy.deepcopy(observations)
        broken["commit"]["url"] = prefix + "/git/commits/" + "b" * 40
        with self.assertRaises(adapter.EvidenceError):
            adapter.verify_live_anchor(self.snapshot, broken, now=clock)
        broken = copy.deepcopy(observations)
        broken["repository"]["response"]["default_branch"] = "different-default"
        with self.assertRaisesRegex(adapter.EvidenceError, "default branch mismatch"):
            adapter.verify_live_anchor(self.snapshot, broken, now=clock)

    def test_receipt_cannot_hide_failure_or_source_drift(self):
        delta = {
            "repository": self.repo,
            "base_commit_sha": self.commit,
            "candidate_tree_sha": self.snapshot["tree_sha"],
        }
        receipt = {
            "schema": "agent-work-check/v1",
            **delta,
            "suite": "PROTOCOL",
            "command_digest": "a" * 64,
            "exit_code": 0,
            "source_unchanged": True,
            "push_qualified": False,
            "timed_out": False,
            "launch_error": None,
            "source_error": None,
            "adapter_exit_code": 0,
            "canonical_source": None,
        }
        adapter.verify_receipt(receipt, delta, suite="PROTOCOL", command_digest="a" * 64)
        for key, value in [
            ("exit_code", 1),
            ("exit_code", False),
            ("candidate_tree_sha", "b" * 40),
            ("source_unchanged", False),
            ("push_qualified", True),
            ("suite", "FULL"),
            ("timed_out", True),
            ("adapter_exit_code", 2),
        ]:
            with self.subTest(key=key), self.assertRaises(adapter.EvidenceError):
                adapter.verify_receipt(
                    {**receipt, key: value}, delta, suite="PROTOCOL", command_digest="a" * 64
                )


if __name__ == "__main__":
    unittest.main()
