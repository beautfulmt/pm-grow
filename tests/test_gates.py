"""Write-time gates for ability and stage changes, and reference checks (v2.1)."""
import json

from support import DataTestCase, attempt, make_record, observe, problem, records, review, upgrade, work


class GateTestCase(DataTestCase):
    def store(self, value):
        """Write a record straight to disk, as an older install would have, bypassing write-time gates."""
        value = dict(value, schema_version=2, recorded_at=self.clock().isoformat(timespec="microseconds"))
        (self.root / "records").mkdir(parents=True, exist_ok=True)
        records.atomic_write_json(self.root / "records" / f"{value['record_id']}.json", value)
        return value

    def level(self, ability_id, stage="independent_pm"):
        return self.view().level(ability_id, stage)


class EvidenceRelevanceTest(GateTestCase):
    def test_unrelated_evidence_cannot_upgrade_another_ability(self):
        # Probe 1: two data-analysis records used to raise team_leadership.
        self.add(attempt("a1", "p1", "2026-10-01", ability="data_validation"))
        self.add(attempt("a2", "p2", "2026-10-02", ability="data_validation"))
        with self.assertRaisesRegex(ValueError, "没有针对「团队领导与人才培养」的观察"):
            self.add(make_record("up", "2026-10-03", kind="review",
                                 ability_updates=[upgrade("team_leadership", ["a1", "a2"], stage="lead")]))
        self.assertEqual(self.level("team_leadership", "lead"), "unobserved")
        result = self.add(make_record("up", "2026-10-03", kind="review",
                                      ability_updates=[upgrade("data_validation", ["a1", "a2"])]))
        self.assertEqual(result["ability_changes"][0]["to"], "independent")
        self.assertEqual(self.level("data_validation"), "independent")

    def test_withdrawn_or_other_ability_observations_do_not_count(self):
        self.add(attempt("a1", "p1", "2026-10-01", observations=[observe("data_validation", "withdrawn")]))
        self.add(attempt("a2", "p2", "2026-10-02", observations=[observe("user_problem")]))
        with self.assertRaises(ValueError) as caught:
            self.add(make_record("up", "2026-10-03", ability_updates=[upgrade("data_validation", ["a1", "a2"])]))
        message = str(caught.exception)
        self.assertIn("证据记录 a1 没有针对「数据分析与效果验证」的观察", message)
        self.assertIn("证据记录 a2 没有针对「数据分析与效果验证」的观察", message)
        self.assertFalse((self.root / "records" / "up.json").exists())

    def test_padding_with_one_unrelated_record_fails_the_update(self):
        self.add(attempt("a1", "p1", "2026-10-01", ability="data_validation"))
        self.add(attempt("a2", "p2", "2026-10-02", ability="data_validation"))
        self.add(attempt("other", "p3", "2026-10-02", ability="user_problem"))
        with self.assertRaisesRegex(ValueError, "证据记录 other 没有针对"):
            self.add(make_record("up", "2026-10-03", ability_updates=[upgrade("data_validation", ["a1", "a2", "other"])]))


class LevelStepTest(GateTestCase):
    def three_attempts(self, ability="data_validation"):
        for index, stamp in enumerate(("2026-10-01", "2026-10-02", "2026-10-03"), start=1):
            self.add(attempt(f"a{index}", f"p{index}", stamp, ability=ability))

    def test_jumping_straight_to_stable_is_rejected(self):
        # Probe 2: unobserved -> stable in one update with three days of data.
        self.three_attempts()
        with self.assertRaisesRegex(ValueError, "能力不能跳级.*目前是「未观察」，这次最多升到「可以独立」"):
            self.add(make_record("jump", "2026-10-03", ability_updates=[
                upgrade("data_validation", ["a1", "a2", "a3"], to="stable", reviewed=review())]))
        self.assertEqual(self.level("data_validation"), "unobserved")

    def test_unobserved_may_go_straight_to_independent(self):
        self.add(attempt("a1", "p1", "2026-10-01", ability="user_problem"))
        self.add(attempt("a2", "p2", "2026-10-08", ability="user_problem"))
        self.add(make_record("up", "2026-10-08", ability_updates=[upgrade("user_problem", ["a1", "a2"])]))
        self.assertEqual(self.level("user_problem"), "independent")

    def test_needs_support_cannot_jump_to_stable_and_downgrades_may_skip(self):
        self.add(attempt("g1", "p0", "2026-09-20", kind="guided", ability="data_validation"))
        self.add(make_record("first", "2026-09-20", ability_updates=[
            upgrade("data_validation", ["g1"], to="needs_support")]))
        self.three_attempts()
        with self.assertRaisesRegex(ValueError, "目前是「需要支持」，这次最多升到「可以独立」"):
            self.add(make_record("jump", "2026-10-03", ability_updates=[
                upgrade("data_validation", ["a1", "a2", "a3"], to="stable", source="needs_support", reviewed=review())]))
        self.add(make_record("step", "2026-10-03", ability_updates=[
            upgrade("data_validation", ["a1", "a2"], source="needs_support")]))
        self.assertEqual(self.level("data_validation"), "independent")
        self.add(make_record("down", "2026-10-04", kind="correction",
                             corrections=[{"record_id": "step", "reason": "隔离测试：复核后发现拆解由导师完成"}],
                             ability_updates=[upgrade("data_validation", [], to="unobserved", source="independent")]))
        self.assertEqual(self.level("data_validation"), "unobserved")


