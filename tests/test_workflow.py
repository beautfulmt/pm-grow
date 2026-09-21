import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


state = module("state")
book = module("build_handbook")


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def put_case(self, identifier, kind="independent", owner="self", status="active", origin="work"):
        value = {
            "schema_version": 1, "case_id": identifier, "title": "隔离模拟任务",
            "owner": owner, "origin": origin, "status": "closed",
            "ability_ids": ["user_problem"],
            "attempts": [{
                "attempt_id": "attempt-01", "date": "2026-09-21",
                "kind": kind, "status": status,
                "user_work": "测试用户先明确目标，再提出需要核对的实际证据。",
                "source": "隔离测试输入，非真实个人档案", "observations": [],
            }],
        }
        state.write_json(self.root / "cases" / (identifier + ".json"), value)
        return value

    def test_init_preserves_existing_files(self):
        original = self.root / "profile.md"
        original.write_text("用户原有记录", encoding="utf-8")
        result = state.init(self.root)
        self.assertEqual(original.read_text(encoding="utf-8"), "用户原有记录")
        self.assertIn("profile.md", result["preserved"])
        self.assertEqual(state.init(self.root)["created"], [])

    def test_status_does_not_initialize_missing_directory(self):
        missing = self.root / "unused"
        result = state.review_status(missing)
        self.assertFalse(result["auto_review_due"])
        self.assertFalse(missing.exists())

    def test_data_directory_override(self):
        with patch.dict(os.environ, {"PM_GROW_DATA_DIR": str(self.root / "env")}):
            self.assertEqual(state.data_root(), (self.root / "env").resolve())
            self.assertEqual(state.data_root(str(self.root)), self.root.resolve())

    def test_only_own_verified_attempts_count(self):
        self.put_case("work-one")
        self.put_case("work-two", kind="guided")
        self.put_case("sim-three", origin="simulation")
        self.put_case("demo", kind="model_demo")
        self.put_case("yes", kind="acknowledgement")
        self.put_case("other", owner="third_party")
        self.put_case("withdrawn", status="withdrawn")
        self.put_case("legacy", origin="legacy", status="unverified")
        (self.root / "growth-log.md").write_text("## 2026-09-21 · 更正\n" * 20, encoding="utf-8")
        result = state.review_status(self.root)
        self.assertEqual(result["new_case_count"], 3)
        self.assertTrue(result["auto_review_due"])
        self.assertEqual(len(result["ignored_case_ids"]), 5)

    def test_multiple_attempts_are_one_case(self):
        value = self.put_case("same-task")
        extra = copy.deepcopy(value["attempts"][0])
        extra["attempt_id"] = "attempt-02"
        value["attempts"].append(extra)
        state.write_json(self.root / "cases" / "same-task.json", value)
        self.assertEqual(state.review_status(self.root)["new_case_count"], 1)

    def test_withdrawal_can_invalidate_case_without_deleting_history(self):
        value = self.put_case("case-one")
        value["attempts"][0]["status"] = "withdrawn"
        state.write_json(self.root / "cases" / "case-one.json", value)
        self.assertEqual(state.review_status(self.root)["new_case_count"], 0)
        self.assertEqual(len(state.read_json(self.root / "cases" / "case-one.json")["attempts"]), 1)

    def test_missing_source_is_not_counted(self):
        value = self.put_case("case-one")
        value["attempts"][0]["source"] = ""
        state.write_json(self.root / "cases" / "case-one.json", value)
        self.assertEqual(state.review_status(self.root)["new_case_count"], 0)

    def test_duplicate_case_ids_fail(self):
        value = self.put_case("case-one")
        state.write_json(self.root / "cases" / "duplicate.json", value)
        with self.assertRaises(ValueError):
            state.review_status(self.root)

    def test_defer_and_new_evidence(self):
        for i in range(3):
            self.put_case(f"case-{i}")
        self.assertTrue(state.review_status(self.root)["auto_review_due"])
        self.assertFalse(state.defer_review(self.root)["auto_review_due"])
        self.assertTrue(state.review_status(self.root)["deferred_unchanged"])
        self.put_case("case-3")
        self.assertTrue(state.review_status(self.root)["auto_review_due"])

    def test_mark_reviewed_only_eligible_cases(self):
        for i in range(3):
            self.put_case(f"case-{i}")
        with self.assertRaises(ValueError):
            state.mark_reviewed(self.root, ["missing"])
        result = state.mark_reviewed(self.root, ["case-0", "case-1", "case-2"])
        self.assertEqual(result["new_case_count"], 0)
        self.assertEqual(len(state.load_state(self.root)["history"]), 1)

    def test_malformed_case_fails_closed(self):
        state.write_json(self.root / "cases" / "bad.json", {"schema_version": 1})
        with self.assertRaises(ValueError):
            state.review_status(self.root)


class HandbookTest(unittest.TestCase):
    def setUp(self):
        self.sample = json.loads((ROOT / "tests" / "fixtures" / "handbook.json").read_text(encoding="utf-8"))

    def test_all_topics_and_sources_are_rendered(self):
        html = book.render(self.sample)
        self.assertIn('id="topic-problem-before-dashboard"', html)
        self.assertIn('id="topic-priority-tradeoffs"', html)
        self.assertIn("GitLab PM CDF", html)
        self.assertIn("querySelectorAll", html)
        self.assertNotIn('<script src=', html)
        self.assertNotIn('<link ', html)
        self.assertNotIn("{{ARTICLES}}", html)

    def test_content_is_escaped_and_not_reprocessed(self):
        self.sample["title"] = "<script>alert(1)</script> {{COUNT}}"
        self.sample["topics"][0]["template"] = '</pre><img src=x onerror="alert(1)">'
        html = book.render(self.sample)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)", html)
        self.assertIn("{{COUNT}}", html)
        self.assertNotIn("<img src=x", html)

    def test_invalid_source_url_is_rejected(self):
        self.sample["topics"][0]["sources"][0]["url"] = "javascript:alert(1)"
        with self.assertRaises(ValueError):
            book.render(self.sample)

    def test_duplicate_topic_id_rejected(self):
        self.sample["topics"][1]["id"] = self.sample["topics"][0]["id"]
        with self.assertRaises(ValueError):
            book.render(self.sample)

    def test_empty_book_or_missing_provenance_rejected(self):
        empty = copy.deepcopy(self.sample)
        empty["topics"] = []
        with self.assertRaises(ValueError):
            book.render(empty)
        self.sample["topics"][0]["sources"] = []
        with self.assertRaises(ValueError):
            book.render(self.sample)

    def test_approved_replacement_preserves_previous_html(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)
            source, output = path / "book.json", path / "book.html"
            source.write_text(json.dumps(self.sample, ensure_ascii=False), encoding="utf-8")
            book.build(source, output)
            original = output.read_text(encoding="utf-8")
            with self.assertRaises(ValueError):
                book.build(source, output)
            self.sample["title"] = "更新后的模拟手册"
            source.write_text(json.dumps(self.sample, ensure_ascii=False), encoding="utf-8")
            result = book.build(source, output, replace=True)
            self.assertEqual(Path(result["backup"]).read_text(encoding="utf-8"), original)
            self.assertIn("更新后的模拟手册", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
