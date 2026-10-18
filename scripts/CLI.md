# pm-grow v2 命令行

统一入口为 `python3 <skill-dir>/scripts/pmgrow.py`，只依赖 Python 标准库。以下示例在技能根目录执行，`<data-dir>` 代表已确定的一位学习者的数据目录。测试使用临时目录。

成功时 stdout 输出一个 JSON 对象；参数和校验错误写入 stderr 并返回非零退出码。只有成功写入并读回之后才能告知用户已保存。

## 数据目录与公共参数

优先级：`--data-dir` > `PM_GROW_DATA_DIR` > `~/pm-grow-data`。

| 参数 | 作用 |
|---|---|
| `--data-dir PATH` | 明确读写哪位学习者的数据 |
| `--today YYYY-MM-DD` | 指定回放日期，影响到期计算和报告日期 |
| `--lock-timeout SECONDS` | 写锁等待上限，默认 10 秒 |

公共参数放在子命令前后均可。`--today` 采用调用者确定的当地日期；它不改变原始记录的事件日期，也不能替代证据。所有写入者须在同一文件系统使用同一数据目录及锁文件。

## 初始化与接续

```sh
python3 scripts/pmgrow.py --data-dir <data-dir> init
python3 scripts/pmgrow.py --data-dir <data-dir> status --recent 5
python3 scripts/pmgrow.py --data-dir <data-dir> recent --limit 5 --problem-id <id>
python3 scripts/pmgrow.py --data-dir <data-dir> recent --context-ref <业务ID>
```

- `init` 补齐缺失模板和目录，保留现有文件。
- `status`、`recent` 和迁移预览为只读，不因目录不存在就自动创建它。
- `status` 返回阶段、能力、未结束问题、`follow_ups_due`、`report`、近期记录与 `migration_needed`。
- `follow_ups_due` 中的 `due` 项可按日期回访，`condition_pending` 项等条件实际出现时再问。

## 记录、更正与能力

```sh
python3 scripts/pmgrow.py --data-dir <data-dir> record --input record.json
python3 scripts/pmgrow.py --data-dir <data-dir> record --input - < record.json
python3 scripts/pmgrow.py --data-dir <data-dir> rebuild-index
```

最小记录示例：

```json
{
  "record_id": "2026-10-19-question-framing",
  "date": "2026-10-19",
  "kind": "exploration",
  "summary": "明确报表使用者与待支持的决策，尚待取证",
  "source": "用户本次对话中的职责和任务描述"
}
```

完整字段、用户产出类别、更正格式与升级门槛见[证据与记录](../reference/evidence-and-records.md)。同一 ID 同样内容可安全重试；同一 ID 内容不同会拒绝，改用新 ID 追加更正。索引损坏时使用 `rebuild-index`，原始 `records/` 是事实来源。

注册个人能力：

```sh
python3 scripts/pmgrow.py --data-dir <data-dir> ability register --input ability.json
python3 scripts/pmgrow.py --data-dir <data-dir> ability register --input ability.json --replace
```

```json
{
  "id": "custom.experiment-design",
  "name": "实验设计",
  "definition": "为具体业务判断设计可验证的对照。",
  "observable_behaviors": ["说明对照条件、观测窗口与失败判据。"]
}
```

`--replace` 只用于已授权替换的不同定义，旧定义进入历史。注册定义本身不构成能力提升。

## 成长报告

```sh
python3 scripts/pmgrow.py --data-dir <data-dir> report draft --output <tmp>/report.json
python3 scripts/pmgrow.py --data-dir <data-dir> report draft --since 2026-10-01
python3 scripts/pmgrow.py --data-dir <data-dir> report build --input <tmp>/report.json
python3 scripts/pmgrow.py --data-dir <data-dir> report defer
python3 scripts/pmgrow.py --data-dir <data-dir> settings set report_mode propose
```

1. `draft` 汇总尚未覆盖的有效记录；`--since` 改为按事件日期选取。没有符合条件的新记录会报错。
2. 导师只补 `narrative`，保留脚本生成的 `basis` 与 `facts`。叙述包含 headline、learned_summary、problems_summary、growth_summary、gaps、next_focus、message。
3. `gaps` 的条目包含已知能力 ID、观察和下一次实践；缺少可靠依据时可为空数组，报告如实说明证据不足。
4. `build` 重新核对事实。记录已变化或 facts 被改动时，重新生成草稿再补叙述。
5. 默认输出 `reports/YYYY-MM-DD.html` 及同名 JSON，成功后更新报告游标。同名报告需要已授权的 `--replace`，上一版会备份。

`defer` 暂缓当前证据集合的报告提示，新增记录后重新计算。`report_mode` 支持 `propose` 和 `auto`，只有用户选择自动生成时才设置 `auto`。

报告时机与页面验收见[成长反馈](../growth/feedback-and-reports.md)。

## 知识手册

```sh
python3 scripts/pmgrow.py --data-dir <data-dir> handbook build
python3 scripts/pmgrow.py --data-dir <data-dir> handbook build \
  --input <data-dir>/knowledge/handbook.json --output <tmp>/handbook.html
```

默认读取 `knowledge/handbook.json`，生成离线 HTML。内容须经用户同意，格式见[知识手册](../reference/handbook.md)。更新已有输出时加 `--replace`，脚本保留上一版备份。

## v1 迁移

```sh
python3 scripts/pmgrow.py --data-dir <data-dir> migrate --dry-run
python3 scripts/pmgrow.py --data-dir <data-dir> migrate
python3 scripts/pmgrow.py --data-dir <data-dir> status
```

先展示预览，用户授权后再迁移。旧文件完整复制到 `legacy-v1/<时间戳>/`，原有背景、业务和学习计划保持原样。迁移保留原始证据性质，第三方、未核实、示范和撤回不会自动变成独立能力证据。重复迁移不重复创建记录。遇到 ID 冲突时保留原数据并停止，先确认冲突来源。

## 故障处理

- **JSON 或字段错误：**按 stderr 修正输入，保留未确认事实。
- **等待写锁超时：**检查同目录的其他写入任务，必要时稍后重试；不要删除锁文件绕过协作锁。
- **写入结果不确定：**用同一个记录 ID 重试，或先查询 `recent`，不要生成新 ID 重复记录。
- **旧档案尚未迁移：**按迁移预览处理，不把空的 v2 视图解释为用户没有历史经验。
- **文件工具或 Python 不可用：**按技能要求给可保存摘要，明确本次未经过脚本校验。
