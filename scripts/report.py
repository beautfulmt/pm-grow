"""Growth reports: script-derived facts, mentor-written narrative, offline HTML."""
from datetime import datetime, timezone
from html import escape
from pathlib import Path
import re
import shutil

from storage import atomic_write_json, file_lock
import records as rec

TEMPLATE = rec.SKILL_DIR / "assets" / "report.html"
NARRATIVE_TEXT = ("headline", "learned_summary", "problems_summary", "growth_summary", "next_focus", "message")
REPORT_KEYS = {"schema_version", "kind", "generated_on", "basis", "facts", "narrative"}
LEARNING_KINDS = ("discussion", "exploration", "review")
REVIEW_MODES = {"agent": "经独立复核", "self_check": "主导师自查"}

# Kept as a module attribute for callers of v2.0; the implementation lives in records.
method_label = rec.method_label


def select_basis(view, since=None):
    if since is not None:
        rec.parse_date(since, "--since")
        chosen = [record for record in view.valid if record["date"] >= since]
        selection = "since_date"
    else:
        covered = set()
        for entry in view.state["report"]["history"]:
            covered.update(entry["record_ids"])
        chosen = [record for record in view.valid if record["record_id"] not in covered]
        selection = "new_since_last_report"
    if not chosen:
        raise ValueError("没有可写入报告的新记录" + (f"（{since} 之后）" if since else "（上次报告之后）"))
    return {"record_ids": [record["record_id"] for record in chosen], "since": since, "selection": selection}


