"""Migrate a v1 data directory (events/, cases/, review-state.json, abilities.json) to v2.

The v1 files are copied to legacy-v1/<timestamp>/ before anything is written and
are never deleted. profile.md, business-context.md and learning-plan.md are not
rewritten. Running the migration again on unchanged v1 data does nothing.
"""
import copy
from datetime import datetime, timezone
from pathlib import Path
import shutil

from storage import atomic_write_json, file_lock
import records as rec

WORK_KINDS = {"independent": "independent", "guided": "guided",
              "model_demo": "demo", "acknowledgement": "acknowledgement"}
BACKUP_NAMES = ("events", "cases", "abilities.json", "review-state.json", "learning-plan.md",
                "growth-log.md", "profile.md", "business-context.md")
UNTOUCHED = ("profile.md", "business-context.md", "learning-plan.md")


def _need(condition, path, message):
    if not condition:
        raise ValueError(f"v1 文件 {path} 格式不正确：{message}")


def _nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def read_v1_abilities(root):
    path = root / "abilities.json"
    if not path.exists():
        return [], []
    value = rec.read_json(path)
    _need(isinstance(value, dict) and value.get("schema_version") == 1
          and isinstance(value.get("abilities"), list), path, "需要 schema_version 1 与 abilities 列表")
    for ability in value["abilities"]:
        rec.validate_ability(ability, str(path))
    history = value.get("history", [])
    _need(isinstance(history, list), path, "history 必须是列表")
    for entry in history:
        _need(isinstance(entry, dict), path, "history 条目必须是对象")
        rec.validate_ability(entry.get("previous_definition"), str(path))
        rec._timestamp(entry.get("replaced_at"), f"{path} history.replaced_at")
    return value["abilities"], history


def read_v1_review(root):
    path = root / "review-state.json"
    if not path.exists():
        return [], []
    value = rec.read_json(path)
    _need(isinstance(value, dict) and value.get("schema_version") == 1, path, "需要 schema_version 1")
    reviewed = value.get("reviewed_case_ids", [])
    history = value.get("history", [])
    _need(isinstance(reviewed, list) and all(isinstance(item, str) for item in reviewed), path, "reviewed_case_ids")
    _need(isinstance(history, list) and all(isinstance(item, dict) for item in history), path, "history")
    for entry in history:
        rec.parse_date(entry.get("date"), f"{path} history.date")
    return reviewed, history


def read_v1_events(root):
    events = []
    for path in sorted((root / "events").glob("*.json")):
        value = rec.read_json(path)
        _need(isinstance(value, dict) and value.get("schema_version", 1) == 1, path, "需要 schema_version 1")
        _need(isinstance(value.get("event_id"), str) and rec.SLUG.fullmatch(value["event_id"])
              and value["event_id"] == path.stem, path, "event_id 无效或与文件名不一致")
        rec.parse_date(value.get("date"), f"{path} date")
        for key in ("kind", "summary", "source"):
            _need(_nonempty(value.get(key)), path, f"{key} 必须是非空文字")
        if "case_id" in value:
            _need(isinstance(value["case_id"], str) and rec.SLUG.fullmatch(value["case_id"]), path, "case_id 无效")
        corrections = value.get("corrections", [])
        _need(isinstance(corrections, list) and all(isinstance(item, dict) and _nonempty(item.get("reason"))
                                                    and (_nonempty(item.get("event_id")) or _nonempty(item.get("record_ref")))
                                                    for item in corrections), path, "corrections 格式不正确")
        events.append((path, value))
    return events


