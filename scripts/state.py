#!/usr/bin/env python3
"""Manage local PM learning records. Structural checks do not assess competence."""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
_storage_spec = importlib.util.spec_from_file_location("pm_grow_storage", SKILL_DIR / "scripts" / "storage.py")
_storage = importlib.util.module_from_spec(_storage_spec)
_storage_spec.loader.exec_module(_storage)
file_lock = _storage.file_lock
write_json = _storage.atomic_write_json
IDS = {
    "user_problem", "business_value", "solution_design", "data_validation",
    "strategy_prioritization", "delivery_risk", "communication_influence",
    "learning_transfer",
}
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
CUSTOM_ID = re.compile(r"custom\.[a-z0-9]+(?:-[a-z0-9]+)*\Z")


def data_root(value=None):
    return Path(value or os.environ.get("PM_GROW_DATA_DIR") or Path.home() / "pm-grow-data").expanduser().resolve()


def read_json(path):
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read {path}: {exc}") from exc


def init(root, lock_timeout=10.0):
    created, kept = [], []
    with file_lock(root, timeout=lock_timeout):
        for name in ("profile.md", "business-context.md", "growth-log.md", "learning-plan.md", "review-state.json", "abilities.json"):
            target = root / name
            if target.exists():
                kept.append(name)
            else:
                # Exclusive creation also preserves files from non-cooperating initializers.
                try:
                    with target.open("xb") as handle:
                        handle.write((SKILL_DIR / "templates" / name).read_bytes())
                    created.append(name)
                except FileExistsError:
                    kept.append(name)
    return {"data_dir": str(root), "created": created, "preserved": kept}


def validate_ability(ability, path="ability"):
    if not isinstance(ability, dict):
        raise ValueError(f"{path}: ability must be an object")
    identifier = ability.get("id")
    if isinstance(identifier, str) and identifier in IDS:
        raise ValueError(f"{path}: base ability IDs cannot be replaced")
    if not isinstance(identifier, str) or not CUSTOM_ID.fullmatch(identifier):
        raise ValueError(f"{path}: id must be custom.<lowercase-hyphen-slug>")
    for key in ("name", "definition"):
        if not isinstance(ability.get(key), str) or not ability[key].strip():
            raise ValueError(f"{path}: {key} is required")
    behaviors = ability.get("observable_behaviors")
    if not isinstance(behaviors, list) or not behaviors or any(
        not isinstance(item, str) or not item.strip() for item in behaviors
    ):
        raise ValueError(f"{path}: observable_behaviors must contain non-empty text")
    return ability


def load_abilities(root):
    path = root / "abilities.json"
    registry = read_json(path) if path.exists() else {"schema_version": 1, "abilities": []}
    if not isinstance(registry, dict) or registry.get("schema_version") != 1 or not isinstance(registry.get("abilities"), list):
        raise ValueError(f"{path}: invalid abilities registry schema")
    seen = set()
    for ability in registry["abilities"]:
        validate_ability(ability, path)
        if ability["id"] in seen:
            raise ValueError(f"{path}: duplicate ability id {ability['id']}")
        seen.add(ability["id"])
    history = registry.get("history", [])
    if not isinstance(history, list):
        raise ValueError(f"{path}: ability history must be a list")
    for entry in history:
        if not isinstance(entry, dict):
            raise ValueError(f"{path}: ability history entry must be an object")
        previous = validate_ability(entry.get("previous_definition"), path)
        if entry.get("ability_id") != previous["id"]:
            raise ValueError(f"{path}: ability history ID does not match the previous definition")
        stamp = entry.get("replaced_at")
        try:
            if not isinstance(stamp, str):
                raise ValueError
            parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError
        except ValueError as exc:
            raise ValueError(f"{path}: ability history replaced_at must be an ISO 8601 timestamp with timezone") from exc
    return registry


def registered_ability_ids(root):
    return IDS | {ability["id"] for ability in load_abilities(root)["abilities"]}


def register_ability(root, ability, replace=False, lock_timeout=10.0):
    validate_ability(ability)
    with file_lock(root, timeout=lock_timeout):
        registry = load_abilities(root)
        existing = next((item for item in registry["abilities"] if item["id"] == ability["id"]), None)
        if existing is not None:
            if existing == ability:
                status = "unchanged"
            elif not replace:
                raise ValueError("Ability already exists with a different definition; use --replace explicitly.")
            else:
                registry.setdefault("history", []).append({
                    "replaced_at": datetime.now(timezone.utc).isoformat(),
                    "ability_id": ability["id"],
                    "previous_definition": existing,
                })
                registry["abilities"][registry["abilities"].index(existing)] = ability
                status = "replaced"
        else:
            registry["abilities"].append(ability)
            status = "created"
        if status != "unchanged":
            write_json(root / "abilities.json", registry)
        return {"data_dir": str(root), "registered": ability["id"], "status": status}


