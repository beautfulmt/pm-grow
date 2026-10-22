"""Maintain an approved topic collection and render it into a standalone offline HTML handbook."""
from copy import deepcopy
from datetime import date, datetime
from html import escape
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import urlsplit

from records import SKILL_DIR, read_json, today_value
from storage import atomic_write_json, file_lock

TEMPLATE = SKILL_DIR / "assets" / "handbook.html"
BOOK_TEMPLATE = SKILL_DIR / "templates" / "handbook.json"
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
PRINCIPLES = {
    "goal": "目标", "facts": "事实", "constraints": "约束",
    "mechanism": "机制", "options": "选择", "validation": "验证",
}
BODY_TEXT = ("problem", "context", "judgment", "case", "template", "counterexample", "next_action")
BODY_LISTS = ("steps", "boundaries", "pitfalls")


def text_field(obj, key, required=True):
    value = obj.get(key, "")
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError(f"{key}: expected non-empty text" if required else f"{key}: expected text")
    return value


def date_field(obj, key):
    value = text_field(obj, key)
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError()
    except ValueError:
        raise ValueError(f"{key}: expected YYYY-MM-DD")
    return value


def text_list(obj, key, required=False):
    value = obj.get(key, [])
    if not isinstance(value, list) or (required and not value):
        raise ValueError(f"{key}: expected a {'non-empty ' if required else ''}list")
    if any(not isinstance(v, str) or not v.strip() for v in value):
        raise ValueError(f"{key}: every item must be non-empty text")
    return value


def validate(book):
    if not isinstance(book, dict) or book.get("schema_version") != 1:
        raise ValueError("Expected handbook schema_version 1")
    text_field(book, "title")
    date_field(book, "updated_on")
    if not isinstance(book.get("topics"), list) or not book["topics"]:
        raise ValueError("At least one approved topic is required")
    ids = set()
    for topic in book["topics"]:
        if not isinstance(topic, dict):
            raise ValueError("Topic must be an object")
        identifier = text_field(topic, "id")
        if not SLUG.fullmatch(identifier) or identifier in ids:
            raise ValueError("Topic IDs must be unique lowercase slugs")
        ids.add(identifier)
        text_field(topic, "title")
        date_field(topic, "updated_on")
        for key in BODY_TEXT:
            text_field(topic, key, required=False)
        for key in (*BODY_LISTS, "tags"):
            text_list(topic, key)
        principles = topic.get("first_principles", {})
        if not isinstance(principles, dict) or any(k not in PRINCIPLES for k in principles):
            raise ValueError("Unknown first_principles field")
        for key in principles:
            text_field(principles, key)
        sections = topic.get("sections", [])
        if not isinstance(sections, list):
            raise ValueError("sections: expected a list")
        for section in sections:
            if not isinstance(section, dict):
                raise ValueError("Section must be an object")
            text_field(section, "heading")
            text_field(section, "content")
        has_body = (
            any(topic.get(key, "").strip() for key in BODY_TEXT)
            or any(topic.get(key, []) for key in BODY_LISTS)
            or bool(principles) or bool(sections)
        )
        if not has_body:
            raise ValueError("Topic needs substantive body content in legacy fields or sections")
        sources = topic.get("sources")
        if not isinstance(sources, list) or not sources:
            raise ValueError("Provide a real source or an honest conversation locator")
        for source in sources:
            if not isinstance(source, dict):
                raise ValueError("Source must be an object")
            text_field(source, "title")
            date_field(source, "checked_on")
            url = text_field(source, "url", required=False)
            locator = text_field(source, "locator", required=False)
            text_field(source, "scope", required=False)
            if not url and not locator.strip():
                raise ValueError("Source needs url or locator")
            if url:
                try:
                    parsed = urlsplit(url)
                    valid = parsed.scheme in {"http", "https"} and bool(parsed.hostname)
                except ValueError:
                    valid = False
                if not valid or any(ord(c) < 32 for c in url):
                    raise ValueError("Only valid http/https source URLs are supported")
    return book


def paragraph(title, value, css=""):
    if not value.strip():
        return ""
    return f'<section class="{css}"><h3>{escape(title)}</h3><p>{escape(value)}</p></section>'


