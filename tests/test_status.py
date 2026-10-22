"""Session-opening status: retired check-backs, stale problems, compact output,
report deferral, prior-stage levels, focus abilities and spaced-transfer prompts."""
import json

from support import Clock, DataTestCase, attempt, make_record, problem, records, upgrade, work
from storage import atomic_write_json
import report


def observed(ability_id="data_validation", text="先核对口径再拆解"):
    return [{"ability_id": ability_id, "text": text, "status": "candidate"}]


def check(on=None, when=None, question="上次的问题现在怎么样了？"):
    value = {"question": question}
    if on:
        value["on"] = on
    if when:
        value["when"] = when
    return value


def in_memory(*values):
    """Stored-form records for View-level tests that do not go through append_record."""
    clock = Clock()
    result = []
    for value in values:
        item = dict(value, schema_version=2)
        item["recorded_at"] = clock().isoformat(timespec="microseconds")
        result.append(item)
    return result


def narrative():
    return {"headline": "隔离模拟报告", "learned_summary": "从模拟材料学习。", "problems_summary": "以记录为准。",
            "growth_summary": "以证据为准。", "gaps": [], "next_focus": "继续观察。", "message": "仅用于功能验证。"}


class CheckBackRetirementTest(DataTestCase):
    def pending(self, today="2026-10-20"):
        return {item["problem_id"]: item for item in self.view().pending_check_backs(records.date.fromisoformat(today))}

    def test_terminal_status_after_the_check_back_retires_it(self):
        self.add(make_record("set", "2026-10-04", problem=problem("p1", check_back=check(on="2026-10-05"))))
        self.assertIn("p1", self.pending())
        self.add(make_record("drop", "2026-10-06", problem={"id": "p1", "status": "dropped"}))
        self.assertNotIn("p1", self.pending())
        self.assertEqual(self.cli_json("--today", "2026-10-20", "status")["follow_ups_due"], [])

    def test_conditional_check_back_is_retired_by_a_later_closed_status(self):
        self.add(make_record("set", "2026-10-04", problem=problem("p1", check_back=check(when="用户下次提到时"))))
        self.add(make_record("close", "2026-10-07", problem={"id": "p1", "status": "closed"}))
        self.assertEqual(self.pending(), {})

    def test_check_back_in_the_same_or_a_later_record_than_the_terminal_status_stays(self):
        self.add(make_record("same", "2026-10-04", problem=problem(
            "p1", status="solved", outcome="已上线", check_back=check(on="2026-10-18", question="指标稳住了吗？"))))
        self.add(make_record("solved", "2026-10-04", problem=problem("p2", status="solved", outcome="已上线")))
        self.add(make_record("later", "2026-10-05", problem={"id": "p2", "check_back": check(on="2026-10-19")}))
        self.assertEqual(sorted(self.pending()), ["p1", "p2"])

    def test_reopening_after_a_terminal_status_brings_the_check_back_back(self):
        self.add(make_record("set", "2026-10-04", problem=problem("p1", check_back=check(on="2026-10-05"))))
        self.add(make_record("drop", "2026-10-06", problem={"id": "p1", "status": "dropped"}))
        self.add(make_record("reopen", "2026-10-08", problem={"id": "p1", "status": "open"}))
        self.assertIn("p1", self.pending())

    def test_answered_check_back_still_needs_a_later_follow_up(self):
        self.add(make_record("set", "2026-10-04", problem=problem("p1", check_back=check(on="2026-10-05"))))
        self.add(make_record("answer", "2026-10-06", kind="follow_up", problem={"id": "p1", "status": "partial"}))
        self.assertEqual(self.pending(), {})


