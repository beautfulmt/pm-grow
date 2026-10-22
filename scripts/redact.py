"""Remove text that was recorded by mistake, everywhere inside one data directory.

Records are otherwise immutable; this is the one explicit exception. Only text
changes: identifiers (record and problem IDs, file names, dates, enum values)
are never rewritten, and matches inside them are reported instead.

Everything is computed and validated in memory first. Files are written only
after every record, the state file and the handbook still validate, so a
rejected request leaves the directory untouched. Reports and the handbook are
re-rendered from their redacted JSON. The log in redactions.json keeps counts
only, never the original text.
"""
import copy
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re

from storage import file_lock
import handbook
import records as rec
import report

LOG_NAME = "redactions.json"
TEXT_SUFFIXES = {".json", ".md", ".txt", ".html", ".htm"}
MIN_FIND_LENGTH = 2
# Values under these keys are identifiers, dates or enum values. They are never
# rewritten, so links between records, files and reports stay intact.
STRUCTURAL_KEYS = frozenset({
    "schema_version", "record_id", "date", "recorded_at", "kind", "id", "scenario", "status", "ability_id",
    "stage", "from", "to", "evidence", "invalidate", "mode", "basis", "record_ids", "problem_ids", "file",
    "fingerprint", "built_at", "deferred_at", "deferred_on", "until", "checked_on", "updated_on", "url",
    "event_id", "case_id", "methods", "abilities", "on", "since", "start", "end", "dates", "type", "version",
    "selection", "direction", "report_mode", "serves", "legacy_dir", "record_ref", "owner", "origin",
})
STRUCTURAL_SUFFIXES = ("_id", "_ids", "_at", "_on", "_date", "_dates", "fingerprint")
NOTE = ("只改动数据目录里的文本文件。数据目录之外的副本不受影响：云同步的历史版本、已分享或另存的报告与草稿、"
        "版本库历史等需要用户自行处理。记录 ID、问题 ID、文件名、日期等标识不会被改写，命中位置见 identifier_matches。")


class Engine:
    """Single-pass literal replacement, so a replacement is never matched again."""

    def __init__(self, pairs):
        self.pairs = pairs
        self._compiled = {}

    def _pattern(self, mode):
        if mode not in self._compiled:
            forms = {}
            variants = [(find, replace) for find, replace in self.pairs]
            if mode in ("md", "html"):
                variants += [(html.escape(find, quote=False), html.escape(replace, quote=False))
                             for find, replace in self.pairs]
            if mode == "html":
                variants += [(html.escape(find, quote=True), html.escape(replace, quote=True))
                             for find, replace in self.pairs]
            for position, (source, target) in enumerate(variants):
                # Raw forms are inserted first and win over an identical escaped form.
                forms.setdefault(source, (position % len(self.pairs), target))
            ordered = sorted(forms, key=len, reverse=True)
            self._compiled[mode] = (re.compile("|".join(re.escape(item) for item in ordered)), forms)
        return self._compiled[mode]

    def sub(self, text, mode, tally):
        pattern, forms = self._pattern(mode)

        def swap(match):
            index, target = forms[match.group(0)]
            tally[index] += 1
            return target
        return pattern.sub(swap, text)

    def count(self, text, mode):
        tally = [0] * len(self.pairs)
        self.sub(text, mode, tally)
        return tally

    def found(self, text):
        return [index for index, (find, _) in enumerate(self.pairs) if find in text]


