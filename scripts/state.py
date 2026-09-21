#!/usr/bin/env python3
"""Manage local PM learning records. Structural checks do not assess competence."""
import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import date
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
IDS = {
    "user_problem", "business_value", "solution_design", "data_validation",
    "strategy_prioritization", "delivery_risk", "communication_influence",
    "learning_transfer",
}
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


def data_root(value=None):
    return Path(value or os.environ.get("PM_GROW_DATA_DIR") or Path.home() / "pm-grow-data").expanduser().resolve()


def read_json(path):
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read {path}: {exc}") from exc


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=".pm-grow-", delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def init(root):
    root.mkdir(parents=True, exist_ok=True)
    created, kept = [], []
    for name in ("profile.md", "business-context.md", "growth-log.md", "learning-plan.md", "review-state.json"):
        target = root / name
        if target.exists():
            kept.append(name)
        else:
            # Exclusive creation keeps existing user files even if another host initializes.
            try:
                with target.open("xb") as handle:
                    handle.write((SKILL_DIR / "templates" / name).read_bytes())
                created.append(name)
            except FileExistsError:
                kept.append(name)
    return {"data_dir": str(root), "created": created, "preserved": kept}


def validate_case(case, path):
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
    if not isinstance(abilities, list) or any(not isinstance(a, str) or a not in IDS for a in abilities):
        raise ValueError(f"{path}: unknown ability_ids")
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
            if not isinstance(obs, dict) or obs.get("ability_id") not in IDS:
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
    for path in sorted((root / "cases").glob("*.json")):
        case = validate_case(read_json(path), path)
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


def mark_reviewed(root, case_ids):
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


def defer_review(root):
    status = review_status(root)
    state = load_state(root)
    state["deferred_fingerprint"] = status["fingerprint"]
    write_json(root / "review-state.json", state)
    return review_status(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "review-status", "defer-review"):
        commands.add_parser(name)
    mark = commands.add_parser("mark-reviewed")
    mark.add_argument("--case-id", action="append", required=True)
    args = parser.parse_args()
    root = data_root(args.data_dir)
    if args.command == "init":
        result = init(root)
    elif args.command == "review-status":
        result = review_status(root)
    elif args.command == "defer-review":
        result = defer_review(root)
    else:
        result = mark_reviewed(root, args.case_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
