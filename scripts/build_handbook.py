#!/usr/bin/env python3
"""Render an approved topic collection into a standalone offline HTML handbook."""
import argparse
from datetime import date, datetime
from html import escape
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
from urllib.parse import urlsplit

TEMPLATE = Path(__file__).resolve().parents[1] / "assets" / "handbook.html"
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
PRINCIPLES = {
    "goal": "目标", "facts": "事实", "constraints": "约束",
    "mechanism": "机制", "options": "选择", "validation": "验证",
}


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
        for key in ("title", "problem", "context", "judgment", "case", "template"):
            text_field(topic, key)
        date_field(topic, "updated_on")
        for key in ("steps", "boundaries"):
            text_list(topic, key, required=True)
        for key in ("tags", "pitfalls"):
            text_list(topic, key)
        for key in ("counterexample", "next_action"):
            text_field(topic, key, required=False)
        principles = topic.get("first_principles", {})
        if not isinstance(principles, dict) or any(k not in PRINCIPLES for k in principles):
            raise ValueError("Unknown first_principles field")
        for key in principles:
            text_field(principles, key)
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
    if not value:
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
        '<div class="tags">' + "".join(f'<span class="tag">{escape(t)}</span>' for t in topic.get("tags", [])) + "</div>",
        paragraph("问题与背景", topic["problem"] + "\n" + topic["context"]),
        paragraph("关键判断", topic["judgment"], "judgment"),
    ]
    principles = topic.get("first_principles", {})
    if principles:
        parts.append('<section><h3>关键推导</h3><div class="principles">')
        for key, label in PRINCIPLES.items():
            if key in principles:
                parts.append(f'<div class="principle"><strong>{label}</strong><p>{escape(principles[key])}</p></div>')
        parts.append("</div></section>")
    parts.extend([
        list_section("解题步骤", topic["steps"], ordered=True),
        list_section("适用边界", topic["boundaries"]),
        paragraph("案例", topic["case"]),
        paragraph("反例与失效条件", topic.get("counterexample", "")),
        f'<section><h3>可复用模板</h3><pre>{escape(topic["template"])}</pre></section>',
        list_section("常见误用", topic.get("pitfalls", [])),
        paragraph("下一步", topic.get("next_action", "")),
        '<section class="sources"><h3>来源与核验范围</h3><ul>',
    ])
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
    with input_path.open(encoding="utf-8") as handle:
        book = json.load(handle)
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    print(json.dumps(build(args.input, args.output, args.replace), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