class StaleProblemTest(DataTestCase):
    def test_open_problems_without_records_for_thirty_days_are_listed_oldest_first(self):
        self.add(make_record("old-a", "2026-08-01", problem=problem("old-a")))
        self.add(make_record("old-b", "2026-09-01", problem=problem("old-b", status="blocked")))
        self.add(make_record("old-planned", "2026-08-15", problem=problem("old-planned", check_back=check(on="2026-11-01"))))
        self.add(make_record("old-solved", "2026-08-01", problem=problem("old-solved", status="solved")))
        self.add(make_record("recent", "2026-10-10", problem=problem("recent")))
        stale = self.cli_json("--today", "2026-10-20", "status")
        self.assertEqual([item["problem_id"] for item in stale["stale_problems"]], ["old-a", "old-b"])
        self.assertEqual(stale["stale_problems"][0]["days_inactive"], 80)
        self.assertEqual(stale["counts"]["stale_problems"], 2)

    def test_a_due_check_back_is_asked_once_not_also_as_a_stale_problem(self):
        self.add(make_record("old-due", "2026-08-02", problem=problem("old-due", check_back=check(on="2026-08-10"))))
        for view in ((), ("--full",)):
            status = self.cli_json("--today", "2026-09-20", "status", *view)
            self.assertEqual([item["problem_id"] for item in status["follow_ups_due"]], ["old-due"])
            self.assertEqual(status["stale_problems"], [])

    def test_asking_once_and_recording_the_answer_clears_the_prompt(self):
        self.add(make_record("old", "2026-08-01", problem=problem("old")))
        self.add(make_record("still-on", "2026-10-20", kind="follow_up", problem={"id": "old"},
                             next_step="下周和运营复盘一次"))
        self.assertEqual(self.cli_json("--today", "2026-10-20", "status")["stale_problems"], [])

    def test_compact_status_caps_stale_problems_and_hides_their_conditional_follow_ups(self):
        for index in range(5):
            self.add(make_record(f"old-{index}", f"2026-08-0{index + 1}", problem=problem(
                f"old-{index}", check_back=check(when="用户下次提到时"))))
        status = self.cli_json("--today", "2026-10-20", "status")
        self.assertEqual(len(status["stale_problems"]), 3)
        self.assertEqual(status["counts"]["stale_problems"], 5)
        self.assertEqual(status["follow_ups_due"], [])
        self.assertTrue(status["truncated"])
        full = self.cli_json("--today", "2026-10-20", "status", "--full")
        self.assertEqual(len(full["stale_problems"]), 5)
        self.assertEqual(len(full["follow_ups_due"]), 5)


class CompactStatusTest(DataTestCase):
    def test_compact_lists_are_capped_and_full_returns_everything(self):
        for index in range(8):
            self.add(make_record(f"due-{index}", "2026-10-01", problem=problem(
                f"due-{index}", check_back=check(on=f"2026-10-0{index + 2}")), next_step="找数据同学确认埋点口径"))
        for index in range(7):
            self.add(make_record(f"cond-{index}", f"2026-10-1{index}", problem=problem(
                f"cond-{index}", check_back=check(when="评审会之后"))))
        status = self.cli_json("--today", "2026-10-20", "status")
        self.assertEqual(status["view"], "compact")
        due = [item for item in status["follow_ups_due"] if item["status"] == "due"]
        conditional = [item for item in status["follow_ups_due"] if item["status"] == "condition_pending"]
        self.assertEqual(len(due), 5)
        self.assertEqual(due[0]["problem_id"], "due-0")  # most overdue first
        self.assertEqual(due[0]["days_overdue"], 18)
        self.assertEqual(len(conditional), 5)
        self.assertEqual(conditional[0]["problem_id"], "cond-6")  # most recently registered first
        self.assertEqual(len(status["open_problems"]), 5)
        self.assertEqual(set(status["open_problems"][0]), {"id", "title", "status", "status_name", "last_date"})
        self.assertTrue(status["truncated"])
        self.assertEqual(status["hint"], "完整列表用 status --full")
        self.assertEqual(status["counts"]["follow_ups_due"], 8)
        self.assertEqual(status["counts"]["condition_pending"], 7)
        self.assertEqual(status["counts"]["open_problems"], 15)
        self.assertNotIn("new_record_ids", status["report"])
        self.assertNotIn("fingerprint", status["report"])
        full = self.cli_json("--today", "2026-10-20", "status", "--full")
        self.assertEqual(full["view"], "full")
        self.assertEqual(len(full["follow_ups_due"]), 15)
        self.assertEqual(len(full["open_problems"]), 15)
        self.assertIn("record_ids", full["open_problems"][0])
        self.assertEqual(len(full["report"]["new_record_ids"]), 15)
        self.assertNotIn("truncated", full)

    def test_small_histories_are_not_marked_truncated(self):
        self.add(make_record("one", problem=problem("p1", check_back=check(on="2026-10-05"))))
        status = self.cli_json("--today", "2026-10-06", "status")
        self.assertFalse(status["truncated"])
        self.assertNotIn("hint", status)

    def test_recent_zero_returns_no_records(self):
        for index in range(3):
            self.add(make_record(f"record-{index}"))
        self.assertEqual(self.cli_json("status", "--recent", "0")["recent"], [])
        self.assertEqual(len(self.cli_json("status", "--recent", "2")["recent"]), 2)
        self.assertNotEqual(self.cli("status", "--recent", "-1").returncode, 0)

    def test_compact_abilities_list_only_observed_ones_and_count_the_rest(self):
        self.add(make_record("stage", stage_update={"stage": "independent_pm", "reason": "独立负责模块"}))
        self.add(attempt("a1", "p1", "2026-10-04", observations=observed()))
        abilities = self.cli_json("status")["abilities"]
        self.assertEqual([item["ability_id"] for item in abilities["current"]], ["data_validation"])
        self.assertEqual(abilities["unobserved_count"], len(records.ABILITIES) - 1)
        self.assertEqual(abilities["current"][0]["latest_observation"]["status"], "candidate")
        full = self.cli_json("status", "--full")["abilities"]
        self.assertEqual(len(full["current"]), len(records.ABILITIES))


