#!/usr/bin/env python3
"""Store immutable learning events and retrieve recent, traceable context."""
import argparse
from datetime import date, datetime, timedelta, timezone
import html
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile

SKILL_DIR = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("pm_grow_storage", Path(__file__).with_name("storage.py"))
_storage = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_storage)
file_lock = _storage.file_lock
atomic_write_json = _storage.atomic_write_json
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
START = "<!-- pm-grow:events:start -->"
END = "<!-- pm-grow:events:end -->"
TEXT_FIELDS = ("user_contribution", "assistance", "unresolved", "next_step")
FIELDS = {"schema_version", "event_id", "date", "recorded_at", "kind", "summary", "source",
          "case_id", "context_ref", "preferences", "corrections", *TEXT_FIELDS}


def data_root(value=None):
    return Path(value or os.environ.get("PM_GROW_DATA_DIR") or Path.home() / "pm-grow-data").expanduser().resolve()


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read {path}: {exc}") from exc


def validate_event(value, stored=False):
    if not isinstance(value, dict) or set(value) - FIELDS:
        raise ValueError("Event must be an object with supported fields only")
    event = dict(value)
    if not stored:
        # Input metadata never overrides the time assigned by the writer.
        event.pop("recorded_at", None)
    elif "recorded_at" in event:
        try:
            timestamp = datetime.fromisoformat(event["recorded_at"])
            if timestamp.utcoffset() != timedelta(0) or timestamp.isoformat(timespec="microseconds") != event["recorded_at"]:
                raise ValueError()
        except (ValueError, TypeError) as exc:
            raise ValueError("Stored recorded_at must be a UTC timestamp with microseconds") from exc
    event.setdefault("schema_version", 1)
    if type(event["schema_version"]) is not int or event["schema_version"] != 1:
        raise ValueError("Expected event schema_version 1")
    for key in ("event_id", "case_id"):
        if key == "case_id" and key not in event:
            continue
        if not isinstance(event.get(key), str) or not SLUG.fullmatch(event[key]):
            raise ValueError(f"Invalid {key}; use lowercase letters, digits and hyphens")
    for key in ("date", "kind", "summary", "source"):
        if not isinstance(event.get(key), str) or not event[key].strip():
            raise ValueError(f"Event {key} must be nonempty text")
    try:
        if date.fromisoformat(event["date"]).isoformat() != event["date"]:
            raise ValueError()
    except ValueError as exc:
        raise ValueError("Event date must be a valid YYYY-MM-DD date") from exc
    for key in TEXT_FIELDS + ("context_ref",):
        if key in event and not isinstance(event[key], str):
            raise ValueError(f"Event {key} must be text")
    if "context_ref" in event and not event["context_ref"].strip():
        raise ValueError("Omit unknown context_ref instead of providing empty text")
    if "preferences" in event and (not isinstance(event["preferences"], list) or any(
            not isinstance(item, str) or not item.strip() for item in event["preferences"])):
        raise ValueError("Event preferences must be a list of nonempty text")
    corrections = event.get("corrections", [])
    if not isinstance(corrections, list):
        raise ValueError("Event corrections must be a list")
    for correction in corrections:
        if not isinstance(correction, dict) or set(correction) - {"event_id", "record_ref", "reason"}:
            raise ValueError("Each correction must contain a target and reason")
        targets = [key for key in ("event_id", "record_ref") if key in correction]
        if len(targets) != 1 or not isinstance(correction.get("reason"), str) or not correction["reason"].strip():
            raise ValueError("Each correction needs exactly one event_id or record_ref and a nonempty reason")
        target = correction[targets[0]]
        if not isinstance(target, str) or not target.strip():
            raise ValueError("Correction target must be nonempty text")
        if targets[0] == "event_id" and (not SLUG.fullmatch(target) or target == event["event_id"]):
            raise ValueError("Correction event_id must be a valid different event ID")
    if event["kind"] == "correction" and not corrections:
        raise ValueError("A correction event needs corrections linking its original record")
    return event


def load_events(root):
    events = []
    for path in (root / "events").glob("*.json"):
        event = validate_event(read_json(path), stored=True)
        if path.stem != event["event_id"]:
            raise ValueError(f"Event filename and event_id differ: {path}")
        events.append(event)
    return sorted(events, key=event_order)


def event_order(event):
    # Legacy events have no recoverable write order; keep their deterministic ID order.
    return event["date"], event.get("recorded_at", ""), event["event_id"]


def next_recorded_at(events):
    timestamp = datetime.now(timezone.utc)
    previous = [datetime.fromisoformat(event["recorded_at"]) for event in events if "recorded_at" in event]
    if previous and timestamp <= max(previous):
        timestamp = max(previous) + timedelta(microseconds=1)
    return timestamp.isoformat(timespec="microseconds")


def short(value, limit=240):
    text = " ".join(value.split())
    return html.escape(text if len(text) <= limit else text[:limit] + "…", quote=False)


