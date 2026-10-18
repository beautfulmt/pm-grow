"""pm-grow v2 personal records: validation, immutable storage and derived state.

One substantive exchange is one immutable record. Problem status, ability
levels, stage, pending check-backs and report triggers are all derived from
the records; nothing is maintained by hand.
"""
from datetime import date, datetime, timedelta, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
import tempfile

from storage import atomic_write_json, file_lock

SKILL_DIR = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 2
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
CUSTOM_ID = re.compile(r"custom\.[a-z0-9]+(?:-[a-z0-9]+)*\Z")

ABILITIES = {
    "user_problem": "用户洞察与问题界定",
    "business_value": "业务与价值判断",
    "solution_design": "方案设计与技术判断",
    "data_validation": "数据分析与效果验证",
    "strategy_prioritization": "策略取舍与规划",
    "delivery_risk": "交付推进与风险控制",
    "communication_influence": "沟通协作与影响力",
    "learning_transfer": "复盘学习与方法迁移",
    "domain_expertise": "领域深度与方法输出",
    "team_leadership": "团队领导与人才培养",
}
STAGES = {"newcomer": "新人", "independent_pm": "独立 PM", "senior": "资深", "expert": "专家", "lead": "负责人"}
LEVELS = ("unobserved", "needs_support", "independent", "stable")
LEVEL_NAMES = {"unobserved": "未观察", "needs_support": "需要支持", "independent": "可以独立", "stable": "复杂情境稳定"}
KINDS = ("discussion", "exploration", "attempt", "follow_up", "context_update",
         "preference", "correction", "milestone", "review")
PROBLEM_STATUSES = {"open": "进行中", "solved": "已解决", "partial": "部分解决",
                    "blocked": "受阻", "dropped": "已放弃", "closed": "已关闭"}
OPEN_STATUSES = ("open", "partial", "blocked")
RESOLVED_STATUSES = ("solved", "partial", "closed")
WORK_KINDS = {"independent": "独立完成", "guided": "引导下完成", "demo": "导师示范", "acknowledgement": "表示认同"}
OBSERVATION_STATUSES = ("candidate", "supported", "withdrawn")
REPORT_MODES = ("propose", "auto")
# Upgrade gates: minimum evidence records, minimum distinct problems, accepted user_work kinds.
GATES = {
    "needs_support": (1, 0, ("guided", "independent")),
    "independent": (2, 2, ("independent",)),
    "stable": (3, 3, ("independent",)),
}
REPORT_PROBLEM_THRESHOLD = 3
REPORT_DAYS_THRESHOLD = 14

FIELDS = {"schema_version", "record_id", "date", "recorded_at", "kind", "summary", "source",
          "problem", "user_work", "methods", "observations", "ability_updates", "stage_update",
          "milestone", "assistance", "unresolved", "next_step", "preferences", "context_ref",
          "corrections", "migrated_from"}
TEXT_FIELDS = ("milestone", "assistance", "unresolved", "next_step", "context_ref")
PROBLEM_FIELDS = {"id", "title", "scenario", "status", "outcome", "check_back"}
LOG_START = "<!-- pm-grow:records:start -->"
LOG_END = "<!-- pm-grow:records:end -->"
V1_LOG_START = "<!-- pm-grow:events:start -->"
V1_LOG_END = "<!-- pm-grow:events:end -->"


# ---------------------------------------------------------------- shared I/O

def data_root(value=None):
    """Resolve the data directory: --data-dir > PM_GROW_DATA_DIR > ~/pm-grow-data."""
    return Path(value or os.environ.get("PM_GROW_DATA_DIR") or Path.home() / "pm-grow-data").expanduser().resolve()


def read_json(path):
    try:
        with Path(path).open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        raise ValueError(f"无法读取 {path}：{exc}") from exc


