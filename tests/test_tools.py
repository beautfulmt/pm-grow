"""Exercise redaction of mistakenly recorded text and handbook topic maintenance."""
import json
from pathlib import Path

from support import DataTestCase, make_record, problem, tree, work
import handbook
import migrate
import records
import redact
import report

SECRET = "星河科技"
UNIT = "R&D 中心"
REQUEST = {"replacements": [{"find": SECRET, "replace": "[客户A]"}, {"find": UNIT, "replace": "[部门B]"}],
           "label": "隔离测试：去掉客户名与部门名"}


def narrative(headline):
    return {"headline": headline, "learned_summary": "隔离模拟。", "problems_summary": "以原始记录为准。",
            "growth_summary": "以证据为准。", "gaps": [], "next_focus": "等待实际结果。", "message": f"和 {UNIT} 对齐"}


def topic(identifier="client-map", title="客户决策链", content=None, **fields):
    value = {"id": identifier, "title": title,
             "sections": [{"heading": "案例", "content": content or "隔离模拟的决策链案例"}],
             "sources": [{"title": "隔离测试会谈", "locator": "隔离测试材料", "checked_on": "2026-10-01"}]}
    value.update(fields)
    return value


def leaks(root, *needles):
    """Files under root that still contain any of the needles (raw or HTML-escaped)."""
    import html
    forms = {form.encode("utf-8") for needle in needles
             for form in (needle, html.escape(needle, quote=False), html.escape(needle, quote=True))}
    return sorted(path.relative_to(root).as_posix() for path in Path(root).rglob("*")
                  if path.is_file() and any(form in path.read_bytes() for form in forms))