def list_section(title, items, ordered=False):
    if not items:
        return ""
    tag = "ol" if ordered else "ul"
    return f"<section><h3>{escape(title)}</h3><{tag}>" + "".join(f"<li>{escape(item)}</li>" for item in items) + f"</{tag}></section>"


def render_topic(topic):
    tid = escape(topic["id"], quote=True)
    parts = [
        f'<article id="topic-{tid}" data-topic="{tid}">',
        f'<h2>{escape(topic["title"])}</h2>',
        f'<p class="meta">更新于 {escape(topic["updated_on"])}</p>',
    ]
    tags = topic.get("tags", [])
    if tags:
        parts.append('<div class="tags">' + "".join(f'<span class="tag">{escape(t)}</span>' for t in tags) + "</div>")
    problem, context = topic.get("problem", ""), topic.get("context", "")
    background = "\n".join(value for value in (problem, context) if value.strip())
    background_title = "问题与背景" if problem.strip() and context.strip() else ("问题" if problem.strip() else "背景")
    parts.extend([
        paragraph(background_title, background),
        paragraph("关键判断", topic.get("judgment", ""), "judgment"),
    ])
    principles = topic.get("first_principles", {})
    if principles:
        parts.append('<section><h3>关键推导</h3><div class="principles">')
        for key, label in PRINCIPLES.items():
            if key in principles:
                parts.append(f'<div class="principle"><strong>{label}</strong><p>{escape(principles[key])}</p></div>')
        parts.append("</div></section>")
    parts.extend([
        list_section("解题步骤", topic.get("steps", []), ordered=True),
        list_section("适用边界", topic.get("boundaries", [])),
        paragraph("案例", topic.get("case", "")),
        paragraph("反例与失效条件", topic.get("counterexample", "")),
    ])
    if topic.get("template", "").strip():
        parts.append(f'<section><h3>可复用模板</h3><pre>{escape(topic["template"])}</pre></section>')
    parts.extend([
        list_section("常见误用", topic.get("pitfalls", [])),
        paragraph("下一步", topic.get("next_action", "")),
    ])
    parts.extend(paragraph(section["heading"], section["content"]) for section in topic.get("sections", []))
    parts.append('<section class="sources"><h3>来源与核验范围</h3><ul>')
    for source in topic["sources"]:
        title = escape(source["title"])
        url = source.get("url", "")
        link = f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{title}</a>' if url else title
        detail = "核对于 " + source["checked_on"]
        if source.get("locator"):
            detail += " · " + source["locator"]
        if source.get("scope"):
            detail += " · " + source["scope"]
        printed_url = f'<small class="source-url">{escape(url)}</small>' if url else ""
        parts.append(f"<li>{link}<small>{escape(detail)}</small>{printed_url}</li>")
    parts.append("</ul></section></article>")
    return "\n".join(parts)


def render(book):
    validate(book)
    toc = "".join(
        f'<li data-topic="{escape(t["id"], quote=True)}"><a href="#topic-{escape(t["id"], quote=True)}">{escape(t["title"])}</a></li>'
        for t in book["topics"]
    )
    values = {
        "TITLE": escape(book["title"]),
        "UPDATED": escape(book["updated_on"]),
        "COUNT": str(len(book["topics"])),
        "TOC": toc,
        "ARTICLES": "\n".join(render_topic(t) for t in book["topics"]),
    }
    return re.sub(r"\{\{([A-Z]+)\}\}", lambda m: values[m.group(1)], TEMPLATE.read_text(encoding="utf-8"))


def build(input_path, output_path, replace=False):
    input_path, output_path = Path(input_path), Path(output_path)
    if input_path.resolve() == output_path.resolve():
        raise ValueError("Input and output paths must differ")
    book = read_json(input_path)
    result = render(book)
    if output_path.exists() and not replace:
        raise ValueError("Output exists; use --replace only for an approved update")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if output_path.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup = output_path.with_name(f"{output_path.stem}.previous-{stamp}{output_path.suffix}")
        shutil.copy2(output_path, backup)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output_path.parent, prefix=".pm-grow-book-", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(result)
    try:
        temporary.replace(output_path)
    finally:
        temporary.unlink(missing_ok=True)
    return {"output": str(output_path.resolve()), "topics": len(book["topics"]), "backup": str(backup.resolve()) if backup else None}


# ---------------------------------------------------------------- topic maintenance

