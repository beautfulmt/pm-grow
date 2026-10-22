"""Exercise report facts, cursor changes, and approved handbook delivery."""
import copy
from pathlib import Path

from support import DataTestCase, FIXTURES, attempt, make_record, problem, upgrade
import handbook
import report


def narrative():
    return {"headline": "隔离模拟报告", "learned_summary": "从模拟材料学习问题界定。",
            "problems_summary": "处理情况以原始记录为准。", "growth_summary": "能力变化以证据为准。",
            "gaps": [], "next_focus": "等待实际结果后核对。", "message": "此报告只用于功能验证。"}


class GrowthReportTest(DataTestCase):
    def draft(self):
        value = report.draft(self.root, today="2026-10-19")
        value["narrative"] = narrative()
        return value

    def test_learning_only_report_does_not_require_invented_gaps_or_growth(self):
        self.add(make_record("discussion-one", methods=["problem-framing"]))
        draft = self.draft()
        self.assertEqual(draft["facts"]["ability_changes"], [])
        self.assertEqual(draft["facts"]["performance_highlights"], [])
        result = report.build(self.root, draft, today="2026-10-19")
        html = Path(result["output"]).read_text()
        self.assertIn("没有足够依据", html)
        self.assertIn("没有记录能力程度变化", html)

    def test_facts_cannot_be_edited_and_stale_drafts_are_rejected(self):
        self.add(attempt("attempt-one", "problem-one"))
        draft = self.draft()
        forged = copy.deepcopy(draft)
        forged["facts"]["period"]["record_count"] = 999
        with self.assertRaisesRegex(ValueError, "facts"):
            report.build(self.root, forged, today="2026-10-19")
        self.add(make_record("follow-up", kind="follow_up", problem=problem("problem-one", status="solved")))
        with self.assertRaisesRegex(ValueError, "facts"):
            report.build(self.root, draft, today="2026-10-19")
        self.assertFalse((self.root / "reports/2026-10-19.html").exists())
        self.assertEqual(self.view().state["report"]["history"], [])

    def test_cross_problem_upgrade_is_rendered_and_report_cursor_advances(self):
        self.add(attempt("attempt-one", "problem-one", stamp="2026-10-02", ability="data_validation"))
        self.add(attempt("attempt-two", "problem-two", ability="data_validation"))
        self.add(make_record("upgrade", ability_updates=[upgrade("data_validation", ["attempt-one", "attempt-two"])],
                             stage_update={"stage": "independent_pm", "reason": "隔离模拟职责"}))
        draft = self.draft()
        self.assertEqual(len(draft["facts"]["ability_changes"]), 1)
        result = report.build(self.root, draft, today="2026-10-19")
        self.assertTrue(result["cursor_updated"])
        self.assertEqual(len(self.view().state["report"]["history"]), 1)
        with self.assertRaisesRegex(ValueError, "新记录"):
            report.draft(self.root, today="2026-10-19")
        self.add(make_record("new-learning", stamp="2026-10-19"))
        self.assertEqual(report.draft(self.root, today="2026-10-19")["basis"]["record_ids"], ["new-learning"])

    def test_defer_restarts_the_clock_so_only_new_triggers_reopen_the_proposal(self):
        for index in range(3):
            self.add(attempt(f"attempt-{index}", f"problem-{index}"))
        self.assertTrue(self.cli_json("--today", "2026-10-19", "status")["report"]["due"])
        report.defer(self.root, today="2026-10-19")
        self.assertFalse(self.cli_json("--today", "2026-10-19", "status")["report"]["due"])
        # One trivial record after the deferral is not a new trigger (v2.0 re-proposed here).
        self.add(make_record("new-learning"))
        cursor = self.cli_json("--today", "2026-10-19", "status")["report"]
        self.assertFalse(cursor["due"])
        self.assertTrue(cursor["deferred"])
        self.assertEqual(cursor["deferred_on"], "2026-10-19")
        for index in range(3, 6):
            self.add(attempt(f"attempt-{index}", f"problem-{index}"))
        cursor = self.cli_json("--today", "2026-10-19", "status")["report"]
        self.assertTrue(cursor["due"])
        self.assertEqual([reason["code"] for reason in cursor["reasons"]], ["problems"])

    def test_replacement_requires_opt_in_and_backs_up_both_outputs(self):
        self.add(make_record("learning"))
        draft = self.draft()
        first = report.build(self.root, draft, today="2026-10-19")
        originals = {name: Path(first[name]).read_bytes() for name in ("output", "json")}
        with self.assertRaisesRegex(ValueError, "replace"):
            report.build(self.root, draft, today="2026-10-19")
        draft["narrative"]["headline"] = "已授权更新的模拟报告"
        replaced = report.build(self.root, draft, replace=True, today="2026-10-19")
        self.assertEqual(len(replaced["backups"]), 2)
        self.assertEqual({Path(p).suffix: Path(p).read_bytes() for p in replaced["backups"]},
                         {Path(first[k]).suffix: value for k, value in originals.items()})

    def test_html_escapes_user_content_and_uses_no_remote_resources(self):
        text = '<script>alert("private")</script> {{TITLE}}'
        self.add(make_record("learning", summary=text))
        draft = self.draft()
        draft["narrative"]["headline"] = text
        result = report.build(self.root, draft, today="2026-10-19")
        html = Path(result["output"]).read_text()
        self.assertNotIn(text, html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("{{TITLE}}", html)
        self.assertNotIn("<script src=", html)
        self.assertNotIn('<link rel="stylesheet"', html)

    def test_draft_since_date_and_output_protection(self):
        self.add(make_record("older", stamp="2026-10-01"))
        self.add(make_record("newer", stamp="2026-10-18"))
        draft = report.draft(self.root, since="2026-10-10", today="2026-10-19")
        self.assertEqual(draft["basis"]["record_ids"], ["newer"])
        path = self.area / "draft.json"
        report.write_draft(draft, path)
        with self.assertRaisesRegex(ValueError, "已存在"):
            report.write_draft(draft, path)


class HandbookTest(DataTestCase):
    def test_build_and_approved_replacement_preserve_previous_output(self):
        source = FIXTURES / "handbook.json"
        target = self.area / "handbook.html"
        first = handbook.build(source, target)
        content = target.read_bytes()
        self.assertEqual(first["topics"], 2)
        with self.assertRaisesRegex(ValueError, "exists"):
            handbook.build(source, target)
        updated = handbook.build(source, target, replace=True)
        self.assertEqual(Path(updated["backup"]).read_bytes(), content)

    def test_missing_sources_and_unsafe_source_urls_are_rejected(self):
        import json
        book = json.loads((FIXTURES / "handbook.json").read_text())
        book["topics"][0]["sources"][0]["url"] = "javascript:alert(1)"
        with self.assertRaises(ValueError):
            handbook.validate(book)
        book["topics"][0]["sources"] = []
        with self.assertRaises(ValueError):
            handbook.validate(book)