def validate_case(case, path, ability_ids=None):
    if ability_ids is None:
        case_path = Path(path)
        root = case_path.parent.parent if case_path.parent.name == "cases" else case_path.parent
        ability_ids = registered_ability_ids(root)
    if not isinstance(case, dict) or case.get("schema_version") != 1:
        raise ValueError(f"{path}: expected case schema_version 1")
    identifier = case.get("case_id")
    if not isinstance(identifier, str) or not SLUG.fullmatch(identifier):
        raise ValueError(f"{path}: invalid case_id")
    if not isinstance(case.get("title"), str) or not case["title"].strip():
        raise ValueError(f"{path}: title is required")
    for key, values in (
        ("owner", {"self", "third_party"}),
        ("origin", {"work", "simulation", "legacy"}),
        ("status", {"open", "closed"}),
    ):
        if case.get(key) not in values:
            raise ValueError(f"{path}: invalid {key}")
    abilities = case.get("ability_ids", [])
    if not isinstance(abilities, list) or any(not isinstance(a, str) or a not in ability_ids for a in abilities):
        raise ValueError(f"{path}: unknown ability_ids")
    if "context_ref" in case and not isinstance(case["context_ref"], str):
        raise ValueError(f"{path}: context_ref must be text")
    if "context_snapshot" in case:
        context = case["context_snapshot"]
        if not isinstance(context, dict):
            raise ValueError(f"{path}: context_snapshot must be an object")
        for key in ("project", "role", "help_received"):
            if key in context and not isinstance(context[key], str):
                raise ValueError(f"{path}: context_snapshot {key} must be text")
        if "constraints" in context and (not isinstance(context["constraints"], list) or any(
            not isinstance(item, str) for item in context["constraints"]
        )):
            raise ValueError(f"{path}: context_snapshot constraints must be a list of text")
    attempts = case.get("attempts")
    if not isinstance(attempts, list):
        raise ValueError(f"{path}: attempts must be a list")
    seen = set()
    for attempt in attempts:
        if not isinstance(attempt, dict):
            raise ValueError(f"{path}: attempt must be an object")
        aid = attempt.get("attempt_id")
        if not isinstance(aid, str) or not SLUG.fullmatch(aid) or aid in seen:
            raise ValueError(f"{path}: invalid or duplicate attempt_id")
        seen.add(aid)
        if attempt.get("kind") not in {"independent", "guided", "model_demo", "acknowledgement"}:
            raise ValueError(f"{path}: invalid attempt kind")
        if attempt.get("status") not in {"active", "withdrawn", "unverified"}:
            raise ValueError(f"{path}: invalid attempt status")
        for key in ("user_work", "source"):
            if not isinstance(attempt.get(key), str):
                raise ValueError(f"{path}: attempt {key} must be text")
        stamp = attempt.get("date", "")
        if stamp:
            try:
                date.fromisoformat(stamp)
            except (ValueError, TypeError):
                raise ValueError(f"{path}: invalid attempt date")
        if attempt["status"] == "active" and not stamp:
            raise ValueError(f"{path}: active attempt needs a date")
        observations = attempt.get("observations", [])
        if not isinstance(observations, list):
            raise ValueError(f"{path}: observations must be a list")
        for obs in observations:
            if not isinstance(obs, dict) or not isinstance(obs.get("ability_id"), str) or obs["ability_id"] not in ability_ids:
                raise ValueError(f"{path}: invalid observation ability_id")
            if obs.get("status") not in {"candidate", "supported", "withdrawn"}:
                raise ValueError(f"{path}: invalid observation status")
            if not isinstance(obs.get("text"), str) or not obs["text"].strip():
                raise ValueError(f"{path}: observation text required")
    return case