class DeferralTest(DataTestCase):
    def three_attempts(self, start, stamp="2026-10-04"):
        for index in range(start, start + 3):
            self.add(attempt(f"attempt-{index}", f"problem-{index}", stamp))

    def test_until_blocks_new_triggers_and_reproposes_on_the_date(self):
        self.three_attempts(0)
        result = self.cli_json("--today", "2026-10-19", "report", "defer", "--until", "2026-11-01")
        self.assertEqual(result["deferred_until"], "2026-11-01")
        self.three_attempts(3)
        before = self.cli_json("--today", "2026-10-31", "status")["report"]
        self.assertFalse(before["due"])
        self.assertEqual(before["deferred_until"], "2026-11-01")
        on_the_day = self.cli_json("--today", "2026-11-01", "status")["report"]
        self.assertTrue(on_the_day["due"])
        self.assertIn("until_reached", [reason["code"] for reason in on_the_day["reasons"]])

    def test_until_must_be_in_the_future(self):
        result = self.cli("--today", "2026-10-19", "report", "defer", "--until", "2026-10-19")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--until", result.stderr)

    def test_elapsed_trigger_counts_from_the_deferral_date(self):
        self.add(make_record("first", "2026-09-01"))
        report.defer(self.root, today="2026-10-01")
        self.add(make_record("after", "2026-10-02"))
        self.assertFalse(self.cli_json("--today", "2026-10-14", "status")["report"]["due"])
        cursor = self.cli_json("--today", "2026-10-15", "status")["report"]
        self.assertTrue(cursor["due"])
        self.assertEqual([reason["code"] for reason in cursor["reasons"]], ["elapsed"])
        self.assertEqual(cursor["since_basis"], "deferred")

    def test_key_moments_before_the_deferral_do_not_count_again(self):
        self.add(make_record("solved", "2026-10-04", problem=problem("p1", status="solved", outcome="已上线")))
        self.assertTrue(self.cli_json("--today", "2026-10-05", "status")["report"]["due"])
        report.defer(self.root, today="2026-10-05")
        self.add(make_record("note", "2026-10-06"))
        self.assertFalse(self.cli_json("--today", "2026-10-06", "status")["report"]["due"])
        self.add(make_record("milestone", "2026-10-07", kind="milestone", milestone="评审通过"))
        cursor = self.cli_json("--today", "2026-10-07", "status")["report"]
        self.assertTrue(cursor["due"])
        self.assertEqual([item["type"] for item in cursor["reasons"][0]["items"]], ["milestone"])

    def test_v2_0_fingerprint_deferral_still_loads(self):
        self.add(make_record("first", "2026-10-01"))
        state = records.load_state(self.root)
        state["report"]["deferred"] = {"fingerprint": "0" * 64, "deferred_at": "2000-01-01T00:00:00+00:00",
                                       "reasons": ["elapsed"]}
        atomic_write_json(self.root / "state.json", state)
        cursor = self.cli_json("--today", "2026-10-20", "status")["report"]
        self.assertTrue(cursor["deferred"])
        self.assertEqual(cursor["deferred_on"], "2000-01-01")
        # The legacy deferral predates every record, so the elapsed trigger applies again.
        self.assertTrue(cursor["due"])

    def test_build_clears_the_deferral(self):
        self.add(make_record("learning", "2026-10-04"))
        report.defer(self.root, today="2026-10-19")
        draft = report.draft(self.root, today="2026-10-19")
        draft["narrative"] = narrative()
        report.build(self.root, draft, today="2026-10-19")
        cursor = self.cli_json("--today", "2026-10-19", "status")["report"]
        self.assertFalse(cursor["deferred"])
        self.assertIsNone(records.load_state(self.root)["report"]["deferred"])

    def test_malformed_deferral_is_rejected(self):
        self.add(make_record("first"))
        state = records.load_state(self.root)
        state["report"]["deferred"] = {"deferred_on": "2026-10-01"}
        (self.root / "state.json").write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "deferred_at"):
            records.load_state(self.root)


