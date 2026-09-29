import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import copy
import json
import os
import subprocess
import unittest
from datetime import UTC, datetime

from agent_protocol.cli import dispatch

ROOT = Path(__file__).resolve().parents[1]


class CLITests(unittest.TestCase):
    def test_write_commands_cannot_accept_authority_from_request_json(self):
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
        for command in ("start", "integrate", "reconcile-not-applied", "close"):
            result = subprocess.run(
                [sys.executable, "-m", "agent_protocol", command],
                input='{"authority":"candidate-chosen"}',
                text=True,
                capture_output=True,
                env=env,
            )
            with self.subTest(command=command):
                self.assertEqual(result.returncode, 2)
                self.assertIn("Independent operator enrollment required", result.stderr)

    def test_public_cli_and_engine_explain_have_identical_preconditions(self):
        value = json.loads((ROOT / "tests/fixtures/lifecycle.json").read_text())
        value["observation"]["observed_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}

        def invoke(payload):
            return subprocess.run(
                [sys.executable, "-m", "agent_protocol", "explain"],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                env=env,
            )

        result = invoke(value)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), dispatch("explain", value))
        for invalid in ("UNKNOWN", "PRODUCTION"):
            bad = copy.deepcopy(value)
            bad["observation"]["effects"] = invalid
            with self.assertRaises(ValueError):
                dispatch("explain", bad)
            self.assertEqual(invoke(bad).returncode, 2)


if __name__ == "__main__":
    unittest.main()