def _load_book(source):
    book = read_json(source)
    if not isinstance(book, dict) or not isinstance(book.get("topics"), list):
        raise ValueError(f"{source} 不是有效的手册源文件：需要包含 topics 列表")
    return book


def _topic_index(book, identifier):
    return next((index for index, topic in enumerate(book["topics"])
                 if isinstance(topic, dict) and topic.get("id") == identifier), None)


def _save_book(source, book):
    """Back up the previous source, then replace it atomically and verify the read-back."""
    backup = None
    if source.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup = source.with_name(f"{source.stem}.previous-{stamp}{source.suffix}")
        shutil.copy2(source, backup)
    atomic_write_json(source, book)
    if read_json(source) != book:
        raise ValueError(f"{source} 写入后读回内容不一致")
    return str(backup.resolve()) if backup else None


def list_topics(source):
    """Read-only overview, so the mentor can reuse IDs instead of editing JSON by hand."""
    source = Path(source).expanduser()
    location = str(source.resolve())
    if not source.exists():
        return {"input": location, "exists": False, "topics": [],
                "note": "手册源文件还不存在；用户同意收录后用 handbook upsert 新增第一个专题"}
    book = _load_book(source)
    result = {"input": location, "exists": True, "title": book.get("title"), "updated_on": book.get("updated_on"),
              "topics": [{key: topic.get(key) for key in ("id", "title", "updated_on")}
                         for topic in book["topics"] if isinstance(topic, dict)]}
    try:
        validate(deepcopy(book))
        result["valid"] = True
    except ValueError as exc:
        result.update({"valid": False, "error": str(exc)})
    return result


def upsert(root, source, topic, today=None, timeout=10.0):
    """Replace one topic in place by id, or append it; the whole book must still validate."""
    if not isinstance(topic, dict):
        raise ValueError("专题必须是 JSON 对象")
    identifier = topic.get("id")
    if not isinstance(identifier, str) or not SLUG.fullmatch(identifier):
        raise ValueError("专题 id 必须是小写字母、数字和单个连字符组成的 slug")
    day = today_value(today).isoformat()
    source = Path(source).expanduser()
    with file_lock(root, timeout=timeout):
        book = _load_book(source if source.exists() else BOOK_TEMPLATE)
        index = _topic_index(book, identifier)
        existing = book["topics"][index] if index is not None else None
        incoming = dict(topic)
        if "updated_on" not in incoming:
            if existing is not None and {k: v for k, v in existing.items() if k != "updated_on"} == incoming:
                incoming = existing
            else:
                incoming["updated_on"] = day
        if existing is not None and existing == incoming and source.exists():
            return {"input": str(source.resolve()), "action": "unchanged", "topic_id": identifier,
                    "topics": len(book["topics"]), "backup": None}
        updated = deepcopy(book)
        if index is None:
            updated["topics"].append(incoming)
            action = "created"
        else:
            updated["topics"][index] = incoming
            action = "replaced"
        updated["updated_on"] = day
        validate(deepcopy(updated))
        backup = _save_book(source, updated)
    return {"input": str(source.resolve()), "action": action, "topic_id": identifier,
            "topics": len(updated["topics"]), "backup": backup,
            "next": "生成或更新 HTML：handbook build（已有输出时加 --replace）"}


def remove(root, source, identifier, today=None, timeout=10.0):
    """Delete one topic by id, keeping a backup; a handbook always keeps at least one topic."""
    day = today_value(today).isoformat()
    source = Path(source).expanduser()
    with file_lock(root, timeout=timeout):
        if not source.exists():
            raise ValueError(f"手册源文件不存在：{source}")
        book = _load_book(source)
        index = _topic_index(book, identifier)
        if index is None:
            raise ValueError(f"手册里没有专题 {identifier}；先用 handbook list 查看已有专题")
        if len(book["topics"]) == 1:
            raise ValueError("删除后手册将没有任何专题；确实要清空时，请和用户确认后直接删除源文件")
        updated = deepcopy(book)
        del updated["topics"][index]
        updated["updated_on"] = day
        validate(deepcopy(updated))
        backup = _save_book(source, updated)
    return {"input": str(source.resolve()), "action": "removed", "topic_id": identifier,
            "topics": len(updated["topics"]), "backup": backup,
            "next": "更新 HTML：handbook build --replace"}