class DatesSpanAndReviewTest(GateTestCase):
    def test_independent_needs_evidence_from_two_dates(self):
        self.add(attempt("a1", "p1", "2026-10-01", ability="data_validation"))
        self.add(attempt("a2", "p2", "2026-10-01", ability="data_validation"))
        with self.assertRaisesRegex(ValueError, "至少 2 个不同日期，目前只有 2026-10-01"):
            self.add(make_record("up", "2026-10-01", ability_updates=[upgrade("data_validation", ["a1", "a2"])]))
        self.add(attempt("a3", "p3", "2026-10-06", ability="data_validation"))
        self.add(make_record("up", "2026-10-06", ability_updates=[upgrade("data_validation", ["a1", "a3"])]))
        self.assertEqual(self.level("data_validation"), "independent")

    def build_independent(self, dates=("2026-10-01", "2026-10-05", "2026-10-08")):
        for index, stamp in enumerate(dates, start=1):
            self.add(attempt(f"a{index}", f"p{index}", stamp, ability="data_validation"))
        self.add(make_record("ind", dates[-1], ability_updates=[
            upgrade("data_validation", [f"a{index}" for index in range(1, len(dates) + 1)])]))

    def test_stable_needs_a_fourteen_day_span(self):
        self.build_independent()
        self.add(attempt("a4", "p4", "2026-10-16", ability="data_validation"))
        with self.assertRaisesRegex(ValueError, "相隔至少 14 天，目前 2026-10-05 到 2026-10-16 相隔 11 天"):
            self.add(make_record("stable", "2026-10-16", ability_updates=[upgrade(
                "data_validation", ["a2", "a3", "a4"], to="stable", source="independent", reviewed=review())]))
        self.add(make_record("stable", "2026-10-16", ability_updates=[upgrade(
            "data_validation", ["a1", "a3", "a4"], to="stable", source="independent", reviewed=review())]))
        self.assertEqual(self.level("data_validation"), "stable")

    def test_stable_needs_fresh_evidence_since_independent(self):
        self.build_independent(("2026-10-01", "2026-10-05", "2026-10-16"))
        with self.assertRaisesRegex(ValueError, "至少需要 1 条升到「可以独立」之后的新证据"):
            self.add(make_record("stable", "2026-10-16", ability_updates=[upgrade(
                "data_validation", ["a1", "a2", "a3"], to="stable", source="independent", reviewed=review())]))
        self.add(attempt("a4", "p4", "2026-10-20", ability="data_validation"))
        self.add(make_record("stable", "2026-10-20", ability_updates=[upgrade(
            "data_validation", ["a1", "a2", "a4"], to="stable", source="independent", reviewed=review())]))
        self.assertEqual(self.level("data_validation"), "stable")

    def test_stable_needs_a_recorded_review(self):
        self.build_independent()
        self.add(attempt("a4", "p4", "2026-10-20", ability="data_validation"))
        evidence = ["a1", "a2", "a4"]
        with self.assertRaisesRegex(ValueError, "需要 growth-reviewer 复核：在这条 ability_update 里写 review"):
            self.add(make_record("stable", "2026-10-20", ability_updates=[
                upgrade("data_validation", evidence, to="stable", source="independent")]))
        result = self.add(make_record("stable", "2026-10-20", ability_updates=[upgrade(
            "data_validation", evidence, to="stable", source="independent", reviewed=review("self_check"))]))
        change = result["ability_changes"][0]
        self.assertEqual(change["review"]["mode"], "self_check")
        self.assertEqual(change["review"]["mode_name"], "主导师自查")
        view = self.view()
        last = view.levels[("data_validation", "independent_pm")]["changes"][-1]
        self.assertEqual(records.change_summary(view, last)["review"]["summary"], review()["summary"])

    def test_review_shape_is_validated(self):
        bad = [{"mode": "maybe", "summary": "x"}, {"mode": "agent", "summary": " "}, {"mode": "agent"},
               {"mode": "agent", "summary": "x", "extra": 1}, "agent"]
        for value in bad:
            with self.subTest(review=value), self.assertRaises(ValueError):
                self.add(make_record("bad", ability_updates=[dict(upgrade("user_problem", []), review=value)]))
            with self.subTest(stage_review=value), self.assertRaises(ValueError):
                self.add(make_record("bad", stage_update={"stage": "senior", "reason": "r", "review": value}))
        self.assertFalse(self.root.exists())