def read_v1_cases(root, known_abilities):
    cases = {}
    for path in sorted((root / "cases").glob("*.json")):
        value = rec.read_json(path)
        _need(isinstance(value, dict) and value.get("schema_version") == 1, path, "需要 schema_version 1")
        identifier = value.get("case_id")
        _need(isinstance(identifier, str) and rec.SLUG.fullmatch(identifier), path, "case_id 无效")
        _need(identifier not in cases, path, f"case_id {identifier} 与其他文件重复")
        _need(_nonempty(value.get("title")), path, "title 必填")
        _need(value.get("owner") in {"self", "third_party"}, path, "owner")
        _need(value.get("origin") in {"work", "simulation", "legacy"}, path, "origin")
        _need(value.get("status") in {"open", "closed"}, path, "status")
        attempts = value.get("attempts")
        _need(isinstance(attempts, list), path, "attempts 必须是列表")
        seen = set()
        for attempt in attempts:
            _need(isinstance(attempt, dict), path, "attempt 必须是对象")
            aid = attempt.get("attempt_id")
            _need(isinstance(aid, str) and rec.SLUG.fullmatch(aid) and aid not in seen, path, "attempt_id 无效或重复")
            seen.add(aid)
            _need(attempt.get("kind") in WORK_KINDS, path, "attempt kind")
            _need(attempt.get("status") in {"active", "withdrawn", "unverified"}, path, "attempt status")
            for key in ("user_work", "source"):
                _need(isinstance(attempt.get(key), str), path, f"attempt {key} 必须是文字")
            if attempt.get("date"):
                rec.parse_date(attempt["date"], f"{path} attempt.date")
            _need(attempt["status"] != "active" or attempt.get("date"), path, "active 尝试需要日期")
            observations = attempt.get("observations", [])
            _need(isinstance(observations, list), path, "observations 必须是列表")
            for item in observations:
                _need(isinstance(item, dict) and item.get("ability_id") in known_abilities, path,
                      f"observation 的能力 {item.get('ability_id') if isinstance(item, dict) else item} 未注册")
                _need(item.get("status") in rec.OBSERVATION_STATUSES and _nonempty(item.get("text")), path, "observation")
        cases[identifier] = (path, value)
    return cases


def event_record(root, path, event, titles):
    original = event["kind"]
    kind = original if original in rec.KINDS else "discussion"
    meta = {"version": 1, "type": "event", "file": path.relative_to(root).as_posix()}
    record = {"schema_version": rec.SCHEMA_VERSION, "record_id": event["event_id"], "date": event["date"],
              "kind": kind, "summary": event["summary"], "source": event["source"]}
    if event.get("case_id"):
        record["problem"] = {"id": event["case_id"], "title": titles.get(event["case_id"]) or f"v1 案例 {event['case_id']}"}
    for key in ("assistance", "unresolved", "next_step", "context_ref"):
        if _nonempty(event.get(key)):
            record[key] = event[key]
    preferences = [item for item in event.get("preferences", []) if _nonempty(item)]
    if preferences:
        record["preferences"] = preferences
    corrections = []
    for item in event.get("corrections", []):
        if _nonempty(item.get("event_id")):
            corrections.append({"record_id": item["event_id"], "reason": item["reason"], "invalidate": False})
        else:
            corrections.append({"record_ref": item["record_ref"], "reason": item["reason"], "invalidate": False})
    if corrections:
        record["corrections"] = corrections
    if (kind == "correction" and not corrections) or (kind == "follow_up" and "problem" not in record):
        kind = record["kind"] = "discussion"
    if kind == "milestone":
        record["milestone"] = event["summary"]
    if kind != original:
        meta["kind"] = original
    if event.get("recorded_at"):
        meta["recorded_at"] = event["recorded_at"]
    if _nonempty(event.get("user_contribution")):
        meta["user_contribution"] = event["user_contribution"]
    record["migrated_from"] = meta
    return (event["date"], 1, event.get("recorded_at", ""), event["event_id"], 0), record