class RedactTest(DataTestCase):
    def seed(self):
        records.init(self.root)
        profile = self.root / "profile.md"
        profile.write_text(profile.read_text(encoding="utf-8") + f"\n- 服务客户：{SECRET}\n", encoding="utf-8")
        self.add(make_record(
            "visit-one", "2026-10-01", kind="attempt", summary=f"拜访{SECRET}的采购负责人", source=f"{SECRET}会议纪要",
            problem=problem("renewal-risk", title=f"{SECRET}续约风险",
                            check_back={"on": "2026-10-20", "question": f"{SECRET}续约了吗？"}),
            user_work=[work(content=f"梳理{SECRET}的决策链")], methods=["stakeholder-map", f"custom:{SECRET}报价法"]))
        draft = report.draft(self.root, today="2026-10-19")
        draft["narrative"] = narrative(f"{SECRET}项目复盘")
        report.build(self.root, draft, today="2026-10-19")
        report.build(self.root, draft, replace=True, today="2026-10-19")
        source = self.root / "knowledge" / "handbook.json"
        handbook.upsert(self.root, source, topic(content=f"{SECRET}的采购由 {UNIT} 发起"), today="2026-10-02")
        target = self.root / "knowledge" / "handbook.html"
        handbook.build(source, target)
        handbook.build(source, target, replace=True)

    def test_dry_run_lists_every_affected_file_without_writing(self):
        self.seed()
        before = tree(self.root)
        result = self.cli_json("redact", "--input", "-", "--dry-run", stdin=json.dumps(REQUEST, ensure_ascii=False))
        self.assertEqual(tree(self.root), before)
        self.assertTrue(result["dry_run"])
        changed = set(result["files_changed"])
        for name in ("records/visit-one.json", "profile.md", "growth-log.md", "reports/2026-10-19.json",
                     "reports/2026-10-19.html", "knowledge/handbook.json", "knowledge/handbook.html"):
            self.assertIn(name, changed)
        self.assertTrue(any(".previous-" in name and name.endswith(".html") for name in changed))
        self.assertEqual([item["index"] for item in result["replacement_counts"]], [0, 1])
        self.assertTrue(all(item["occurrences"] > 0 for item in result["replacement_counts"]))
        self.assertEqual(result["identifier_matches"], [])
        self.assertNotIn(SECRET, json.dumps(result, ensure_ascii=False))

    def test_redaction_removes_text_everywhere_and_keeps_data_valid(self):
        self.seed()
        preview = redact.redact(self.root, REQUEST, dry_run=True)
        result = redact.redact(self.root, REQUEST)
        self.assertEqual(result["files_changed"], preview["files_changed"])
        self.assertEqual(leaks(self.root, SECRET, UNIT), [])
        self.assertEqual(set(result["rerendered"]), {"reports/2026-10-19.html", "knowledge/handbook.html"})
        stored = records.load_records(self.root)[0]
        self.assertEqual(stored["record_id"], "visit-one")
        self.assertEqual(stored["summary"], "拜访[客户A]的采购负责人")
        self.assertEqual(stored["methods"], ["stakeholder-map", "custom:[客户A]报价法"])
        status = self.cli_json("--today", "2026-10-21", "status")
        self.assertEqual([item["question"] for item in status["follow_ups_due"]], ["[客户A]续约了吗？"])
        self.assertIn("[客户A]项目复盘", (self.root / "reports/2026-10-19.html").read_text(encoding="utf-8"))
        backups = list((self.root / "reports").glob("*.previous-*.html"))
        self.assertTrue(backups)
        self.assertIn("[部门B]", backups[0].read_text(encoding="utf-8"))
        self.assertIn("[客户A]", (self.root / "growth-log.md").read_text(encoding="utf-8"))
        self.assertIn("[客户A]", (self.root / "knowledge/handbook.html").read_text(encoding="utf-8"))
        handbook.validate(json.loads((self.root / "knowledge/handbook.json").read_text(encoding="utf-8")))

    def test_rerun_changes_nothing_and_log_keeps_counts_only(self):
        self.seed()
        first = redact.redact(self.root, REQUEST)
        before = tree(self.root)
        second = redact.redact(self.root, REQUEST)
        self.assertEqual(second["files_changed"], [])
        self.assertEqual(second["total_occurrences"], 0)
        self.assertEqual(tree(self.root), before)
        log_text = (self.root / "redactions.json").read_text(encoding="utf-8")
        self.assertNotIn(SECRET, log_text)
        self.assertNotIn(UNIT, log_text)
        entries = json.loads(log_text)["entries"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["label"], REQUEST["label"])
        self.assertEqual(entries[0]["files_changed"], len(first["files_changed"]))
        self.assertEqual(entries[0]["occurrences"], first["total_occurrences"])

    def test_identifiers_are_reported_instead_of_rewritten(self):
        self.add(make_record("xinghe-visit", summary="xinghe 团队来访", methods=["metric-diagnosis"],
                             problem=problem("xinghe-renewal", title="xinghe 续约")))
        request = {"replacements": [{"find": "xinghe", "replace": "client-a"},
                                    {"find": "diagnosis", "replace": "[方法]"}]}
        result = redact.redact(self.root, request)
        stored = records.load_records(self.root)[0]
        self.assertEqual(stored["record_id"], "xinghe-visit")
        self.assertEqual(stored["problem"]["id"], "xinghe-renewal")
        self.assertEqual(stored["problem"]["title"], "client-a 续约")
        self.assertEqual(stored["summary"], "client-a 团队来访")
        self.assertEqual(stored["methods"], ["metric-diagnosis"])
        found = {(item["file"], item["path"], item["replacement"]) for item in result["identifier_matches"]}
        record_file = "records/xinghe-visit.json"
        for expected in ((record_file, "(文件名)", 0), (record_file, "record_id", 0),
                         (record_file, "problem.id", 0), (record_file, "methods[0]", 1)):
            self.assertIn(expected, found)
        self.assertTrue((self.root / record_file).exists())
        self.assertIn("xinghe-visit", (self.root / "growth-log.md").read_text(encoding="utf-8"))

    def test_unsafe_requests_are_rejected_without_writing(self):
        self.seed()
        before = tree(self.root)
        cases = [
            ({"replacements": [{"find": SECRET, "replace": f"{SECRET}（已脱敏）"}]}, "replace 不能包含"),
            ({"replacements": [{"find": "星", "replace": "*"}]}, "至少要有"),
            ({"replacements": [{"find": SECRET, "replace": "A"}, {"find": SECRET, "replace": "B"}]}, "重复"),
            ({"replacements": [{"find": SECRET, "replace": "A"}], "label": f"删除{SECRET}"}, "label"),
            ({"replacements": [{"find": f"拜访{SECRET}的采购负责人", "replace": ""}]}, "空文字"),
            ({"replacements": []}, "至少一条"),
            ({"replacements": [{"find": SECRET}]}, "find 和 replace"),
        ]
        for request, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                redact.redact(self.root, request)
        self.assertEqual(tree(self.root), before)

    def test_migrated_v1_originals_stay_migrated_after_redaction(self):
        self.copy_fixture()
        migrate.migrate(self.root)
        self.assertFalse(records.migration_needed(self.root))
        result = redact.redact(self.root, {"replacements": [{"find": "留存下降排查", "replace": "[案例]"}]})
        self.assertTrue(result["migration_fingerprint_updated"])
        self.assertIn("cases/case-open.json", result["files_changed"])
        self.assertEqual(leaks(self.root, "留存下降排查"), [])
        self.assertFalse(records.migration_needed(self.root))
        self.assertFalse(migrate.migrate(self.root, dry_run=True)["changes_pending"])
        self.add(make_record("after-redaction", stamp="2026-10-21"))
        self.assertFalse(self.cli_json("status")["migration_needed"])

    def test_missing_data_directory_is_not_created(self):
        missing = self.area / "nobody"
        for dry_run in (True, False):
            result = redact.redact(missing, REQUEST, dry_run=dry_run)
            self.assertFalse(result["exists"])
        self.assertFalse(missing.exists())