def build_facts(view, basis):
    """Summarize the basis records. Everything here is checkable against records/."""
    wanted = basis["record_ids"]
    missing = [identifier for identifier in wanted if identifier not in view.by_id]
    if missing:
        raise ValueError(f"报告依据的记录不存在：{'、'.join(missing)}")
    chosen = [record for record in view.valid if record["record_id"] in set(wanted)]
    if not chosen:
        raise ValueError("报告依据的记录都已作废，请重新运行 report draft")
    chosen_ids = {record["record_id"] for record in chosen}
    state = view.state
    problem_ids = []
    for record in chosen:
        if record.get("problem") and record["problem"]["id"] not in problem_ids:
            problem_ids.append(record["problem"]["id"])

    methods = {}
    for record in chosen:
        for method in record.get("methods", []):
            entry = methods.setdefault(method, {"id": method, "label": method_label(method), "record_ids": [], "dates": []})
            entry["record_ids"].append(record["record_id"])
            if record["date"] not in entry["dates"]:
                entry["dates"].append(record["date"])
    topics = [{"record_id": record["record_id"], "date": record["date"], "kind": record["kind"],
               "summary": record["summary"], "methods": list(record.get("methods", []))}
              for record in chosen if record["kind"] in LEARNING_KINDS or record.get("methods")]

    work, highlights = [], []
    for record in chosen:
        problem = record.get("problem")
        for item in record.get("user_work", []):
            if item["kind"] not in ("independent", "guided"):
                continue
            pid = problem["id"] if problem else None
            group = next((entry for entry in work if entry["problem_id"] == pid), None)
            if group is None:
                title = view.problems[pid]["title"] if pid else "未关联问题"
                group = {"problem_id": pid, "title": title, "items": []}
                work.append(group)
            group["items"].append({"record_id": record["record_id"], "date": record["date"], "kind": item["kind"],
                                   "kind_name": rec.WORK_KINDS[item["kind"]], "content": item["content"],
                                   "source": item["source"]})
            highlights.append({"record_id": record["record_id"], "date": record["date"], "problem_id": pid,
                               "problem_title": group["title"], "kind": item["kind"],
                               "kind_name": rec.WORK_KINDS[item["kind"]], "quote": item["content"],
                               "source": item["source"]})

    problems = []
    for pid in problem_ids:
        merged = view.problems[pid]
        related = [record for record in chosen if record.get("problem", {}).get("id") == pid]
        counts = {}
        for record in related:
            for item in record.get("user_work", []):
                counts[item["kind"]] = counts.get(item["kind"], 0) + 1
        approach_methods = []
        for record in related:
            for method in record.get("methods", []):
                if method not in approach_methods:
                    approach_methods.append(method)
        entry = {"problem_id": pid, "title": merged["title"], "status": merged["status"],
                 "status_name": rec.PROBLEM_STATUSES[merged["status"]],
                 "approach": {"methods": [{"id": method, "label": method_label(method)} for method in approach_methods],
                              "assistance": [record["assistance"] for record in related if record.get("assistance")],
                              "user_work": {kind: counts[kind] for kind in rec.WORK_KINDS if kind in counts}},
                 "record_ids": [record["record_id"] for record in related],
                 "first_date": min(record["date"] for record in related),
                 "last_date": max(record["date"] for record in related)}
        for key in ("scenario", "outcome"):
            if merged[key]:
                entry[key] = merged[key]
        problems.append(entry)

    changes = [rec.change_summary(view, item) for item in view.applied if item["record_id"] in chosen_ids]
    practicing = []
    for record in chosen:
        for item in record.get("observations", []):
            if item["status"] != "withdrawn":
                practicing.append({"record_id": record["record_id"], "date": record["date"],
                                   "ability_id": item["ability_id"], "name": rec.ability_label(state, item["ability_id"]),
                                   "text": item["text"], "status": item["status"]})

    pending = {item["problem_id"]: item for item in view.pending_check_backs(rec.date.max)}
    open_items = []
    for problem in view.open_problems():
        item = {"problem_id": problem["id"], "title": problem["title"], "status": problem["status"],
                "status_name": problem["status_name"], "last_date": problem["last_date"]}
        for key in ("next_step", "unresolved"):
            if key in problem:
                item[key] = problem[key]
        if problem["id"] in pending:
            check = pending[problem["id"]]
            item["check_back"] = {key: check[key] for key in ("question", "on", "when") if key in check}
        open_items.append(item)

    stage = None
    if view.stage:
        stage = {"stage": view.stage["stage"], "name": view.stage["name"], "reason": view.stage["reason"],
                 "date": view.stage["date"],
                 "changed_in_period": any("stage_update" in record for record in chosen)}
    dates = [record["date"] for record in chosen]
    return {
        "period": {"start": basis["since"] or min(dates), "end": max(dates),
                   "record_count": len(chosen), "problem_count": len(problem_ids)},
        "stage": stage,
        "learned": {"methods": list(methods.values()), "topics": topics},
        "work": work,
        "problems": problems,
        "performance_highlights": highlights,
        "ability_changes": changes,
        "ability_overview": ability_overview(view, chosen),
        "focus": focus_progress(view, chosen, changes),
        "milestones": [{"record_id": record["record_id"], "date": record["date"], "text": record["milestone"]}
                       for record in chosen if record.get("milestone")],
        "still_practicing": practicing,
        "open_items": open_items,
        "evidence": [{"record_id": record["record_id"], "date": record["date"], "kind": record["kind"],
                      "summary": record["summary"], "source": record["source"],
                      **({"problem_id": record["problem"]["id"]} if record.get("problem") else {})}
                     for record in chosen],
    }


def ability_overview(view, chosen):
    """One row per ability that is observed or has a level: current-stage level plus the prior-stage level."""
    stage = view.stage["stage"] if view.stage else None
    observed = {item["ability_id"] for record in view.written for item in record.get("observations", [])
                if item["status"] != "withdrawn"}
    rows = []
    for ability_id in rec.known_ability_ids(view.state):
        level = view.level(ability_id, stage) if stage else None
        prior = view.prior_level(ability_id, stage)
        if ability_id not in observed and not prior and level in (None, "unobserved"):
            continue
        row = {"ability_id": ability_id, "name": rec.ability_label(view.state, ability_id),
               "stage": stage, "stage_name": rec.STAGES[stage] if stage else None,
               "level": level, "level_name": rec.LEVEL_NAMES[level] if level else None,
               "observations_in_period": sum(1 for record in chosen if rec._observes(record, ability_id))}
        if prior:
            row["prior"] = prior
        rows.append(row)
    return rows


