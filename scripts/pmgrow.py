#!/usr/bin/env python3
"""pm-grow v2 command line: the only entry point for personal records, reports,
handbooks, migration and redaction. Every command prints one JSON object on success; errors
go to stderr as `错误：...` with exit code 1. See scripts/CLI.md."""
import argparse
import json
from pathlib import Path
import sys

import handbook
import migrate
import records
import redact
import report


def read_input(value):
    if value == "-":
        try:
            return json.loads(sys.stdin.buffer.read().decode("utf-8"))
        except ValueError as exc:
            raise ValueError(f"无法从标准输入读取 JSON：{exc}") from exc
    return records.read_json(Path(value))


def common_options(parser, defaults):
    # Global options work before or after the subcommand; only the top level sets defaults.
    def default(value):
        return value if defaults else argparse.SUPPRESS

    parser.add_argument("--data-dir", default=default(None),
                        help="数据目录（优先于 PM_GROW_DATA_DIR，默认 ~/pm-grow-data）")
    parser.add_argument("--lock-timeout", type=float, default=default(10.0),
                        help="等待写锁的最长秒数（默认 10）")
    parser.add_argument("--today", default=default(None),
                        help="按指定日期（YYYY-MM-DD）计算到期与报告，用于回放和测试")


def build_parser():
    parser = argparse.ArgumentParser(prog="pmgrow.py", description=__doc__)
    common_options(parser, True)
    shared = argparse.ArgumentParser(add_help=False)
    common_options(shared, False)
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")

    commands.add_parser("init", parents=[shared], help="创建数据目录与模板（保留已有文件）")
    status = commands.add_parser("status", parents=[shared], help="只读：一次返回开场需要的状态（默认精简版）")
    status.add_argument("--recent", type=int, default=5, help="附带最近几条记录（默认 5；0 表示不附带）")
    status.add_argument("--full", action="store_true", help="输出完整列表；默认精简版只列最需要处理的几项")

    record = commands.add_parser("record", parents=[shared], help="写入一条不可变记录")
    record.add_argument("--input", required=True, help="JSON 文件路径；- 表示从标准输入读取")

    recent = commands.add_parser("recent", parents=[shared], help="只读：最近记录及其更正链")
    recent.add_argument("--limit", type=int, default=5)
    recent.add_argument("--problem-id")
    recent.add_argument("--context-ref")

    ability = commands.add_parser("ability", parents=[shared], help="自定义能力")
    ability_commands = ability.add_subparsers(dest="action", required=True, metavar="action")
    register = ability_commands.add_parser("register", parents=[shared], help="注册 custom.<slug> 能力")
    register.add_argument("--input", required=True, help="JSON 文件路径；- 表示标准输入")
    register.add_argument("--replace", action="store_true", help="明确替换已有的不同定义（旧定义进入 history）")

    reports = commands.add_parser("report", parents=[shared], help="成长报告")
    report_commands = reports.add_subparsers(dest="action", required=True, metavar="action")
    draft = report_commands.add_parser("draft", parents=[shared], help="只读：输出事实已汇总、叙述待填写的 JSON")
    draft.add_argument("--since", help="改为包含该日期（含）之后的全部有效记录")
    draft.add_argument("--output", help="另存为文件（不覆盖已有文件）；默认只打印")
    build = report_commands.add_parser("build", parents=[shared], help="校验叙述并渲染 HTML，更新报告游标")
    build.add_argument("--input", required=True, help="填好 narrative 的 JSON；- 表示标准输入")
    build.add_argument("--output", help="默认 <data-dir>/reports/YYYY-MM-DD.html")
    build.add_argument("--replace", action="store_true", help="替换同名报告（旧文件会备份）")
    defer = report_commands.add_parser("defer", parents=[shared],
                                       help="用户暂缓：之后出现新的触发条件前不再提议")
    defer.add_argument("--until", help="暂缓到这一天（YYYY-MM-DD），当天起再提议")

    settings = commands.add_parser("settings", parents=[shared], help="偏好开关")
    settings_commands = settings.add_subparsers(dest="action", required=True, metavar="action")
    setter = settings_commands.add_parser("set", parents=[shared], help="settings set report_mode propose|auto")
    setter.add_argument("key", choices=["report_mode"])
    setter.add_argument("value")

    books = commands.add_parser("handbook", parents=[shared], help="离线知识手册")
    book_commands = books.add_subparsers(dest="action", required=True, metavar="action")
    book = book_commands.add_parser("build", parents=[shared], help="渲染手册 HTML")
    book.add_argument("--input", help="默认 <data-dir>/knowledge/handbook.json")
    book.add_argument("--output", help="默认 <data-dir>/knowledge/handbook.html")
    book.add_argument("--replace", action="store_true", help="替换已批准更新的手册（旧文件会备份）")
    listing = book_commands.add_parser("list", parents=[shared], help="只读：列出手册专题")
    listing.add_argument("--input", help="默认 <data-dir>/knowledge/handbook.json")
    upsert = book_commands.add_parser("upsert", parents=[shared], help="按 id 新增或原位替换一个专题（备份上一版）")
    upsert.add_argument("--topic", required=True, help="专题 JSON 文件；- 表示从标准输入读取")
    upsert.add_argument("--input", help="默认 <data-dir>/knowledge/handbook.json")
    removal = book_commands.add_parser("remove", parents=[shared], help="按 id 删除一个专题（备份上一版）")
    removal.add_argument("--id", required=True, dest="topic_id", help="要删除的专题 id")
    removal.add_argument("--input", help="默认 <data-dir>/knowledge/handbook.json")

    migration = commands.add_parser("migrate", parents=[shared], help="v1 → v2 迁移（原文件复制到 legacy-v1/）")
    migration.add_argument("--dry-run", action="store_true", help="只打印计划，不写任何文件")
    commands.add_parser("rebuild-index", parents=[shared], help="重建 growth-log.md 的自动索引区块")
    redaction = commands.add_parser("redact", parents=[shared], help="清除误记的敏感文字（先用 --dry-run 预览）")
    redaction.add_argument("--input", required=True, help="替换规则 JSON 文件；- 表示从标准输入读取")
    redaction.add_argument("--dry-run", action="store_true", help="只统计将改动的文件与次数，不写任何文件")
    return parser


