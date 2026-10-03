import copy
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "memory.py"
spec = importlib.util.spec_from_file_location("memory", SCRIPT)
memory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(memory)


class MemoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.area = Path(self.temp.name)
        self.root = self.area / "isolated-data"

    def tearDown(self):
        self.temp.cleanup()

    def event(self, identifier="event-one", stamp="2026-10-04", **fields):
        return {"event_id": identifier, "date": stamp, "kind": "exploration",
                "summary": "隔离测试：方案仍在探索，未形成能力评价。",
                "source": "隔离测试输入，非真实个人档案", **fields}

    def test_data_directory_precedence(self):
        with patch.dict(os.environ, {"PM_GROW_DATA_DIR": str(self.area / "env")}):
            self.assertEqual(memory.data_root(), (self.area / "env").resolve())
            self.assertEqual(memory.data_root(str(self.root)), self.root.resolve())
        with patch.dict(os.environ, {}, clear=True), patch.object(Path, "home", return_value=self.area):
            self.assertEqual(memory.data_root(), (self.area / "pm-grow-data").resolve())

    def test_read_only_does_not_initialize(self):
        self.assertEqual(memory.recent(self.root)["events"], [])
        self.assertFalse(self.root.exists())
        result = subprocess.run([sys.executable, str(SCRIPT), "--data-dir", str(self.root),
                                 "recent", "--limit", "3"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["events"], [])
        self.assertFalse(self.root.exists())
        with self.assertRaises(ValueError):
            memory.recent(self.root, limit=0)
        self.assertFalse(self.root.exists())

    def test_append_is_idempotent_and_conflict_is_explicit(self):
        value = self.event(user_contribution="用户给出假设", assistance="导师提出核实问题")
        self.assertTrue(memory.append_event(self.root, value)["created"])
        path = self.root / "events" / "event-one.json"
        saved = path.read_bytes()
        self.assertFalse(memory.append_event(self.root, value)["created"])
        self.assertEqual(path.read_bytes(), saved)
        self.assertEqual(len(memory.load_events(self.root)), 1)
        conflict = dict(value, summary="不同内容不能覆盖")
        with self.assertRaisesRegex(ValueError, "Conflicting event_id event-one"):
            memory.append_event(self.root, conflict)
        self.assertEqual(path.read_bytes(), saved)
        self.assertEqual((self.root / "growth-log.md").read_text(encoding="utf-8").count("### 2026-10-04"), 1)
        self.assertFalse((self.root / "cases").exists())
        self.assertFalse((self.root / "profile.md").exists())

    def test_recent_keeps_original_dates_and_filters(self):
        values = [self.event("event-c", "2026-10-03", case_id="case-a", context_ref="project-a"),
                  self.event("event-a", "2026-10-01", case_id="case-a", context_ref="project-a"),
                  self.event("event-b", "2026-10-02", case_id="case-a", context_ref="project-b"),
                  self.event("event-d", "2026-10-03", case_id="case-b", context_ref="project-a")]
        for value in values:
            memory.append_event(self.root, value)
        self.assertEqual([e["event_id"] for e in memory.recent(self.root, 2)["events"]], ["event-c", "event-d"])
        selected = memory.recent(self.root, 5, case_id="case-a", context_ref="project-a")["events"]
        self.assertEqual([(e["event_id"], e["date"]) for e in selected],
                         [("event-a", "2026-10-01"), ("event-c", "2026-10-03")])

    def test_same_day_reverse_ids_follow_write_order_and_retry_keeps_timestamp(self):
        fixed = datetime(2026, 10, 4, 3, 0, tzinfo=timezone.utc)
        with patch.object(memory, "datetime", wraps=datetime) as clock:
            clock.now.return_value = fixed
            for identifier in ("event-z", "event-m", "event-a"):
                memory.append_event(self.root, self.event(identifier))
        self.assertEqual([event["event_id"] for event in memory.recent(self.root, 2)["events"]],
                         ["event-m", "event-a"])
        events = memory.load_events(self.root)
        self.assertEqual([event["recorded_at"] for event in events], sorted({event["recorded_at"] for event in events}))
        path = self.root / "events" / "event-z.json"
        saved = path.read_bytes()
        self.assertFalse(memory.append_event(self.root, self.event("event-z"))["created"])
        self.assertEqual(path.read_bytes(), saved)
        forged = dict(memory.read_json(path), recorded_at="2099-01-01T00:00:00.000000+00:00")
        self.assertFalse(memory.append_event(self.root, forged)["created"])
        self.assertEqual(path.read_bytes(), saved)
        self.assertEqual(memory.recent(self.root, 1)["events"][0]["event_id"], "event-a")
        self.assertEqual(memory.read_json(path)["date"], "2026-10-04")

    def test_legacy_events_without_write_time_remain_unchanged(self):
        directory = self.root / "events"
        directory.mkdir(parents=True)
        for identifier in ("legacy-z", "legacy-a"):
            (directory / f"{identifier}.json").write_text(json.dumps(self.event(identifier)), encoding="utf-8")
        saved = (directory / "legacy-z.json").read_bytes()
        self.assertFalse(memory.append_event(self.root, self.event("legacy-z"))["created"])
        self.assertEqual((directory / "legacy-z.json").read_bytes(), saved)
        memory.append_event(self.root, self.event("new-a"))
        self.assertEqual([event["event_id"] for event in memory.recent(self.root, 3)["events"]],
                         ["legacy-a", "legacy-z", "new-a"])
        self.assertNotIn("recorded_at", memory.read_json(directory / "legacy-z.json"))

    def test_corrections_keep_original_sources_and_follow_chains(self):
        original = self.event("original", "2026-10-01", context_ref="old-project")
        correction = self.event("correction-one", "2026-10-02", kind="correction",
                                corrections=[{"event_id": "original", "reason": "原职责描述有误"}])
        followup = self.event("correction-two", "2026-10-03", kind="correction",
                              corrections=[{"event_id": "correction-one", "reason": "补充更正来源"}])
        for value in (original, correction, followup):
            memory.append_event(self.root, value)
        view = memory.recent(self.root, 1, context_ref="old-project")
        self.assertEqual(view["events"][0]["source"], original["source"])
        self.assertEqual([e["event_id"] for e in view["related_events"]], ["correction-one", "correction-two"])
        latest = memory.recent(self.root, 1)
        self.assertEqual([e["event_id"] for e in latest["related_events"]], ["original", "correction-one"])
        self.assertEqual(memory.read_json(self.root / "events" / "original.json")["summary"], original["summary"])

    def test_legacy_correction_and_manual_markdown_survive_rebuild(self):
        self.root.mkdir()
        path = self.root / "growth-log.md"
        original = "# 旧人工档案\n\n## 2026-09-30 学习记录\n原来源与手写正文保留。\n"
        path.write_text(original, encoding="utf-8")
        memory.append_event(self.root, self.event(kind="correction", corrections=[{
            "record_ref": "growth-log.md#2026-09-30 学习记录", "reason": "原结论暂未证实"}]))
        path.write_text(path.read_text(encoding="utf-8") + "\n## 新人工记录\n保留后缀。\n", encoding="utf-8")
        result = memory.rebuild_log(self.root)
        content = path.read_text(encoding="utf-8")
        self.assertTrue(result["rebuilt"])
        self.assertTrue(content.startswith(original))
        self.assertTrue(content.endswith("\n## 新人工记录\n保留后缀。\n"))
        self.assertEqual(content.count(memory.START), 1)
        self.assertIn("更正关联：growth-log.md#2026-09-30 学习记录", content)

    def test_event_survives_index_failure_and_retry_repairs_it(self):
        value = self.event()
        with patch.object(memory, "write_log", side_effect=OSError("simulated index interruption")):
            with self.assertRaises(OSError):
                memory.append_event(self.root, value)
        self.assertEqual(len(memory.load_events(self.root)), 1)
        self.assertFalse((self.root / "growth-log.md").exists())
        self.assertFalse(memory.append_event(self.root, value)["created"])
        self.assertIn("event-one", (self.root / "growth-log.md").read_text(encoding="utf-8"))

    def test_manual_windows_line_endings_are_preserved(self):
        self.root.mkdir()
        original = "# 人工记录\r\n\r\n保留原换行。\r\n".encode("utf-8")
        path = self.root / "growth-log.md"
        path.write_bytes(original)
        memory.append_event(self.root, self.event())
        memory.rebuild_log(self.root)
        self.assertTrue(path.read_bytes().startswith(original))

    def test_invalid_events_and_missing_correction_targets_are_rejected(self):
        for fields in ({"date": "2026-02-30"}, {"event_id": "../outside"}, {"source": ""},
                       {"kind": "correction"}, {"preferences": "not a list"}, {"unexpected": "field"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                memory.append_event(self.root, self.event(**fields))
        self.assertFalse(self.root.exists())
        with self.assertRaisesRegex(ValueError, "target event does not exist"):
            memory.append_event(self.root, self.event(kind="correction", corrections=[{
                "event_id": "missing", "reason": "不允许悬空事件关联"}]))
        self.assertEqual(memory.load_events(self.root), [])

    def test_concurrent_appends_keep_every_event_and_summary(self):
        values = [self.event(f"concurrent-{i}") for i in range(10)]
        values += [copy.deepcopy(values[0]) for _ in range(3)]
        processes = []
        for i, value in enumerate(values):
            source = self.area / f"input-{i}.json"
            source.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            processes.append(subprocess.Popen([sys.executable, str(SCRIPT), "--data-dir", str(self.root),
                                               "append-event", "--input", str(source)],
                                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        for process in processes:
            stdout, stderr = process.communicate(timeout=20)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertTrue(json.loads(stdout)["readback_verified"])
        self.assertEqual(len(memory.load_events(self.root)), 10)
        content = (self.root / "growth-log.md").read_text(encoding="utf-8")
        self.assertEqual(content.count("### 2026-10-04"), 10)
        for i in range(10):
            self.assertEqual(content.count(f"· concurrent-{i}\n"), 1)


if __name__ == "__main__":
    unittest.main()