def focus_progress(view, chosen, changes):
    """The current focus abilities and what happened to them in this period since the focus was set."""
    current = view.focus_status()
    if not current:
        return None
    since_focus = {record["record_id"] for record in view.written[view.focus["position"]:]}
    in_scope = [record for record in chosen if record["record_id"] in since_focus]
    abilities = []
    for item in current["abilities"]:
        practiced = [record for record in in_scope if rec._observes(record, item["ability_id"])
                     and rec._work_kinds(record) & {"independent", "guided"}]
        abilities.append({**item, "records_in_period": len(practiced),
                          "changes_in_period": [{"date": change["date"], "stage_name": change["stage_name"],
                                                 "from_name": change["from_name"], "to_name": change["to_name"]}
                                                for change in changes if change["ability_id"] == item["ability_id"]
                                                and change["record_id"] in since_focus]})
    return {"since": current["since"], "reason": current["reason"], "record_id": current["record_id"],
            "abilities": abilities}


def empty_narrative(facts):
    gaps = []
    for item in facts["still_practicing"]:
        if item["ability_id"] not in [gap["ability_id"] for gap in gaps]:
            gaps.append({"ability_id": item["ability_id"], "text": "", "next_practice": ""})
    return {"headline": "", "learned_summary": "", "problems_summary": "", "growth_summary": "",
            "gaps": gaps,
            "next_focus": "", "message": ""}


def load_view(root):
    root = Path(root)
    if not root.exists():
        return rec.View([], rec.default_state())
    return rec.View(rec.load_records(root), rec.load_state(root))


def draft(root, since=None, today=None):
    view = load_view(root)
    basis = select_basis(view, since)
    facts = build_facts(view, basis)
    return {
        "schema_version": rec.SCHEMA_VERSION,
        "kind": "pm-grow-report",
        "generated_on": rec.today_value(today).isoformat(),
        "basis": basis,
        "facts": facts,
        "narrative": empty_narrative(facts),
    }


def validate_narrative(narrative, state):
    if not isinstance(narrative, dict):
        raise ValueError("narrative 必须是对象")
    unknown = sorted(set(narrative) - set(NARRATIVE_TEXT) - {"gaps"})
    if unknown:
        raise ValueError(f"narrative 包含不支持的字段：{'、'.join(unknown)}")
    missing = [key for key in NARRATIVE_TEXT
               if not isinstance(narrative.get(key), str) or not narrative[key].strip()]
    gaps = narrative.get("gaps")
    if not isinstance(gaps, list):
        missing.append("gaps（数组；缺少可靠依据时可以为空）")
        gaps = []
    known = set(rec.known_ability_ids(state))
    for index, gap in enumerate(gaps):
        if not isinstance(gap, dict) or set(gap) - {"ability_id", "text", "next_practice"}:
            raise ValueError(f"narrative.gaps[{index}] 只能包含 ability_id、text、next_practice")
        for key in ("ability_id", "text", "next_practice"):
            if not isinstance(gap.get(key), str) or not gap[key].strip():
                missing.append(f"gaps[{index}].{key}")
        if isinstance(gap.get("ability_id"), str) and gap["ability_id"].strip() and gap["ability_id"] not in known:
            raise ValueError(f"narrative.gaps[{index}].ability_id 不是已知能力：{gap['ability_id']}")
    if missing:
        raise ValueError("narrative 还有未填写的字段：" + "、".join(missing))
    return narrative