class StageGateTest(GateTestCase):
    def stage(self, identifier, stage, stamp="2026-10-04", **fields):
        return make_record(identifier, stamp, kind="context_update",
                           stage_update={"stage": stage, "reason": "隔离测试中的职责说明", **fields})

    def test_first_positioning_needs_no_basis(self):
        self.add(self.stage("first", "independent_pm"))
        self.assertEqual(self.view().stage["stage"], "independent_pm")
        other = self.area / "other"
        self.add(self.stage("first", "senior", basis="initial"), root=other)
        with self.assertRaisesRegex(ValueError, "第一次定位省略 basis 或写 initial"):
            self.add(self.stage("first", "senior", basis="role_change"), root=self.area / "third")

    def test_later_changes_need_an_honest_basis(self):
        self.add(self.stage("first", "newcomer"))
        with self.assertRaisesRegex(ValueError, "调整阶段需要写 basis"):
            self.add(self.stage("second", "independent_pm"))
        with self.assertRaisesRegex(ValueError, "basis 不能是 initial"):
            self.add(self.stage("second", "independent_pm", basis="initial"))
        with self.assertRaisesRegex(ValueError, "阶段没有变化"):
            self.add(self.stage("second", "newcomer", basis="role_change"))
        self.add(self.stage("second", "senior", basis="role_change"))
        self.assertEqual((self.view().stage["stage"], self.view().stage["basis"]), ("senior", "role_change"))
        self.add(self.stage("third", "independent_pm", basis="correction"))
        self.assertEqual(self.view().stage["stage"], "independent_pm")
        with self.assertRaises(ValueError):
            self.add(self.stage("fourth", "senior", basis="promotion"))

    def stable_ability(self, ability, prefix):
        """Raise one ability to stable in independent_pm with evidence spanning 19 days."""
        dates = ("2026-10-01", "2026-10-05", "2026-10-20")
        for index, stamp in enumerate(dates, start=1):
            self.add(attempt(f"{prefix}{index}", f"{prefix}-p{index}", stamp, ability=ability))
        self.add(make_record(f"{prefix}-ind", "2026-10-05", ability_updates=[
            upgrade(ability, [f"{prefix}1", f"{prefix}2"])]))
        return upgrade(ability, [f"{prefix}1", f"{prefix}2", f"{prefix}3"], to="stable", source="independent",
                       reviewed=review())

    def test_performance_promotion_needs_two_stable_abilities_and_a_review(self):
        self.add(self.stage("first", "independent_pm", "2026-09-30"))
        self.add(make_record("dv-stable", "2026-10-20", ability_updates=[self.stable_ability("data_validation", "d")]))
        with self.assertRaises(ValueError) as caught:
            self.add(self.stage("promote", "senior", "2026-10-21", basis="performance"))
        message = str(caught.exception)
        self.assertIn("至少 2 项能力达到「复杂情境稳定」，目前 1 项（数据分析与效果验证）", message)
        self.assertIn("按表现升阶前需要 growth-reviewer 复核", message)
        second = self.stable_ability("user_problem", "u")
        with self.assertRaisesRegex(ValueError, "按表现升阶前需要 growth-reviewer 复核"):
            self.add(make_record("promote", "2026-10-21", ability_updates=[second],
                                 stage_update={"stage": "senior", "reason": "连续表现超出", "basis": "performance"}))
        # Raising the second ability and promoting in the same record counts toward the gate.
        self.add(make_record("promote", "2026-10-21", ability_updates=[second],
                             stage_update={"stage": "senior", "reason": "连续表现超出", "basis": "performance",
                                           "review": review()}))
        stage = self.view().stage
        self.assertEqual((stage["stage"], stage["basis"], stage["review"]["mode"]), ("senior", "performance", "agent"))

    def test_performance_is_only_for_promotions(self):
        self.add(self.stage("first", "senior"))
        with self.assertRaisesRegex(ValueError, "performance 只用于升阶"):
            self.add(self.stage("second", "independent_pm", basis="performance", review=review()))
        self.add(self.stage("second", "lead", basis="role_change"))
        with self.assertRaisesRegex(ValueError, "performance 只用于升阶"):
            self.add(self.stage("third", "expert", basis="performance", review=review()))

    def test_legacy_stage_updates_without_basis_still_load(self):
        self.store(self.stage("first", "independent_pm", "2026-09-01"))
        self.store(self.stage("second", "senior", "2026-10-01"))
        stage = self.view().stage
        self.assertEqual(stage["stage"], "senior")
        self.assertNotIn("basis", stage)
        self.add(self.stage("third", "lead", "2026-10-21", basis="role_change"))
        self.assertEqual(self.view().stage["stage"], "lead")