def case_records(root, path, case):
    """One problem header, one record per attempt, invalidations for withdrawn attempts, and closure."""
    cid, title = case["case_id"], case["title"]
    rel = path.relative_to(root).as_posix()
    dated = sorted(attempt["date"] for attempt in case["attempts"] if attempt.get("date"))
    first = dated[0] if dated else datetime.fromtimestamp(path.stat().st_mtime).date().isoformat()
    last = dated[-1] if dated else first
    planned = []
    meta = {"version": 1, "type": "case", "file": rel, "owner": case["owner"], "origin": case["origin"],
            "status": case["status"], "ability_ids": list(case.get("ability_ids", []))}
    if "context_snapshot" in case:
        meta["context_snapshot"] = case["context_snapshot"]
    header = {"schema_version": rec.SCHEMA_VERSION, "record_id": f"v1-case-{cid}", "date": first,
              "kind": "discussion", "summary": f"v1 案例迁移：{title}", "source": f"v1 案例文件 {rel}",
              "problem": {"id": cid, "title": title}, "migrated_from": meta}
    if _nonempty(case.get("context_ref")):
        header["context_ref"] = case["context_ref"]
    planned.append(((first, 0, "", cid, 0), header))
    for index, attempt in enumerate(case["attempts"]):
        stamp = attempt.get("date") or first
        identifier = f"v1-case-{cid}-{attempt['attempt_id']}"
        summary = f"v1 案例尝试：{title}"
        if _nonempty(attempt.get("result")):
            summary += f"；结果：{attempt['result']}"
        source = attempt["source"] if _nonempty(attempt["source"]) else f"v1 案例文件 {rel}"
        record = {"schema_version": rec.SCHEMA_VERSION, "record_id": identifier, "date": stamp, "kind": "attempt",
                  "summary": summary, "source": source, "problem": {"id": cid, "title": title}}
        excluded = None
        if case["owner"] != "self":
            excluded = "第三方案例，不是本人产出"
        elif case["origin"] == "legacy":
            excluded = "旧档案导入，未核实"
        elif attempt["status"] == "unverified":
            excluded = "尝试未核实"
        elif not _nonempty(attempt["source"]):
            excluded = "缺少来源"
        if _nonempty(attempt["user_work"]):
            if excluded:
                record["unresolved"] = f"v1 中此尝试不计入本人证据（{excluded}）：{attempt['user_work']}"
            else:
                record["user_work"] = [{"kind": WORK_KINDS[attempt["kind"]], "content": attempt["user_work"],
                                        "source": attempt["source"]}]
        if _nonempty(attempt.get("feedback")):
            record["assistance"] = attempt["feedback"]
        if attempt.get("observations"):
            record["observations"] = [{"ability_id": item["ability_id"], "text": item["text"], "status": item["status"]}
                                      for item in attempt["observations"]]
        if _nonempty(case.get("context_ref")):
            record["context_ref"] = case["context_ref"]
        record["migrated_from"] = {"version": 1, "type": "case_attempt", "file": rel, "case_id": cid,
                                   "attempt_id": attempt["attempt_id"], "kind": attempt["kind"],
                                   "status": attempt["status"], "owner": case["owner"], "origin": case["origin"]}
        planned.append(((stamp, 2, cid, "", index * 2), record))
        if attempt["status"] == "withdrawn":
            planned.append(((stamp, 2, cid, "", index * 2 + 1), {
                "schema_version": rec.SCHEMA_VERSION, "record_id": identifier + "-withdrawn", "date": stamp,
                "kind": "correction", "summary": f"v1 中尝试 {attempt['attempt_id']} 已撤回，对应记录作废",
                "source": f"v1 案例文件 {rel}",
                "corrections": [{"record_id": identifier, "reason": "v1 中该尝试的状态为 withdrawn", "invalidate": True}],
                "migrated_from": {"version": 1, "type": "case_withdrawal", "file": rel, "case_id": cid,
                                  "attempt_id": attempt["attempt_id"]},
            }))
    if case["status"] == "closed":
        planned.append(((last, 3, cid, "", 0), {
            "schema_version": rec.SCHEMA_VERSION, "record_id": f"v1-case-{cid}-closed", "date": last,
            "kind": "follow_up", "summary": f"v1 案例已关闭：{title}", "source": f"v1 案例文件 {rel}",
            "problem": {"id": cid, "status": "closed"},
            "migrated_from": {"version": 1, "type": "case_closed", "file": rel, "case_id": cid},
        }))
    return planned


