"""Shared helpers for the v2 tests. Every test works in a temporary directory."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
CLI = SCRIPTS / "pmgrow.py"
FIXTURES = ROOT / "tests" / "fixtures"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# Any accidental default resolves to an empty temporary directory, never ~/pm-grow-data.
_GUARD = tempfile.mkdtemp(prefix="pm-grow-guard-")
os.environ["PM_GROW_DATA_DIR"] = str(Path(_GUARD) / "unused")

import records  # noqa: E402


def make_record(identifier, stamp="2026-10-04", **fields):
    value = {"record_id": identifier, "date": stamp, "kind": "discussion",
             "summary": "隔离测试：讨论一个问题，未形成能力评价。",
             "source": "隔离测试输入，非真实个人档案"}
    value.update(fields)
    return value


def work(kind="independent", content="用户本人给出的判断。"):
    return {"kind": kind, "content": content, "source": "隔离测试中的用户原话"}


def problem(identifier, title=None, **fields):
    value = {"id": identifier, "title": title or f"问题 {identifier}"}
    value.update(fields)
    return value


def attempt(identifier, problem_id, stamp="2026-10-04", kind="independent", **fields):
    return make_record(identifier, stamp, kind="attempt", problem=problem(problem_id),
                       user_work=[work(kind)], **fields)


def upgrade(ability_id, evidence, to="independent", source="unobserved", stage="independent_pm"):
    return {"ability_id": ability_id, "stage": stage, "from": source, "to": to,
            "evidence": list(evidence), "reason": "隔离测试中的能力变化依据"}


class Clock:
    """Deterministic, strictly increasing write times."""

    def __init__(self, start=datetime(2026, 10, 1, tzinfo=timezone.utc)):
        self.value = start

    def __call__(self):
        self.value += timedelta(seconds=1)
        return self.value


class DataTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pm-grow-test-")
        self.area = Path(self.temp.name)
        self.root = self.area / "data"
        self.clock = Clock()

    def tearDown(self):
        self.temp.cleanup()

    def add(self, value, root=None):
        return records.append_record(root or self.root, value, now=self.clock())

    def view(self, root=None):
        root = root or self.root
        return records.View(records.load_records(root), records.load_state(root))

    def cli(self, *arguments, root=None, stdin=None):
        return subprocess.run([sys.executable, "-B", str(CLI), "--data-dir", str(root or self.root), *arguments],
                              capture_output=True, text=True, input=stdin, timeout=60,
                              env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})

    def cli_json(self, *arguments, root=None, stdin=None):
        result = self.cli(*arguments, root=root, stdin=stdin)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def write_json(self, name, value):
        path = self.area / name
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def copy_fixture(self, name="v1", target=None):
        target = target or self.root
        shutil.copytree(FIXTURES / name, target)
        return target


def tree(root):
    """Map every file under root to its bytes, for before/after comparisons."""
    root = Path(root)
    if not root.exists():
        return None
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}
