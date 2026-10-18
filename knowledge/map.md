# 知识地图

从当前问题挑一张主力方法卡，再按[行业适配](industry-adaptation.md)读取会改变判断的行业包。方法是推理工具，用户的事实、任务和约束决定怎样使用。

## 按问题选方法

| 当前卡点 | 首选 | 需要时再读 |
|---|---|---|
| 只有功能要求，不清楚真实问题 | [问题界定](methods/problem-framing.md) | [待办任务](methods/jtbd.md)、[用户访谈](methods/user-interview.md) |
| 指标变化，不知道原因 | [指标诊断](methods/metric-diagnosis.md) | [漏斗](methods/funnel.md)、[同期群](methods/retention-cohort.md) |
| 有方案，需要判断是否值得做 | [四大风险](methods/four-risks.md) | [投入论证](methods/investment-case.md)、[单位经济](methods/unit-economics.md) |
| 资源不够、需求冲突 | [优先级](methods/prioritization.md) | [路线图](methods/roadmap-okr.md)、[战略选择](methods/strategy-choice.md) |
| 方案落不细、交接容易出错 | [流程与状态](methods/flow-state.md) | [用户故事](methods/user-story.md)、[PRD](methods/prd-writing.md) |
| 评审受阻、各方意见冲突 | [相关方地图](methods/stakeholder-map.md) | [评审答辩](methods/review-defense.md)、[结构化表达](methods/structured-communication.md) |
| 上线和结果验证 | [发布灰度](methods/launch-rollout.md) | [A/B 实验](methods/ab-test.md)、[复盘](methods/retrospective.md) |
| 专家做深或负责人带团队 | [领域建模](methods/domain-modeling.md) | [团队培养](methods/team-development.md)，按本人路线选择 |

## 通用方法卡

主能力用于索引，不能因调用了方法就判断用户具备对应能力。阶段用法和前提见各卡正文，能力定义见[能力模型](../growth/abilities.md)。

| 主能力 | 方法 | 帮助完成的判断或产物 |
|---|---|---|
| user_problem | [问题界定](methods/problem-framing.md) | 从功能要求还原问题与验证方式 |
| user_problem | [待办任务](methods/jtbd.md) | 明确用户在场景中要取得的进展 |
| user_problem | [用户访谈](methods/user-interview.md) | 从真实行为取得证据 |
| user_problem | [用户旅程与服务蓝图](methods/journey-map.md) | 找到跨角色交接与服务断点 |
| user_problem | [机会解决方案树](methods/opportunity-tree.md) | 分开目标、机会、方案和假设 |
| business_value | [商业模式画布](methods/business-model.md) | 说明价值交换与经营条件 |
| business_value | [单位经济模型](methods/unit-economics.md) | 核对收益、成本和计量单位 |
| business_value | [四大风险](methods/four-risks.md) | 检查价值、可用性、可行性和经营风险 |
| business_value | [投入论证](methods/investment-case.md) | 比较选项、代价与证据强弱 |
| solution_design | [用户故事与验收](methods/user-story.md) | 将任务与异常写成可验收条件 |
| solution_design | [流程与状态](methods/flow-state.md) | 还原动作、状态、权限与异常 |
| solution_design | [MVP 切片](methods/mvp-slicing.md) | 用最小范围验证关键假设 |
| solution_design | [PRD 写作](methods/prd-writing.md) | 形成支持协作的需求说明 |
| data_validation | [指标树](methods/metric-tree.md) | 连接目标、输入与护栏 |
| data_validation | [漏斗分析](methods/funnel.md) | 在同口径链路中定位流失 |
| data_validation | [同期群分析](methods/retention-cohort.md) | 对齐进入时间与行为周期 |
| data_validation | [指标异动诊断](methods/metric-diagnosis.md) | 排除数据错误并比较解释 |
| data_validation | [A/B 实验](methods/ab-test.md) | 用合适的对照设计检验假设 |
| strategy_prioritization | [优先级排序](methods/prioritization.md) | 结合目标、证据、成本和依赖比较需求 |
| strategy_prioritization | [路线图与 OKR](methods/roadmap-okr.md) | 将目标、验证和推进顺序连接起来 |
| strategy_prioritization | [竞品与市场分析](methods/competitive-analysis.md) | 从证据解释竞争选择及迁移条件 |
| strategy_prioritization | [战略选择](methods/strategy-choice.md) | 说明取舍与放弃的机会 |
| delivery_risk | [风险清单与预案](methods/risk-register.md) | 明确触发信号、负责人和应对 |
| delivery_risk | [发布与灰度](methods/launch-rollout.md) | 设定验证、停止与回退条件 |
| communication_influence | [结构化表达](methods/structured-communication.md) | 让结论、证据和请求相互对应 |
| communication_influence | [相关方地图](methods/stakeholder-map.md) | 确认目标、权限与决策关系 |
| communication_influence | [向上管理](methods/managing-up.md) | 对齐决策请求、风险和信息节奏 |
| communication_influence | [方案评审与答辩](methods/review-defense.md) | 把质疑还原为待验证的顾虑 |
| learning_transfer | [复盘](methods/retrospective.md) | 比较预期与实际并修正判断 |
| domain_expertise | [领域建模](methods/domain-modeling.md) | 提炼可验证的领域概念与方法 |
| team_leadership | [团队培养](methods/team-development.md) | 分配决策权、支持和反馈 |

## 行业包

| 包 | 选择条件 |
|---|---|
| [教育](industries/education.md) | 学习、教学与教育交付 |
| [企业服务 SaaS](industries/saas.md) | 企业采购、实施、使用与续约 |
| [中后台与内部系统](industries/internal-platform.md) | 组织内部任务、权限与流程 |
| [内容、社区与社交](industries/content-community.md) | 内容供给、关系与治理 |
| [电商与零售](industries/ecommerce.md) | 商品、交易、履约与售后 |
| [本地生活与出行](industries/local-services.md) | 本地供需、匹配与线下服务 |
| [金融科技](industries/fintech.md) | 资金、金融服务与风险反馈 |
| [医疗健康](industries/healthcare.md) | 健康服务、临床边界与专业工作流 |
| [游戏](industries/gaming.md) | 核心体验、进程、经济与内容运营 |
| [硬件、IoT 与工业制造](industries/hardware-iot.md) | 实体交付、设备与现场生命周期 |
| [广告与商业化](industries/ads-monetization.md) | 流量、预算、效果与结算 |
| [AI 产品](industries/ai-product.md) | 叠加层：模型输出、评测与自动执行 |

## 维护

新增方法时沿用[方法卡模板](../templates/method-card.md)，声明已有或已注册的能力 ID 与适用阶段，并在本表登记。新增行业时沿用[行业包模板](../templates/industry-pack.md)，注明覆盖范围和取证方向。个人方法与行业条件保留在个人数据目录，升格为共享资料按[扩展机制](../reference/extensions.md)处理。
