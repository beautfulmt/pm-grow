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
python3 scripts/pmgrow.py --data-dir <data-dir> status
python3 scripts/pmgrow.py --data-dir <data-dir> status --full
python3 scripts/pmgrow.py --data-dir <data-dir> status --recent 0
python3 scripts/pmgrow.py --data-dir <data-dir> recent --limit 5 --problem-id <id>
python3 scripts/pmgrow.py --data-dir <data-dir> recent --context-ref <业务ID>
```

- `init` 补齐缺失模板和目录，保留现有文件。
- `status`、`recent` 和迁移预览为只读，不因目录不存在就自动创建它。
- `status` 默认输出精简版（单行 JSON），每次开场读一遍。数据积累几个月后，体积也保持在几 KB。
  - **原有键名不变：**`stage`、`abilities`、`open_problems`、`follow_ups_due`、`report`、`recent`、`migration_needed`。
  - **新增键：**
    - `focus`：焦点能力及设定以来的练习次数。
    - `stale_problems`：30 天没动静的未结问题。
    - `transfer_opportunities`：至少 7 天前只在示范、引导或讲解中用过（那条记录没有 independent 产出）、之后还没独立用过的方法。
    - `counts`：各列表的总数。
    - `view`：`compact` 或 `full`，标明这次输出的是哪一版。
  - **列表上限：**未结问题、到期回访、条件回访各最多 5 条；长期未动的问题、迁移机会各最多 3 条。`abilities.current` 只列当前阶段已有程度、有观察记录、带此前阶段程度（`prior`）或属于焦点的能力，其余计入 `unobserved_count`。
  - **有省略时：**`truncated` 为 true，并给出 `hint`。
- `status --full` 输出全部条目和完整字段（缩进格式）。`--recent N` 控制附带的近期记录条数，0 表示不附带。
- `follow_ups_due` 中的 `due` 项可按日期回访，逾期最久的在前；`condition_pending` 项等条件实际出现时再问，最近登记的在前。属于长期未动问题的条件回访，只在 `stale_problems` 中出现。
- 问题在登记回访之后被写成 solved、dropped 或 closed，该回访自动失效。回访和终态写在同一条或更晚的记录里时，回访保留。

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

写入新记录时，脚本还会做以下校验。推导已保存的记录时只复核证据存在、未作废和条数、问题数、产出类型，所以旧记录不会因门槛收紧被追溯作废：

- **能力升级：**每条证据都要有同一能力的观察，不能跳级，independent 的证据要来自至少 2 个不同日期。stable 的证据要相隔至少 14 天、至少 1 条是新证据，并带 `review`（`mode` 为 agent 或 self_check）。
- **阶段调整：**已有阶段时，`stage_update` 必须写 `basis`；`performance` 只用于升阶，需要当前阶段至少 2 项能力达到 stable，并带 `review`。
- **引用：**`methods` 和 `problem.scenario` 必须是技能中已有的方法卡或场景 ID；写错时报错，并提示最接近的 ID。

拒绝信息写在 stderr，按提示补齐后重试即可。

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
python3 scripts/pmgrow.py --data-dir <data-dir> report defer --until 2026-11-01
python3 scripts/pmgrow.py --data-dir <data-dir> settings set report_mode propose
```

1. `draft` 汇总尚未覆盖的有效记录；`--since` 改为按事件日期选取。没有符合条件的新记录会报错。
2. 导师只补 `narrative`，保留脚本生成的 `basis` 与 `facts`。叙述包含 headline、learned_summary、problems_summary、growth_summary、gaps、next_focus、message。
3. `gaps` 的条目包含已知能力 ID、观察和下一次实践；缺少可靠依据时可为空数组，报告如实说明证据不足。
4. `build` 重新核对事实。记录已变化或 facts 被改动时，重新生成草稿再补叙述。
5. 默认输出 `reports/YYYY-MM-DD.html` 及同名 JSON，成功后更新报告游标并清除暂缓状态。同名报告需要已授权的 `--replace`，上一版会备份。
6. `facts` 含 `ability_overview`（各能力的当前阶段程度与此前阶段程度）和 `focus`（本期焦点及进展），页面在“成长与欠缺”中渲染“本期焦点”和“能力全景”。v2.0 生成的旧报告 JSON 没有这两项，照样可以渲染。