class PriorStageTest(DataTestCase):
    def history(self):
        return in_memory(
            make_record("stage-one", "2026-09-01", kind="context_update",
                        stage_update={"stage": "independent_pm", "reason": "独立负责会员模块"}),
            attempt("a1", "p1", "2026-09-02", observations=observed()),
            attempt("a2", "p2", "2026-09-09", observations=observed()),
            make_record("up", "2026-09-10", kind="review",
                        ability_updates=[upgrade("data_validation", ["a1", "a2"])]),
            make_record("stage-two", "2026-10-01", kind="context_update",
                        stage_update={"stage": "senior", "reason": "负责一条业务线", "basis": "role_change"}),
            attempt("a3", "p3", "2026-10-02", observations=observed("strategy_prioritization", "先定目标再排序")),
        )

    def test_snapshot_keeps_the_previous_stage_level_next_to_the_new_stage(self):
        view = records.View(self.history(), records.default_state())
        self.assertEqual(view.stage["stage"], "senior")
        snapshot = records.ability_snapshot(view, full=False)
        entry = next(item for item in snapshot["current"] if item["ability_id"] == "data_validation")
        self.assertEqual(entry["level"], "unobserved")
        self.assertEqual(entry["prior"], {"stage": "independent_pm", "stage_name": "独立 PM", "level": "independent",
                                          "level_name": "可以独立", "date": "2026-09-10"})
        full = records.ability_snapshot(view, full=True)
        self.assertEqual(next(item for item in full["current"] if item["ability_id"] == "data_validation")["prior"],
                         entry["prior"])

    def test_report_overview_renders_prior_levels_and_old_reports_still_render(self):
        view = records.View(self.history(), records.default_state())
        basis = report.select_basis(view)
        facts = report.build_facts(view, basis)
        overview = {row["ability_id"]: row for row in facts["ability_overview"]}
        self.assertEqual(overview["data_validation"]["prior"]["level"], "independent")
        self.assertEqual(overview["strategy_prioritization"]["level"], "unobserved")
        self.assertNotIn("team_leadership", overview)
        value = {"schema_version": 2, "kind": "pm-grow-report", "generated_on": "2026-10-20", "basis": basis,
                 "facts": facts, "narrative": narrative()}
        html = report.render(value, view.state)
        self.assertIn("能力全景", html)
        self.assertIn("独立 PM：可以独立", html)
        legacy = json.loads(json.dumps(value))
        for key in ("ability_overview", "focus"):
            legacy["facts"].pop(key)
        html = report.render(legacy, view.state)
        self.assertIn("成长与欠缺", html)
        self.assertNotIn("能力全景", html)

    def test_review_mode_is_shown_when_present(self):
        view = records.View(self.history(), records.default_state())
        value = {"schema_version": 2, "kind": "pm-grow-report", "generated_on": "2026-10-20",
                 "basis": report.select_basis(view), "facts": None, "narrative": narrative()}
        value["facts"] = report.build_facts(view, value["basis"])
        value["facts"]["ability_changes"][0]["review"] = {"mode": "self_check", "summary": "无委派工具，按角色卡自查"}
        self.assertIn("主导师自查", report.render(value, view.state))