def build_plan(root, today=None):
    root = Path(root)
    files = rec.v1_files(root)
    state = rec.load_state(root)
    existing = rec.load_records(root)
    fingerprint = rec.v1_fingerprint(root) if files else None
    summary = {"data_dir": str(root), "v1_files": [path.relative_to(root).as_posix() for path in files],
               "needed": rec.migration_needed(root, state)}
    if not files:
        summary.update({"records": {"create": [], "unchanged": [], "conflicts": []}, "conflicts": []})
        return summary, None

    conflicts = []
    new_state = copy.deepcopy(state)
    abilities, ability_history = read_v1_abilities(root)
    ability_plan = {"add": [], "unchanged": []}
    for ability in abilities:
        current = next((item for item in new_state["abilities"] if item["id"] == ability["id"]), None)
        if current is None:
            new_state["abilities"].append(ability)
            ability_plan["add"].append(ability["id"])
        elif current == ability:
            ability_plan["unchanged"].append(ability["id"])
        else:
            conflicts.append(f"自定义能力 {ability['id']} 在 v1 与 state.json 中定义不同")
    for entry in ability_history:
        if entry not in new_state["ability_history"]:
            new_state["ability_history"].append(entry)

    known = set(rec.known_ability_ids(new_state))
    cases = read_v1_cases(root, known)
    events = read_v1_events(root)
    titles = {cid: case["title"] for cid, (_, case) in cases.items()}
    planned = [event_record(root, path, event, titles) for path, event in events]
    case_record_ids = {}
    for cid, (path, case) in cases.items():
        items = case_records(root, path, case)
        case_record_ids[cid] = [record["record_id"] for _, record in items]
        planned += items
    planned.sort(key=lambda pair: pair[0])

    seen, normalized = set(), []
    for _, record in planned:
        if record["record_id"] in seen:
            conflicts.append(f"迁移生成了重复的 record_id：{record['record_id']}")
            continue
        seen.add(record["record_id"])
        normalized.append(rec.validate_record(record))
    by_id = {record["record_id"]: record for record in existing}
    all_ids = set(by_id) | seen
    for record in normalized:
        for correction in record.get("corrections", []):
            if "record_id" in correction and correction["record_id"] not in all_ids:
                # Keep a dangling v1 link as a locator instead of failing the whole migration.
                correction["record_ref"] = f"events/{correction.pop('record_id')}.json"
        try:
            rec.check_registered(record, new_state)
        except ValueError as exc:
            conflicts.append(f"{record['record_id']}：{exc}")
    create, unchanged = [], []
    for record in normalized:
        current = by_id.get(record["record_id"])
        if current is None:
            create.append(record)
        elif rec.without_recorded_at(current) == record:
            unchanged.append(record["record_id"])
        else:
            conflicts.append(f"记录 {record['record_id']} 已存在且内容不同（v1 数据在上次迁移后被修改过？）")

    reviewed, review_history = read_v1_review(root)
    report_plan = None
    if reviewed:
        review_date = max((entry["date"] for entry in review_history), default=rec.today_value(today).isoformat())
        covered = set()
        for cid in reviewed:
            covered.update(case_record_ids.get(cid, []))
        for path, event in events:
            if event.get("case_id") in reviewed or event["date"] <= review_date:
                covered.add(event["event_id"])
        entry = {"source": "v1", "date": review_date, "record_ids": sorted(covered & all_ids),
                 "case_ids": sorted(reviewed), "note": "v1 阶段回顾，迁移时导入；回顾日及之前的事件视为已回顾"}
        history = new_state["report"]["history"]
        position = next((index for index, item in enumerate(history) if item["source"] == "v1"), None)
        if position is None:
            history.insert(0, entry)
            report_plan = {"action": "add", "entry": entry}
        elif history[position] != entry:
            history[position] = entry
            report_plan = {"action": "update", "entry": entry}
        else:
            report_plan = {"action": "unchanged", "entry": entry}

    log = root / "growth-log.md"
    if not log.exists():
        log_plan = "create_from_template"
    else:
        text = log.read_text(encoding="utf-8")
        log_plan = ("update_v2_block" if rec.LOG_START in text else
                    "replace_v1_block" if rec.V1_LOG_START in text else "append_block")
    state_changed = new_state != state
    done = fingerprint in [item.get("v1_fingerprint") for item in state["migrations"]]
    summary.update({
        "records": {"create": [{"record_id": record["record_id"], "date": record["date"], "kind": record["kind"],
                                "from": record["migrated_from"].get("file")} for record in create],
                    "unchanged": unchanged},
        "abilities": ability_plan,
        "report_history": report_plan,
        "growth_log": log_plan,
        "backup": [name for name in BACKUP_NAMES if (root / name).exists()],
        "untouched": [name for name in UNTOUCHED if (root / name).exists()],
        "conflicts": conflicts,
        "changes_pending": bool(create) or state_changed or not done,
    })
    actions = {"create": create, "state": new_state, "fingerprint": fingerprint, "unchanged": len(unchanged)}
    return summary, actions


