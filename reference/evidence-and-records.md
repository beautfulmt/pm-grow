# 证据与记录

## 证据原则

本节是全技能唯一定义证据规则的地方。

1. 能力判断只看用户本人的产出，即用户在真实任务、或明确标注过的模拟中，自己做出的判断、方案、修改和结果。
2. 以下内容不算能力证据：导师或 Agent 的示范、用户说“懂了”、聊天次数、时间流逝、知识被收进手册。
3. 一次表现只说明这一次。能力变化需要跨多个问题的可比证据，门槛见下文，由脚本校验。
4. 比较前后表现时，要核对任务难度、用户得到的帮助，以及当时的职责和约束。
5. 某条观察被反证后就撤回，并同步修正依赖它的结论；历史记录保留不删。
6. 没有实践机会、用户选择跳过练习、业务结果受外部因素影响，这些情况都不能解释为能力差。
7. 写入完成并读回确认后，才能对用户说“已记录”。

## 什么时候记录

本人学习、并且允许记录时，在自然停顿处为每次实质交流写一条记录。值得记录的内容包括：

- 对问题的理解发生了变化
- 用户给出的判断或产出
- 做出的取舍
- 背景或职责的变化
- 用户的偏好
- 约定的下一步
- 回访结果
- 更正

以下情况不记录：

- 寒暄和重复内容
- 第三方代问
- 只交付制品
- 技能维护
- 用户要求不记录

## 数据目录

数据目录按以下顺序确定：用户指定的目录 > `PM_GROW_DATA_DIR` > `~/pm-grow-data`。一个目录只服务一位学习者。

| 文件 | 内容 |
|---|---|
| profile.md | 职责、阶段及依据、赛道与产品、成长目标、帮助偏好与报告偏好 |
| business-context.md | 业务事实及来源、选用的行业包、约束、未知项 |
| records/ | 每次实质交流一条记录，写入后不可修改 |
| state.json | 自定义能力、报告进度、设置，由脚本维护 |
| growth-log.md | 记录索引。脚本只更新它生成的区块，区块外可以手写 |
| reports/ | 成长报告 |
| knowledge/ | 知识手册源文件与 HTML、业务方法沉淀 |
| industries/ | 个人行业包 |
| extensions.json | 个人扩展注册表 |

## 命令

`<skill-dir>` 换成技能实际所在的目录。没有 Python 时，用宿主的文件工具按同样的格式读写，并告诉用户这次没有经过脚本校验。

```sh
python3 <skill-dir>/scripts/pmgrow.py --data-dir <data-dir> init
python3 <skill-dir>/scripts/pmgrow.py --data-dir <data-dir> status
python3 <skill-dir>/scripts/pmgrow.py --data-dir <data-dir> record --input -
python3 <skill-dir>/scripts/pmgrow.py --data-dir <data-dir> recent --limit 5 --problem-id <id>
python3 <skill-dir>/scripts/pmgrow.py --data-dir <data-dir> migrate --dry-run
```

| 命令 | 用途 |
|---|---|
| init | 首次使用时运行，只补齐缺失的文件 |
| status | 每次开场运行，只读，不会创建任何文件。返回到期的回访、报告时机、能力快照、当前阶段、未结束的问题和近期记录 |
| record | 从标准输入读入一条 JSON 记录 |
| recent | 查看近期记录 |
| migrate | 迁移旧格式数据，见下文 |

报告相关命令见[反问、成长告知与成长报告](../growth/feedback-and-reports.md)，手册相关命令见[知识手册](handbook.md)，完整参数见 [scripts/CLI.md](../scripts/CLI.md)。

## 记录格式

