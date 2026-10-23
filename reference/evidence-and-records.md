# 证据与记录

## 证据原则

本节是全技能唯一定义证据规则的地方。

1. 能力判断只看用户本人的产出，即用户在真实任务、或明确标注过的模拟中，自己做出的判断、方案、修改和结果。
2. 以下内容不算能力证据：导师或 Agent 的示范、用户说“懂了”、聊天次数、时间流逝、知识被收进手册。
3. 一次表现只说明这一次。能力变化需要跨多个问题、跨时间的可比证据，而且证据要针对这项能力本身；门槛见下文，由脚本校验。
4. 比较前后表现时，要核对任务难度、用户得到的帮助，以及当时的职责和约束。
5. 某条观察被反证后就撤回，并同步修正依赖它的结论；历史记录保留不删。
6. 没有实践机会、用户选择跳过练习、业务结果受外部因素影响，这些情况都不能解释为能力差。
7. 写入完成并读回确认后，才能对用户说“已记录”。
8. 能力要升到“复杂情境稳定”、或按表现升阶之前，先委派 growth-reviewer 独立复核证据，结论写进记录的 `review`；宿主没有委派工具时由主导师按角色卡自查（`self_check`），并告诉用户。

## 什么时候记录

每轮回复结束前，按以下优先级检查：

1. 用户要求不记录，或本轮属于第三方代问、只交付制品、技能维护时，不写成长记录，也不更新个人档案和偏好。
2. 本人学习且允许记录时，新增长期偏好、偏好变更和更正都要保存，任何回答档位均适用。“只回复收到”只限制回复内容；明确说“不要记录”时遵从上一条。偏好标明本轮、某类任务或长期的作用范围。
3. 其余快答内容，只在问题状态有变化时记录，例如有了结果、决定放弃或约定了回访。普通事实或方法问答不写记录。
4. 标准和深度档，对照下面的清单，有新增内容就写记录；寒暄、重复内容和同一问题上没有新变化的追问不写。

不要等对话自然结束再补记：导师无法知道哪一轮是最后一轮，用户不再回来时，没写下的问题就不会被回访，也不会进入报告。早记的内容后来有变化，再写一条记录更新或更正即可。值得记录的内容包括：

- 出现了新问题
- 对问题的理解发生了变化
- 用户给出的判断或产出
- 做出的取舍
- 背景或职责的变化
- 新偏好或偏好变更
- 约定的下一步
- 回访结果
- 更正

## 数据目录

数据目录按以下顺序确定：用户指定的目录 > `PM_GROW_DATA_DIR` > `~/pm-grow-data`。一个目录只服务一位学习者。

| 文件 | 内容 |
|---|---|
| profile.md | 职责、阶段及依据、赛道与产品、成长目标、帮助偏好与报告偏好 |
| business-context.md | 业务事实及来源、选用的行业包、约束、未知项 |
| records/ | 每轮有值得记录的变化时写一条记录，写入后不可修改 |
| state.json | 自定义能力、报告进度与暂缓状态、设置，由脚本维护 |
| growth-log.md | 记录索引。脚本只更新它生成的区块，区块外可以手写 |
| reports/ | 成长报告 |
| knowledge/ | 知识手册源文件与 HTML、业务方法沉淀 |
| industries/ | 个人行业包 |
| extensions.json | 个人扩展注册表 |
| redactions.json | 清除敏感信息的操作日志，只记时间、说明、改动文件数和替换次数，不含原文 |

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
| status | 每次开场运行，只读，不会创建任何文件。默认返回精简版：到期回访、30 天没动静的问题（`stale_problems`）、焦点能力（`focus`）、迁移练习机会（`transfer_opportunities`）、报告时机、能力快照（含此前阶段的程度 `prior`）、当前阶段、最近的未结问题和近期记录。各列表只列最需要处理的几项，总数见 `counts`；有省略时 `truncated` 为 true，需要完整列表时加 `--full` |
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
| `problem` | 同一个 `id` 跨多条记录合并，后写入的字段覆盖先写入的。`status` 取值：open、solved、partial、blocked、dropped、closed。`check_back` 填 `on`（日期）或 `when`（条件），再加上要问的 `question`。`scenario` 写 playbooks/ 下已有的场景 ID，没有合适的就省略 |
| `problem.outcome` | 实际结果及核验范围，直接写在 `problem` 内。首次设置或切换到 solved/partial 时，本条记录必须填写；保持同一状态且已有有效结果时可沿用。只写在 summary 或 user_work 中不会进入报告的结果栏。结果未知时保留 open/blocked；已结束但结果未核实用 closed |
| `user_work` | `kind` 取值：independent、guided、demo、acknowledgement。只写用户本人的产出；导师和 Agent 的贡献写在 `assistance` |
| `methods` | knowledge/methods/ 下已有的方法卡 ID，写错时脚本拒绝并提示最接近的 ID；个人方法写成 `custom:<名称>` |
| `observations` | `status` 取值：candidate、supported、withdrawn |
| `ability_updates` | 能力程度变化，需满足下文的门槛。可带 `review`：`{"mode": "agent", "summary": "复核结论"}`，`mode` 取 agent 或 self_check；升到 stable 时必填 |
| `stage_update` | `{"stage": "senior", "reason": "...", "basis": "role_change"}`。`basis` 取值见下文“阶段调整”；已有阶段时必填，按表现升阶时另带 `review` |
| 文本字段 | `milestone`、`unresolved`、`next_step`、`assistance`、`context_ref` 均为非空字符串；多个未决点可用换行写在同一字符串中 |
| `preferences` | 字符串数组，只记录用户明确表达过的偏好 |
| `focus_update` | `{"abilities": ["data_validation"], "reason": "..."}`：本期焦点能力，0–2 个不重复的已知能力 ID，必须是用户认可的；空数组表示清除焦点。`reason` 必填，写用户原话里的目标。以最后一条有效记录为准，`status` 和成长报告据此展示焦点进展 |