def validate_report(report, view):
    if not isinstance(report, dict) or report.get("schema_version") != rec.SCHEMA_VERSION or report.get("kind") != "pm-grow-report":
        raise ValueError("报告输入必须来自 report draft（schema_version 2、kind=pm-grow-report）")
    unknown = sorted(set(report) - REPORT_KEYS)
    if unknown:
        raise ValueError(f"报告输入包含不支持的字段：{'、'.join(unknown)}")
    basis = report.get("basis")
    if (not isinstance(basis, dict) or set(basis) != {"record_ids", "since", "selection"}
            or not isinstance(basis["record_ids"], list) or not basis["record_ids"]
            or any(not isinstance(item, str) for item in basis["record_ids"])):
        raise ValueError("basis 格式不正确，请使用 report draft 生成的原样内容")
    if basis["since"] is not None:
        rec.parse_date(basis["since"], "basis.since")
    validate_narrative(report.get("narrative"), view.state)
    facts = build_facts(view, basis)
    if report.get("facts") != facts:
        raise ValueError("facts 与当前记录不一致：facts 由脚本生成，不能手改；"
                         "如果 draft 之后记录有变化，请重新运行 report draft 并把 narrative 填回去")
    return facts


# ---------------------------------------------------------------- HTML

def _e(value):
    return escape(str(value), quote=True)


def _paragraphs(text, css="lead"):
    return "".join(f'<p class="{css}">{_e(part)}</p>' for part in text.split("\n\n") if part.strip())


def _status_badge(status):
    return f'<span class="badge status-{_e(status)}">{_e(rec.PROBLEM_STATUSES[status])}</span>'


def _section(identifier, number, title, body):
    return (f'<section id="{identifier}" class="block" aria-labelledby="{identifier}-title">'
            f'<h2 id="{identifier}-title"><span class="num">{number}</span>{_e(title)}</h2>{body}</section>')


def render_learned(facts, narrative):
    parts = [_paragraphs(narrative["learned_summary"])]
    methods = facts["learned"]["methods"]
    if methods:
        parts.append("<h3>用到的方法</h3><ul class=\"chips\">" + "".join(
            f'<li>{_e(item["label"])}<small>{len(item["record_ids"])} 次</small></li>' for item in methods) + "</ul>")
    topics = facts["learned"]["topics"]
    if topics:
        parts.append("<h3>学习与讨论</h3><ol class=\"timeline\">" + "".join(
            f'<li><time>{_e(item["date"])}</time><span>{_e(item["summary"])}</span></li>' for item in topics) + "</ol>")
    parts.append("<h3>你做了什么</h3>")
    if facts["work"]:
        for group in facts["work"]:
            parts.append(f'<div class="work"><h4>{_e(group["title"])}</h4><ul>' + "".join(
                f'<li><span class="kind kind-{_e(item["kind"])}">{_e(item["kind_name"])}</span>'
                f'<span class="text">{_e(item["content"])}</span>'
                f'<small>{_e(item["date"])} · {_e(item["source"])}</small></li>' for item in group["items"]) + "</ul></div>")
    else:
        parts.append('<p class="empty">本期没有记录到你本人的独立或引导下产出。</p>')
    return _section("learned", "一", "最近学了什么、做了什么", "".join(parts))


def render_problems(facts, narrative):
    parts = [_paragraphs(narrative["problems_summary"])]
    parts.append('<p class="legend" aria-label="状态说明">' + "".join(
        _status_badge(status) for status in rec.PROBLEM_STATUSES) + "</p>")
    for item in facts["problems"]:
        approach = item["approach"]
        rows = []
        if item.get("scenario"):
            rows.append(("场景", _e(item["scenario"])))
        ways = []
        if approach["methods"]:
            ways.append("方法：" + "、".join(_e(method["label"]) for method in approach["methods"]))
        if approach["user_work"]:
            ways.append("你的产出：" + "，".join(f"{_e(rec.WORK_KINDS[kind])} {count}" for kind, count in approach["user_work"].items()))
        ways += ["获得帮助：" + _e(text) for text in approach["assistance"]]
        rows.append(("处理方式", "<br>".join(ways) if ways else "以讨论为主"))
        rows.append(("结果", _e(item["outcome"]) if item.get("outcome") else "尚无结果"))
        rows.append(("时间", f'{_e(item["first_date"])} 至 {_e(item["last_date"])}'))
        parts.append(f'<article class="problem status-{_e(item["status"])}"><header><h3>{_e(item["title"])}</h3>'
                     f'{_status_badge(item["status"])}</header><dl>'
                     + "".join(f"<dt>{label}</dt><dd>{value}</dd>" for label, value in rows) + "</dl></article>")
    if not facts["problems"]:
        parts.append('<p class="empty">本期记录没有关联具体问题。</p>')
    return _section("problems", "二", "遇到的问题、怎么处理、是否解决", "".join(parts))