```json
{
  "record_id": "2026-10-19-pdp-conversion",
  "date": "2026-10-19",
  "kind": "attempt",
  "summary": "详情页转化下降：用户按渠道拆解，定位到直播导流新客",
  "source": "2026-10-19 会话，用户贴出的渠道拆解表",
  "context_ref": "shop-app",
  "problem": {
    "id": "pdp-conversion-drop",
    "title": "商品详情页转化率下降",
    "scenario": "metric-anomaly",
    "status": "open",
    "check_back": {"on": "2026-10-26", "question": "新客落地页调整后转化恢复了吗？"}
  },
  "user_work": [
    {"kind": "independent", "content": "按渠道和新老客拆解，发现下降集中在直播导流新客", "source": "用户贴出的拆解表"}
  ],
  "assistance": "导师给出竞争解释清单，以及拆解维度的先后顺序",
  "methods": ["metric-diagnosis"],
  "observations": [
    {"ability_id": "data_validation", "text": "先核对分母变化再找原因", "status": "candidate"}
  ],
  "ability_updates": [
    {"ability_id": "data_validation", "stage": "independent_pm", "from": "needs_support", "to": "independent",
     "evidence": ["2026-10-12-coupon-roi", "2026-10-19-pdp-conversion"], "reason": "两个不同问题中独立完成口径核对和拆解"}
  ],
  "next_step": "用户找直播运营确认最近的选品变化"
}
```

**必填字段**：`record_id`（小写英文、数字和短横线）、`date`（事件实际发生的日期）、`kind`、`summary`、`source`。

**可选字段**：

| 字段 | 说明 |
|---|---|
| `kind` | 取值：discussion、exploration、attempt、follow_up、context_update、preference、correction、milestone、review |
| `problem` | 同一个 `id` 跨多条记录合并，后写入的字段覆盖先写入的。`status` 取值：open、solved、partial、blocked、dropped、closed。`check_back` 填 `on`（日期）或 `when`（条件），再加上要问的 `question` |
| `user_work` | `kind` 取值：independent、guided、demo、acknowledgement。只写用户本人的产出；导师和 Agent 的贡献写在 `assistance` |
| `methods` | 方法卡 ID；个人方法写成 `custom:<名称>` |
| `observations` | `status` 取值：candidate、supported、withdrawn |
| `ability_updates` | 能力程度变化，需满足下文的门槛 |
| `stage_update` | `{"stage": "senior", "reason": "..."}` |
| 文本字段 | `milestone`、`unresolved`、`next_step`、`assistance`、`context_ref` 均为非空字符串；多个未决点可用换行写在同一字符串中 |
| `preferences` | 字符串数组，只记录用户明确表达过的偏好 |

## 升级门槛

脚本会校验以下门槛：

| 升到 | 需要 |
|---|---|
| needs_support | 至少 1 条证据记录，含 guided 或 independent 的 user_work |
| independent | 至少 2 条证据记录，来自 2 个以上不同的问题，每条都含 independent 的 user_work |
| stable | 至少 3 条证据记录，来自 3 个以上不同的问题，每条都含 independent 的 user_work |

- `from` 必须等于这项能力在该阶段的当前程度。
- 证据记录必须存在、没有被作废，并且日期不晚于本条记录。
- demo 和 acknowledgement 不能作为证据。
- 降级或撤回需要至少 1 条证据，或者一条更正。

脚本拒绝时会说明缺少什么。这时如实告诉用户“还差一次独立完成的机会”，等有了新证据再升级。

## 更正

追加一条 `kind: "correction"` 的记录：

```json
"corrections": [{"record_id": "<原记录ID>", "reason": "更正内容与理由", "invalidate": true}]
```

- `invalidate: true`：原记录不再参与推导问题状态、能力和报告，但仍然保留在磁盘和历史中。
- 只修正背景事实时用 `false`，然后由主导师同步更新受影响的 profile 或 business-context。

## 从 v1 迁移

`status` 返回 `migration_needed: true` 时，按以下步骤处理：

1. 告诉用户需要迁移。
2. 运行 `migrate --dry-run`，把迁移计划给用户看。
3. 用户同意后，运行 `migrate`。旧文件会完整复制到 `legacy-v1/<时间戳>/`；profile.md、business-context.md 和 learning-plan.md 保留原样。

## 无法写入文件时

在当前会话内完成工作，结束时给用户一段可以自行保存的摘要，并说明下次无法自动接续。
