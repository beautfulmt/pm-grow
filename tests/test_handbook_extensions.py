import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("handbook_extensions", ROOT / "scripts" / "build_handbook.py")
book = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(book)


class FlexibleHandbookTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.topic = {
            "id": "metric-and-goal",
            "title": "指标与目标",
            "updated_on": "2026-10-04",
            "sources": [{
                "title": "隔离测试讨论",
                "checked_on": "2026-10-04",
                "locator": "此测试的概念解释输入",
                "scope": "合成测试数据，不属于用户档案",
            }],
        }
        self.sample = {
            "schema_version": 1,
            "title": "隔离知识手册",
            "updated_on": "2026-10-04",
            "topics": [self.topic],
        }

    def tearDown(self):
        self.temp.cleanup()

    def add_sections(self):
        self.topic["sections"] = [
            {"heading": "概念关系", "content": "目标描述想要改变的结果。\n指标提供可观察的信号。"},
            {"heading": "待核对的问题", "content": "这个信号在当前业务中是否稳定代表目标，仍需核对。"},
        ]

    def test_concept_can_use_only_sections(self):
        self.add_sections()
        before = copy.deepcopy(self.sample)
        html = book.render(self.sample)
        self.assertIn('<a href="#topic-metric-and-goal">指标与目标</a>', html)
        self.assertIn("<h3>概念关系</h3>", html)
        self.assertIn("目标描述想要改变的结果。\n指标提供可观察的信号。", html)
        self.assertIn("<h3>待核对的问题</h3>", html)
        self.assertNotIn('<div class="tags"></div>', html)
        for heading in ("关键判断", "解题步骤", "适用边界", "案例", "可复用模板", "关键推导"):
            self.assertNotIn(f"<h3>{heading}</h3>", html)
        self.assertEqual(self.sample, before)

    def test_legacy_fixture_still_renders_all_its_content(self):
        fixture = json.loads((ROOT / "tests" / "fixtures" / "handbook.json").read_text(encoding="utf-8"))
        html = book.render(fixture)
        for topic in fixture["topics"]:
            self.assertIn(f'id="topic-{topic["id"]}"', html)
            self.assertIn(topic["title"], html)
        for heading in ("问题与背景", "关键判断", "解题步骤", "适用边界", "案例", "可复用模板"):
            self.assertIn(f"<h3>{heading}</h3>", html)

    def test_legacy_body_fields_are_individually_optional(self):
        candidates = {
            "problem": "希望澄清指标与业务结果的关系。",
            "context": "此业务尚未积累完整的任务完成数据。",
            "case": "模拟案例：点击率上升，但任务完成率未变。",
            "first_principles": {"mechanism": "指标可能同时受流量结构和产品变化影响。"},
            "boundaries": ["结论只适用于当前观察窗口。"],
        }
        for key, value in candidates.items():
            with self.subTest(key=key):
                sample = copy.deepcopy(self.sample)
                sample["topics"][0][key] = value
                self.assertIn('id="topic-metric-and-goal"', book.render(sample))

    def test_mixed_sections_and_legacy_fields_keep_content_order(self):
        self.add_sections()
        self.topic.update({
            "context": "当前缺少任务完成数据。",
            "first_principles": {"constraints": "只能观察到页面点击。"},
            "case": "模拟案例：入口调整带来更多点击。",
        })
        html = book.render(self.sample)
        self.assertIn("<h3>背景</h3>", html)
        self.assertIn("<strong>约束</strong>", html)
        self.assertNotIn("<strong>目标</strong>", html)
        positions = [html.index(text) for text in ("<h3>背景</h3>", "<h3>案例</h3>", "<h3>概念关系</h3>", "<h3>待核对的问题</h3>", "<h3>来源与核验范围</h3>")]
        self.assertEqual(positions, sorted(positions))

    def test_empty_optional_fields_do_not_create_columns(self):
        self.add_sections()
        self.topic.update({key: " \n " for key in book.BODY_TEXT})
        self.topic.update({key: [] for key in (*book.BODY_LISTS, "tags")})
        self.topic["first_principles"] = {}
        html = book.render(self.sample)
        self.assertEqual(html.count("<h3>"), 3)
        self.assertNotIn("<pre>", html)

    def test_metadata_tags_and_blank_fields_are_not_a_body(self):
        for additions in ({}, {"tags": ["标签"]}, {"sections": []}, {"first_principles": {}}, {"context": " \n\t", "steps": []}):
            with self.subTest(additions=additions):
                sample = copy.deepcopy(self.sample)
                sample["topics"][0].update(additions)
                with self.assertRaisesRegex(ValueError, "body content"):
                    book.render(sample)

    def test_present_legacy_fields_keep_strict_types(self):
        self.add_sections()
        invalid = [(key, None) for key in book.BODY_TEXT]
        invalid += [(key, "text") for key in (*book.BODY_LISTS, "tags")]
        invalid += [(key, [" "]) for key in (*book.BODY_LISTS, "tags")]
        invalid += [("first_principles", None), ("first_principles", {"mechanism": " "}), ("first_principles", {"unknown": "text"})]
        for key, value in invalid:
            with self.subTest(key=key, value=value):
                sample = copy.deepcopy(self.sample)
                sample["topics"][0][key] = value
                with self.assertRaises(ValueError):
                    book.render(sample)

    def test_sections_require_real_heading_and_content_strings(self):
        invalid = [None, "text", [None], [{}], [{"heading": "标题"}],
                   [{"heading": " ", "content": "正文"}],
                   [{"heading": "标题", "content": " \n "}],
                   [{"heading": "标题", "content": ["正文"]}]]
        for sections in invalid:
            with self.subTest(sections=sections):
                self.topic["sections"] = sections
                with self.assertRaises(ValueError):
                    book.render(self.sample)

    def test_required_metadata_and_sources_still_apply(self):
        self.add_sections()
        for key in ("id", "title", "updated_on", "sources"):
            with self.subTest(key=key):
                sample = copy.deepcopy(self.sample)
                del sample["topics"][0][key]
                with self.assertRaises(ValueError):
                    book.render(sample)
        for source in ({"title": "来源", "checked_on": "2026-10-04"},
                       {"title": "来源", "checked_on": "2026-10-04", "url": "javascript:alert(1)"}):
            with self.subTest(source=source):
                self.topic["sources"] = [source]
                with self.assertRaises(ValueError):
                    book.render(self.sample)

    def test_sections_escape_markup_without_replacing_literal_placeholders(self):
        self.topic["sections"] = [{
            "heading": '<img src=x onerror="alert(1)"> {{TITLE}}',
            "content": '</p><script>alert("x")</script> {{ARTICLES}} {{COUNT}}',
        }]
        html = book.render(self.sample)
        self.assertNotIn('<img src=x', html)
        self.assertNotIn('<script>alert(', html)
        self.assertIn('&lt;img src=x', html)
        self.assertIn('&lt;/p&gt;&lt;script&gt;', html)
        for token in ("{{TITLE}}", "{{ARTICLES}}", "{{COUNT}}"):
            self.assertIn(token, html)

    def test_replacement_keeps_backup_and_failed_validation_preserves_output(self):
        self.add_sections()
        source, output = self.root / "book.json", self.root / "book.html"
        source.write_text(json.dumps(self.sample, ensure_ascii=False), encoding="utf-8")
        book.build(source, output)
        original = output.read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Output exists"):
            book.build(source, output)
        self.topic["sections"].append({"heading": "补充说明", "content": "新增观察仍不能证明因果关系。"})
        source.write_text(json.dumps(self.sample, ensure_ascii=False), encoding="utf-8")
        result = book.build(source, output, replace=True)
        self.assertEqual(Path(result["backup"]).read_text(encoding="utf-8"), original)
        updated = output.read_text(encoding="utf-8")
        self.assertIn("新增观察仍不能证明因果关系。", updated)
        self.topic["sections"] = []
        source.write_text(json.dumps(self.sample, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(ValueError):
            book.build(source, output, replace=True)
        self.assertEqual(output.read_text(encoding="utf-8"), updated)
        self.assertEqual(len(list(self.root.glob("book.previous-*.html"))), 1)


if __name__ == "__main__":
    unittest.main()