class HandbookMaintenanceTest(DataTestCase):
    def source(self):
        return self.root / "knowledge" / "handbook.json"

    def book(self):
        return json.loads(self.source().read_text(encoding="utf-8"))

    def upsert(self, value, today="2026-10-21"):
        return self.cli_json("--today", today, "handbook", "upsert", "--topic", "-",
                             stdin=json.dumps(value, ensure_ascii=False))

    def test_list_reports_a_missing_source_without_creating_it(self):
        result = self.cli_json("handbook", "list")
        self.assertFalse(result["exists"])
        self.assertEqual(result["topics"], [])
        self.assertFalse(self.source().exists())

    def test_upsert_starts_from_the_template_and_is_idempotent(self):
        first = self.upsert(topic())
        self.assertEqual(first["action"], "created")
        book = self.book()
        template = json.loads(handbook.BOOK_TEMPLATE.read_text(encoding="utf-8"))
        self.assertEqual(book["title"], template["title"])
        self.assertEqual(book["updated_on"], "2026-10-21")
        self.assertEqual(book["topics"][0]["updated_on"], "2026-10-21")
        before = tree(self.root)
        second = self.upsert(topic(), today="2026-10-22")
        self.assertEqual(second["action"], "unchanged")
        self.assertIsNone(second["backup"])
        self.assertEqual(tree(self.root), before)
        listed = self.cli_json("handbook", "list")
        self.assertTrue(listed["valid"])
        self.assertEqual([item["id"] for item in listed["topics"]], ["client-map"])

    def test_upsert_replaces_in_place_and_backs_up_the_previous_source(self):
        self.upsert(topic())
        self.upsert(topic("priority-tradeoffs", "取舍说明"))
        previous = self.source().read_bytes()
        result = self.upsert(topic(title="客户决策链（修订）", updated_on="2026-10-21"))
        self.assertEqual(result["action"], "replaced")
        self.assertEqual([item["id"] for item in self.book()["topics"]], ["client-map", "priority-tradeoffs"])
        self.assertEqual(self.book()["topics"][0]["title"], "客户决策链（修订）")
        self.assertEqual(Path(result["backup"]).read_bytes(), previous)

    def test_invalid_topic_is_rejected_without_writing(self):
        self.upsert(topic())
        before = tree(self.root)
        failed = self.cli("handbook", "upsert", "--topic", "-",
                          stdin=json.dumps(topic("no-source", sources=[]), ensure_ascii=False))
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("错误", failed.stderr)
        with self.assertRaisesRegex(ValueError, "slug"):
            handbook.upsert(self.root, self.source(), topic("Not A Slug"))
        self.assertEqual(tree(self.root), before)

    def test_remove_backs_up_and_keeps_at_least_one_topic(self):
        self.upsert(topic())
        self.upsert(topic("priority-tradeoffs", "取舍说明"))
        removed = self.cli_json("--today", "2026-10-23", "handbook", "remove", "--id", "priority-tradeoffs")
        self.assertEqual(removed["action"], "removed")
        self.assertEqual(removed["topics"], 1)
        self.assertTrue(Path(removed["backup"]).exists())
        self.assertEqual(self.book()["updated_on"], "2026-10-23")
        before = tree(self.root)
        with self.assertRaisesRegex(ValueError, "没有任何专题"):
            handbook.remove(self.root, self.source(), "client-map")
        with self.assertRaisesRegex(ValueError, "没有专题"):
            handbook.remove(self.root, self.source(), "missing-topic")
        self.assertEqual(tree(self.root), before)

    def test_build_renders_the_maintained_source(self):
        self.upsert(topic())
        built = self.cli_json("handbook", "build")
        self.assertIn("客户决策链", Path(built["output"]).read_text(encoding="utf-8"))