def _review_note(item):
    review = item.get("review")
    if not isinstance(review, dict) or review.get("mode") not in REVIEW_MODES:
        return ""
    return f'<span class="review">{_e(REVIEW_MODES[review["mode"]])}</span>'


def render_focus(focus):
    if not focus:
        return ""
    rows = []
    for item in focus.get("abilities", []):
        step = f'当前「{_e(item["level_name"])}」'
        if item.get("next_level_name"):
            step += f'，下一级「{_e(item["next_level_name"])}」'
        prior = item.get("prior")
        if prior:
            step += f'（此前{_e(prior["stage_name"])}阶段已达「{_e(prior["level_name"])}」）'
        changes = "；".join(
            f'{_e(change["from_name"])} → {_e(change["to_name"])}'
            f'（{_e(change.get("stage_name", ""))}阶段，{_e(change["date"])}）'
            for change in item.get("changes_in_period", []))
        rows.append(f'<li><strong>{_e(item["name"])}</strong>：{step}；设定焦点以来本期练到 '
                    f'{_e(item.get("records_in_period", 0))} 次'
                    + (f'<small>本期变化：{changes}</small>' if changes else "") + "</li>")
    return (f'<div class="focus"><h3>本期焦点</h3><p class="note">自 {_e(focus["since"])} 起：{_e(focus["reason"])}</p>'
            f'<ul>{"".join(rows)}</ul></div>')


def render_overview(rows):
    if not rows:
        return ""
    stage_name = rows[0].get("stage_name")
    header = f"当前阶段（{_e(stage_name)}）" if stage_name else "当前阶段（尚未定位）"
    body = []
    for row in rows:
        prior = row.get("prior")
        earlier = (f'{_e(prior["stage_name"])}：{_e(prior["level_name"])}<small>{_e(prior["date"])}</small>'
                   if prior else "—")
        body.append(f'<tr><th scope="row">{_e(row["name"])}</th><td>{_e(row.get("level_name") or "—")}</td>'
                    f"<td>{earlier}</td></tr>")
    return ('<h3>能力全景</h3><p class="note">各阶段分别追踪；换阶段后，此前阶段已达到的程度保留在右栏。</p>'
            f'<table class="overview"><thead><tr><th scope="col">能力</th><th scope="col">{header}</th>'
            f'<th scope="col">此前阶段</th></tr></thead><tbody>{"".join(body)}</tbody></table>')


