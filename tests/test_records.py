import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from support import CLI, DataTestCase, make_record, problem, records, tree, work
from storage import atomic_write_json, file_lock


class DataDirectoryTest(DataTestCase):
    def test_precedence_is_flag_then_environment_then_home(self):
        with patch.dict(os.environ, {"PM_GROW_DATA_DIR": str(self.area / "env")}):
            self.assertEqual(records.data_root(), (self.area / "env").resolve())
            self.assertEqual(records.data_root(str(self.root)), self.root.resolve())
        with patch.dict(os.environ, {}, clear=True), patch.object(Path, "home", return_value=self.area):
            self.assertEqual(records.data_root(), (self.area / "pm-grow-data").resolve())

    def test_read_only_commands_never_create_the_directory(self):
        for arguments in (["status"], ["recent", "--limit", "3"], ["rebuild-index"], ["migrate", "--dry-run"]):
            with self.subTest(arguments=arguments):
                result = self.cli(*arguments)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(self.root.exists())
        status = self.cli_json("status")
        self.assertFalse(status["exists"])
        self.assertFalse(status["report"]["due"])
        self.assertEqual(status["follow_ups_due"], [])
        result = self.cli("report", "draft")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("没有可写入报告的新记录", result.stderr)
        self.assertFalse(self.root.exists())
        with self.assertRaises(ValueError):
            records.recent(self.root, limit=0)
        self.assertFalse(self.root.exists())

    def test_init_creates_v2_templates_and_preserves_existing_files(self):
        self.root.mkdir()
        (self.root / "profile.md").write_text("用户原有记录", encoding="utf-8")
        result = records.init(self.root)
        self.assertEqual((self.root / "profile.md").read_text(encoding="utf-8"), "用户原有记录")
        self.assertIn("profile.md", result["preserved"])
        self.assertEqual(sorted(result["created"]), ["business-context.md", "growth-log.md", "state.json"])
        self.assertEqual(records.load_state(self.root), records.default_state())
        self.assertFalse(result["migration_needed"])
        self.assertEqual(records.init(self.root)["created"], [])
        for name in ("records", "reports", "knowledge"):
            self.assertTrue((self.root / name).is_dir())