def parse_request(value):
    if not isinstance(value, dict):
        raise ValueError('redact 输入必须是 JSON 对象：{"replacements": [{"find": "原文", "replace": "替换文字"}], "label": "可选说明"}')
    unknown = sorted(set(value) - {"replacements", "label"})
    if unknown:
        raise ValueError(f"redact 输入包含不支持的字段：{'、'.join(unknown)}")
    items = value.get("replacements")
    if not isinstance(items, list) or not items:
        raise ValueError("replacements 需要至少一条 {find, replace}")
    pairs = []
    for index, item in enumerate(items):
        label = f"replacements[{index}]"
        if not isinstance(item, dict) or set(item) != {"find", "replace"}:
            raise ValueError(f"{label} 需要且只能包含 find 和 replace")
        find, replace = item["find"], item["replace"]
        if not isinstance(find, str) or len(find.strip()) < MIN_FIND_LENGTH:
            raise ValueError(f"{label}.find 至少要有 {MIN_FIND_LENGTH} 个非空白字符，避免误改大量文字")
        if not isinstance(replace, str):
            raise ValueError(f"{label}.replace 必须是文字，可以是空字符串")
        pairs.append((find, replace))
    finds = [find for find, _ in pairs]
    if len(set(finds)) != len(finds):
        raise ValueError("replacements 中有重复的 find")
    for index, (_, replace) in enumerate(pairs):
        if any(find in replace for find in finds):
            raise ValueError(f"replacements[{index}].replace 不能包含任何要查找的原文，否则重复执行会继续替换")
    label = value.get("label")
    if label is not None:
        if not isinstance(label, str) or not label.strip() or len(label) > 200:
            raise ValueError("label 必须是 200 字以内的非空文字；不需要时请省略")
        if any(find in label for find in finds):
            raise ValueError("label 里不要写要清除的原文")
    return pairs, label


def _structural(key):
    return isinstance(key, str) and (key in STRUCTURAL_KEYS or key.endswith(STRUCTURAL_SUFFIXES))


def _walk(value, key, path, engine, tally, findings):
    """Replace inside string values; identifiers are reported, not changed."""
    if isinstance(value, dict):
        result = {}
        for name, item in value.items():
            child = f"{path}.{name}" if path else str(name)
            for index in engine.found(str(name)):
                findings["matches"].append({"path": child + "（键名）", "replacement": index})
            result[name] = _walk(item, name, child, engine, tally, findings)
        return result
    if isinstance(value, list):
        return [_walk(item, key, f"{path}[{index}]", engine, tally, findings) for index, item in enumerate(value)]
    if not isinstance(value, str):
        return value
    # custom:<名称> is free text that names a personal method, even under an ID-like key.
    if _structural(key) and not value.startswith("custom:"):
        for index in engine.found(value):
            findings["matches"].append({"path": path or "(根)", "replacement": index})
        return value
    replaced = engine.sub(value, "raw", tally)
    if value.strip() and not replaced.strip():
        findings["emptied"].append(path or "(根)")
    return replaced


def _dumps(value):
    # Same bytes as storage.atomic_write_json, so stored records keep their format.
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def _is_record(rel):
    return rel.startswith("records/") and rel.count("/") == 1 and rel.endswith(".json")


def _is_report(value):
    return isinstance(value, dict) and value.get("kind") == "pm-grow-report"


def _is_book(value):
    return (isinstance(value, dict) and value.get("schema_version") == 1
            and isinstance(value.get("topics"), list) and "title" in value)


def _book_valid(value):
    try:
        handbook.validate(copy.deepcopy(value))
    except ValueError:
        return False
    return True


def _files(root):
    found, skipped = [], []
    for directory, folders, names in os.walk(root, followlinks=False):
        # Hidden directories (.git and the like) and hidden files (lock, temporary files) are not data.
        folders[:] = sorted(name for name in folders if not name.startswith("."))
        for name in sorted(names):
            if name.startswith("."):
                continue
            path = Path(directory) / name
            rel = path.relative_to(root).as_posix()
            if rel == LOG_NAME:
                continue
            if path.is_symlink() or path.suffix.lower() not in TEXT_SUFFIXES:
                skipped.append(rel)
                continue
            found.append((rel, path))
    return found, skipped


def _fingerprint(root, paths, new_text):
    """records.v1_fingerprint over the bytes that are about to be written."""
    digest = hashlib.sha256()
    for path in paths:
        rel = path.relative_to(root).as_posix()
        data = new_text[rel].encode("utf-8") if rel in new_text else path.read_bytes()
        digest.update(rel.encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(data).hexdigest().encode("ascii") + b"\n")
    return digest.hexdigest()


