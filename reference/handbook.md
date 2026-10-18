# 累计知识手册

知识手册是用户自己的 PM 方法库，由一个单文件 HTML 承载，可以离线搜索和打印。成长报告记录“我成长了什么”，知识手册沉淀“我学会了哪些方法、业务里的哪些机制”。

## 先提议，再生成

出现以下值得长期保留的内容时，列出拟收录的主题，询问用户是否生成或更新手册：

- 一个讲清楚的概念
- 一个值得复盘的案例
- 一条梳理过的业务机制
- 一个改造成本业务版本的方法（`knowledge/business-methods.md` 里的条目）
- 一个需要持续跟进的开放问题

用户明确同意后，才修改知识源并生成手册。有几条规则：

- 每次同意只覆盖当次列出的主题。
- 用户暂缓时，在记录里注明；有新增知识后再提。
- 没有新增内容时不重复邀请。

## 专题怎么写

专题结构由内容决定，可以按需组合：

| 内容类型 | 常见写法 |
|---|---|
| 概念 | 定义、成立条件、易混淆之处 |
| 案例 | 经过、结果、解释的局限 |
| 业务机制 | 参与者与规则、为什么会发生、可能失效的条件 |
| 方法 | 关键判断、步骤、边界、在本业务中的用法 |
| 开放问题 | 已知证据、几种可能的解释、什么证据会改变判断 |

- 有的就写，没有的栏目直接省略。
- 不确定的地方明确写出来。
- 个人能力评价、同事评价和敏感的内部细节放在成长档案里，不进手册。
- 内部来源用用户确认过的脱敏名称和定位。

## 数据格式

源文件在 `<data-dir>/knowledge/handbook.json`，从 [templates/handbook.json](../templates/handbook.json) 开始。

**每个专题必填：**

| 字段 | 要求 |
|---|---|
| `id` | 小写英文加短横线，保持稳定 |
| `title` | 专题标题 |
| `updated_on` | 格式 YYYY-MM-DD |
| `sources` | 每条包含 `title`、`checked_on`，以及 `url`（公开来源，http 或 https）或 `locator`（内部来源或会话定位）；可选 `scope` |
| 正文 | 至少一段有内容的正文 |

**正文格式：**

- 推荐使用 `sections`，形如 `[{"heading": "段落标题", "content": "正文"}]`，按阅读顺序排列，正文以纯文本显示。
- 旧字段仍然可用，都可以省略：`problem`、`context`、`judgment`、`steps`、`boundaries`、`pitfalls`、`case`、`template`、`counterexample`、`next_action`、`first_principles`、`tags`。

修改已有专题前先读出原内容，按 `id` 更新，保留其他专题。

## 生成与检查

```sh
python3 <skill-dir>/scripts/pmgrow.py --data-dir <data-dir> handbook build \
  --input <data-dir>/knowledge/handbook.json --output <data-dir>/knowledge/handbook.html
```

更新已有手册时加 `--replace`，脚本会备份上一版。

生成后，有浏览器工具时实际打开页面，检查以下几项：

- 目录跳转
- 搜索和清空搜索
- 打印
- 窄屏排版

检查完成后，把绝对路径交给用户。无法检查时，如实说明。
