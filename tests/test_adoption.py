import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import tempfile
import unittest

from test_source import fixture

from agent_protocol.adoption import assess_migration, plan
from agent_protocol.ledger import digest


class AdoptionTests(unittest.TestCase):
    def test_unmanaged_local_edits_preserved_and_copy_is_not_adoption(self):
        content, manifest = fixture()
        profile = {
            "schema": "agent-protocol-adapter/v2",
            "repository": "example/consumer",
            "repository_id": 17,
            "source_repository": "gabned/agent-protocol",
            "prefix": ".github/agent-protocol/core",
            "entrypoints": ["tools/agent-check"],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target = root / "source", root / "consumer"
            file = source / "src/example.py"
            file.parent.mkdir(parents=True)
            file.write_bytes(content)
            args = {
                "accepted_manifest_digest": digest(manifest),
                "accepted_profile_digest": digest(profile),
                "previous_files": {},
            }
            result = plan(source, target, manifest, profile, **args)
            self.assertEqual(result["adoption"], "REQUIRES_NATIVE_CONFORMANCE")
            copied = target / result["files"][0]["destination"]
            copied.parent.mkdir(parents=True)
            copied.write_bytes(b"unmanaged work")
            with self.assertRaises(ValueError):
                plan(source, target, manifest, profile, **args)
            self.assertEqual(copied.read_bytes(), b"unmanaged work")

    def test_native_vendor_location_requires_independent_profile_acceptance(self):
        content, manifest = fixture()
        profile = {
            "schema": "agent-protocol-adapter/v2",
            "repository": "example/consumer",
            "repository_id": 17,
            "source_repository": "gabned/agent-protocol",
            "prefix": "tools/agent_protocol_core",
            "entrypoints": ["tools/agent-protocol"],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target = root / "source", root / "consumer"
            file = source / "src/example.py"
            file.parent.mkdir(parents=True)
            file.write_bytes(content)
            args = {
                "accepted_manifest_digest": digest(manifest),
                "accepted_profile_digest": digest(profile),
                "previous_files": {},
            }
            result = plan(source, target, manifest, profile, **args)
            self.assertEqual(
                result["files"][0]["destination"],
                "tools/agent_protocol_core/src/example.py",
            )
            changed = {**profile, "prefix": "scripts/agent/core"}
            with self.assertRaisesRegex(ValueError, "profile not accepted"):
                plan(source, target, manifest, changed, **args)
            for prefix in (".GIT/objects", ".agent/core", "../escape"):
                changed = {**profile, "prefix": prefix}
                with self.assertRaises(ValueError):
                    plan(
                        source,
                        target,
                        manifest,
                        changed,
                        **{**args, "accepted_profile_digest": digest(changed)},
                    )
            changed = {**profile, "entrypoints": ["TOOLS/AGENT_PROTOCOL_CORE/wrapper"]}
            with self.assertRaisesRegex(ValueError, "overlap"):
                plan(
                    source,
                    target,
                    manifest,
                    changed,
                    **{**args, "accepted_profile_digest": digest(changed)},
                )

    def test_cache_is_not_a_second_lifecycle_and_owner_is_not_assumed(self):
        value = {
            "schema": "synthetic-legacy/v1",
            "role": "CACHE",
            "owner": "owner-a",
            "state": "ACTIVE",
            "receipt_reference": "synthetic:receipt",
            "receipt_sha256": "a" * 64,
        }
        args = {
            "accepted_validator_result": "PASS",
            "active_owner": "owner-a",
            "coordinated_grant": None,
        }
        self.assertEqual(assess_migration(value, **args)["migration"], "NOT_REQUIRED")
        value["role"] = "AUTHORITATIVE"
        self.assertEqual(assess_migration(value, **args)["migration"], "BLOCKED")
        self.assertEqual(value["state"], "ACTIVE")
        self.assertEqual(value["owner"], "owner-a")


if __name__ == "__main__":
    unittest.main()