def load_state(root):
    path = root / "review-state.json"
    value = read_json(path) if path.exists() else {
        "schema_version": 1, "reviewed_case_ids": [], "deferred_fingerprint": None, "history": [],
    }
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("Invalid review-state schema")
    if not isinstance(value.get("reviewed_case_ids"), list) or any(not isinstance(x, str) for x in value["reviewed_case_ids"]):
        raise ValueError("Invalid reviewed_case_ids")
    if not isinstance(value.get("history"), list):
        raise ValueError("Invalid review history")
    if value.get("deferred_fingerprint") is not None and not isinstance(value["deferred_fingerprint"], str):
        raise ValueError("Invalid deferred_fingerprint")
    return value


def eligible_cases(root):
    eligible, ignored, seen = [], [], set()
    ability_ids = registered_ability_ids(root)
    for path in sorted((root / "cases").glob("*.json")):
        case = validate_case(read_json(path), path, ability_ids=ability_ids)
        cid = case["case_id"]
        if cid in seen:
            raise ValueError(f"Duplicate case_id across files: {cid}")
        seen.add(cid)
        usable = [
            a for a in case["attempts"]
            if a["status"] == "active" and a["kind"] in {"independent", "guided"}
            and a["user_work"].strip() and a["source"].strip()
        ]
        if case["owner"] == "self" and case["origin"] in {"work", "simulation"} and case["status"] == "closed" and usable:
            eligible.append({
                "case_id": cid, "title": case["title"], "origin": case["origin"],
                "attempts": usable,
                **{key: case[key] for key in ("context_ref", "context_snapshot") if key in case},
            })
        else:
            ignored.append(cid)
    return eligible, ignored


def review_status(root):
    state = load_state(root)
    eligible, ignored = eligible_cases(root)
    reviewed = set(state["reviewed_case_ids"])
    fresh = [c for c in eligible if c["case_id"] not in reviewed]
    signature = json.dumps(fresh, ensure_ascii=False, sort_keys=True).encode("utf-8")
    fingerprint = hashlib.sha256(signature).hexdigest()
    deferred = state.get("deferred_fingerprint") == fingerprint
    return {
        "data_dir": str(root),
        "eligible_total": len(eligible),
        "new_case_count": len(fresh),
        "new_case_ids": [c["case_id"] for c in fresh],
        "origins": {c["case_id"]: c["origin"] for c in fresh},
        "ignored_case_ids": ignored,
        "fingerprint": fingerprint,
        "deferred_unchanged": deferred,
        "auto_review_due": len(fresh) >= 3 and not deferred,
        "note": "Counts identify a review opportunity, not evidence of competence or growth.",
    }


def mark_reviewed(root, case_ids, lock_timeout=10.0):
    with file_lock(root, timeout=lock_timeout):
        status = review_status(root)
        selected = set(case_ids)
        if not selected or not selected.issubset(set(status["new_case_ids"])):
            raise ValueError("Select only eligible, not-yet-reviewed case IDs after completing the review.")
        state = load_state(root)
        state["reviewed_case_ids"] = sorted(set(state["reviewed_case_ids"]) | selected)
        state["deferred_fingerprint"] = None
        state["history"].append({"date": date.today().isoformat(), "case_ids": sorted(selected)})
        write_json(root / "review-state.json", state)
        return review_status(root)


def defer_review(root, lock_timeout=10.0):
    with file_lock(root, timeout=lock_timeout):
        status = review_status(root)
        state = load_state(root)
        state["deferred_fingerprint"] = status["fingerprint"]
        write_json(root / "review-state.json", state)
        return review_status(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir")
    parser.add_argument("--lock-timeout", type=float, default=10.0, help="Maximum seconds to wait for a data write lock (default: 10)")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "review-status", "defer-review"):
        commands.add_parser(name)
    mark = commands.add_parser("mark-reviewed")
    mark.add_argument("--case-id", action="append", required=True)
    register = commands.add_parser("register-ability")
    register.add_argument("--input", type=Path, required=True, help="JSON file containing one custom ability definition")
    register.add_argument("--replace", action="store_true", help="Explicitly replace a different existing custom definition")
    args = parser.parse_args()
    root = data_root(args.data_dir)
    if args.command == "init":
        result = init(root, lock_timeout=args.lock_timeout)
    elif args.command == "review-status":
        result = review_status(root)
    elif args.command == "defer-review":
        result = defer_review(root, lock_timeout=args.lock_timeout)
    elif args.command == "register-ability":
        result = register_ability(root, read_json(args.input), replace=args.replace, lock_timeout=args.lock_timeout)
    else:
        result = mark_reviewed(root, args.case_id, lock_timeout=args.lock_timeout)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