def run(args):
    root = records.data_root(args.data_dir)
    timeout, today = args.lock_timeout, args.today
    if today is not None:
        records.parse_date(today, "--today")
    command, action = args.command, getattr(args, "action", None)
    if command == "init":
        return records.init(root, timeout)
    if command == "status":
        if args.recent < 0:
            raise ValueError("--recent 不能是负数")
        return records.status(root, today, args.recent, args.full)
    if command == "record":
        return records.append_record(root, read_input(args.input), timeout)
    if command == "recent":
        return records.recent(root, args.limit, args.problem_id, args.context_ref)
    if command == "ability":
        return records.register_ability(root, read_input(args.input), args.replace, timeout)
    if command == "report" and action == "draft":
        value = report.draft(root, args.since, today)
        if args.output:
            return {"output": report.write_draft(value, args.output), "basis": value["basis"]}
        return value
    if command == "report" and action == "build":
        return report.build(root, read_input(args.input), args.output, args.replace, today, timeout)
    if command == "report":
        return report.defer(root, today, args.until, timeout)
    if command == "settings":
        return records.set_setting(root, args.key, args.value, timeout)
    if command == "handbook":
        source = Path(args.input) if args.input else root / "knowledge" / "handbook.json"
        if action == "list":
            return handbook.list_topics(source)
        if action == "upsert":
            return handbook.upsert(root, source, read_input(args.topic), today, timeout)
        if action == "remove":
            return handbook.remove(root, source, args.topic_id, today, timeout)
        target = Path(args.output) if args.output else root / "knowledge" / "handbook.html"
        return handbook.build(source, target, args.replace)
    if command == "redact":
        return redact.redact(root, read_input(args.input), args.dry_run, timeout)
    if command == "migrate":
        return migrate.migrate(root, args.dry_run, today, timeout)
    return records.rebuild_index(root, timeout)


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        result = run(args)
    except (OSError, ValueError, KeyError, TimeoutError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    # The compact status is read at the start of every session, so it is printed without indentation.
    compact = args.command == "status" and not args.full
    print(json.dumps(result, ensure_ascii=False, **({"separators": (",", ":")} if compact else {"indent": 2})))
    return 0


if __name__ == "__main__":
    sys.exit(main())