class FocusTest(DataTestCase):
    def test_focus_update_is_validated(self):
        bad = [
            {"focus_update": {"abilities": ["data_validation", "user_problem", "business_value"], "reason": "太多"}},
            {"focus_update": {"abilities": ["data_validation", "data_validation"], "reason": "重复"}},
            {"focus_update": {"abilities": ["made_up"], "reason": "未知"}},
            {"focus_update": {"abilities": ["data_validation"]}},
            {"focus_update": {"reason": "缺 abilities"}},
            {"focus_update": {"abilities": "data_validation", "reason": "不是数组"}},
            {"focus_update": {"abilities": [], "reason": "r", "extra": 1}},
        ]
        for fields in bad:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.add(make_record("focus", kind="preference", **fields))
        with self.assertRaisesRegex(ValueError, "尚未注册"):
            self.add(make_record("focus", kind="preference",
                                 focus_update={"abilities": ["custom.ethics"], "reason": "想练伦理判断"}))
        self.assertFalse((self.root / "records").exists())

    def test_status_reports_focus_progress_and_clearing_removes_it(self):
        self.add(make_record("stage", "2026-10-01", stage_update={"stage": "independent_pm", "reason": "独立负责模块"}))
        self.add(attempt("before", "p0", "2026-10-01", observations=observed()))
        self.add(make_record("focus", "2026-10-02", kind="preference",
                             focus_update={"abilities": ["data_validation", "strategy_prioritization"],
                                           "reason": "述职前想把数据验证练扎实"}))
        self.add(attempt("practice", "p1", "2026-10-05", observations=observed()))
        self.add(attempt("demo-only", "p2", "2026-10-06", kind="demo", observations=observed()))
        focus = self.cli_json("status")["focus"]
        self.assertEqual(focus["since"], "2026-10-02")
        self.assertEqual(focus["reason"], "述职前想把数据验证练扎实")
        first = focus["abilities"][0]
        self.assertEqual((first["ability_id"], first["level"], first["next_level"]),
                         ("data_validation", "unobserved", "needs_support"))
        self.assertEqual(first["records_since_focus"], 1)
        self.assertEqual(first["last_practiced_on"], "2026-10-05")
        self.assertEqual(focus["abilities"][1]["records_since_focus"], 0)
        current = {item["ability_id"]: item for item in self.cli_json("status")["abilities"]["current"]}
        self.assertTrue(current["strategy_prioritization"]["focus"])
        log = (self.root / "growth-log.md").read_text(encoding="utf-8")
        self.assertIn("焦点能力：数据分析与效果验证、策略取舍与规划", log)
        self.add(make_record("clear", "2026-10-07", kind="preference",
                             focus_update={"abilities": [], "reason": "述职结束，先不设焦点"}))
        self.assertIsNone(self.cli_json("status")["focus"])
        self.assertIn("焦点能力：清除焦点", (self.root / "growth-log.md").read_text(encoding="utf-8"))

    def test_invalidated_focus_falls_back_to_the_previous_one(self):
        self.add(make_record("first", kind="preference", focus_update={"abilities": ["user_problem"], "reason": "先练问题界定"}))
        self.add(make_record("second", kind="preference", focus_update={"abilities": ["business_value"], "reason": "记错了"}))
        self.add(make_record("fix", kind="correction", corrections=[{"record_id": "second", "reason": "用户没有改焦点", "invalidate": True}]))
        self.assertEqual(self.view().focus["abilities"], ["user_problem"])

    def test_report_shows_the_focus_and_its_progress_in_the_period(self):
        self.add(make_record("focus", "2026-10-02", kind="preference",
                             focus_update={"abilities": ["data_validation"], "reason": "先练数据验证"}))
        self.add(attempt("practice", "p1", "2026-10-05", observations=observed()))
        draft = report.draft(self.root, today="2026-10-19")
        self.assertEqual(draft["facts"]["focus"]["abilities"][0]["records_in_period"], 1)
        draft["narrative"] = narrative()
        html = (self.root / "reports" / "2026-10-19.html")
        report.build(self.root, draft, today="2026-10-19")
        content = html.read_text(encoding="utf-8")
        self.assertIn("本期焦点", content)
        self.assertIn("先练数据验证", content)