def backup_v1(root, names):
    base = root / "legacy-v1"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = base / stamp
    counter = 1
    while target.exists():
        counter += 1
        target = base / f"{stamp}-{counter}"
    target.mkdir(parents=True)
    for name in names:
        source = root / name
        if source.is_dir():
            shutil.copytree(source, target / name)
        else:
            shutil.copy2(source, target / name)
    return target


def migrate(root, dry_run=False, today=None, timeout=10.0, now=None):
    root = Path(root)
    if dry_run:
        # Read-only: no lock file, no directories, no writes.
        if not root.exists():
            return {"data_dir": str(root), "dry_run": True, "needed": False, "v1_files": []}
        summary, _ = build_plan(root, today)
        return {**summary, "dry_run": True}
    if not root.exists():
        return {"data_dir": str(root), "dry_run": False, "needed": False, "changed": False, "v1_files": []}
    with file_lock(root, timeout=timeout):
        summary, actions = build_plan(root, today)
        if actions is None:
            return {**summary, "dry_run": False, "changed": False, "note": "没有发现 v1 数据"}
        if summary["conflicts"]:
            raise ValueError("迁移中止，没有写入任何文件：" + "；".join(summary["conflicts"]))
        if not summary["changes_pending"]:
            return {**summary, "dry_run": False, "changed": False, "note": "v1 数据已迁移，没有新的变化"}
        legacy = backup_v1(root, summary["backup"])
        existing = rec.load_records(root)
        stamp = now or datetime.now(timezone.utc)
        written = []
        for record in actions["create"]:
            record["recorded_at"] = rec.next_recorded_at(existing + written, stamp)
            path = root / "records" / (record["record_id"] + ".json")
            atomic_write_json(path, record)
            if rec.validate_record(rec.read_json(path), stored=True) != record:
                raise ValueError(f"记录写入后读回内容不一致：{path}")
            written.append(record)
        state = actions["state"]
        view = rec.View(existing + written, state)
        rec.write_index(root, view)
        state["migrations"].append({
            "from_version": 1, "migrated_at": datetime.now(timezone.utc).isoformat(),
            "legacy_dir": legacy.relative_to(root).as_posix(), "v1_fingerprint": actions["fingerprint"],
            "records_created": len(written), "records_unchanged": actions["unchanged"],
        })
        rec.write_state(root, state)
    return {**summary, "dry_run": False, "changed": True, "legacy_dir": str(legacy),
            "records_created": len(written), "migration_needed": False}
