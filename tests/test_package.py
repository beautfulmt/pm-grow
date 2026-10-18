"""Check the shipped routing graph and metadata without loading personal data."""
import re
import unittest
from urllib.parse import unquote

from support import ROOT, records


def body(text):
    lines, fence = [], None
    for line in text.splitlines():
        found = re.match(r"^\s*(`{3,}|~{3,})", line)
        if found:
            marker = found.group(1)[0]
            fence = None if fence == marker else marker if fence is None else fence
        elif fence is None:
            lines.append(line)
    return "\n".join(lines)


class PackageTest(unittest.TestCase):
    def test_every_operational_local_markdown_link_resolves(self):
        failures = []
        for path in ROOT.rglob("*.md"):
            if ".git" in path.parts or "templates" in path.relative_to(ROOT).parts:
                continue
            for match in re.finditer(r"(?<!!)\[[^\]]*\]\(([^)]+)\)", body(path.read_text())):
                link = match.group(1).split(' "')[0].strip("<>")
                if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:|^#", link):
                    continue
                target = unquote(link.split("#")[0])
                if target and not (path.parent / target).exists():
                    failures.append(f"{path.relative_to(ROOT)}: {target}")
        self.assertEqual(failures, [], "\n".join(failures))

    def test_knowledge_map_discovers_every_method_and_industry(self):
        text = (ROOT / "knowledge/map.md").read_text()
        for category in ("methods", "industries"):
            listed = set(re.findall(rf"\]\({category}/([^/)]+)\.md\)", text))
            shipped = {path.stem for path in (ROOT / "knowledge" / category).glob("*.md")}
            self.assertEqual(listed, shipped)

    def test_method_identity_and_capability_references_are_valid(self):
        for path in (ROOT / "knowledge/methods").glob("*.md"):
            with self.subTest(method=path.stem):
                text = path.read_text()
                self.assertIn(f"\nid: {path.stem}\n", text)
                for field, known in (("abilities", records.ABILITIES), ("stages", records.STAGES)):
                    match = re.search(rf"(?m)^{field}: \[([^]]+)\]$", text)
                    self.assertIsNotNone(match)
                    values = {value.strip() for value in match.group(1).split(",")}
                    self.assertTrue(values <= set(known), f"{field}: {values - set(known)}")

    def test_industry_packs_expose_the_required_operating_context(self):
        sections = {"价值链与角色", "核心指标与滞后性", "关键约束与合规", "高频问题",
                    "通用方法在本行业的变形", "易踩的坑", "一手取证来源类型", "适用边界"}
        for path in (ROOT / "knowledge/industries").glob("*.md"):
            with self.subTest(industry=path.stem):
                text = path.read_text()
                self.assertIn(f"\nid: {path.stem}\n", text)
                self.assertTrue(sections <= set(re.findall(r"(?m)^## (.+)$", text)))
                methods = set(re.findall(r"\]\(\.\./methods/([^/)]+)\.md\)", text))
                self.assertGreaterEqual(len(methods), 6)
