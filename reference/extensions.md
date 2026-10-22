# 扩展机制

pm-grow 的知识和能力可以按需扩展，分两个层级：

- **技能级扩展**：写进本仓库，所有用户共享。适合通用的方法、行业、场景和角色。
- **个人扩展**：写进用户的数据目录，只服务这一位用户。适合个人的业务、行业和工具。

## 扩展点

| 扩展点 | 技能级位置 | 个人位置 | 模板 | 登记位置 |
|---|---|---|---|---|
| 方法卡 | `knowledge/methods/<id>.md` | `<data-dir>/knowledge/business-methods.md` | [method-card.md](../templates/method-card.md) | [知识地图](../knowledge/map.md) |
| 行业包 | `knowledge/industries/<slug>.md` | `<data-dir>/industries/<slug>.md` | [industry-pack.md](../templates/industry-pack.md) | [行业适配](../knowledge/industry-adaptation.md) |
| 问题场景 | `playbooks/<id>.md` | 无 | [playbook.md](../templates/playbook.md) | [场景索引](../playbooks/index.md) |
| Agent 角色 | [agents.md](agents.md) 中的角色卡 | `<data-dir>/extensions.json` | [role.md](../templates/role.md) | 角色卡列表或注册表 |
| 外部工具或 skill | 无 | `<data-dir>/extensions.json` | [extensions.json](../templates/extensions.json) | 注册表本身 |

能力维度另行扩展：用 `ability register` 注册 `custom.<slug>`，见[能力模型](../growth/abilities.md)。

## 个人扩展注册表

用户第一次登记扩展时，从模板创建 `<data-dir>/extensions.json`：

```json
{
  "schema_version": 1,
  "extensions": [
    {
      "id": "competitor-research",
      "type": "skill",
      "name": "数字产品竞品研究",
      "serves": ["competitor-analyst"],
      "use_when": "需要系统对比竞品的功能、定价和体验时",
      "how_to_invoke": "在当前宿主中调用 skill：digital-product-competitor-research",
      "data_boundary": "只传公开产品名称和对比维度，不传内部数据",
      "added_on": "2026-10-19"
    }
  ]
}
```

字段说明：

| 字段 | 说明 |
|---|---|
| `type` | 可选 `skill`、`agent-role`、`mcp`、`script`、`other` |
| `serves` | 这个扩展能替代或增强的内置角色，可以为空 |
| `type` 为 `agent-role` | 在 `how_to_invoke` 中写清楚角色的用途、输入和输出，格式同 [role.md](../templates/role.md) |

导师使用规则：

- **何时读取：**需要某个角色或工具时读取注册表。`serves` 与当前角色匹配、且 `use_when` 符合当前情况的扩展优先使用。
- **可用性：**只调用当前宿主里实际可用的扩展。不可用时告诉用户，改用内置角色。
- **数据边界：**遵守 `data_boundary`。调用外部工具前，先确认不会发出用户不愿意外传的数据。
- **新增登记：**用户说“以后竞品分析用 X”时，确认后写入注册表，并读回核对。

### 制品类任务的交接

用户只要一份制品（PRD、原型、流程图、简历等），而宿主里有更专门的制品类 skill 时，交给它做，本轮不启动成长记录。

- **登记：**用户说“以后写 PRD 用 X”时，确认后在注册表里加一条 `type: "skill"` 的扩展。`serves` 留空；`use_when` 写清制品类型和触发条件，例如“只需要交付 PRD 文档、不讨论其中的判断时”；`how_to_invoke` 写调用方式，例如“在当前宿主中调用 skill：<名称>”；`data_boundary` 写清能传哪些材料。写入后读回核对。
- **交接：**遇到只交付制品的请求时，先查注册表：
  - 有 `use_when` 匹配、且宿主里可用的扩展时，告诉用户交给它，只传这份制品需要的材料。
  - 没有登记、但宿主里明显有更专门的 skill 时，先问用户要不要交接。
  - 用户想在本技能里做，就照做。
- **回到导师模式：**制品做完，用户想讨论其中的判断（为什么这样设计、怎么应对评审）时，回到导师流程，照常记录。

## 贡献技能级扩展

只在用户明确授权维护 skill 时修改仓库：

1. 按模板写新文件，在对应的索引里登记一行。
2. ID 使用小写英文加短横线，不与现有 ID 重复。
3. 出处只写真实可查的资料；文件里不放个人案例或公司信息。
4. 运行测试。链接完整性测试会检查索引、ID 和文件是否一致。
5. 在 `BACKLOG.md` 记下这次变更。

## 从个人扩展升格为技能级

个人行业包或业务方法经过多次使用验证、并去除公司信息后，可以在维护任务中整理成技能级扩展。升格前需要得到用户同意。