回访确认结果时，例如：

```json
"problem": {
  "id": "onboarding-entry",
  "status": "solved",
  "outcome": "原先反馈的 10 位新用户验收均能找到入口；结论仅覆盖该样本。"
}
```

结果检查仅用于新写入，旧记录仍可读取和原样重试。旧记录已是 solved/partial 却缺少结果时，报告显示“结果尚未补录”。核实来源后，追加同一 `problem.id` 的 follow_up 记录补充 `problem.outcome`，由脚本更新结果栏和关键节点；不得根据状态猜测结果或覆盖旧记录。

## 升级门槛

写入新记录时，脚本校验以下门槛：

| 升到 | 证据记录 | 不同问题 | 用户产出 | 时间 |
|---|---|---|---|---|
| needs_support | 至少 1 条 | 不限 | guided 或 independent | 不限 |
| independent | 至少 2 条 | 至少 2 个 | 每条都含 independent | 来自至少 2 个不同日期 |
| stable | 至少 3 条 | 至少 3 个 | 每条都含 independent | 最早到最晚相隔至少 14 天，且至少 1 条是升到 independent 之后的新证据 |

- **针对这项能力：**每条证据记录都要有同一 `ability_id`、未撤回的观察（observations）。为别的能力写的记录不能拿来凑数。
- **不跳级：**一次升一级，只有 unobserved 可以直接升到 independent；stable 只能从 independent 升上来。降级可以跨级。
- **复核留痕：**升到 stable 时，这条 ability_update 必须带 `review`。`mode: agent` 表示派了独立的 growth-reviewer；`mode: self_check` 表示宿主没有委派工具，由主导师按角色卡自查，并已告诉用户。`summary` 写复核结论，见[多 Agent 协作](agents.md)。
- `from` 必须等于这项能力在该阶段的当前程度。
- 证据记录必须存在、没有被作废，并且日期不晚于本条记录。
- demo 和 acknowledgement 不能作为证据。
- 降级或撤回需要至少 1 条证据，或者一条更正。
- 以上规则在写入时校验。推导已保存的记录时，只复核证据是否存在、是否被作废，以及条数、问题数和用户产出类型；观察相关性、日期、跨度、跳级、新证据和复核只在写入时检查，所以旧记录不会因为门槛收紧而被追溯作废。证据被更正作废、剩下的证据不再满足条数或问题数时，依赖它的变化随之失效。

脚本拒绝时会说明缺少什么。这时如实告诉用户还差什么，例如“还差一次在另一天独立完成的机会”，等有了新证据再升级。

### 阶段调整

写入 `stage_update` 时，脚本按 `basis` 校验：

| 情况 | basis | 要求 |
|---|---|---|
| 第一次定位 | 省略或写 initial | 无 |
| 换岗、升职、转方向 | role_change | 写清职责变化；能力在新阶段重新观察，旧阶段的程度保留 |
| 表现持续超出当前阶段 | performance | 只用于升阶；当前阶段至少 2 项能力达到 stable，并带 `review` |
| 之前的定位有误 | correction | 写清理由 |

已有阶段时必须写 basis，不能写 initial，目标阶段也不能与当前相同。阶段顺序为新人 → 独立 PM → 资深 → 专家或负责人；专家与负责人之间切换用 role_change。旧版本写下的、没有 basis 的阶段记录照常读取。

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

## 清除敏感信息

用户发现误记了不该保存的内容（客户名、同事评价、内部数据等）并要求删除时，按以下步骤处理。这是“记录写入后不可修改”的唯一例外：只替换文字，记录的结构、日期和推导结果保持不变。

1. **确认替换内容。**和用户确认要清除的原文和替换文字，例如把客户全称换成“[客户A]”。原文只放在命令输入里，不写进记录、摘要或 `label`。
2. **先预览。**

   ```sh
   python3 <skill-dir>/scripts/pmgrow.py --data-dir <data-dir> redact --input - --dry-run
   ```

   输入格式：`{"replacements": [{"find": "原文", "replace": "替换文字"}], "label": "可选，不含原文的说明"}`。把 `files_changed` 列出的文件和 `replacement_counts` 里每条替换的次数告诉用户。
3. **用户确认后执行。**去掉 `--dry-run` 再运行一次。脚本先在内存里完成全部替换，并校验记录、状态和手册；有任何字段会变成空文字或校验失败时整体中止，不写入任何文件。报告和手册按替换后的内容重新渲染，growth-log 索引同步重建。重复执行不会再改动。
4. **说明结果和剩余部分。**
   - `identifier_matches` 列出的记录 ID、问题 ID、文件名等标识不会被改写，以免破坏证据链。告诉用户命中的位置，由用户决定是否另行处理。
   - 数据目录之外的副本不受影响，例如云同步的历史版本、已分享或另存的报告与草稿、版本库历史。提醒用户自行清理。

## 无法写入文件时

在当前会话内完成工作，结束时给用户一段可以自行保存的摘要，并说明下次无法自动接续。
