import importlib.util
import json
from datetime import datetime
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "state.py"
SPEC = importlib.util.spec_from_file_location("state_extensions_under_test", SCRIPT)
state = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(state)


# Each worker imports the real CLI, joins a filesystem start barrier, and widens
# the write window. Without a transaction lock, concurrent writes lose updates.
WORKER = r"""
import importlib.util
from pathlib import Path
import sys
import time

script, root, gate, ready = map(Path, sys.argv[1:5])
arguments = sys.argv[5:]
spec = importlib.util.spec_from_file_location('state_process_under_test', script)
state = importlib.util.module_from_spec(spec)
spec.loader.exec_module(state)
original_write = state.write_json
def delayed_write(*args, **kwargs):
    time.sleep(0.06)
    return original_write(*args, **kwargs)
state.write_json = delayed_write
ready.write_text('ready', encoding='utf-8')
deadline = time.monotonic() + 15
while not gate.exists():
    if time.monotonic() > deadline:
        raise TimeoutError('Test start barrier timed out')
    time.sleep(0.005)
sys.argv = [str(script), '--data-dir', str(root), *arguments]
state.main()
"""


class StateExtensionsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.root = self.directory / "data"

    def tearDown(self):
        self.temp.cleanup()

    def ability(self, identifier="custom.experiment-design"):
        return {
            "id": identifier,
            "name": "实验设计",
            "definition": "为具体决策设计可验证的实验。",
            "observable_behaviors": ["说明对照条件和成功判据。"],
        }

    def case(self, identifier="case-one", ability_id="user_problem"):
        return {
            "schema_version": 1, "case_id": identifier, "title": "隔离案例",
            "owner": "self", "origin": "work", "status": "closed",
            "ability_ids": [ability_id],
            "attempts": [{
                "attempt_id": "attempt-one", "date": "2026-10-04",
                "kind": "independent", "status": "active",
                "user_work": "用户给出真实判断。", "source": "仅用于临时测试",
                "observations": [{"ability_id": ability_id, "status": "supported", "text": "观察到一项具体行为。"}],
            }],
        }

    def put_case(self, identifier="case-one", ability_id="user_problem"):
        value = self.case(identifier, ability_id)
        state.write_json(self.root / "cases" / (identifier + ".json"), value)
        return value

    def cli(self, *arguments):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--data-dir", str(self.root), *arguments],
            capture_output=True, text=True, timeout=20,
        )

    def concurrent_cli(self, arguments):
        gate = self.directory / "start"
        processes = []
        markers = []
        try:
            for index, command in enumerate(arguments):
                ready = self.directory / f"ready-{index}"
                markers.append(ready)
                processes.append(subprocess.Popen(
                    [sys.executable, "-c", WORKER, str(SCRIPT), str(self.root), str(gate), str(ready), *command],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                ))
            deadline = time.monotonic() + 15
            while not all(marker.exists() for marker in markers):
                for process in processes:
                    if process.poll() is not None:
                        output, error = process.communicate()
                        self.fail(f"Worker exited before barrier: {output} {error}")
                if time.monotonic() > deadline:
                    self.fail("Workers did not reach the start barrier")
                time.sleep(0.01)
            gate.write_text("start", encoding="utf-8")
            results = []
            for process in processes:
                output, error = process.communicate(timeout=20)
                self.assertEqual(process.returncode, 0, error)
                results.append(json.loads(output))
            return results
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                process.communicate()

    def test_registration_accepts_case_and_observation(self):
        ability = self.ability()
        self.assertEqual(state.register_ability(self.root, ability)["status"], "created")
        value = self.put_case(ability_id=ability["id"])
        path = self.root / "cases" / "case-one.json"
        self.assertEqual(state.validate_case(value, path), value)
        eligible, ignored = state.eligible_cases(self.root)
        self.assertEqual([item["case_id"] for item in eligible], ["case-one"])
        self.assertEqual(eligible[0]["attempts"][0]["observations"][0]["ability_id"], ability["id"])
        self.assertEqual(ignored, [])

    def test_cli_registration_and_explicit_replacement(self):
        source = self.directory / "ability.json"
        ability = self.ability()
        state.write_json(source, ability)
        result = self.cli("register-ability", "--input", str(source))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "created")
        self.assertEqual(state.register_ability(self.root, ability)["status"], "unchanged")
        changed = {**ability, "definition": "更精确的实验设计定义。"}
        state.write_json(source, changed)
        result = self.cli("register-ability", "--input", str(source))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--replace", result.stderr)
        self.assertEqual(state.load_abilities(self.root)["abilities"], [ability])
        result = self.cli("register-ability", "--input", str(source), "--replace")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "replaced")
        registry = state.load_abilities(self.root)
        self.assertEqual(registry["abilities"], [changed])
        self.assertEqual(registry["history"][0]["previous_definition"], ability)

    def test_replacements_preserve_versions_without_duplicate_history(self):
        original = self.ability()
        state.register_ability(self.root, original)
        self.assertNotIn("history", state.load_abilities(self.root))
        second = {**original, "definition": "第二个完整定义。"}
        third = {**second, "observable_behaviors": ["第三个版本的行为。"]}
        state.register_ability(self.root, second, replace=True)
        first_history = state.load_abilities(self.root)["history"]
        self.assertEqual(len(first_history), 1)
        self.assertEqual(first_history[0]["ability_id"], original["id"])
        self.assertEqual(first_history[0]["previous_definition"], original)
        self.assertIsNotNone(datetime.fromisoformat(first_history[0]["replaced_at"]).tzinfo)
        before = (self.root / "abilities.json").read_bytes()
        for replace in (False, True):
            self.assertEqual(state.register_ability(self.root, second, replace=replace)["status"], "unchanged")
            self.assertEqual((self.root / "abilities.json").read_bytes(), before)
        state.register_ability(self.root, third, replace=True)
        saved = state.load_abilities(self.root)
        self.assertEqual(saved["abilities"], [third])
        self.assertEqual([entry["previous_definition"] for entry in saved["history"]], [original, second])
        self.assertEqual(saved["history"][0], first_history[0])

    def test_invalid_registry_history_is_rejected_without_rewriting(self):
        ability = self.ability()
        valid = {
            "replaced_at": "2026-10-04T10:00:00+00:00", "ability_id": ability["id"],
            "previous_definition": ability,
        }
        invalid_histories = (
            None, {}, ["bad"], [{}], [{**valid, "replaced_at": 123}],
            [{**valid, "replaced_at": "not-a-date"}], [{**valid, "replaced_at": "2026-10-04"}],
            [{**valid, "ability_id": "custom.wrong"}], [{**valid, "previous_definition": {}}],
            [{**valid, "ability_id": "user_problem", "previous_definition": self.ability("user_problem")}],
        )
        for history in invalid_histories:
            with self.subTest(history=history):
                state.write_json(self.root / "abilities.json", {
                    "schema_version": 1, "abilities": [ability], "history": history,
                })
                before = (self.root / "abilities.json").read_bytes()
                with self.assertRaises(ValueError):
                    state.register_ability(self.root, self.ability("custom.another"))
                self.assertEqual((self.root / "abilities.json").read_bytes(), before)

    def test_unknown_case_or_observation_ability_is_rejected(self):
        path = self.root / "cases" / "case-one.json"
        unknown_case = self.case(ability_id="custom.unregistered")
        with self.assertRaisesRegex(ValueError, "unknown ability_ids"):
            state.validate_case(unknown_case, path)
        unknown_observation = self.case()
        unknown_observation["attempts"][0]["observations"][0]["ability_id"] = "custom.unregistered"
        with self.assertRaisesRegex(ValueError, "observation ability_id"):
            state.validate_case(unknown_observation, path)
        state.write_json(path, unknown_case)
        with self.assertRaises(ValueError):
            state.eligible_cases(self.root)

    def test_old_v1_archive_works_without_registry(self):
        self.put_case()
        original_history = [{"date": "2026-09-01", "case_ids": ["old-case"]}]
        state.write_json(self.root / "review-state.json", {
            "schema_version": 1, "reviewed_case_ids": ["old-case"],
            "deferred_fingerprint": None, "history": original_history,
        })
        self.assertEqual(state.review_status(self.root)["new_case_count"], 1)
        self.assertEqual(state.mark_reviewed(self.root, ["case-one"])["new_case_count"], 0)
        saved = state.load_state(self.root)
        self.assertEqual(saved["history"][0], original_history[0])
        self.assertEqual(saved["reviewed_case_ids"], ["case-one", "old-case"])
        self.assertFalse((self.root / "abilities.json").exists())

    def test_init_only_adds_missing_templates(self):
        ability = self.ability()
        state.register_ability(self.root, ability)
        original = (self.root / "abilities.json").read_bytes()
        result = state.init(self.root)
        self.assertIn("abilities.json", result["preserved"])
        self.assertEqual((self.root / "abilities.json").read_bytes(), original)
        self.assertEqual(state.init(self.root)["created"], [])
        empty_root = self.directory / "empty"
        self.assertIn("abilities.json", state.init(empty_root)["created"])
        self.assertEqual(state.load_abilities(empty_root)["abilities"], [])

    def test_status_does_not_create_empty_directory_or_lock(self):
        result = self.cli("review-status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["new_case_count"], 0)
        self.assertFalse(self.root.exists())

    def test_base_ids_cannot_be_registered_or_replaced(self):
        self.assertEqual(len(state.IDS), 8)
        for identifier in state.IDS:
            with self.subTest(identifier=identifier):
                for replace in (False, True):
                    with self.assertRaisesRegex(ValueError, "base ability IDs"):
                        state.register_ability(self.root, self.ability(identifier), replace=replace)
        self.assertFalse(self.root.exists())

    def test_invalid_custom_definitions_are_rejected(self):
        for identifier in ("experiment-design", "custom.Mixed", "custom.snake_case", "custom.two--dashes", "custom."):
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                state.register_ability(self.root, self.ability(identifier))
        for field, value in (("name", " "), ("definition", None), ("observable_behaviors", []), ("observable_behaviors", [3])):
            invalid = {**self.ability(), field: value}
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                state.register_ability(self.root, invalid)

    def test_invalid_existing_registry_is_not_silently_rewritten(self):
        duplicate = self.ability()
        for definitions in ([duplicate, duplicate], [self.ability("user_problem")]):
            state.write_json(self.root / "abilities.json", {"schema_version": 1, "abilities": definitions})
            original = (self.root / "abilities.json").read_bytes()
            with self.assertRaises(ValueError):
                state.register_ability(self.root, self.ability("custom.another"))
            self.assertEqual((self.root / "abilities.json").read_bytes(), original)

    def test_optional_context_is_validated_preserved_and_affects_fingerprint(self):
        case = self.put_case()
        original = state.review_status(self.root)["fingerprint"]
        case["context_ref"] = "business-context.md#project-a"
        case["context_snapshot"] = {
            "project": "项目 A", "role": "负责试点验证", "constraints": ["两周内完成"],
            "help_received": "同事补充了数据口径",
        }
        path = self.root / "cases" / "case-one.json"
        state.write_json(path, case)
        state.validate_case(case, path)
        eligible, _ = state.eligible_cases(self.root)
        self.assertEqual(eligible[0]["context_snapshot"], case["context_snapshot"])
        self.assertEqual(eligible[0]["context_ref"], case["context_ref"])
        self.assertNotEqual(state.review_status(self.root)["fingerprint"], original)
        state.defer_review(self.root)
        case["context_snapshot"]["help_received"] = "独立完成"
        state.write_json(path, case)
        self.assertFalse(state.review_status(self.root)["deferred_unchanged"])
        partial = {**self.case(), "context_snapshot": {"role": "负责研究"}}
        state.validate_case(partial, path)

    def test_invalid_optional_context_is_rejected(self):
        for fields in (
            {"context_ref": []}, {"context_snapshot": "bad"},
            {"context_snapshot": {"project": []}}, {"context_snapshot": {"role": 3}},
            {"context_snapshot": {"constraints": "bad"}},
            {"context_snapshot": {"constraints": [1]}},
            {"context_snapshot": {"help_received": False}},
        ):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                state.validate_case({**self.case(), **fields}, self.root / "cases" / "case-one.json")

    def test_concurrent_processes_mark_reviewed_without_losing_history(self):
        identifiers = [f"case-{index}" for index in range(8)]
        for identifier in identifiers:
            self.put_case(identifier)
        self.concurrent_cli([["mark-reviewed", "--case-id", identifier] for identifier in identifiers])
        saved = state.load_state(self.root)
        self.assertEqual(saved["reviewed_case_ids"], identifiers)
        self.assertEqual(len(saved["history"]), len(identifiers))
        self.assertEqual(sorted(item["case_ids"][0] for item in saved["history"]), identifiers)

    def test_concurrent_processes_register_without_losing_ids(self):
        identifiers = [f"custom.dimension-{index}" for index in range(8)]
        commands = []
        for index, identifier in enumerate(identifiers):
            path = self.directory / f"ability-{index}.json"
            state.write_json(path, self.ability(identifier))
            commands.append(["register-ability", "--input", str(path)])
        results = self.concurrent_cli(commands)
        self.assertTrue(all(result["status"] == "created" for result in results))
        self.assertEqual(sorted(item["id"] for item in state.load_abilities(self.root)["abilities"]), identifiers)

    def test_lock_timeout_and_release_after_exception(self):
        with state.file_lock(self.root):
            result = self.cli("--lock-timeout", "0.05", "defer-review")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Timed out waiting for data lock", result.stderr)
        self.assertFalse((self.root / "review-state.json").exists())
        with self.assertRaisesRegex(RuntimeError, "deliberate"):
            with state.file_lock(self.root):
                raise RuntimeError("deliberate")
        state.defer_review(self.root, lock_timeout=0.1)
        self.assertTrue((self.root / "review-state.json").exists())

    def test_concurrent_replacements_preserve_every_previous_definition(self):
        initial = self.ability()
        state.register_ability(self.root, initial)
        commands, definitions = [], [initial]
        for index in range(6):
            definition = {**initial, "definition": f"Concurrent definition {index}"}
            definitions.append(definition)
            path = self.directory / f"replacement-{index}.json"
            state.write_json(path, definition)
            commands.append(["register-ability", "--input", str(path), "--replace"])
        results = self.concurrent_cli(commands)
        self.assertTrue(all(result["status"] == "replaced" for result in results))
        saved = state.load_abilities(self.root)
        self.assertEqual(len(saved["history"]), 6)
        preserved = [item["previous_definition"] for item in saved["history"]] + saved["abilities"]
        self.assertCountEqual(preserved, definitions)

    def test_failed_atomic_json_write_preserves_original_and_cleans_temp(self):
        path = self.root / "sample.json"
        state.write_json(path, {"original": True})
        with self.assertRaises(TypeError):
            state.write_json(path, {"bad": {1, 2}})
        self.assertEqual(state.read_json(path), {"original": True})
        self.assertEqual(list(self.root.glob(".pm-grow-*")), [])


if __name__ == "__main__":
    unittest.main()