def render_growth(facts, narrative, state):
    parts = [_paragraphs(narrative["growth_summary"])]
    # Reports built by v2.0 lack focus and ability_overview; redaction re-renders them, so read with .get.
    parts.append(render_focus(facts.get("focus")))
    if facts["milestones"]:
        parts.append('<ul class="milestones" aria-label="里程碑">' + "".join(
            f'<li><time>{_e(item["date"])}</time>{_e(item["text"])}</li>' for item in facts["milestones"]) + "</ul>")
    parts.append('<div class="tier"><h3>【本次表现】</h3>')
    if facts["performance_highlights"]:
        parts.append("".join(
            f'<figure class="quote"><blockquote>{_e(item["quote"])}</blockquote>'
            f'<figcaption>{_e(item["date"])} · {_e(item["problem_title"])} · {_e(item["kind_name"])} · 来源：{_e(item["source"])}</figcaption></figure>'
            for item in facts["performance_highlights"]))
    else:
        parts.append('<p class="empty">本期没有可引用的本人产出。</p>')
    parts.append('</div><div class="tier"><h3>【能力变化】</h3>')
    if facts["ability_changes"]:
        parts.append('<ul class="changes">' + "".join(
            f'<li class="change-{_e(item["direction"])}"><strong>{_e(item["name"])}</strong>：'
            f'{_e(item["from_name"])} → {_e(item["to_name"])}'
            f'<span class="stage">（{_e(item["stage_name"])}阶段）</span>，依据：'
            f'{_e("、".join(item["evidence_dates"]) or "更正记录 " + item["record_id"])}{_review_note(item)}'
            f'<small>{_e(item["reason"])}</small></li>' for item in facts["ability_changes"]) + "</ul>")
    else:
        parts.append('<p class="empty">本期没有记录能力程度变化；成长以证据为准，不按次数推断。</p>')
    parts.append('</div><div class="tier"><h3>【仍在练】</h3><ul class="gaps">')
    parts.append("".join(
        f'<li><strong>{_e(rec.ability_label(state, gap["ability_id"]))}</strong>：{_e(gap["text"])}'
        f'<span class="practice">下一次练：{_e(gap["next_practice"])}</span></li>' for gap in narrative["gaps"]))
    if not narrative["gaps"]:
        parts.append('<li class="empty">本期没有足够依据确定具体欠缺，留待实际尝试后观察。</li>')
    parts.append("</ul>")
    if facts["still_practicing"]:
        parts.append('<h4>相关观察</h4><ul class="observations">' + "".join(
            f'<li><span>{_e(item["name"])}</span>{_e(item["text"])}<small>{_e(item["date"])}</small></li>'
            for item in facts["still_practicing"]) + "</ul>")
    parts.append("</div>")
    parts.append(render_overview(facts.get("ability_overview") or []))
    return _section("growth", "三", "成长与欠缺", "".join(parts))


def render_next(facts, narrative):
    parts = [_paragraphs(narrative["next_focus"])]
    if facts["open_items"]:
        parts.append("<h3>还在进行的问题</h3><ul class=\"open-items\">")
        for item in facts["open_items"]:
            extra = []
            if item.get("next_step"):
                extra.append("下一步：" + item["next_step"])
            if item.get("check_back"):
                check = item["check_back"]
                when = "，".join(value for value in (check.get("on"), check.get("when")) if value)
                extra.append(f"回访（{when}）：{check['question']}")
            parts.append(f'<li>{_status_badge(item["status"])}<strong>{_e(item["title"])}</strong>'
                         + "".join(f"<small>{_e(text)}</small>" for text in extra) + "</li>")
        parts.append("</ul>")
    parts.append(f'<div class="message"><h3>导师的话</h3>{_paragraphs(narrative["message"], "")}</div>')
    return _section("next", "四", "下一阶段重点", "".join(parts))


def render_evidence(facts):
    rows = "".join(
        f'<li><code>{_e(item["record_id"])}</code><time>{_e(item["date"])}</time>'
        f'<span class="kind">{_e(item["kind"])}</span><span class="text">{_e(item["summary"])}</span>'
        f'<small>来源：{_e(item["source"])}</small></li>' for item in facts["evidence"])
    body = ('<p class="note">以下记录是本报告的全部依据，原文保存在数据目录 records/ 下。'
            '示范与认同不计为能力证据；作废的记录不出现在这里。</p>'
            f'<ol class="evidence">{rows}</ol>')
    return _section("evidence", "附", "证据附录", body)


