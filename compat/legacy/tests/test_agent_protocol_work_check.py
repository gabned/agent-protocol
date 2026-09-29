"""Process/log conformance with explicitly synthetic local scripts, never app CI."""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import agent_protocol_work_check as runner
import agent_protocol_work_source as source


class PortableCheckTests(unittest.TestCase):
    def test_collector_conformance_in_provided_node_runtime(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Work collector conformance requires the provided Node runtime")
        candidates = [Path(__file__).with_name(name) for name in (
            "test_agent_protocol_work_collect.mjs", "agent_protocol_work_collect_test.mjs",
        )]
        present = [path for path in candidates if path.is_file()]
        self.assertEqual(len(present), 1, "one repository-local collector suite is required")
        test_file = present[0]
        result = subprocess.run(
            [node, "--test", str(test_file)],
            capture_output=True, text=True, timeout=120, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unsupported_host_fails_before_execution_or_output_creation(self):
        root = Path("unused-synthetic-path")
        with (
            patch.object(runner, "os", SimpleNamespace(name="nt")),
            self.assertRaisesRegex(source.EvidenceError, "POSIX"),
        ):
            runner.run_check(root, root, root, root, workstream="PROTOCOL", suite="FULL")


class WindowsShardContractTests(unittest.TestCase):
    """Synthetic receipts exercise the independent gate, never qualify app CI."""

    def fixture(self, node_count=4):
        expected = {"commit": "a" * 40, "tree": "b" * 40,
                    "run_id": "1234", "run_attempt": "1", "event": "pull_request"}
        identity = {**expected, "platform": "win32", "python": "3.12.10"}
        cases = []
        for index in range(node_count):
            descriptor = {"parent": f"tests/test_synthetic_{index}.py",
                          "originalname": "test_one", "indices": [["payload", 0]]}
            cases.append({"id": source.digest(descriptor), "descriptor": descriptor,
                          "raw_nodeid": f"tests/test_synthetic_{index}.py::test_one[synthetic]"})
        nodes = [case["id"] for case in cases]

        def record(mode, shard=None):
            selected = nodes if mode == "inventory" else nodes[shard::4]
            outcomes = {node: {"setup": "passed", "call": "passed", "teardown": "passed"}
                        for node in selected} if mode == "shard" else {}
            return {"schema": "agent-windows-ci-pytest/v2", "identity": deepcopy(identity),
                    "mode": mode, "shard": shard, "inventory": list(nodes),
                    "selected": list(selected), "outcomes": outcomes,
                    "cases": deepcopy(cases), "exit_code": 0, "errors": []}

        groups = [{"schema": "agent-windows-ci-group/v1", "identity": deepcopy(identity),
                   "group": group, "inventory": record("inventory"),
                   "shards": [record("shard", index) for index in (2 * group, 2 * group + 1)],
                   "timed_out": False, "exit_code": 0, "timeout_seconds": 540,
                   "duration_seconds": 200}
                  for group in range(2)]
        return groups, expected

    def assert_rejected(self, mutate):
        groups, expected = self.fixture()
        mutate(groups)
        with self.assertRaises(source.EvidenceError):
            runner.verify_windows_reports(groups, expected)

    def test_complete_union_preserves_pass_call_skip_and_setup_skip(self):
        groups, expected = self.fixture()
        call_skip = groups[0]["shards"][1]
        call_skip["outcomes"][call_skip["selected"][0]]["call"] = "skipped"
        setup_skip = groups[1]["shards"][0]
        setup_skip["outcomes"][setup_skip["selected"][0]] = {
            "setup": "skipped", "teardown": "passed"}
        result = runner.verify_windows_reports(groups, expected)
        self.assertEqual(result["result"], "PASS")
        self.assertEqual(result["node_count"], 4)
        self.assertEqual(result["shard_count"], 4)

    def test_empty_shard_is_valid_only_with_nonempty_complete_global_inventory(self):
        groups, expected = self.fixture(node_count=2)
        self.assertEqual(groups[1]["shards"][0]["selected"], [])
        self.assertEqual(groups[1]["shards"][1]["outcomes"], {})
        self.assertEqual(runner.verify_windows_reports(groups, expected)["node_count"], 2)
        groups, expected = self.fixture(node_count=0)
        with self.assertRaises(source.EvidenceError):
            runner.verify_windows_reports(groups, expected)

    def test_missing_duplicate_and_wrong_group_or_shard_cannot_form_a_pass(self):
        mutations = {
            "missing group": lambda gs: gs.pop(),
            "duplicate group": lambda gs: gs.__setitem__(1, deepcopy(gs[0])),
            "unknown group": lambda gs: gs[1].__setitem__("group", 2),
            "missing shard": lambda gs: gs[0]["shards"].pop(),
            "duplicate shard": lambda gs: gs[0]["shards"].__setitem__(1,
                                                deepcopy(gs[0]["shards"][0])),
            "unknown shard": lambda gs: gs[1]["shards"][1].__setitem__("shard", 4),
            "wrong runner group": lambda gs: gs[0]["shards"].__setitem__(0,
                                                deepcopy(gs[1]["shards"][0])),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                self.assert_rejected(mutate)

    def test_inventory_and_execution_must_be_exact_disjoint_complete_sets(self):
        def remove_execution(groups):
            worker = groups[0]["shards"][0]
            worker["selected"] = []
            worker["outcomes"] = {}

        def overlap(groups):
            donor, worker = groups[0]["shards"]
            worker["selected"] += donor["selected"]
            worker["outcomes"].update(deepcopy(donor["outcomes"]))

        def invented_node(groups):
            worker = groups[0]["shards"][0]
            worker["outcomes"]["tests/test_not_collected.py::test_one"] = {
                "setup": "passed", "call": "passed", "teardown": "passed"}

        mutations = {
            "assigned node never executed": lambda gs: gs[0]["shards"][0]["outcomes"].clear(),
            "missing from union": remove_execution,
            "overlapping shards": overlap,
            "invented result": invented_node,
            "duplicate selected node": lambda gs: gs[0]["shards"][0]["selected"].extend(
                                                gs[0]["shards"][0]["selected"]),
            "duplicate collected node": lambda gs: gs[0]["inventory"]["inventory"].append(
                                                gs[0]["inventory"]["inventory"][0]),
            "worker collected less": lambda gs: gs[0]["shards"][0]["inventory"].pop(),
            "runner collected less": lambda gs: gs[1]["inventory"]["inventory"].pop(),
            "missing independent inventory": lambda gs: gs[0].__setitem__("inventory", None),
            "malformed independent inventory": lambda gs: gs[0].__setitem__("inventory", []),
            "inventory has deselection": lambda gs: gs[0]["inventory"]["selected"].pop(),
            "inventory reported execution": lambda gs: gs[0]["inventory"].__setitem__(
                "outcomes", deepcopy(gs[0]["shards"][0]["outcomes"])),
            "wrong worker mode": lambda gs: gs[0]["shards"][0].__setitem__("mode", "inventory"),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                self.assert_rejected(mutate)

    def test_duration_must_prove_completion_before_the_unchanged_deadline(self):
        for duration in (None, float("nan"), float("inf"), 540, False, -1):
            with self.subTest(duration=duration):
                self.assert_rejected(
                    lambda gs, value=duration: gs[0].__setitem__("duration_seconds", value))
        self.assert_rejected(lambda gs: gs[0].pop("duration_seconds"))

    def test_case_catalog_is_complete_canonical_and_collision_free(self):
        mutations = {
            "missing catalog": lambda gs: gs[0]["inventory"].pop("cases"),
            "missing case": lambda gs: gs[0]["inventory"]["cases"].pop(),
            "duplicate case": lambda gs: gs[0]["inventory"]["cases"].append(
                deepcopy(gs[0]["inventory"]["cases"][0])),
            "duplicate raw node": lambda gs: gs[0]["inventory"]["cases"][1].__setitem__(
                "raw_nodeid", gs[0]["inventory"]["cases"][0]["raw_nodeid"]),
            "wrong digest": lambda gs: gs[0]["inventory"]["cases"][0].__setitem__("id", "f" * 64),
            "altered coordinate": lambda gs: gs[0]["inventory"]["cases"][0][
                "descriptor"].__setitem__("indices", [["payload", 1]]),
            "boolean coordinate": lambda gs: gs[0]["inventory"]["cases"][0][
                "descriptor"].__setitem__("indices", [["payload", False]]),
            "unsorted coordinates": lambda gs: gs[0]["inventory"]["cases"][0][
                "descriptor"].__setitem__("indices", [["z", 0], ["a", 0]]),
            "missing raw diagnostic": lambda gs: gs[0]["inventory"]["cases"][0].pop("raw_nodeid"),
            "old raw-node schema": lambda gs: gs[0]["inventory"].__setitem__(
                "schema", "agent-windows-ci-pytest/v1"),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                self.assert_rejected(mutate)

    def test_rendered_parameter_labels_can_differ_without_changing_coordinate_coverage(self):
        groups, expected = self.fixture()
        for index, group in enumerate(groups):
            for offset, record in enumerate([group["inventory"], *group["shards"]]):
                for case in record["cases"]:
                    descriptor = case["descriptor"]
                    case["raw_nodeid"] = (f"{descriptor['parent']}::{descriptor['originalname']}"
                                          f"[volatile-rendering-{index}-{offset}]")
        self.assertEqual(runner.verify_windows_reports(groups, expected)["node_count"], 4)

    def test_every_report_binds_exact_source_run_event_os_and_python(self):
        wrong = {"commit": "c" * 40, "tree": "d" * 40, "run_id": "9999",
                 "run_attempt": "2", "event": "push", "platform": "linux",
                 "python": "3.11.10"}
        for location in ("group", "inventory", "shard"):
            for field, value in wrong.items():
                with self.subTest(location=location, field=field):
                    groups, expected = self.fixture()
                    record = (groups[0] if location == "group" else groups[0]["inventory"]
                              if location == "inventory" else groups[0]["shards"][0])
                    record["identity"][field] = value
                    with self.assertRaises(source.EvidenceError):
                        runner.verify_windows_reports(groups, expected)

    def test_unknown_or_failed_exit_timeout_and_errors_never_pass(self):
        for location in ("group", "inventory", "shard"):
            for code in (None, 1, 5, True, "0"):
                with self.subTest(location=location, code=code):
                    groups, expected = self.fixture()
                    record = (groups[0] if location == "group" else groups[0]["inventory"]
                              if location == "inventory" else groups[0]["shards"][0])
                    record["exit_code"] = code
                    with self.assertRaises(source.EvidenceError):
                        runner.verify_windows_reports(groups, expected)
        mutations = {
            "supervisor timeout": lambda gs: gs[0].__setitem__("timed_out", True),
            "unknown supervisor state": lambda gs: gs[0].__setitem__("timed_out", None),
            "larger budget": lambda gs: gs[0].__setitem__("timeout_seconds", 541),
            "collection error": lambda gs: gs[0]["inventory"]["errors"].append("collection"),
            "worker error": lambda gs: gs[0]["shards"][0]["errors"].append("internal"),
            "missing worker exit": lambda gs: gs[0]["shards"][0].pop("exit_code"),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                self.assert_rejected(mutate)

    def test_each_selected_node_requires_valid_complete_nonfailing_phases(self):
        invalid_phases = (
            {}, {"setup": "passed", "call": "passed"},
            {"setup": "passed", "teardown": "passed"},
            {"setup": "failed", "teardown": "passed"},
            {"setup": "passed", "call": "failed", "teardown": "passed"},
            {"setup": "passed", "call": "passed", "teardown": "failed"},
            {"setup": "passed", "call": "unknown", "teardown": "passed"},
            {"setup": "skipped", "call": "passed", "teardown": "passed"},
        )
        for phases in invalid_phases:
            with self.subTest(phases=phases):
                groups, expected = self.fixture()
                worker = groups[0]["shards"][0]
                worker["outcomes"][worker["selected"][0]] = phases
                with self.assertRaises(source.EvidenceError):
                    runner.verify_windows_reports(groups, expected)

    def test_recorder_preserves_duplicate_and_unexpected_phase_errors(self):
        for kind in ("duplicate", "unknown raw", "unselected", "unknown phase"):
            with self.subTest(kind=kind):
                groups, expected = self.fixture()
                worker = groups[0]["shards"][0]
                selected = worker["selected"][0]
                case = next(case for case in worker["cases"] if case["id"] == selected)
                node = case["raw_nodeid"]
                recorder = runner._WindowsRecorder(worker["identity"], "shard", 0)

                def item(case):
                    descriptor = case["descriptor"]
                    return SimpleNamespace(nodeid=case["raw_nodeid"],
                                           parent=SimpleNamespace(nodeid=descriptor["parent"]),
                                           originalname=descriptor["originalname"],
                                           callspec=SimpleNamespace(indices=dict(
                                               descriptor["indices"])))

                recorder.pytest_collection_modifyitems(
                    [item(case) for case in worker["cases"]])
                recorder.pytest_collection_finish(SimpleNamespace(items=[item(case)]))
                for phase in ("setup", "call", "teardown"):
                    recorder.pytest_runtest_logreport(
                        SimpleNamespace(nodeid=node, when=phase, outcome="passed"))
                unexpected = ("tests/test_other.py::test_one" if kind == "unknown raw"
                              else worker["cases"][1]["raw_nodeid"] if kind == "unselected"
                              else node)
                recorder.pytest_runtest_logreport(SimpleNamespace(
                    nodeid=unexpected,
                    when="call" if kind != "unknown phase" else "collection", outcome="passed"))
                record = recorder.record(0)
                self.assertTrue(record["errors"])
                groups[0]["shards"][0] = record
                with self.assertRaises(source.EvidenceError):
                    runner.verify_windows_reports(groups, expected)

    def test_recorder_retains_identity_and_raw_collisions_as_errors(self):
        for collision in ("coordinate", "raw"):
            with self.subTest(collision=collision):
                groups, _ = self.fixture()
                worker = groups[0]["shards"][0]
                descriptor = worker["cases"][0]["descriptor"]
                first = SimpleNamespace(
                    nodeid="tests/test_synthetic.py::test_one[first]",
                    parent=SimpleNamespace(nodeid=descriptor["parent"]),
                    originalname=descriptor["originalname"],
                    callspec=SimpleNamespace(indices={"payload": 0}))
                second = deepcopy(first)
                if collision == "coordinate":
                    second.nodeid = "tests/test_synthetic.py::test_one[second]"
                else:
                    second.callspec.indices["payload"] = 1
                recorder = runner._WindowsRecorder(worker["identity"], "inventory", None)
                recorder.pytest_collection_modifyitems([first, second])
                recorder.pytest_collection_finish(SimpleNamespace(items=[first, second]))
                record = recorder.record(0)
                self.assertEqual(len(record["cases"]), 2)
                self.assertTrue(record["errors"])

    def test_supervisor_runs_inventory_and_exact_pair_with_bounded_cp1252_replay(self):
        groups, expected = self.fixture()
        identity = groups[0]["identity"]
        maximum = 2 * 1024 * 1024
        with tempfile.TemporaryDirectory(prefix="provelume-ci-supervisor-") as temporary:
            root = Path(temporary) / "source"
            root.mkdir()
            for group in (0, 1):
                with self.subTest(group=group):
                    output = Path(temporary) / f"evidence-{group}"
                    commands, environments = [], []

                    class Process:
                        returncode = None
                        pid = 12345

                        def wait(process, timeout):
                            self.assertGreater(timeout, 0)
                            self.assertLessEqual(timeout, 540)
                            process.returncode = 0
                            return 0

                        def poll(process):
                            return process.returncode

                    def launch(command, commands=commands, environments=environments,
                               group=group, **kwargs):
                        mode = command[2]
                        destination = Path(command[command.index("--output") + 1])
                        index = (None if "--shard" not in command
                                 else int(command[command.index("--shard") + 1]))
                        commands.append((mode, index))
                        environments.append(kwargs["env"])
                        self.assertEqual(kwargs["cwd"], root)
                        self.assertEqual(command[0], sys.executable)
                        record = (groups[group]["inventory"] if index is None
                                  else groups[group]["shards"][index % 2])
                        destination.write_text(json.dumps(record))
                        content = "synthetic unicode: 🧊\n".encode()
                        if index is None:
                            content = b"OMITTED_PREFIX" + b"x" * maximum + content
                        kwargs["stdout"].write(content)
                        kwargs["stdout"].flush()
                        return Process()

                    buffer = io.BytesIO()
                    console = io.TextIOWrapper(buffer, encoding="cp1252")
                    with (
                        patch.object(runner.sys, "platform", "win32"),
                        patch.object(runner.sys, "stdout", console),
                        patch.object(runner, "windows_identity", return_value=identity),
                        patch.object(runner.subprocess, "Popen", side_effect=launch),
                    ):
                        code = runner.run_windows_group(root, output, expected, group)
                    console.flush()
                    replay = buffer.getvalue().decode("cp1252")
                    console.close()
                    self.assertEqual(code, 0)
                    self.assertEqual(commands, [("windows-inventory", None),
                                               ("windows-shard", group * 2),
                                               ("windows-shard", group * 2 + 1)])
                    self.assertIn("\\U0001f9ca", replay)
                    self.assertIn("[bounded output; complete log retained in artifact]", replay)
                    self.assertNotIn("OMITTED_PREFIX", replay)
                    self.assertLess(len(replay), maximum + 1000)
                    self.assertTrue((output / f"inventory-{group}.log").read_bytes().startswith(
                        b"OMITTED_PREFIX"))
                    self.assertEqual(len({env["LOCALAPPDATA"] for env in environments}), 3)
                    for environment in environments:
                        self.assertEqual(environment["PYTHONPATH"], os.pathsep.join(
                            (str(root / "core"), str(root), str(root / "tools"))))
                        self.assertEqual(environment["PROVELUME_WINDOWS_SHARD_CHILD"], "1")
                    groups[group] = json.loads((output / f"group-{group}.json").read_text())
            self.assertEqual(runner.verify_windows_reports(groups, expected)["node_count"], 4)


class WindowsShardRecorderTests(unittest.TestCase):
    @staticmethod
    def synthetic_plugin(root):
        """Exercise recorder hooks with real pytest, independently of Product."""
        plugin = root / "core/synthetic_work_shard.py"
        plugin.parent.mkdir(parents=True, exist_ok=True)
        plugin.write_text(
            "import json, os, sys\nfrom pathlib import Path\nimport pytest\n"
            "def pytest_addoption(parser):\n"
            "    parser.addoption('--provelume-shard-index', type=int, default=None)\n"
            "    parser.addoption('--provelume-shard-count', type=int, default=4)\n"
            "def pytest_configure(config):\n"
            "    loaded = {'plugin': str(Path(__file__).resolve()),\n"
            "              'application_modules': sorted(name for name in sys.modules\n"
            "                  if name == 'provelume' or name.startswith('provelume.'))}\n"
            "    Path(os.environ['WORK_FIXTURE_PLUGIN_RECEIPT']).write_text(\n"
            "        json.dumps(loaded), encoding='utf-8')\n"
            "@pytest.hookimpl(trylast=True)\n"
            "def pytest_collection_modifyitems(config, items):\n"
            "    index = config.getoption('--provelume-shard-index')\n"
            "    if index is None:\n        return\n"
            "    count = config.getoption('--provelume-shard-count')\n"
            "    modules = sorted({item.nodeid.split('::', 1)[0] for item in items})\n"
            "    chosen, excluded = [], []\n"
            "    for item in items:\n"
            "        module = item.nodeid.split('::', 1)[0]\n"
            "        target = chosen if modules.index(module) % count == index else excluded\n"
            "        target.append(item)\n"
            "    items[:] = chosen\n"
            "    config.hook.pytest_deselected(items=excluded)\n",
            encoding="utf-8",
        )
        return plugin

    def assert_fixture_plugin(self, receipt, plugin):
        self.assertEqual(json.loads(receipt.read_text(encoding="utf-8")), {
            "plugin": str(plugin.resolve()), "application_modules": [],
        })

    def test_real_pytest_records_complete_collection_execution_skips_and_failure(self):
        root = Path(__file__).resolve().parents[1]
        expected = {"commit": "a" * 40, "tree": "b" * 40,
                    "run_id": "1234", "run_attempt": "1", "event": "pull_request"}
        # Explicitly synthetic identity tests receipt mechanics on any host.
        identity = {**expected, "platform": "win32", "python": "3.12.10"}
        with tempfile.TemporaryDirectory(prefix="provelume-ci-recorder-") as temporary:
            fixture = Path(temporary)
            plugin = self.synthetic_plugin(fixture)
            config = fixture / "pytest.ini"
            config.write_text("[pytest]\naddopts = -p synthetic_work_shard\n", encoding="utf-8")
            for index in range(4):
                (fixture / f"test_synthetic_{index}.py").write_text(
                    "import pytest\ndef test_one():\n    pass\n"
                    "@pytest.mark.skip(reason='synthetic existing skip')\n"
                    "def test_two():\n    pass\n")
            (fixture / "test_synthetic_0.py").write_text(
                "import os\nfrom io import BytesIO\nfrom zipfile import ZipFile, ZipInfo\n"
                "import pytest\ndef _payload(name):\n    stream = BytesIO()\n"
                "    year = int(os.environ['PROVELUME_CI_FIXTURE_ZIP_YEAR'])\n"
                "    with ZipFile(stream, 'w') as archive:\n"
                "        archive.writestr(ZipInfo(name, (year, 1, 1, 0, 0, 0)), b'synthetic')\n"
                "    return stream.getvalue()\n"
                "@pytest.mark.parametrize('payload', [_payload('one'), _payload('two')])\n"
                "def test_one(payload):\n    assert payload.startswith(b'PK')\n    pass\n")
            script = fixture / "record_fixture.py"
            script.write_text(
                "import json,sys\nfrom pathlib import Path\nimport pytest\n"
                "import agent_protocol_work_check as runner\n"
                "identity=json.loads(sys.argv[1])\nmode=sys.argv[2]\n"
                "shard=None if sys.argv[3]=='none' else int(sys.argv[3])\n"
                "output=Path(sys.argv[4])\n"
                "runner._WindowsRecorder.pytest_collection_modifyitems = "
                "pytest.hookimpl(tryfirst=True)("
                "runner._WindowsRecorder.pytest_collection_modifyitems)\n"
                "recorder=runner._WindowsRecorder(identity, mode, shard)\n"
                "code=pytest.main(sys.argv[5:], plugins=[recorder])\n"
                "output.write_text(json.dumps(recorder.record(int(code))))\n"
                "sys.exit(int(code))\n")
            environment = os.environ.copy()
            environment["PYTHONPATH"] = os.pathsep.join(
                (str(fixture / "core"), str(root / "tools")))
            environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
            environment["PYTHONIOENCODING"] = "utf-8"
            environment["PROVELUME_WINDOWS_SHARD_DISABLE"] = "1"
            environment.pop("PROVELUME_WINDOWS_SHARD_FORCE", None)
            environment.pop("PROVELUME_WINDOWS_SHARD_CHILD", None)
            invocation = 0

            def capture(mode, shard=None):
                nonlocal invocation
                invocation += 1
                receipt = fixture / f"plugin-{invocation}.json"
                child_environment = {**environment,
                                     "PROVELUME_CI_FIXTURE_ZIP_YEAR": str(2020 + invocation),
                                     "WORK_FIXTURE_PLUGIN_RECEIPT": str(receipt)}
                output = fixture / f"{mode}-{shard}.json"
                arguments = ["-c", str(config), "--rootdir", str(fixture), "-q", str(fixture)]
                if mode == "inventory":
                    arguments += ["--collect-only"]
                else:
                    arguments += [f"--provelume-shard-index={shard}",
                                  "--provelume-shard-count=4"]
                process = subprocess.run(
                    [sys.executable, str(script), json.dumps(identity), mode,
                     "none" if shard is None else str(shard), str(output), *arguments],
                    cwd=fixture, env=child_environment, capture_output=True, encoding="utf-8",
                    timeout=45, check=False,
                )
                self.assertTrue(output.is_file(), process.stdout + process.stderr)
                self.assert_fixture_plugin(receipt, plugin)
                return json.loads(output.read_text()), process.returncode

            inventory, code = capture("inventory")
            self.assertEqual(code, 0)
            self.assertEqual(len(inventory["inventory"]), 8)
            self.assertEqual(inventory["outcomes"], {})
            shards = []
            for index in range(4):
                record, code = capture("shard", index)
                self.assertEqual(code, 0)
                self.assertEqual(record["inventory"], inventory["inventory"])
                self.assertEqual(set(record["outcomes"]), set(record["selected"]))
                self.assertEqual(len(record["selected"]), 2)
                volatile_raw = {case["id"]: case["raw_nodeid"] for case in record["cases"]
                                if case["descriptor"]["indices"]}
                independent_raw = {case["id"]: case["raw_nodeid"] for case in inventory["cases"]
                                   if case["descriptor"]["indices"]}
                self.assertEqual(set(volatile_raw), set(independent_raw))
                self.assertEqual(len(volatile_raw), 2)
                self.assertTrue(all(raw != independent_raw[key]
                                    for key, raw in volatile_raw.items()))
                shards.append(record)
            groups = [{"schema": "agent-windows-ci-group/v1", "identity": identity,
                       "group": group, "inventory": inventory, "shards": shards[2*group:2*group+2],
                       "timed_out": False, "exit_code": 0, "timeout_seconds": 540,
                       "duration_seconds": 200}
                      for group in range(2)]
            self.assertEqual(runner.verify_windows_reports(groups, expected)["node_count"], 8)
            for index in range(4):
                file = fixture / f"test_synthetic_{index}.py"
                file.write_text(file.read_text().replace("    pass", "    assert False", 1))
            failed, code = capture("shard", 0)
            self.assertEqual(code, 1)
            self.assertTrue(any(phases.get("call") == "failed"
                                for phases in failed["outcomes"].values()))
            groups[0]["shards"][0] = failed
            with self.assertRaises(source.EvidenceError):
                runner.verify_windows_reports(groups, expected)

    def test_real_inventory_entrypoint_uses_supervisor_environment_for_namespace_imports(self):
        source_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="provelume-ci-entrypoint-") as temporary:
            parent = Path(temporary)
            root = parent / "source"
            for directory in ("core", "tools", "scripts", "tests"):
                (root / directory).mkdir(parents=True, exist_ok=True)
            for relative in ("tools/agent_protocol_work_check.py",
                             "tools/agent_protocol_work_source.py"):
                shutil.copyfile(source_root / relative, root / relative)
            plugin = self.synthetic_plugin(root)
            (root / "scripts/synthetic_namespace.py").write_text(
                "VALUE = 'synthetic namespace fixture'\n", encoding="utf-8")
            (root / "pyproject.toml").write_text(
                '[tool.pytest.ini_options]\naddopts = "-p synthetic_work_shard"\n'
                'pythonpath = ["core"]\ntestpaths = ["tests"]\n')
            (root / "tests/test_tools_namespace.py").write_text(
                "from tools.agent_protocol_work_source import SCHEMA\n"
                "def test_tools_namespace():\n    assert SCHEMA == 'agent-work-source/v1'\n")
            (root / "tests/test_scripts_namespace.py").write_text(
                "from scripts.synthetic_namespace import VALUE\n"
                "def test_scripts_namespace():\n"
                "    assert VALUE == 'synthetic namespace fixture'\n")

            def git(*arguments):
                return subprocess.check_output(
                    ["git", "-C", str(root), "-c", "user.name=Synthetic CI test",
                     "-c", "user.email=synthetic@example.invalid", "-c", "commit.gpgsign=false",
                     *arguments], text=True, stderr=subprocess.STDOUT,
                ).strip()

            git("init", "--quiet")
            git("add", ".")
            git("commit", "--quiet", "-m", "synthetic namespace fixture")
            expected = {"commit": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}"),
                        "run_id": "1234", "run_attempt": "1", "event": "push"}
            captured = []

            def capture_environment(command, **kwargs):
                self.assertEqual(command[2], "windows-inventory")
                captured.append(dict(kwargs["env"]))
                raise OSError("synthetic stop after capturing the real child environment")

            with (
                patch.dict(os.environ, {
                    "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                    "WORK_FIXTURE_PLUGIN_RECEIPT": str(parent / "plugin.json"),
                }),
                patch.object(runner.sys, "platform", "win32"),
                patch.object(runner.sys, "stdout", io.StringIO()),
                patch.object(runner, "windows_identity", return_value=expected),
                patch.object(runner.subprocess, "Popen", side_effect=capture_environment),
            ):
                self.assertEqual(runner.run_windows_group(
                    root, parent / "captured-supervisor", expected, 0), 1)
            self.assertEqual(len(captured), 1)
            environment = captured[0]

            def inventory(name, child_environment):
                output = parent / f"{name}.json"
                (parent / "plugin.json").unlink(missing_ok=True)
                process = subprocess.run(
                    [sys.executable, str(root / "tools/agent_protocol_work_check.py"),
                     "windows-inventory", "--root", str(root), "--output", str(output),
                     "--commit", expected["commit"], "--run-id", expected["run_id"],
                     "--run-attempt", expected["run_attempt"], "--event", expected["event"]],
                    cwd=root, env=child_environment, capture_output=True, encoding="utf-8",
                    timeout=45, check=False,
                )
                self.assertTrue(output.is_file(), process.stdout + process.stderr)
                self.assert_fixture_plugin(parent / "plugin.json", plugin)
                return process, json.loads(output.read_text())

            # Reproduce the broken script-entrypoint shape without a root namespace.
            missing_root = dict(environment)
            missing_root["PYTHONPATH"] = os.pathsep.join(
                value for value in environment["PYTHONPATH"].split(os.pathsep)
                if Path(value).resolve() != root.resolve())
            broken, broken_record = inventory("missing-root", missing_root)
            self.assertEqual(broken.returncode, 2, broken.stdout + broken.stderr)
            self.assertEqual(broken_record["exit_code"], 2)
            self.assertIn("No module named 'scripts'", broken.stdout + broken.stderr)
            self.assertIn("No module named 'tools'", broken.stdout + broken.stderr)
            # The success must use the actual supervisor environment, without repairing it here.
            passed, record = inventory("supervisor-environment", environment)
            self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)
            self.assertEqual(record["exit_code"], 0)
            self.assertEqual({case["raw_nodeid"] for case in record["cases"]}, {
                "tests/test_tools_namespace.py::test_tools_namespace",
                "tests/test_scripts_namespace.py::test_scripts_namespace",
            })
            self.assertEqual(set(record["inventory"]), {case["id"] for case in record["cases"]})
            self.assertEqual(record["selected"], record["inventory"])
            self.assertEqual(record["outcomes"], {})


@unittest.skipUnless(os.name == "posix", "POSIX process supervisor conformance")
class CheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.parent = Path(self.tmp.name)
        self.base = self.parent / "base"
        (self.base / "tools").mkdir(parents=True)
        (self.base / "tools/agent-check").write_text(
            "echo synthetic-out\necho synthetic-error >&2\nexit 7\n"
        )
        entries = source.inventory(self.base)
        tree = source.tree_identity(entries, verify=True)
        self.snapshot = self.parent / "snapshot.json"
        self.snapshot.write_text(
            json.dumps(
                {
                    "schema": source.SCHEMA,
                    "repository": "brickms/brickms",
                    "commit_sha": "a" * 40,
                    "tree_sha": tree,
                    "tree": {"sha": tree, "truncated": False, "tree": list(entries.values())},
                }
            )
        )
        self.candidate = self.parent / "candidate"
        shutil.copytree(self.base, self.candidate)

    def run_fixture(self, **kwargs):
        return runner.run_check(
            self.snapshot,
            self.base,
            self.candidate,
            self.parent / "result",
            workstream="PROTOCOL",
            suite="PROTOCOL_ONLY",
            **kwargs,
        )

    def test_real_nonzero_exit_and_both_streams_preserved(self):
        result, code = self.run_fixture()
        self.assertEqual((result["exit_code"], code), (7, 2))
        self.assertEqual((self.parent / "result/stdout.log").read_text(), "synthetic-out\n")
        self.assertEqual((self.parent / "result/stderr.log").read_text(), "synthetic-error\n")
        self.assertFalse(result["push_qualified"])

    def test_checkpoint_only_requires_full_and_closed_paths_before_launch(self):
        for suite in ("PROTOCOL_ONLY", "FULL"):
            with self.subTest(suite=suite), self.assertRaises(source.EvidenceError):
                runner.run_check(self.snapshot, self.base, self.candidate,
                                 self.parent / "result", workstream="CHECKPOINT_ONLY", suite=suite)
            self.assertFalse((self.parent / "result").exists())
        (self.candidate / "AGENT_STATUS.md").write_text("synthetic checkpoint\n")
        (self.candidate / "application.py").write_text("synthetic product\n")
        with self.assertRaisesRegex(source.EvidenceError, "only checkpoint"):
            runner.run_check(self.snapshot, self.base, self.candidate,
                             self.parent / "result", workstream="CHECKPOINT_ONLY", suite="FULL")
        self.assertFalse((self.parent / "result").exists())

    def test_checkpoint_only_preserves_local_failure_and_exact_class(self):
        (self.candidate / "AGENT_STATUS.md").write_text("synthetic checkpoint\n")
        result, code = runner.run_check(self.snapshot, self.base, self.candidate,
                                       self.parent / "result",
                                       workstream="CHECKPOINT_ONLY", suite="FULL")
        self.assertEqual((result["exit_code"], code), (7, 2))
        self.assertIn("CHECKPOINT_ONLY", result["command"])
        self.assertEqual(result["command"][-1], "--full")
        self.assertTrue(result["source_unchanged"])
        self.assertFalse(result["push_qualified"])

    def test_checkpoint_only_cannot_adopt_vendor(self):
        with self.assertRaisesRegex(source.EvidenceError, "requires PROTOCOL"):
            runner.run_check(self.snapshot, self.base, self.candidate,
                             self.parent / "result", workstream="CHECKPOINT_ONLY", suite="FULL",
                             canonical_snapshot=self.snapshot, canonical_anchor=self.snapshot)
        self.assertFalse((self.parent / "result").exists())

    def test_vendor_update_requires_both_independent_inputs(self):
        with self.assertRaisesRegex(source.EvidenceError, "supplied together"):
            self.run_fixture(canonical_snapshot=self.snapshot)
        self.assertFalse((self.parent / "result").exists())

    def canonical_fixture(self):
        snapshot = json.loads(self.snapshot.read_text())
        snapshot["repository"] = "gabned/provelume"
        canonical = self.parent / "canonical.json"
        canonical.write_text(json.dumps(snapshot))
        stamp = datetime.now(UTC).isoformat()
        prefix = "https://api.github.com/repos/gabned/provelume"
        ref = {"ref": "refs/heads/main",
               "object": {"type": "commit", "sha": snapshot["commit_sha"]}}
        def observation(path, response):
            return {"url": prefix + path, "observed_at": stamp, "response": response}
        anchor = {"default_branch": "main",
            "repository": observation("", {"full_name": snapshot["repository"],
                                           "default_branch": "main"}),
            "before": observation("/git/ref/heads/main", ref),
            "commit": observation("/git/commits/" + snapshot["commit_sha"],
                {"sha": snapshot["commit_sha"], "tree": {"sha": snapshot["tree_sha"]}}),
            "after": observation("/git/ref/heads/main", ref)}
        anchor_path = self.parent / "canonical-anchor.json"
        anchor_path.write_text(json.dumps(anchor))
        return canonical, anchor_path

    def test_canonical_identity_and_inputs_are_required_to_verify_success(self):
        canonical, anchor = self.canonical_fixture()
        (self.candidate / "tools/agent-check").write_text("echo canonical-fixture\nexit 0\n")
        result, code = self.run_fixture(canonical_snapshot=canonical, canonical_anchor=anchor)
        self.assertEqual(code, 0)
        self.assertEqual(result["canonical_source"]["repository"], "gabned/provelume")
        delta = source.candidate_delta(source.read_json(self.snapshot), self.base, self.candidate,
                                       "brickms/brickms", "a" * 40)
        args = {"suite": "PROTOCOL_ONLY", "command_digest": result["command_digest"]}
        with self.assertRaisesRegex(source.EvidenceError, "retained independent inputs"):
            source.verify_receipt(result, delta, **args)
        source.verify_receipt(result, delta, canonical_snapshot=canonical,
                              canonical_anchor=anchor, **args)
        changed = json.loads(anchor.read_text())
        changed["extra_observation"] = "changed after execution"
        anchor.write_text(json.dumps(changed))
        with self.assertRaisesRegex(source.EvidenceError, "input identity changed"):
            source.verify_receipt(result, delta, canonical_snapshot=canonical,
                                  canonical_anchor=anchor, **args)
        canonical.unlink()
        with self.assertRaises(OSError):
            source.verify_receipt(result, delta, canonical_snapshot=canonical,
                                  canonical_anchor=anchor, **args)

    def test_canonical_inputs_cannot_change_during_a_successful_child(self):
        import shlex
        canonical, anchor = self.canonical_fixture()
        (self.candidate / "tools/agent-check").write_text(
            "printf '{}' > " + shlex.quote(str(anchor)) + "\nexit 0\n")
        result, code = self.run_fixture(canonical_snapshot=canonical, canonical_anchor=anchor)
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(code, 2)
        self.assertIsNotNone(result["source_error"])

    def test_vendor_update_rejects_noncanonical_repository(self):
        with self.assertRaisesRegex(source.EvidenceError, "canonical vendor repository"):
            self.run_fixture(canonical_snapshot=self.snapshot, canonical_anchor=self.snapshot)
        self.assertFalse((self.parent / "result").exists())

    def test_product_cannot_select_protocol_vendor_adoption(self):
        with self.assertRaisesRegex(source.EvidenceError, "requires PROTOCOL"):
            runner.run_check(
                self.snapshot, self.base, self.candidate, self.parent / "result",
                workstream="PRODUCT", suite="FULL", canonical_snapshot=self.snapshot,
                canonical_anchor=self.snapshot,
            )
        self.assertFalse((self.parent / "result").exists())

    def test_successful_child_cannot_hide_source_change(self):
        (self.candidate / "tools/agent-check").write_text("echo changed > new-file\nexit 0\n")
        result, code = self.run_fixture()
        self.assertEqual(result["exit_code"], 0)
        self.assertFalse(result["source_unchanged"])
        self.assertEqual(code, 2)

    def test_previous_output_is_preserved(self):
        (self.parent / "result").mkdir()
        (self.parent / "result/old").write_text("retained")
        with self.assertRaises(source.EvidenceError):
            self.run_fixture()
        self.assertEqual((self.parent / "result/old").read_text(), "retained")

    def test_external_adapter_cannot_be_candidate_controlled(self):
        with self.assertRaisesRegex(source.EvidenceError, "outside source directories"):
            self.run_fixture(adapter_root=self.candidate)
        self.assertFalse((self.parent / "result").exists())

    def test_external_adapter_is_passed_explicitly_to_local_guard(self):
        external = self.parent / "canonical"
        external.mkdir()
        result, code = self.run_fixture(adapter_root=external)
        at = result["command"].index("--work-tools")
        self.assertEqual(result["command"][at + 1], str(external.resolve()))
        self.assertEqual((result["exit_code"], code), (7, 2))

    def test_evidence_cannot_pollute_source(self):
        with self.assertRaises(source.EvidenceError):
            runner.run_check(
                self.snapshot,
                self.base,
                self.candidate,
                self.candidate / "result",
                workstream="PROTOCOL",
                suite="PROTOCOL_ONLY",
            )

    def test_timeout_records_real_terminal_code(self):
        (self.candidate / "tools/agent-check").write_text("sleep 10\n")
        result, code = self.run_fixture(timeout=1)
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["exit_code"], -15)
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