def log_content(root, events):
    path = root / "growth-log.md"
    source = path if path.exists() else SKILL_DIR / "templates" / "growth-log.md"
    with source.open(encoding="utf-8", newline="") as handle:
        original = handle.read()
    if START in original or END in original:
        if original.count(START) != 1 or original.count(END) != 1 or original.index(START) > original.index(END):
            raise ValueError("Invalid managed event markers in growth-log.md; preserve manual text and repair markers first")
        before, rest = original.split(START)
        _, after = rest.split(END)
    else:
        before, after = original + ("" if original.endswith("\n") else "\n") + "\n", "\n"
    lines = [START, "## 日常摘要索引", "", "由 events/ 生成；人工记录请写在本区域之外。摘要数量不代表能力证据数量。", ""]
    for event in events:
        identifier = event["event_id"]
        lines += [f"### {event['date']} · {short(event['kind'], 64)} · {identifier}", "",
                  f"{short(event['summary'])}", "",
                  f"- 来源：{short(event['source'])}；[完整事件](events/{identifier}.json)"]
        for key, label in (("case_id", "案例"), ("context_ref", "上下文"),
                           ("user_contribution", "用户贡献"), ("assistance", "获得帮助"),
                           ("unresolved", "未决"), ("next_step", "下一步")):
            if event.get(key):
                lines.append(f"- {label}：{short(event[key])}")
        if event.get("preferences"):
            lines.append(f"- 偏好：{short('；'.join(event['preferences']))}")
        for correction in event.get("corrections", []):
            target = correction.get("event_id") or correction["record_ref"]
            lines.append(f"- 更正关联：{short(target)}；{short(correction['reason'])}")
        lines.append("")
    return before + "\n".join(lines) + END + after


def write_log(root, content):
    target = root / "growth-log.md"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=root, prefix=".pm-grow-log-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    with target.open(encoding="utf-8", newline="") as handle:
        if handle.read() != content:
            raise ValueError("growth-log.md readback differs from the saved index")


def append_event(root, value, timeout=10.0):
    event = validate_event(value)
    with file_lock(root, timeout=timeout):
        events = load_events(root)
        previous = {item["event_id"]: item for item in events}
        existing = previous.get(event["event_id"])
        if existing is not None and validate_event(existing) != event:
            raise ValueError(f"Conflicting event_id {event['event_id']}: saved content differs; use a new correction event ID")
        for correction in event.get("corrections", []):
            if "event_id" in correction and correction["event_id"] not in previous:
                raise ValueError(f"Correction target event does not exist: {correction['event_id']}")
        if existing is None:
            event["recorded_at"] = next_recorded_at(events)
            events.append(event)
            events.sort(key=event_order)
        else:
            event = existing
        content = log_content(root, events)
        target = root / "events" / (event["event_id"] + ".json")
        if existing is None:
            # The shared directory lock serializes existence checks and atomic publication.
            atomic_write_json(target, event)
        if validate_event(read_json(target), stored=True) != event:
            raise ValueError(f"Event readback differs from the saved content: {target}")
        write_log(root, content)
    return {"data_dir": str(root), "event_id": event["event_id"], "created": existing is None,
            "readback_verified": True, "event_file": str(target), "growth_log": str(root / "growth-log.md")}


def rebuild_log(root, timeout=10.0):
    # A read-only or repair request on an absent directory must not create a profile.
    if not root.exists():
        return {"data_dir": str(root), "event_count": 0, "rebuilt": False}
    with file_lock(root, timeout=timeout):
        events = load_events(root)
        write_log(root, log_content(root, events))
    return {"data_dir": str(root), "event_count": len(events), "rebuilt": True}


def recent(root, limit=5, case_id=None, context_ref=None):
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be a positive integer")
    events = load_events(root)
    selected = [event for event in events if (case_id is None or event.get("case_id") == case_id)
                and (context_ref is None or event.get("context_ref") == context_ref)][-limit:]
    selected_ids = {event["event_id"] for event in selected}
    related_ids = set(selected_ids)
    # Include original records and later corrections even when their context differs.
    changed = True
    while changed:
        changed = False
        for event in events:
            links = {item["event_id"] for item in event.get("corrections", []) if "event_id" in item}
            links.add(event["event_id"])
            if links & related_ids and not links <= related_ids:
                related_ids.update(links)
                changed = True
    return {"data_dir": str(root), "events": selected,
            "related_events": [event for event in events if event["event_id"] in related_ids - selected_ids],
            "note": "Events and related_events retain occurrence-date order, then write order when recorded_at exists. Legacy same-date events use ID order. Corrections preserve original records; a mentor must reconcile affected snapshots."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir")
    parser.add_argument("--lock-timeout", type=float, default=10.0)
    commands = parser.add_subparsers(dest="command", required=True)
    append = commands.add_parser("append-event")
    append.add_argument("--input", type=Path, required=True)
    read = commands.add_parser("recent")
    read.add_argument("--limit", type=int, default=5)
    read.add_argument("--case-id")
    read.add_argument("--context-ref")
    commands.add_parser("rebuild-log")
    args = parser.parse_args()
    root = data_root(args.data_dir)
    if args.command == "append-event":
        result = append_event(root, read_json(args.input), timeout=args.lock_timeout)
    elif args.command == "recent":
        result = recent(root, args.limit, args.case_id, args.context_ref)
    else:
        result = rebuild_log(root, timeout=args.lock_timeout)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