def _read_log(root):
    path = root / LOG_NAME
    if not path.exists():
        return {"schema_version": 1, "entries": []}
    log = rec.read_json(path)
    if not isinstance(log, dict) or log.get("schema_version") != 1 or not isinstance(log.get("entries"), list):
        raise ValueError(f"{path} 格式不正确，请先修复（需要 schema_version 1 与 entries 列表）")
    return log


def plan(root, pairs):
    """Compute every change in memory and validate it; nothing is written here."""
    engine = Engine(pairs)
    files, skipped = _files(root)
    texts, matches, warnings = {}, [], []
    for rel, path in files:
        try:
            texts[rel] = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            skipped.append(rel)
    tallies = {rel: [0] * len(pairs) for rel in texts}
    for rel in texts:
        matches += [{"file": rel, "path": "(文件名)", "replacement": index} for index in engine.found(rel)]

    new_text, old_json, new_json, emptied = {}, {}, {}, []
    for rel, text in texts.items():
        if not rel.endswith(".json"):
            continue
        try:
            value = json.loads(text)
        except ValueError:
            if _is_record(rel) or rel == "state.json":
                raise ValueError(f"{rel} 不是有效的 JSON，请先修复再清除敏感信息")
            replaced = engine.sub(text, "md", tallies[rel])
            if replaced != text:
                new_text[rel] = replaced
                warnings.append(f"{rel} 不是有效的 JSON，已按纯文本替换")
            continue
        findings = {"matches": [], "emptied": []}
        redacted = _walk(value, None, "", engine, tallies[rel], findings)
        matches += [{"file": rel, **item} for item in findings["matches"]]
        emptied += [f"{rel}：{item}" for item in findings["emptied"]]
        old_json[rel], new_json[rel] = value, redacted
        if redacted != value:
            new_text[rel] = _dumps(redacted)
    if emptied:
        raise ValueError("替换后这些字段会变成空文字，已中止，没有写入任何文件：" + "；".join(emptied)
                         + "。请改用非空的替换文字")

    # Records and state must still validate exactly as stored data does.
    records = []
    for rel, value in new_json.items():
        if not _is_record(rel):
            continue
        try:
            record = rec.validate_record(value, stored=True)
        except ValueError as exc:
            raise ValueError(f"{rel} 替换后不再是有效记录，已中止：{exc}") from exc
        if record["record_id"] != Path(rel).stem:
            raise ValueError(f"记录文件名与 record_id 不一致：{rel}")
        records.append(record)
    state_value = new_json.get("state.json")
    migration_alias = False
    v1_paths = rec.v1_files(root)
    if isinstance(state_value, dict) and v1_paths:
        changed = [path for path in v1_paths if path.relative_to(root).as_posix() in new_text]
        done = [item.get("v1_fingerprint") for item in state_value.get("migrations", []) if isinstance(item, dict)]
        if changed and rec.v1_fingerprint(root) in done:
            fingerprint = _fingerprint(root, v1_paths, new_text)
            if fingerprint not in done:
                state_value["migrations"].append({
                    "from_version": 1, "v1_fingerprint": fingerprint,
                    "redacted_at": datetime.now(timezone.utc).isoformat(),
                    "note": "清除敏感信息改动了已迁移的 v1 原件；迁移结果已同步替换，无需重新迁移",
                })
                new_text["state.json"] = _dumps(state_value)
                migration_alias = True
    if state_value is not None:
        try:
            state = rec.validate_state(copy.deepcopy(state_value))
        except ValueError as exc:
            raise ValueError(f"state.json 替换后校验失败，已中止：{exc}") from exc
    else:
        state = rec.default_state()
    view = rec.View(records, state)
    for rel, value in new_json.items():
        if _is_book(old_json[rel]) and _book_valid(old_json[rel]) and not _book_valid(value):
            try:
                handbook.validate(copy.deepcopy(value))
            except ValueError as exc:
                raise ValueError(f"{rel} 替换后手册校验失败，已中止：{exc}") from exc

    # HTML: re-render from the redacted JSON next to it; otherwise replace raw and escaped forms.
    rerendered = []
    for rel, text in texts.items():
        if not rel.endswith((".html", ".htm")):
            continue
        hits = engine.count(text, "html")
        companion = rel[:rel.rfind(".")] + ".json"
        old, new = old_json.get(companion), new_json.get(companion)
        rendered = None
        if old is not None and (any(hits) or new != old):
            if _is_report(old):
                try:
                    rendered = report.render(new, state)
                except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
                    warnings.append(f"{rel} 无法按报告 JSON 重新渲染（{type(exc).__name__}），改为字面替换")
            elif _is_book(old) and _book_valid(new):
                rendered = handbook.render(new)
        if rendered is not None:
            if rendered != text:
                new_text[rel] = rendered
                rerendered.append(rel)
                tallies[rel] = [count + extra for count, extra in zip(tallies[rel], hits)]
            continue
        if any(hits):
            new_text[rel] = engine.sub(text, "html", tallies[rel])

    for rel, text in texts.items():
        if rel.endswith((".md", ".txt")):
            replaced = engine.sub(text, "md", tallies[rel])
            if replaced != text:
                new_text[rel] = replaced

    counts = []
    for index in range(len(pairs)):
        files_hit = [rel for rel, tally in tallies.items() if tally[index]]
        counts.append({"index": index, "occurrences": sum(tallies[rel][index] for rel in files_hit),
                       "files": len(files_hit)})
    return {
        "new_text": new_text, "records": records, "state": state, "view": view,
        "state_changed": "state.json" in new_text, "migration_alias": migration_alias,
        "counts": counts, "matches": matches, "rerendered": sorted(rerendered),
        "skipped": sorted(skipped), "warnings": warnings,
    }