`defer` 把报告提议的时钟拨到现在：此后只有暂缓之后写入的记录才计入触发条件，即 3 个含用户尝试的问题、新的关键节点，或暂缓满 14 天且期间有新记录。`--until YYYY-MM-DD`（必须晚于今天）表示这一天之前一律不提议；到了这一天，尚未写进报告的记录会再次提议，原因代码为 `until_reached`。v2.0 的暂缓记录照常读取。`report_mode` 支持 `propose` 和 `auto`，只有用户选择自动生成时才设置 `auto`。

报告时机与页面验收见[成长反馈](../growth/feedback-and-reports.md)。

## 知识手册

```sh
python3 scripts/pmgrow.py --data-dir <data-dir> handbook list
python3 scripts/pmgrow.py --data-dir <data-dir> handbook upsert --topic topic.json
python3 scripts/pmgrow.py --data-dir <data-dir> handbook upsert --topic - < topic.json
python3 scripts/pmgrow.py --data-dir <data-dir> handbook remove --id <topic-id>
python3 scripts/pmgrow.py --data-dir <data-dir> handbook build
python3 scripts/pmgrow.py --data-dir <data-dir> handbook build --replace
python3 scripts/pmgrow.py --data-dir <data-dir> handbook build \
  --input <data-dir>/knowledge/handbook.json --output <tmp>/handbook.html
```

- 默认读写 `knowledge/handbook.json`，`--input` 可以指定其他源文件。
- `list` 只读，列出专题的 id、标题和更新日期，并说明源文件能否通过校验。
- `upsert` 读入一个专题：`id` 已存在就原位替换，否则追加；源文件不存在时从模板新建。整本校验通过才写入，上一版备份为 `handbook.previous-<时间>.json`。内容没有变化时返回 `unchanged`，不写文件。专题省略 `updated_on` 时用 `--today` 或当天日期。
- `remove` 按 `id` 删除一个专题并备份；不能删到一个专题都不剩。
- `build` 生成离线 HTML。更新已有输出时加 `--replace`，脚本保留上一版备份。

内容须经用户同意，格式见[知识手册](../reference/handbook.md)。

## 清除敏感信息

```sh
python3 scripts/pmgrow.py --data-dir <data-dir> redact --input request.json --dry-run
python3 scripts/pmgrow.py --data-dir <data-dir> redact --input - < request.json
```

```json
{"replacements": [{"find": "某客户全称", "replace": "[客户A]"}], "label": "用户要求去掉客户名"}
```

- 处理整个数据目录的文本文件：记录、状态、档案、业务背景、报告与手册（含备份）、个人行业包、扩展注册表和 `legacy-v1/` 等。隐藏文件、隐藏目录和非文本文件不处理，后者列在 `skipped`。
- 记录 ID、问题 ID、日期、枚举值和文件名等标识不改写，命中位置列在 `identifier_matches`。方法列表里只替换 `custom:` 开头的个人方法。
- 先在内存中完成替换和校验。任何字段会被替换成空文字，或记录、状态、手册校验失败时，整体中止，不写任何文件。
- 报告和手册按替换后的 JSON 重新渲染，结果列在 `rerendered`；没有对应 JSON 的 HTML 和备份按原文及其 HTML 转义形式替换；growth-log 索引会重建。已迁移的 v1 原件内容变化时，同步更新迁移指纹（`migration_fingerprint_updated`），不会被要求重新迁移。
- `find` 至少 2 个非空白字符，不能重复；`replace` 不能包含任何 `find`，所以重复执行不会再改动。
- 执行后在 `redactions.json` 追加一条日志，只记时间、`label`、改动文件数和替换次数，不保存原文。操作流程见[证据与记录](../reference/evidence-and-records.md)。

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
