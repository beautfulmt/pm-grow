"""Eight weeks of simulated use: the opening status stays small and every
long-run signal (retired check-backs, stale problems, deferral, focus, prior
stage, spaced transfer) holds end to end through status and a built report."""
from datetime import date, timedelta
import json
from pathlib import Path

from support import DataTestCase, make_record, records, upgrade, work
from storage import atomic_write_json
import report

START = date(2026, 8, 24)
TODAY = "2026-10-20"  # day 57
STATUS_BYTES_LIMIT = 8 * 1024
ROTATING_METHODS = ["metric-diagnosis", "funnel", "problem-framing", "prioritization", "retention-cohort",
                    "user-interview", "ab-test", "four-risks"]
SCENARIOS = ["metric-anomaly", "feature-request", "prioritization-planning", "solution-review", "launch-review"]
TOPICS = ["会员续费率下降", "详情页转化波动", "新客首单流失", "评审被质疑价值", "季度规划排不下",
          "直播导流质量变差", "老功能维护成本高", "运营活动效果评估"]


def day(offset):
    return (START + timedelta(days=offset)).isoformat()


def observed(ability_id="data_validation", text="先核对口径和人群，再找原因"):
    return [{"ability_id": ability_id, "text": text, "status": "candidate"}]


class LongitudinalTest(DataTestCase):
    def setUp(self):
        super().setUp()
        self.problem_ids = []
        self.build_history()

    # ------------------------------------------------------------ fixture

    def build_history(self):
        add = self.add
        add(make_record("stage-initial", day(0), kind="context_update", summary="用户独立负责会员模块，首次定位阶段",
                        stage_update={"stage": "independent_pm", "reason": "独立负责会员模块的全流程"}))
        for index in range(40):
            self.problem(index)
        # Two independent, observed attempts on different problems and dates (p00 day 0, p03 day 3).
        add(make_record("upgrade-data", day(20), kind="review", summary="数据验证能力在独立 PM 阶段升为可以独立",
                        ability_updates=[upgrade("data_validation", ["p00-open", "p03-open"])]))
        # Methods reserved for the spaced-transfer checks.
        add(make_record("taught-jtbd", day(40), kind="attempt", summary="导师示范用待办任务拆客户诉求",
                        problem={"id": "p20"}, methods=["jtbd"], user_work=[work("demo", "导师示范，用户旁听")]))
        add(make_record("story-demo", day(30), kind="attempt", summary="导师示范写验收标准",
                        problem={"id": "p21"}, methods=["user-story"], user_work=[work("demo", "导师示范验收标准")]))
        add(make_record("story-own", day(44), kind="attempt", summary="用户自己写出验收标准",
                        problem={"id": "p22"}, methods=["user-story"], user_work=[work("independent", "独立写出验收标准")]))
        self.inject_senior_stage()
        add(make_record("focus-set", day(42), kind="preference", summary="用户希望述职前把数据验证和取舍练扎实",
                        focus_update={"abilities": ["data_validation", "strategy_prioritization"],
                                      "reason": "述职前想把数据验证和取舍练扎实"}))
        for offset, pid in ((45, "p30"), (47, "p31"), (48, "p32")):
            add(make_record(f"{pid}-practice", day(offset), kind="attempt", summary="用户独立复核指标口径并给出竞争解释",
                            problem={"id": pid}, methods=["metric-diagnosis"],
                            user_work=[work("independent", "独立核对口径并列出两个竞争解释")],
                            observations=observed()))
        report.defer(self.root, today=day(49))
        add(make_record("after-defer-note", day(50), kind="preference", summary="用户希望回答更短",
                        preferences=["回答短一点，先给结论"]))
        self.after_defer_status = records.status(self.root, today=day(50))
        for offset, pid in ((52, "p33"), (53, "p34"), (54, "p35")):
            add(make_record(f"{pid}-late", day(offset), kind="attempt", summary="用户独立给出排序与取舍理由",
                            problem={"id": pid}, methods=["prioritization"],
                            user_work=[work("guided", "在提示下补上了机会成本")],
                            observations=observed("strategy_prioritization", "补上了机会成本")))

    def problem(self, index):
        pid = f"p{index:02d}"
        self.problem_ids.append(pid)
        start = index  # problems open on days 0–39; every record stays before TODAY
        topic = TOPICS[index % len(TOPICS)]
        method = ROTATING_METHODS[index % len(ROTATING_METHODS)]
        kind = ("independent", "guided", "demo")[index % 3]
        check_back = None
        if index % 4 == 0:
            check_back = {"on": day(start + 7), "question": f"上次说的{topic}，调整后指标回来了吗？"}
        elif index % 4 == 1:
            check_back = {"when": "用户和相关方沟通之后", "question": f"{topic}这件事，对方接受了哪个选项？"}
        opening = {"id": pid, "title": f"{topic}（{index:02d}）", "scenario": SCENARIOS[index % len(SCENARIOS)]}
        if check_back:
            opening["check_back"] = check_back
        self.add(make_record(f"{pid}-open", day(start), kind="attempt",
                             summary=f"用户带来{topic}的问题，先按渠道和新老客拆了一层数据",
                             problem=opening, methods=[method],
                             user_work=[work(kind, "按渠道和新老客拆解，定位到变化集中的人群")],
                             observations=observed() if kind != "demo" else [],
                             assistance="导师给出竞争解释清单和取证顺序"))
        self.add(make_record(f"{pid}-talk", day(start + 3), summary=f"继续讨论{topic}的取证计划",
                             problem={"id": pid}, next_step="找数据同学确认最近两周的埋点和口径变更"))
        if index % 2 == 0:
            self.add(make_record(f"{pid}-extra", day(start + 6), kind="attempt", summary="用户补充了一次对照分析",
                                 problem={"id": pid}, methods=[method],
                                 user_work=[work("guided", "在提示下补了同期对照")]))
        fate = index % 5
        if fate == 0:
            self.add(make_record(f"{pid}-solved", day(start + 10), kind="follow_up", summary="回访：调整后指标恢复",
                                 problem={"id": pid, "status": "solved", "outcome": "指标回到基线，原因得到验证"}))
        elif fate == 1:
            self.add(make_record(f"{pid}-dropped", day(start + 12), summary="用户决定不再跟进这个问题",
                                 problem={"id": pid, "status": "dropped"}))
        elif fate == 3:
            self.add(make_record(f"{pid}-blocked", day(start + 5), summary="等待其他团队排期，暂时受阻",
                                 problem={"id": pid, "status": "blocked"}, unresolved="依赖方还没有给出排期"))
        elif fate == 4:
            self.add(make_record(f"{pid}-partial", day(start + 9), kind="follow_up", summary="回访：部分解决",
                                 problem={"id": pid, "status": "partial", "outcome": "新客转化回升一半",
                                          "check_back": {"when": "下次提到这个指标时", "question": "剩下一半找到原因了吗？"}}))

    def inject_senior_stage(self):
        """A second stage change stored as a v2.0 record (no basis), the shape existing data has."""
        value = make_record("stage-senior", day(35), kind="context_update", summary="用户升任资深，负责会员与增长两条线",
                            stage_update={"stage": "senior", "reason": "职责扩大到一条业务线"})
        value["schema_version"] = 2
        value["recorded_at"] = self.clock().isoformat(timespec="microseconds")
        records.validate_record(value, stored=True)
        atomic_write_json(self.root / "records" / "stage-senior.json", value)

    # ------------------------------------------------------------ checks

    def status(self, *extra):
        result = self.cli("--today", TODAY, "status", *extra)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout, json.loads(result.stdout)

    def test_history_has_the_intended_scale(self):
        view = self.view()
        self.assertGreaterEqual(len(view.records), 140)
        self.assertEqual(len(view.problems), 40)

    def test_compact_status_stays_small_and_points_to_full(self):
        raw, status = self.status()
        size = len(raw.encode("utf-8"))
        self.assertLessEqual(size, STATUS_BYTES_LIMIT, f"compact status is {size} bytes")
        self.assertTrue(status["truncated"])
        self.assertLessEqual(len(status["open_problems"]), 5)
        self.assertLessEqual(len(status["follow_ups_due"]), 10)
        self.assertLessEqual(len(status["stale_problems"]), 3)
        self.assertLessEqual(len(status["transfer_opportunities"]), 3)
        self.assertLessEqual(len(status["recent"]), 5)
        full_raw, full = self.status("--full")
        self.assertGreater(len(full_raw.encode("utf-8")), size)
        self.assertEqual(full["counts"], status["counts"])
        self.assertEqual(len(full["follow_ups_due"]), status["counts"]["follow_ups_due"] + status["counts"]["condition_pending"])

    def test_dropped_and_answered_check_backs_are_not_asked_again(self):
        _, full = self.status("--full")
        pending = {item["problem_id"] for item in full["follow_ups_due"]}
        # Dropped after the check-back (index % 5 == 1 with a check-back): retired.
        for pid in ("p01", "p16", "p21", "p36"):
            self.assertNotIn(pid, pending)
        # Answered by a follow_up (solved, or partial with no new check-back of the original kind).
        for pid in ("p00", "p05", "p20"):
            self.assertNotIn(pid, pending)
        # Still waiting: blocked or open with a dated check-back, and partial ones that set a new conditional.
        for pid in ("p08", "p12", "p28", "p32", "p04", "p09"):
            self.assertIn(pid, pending)

    def test_stale_problems_are_open_and_inactive_for_thirty_days(self):
        _, full = self.status("--full")
        stale = full["stale_problems"]
        self.assertGreater(len(stale), 3)
        self.assertEqual([item["last_date"] for item in stale], sorted(item["last_date"] for item in stale))
        today = date.fromisoformat(TODAY)
        for item in stale:
            self.assertIn(item["status"], records.OPEN_STATUSES)
            self.assertGreaterEqual((today - date.fromisoformat(item["last_date"])).days, records.STALE_DAYS)
        stale_ids = {item["problem_id"] for item in stale}
        _, compact = self.status()
        for item in compact["follow_ups_due"]:
            if item["status"] == "condition_pending":
                self.assertNotIn(item["problem_id"], stale_ids)

    def test_deferral_held_until_new_problems_with_attempts_arrived(self):
        self.assertFalse(self.after_defer_status["report"]["due"])
        self.assertTrue(self.after_defer_status["report"]["deferred"])
        _, status = self.status()
        cursor = status["report"]
        self.assertTrue(cursor["due"])
        self.assertEqual([reason["code"] for reason in cursor["reasons"]], ["problems"])
        self.assertEqual(cursor["reasons"][0]["problem_ids"], ["p33", "p34", "p35"])

    def test_focus_prior_stage_and_transfer_signals(self):
        _, status = self.status()
        self.assertEqual(status["stage"]["stage"], "senior")
        focus = {item["ability_id"]: item for item in status["focus"]["abilities"]}
        self.assertEqual(focus["data_validation"]["records_since_focus"], 3)
        self.assertEqual(focus["strategy_prioritization"]["records_since_focus"], 3)
        current = {item["ability_id"]: item for item in status["abilities"]["current"]}
        self.assertEqual(current["data_validation"]["level"], "unobserved")
        self.assertEqual(current["data_validation"]["prior"]["stage"], "independent_pm")
        self.assertEqual(current["data_validation"]["prior"]["level"], "independent")
        _, full = self.status("--full")
        methods = {item["method_id"] for item in full["transfer_opportunities"]}
        self.assertIn("jtbd", methods)
        self.assertNotIn("user-story", methods)
        log = (self.root / "growth-log.md").read_text(encoding="utf-8")
        self.assertIn("stage-senior", log)
        self.assertIn("焦点能力：", log)

    def test_report_over_the_whole_period_renders_overview_and_focus(self):
        draft = report.draft(self.root, today=TODAY)
        facts = draft["facts"]
        overview = {row["ability_id"]: row for row in facts["ability_overview"]}
        self.assertEqual(overview["data_validation"]["prior"]["stage_name"], "独立 PM")
        self.assertEqual(facts["focus"]["abilities"][0]["ability_id"], "data_validation")
        draft["narrative"] = {"headline": "八周模拟", "learned_summary": "以记录为准。", "problems_summary": "以记录为准。",
                              "growth_summary": "以证据为准。", "gaps": [], "next_focus": "继续观察。",
                              "message": "仅用于功能验证。"}
        result = report.build(self.root, draft, today=TODAY)
        html = Path(result["output"]).read_text(encoding="utf-8")
        for text in ("能力全景", "本期焦点", "独立 PM：可以独立", "述职前想把数据验证和取舍练扎实"):
            self.assertIn(text, html)
        _, after = self.status()
        self.assertFalse(after["report"]["due"])
        self.assertFalse(after["report"]["deferred"])