def _summary(root, dry_run, result):
    total = sum(item["occurrences"] for item in result["counts"])
    return {
        "data_dir": str(root), "dry_run": dry_run, "files_changed": sorted(result["new_text"]),
        "replacement_counts": result["counts"], "total_occurrences": total,
        "identifier_matches": result["matches"], "rerendered": result["rerendered"],
        "migration_fingerprint_updated": result["migration_alias"],
        "skipped": result["skipped"], "warnings": result["warnings"], "note": NOTE,
    }


def redact(root, request, dry_run=False, timeout=10.0):
    pairs, label = parse_request(request)
    root = Path(root)
    if not root.exists():
        # Neither mode creates a data directory or a lock file for a learner who has none.
        return {"data_dir": str(root), "dry_run": dry_run, "exists": False, "files_changed": [],
                "replacement_counts": [{"index": index, "occurrences": 0, "files": 0} for index in range(len(pairs))],
                "total_occurrences": 0, "identifier_matches": [], "rerendered": [], "note": NOTE}
    if dry_run:
        return _summary(root, True, plan(root, pairs))
    with file_lock(root, timeout=timeout):
        result = plan(root, pairs)
        changed = result["new_text"]
        if not changed:
            return _summary(root, False, result)
        log = _read_log(root)
        if result["state_changed"]:
            # Written first: if anything fails later, migration status is still correct.
            rec.write_state(root, result["state"])
        for rel in sorted(changed):
            if rel == "state.json":
                continue
            path = root / rel
            rec.atomic_write_text(path, changed[rel])
            if _is_record(rel):
                stored = rec.validate_record(rec.read_json(path), stored=True)
                if stored != next(item for item in result["records"] if item["record_id"] == path.stem):
                    raise ValueError(f"记录写入后读回内容不一致：{path}")
        warnings = result["warnings"]
        records_changed = any(_is_record(rel) for rel in changed)
        if (root / "growth-log.md").exists() and (records_changed or "growth-log.md" in changed):
            try:
                rec.write_index(root, result["view"])
            except ValueError as exc:
                warnings.append(f"growth-log.md 已做字面替换，但自动索引没有重建：{exc}")
        total = sum(item["occurrences"] for item in result["counts"])
        log["entries"].append({"at": datetime.now(timezone.utc).isoformat(), "label": label,
                               "files_changed": len(changed), "occurrences": total})
        rec.atomic_write_text(root / LOG_NAME, _dumps(log))
    summary = _summary(root, False, result)
    summary["log"] = str(root / LOG_NAME)
    return summary
