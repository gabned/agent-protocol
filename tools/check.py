"""Run the independently extracted Protocol conformance, without product imports."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    legacy = ROOT / "compat/legacy"
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTEST_ADDOPTS", None)
    with tempfile.TemporaryDirectory(prefix="ap-") as temporary:
        commands = [
            (
                [
                    sys.executable,
                    "-m",
                    "ruff",
                    "check",
                    "tools",
                    "tests",
                    "compat/legacy/tools",
                    "compat/legacy/tests",
                ],
                ROOT,
            ),
            (
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "-c",
                    "pytest.ini",
                    "--basetemp",
                    str(Path(temporary) / "p"),
                ],
                legacy,
            ),
            (["node", "--test", "tests/test_agent_protocol_work_collect.mjs"], legacy),
            ([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], ROOT),
        ]
        for argv, cwd in commands:
            process = subprocess.run(argv, cwd=cwd, env=env, check=False)
            if process.returncode:
                return process.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