class LegacyDerivationTest(GateTestCase):
    def test_stored_upgrades_are_never_voided_by_the_new_rules(self):
        for index in (1, 2, 3):
            self.add(attempt(f"a{index}", f"p{index}", "2026-10-01"))
        self.store(make_record("old-upgrade", "2026-10-01", ability_updates=[
            upgrade("data_validation", ["a1", "a2", "a3"], to="stable")]))
        view = self.view()
        self.assertEqual(view.level("data_validation", "independent_pm"), "stable")
        self.assertEqual(view.voided, [])
        self.add(make_record("later", "2026-10-02"))
        self.assertEqual(self.level("data_validation"), "stable")


class ReferenceCheckTest(GateTestCase):
    def test_misspelled_method_and_scenario_are_rejected_with_suggestions(self):
        # Probe 3: typos used to be stored and shown in reports.
        with self.assertRaisesRegex(ValueError, "methods\\[0\\] 不是已有的方法卡：metric-diagnosys；你是不是想写 metric-diagnosis？"):
            self.add(make_record("typo", methods=["metric-diagnosys"]))
        with self.assertRaisesRegex(ValueError, "problem.scenario 不是已有的场景：metric-anomally；你是不是想写 metric-anomaly？"):
            self.add(make_record("typo", problem=problem("p1", scenario="metric-anomally")))
        with self.assertRaisesRegex(ValueError, "不是已有的场景：index"):
            self.add(make_record("typo", problem=problem("p1", scenario="index")))
        self.assertFalse((self.root / "records" / "typo.json").exists())
        self.add(make_record("ok", methods=["metric-diagnosis", "custom:按直播场次拆分"],
                             problem=problem("p1", scenario="metric-anomaly")))
        self.assertEqual(self.view().problems["p1"]["scenario"], "metric-anomaly")

    def test_stored_records_with_retired_ids_still_load(self):
        self.store(make_record("old", methods=["retired-method"], problem=problem("p1", scenario="retired-scenario")))
        self.assertEqual(records.load_records(self.root)[0]["methods"], ["retired-method"])
        self.assertEqual(self.view().problems["p1"]["scenario"], "retired-scenario")
        self.add(make_record("next", methods=["jtbd"]))
        self.assertEqual(len(records.load_records(self.root)), 2)

    def test_command_line_reports_the_reason(self):
        result = self.cli("record", "--input", "-", stdin=json.dumps(
            make_record("typo", methods=["prioritisation"], user_work=[work()]), ensure_ascii=False))
        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stderr.startswith("错误："))
        self.assertIn("你是不是想写 prioritization？", result.stderr)


if __name__ == "__main__":
    import unittest
    unittest.main()
