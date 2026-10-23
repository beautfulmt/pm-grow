"""Check result capture through record writing, report triggers and rendering."""
import json
from pathlib import Path

from support import DataTestCase, make_record, problem, records, tree
from storage import atomic_write_json
import report


class OutcomeTest(DataTestCase):
    def test_summary_cannot_replace_outcome_or_retire_the_check_back(self):
        self.add(make_record("start", problem=problem(
            "p1", check_back={"on": "2026-10-04", "question": "验收结果如何？"})))
        original = tree(self.root)
        for status in ("solved", "partial"):
            with self.subTest(status=status):
                value = make_record("missing-" + status, kind="follow_up",
                                    summary="模拟验收已有明确结果，但只写在摘要里。",
                                    problem={"id": "p1", "status": status})
                result = self.cli("record", "--input", "-", stdin=json.dumps(value))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("problem.outcome", result.stderr)
                self.assertEqual(tree(self.root), original)
                view = self.view()
                self.assertEqual(view.problems["p1"]["status"], "open")
                self.assertEqual(len(view.pending_check_backs(records.date(2026, 10, 4))), 1)

    def test_cli_result_triggers_report_and_reaches_html(self):
        self.add(make_record("start", problem=problem("p1")))
        outcome = "隔离模拟：10 位用户均通过验收，结论仅覆盖该样本。"
        value = make_record("verified", kind="follow_up",
                            problem={"id": "p1", "status": "solved", "outcome": outcome})
        written = self.cli_json("record", "--input", "-", stdin=json.dumps(value))
        self.assertTrue(written["readback_verified"])
        status = self.cli_json("--today", "2026-10-04", "status")
        self.assertTrue(status["report"]["due"])
        self.assertEqual(status["report"]["counts"]["key_moments"], 1)
        self.assertEqual([r["code"] for r in status["report"]["reasons"]], ["key_moment"])
        draft = report.draft(self.root, today="2026-10-04")
        self.assertEqual(draft["facts"]["problems"][0]["outcome"], outcome)
        draft["narrative"].update(
            headline="隔离模拟报告", learned_summary="以记录为准。", problems_summary="验收已完成。",
            growth_summary="未判断能力变化。", next_focus="继续观察。", message="仅用于验证。")
        built = report.build(self.root, draft, today="2026-10-04")
        html = Path(built["output"]).read_text(encoding="utf-8")
        self.assertIn(outcome, html)
        self.assertNotIn("尚无结果", html)
        self.assertNotIn("结果尚未补录", html)

    def test_status_transition_requires_a_current_result(self):
        self.add(make_record("partial", problem=problem("p1", status="partial", outcome="只完成一半")))
        with self.assertRaisesRegex(ValueError, "problem.outcome"):
            self.add(make_record("missing", problem={"id": "p1", "status": "solved"}))
        self.add(make_record("solved", problem={"id": "p1", "status": "solved", "outcome": "全部通过验收"}))
        self.add(make_record("reopened", problem={"id": "p1", "status": "open"}))
        with self.assertRaisesRegex(ValueError, "problem.outcome"):
            self.add(make_record("reuse-old-result", problem={"id": "p1", "status": "solved"}))
        self.assertEqual(self.view().problems["p1"]["status"], "open")

    def test_same_status_inherits_result_and_retry_is_idempotent(self):
        value = make_record("verified", problem=problem("p1", status="solved", outcome="已验收"))
        self.add(value)
        self.assertFalse(self.add(value)["created"])
        self.add(make_record("note", problem={"id": "p1", "status": "solved"}, next_step="保留观察"))
        self.assertEqual(self.view().problems["p1"]["outcome"], "已验收")
        self.assertEqual(len(self.view().key_moments), 1)

    def test_legacy_missing_result_can_be_read_retried_and_supplemented(self):
        records.init(self.root)
        value = make_record("legacy", problem=problem("p1", status="solved"))
        stored = records.validate_record(value)
        stored["recorded_at"] = self.clock().isoformat(timespec="microseconds")
        path = self.root / "records" / "legacy.json"
        atomic_write_json(path, stored)
        original = path.read_bytes()
        status = self.cli_json("--today", "2026-10-04", "status")
        self.assertEqual(status["report"]["counts"]["key_moments"], 0)
        self.assertFalse(self.add(value)["created"])
        draft = report.draft(self.root, today="2026-10-04")
        html = report.render_problems(draft["facts"], draft["narrative"])
        self.assertIn("结果尚未补录", html)
        self.assertNotIn("尚无结果", html)
        self.add(make_record("details", kind="follow_up", problem={"id": "p1", "outcome": "根据原来源补录验收结果"}))
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.view().problems["p1"]["outcome"], "根据原来源补录验收结果")
        self.assertEqual(len(self.view().key_moments), 1)

    def test_closed_with_unverified_result_does_not_require_invention(self):
        self.add(make_record("closed", problem=problem("p1", status="closed")))
        draft = report.draft(self.root, today="2026-10-04")
        self.assertIn("结果尚未核实", report.render_problems(draft["facts"], draft["narrative"]))
        self.assertEqual(self.view().key_moments, [])
