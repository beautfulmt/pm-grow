"""Check that the mentor eval cases are well-formed. Scoring the answers stays a human job."""
from datetime import date
import json
import re
import unittest

from support import ROOT, records

CASES = ROOT / "tests" / "evals" / "cases.json"
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
REQUIRED = {"id", "stage", "scenario", "industry", "setup", "prompt", "expect", "anti_patterns"}
OPTIONAL = {"today", "turns"}
TURN_REQUIRED = {"user"}
TURN_OPTIONAL = {"today", "expect", "note"}


def nonempty_text(value):
    return isinstance(value, str) and bool(value.strip())


def text_list(value):
    return isinstance(value, list) and bool(value) and all(nonempty_text(item) for item in value)


def iso_date(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


class EvalCasesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CASES.open(encoding="utf-8") as handle:
            cls.data = json.load(handle)
        cls.cases = cls.data.get("cases") if isinstance(cls.data, dict) else None

    def test_top_level_shape(self):
        self.assertIsInstance(self.data, dict)
        self.assertEqual(set(self.data), {"schema_version", "note", "cases"})
        self.assertIs(type(self.data["schema_version"]), int)
        self.assertTrue(nonempty_text(self.data["note"]))
        self.assertIsInstance(self.cases, list)
        self.assertTrue(self.cases)
        for case in self.cases:
            self.assertIsInstance(case, dict)

    def test_ids_are_unique_slugs(self):
        ids = [case.get("id") for case in self.cases]
        for identifier in ids:
            self.assertTrue(isinstance(identifier, str) and SLUG.fullmatch(identifier), repr(identifier))
        duplicates = sorted({identifier for identifier in ids if ids.count(identifier) > 1})
        self.assertEqual(duplicates, [])

    def test_required_fields_exist_with_correct_types(self):
        for case in self.cases:
            with self.subTest(case=case.get("id")):
                self.assertEqual(sorted(REQUIRED - set(case)), [], "缺少必填字段")
                self.assertEqual(sorted(set(case) - REQUIRED - OPTIONAL), [], "包含未约定的字段")
                for key in ("setup", "prompt"):
                    self.assertTrue(nonempty_text(case[key]), key)
                # Scenario and industry stay slugs ("none" when not applicable); file existence is
                # deliberately not checked so cases can target content that lands in the same release.
                for key in ("scenario", "industry"):
                    self.assertTrue(isinstance(case[key], str) and SLUG.fullmatch(case[key]), key)
                for key in ("expect", "anti_patterns"):
                    self.assertTrue(text_list(case[key]), f"{key} 必须是非空文字组成的非空列表")
                if "today" in case:
                    self.assertIsNotNone(iso_date(case["today"]), "today 必须是 YYYY-MM-DD")

    def test_stage_values_are_known(self):
        for case in self.cases:
            with self.subTest(case=case.get("id")):
                self.assertIn(case.get("stage"), records.STAGES)

    def test_scenarios_and_industries_point_to_shipped_files(self):
        # "none" marks a case that is deliberately outside every scenario or industry pack.
        playbooks = {path.stem for path in (ROOT / "playbooks").glob("*.md")} - {"index"}
        industries = {path.stem for path in (ROOT / "knowledge" / "industries").glob("*.md")}
        for case in self.cases:
            with self.subTest(case=case.get("id")):
                self.assertIn(case.get("scenario"), playbooks | {"none"})
                self.assertIn(case.get("industry"), industries | {"none"})

    def test_turns_follow_the_multi_turn_protocol(self):
        for case in self.cases:
            if "turns" not in case:
                continue
            with self.subTest(case=case.get("id")):
                turns = case["turns"]
                self.assertTrue(isinstance(turns, list) and turns, "turns 必须是非空列表")
                session_date = iso_date(case.get("today"))
                for index, turn in enumerate(turns):
                    label = f"turns[{index}]"
                    self.assertIsInstance(turn, dict, label)
                    self.assertEqual(sorted(TURN_REQUIRED - set(turn)), [], label)
                    self.assertEqual(sorted(set(turn) - TURN_REQUIRED - TURN_OPTIONAL), [], label)
                    self.assertTrue(nonempty_text(turn["user"]), label)
                    if "expect" in turn:
                        self.assertTrue(text_list(turn["expect"]), f"{label}.expect")
                    if "note" in turn:
                        self.assertTrue(nonempty_text(turn["note"]), f"{label}.note")
                    if "today" in turn:
                        # A dated turn opens a new session, so the dates must move forward.
                        new_date = iso_date(turn["today"])
                        self.assertIsNotNone(new_date, f"{label}.today 必须是 YYYY-MM-DD")
                        self.assertIsNotNone(session_date, f"{label}：开启新会话的题目需要顶层 today")
                        self.assertGreater(new_date, session_date, f"{label}.today 必须晚于上一个会话")
                        session_date = new_date

    def test_suite_keeps_multi_turn_and_cross_session_coverage(self):
        multi_turn = [case["id"] for case in self.cases if case.get("turns")]
        cross_session = [case["id"] for case in self.cases
                         if any("today" in turn for turn in case.get("turns", []))]
        self.assertGreaterEqual(len(multi_turn), 3, "至少保留 3 道多轮题")
        self.assertTrue(cross_session, "至少保留 1 道跨会话的多轮题")


if __name__ == "__main__":
    unittest.main()