class TransferOpportunityTest(DataTestCase):
    def opportunities(self, today="2026-10-20", full=False):
        arguments = ["--today", today, "status"] + (["--full"] if full else [])
        return [item["method_id"] for item in self.cli_json(*arguments)["transfer_opportunities"]]

    def test_supported_use_becomes_an_opportunity_after_a_week_until_used_independently(self):
        self.add(make_record("demo", "2026-10-01", kind="attempt", problem=problem("p1"), methods=["metric-diagnosis"],
                             user_work=[work("demo", "导师示范拆解")]))
        self.add(make_record("taught", "2026-10-02", methods=["jtbd"]))
        self.add(make_record("recent", "2026-10-15", kind="attempt", problem=problem("p2"), methods=["funnel"],
                             user_work=[work("guided")]))
        self.add(make_record("demo-then", "2026-10-03", kind="attempt", problem=problem("p3"), methods=["prioritization"],
                             user_work=[work("demo")]))
        self.add(make_record("own", "2026-10-10", kind="attempt", problem=problem("p4"), methods=["prioritization"],
                             user_work=[work("independent")]))
        status = self.cli_json("--today", "2026-10-20", "status")
        items = {item["method_id"]: item for item in status["transfer_opportunities"]}
        self.assertEqual(sorted(items), ["jtbd", "metric-diagnosis"])
        self.assertEqual(items["metric-diagnosis"]["label"], "指标异动诊断")
        self.assertEqual(items["metric-diagnosis"]["days_since"], 19)
        self.assertEqual(self.opportunities()[0], "jtbd")  # most recent supported use first
        self.assertIn("funnel", self.opportunities(today="2026-10-22"))

    def test_support_after_an_independent_use_counts_again(self):
        self.add(make_record("own", "2026-10-01", kind="attempt", problem=problem("p1"), methods=["ab-test"],
                             user_work=[work("independent")]))
        self.add(make_record("again", "2026-10-05", kind="attempt", problem=problem("p2"), methods=["ab-test"],
                             user_work=[work("guided")]))
        self.assertEqual(self.opportunities(), ["ab-test"])

    def test_compact_status_keeps_three(self):
        for index, method in enumerate(["jtbd", "funnel", "prioritization", "ab-test", "user-interview"]):
            self.add(make_record(f"taught-{index}", f"2026-10-0{index + 1}", methods=[method]))
        self.assertEqual(len(self.opportunities()), 3)
        self.assertEqual(len(self.opportunities(full=True)), 5)
        self.assertEqual(self.cli_json("--today", "2026-10-20", "status")["counts"]["transfer_opportunities"], 5)

    def test_method_label_moved_to_records_and_report_keeps_the_name(self):
        self.assertIs(report.method_label, records.method_label)
        self.assertEqual(records.method_label("custom:本公司的灰度检查"), "本公司的灰度检查")
        self.assertEqual(records.method_label("not-a-card"), "not-a-card")