def render(report, state):
    facts, narrative = report["facts"], report["narrative"]
    period = facts["period"]
    stage = facts["stage"]
    stats = [("记录", period["record_count"]), ("问题", period["problem_count"]),
             ("本人产出", len(facts["performance_highlights"])), ("能力变化", len(facts["ability_changes"]))]
    values = {
        "TITLE": _e(f"PM 成长报告 · {period['start']} 至 {period['end']}"),
        "PERIOD": _e(f"{period['start']} 至 {period['end']}"),
        "STAGE": _e(f"当前阶段：{stage['name']}" if stage else "当前阶段：尚未定位"),
        "GENERATED": _e(report["generated_on"]),
        "HEADLINE": _e(narrative["headline"]),
        "STATS": "".join(f"<li><strong>{value}</strong><span>{label}</span></li>" for label, value in stats),
        "LEARNED": render_learned(facts, narrative),
        "PROBLEMS": render_problems(facts, narrative),
        "GROWTH": render_growth(facts, narrative, state),
        "NEXT": render_next(facts, narrative),
        "EVIDENCE": render_evidence(facts),
    }
    # One pass, so placeholder-like text inside escaped content is never reprocessed.
    return re.sub(r"\{\{([A-Z]+)\}\}", lambda match: values[match.group(1)], TEMPLATE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- commands

def _backup(path):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = path.with_name(f"{path.stem}.previous-{stamp}{path.suffix}")
    shutil.copy2(path, backup)
    return backup


def build(root, report, output=None, replace=False, today=None, timeout=10.0):
    root = Path(root)
    today = rec.today_value(today)
    with file_lock(root, timeout=timeout):
        view = rec.View(rec.load_records(root), rec.load_state(root))
        validate_report(report, view)
        html = render(report, view.state)
        target = Path(output) if output else root / "reports" / f"{today.isoformat()}.html"
        target = target.expanduser().resolve()
        companion = target.with_suffix(".json")
        existing = [path for path in (target, companion) if path.exists()]
        if existing and not replace:
            raise ValueError(f"{existing[0]} 已存在；确认要替换时加 --replace（旧文件会备份）")
        backups = [str(_backup(path)) for path in existing]
        atomic_write_json(companion, report)
        rec.atomic_write_text(target, html)
        state = view.state
        try:
            location = target.relative_to(root).as_posix()
        except ValueError:
            location = str(target)
        problem_ids = [item["problem_id"] for item in report["facts"]["problems"]]
        state["report"]["history"].append({
            "source": "v2", "date": today.isoformat(), "built_at": datetime.now(timezone.utc).isoformat(),
            "file": location, "record_ids": list(report["basis"]["record_ids"]), "problem_ids": problem_ids,
        })
        state["report"]["deferred"] = None
        rec.write_state(root, state)
    return {"data_dir": str(root), "output": str(target), "json": str(companion), "backups": backups,
            "record_count": len(report["basis"]["record_ids"]), "cursor_updated": True}


def defer(root, today=None, until=None, timeout=10.0):
    """Restart the proposal clock: only evidence written after now counts toward the next proposal.

    `until` (YYYY-MM-DD, later than today) also blocks proposals before that date.
    """
    root = Path(root)
    today = rec.today_value(today)
    if until is not None and rec.parse_date(until, "--until") <= today:
        raise ValueError("--until 必须晚于今天；只是这次不想要报告时直接运行 report defer")
    with file_lock(root, timeout=timeout):
        state = rec.load_state(root)
        records = rec.load_records(root)
        # The records' own write clock marks the deferral, so later writes always count as new.
        latest = max((record["recorded_at"] for record in records), key=rec._utc, default=None)
        state["report"]["deferred"] = {"deferred_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                                       "deferred_on": today.isoformat(), "until": until,
                                       "after_recorded_at": latest}
        rec.write_state(root, state)
        cursor = rec.report_cursor(rec.View(records, state), today)
    note = ("暂缓后只看之后的新记录：再出现 3 个含用户尝试的问题、新的关键节点，或暂缓满 14 天且有新记录，才会再提议。"
            "用户主动要求时随时可以生成。")
    if until:
        note = f"{until} 之前不再提议；到那天起，尚未写进报告的记录会再次提议。" + note
    return {"data_dir": str(root), "deferred": True, "deferred_on": today.isoformat(), "deferred_until": until,
            "report": rec._compact_cursor(cursor)[0], "note": note}


def write_draft(report, output):
    target = Path(output).expanduser().resolve()
    if target.exists():
        raise ValueError(f"{target} 已存在，请换一个路径")
    atomic_write_json(target, report)
    return str(target)