class RecordWriteTest(DataTestCase):
    def test_record_is_idempotent_and_conflicts_are_explicit(self):
        value = make_record("record-one", problem=problem("p1"), user_work=[work()], assistance="导师追问证据")
        result = self.add(value)
        self.assertTrue(result["created"])
        self.assertTrue(result["readback_verified"])
        path = self.root / "records" / "record-one.json"
        saved = path.read_bytes()
        self.assertFalse(self.add(value)["created"])
        self.assertEqual(path.read_bytes(), saved)
        with self.assertRaisesRegex(ValueError, "已存在且内容不同"):
            self.add(dict(value, summary="不同内容不能覆盖"))
        self.assertEqual(path.read_bytes(), saved)
        self.assertEqual(len(records.load_records(self.root)), 1)
        log = (self.root / "growth-log.md").read_text(encoding="utf-8")
        self.assertEqual(log.count("### 2026-10-04"), 1)
        self.assertFalse((self.root / "profile.md").exists())
        stored = json.loads(saved)
        self.assertEqual(stored["schema_version"], 2)
        self.assertIn("recorded_at", stored)

    def test_explicit_defaults_and_resubmission_compare_equal(self):
        value = make_record("base")
        self.add(value)
        correction = make_record("fix", kind="correction", corrections=[{"record_id": "base", "reason": "原描述有误"}])
        self.add(correction)
        explicit = dict(correction, schema_version=2, corrections=[{"record_id": "base", "reason": "原描述有误", "invalidate": False}])
        self.assertFalse(self.add(explicit)["created"])

    def test_invalid_records_are_rejected_without_creating_data(self):
        bad = [
            {"date": "2026-02-30"}, {"record_id": "../outside"}, {"record_id": "Upper"}, {"source": ""},
            {"summary": "  "}, {"kind": "chat"}, {"unexpected": "field"}, {"schema_version": 1},
            {"kind": "correction"}, {"kind": "follow_up"}, {"kind": "milestone"},
            {"problem": {"title": "缺 id"}}, {"problem": {"id": "p", "status": "done"}},
            {"problem": {"id": "p", "title": "t", "check_back": {"on": "2026-10-10"}}},
            {"problem": {"id": "p", "title": "t", "check_back": {"question": "问什么？"}}},
            {"problem": {"id": "p", "title": "t", "check_back": {"on": "2026-10-01", "question": "早于记录日期？"}}},
            {"problem": {"id": "p", "title": "t", "extra": 1}},
            {"user_work": [{"kind": "model_demo", "content": "x", "source": "y"}]},
            {"user_work": [{"kind": "independent", "content": "x"}]}, {"user_work": "not a list"},
            {"methods": ["Not A Slug"]}, {"methods": ["custom:"]}, {"methods": ["jtbd", "jtbd"]},
            {"observations": [{"ability_id": "made_up", "text": "x", "status": "candidate"}]},
            {"observations": [{"ability_id": "user_problem", "text": "x", "status": "maybe"}]},
            {"ability_updates": [{"ability_id": "user_problem", "stage": "senior", "from": "unobserved",
                                  "to": "unobserved", "evidence": [], "reason": "无变化"}]},
            {"ability_updates": [{"ability_id": "user_problem", "stage": "manager", "from": "unobserved",
                                  "to": "needs_support", "evidence": [], "reason": "r"}]},
            {"stage_update": {"stage": "director", "reason": "r"}}, {"stage_update": {"stage": "senior"}},
            {"preferences": "not a list"}, {"context_ref": ""}, {"next_step": ""},
            {"corrections": [{"reason": "缺目标"}]},
            {"corrections": [{"record_ref": "growth-log.md#x", "reason": "r", "invalidate": True}]},
            {"corrections": [{"record_id": "same", "reason": "不能更正自己"}], "record_id": "same"},
            {"migrated_from": "text"},
        ]
        for fields in bad:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.add(make_record("record-one", **fields))
        self.assertFalse(self.root.exists())

    def test_cross_record_rules(self):
        with self.assertRaisesRegex(ValueError, "更正目标记录不存在"):
            self.add(make_record("fix", kind="correction", corrections=[{"record_id": "missing", "reason": "悬空"}]))
        with self.assertRaisesRegex(ValueError, "第一次出现，需要 problem.title"):
            self.add(make_record("untitled", problem={"id": "new-problem"}))
        self.add(make_record("titled", problem=problem("new-problem")))
        self.add(make_record("later", problem={"id": "new-problem", "status": "blocked"}))
        with self.assertRaisesRegex(ValueError, "尚未注册"):
            self.add(make_record("custom", observations=[{"ability_id": "custom.ethics", "text": "x", "status": "candidate"}]))
        records.register_ability(self.root, {"id": "custom.ethics", "name": "伦理判断", "definition": "识别伤害",
                                             "observable_behaviors": ["列出受影响人群"]})
        self.add(make_record("custom", observations=[{"ability_id": "custom.ethics", "text": "x", "status": "candidate"}]))
        self.assertEqual(len(records.load_records(self.root)), 3)

    def test_write_order_is_monotonic_and_retry_keeps_timestamp(self):
        for identifier in ("record-z", "record-m", "record-a"):
            records.append_record(self.root, make_record(identifier), now=self.clock.value)
        loaded = records.load_records(self.root)
        self.assertEqual([item["record_id"] for item in loaded], ["record-z", "record-m", "record-a"])
        self.assertEqual(len({item["recorded_at"] for item in loaded}), 3)
        path = self.root / "records" / "record-z.json"
        saved = path.read_bytes()
        forged = dict(records.read_json(path), recorded_at="2099-01-01T00:00:00.000000+00:00")
        self.assertFalse(self.add(forged)["created"])
        self.assertEqual(path.read_bytes(), saved)
        self.assertEqual(records.recent(self.root, 1)["records"][0]["record_id"], "record-a")

    def test_display_order_uses_occurrence_date(self):
        for identifier, stamp in (("c", "2026-10-03"), ("a", "2026-10-01"), ("b", "2026-10-02")):
            self.add(make_record(identifier, stamp, context_ref="project-a" if identifier != "b" else "project-b"))
        self.assertEqual([item["record_id"] for item in records.recent(self.root, 2)["records"]], ["b", "c"])
        selected = records.recent(self.root, 5, context_ref="project-a")["records"]
        self.assertEqual([(item["record_id"], item["date"]) for item in selected], [("a", "2026-10-01"), ("c", "2026-10-03")])

    def test_recent_follows_correction_chains_and_problem_filter(self):
        self.add(make_record("original", "2026-10-01", problem=problem("p1"), context_ref="old-project"))
        self.add(make_record("correction-one", "2026-10-02", kind="correction",
                             corrections=[{"record_id": "original", "reason": "原职责描述有误", "invalidate": True}]))
        self.add(make_record("correction-two", "2026-10-03", kind="correction",
                             corrections=[{"record_id": "correction-one", "reason": "补充更正来源"}]))
        view = records.recent(self.root, 1, context_ref="old-project")
        self.assertEqual(view["records"][0]["record_id"], "original")
        self.assertEqual([item["record_id"] for item in view["related_records"]], ["correction-one", "correction-two"])
        self.assertEqual(view["invalidated"], {"original": ["correction-one"]})
        latest = records.recent(self.root, 1)
        self.assertEqual([item["record_id"] for item in latest["related_records"]], ["original", "correction-one"])
        self.assertEqual([item["record_id"] for item in records.recent(self.root, 5, problem_id="p1")["records"]], ["original"])
        self.assertEqual(records.read_json(self.root / "records" / "original.json")["summary"], make_record("x")["summary"])

    def test_invalidated_record_is_kept_but_excluded_and_reinstated_when_correction_is_invalidated(self):
        self.add(make_record("first", problem=problem("p1", status="solved", outcome="已上线")))
        self.add(make_record("void", kind="correction", corrections=[{"record_id": "first", "reason": "记错", "invalidate": True}]))
        view = self.view()
        self.assertNotIn("p1", view.problems)
        self.assertTrue((self.root / "records" / "first.json").exists())
        log = (self.root / "growth-log.md").read_text(encoding="utf-8")
        self.assertIn("已作废：被 void 更正，不参与推导", log)
        self.add(make_record("undo", kind="correction", corrections=[{"record_id": "void", "reason": "更正本身有误", "invalidate": True}]))
        self.assertEqual(self.view().problems["p1"]["status"], "solved")

    def test_problem_fields_merge_in_write_order(self):
        self.add(make_record("one", "2026-10-05", problem=problem("p1", "旧标题", scenario="feature-request")))
        self.add(make_record("two", "2026-10-03", problem={"id": "p1", "title": "新标题", "status": "partial"}))
        merged = self.view().problems["p1"]
        self.assertEqual((merged["title"], merged["scenario"], merged["status"]), ("新标题", "feature-request", "partial"))
        self.assertEqual((merged["first_date"], merged["last_date"]), ("2026-10-03", "2026-10-05"))

    def test_manual_growth_log_text_and_line_endings_survive(self):
        self.root.mkdir()
        original = "# 旧人工档案\r\n\r\n## 手写记录\r\n原来源与手写正文保留。\r\n".encode("utf-8")
        path = self.root / "growth-log.md"
        path.write_bytes(original)
        self.add(make_record("record-one", kind="correction", corrections=[{
            "record_ref": "growth-log.md#手写记录", "reason": "原结论暂未证实"}]))
        path.write_bytes(path.read_bytes() + "\n## 新人工记录\n保留后缀。\n".encode("utf-8"))
        result = records.rebuild_index(self.root)
        content = path.read_bytes()
        self.assertTrue(result["rebuilt"])
        self.assertTrue(content.startswith(original))
        self.assertTrue(content.endswith("\n## 新人工记录\n保留后缀。\n".encode("utf-8")))
        self.assertEqual(content.decode("utf-8").count(records.LOG_START), 1)
        self.assertIn("更正：growth-log.md#手写记录", content.decode("utf-8"))
        path.write_text(path.read_text(encoding="utf-8").replace(records.LOG_END, ""), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "标记不完整"):
            records.rebuild_index(self.root)

    def test_index_markup_is_escaped(self):
        self.add(make_record("record-one", summary="<script>alert(1)</script>"))
        log = (self.root / "growth-log.md").read_text(encoding="utf-8")
        self.assertNotIn("<script>alert", log)
        self.assertIn("&lt;script&gt;", log)

    def test_record_survives_index_failure_and_retry_repairs_it(self):
        value = make_record("record-one")
        with patch.object(records, "write_index", side_effect=OSError("simulated index interruption")):
            with self.assertRaises(OSError):
                self.add(value)
        self.assertEqual(len(records.load_records(self.root)), 1)
        self.assertFalse((self.root / "growth-log.md").exists())
        self.assertFalse(self.add(value)["created"])
        self.assertIn("record-one", (self.root / "growth-log.md").read_text(encoding="utf-8"))

    def test_unmigrated_v1_data_blocks_new_records(self):
        (self.root / "events").mkdir(parents=True)
        (self.root / "events" / "old.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "先运行 migrate"):
            self.add(make_record("record-one"))
        self.assertFalse((self.root / "records").exists())
        self.assertTrue(records.status(self.root)["migration_needed"])

    def test_malformed_stored_record_fails_closed(self):
        self.add(make_record("record-one"))
        (self.root / "records" / "bad.json").write_text(json.dumps(make_record("bad")), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "recorded_at"):
            records.status(self.root)
        (self.root / "records" / "bad.json").write_text(json.dumps(
            dict(records.read_json(self.root / "records" / "record-one.json"), record_id="other")), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "文件名与 record_id 不一致"):
            records.load_records(self.root)


class CommandLineTest(DataTestCase):
    def test_record_reads_stdin_and_files(self):
        result = self.cli_json("record", "--input", "-", stdin=json.dumps(make_record("from-stdin"), ensure_ascii=False))
        self.assertTrue(result["created"])
        path = self.write_json("input.json", make_record("from-file"))
        self.assertTrue(self.cli_json("record", "--input", str(path))["created"])
        failed = self.cli("record", "--input", "-", stdin="{not json")
        self.assertNotEqual(failed.returncode, 0)
        self.assertTrue(failed.stderr.startswith("错误："))

    def test_global_options_work_after_the_subcommand(self):
        result = subprocess.run([sys.executable, "-B", str(CLI), "status", "--data-dir", str(self.root), "--today", "2026-10-19"],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["today"], "2026-10-19")
        self.assertNotEqual(self.cli("--today", "2026-13-01", "status").returncode, 0)

    def test_concurrent_writers_keep_every_record_and_index_entry(self):
        values = [make_record(f"concurrent-{index}", problem=problem(f"p{index}"), user_work=[work()]) for index in range(10)]
        values += [values[0]] * 3
        processes = [subprocess.Popen([sys.executable, "-B", str(CLI), "--data-dir", str(self.root), "record", "--input", "-"],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                     for _ in values]
        for process, value in zip(processes, values):
            process.stdin.write(json.dumps(value, ensure_ascii=False))
            process.stdin.close()
        for process in processes:
            process.wait(timeout=60)
            stdout, stderr = process.stdout.read(), process.stderr.read()
            process.stdout.close()
            process.stderr.close()
            self.assertEqual(process.returncode, 0, stderr)
            self.assertTrue(json.loads(stdout)["readback_verified"])
        loaded = records.load_records(self.root)
        self.assertEqual(len(loaded), 10)
        self.assertEqual(len({item["recorded_at"] for item in loaded}), 10)
        content = (self.root / "growth-log.md").read_text(encoding="utf-8")
        for index in range(10):
            self.assertEqual(content.count(f"· concurrent-{index}\n"), 1)

    def test_lock_timeout_and_release_after_exception(self):
        path = self.write_json("input.json", make_record("record-one"))
        with file_lock(self.root):
            result = self.cli("--lock-timeout", "0.05", "record", "--input", str(path))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Timed out waiting for data lock", result.stderr)
        self.assertFalse((self.root / "records").exists())
        with self.assertRaisesRegex(RuntimeError, "deliberate"):
            with file_lock(self.root):
                raise RuntimeError("deliberate")
        records.append_record(self.root, make_record("record-one"), timeout=0.1)
        self.assertTrue((self.root / "records" / "record-one.json").exists())

    def test_failed_atomic_write_preserves_original_and_cleans_temporary_files(self):
        path = self.root / "sample.json"
        atomic_write_json(path, {"original": True})
        with self.assertRaises(TypeError):
            atomic_write_json(path, {"bad": {1, 2}})
        self.assertEqual(records.read_json(path), {"original": True})
        self.assertEqual(list(self.root.glob(".pm-grow-*")), [])

    def test_rebuild_index_command(self):
        self.add(make_record("record-one"))
        (self.root / "growth-log.md").unlink()
        self.assertTrue(self.cli_json("rebuild-index")["rebuilt"])
        self.assertIn("record-one", (self.root / "growth-log.md").read_text(encoding="utf-8"))
        before = tree(self.root)
        self.cli_json("status")
        self.assertEqual(tree(self.root), before)


if __name__ == "__main__":
    unittest.main()