def atomic_write_text(path, content):
    """Replace one text file atomically and verify the bytes that landed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent,
                                         prefix=".pm-grow-text-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    with path.open(encoding="utf-8", newline="") as handle:
        if handle.read() != content:
            raise ValueError(f"{path} 写入后读回内容不一致")


def parse_date(value, label):
    if not isinstance(value, str):
        raise ValueError(f"{label} 必须是 YYYY-MM-DD 日期")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        parsed = None
    if parsed is None or parsed.isoformat() != value:
        raise ValueError(f"{label} 必须是有效的 YYYY-MM-DD 日期，收到：{value}")
    return parsed


def today_value(today=None):
    if today is None:
        return date.today()
    if isinstance(today, date):
        return today
    return parse_date(today, "today")


def ability_label(state, ability_id):
    if ability_id in ABILITIES:
        return ABILITIES[ability_id]
    for ability in (state or {}).get("abilities", []):
        if ability["id"] == ability_id:
            return ability["name"]
    return ability_id


# ---------------------------------------------------------------- validation

def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} 必须是非空文字；未知时请省略该字段")
    return value


def _slug(value, label):
    if not isinstance(value, str) or not SLUG.fullmatch(value):
        raise ValueError(f"{label} 必须是小写字母、数字和单个连字符组成的 slug，收到：{value!r}")
    return value


def _ability_id(value, label):
    if not isinstance(value, str) or (value not in ABILITIES and not CUSTOM_ID.fullmatch(value)):
        raise ValueError(f"{label} 不是有效的能力 ID：{value!r}；内置能力见 growth/abilities.md，自定义能力用 custom.<slug>")
    return value


def _object(value, label, allowed):
    if not isinstance(value, dict):
        raise ValueError(f"{label} 必须是对象")
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        raise ValueError(f"{label} 包含不支持的字段：{'、'.join(unknown)}")
    return dict(value)


def _list(value, label):
    if not isinstance(value, list):
        raise ValueError(f"{label} 必须是列表")
    return value


def _validate_problem(value, record_date):
    problem = _object(value, "problem", PROBLEM_FIELDS)
    if "id" not in problem:
        raise ValueError("problem.id 必填")
    _slug(problem["id"], "problem.id")
    for key in ("title", "outcome"):
        if key in problem:
            _text(problem[key], f"problem.{key}")
    if "scenario" in problem:
        _slug(problem["scenario"], "problem.scenario")
    if "status" in problem and problem["status"] not in PROBLEM_STATUSES:
        raise ValueError(f"problem.status 只能是 {'|'.join(PROBLEM_STATUSES)}")
    if "check_back" in problem:
        check = _object(problem["check_back"], "problem.check_back", {"on", "when", "question"})
        if "question" not in check:
            raise ValueError("problem.check_back.question 必填：写下回访时要问的那句话")
        _text(check["question"], "problem.check_back.question")
        if "on" not in check and "when" not in check:
            raise ValueError("problem.check_back 需要 on（回访日期）或 when（回访条件）至少一项")
        if "on" in check and parse_date(check["on"], "problem.check_back.on") < record_date:
            raise ValueError("problem.check_back.on 不能早于本条记录的 date")
        if "when" in check:
            _text(check["when"], "problem.check_back.when")
        problem["check_back"] = check
    return problem


def validate_record(value, stored=False):
    """Validate one record and return its normalized form.

    Input metadata never sets recorded_at; the writer assigns it. Stored records
    must carry it.
    """
    if not isinstance(value, dict):
        raise ValueError("记录必须是 JSON 对象")
    unknown = sorted(set(value) - FIELDS)
    if unknown:
        raise ValueError(f"记录包含不支持的字段：{'、'.join(unknown)}")
    record = json.loads(json.dumps(value, ensure_ascii=False))
    if stored:
        stamp = record.get("recorded_at")
        try:
            parsed = datetime.fromisoformat(stamp) if isinstance(stamp, str) else None
        except ValueError:
            parsed = None
        if (parsed is None or parsed.utcoffset() != timedelta(0)
                or parsed.isoformat(timespec="microseconds") != stamp):
            raise ValueError("已保存记录的 recorded_at 必须是带微秒的 UTC 时间")
    else:
        record.pop("recorded_at", None)
    record.setdefault("schema_version", SCHEMA_VERSION)
    if type(record["schema_version"]) is not int or record["schema_version"] != SCHEMA_VERSION:
        raise ValueError("记录 schema_version 必须是 2；v1 数据请先运行 migrate")
    for key in ("record_id", "date", "kind", "summary", "source"):
        if key not in record:
            raise ValueError(f"记录缺少必填字段：{key}")
    _slug(record["record_id"], "record_id")
    record_date = parse_date(record["date"], "date")
    if record["kind"] not in KINDS:
        raise ValueError(f"kind 只能是 {'|'.join(KINDS)}")
    _text(record["summary"], "summary")
    _text(record["source"], "source")
    for key in TEXT_FIELDS:
        if key in record:
            _text(record[key], key)

    if "problem" in record:
        record["problem"] = _validate_problem(record["problem"], record_date)

    if "user_work" in record:
        work = []
        for index, item in enumerate(_list(record["user_work"], "user_work")):
            label = f"user_work[{index}]"
            item = _object(item, label, {"kind", "content", "source"})
            if item.get("kind") not in WORK_KINDS:
                raise ValueError(f"{label}.kind 只能是 {'|'.join(WORK_KINDS)}")
            _text(item.get("content"), f"{label}.content")
            _text(item.get("source"), f"{label}.source")
            work.append(item)
        record["user_work"] = work

    if "methods" in record:
        methods = _list(record["methods"], "methods")
        for index, method in enumerate(methods):
            label = f"methods[{index}]"
            if isinstance(method, str) and method.startswith("custom:"):
                _text(method[len("custom:"):], label + " 的自定义方法文字")
            else:
                _slug(method, label + "（方法卡 ID 或 custom:<文字>）")
        if len(set(methods)) != len(methods):
            raise ValueError("methods 中有重复项")

    if "observations" in record:
        observations = []
        for index, item in enumerate(_list(record["observations"], "observations")):
            label = f"observations[{index}]"
            item = _object(item, label, {"ability_id", "text", "status"})
            _ability_id(item.get("ability_id"), f"{label}.ability_id")
            _text(item.get("text"), f"{label}.text")
            if item.get("status") not in OBSERVATION_STATUSES:
                raise ValueError(f"{label}.status 只能是 {'|'.join(OBSERVATION_STATUSES)}")
            observations.append(item)
        record["observations"] = observations

    if "ability_updates" in record:
        updates = []
        for index, item in enumerate(_list(record["ability_updates"], "ability_updates")):
            label = f"ability_updates[{index}]"
            item = _object(item, label, {"ability_id", "stage", "from", "to", "evidence", "reason"})
            for key in ("ability_id", "stage", "from", "to", "evidence", "reason"):
                if key not in item:
                    raise ValueError(f"{label} 缺少 {key}")
            _ability_id(item["ability_id"], f"{label}.ability_id")
            if item["stage"] not in STAGES:
                raise ValueError(f"{label}.stage 只能是 {'|'.join(STAGES)}")
            for key in ("from", "to"):
                if item[key] not in LEVELS:
                    raise ValueError(f"{label}.{key} 只能是 {'|'.join(LEVELS)}")
            if item["from"] == item["to"]:
                raise ValueError(f"{label} 的 from 与 to 相同，没有变化就不要写 ability_update")
            evidence = _list(item["evidence"], f"{label}.evidence")
            for position, identifier in enumerate(evidence):
                _slug(identifier, f"{label}.evidence[{position}]")
            if len(set(evidence)) != len(evidence):
                raise ValueError(f"{label}.evidence 中有重复的记录 ID")
            _text(item["reason"], f"{label}.reason")
            updates.append(item)
        record["ability_updates"] = updates

    if "stage_update" in record:
        update = _object(record["stage_update"], "stage_update", {"stage", "reason"})
        if update.get("stage") not in STAGES:
            raise ValueError(f"stage_update.stage 只能是 {'|'.join(STAGES)}")
        _text(update.get("reason"), "stage_update.reason")
        record["stage_update"] = update

    if "preferences" in record:
        for index, item in enumerate(_list(record["preferences"], "preferences")):
            _text(item, f"preferences[{index}]")

    if "corrections" in record:
        corrections = []
        for index, item in enumerate(_list(record["corrections"], "corrections")):
            label = f"corrections[{index}]"
            item = _object(item, label, {"record_id", "record_ref", "reason", "invalidate"})
            targets = [key for key in ("record_id", "record_ref") if key in item]
            if len(targets) != 1:
                raise ValueError(f"{label} 需要且只能有一个目标：record_id（v2 记录）或 record_ref（旧档案位置）")
            _text(item.get("reason"), f"{label}.reason")
            item["invalidate"] = item.get("invalidate", False)
            if type(item["invalidate"]) is not bool:
                raise ValueError(f"{label}.invalidate 必须是 true 或 false")
            if "record_id" in item:
                _slug(item["record_id"], f"{label}.record_id")
                if item["record_id"] == record["record_id"]:
                    raise ValueError(f"{label} 不能更正记录自身")
            else:
                _text(item["record_ref"], f"{label}.record_ref")
                if item["invalidate"]:
                    raise ValueError(f"{label} 只有指向 v2 记录（record_id）时才能 invalidate")
            corrections.append(item)
        record["corrections"] = corrections

    if "migrated_from" in record and not isinstance(record["migrated_from"], dict):
        raise ValueError("migrated_from 必须是对象")

    if record["kind"] == "correction" and not record.get("corrections"):
        raise ValueError("kind=correction 的记录需要 corrections 指向被更正的记录")
    if record["kind"] == "follow_up" and "problem" not in record:
        raise ValueError("kind=follow_up 的记录需要 problem.id，用来对应要回访的问题")
    if record["kind"] == "milestone" and "milestone" not in record:
        raise ValueError("kind=milestone 的记录需要 milestone 文字")
    return record


def without_recorded_at(record):
    return {key: value for key, value in record.items() if key != "recorded_at"}


# ---------------------------------------------------------------- state.json

def default_state():
    return {
        "schema_version": SCHEMA_VERSION,
        "abilities": [],
        "ability_history": [],
        "report": {"history": [], "deferred": None},
        "settings": {"report_mode": "propose"},
        "migrations": [],
    }


def validate_ability(ability, label="ability"):
    if not isinstance(ability, dict):
        raise ValueError(f"{label}：能力定义必须是对象")
    identifier = ability.get("id")
    if isinstance(identifier, str) and identifier in ABILITIES:
        raise ValueError(f"{label}：内置能力 ID 不能注册或替换（base ability IDs are fixed）")
    if not isinstance(identifier, str) or not CUSTOM_ID.fullmatch(identifier):
        raise ValueError(f"{label}：id 必须是 custom.<小写连字符 slug>")
    unknown = sorted(set(ability) - {"id", "name", "definition", "observable_behaviors"})
    if unknown:
        raise ValueError(f"{label}：包含不支持的字段 {'、'.join(unknown)}")
    for key in ("name", "definition"):
        if not isinstance(ability.get(key), str) or not ability[key].strip():
            raise ValueError(f"{label}：{key} 必填")
    behaviors = ability.get("observable_behaviors")
    if not isinstance(behaviors, list) or not behaviors or any(
            not isinstance(item, str) or not item.strip() for item in behaviors):
        raise ValueError(f"{label}：observable_behaviors 需要至少一条非空文字")
    return ability


def _timestamp(value, label):
    try:
        if not isinstance(value, str):
            raise ValueError()
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError()
    except ValueError as exc:
        raise ValueError(f"{label} 必须是带时区的 ISO 8601 时间") from exc
    return value


def validate_state(state, label="state.json"):
    if not isinstance(state, dict) or state.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"{label}：schema_version 必须是 2")
    unknown = sorted(set(state) - set(default_state()))
    if unknown:
        raise ValueError(f"{label}：包含未知字段 {'、'.join(unknown)}")
    defaults = default_state()
    for key, value in defaults.items():
        state.setdefault(key, value)
    seen = set()
    if not isinstance(state["abilities"], list):
        raise ValueError(f"{label}：abilities 必须是列表")
    for ability in state["abilities"]:
        validate_ability(ability, label)
        if ability["id"] in seen:
            raise ValueError(f"{label}：能力 {ability['id']} 重复")
        seen.add(ability["id"])
    if not isinstance(state["ability_history"], list):
        raise ValueError(f"{label}：ability_history 必须是列表")
    for entry in state["ability_history"]:
        if not isinstance(entry, dict) or set(entry) - {"replaced_at", "ability_id", "previous_definition"}:
            raise ValueError(f"{label}：ability_history 条目格式不正确")
        previous = validate_ability(entry.get("previous_definition"), label)
        if entry.get("ability_id") != previous["id"]:
            raise ValueError(f"{label}：ability_history 的 ability_id 与旧定义不一致")
        _timestamp(entry.get("replaced_at"), f"{label}：ability_history.replaced_at")
    report = state["report"]
    if not isinstance(report, dict) or set(report) - {"history", "deferred"}:
        raise ValueError(f"{label}：report 格式不正确")
    report.setdefault("history", [])
    report.setdefault("deferred", None)
    if not isinstance(report["history"], list):
        raise ValueError(f"{label}：report.history 必须是列表")
    for entry in report["history"]:
        if not isinstance(entry, dict) or entry.get("source") not in {"v1", "v2"}:
            raise ValueError(f"{label}：report.history 条目需要 source=v1|v2")
        parse_date(entry.get("date"), f"{label}：report.history.date")
        ids = entry.get("record_ids")
        if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids):
            raise ValueError(f"{label}：report.history.record_ids 必须是记录 ID 列表")
    deferred = report["deferred"]
    if deferred is not None and (not isinstance(deferred, dict) or not isinstance(deferred.get("fingerprint"), str)):
        raise ValueError(f"{label}：report.deferred 必须是 null 或包含 fingerprint 的对象")
    settings = state["settings"]
    if not isinstance(settings, dict) or set(settings) - {"report_mode"}:
        raise ValueError(f"{label}：settings 只支持 report_mode")
    settings.setdefault("report_mode", "propose")
    if settings["report_mode"] not in REPORT_MODES:
        raise ValueError(f"{label}：settings.report_mode 只能是 {'|'.join(REPORT_MODES)}")
    if not isinstance(state["migrations"], list) or any(not isinstance(item, dict) for item in state["migrations"]):
        raise ValueError(f"{label}：migrations 必须是对象列表")
    return state


def load_state(root):
    path = Path(root) / "state.json"
    if not path.exists():
        return default_state()
    return validate_state(read_json(path), str(path))


def write_state(root, state):
    validate_state(state)
    path = Path(root) / "state.json"
    atomic_write_json(path, state)
    if read_json(path) != state:
        raise ValueError("state.json 写入后读回内容不一致")


def known_ability_ids(state):
    return list(ABILITIES) + [ability["id"] for ability in state["abilities"]]


def register_ability(root, ability, replace=False, timeout=10.0):
    validate_ability(ability)
    root = Path(root)
    with file_lock(root, timeout=timeout):
        state = load_state(root)
        existing = next((item for item in state["abilities"] if item["id"] == ability["id"]), None)
        if existing is not None:
            if existing == ability:
                status = "unchanged"
            elif not replace:
                raise ValueError("该自定义能力已存在且定义不同；确认要替换时加 --replace")
            else:
                state["ability_history"].append({
                    "replaced_at": datetime.now(timezone.utc).isoformat(),
                    "ability_id": ability["id"],
                    "previous_definition": existing,
                })
                state["abilities"][state["abilities"].index(existing)] = ability
                status = "replaced"
        else:
            state["abilities"].append(ability)
            status = "created"
        if status != "unchanged":
            write_state(root, state)
    return {"data_dir": str(root), "registered": ability["id"], "status": status}


def set_setting(root, key, value, timeout=10.0):
    if key != "report_mode":
        raise ValueError("目前只支持设置 report_mode")
    if value not in REPORT_MODES:
        raise ValueError(f"report_mode 只能是 {'|'.join(REPORT_MODES)}")
    root = Path(root)
    with file_lock(root, timeout=timeout):
        state = load_state(root)
        changed = state["settings"].get(key) != value
        state["settings"][key] = value
        if changed or not (root / "state.json").exists():
            write_state(root, state)
    return {"data_dir": str(root), "settings": state["settings"], "changed": changed}


# ---------------------------------------------------------------- v1 detection

V1_DATA = ("events", "cases", "abilities.json", "review-state.json")


def v1_files(root):
    root = Path(root)
    found = []
    for name in ("events", "cases"):
        found += sorted(path for path in (root / name).glob("*.json") if path.is_file())
    for name in ("abilities.json", "review-state.json"):
        if (root / name).is_file():
            found.append(root / name)
    return found


def v1_fingerprint(root):
    root = Path(root)
    digest = hashlib.sha256()
    for path in v1_files(root):
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii") + b"\n")
    return digest.hexdigest()


def migration_needed(root, state=None):
    files = v1_files(root)
    if not files:
        return False
    state = state if state is not None else load_state(root)
    done = [item.get("v1_fingerprint") for item in state["migrations"]]
    return v1_fingerprint(root) not in done


# ---------------------------------------------------------------- records

def display_order(record):
    return record["date"], record["recorded_at"], record["record_id"]


def write_order(record):
    return record["recorded_at"], record["record_id"]


def load_records(root):
    records = []
    for path in sorted((Path(root) / "records").glob("*.json")):
        record = validate_record(read_json(path), stored=True)
        if path.stem != record["record_id"]:
            raise ValueError(f"记录文件名与 record_id 不一致：{path}")
        records.append(record)
    return sorted(records, key=display_order)


def next_recorded_at(records, now=None):
    timestamp = now or datetime.now(timezone.utc)
    previous = [datetime.fromisoformat(record["recorded_at"]) for record in records]
    if previous and timestamp <= max(previous):
        timestamp = max(previous) + timedelta(microseconds=1)
    return timestamp.isoformat(timespec="microseconds")


def _work_kinds(record):
    return {item["kind"] for item in record.get("user_work", [])}


class View:
    """Everything derivable from the records, computed once per read."""

    def __init__(self, records, state=None):
        self.state = state or default_state()
        self.records = sorted(records, key=display_order)
        self.by_id = {record["record_id"]: record for record in self.records}
        self.invalidated_by = self._invalidations()
        self.valid = [record for record in self.records if record["record_id"] not in self.invalidated_by]
        self.valid_ids = {record["record_id"] for record in self.valid}
        self.written = sorted(self.valid, key=write_order)
        self.problems, self.key_moments = self._problems()
        self.levels, self.applied, self.voided = self._abilities()
        self.stage = None
        for record in self.written:
            if "stage_update" in record:
                self.stage = {**record["stage_update"], "name": STAGES[record["stage_update"]["stage"]],
                              "date": record["date"], "record_id": record["record_id"]}

    def _invalidations(self):
        invalidators = {}
        for record in self.records:
            for correction in record.get("corrections", []):
                if correction.get("invalidate") and correction.get("record_id") in self.by_id:
                    invalidators.setdefault(correction["record_id"], []).append(record["record_id"])
        memo = {}

        def valid(identifier, stack):
            if identifier in memo:
                return memo[identifier]
            if identifier in stack:
                raise ValueError(f"更正链出现循环：{identifier}")
            result = not any(valid(other, stack | {identifier}) for other in invalidators.get(identifier, []))
            memo[identifier] = result
            return result

        result = {}
        for identifier, sources in invalidators.items():
            if not valid(identifier, frozenset()):
                result[identifier] = [source for source in sources if valid(source, frozenset())]
        return result

    def _problems(self):
        problems, moments = {}, []
        for position, record in enumerate(self.written):
            value = record.get("problem")
            if not value:
                continue
            entry = problems.setdefault(value["id"], {
                "id": value["id"], "title": None, "scenario": None, "status": "open", "outcome": None,
                "check_back": None, "check_back_record": None, "check_back_position": None,
                "follow_up_position": None, "record_ids": [], "first_date": record["date"],
                "last_date": record["date"], "next_step": None, "unresolved": None,
            })
            previous_status, previous_outcome = entry["status"], entry["outcome"]
            for key in ("title", "scenario", "outcome", "status"):
                if key in value:
                    entry[key] = value[key]
            if record["kind"] == "follow_up":
                entry["follow_up_position"] = position
            if "check_back" in value:
                entry["check_back"] = value["check_back"]
                entry["check_back_record"] = record["record_id"]
                entry["check_back_date"] = record["date"]
                entry["check_back_position"] = position
            for key in ("next_step", "unresolved"):
                if key in record:
                    entry[key] = record[key]
            entry["record_ids"].append(record["record_id"])
            entry["first_date"] = min(entry["first_date"], record["date"])
            entry["last_date"] = max(entry["last_date"], record["date"])
            reached = entry["status"] in RESOLVED_STATUSES and entry["outcome"]
            changed = entry["status"] != previous_status or entry["outcome"] != previous_outcome
            if reached and changed:
                moments.append({"type": "problem_resolved", "record_id": record["record_id"],
                                "date": record["date"], "problem_id": entry["id"],
                                "status": entry["status"], "outcome": entry["outcome"]})
        return problems, moments

    def evidence_errors(self, update, record):
        """Return the reasons, in Chinese, why one ability update fails its gate."""
        rank = LEVELS.index
        errors = []
        target, source = update["to"], update["from"]
        evidence = []
        for identifier in update["evidence"]:
            item = self.by_id.get(identifier)
            if item is None:
                errors.append(f"证据记录 {identifier} 不存在")
            elif identifier not in self.valid_ids:
                errors.append(f"证据记录 {identifier} 已被作废")
            elif item["date"] > record["date"]:
                errors.append(f"证据记录 {identifier} 的日期 {item['date']} 晚于本条记录 {record['date']}")
            elif write_order(item) > write_order(record):
                errors.append(f"证据记录 {identifier} 在本条记录之后才写入")
            else:
                evidence.append(item)
        if rank(target) < rank(source):
            if not update["evidence"] and not record.get("corrections"):
                errors.append("降级或撤回需要至少 1 条证据记录，或在本条记录里写 corrections 说明更正")
            return errors
        minimum_records, minimum_problems, accepted = GATES[target]
        accepted_names = "或".join(f"{kind}（{WORK_KINDS[kind]}）" for kind in accepted)
        qualified = []
        for item in evidence:
            kinds = _work_kinds(item)
            if not kinds & set(accepted):
                if kinds and kinds <= {"demo", "acknowledgement"}:
                    errors.append(f"证据记录 {item['record_id']} 只有导师示范或用户认同，不算用户本人的证据")
                else:
                    errors.append(f"证据记录 {item['record_id']} 没有 {accepted_names} 的 user_work")
            elif minimum_problems and not item.get("problem"):
                errors.append(f"证据记录 {item['record_id']} 没有关联 problem.id，无法计入不同问题")
            else:
                qualified.append(item)
        problems = {item["problem"]["id"] for item in qualified if item.get("problem")}
        if len(qualified) < minimum_records or len(problems) < minimum_problems:
            need = f"至少 {minimum_records} 条证据记录"
            if minimum_problems:
                need += f"，来自至少 {minimum_problems} 个不同的问题（problem.id）"
            errors.append(f"升到「{LEVEL_NAMES[target]}」需要{need}，每条都含 {accepted_names} 的 user_work；"
                          f"目前合格证据 {len(qualified)} 条，涉及 {len(problems)} 个问题")
        return errors

    def _abilities(self):
        levels, applied, voided = {}, [], []
        for record in self.written:
            for update in record.get("ability_updates", []):
                key = (update["ability_id"], update["stage"])
                current = levels.get(key, {"level": "unobserved"})["level"]
                errors = []
                if update["from"] != current:
                    errors.append(f"from 是「{LEVEL_NAMES[update['from']]}」，但 {update['ability_id']} 在 "
                                  f"{update['stage']} 阶段当前推导为「{LEVEL_NAMES[current]}」")
                errors += self.evidence_errors(update, record)
                entry = {**update, "record_id": record["record_id"], "date": record["date"]}
                if errors:
                    voided.append({**entry, "errors": errors})
                    continue
                entry["evidence_dates"] = sorted({self.by_id[item]["date"] for item in update["evidence"]})
                entry["direction"] = "up" if LEVELS.index(update["to"]) > LEVELS.index(update["from"]) else "down"
                applied.append(entry)
                state = levels.setdefault(key, {"level": "unobserved", "changes": []})
                state["level"] = update["to"]
                state["changes"].append(entry)
        return levels, applied, voided

    # -- derived views used by status and reports

    def pending_check_backs(self, today):
        due = []
        for problem in self.problems.values():
            check = problem["check_back"]
            if not check:
                continue
            if problem["follow_up_position"] is not None and problem["follow_up_position"] > problem["check_back_position"]:
                continue
            item = {"problem_id": problem["id"], "title": problem["title"], "question": check["question"],
                    "problem_status": problem["status"], "set_by": problem["check_back_record"],
                    "set_on": problem["check_back_date"]}
            for key in ("on", "when"):
                if key in check:
                    item[key] = check[key]
            if "on" in check:
                if date.fromisoformat(check["on"]) <= today:
                    item["status"] = "due"
                    item["days_overdue"] = (today - date.fromisoformat(check["on"])).days
                    due.append(item)
            else:
                item["status"] = "condition_pending"
                due.append(item)
        return sorted(due, key=lambda item: (item["status"] != "due", item.get("on", ""), item["problem_id"]))

    def open_problems(self):
        items = []
        for problem in self.problems.values():
            if problem["status"] in OPEN_STATUSES:
                items.append(public_problem(problem))
        return sorted(items, key=lambda item: (item["last_date"], item["id"]), reverse=True)

    def level(self, ability_id, stage):
        return self.levels.get((ability_id, stage), {"level": "unobserved"})["level"]


def public_problem(problem):
    value = {key: problem[key] for key in ("id", "title", "scenario", "status", "outcome",
                                           "check_back", "first_date", "last_date", "next_step", "unresolved")}
    value["status_name"] = PROBLEM_STATUSES[problem["status"]]
    value["record_ids"] = list(problem["record_ids"])
    return {key: item for key, item in value.items() if item is not None}


def change_summary(view, entry):
    return {
        "record_id": entry["record_id"], "date": entry["date"], "ability_id": entry["ability_id"],
        "name": ability_label(view.state, entry["ability_id"]), "stage": entry["stage"],
        "stage_name": STAGES[entry["stage"]], "from": entry["from"], "from_name": LEVEL_NAMES[entry["from"]],
        "to": entry["to"], "to_name": LEVEL_NAMES[entry["to"]], "direction": entry["direction"],
        "evidence": list(entry["evidence"]), "evidence_dates": list(entry["evidence_dates"]),
        "reason": entry["reason"],
    }


# ---------------------------------------------------------------- growth-log index

def _short(value, limit=240):
    text = " ".join(str(value).split())
    return html.escape(text if len(text) <= limit else text[:limit] + "…", quote=False)


def log_content(root, view):
    path = Path(root) / "growth-log.md"
    source = path if path.exists() else SKILL_DIR / "templates" / "growth-log.md"
    with source.open(encoding="utf-8", newline="") as handle:
        original = handle.read()
    block = None
    for start, end in ((LOG_START, LOG_END), (V1_LOG_START, V1_LOG_END)):
        if start in original or end in original:
            if original.count(start) != 1 or original.count(end) != 1 or original.index(start) > original.index(end):
                raise ValueError("growth-log.md 的自动索引标记不完整；请先修复标记，人工文字会保留")
            block = (start, end)
            break
    if block:
        before, rest = original.split(block[0])
        _, after = rest.split(block[1])
    else:
        before, after = original + ("" if original.endswith("\n") else "\n") + "\n", "\n"
    lines = [LOG_START, "## 记录索引", "",
             "由 records/ 自动生成，人工文字请写在本区域之外。条数不代表能力证据数量。", ""]
    for record in view.records:
        identifier = record["record_id"]
        lines += [f"### {record['date']} · {record['kind']} · {identifier}", "", _short(record["summary"]), "",
                  f"- 来源：{_short(record['source'])}；[完整记录](records/{identifier}.json)"]
        if identifier in view.invalidated_by:
            lines.append(f"- 已作废：被 {_short('、'.join(view.invalidated_by[identifier]))} 更正，不参与推导")
        problem = record.get("problem")
        if problem:
            text = f"- 问题：{_short(problem.get('title') or problem['id'], 80)}（{problem['id']}）"
            if "status" in problem:
                text += f" · 状态：{PROBLEM_STATUSES[problem['status']]}"
            lines.append(text)
            if "outcome" in problem:
                lines.append(f"- 结果：{_short(problem['outcome'])}")
            if "check_back" in problem:
                check = problem["check_back"]
                when = "；".join(value for value in (check.get("on"), check.get("when")) if value)
                lines.append(f"- 回访：{_short(check['question'])}（{_short(when, 80)}）")
        if record.get("user_work"):
            counts = {}
            for item in record["user_work"]:
                counts[item["kind"]] = counts.get(item["kind"], 0) + 1
            lines.append("- 用户产出：" + "，".join(f"{WORK_KINDS[kind]} {count}" for kind, count in counts.items()))
        if record.get("methods"):
            lines.append(f"- 方法：{_short('、'.join(record['methods']))}")
        for update in record.get("ability_updates", []):
            lines.append(f"- 能力变化：{update['ability_id']}（{update['stage']}）"
                         f"{LEVEL_NAMES[update['from']]} → {LEVEL_NAMES[update['to']]}")
        if "stage_update" in record:
            lines.append(f"- 阶段：{STAGES[record['stage_update']['stage']]}；{_short(record['stage_update']['reason'])}")
        for key, label in (("milestone", "里程碑"), ("context_ref", "上下文"), ("assistance", "获得帮助"),
                           ("unresolved", "未决"), ("next_step", "下一步")):
            if record.get(key):
                lines.append(f"- {label}：{_short(record[key])}")
        if record.get("preferences"):
            lines.append(f"- 偏好：{_short('；'.join(record['preferences']))}")
        legacy = record.get("migrated_from", {}).get("user_contribution")
        if isinstance(legacy, str) and legacy.strip():
            lines.append(f"- v1 用户贡献（未分级，不计证据）：{_short(legacy)}")
        for correction in record.get("corrections", []):
            target = correction.get("record_id") or correction["record_ref"]
            flag = "，作废原记录" if correction["invalidate"] else ""
            lines.append(f"- 更正：{_short(target)}；{_short(correction['reason'])}{flag}")
        lines.append("")
    return before + "\n".join(lines) + LOG_END + after


def write_index(root, view):
    atomic_write_text(Path(root) / "growth-log.md", log_content(root, view))


def rebuild_index(root, timeout=10.0):
    root = Path(root)
    # A repair request on an absent directory must not create a profile.
    if not root.exists():
        return {"data_dir": str(root), "record_count": 0, "rebuilt": False}
    with file_lock(root, timeout=timeout):
        view = View(load_records(root), load_state(root))
        write_index(root, view)
    return {"data_dir": str(root), "record_count": len(view.records), "rebuilt": True}


# ---------------------------------------------------------------- writing

def check_registered(record, state):
    known = set(known_ability_ids(state))
    ids = [item["ability_id"] for item in record.get("observations", [])]
    ids += [item["ability_id"] for item in record.get("ability_updates", [])]
    unknown = sorted(set(ids) - known)
    if unknown:
        raise ValueError(f"能力 {'、'.join(unknown)} 尚未注册；自定义能力先用 ability register 注册")


def append_record(root, value, timeout=10.0, now=None):
    record = validate_record(value)
    root = Path(root)
    with file_lock(root, timeout=timeout):
        state = load_state(root)
        if migration_needed(root, state):
            raise ValueError("检测到尚未迁移的 v1 数据（events/、cases/ 等）；请先运行 migrate，再写新记录")
        records = load_records(root)
        existing = next((item for item in records if item["record_id"] == record["record_id"]), None)
        warnings, changes = [], []
        if existing is not None:
            if without_recorded_at(existing) != record:
                raise ValueError(f"record_id {record['record_id']} 已存在且内容不同；记录不可修改，"
                                 "请用新的 record_id 写一条 correction")
            record = existing
            view = View(records, state)
        else:
            check_registered(record, state)
            ids = {item["record_id"] for item in records}
            for correction in record.get("corrections", []):
                if "record_id" in correction and correction["record_id"] not in ids:
                    raise ValueError(f"更正目标记录不存在：{correction['record_id']}")
            before = View(records, state)
            record["recorded_at"] = next_recorded_at(records, now)
            view = View(records + [record], state)
            failed = [item for item in view.voided if item["record_id"] == record["record_id"]]
            if failed:
                details = "；".join(f"{item['ability_id']}（{item['stage']}）{LEVEL_NAMES[item['from']]} → "
                                   f"{LEVEL_NAMES[item['to']]}：" + "；".join(item["errors"]) for item in failed)
                raise ValueError("能力变化未通过证据门槛：" + details)
            problem = record.get("problem")
            if problem and not view.problems[problem["id"]]["title"]:
                raise ValueError(f"问题 {problem['id']} 第一次出现，需要 problem.title")
            newly_voided = {(item["record_id"], item["ability_id"], item["stage"], item["to"]) for item in view.voided}
            newly_voided -= {(item["record_id"], item["ability_id"], item["stage"], item["to"]) for item in before.voided}
            for record_id, ability_id, stage, target in sorted(newly_voided):
                warnings.append(f"本条更正使 {record_id} 中 {ability_id}（{stage}）→ {LEVEL_NAMES[target]} 的变化失去依据，"
                                "请核对后另写记录更新能力")
            changes = [change_summary(view, item) for item in view.applied if item["record_id"] == record["record_id"]]
            path = root / "records" / (record["record_id"] + ".json")
            # The directory lock serializes the existence check and atomic publication.
            atomic_write_json(path, record)
        path = root / "records" / (record["record_id"] + ".json")
        if validate_record(read_json(path), stored=True) != record:
            raise ValueError(f"记录写入后读回内容不一致：{path}")
        write_index(root, view)
    result = {"data_dir": str(root), "record_id": record["record_id"], "created": existing is None,
              "recorded_at": record["recorded_at"], "readback_verified": True,
              "record_file": str(path), "growth_log": str(root / "growth-log.md")}
    if changes:
        result["ability_changes"] = changes
    if warnings:
        result["warnings"] = warnings
    return result


# ---------------------------------------------------------------- reading

def init(root, timeout=10.0):
    root = Path(root)
    created, kept = [], []
    with file_lock(root, timeout=timeout):
        for name in ("profile.md", "business-context.md", "growth-log.md", "state.json"):
            target = root / name
            try:
                # Exclusive creation also preserves files from non-cooperating writers.
                with target.open("xb") as handle:
                    handle.write((SKILL_DIR / "templates" / name).read_bytes())
                created.append(name)
            except FileExistsError:
                kept.append(name)
        for name in ("records", "reports", "knowledge"):
            (root / name).mkdir(exist_ok=True)
        state = load_state(root)
        needed = migration_needed(root, state)
    return {"data_dir": str(root), "created": created, "preserved": kept, "migration_needed": needed}


def recent(root, limit=5, problem_id=None, context_ref=None):
    if type(limit) is not int or limit < 1:
        raise ValueError("limit 必须是正整数")
    root = Path(root)
    records = load_records(root) if root.exists() else []
    view = View(records, load_state(root) if root.exists() else None)
    selected = [record for record in view.records
                if (problem_id is None or record.get("problem", {}).get("id") == problem_id)
                and (context_ref is None or record.get("context_ref") == context_ref)][-limit:]
    selected_ids = {record["record_id"] for record in selected}
    related = set(selected_ids)
    # Include original records and later corrections even when their context differs.
    changed = True
    while changed:
        changed = False
        for record in view.records:
            links = {item["record_id"] for item in record.get("corrections", []) if "record_id" in item}
            links.add(record["record_id"])
            if links & related and not links <= related:
                related.update(links)
                changed = True
    return {
        "data_dir": str(root),
        "records": selected,
        "related_records": [record for record in view.records if record["record_id"] in related - selected_ids],
        "invalidated": {key: value for key, value in view.invalidated_by.items() if key in related},
        "note": "按发生日期排序，同日按写入先后。作废的记录保留原文，但不参与推导。",
    }


def record_brief(view, record):
    item = {"record_id": record["record_id"], "date": record["date"], "kind": record["kind"],
            "summary": record["summary"]}
    if record.get("problem"):
        item["problem_id"] = record["problem"]["id"]
    if record["record_id"] in view.invalidated_by:
        item["invalidated_by"] = view.invalidated_by[record["record_id"]]
    return item


def report_cursor(view, today):
    """Compute whether a growth report is due, and why."""
    state = view.state
    history = state["report"]["history"]
    covered = set()
    for entry in history:
        covered.update(entry["record_ids"])
    last = max(history, key=lambda entry: (entry["date"], entry.get("built_at", ""))) if history else None
    fresh = [record for record in view.valid if record["record_id"] not in covered]
    fresh_ids = {record["record_id"] for record in fresh}
    with_work = []
    for record in fresh:
        if record.get("problem") and _work_kinds(record) & {"independent", "guided"}:
            if record["problem"]["id"] not in with_work:
                with_work.append(record["problem"]["id"])
    if last:
        since, basis = last["date"], "last_report"
    elif view.valid:
        since, basis = min(record["date"] for record in view.valid), "first_record"
    else:
        since, basis = None, None
    days = (today - date.fromisoformat(since)).days if since else None
    moments = [item for item in view.key_moments if item["record_id"] in fresh_ids]
    moments += [{"type": "ability_up", "record_id": item["record_id"], "date": item["date"],
                 "ability_id": item["ability_id"], "stage": item["stage"], "from": item["from"], "to": item["to"]}
                for item in view.applied if item["record_id"] in fresh_ids and item["direction"] == "up"]
    moments += [{"type": "milestone", "record_id": record["record_id"], "date": record["date"],
                 "milestone": record["milestone"]} for record in fresh if record.get("milestone")]
    moments.sort(key=lambda item: (item["date"], item["record_id"]))
    reasons = []
    if len(with_work) >= REPORT_PROBLEM_THRESHOLD:
        reasons.append({"code": "problems", "problem_ids": with_work,
                        "text": f"上次报告后已有 {len(with_work)} 个问题含用户本人的尝试"})
    if days is not None and days >= REPORT_DAYS_THRESHOLD and fresh:
        anchor = "上次报告" if basis == "last_report" else "第一条记录"
        reasons.append({"code": "elapsed", "days": days,
                        "text": f"距{anchor}（{since}）已 {days} 天，期间有 {len(fresh)} 条新记录"})
    if moments:
        reasons.append({"code": "key_moment", "items": moments,
                        "text": f"出现 {len(moments)} 个关键节点（问题有结果、能力提升或里程碑）"})
    fingerprint = hashlib.sha256(json.dumps(sorted(fresh_ids)).encode("utf-8")).hexdigest()
    deferred = state["report"]["deferred"]
    is_deferred = bool(deferred) and deferred["fingerprint"] == fingerprint
    return {
        "due": bool(reasons) and not is_deferred,
        "reasons": reasons,
        "since": since,
        "since_basis": basis,
        "counts": {"new_records": len(fresh), "problems_with_user_work": len(with_work),
                   "days_since": days, "key_moments": len(moments)},
        "deferred": is_deferred,
        "mode": state["settings"]["report_mode"],
        "last_report": {key: last[key] for key in ("date", "file", "source") if key in last} if last else None,
        "fingerprint": fingerprint,
        "new_record_ids": [record["record_id"] for record in fresh],
    }


def ability_snapshot(view):
    stage = view.stage["stage"] if view.stage else None
    latest_observation = {}
    for record in view.written:
        for item in record.get("observations", []):
            latest_observation[item["ability_id"]] = {**item, "date": record["date"], "record_id": record["record_id"]}
    current = []
    if stage:
        for ability_id in known_ability_ids(view.state):
            level = view.level(ability_id, stage)
            changes = view.levels.get((ability_id, stage), {}).get("changes", [])
            item = {"ability_id": ability_id, "name": ability_label(view.state, ability_id),
                    "level": level, "level_name": LEVEL_NAMES[level],
                    "last_change": change_summary(view, changes[-1]) if changes else None}
            if ability_id in latest_observation:
                item["latest_observation"] = latest_observation[ability_id]
            current.append(item)
    others = []
    for (ability_id, item_stage), value in sorted(view.levels.items(), key=lambda pair: (pair[0][1], pair[0][0])):
        if item_stage == stage:
            continue
        others.append({"ability_id": ability_id, "name": ability_label(view.state, ability_id),
                       "stage": item_stage, "stage_name": STAGES[item_stage],
                       "level": value["level"], "level_name": LEVEL_NAMES[value["level"]],
                       "changes": [change_summary(view, entry) for entry in value["changes"]]})
    result = {"stage": stage, "current": current, "other_stages": others,
              "voided_updates": [{key: item[key] for key in ("record_id", "date", "ability_id", "stage", "from", "to", "errors")}
                                 for item in view.voided]}
    if not stage:
        result["note"] = "尚未记录阶段（stage_update）；能力程度按阶段分别追踪"
    return result


def status(root, today=None, recent_limit=5):
    root = Path(root)
    today = today_value(today)
    exists = root.exists()
    state = load_state(root) if exists else default_state()
    records = load_records(root) if exists else []
    view = View(records, state)
    needed = migration_needed(root, state) if exists else False
    result = {
        "data_dir": str(root),
        "exists": exists,
        "initialized": (root / "state.json").exists(),
        "today": today.isoformat(),
        "migration_needed": needed,
        "stage": view.stage,
        "abilities": ability_snapshot(view),
        "open_problems": view.open_problems(),
        "follow_ups_due": view.pending_check_backs(today),
        "report": report_cursor(view, today),
        "recent": [record_brief(view, record) for record in view.records[-recent_limit:]],
        "settings": state["settings"],
        "counts": {"records": len(view.records), "valid_records": len(view.valid),
                   "problems": len(view.problems)},
    }
    if needed:
        files = v1_files(root)
        result["migration"] = {
            "v1_events": sum(1 for path in files if path.parent.name == "events"),
            "v1_cases": sum(1 for path in files if path.parent.name == "cases"),
            "hint": "运行 migrate --dry-run 预览，再运行 migrate；原文件会复制到 legacy-v1/",
        }
    return result
