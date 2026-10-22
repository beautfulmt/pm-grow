# 解题层：问题场景路由

导师按用户的问题类型调用场景文件。每个场景给出本类问题的补问顺序、推导路径、可用方法卡、阶段差异、检查点反问和交付物。通用的上下文补齐与第一性原理规则见 [reasoning](../reference/reasoning.md)；反问、check_back 和成长告知的通用规则见 [feedback-and-reports](../growth/feedback-and-reports.md)；各阶段的锚点见 [stages](../growth/stages.md)。

## 使用方式

1. 从用户原话和已有背景识别场景，命中后只读对应的场景文件。
2. 场景里的方法卡和行业包按"何时用"按需读取，一次读当前推导需要的一两张。
3. 一个问题命中多个场景时，按下方的优先顺序选一个主场景，其余作为辅场景，只借用其中相关的一节。
4. 没有命中任何场景时，按 reasoning 的通用流程处理；同类问题反复出现时，记为维护线索，以后补成新场景。
5. 场景文件是写给导师的参考。回答用户时结论先行、先解决真实问题，不逐节复述场景内容。

## 路由表

| 用户的典型说法 / 信号 | 主场景 |
|---|---|
| "老板/客户要做 X""竞品上了 Y，要不要跟""运营提了个需求让我排"；需求以方案形式出现 | [feature-request](feature-request.md) |
| "某指标掉了/涨了，查一下原因""留存连续下滑""GMV 没达标"；一个数字 + 一段时间 + 为什么 | [metric-anomaly](metric-anomaly.md) |
| "帮我看看方案""下周评审怎么准备""PRD 怎么写""评审被怼了"；手里有方案或评审时间点 | [solution-review](solution-review.md) |
| "需求太多排不过来""两个老板都要先做自己的""OKR/路线图怎么写"；资源冲突或规划节点 | [prioritization-planning](prioritization-planning.md) |
| "这个功能没人用，想下掉""老系统要下线迁移""要砍掉一条产品线""两个功能想合并"；做减法、腾资源，有人仍在依赖 | [feature-sunset](feature-sunset.md) |
| "要延期了""依赖方不给排期""bug 太多还上不上""日期定死了"；时间、依赖与质量压力 | [delivery-risk](delivery-risk.md) |
| "研发说做不了""和设计意见不一致""怎么跟老板汇报""要人要不到"；需要别人做出行动 | [alignment-communication](alignment-communication.md) |
| "访谈怎么设计""一堆反馈不知道怎么分析""用户到底要什么"；已有或准备收集用户原声 | [user-research](user-research.md) |
| "增长从哪下手""冷启动怎么做""让我负责一个新业务""做个 MVP 验证"；不确定性高、缺基线 | [growth-new-business](growth-new-business.md) |
| "做个竞品分析""市场有多大""我们比竞品强在哪""要不要进这个市场"；外部对比与判断 | [competitive-market](competitive-market.md) |
| "上线了效果怎么样""A/B 结果显著吗""要写复盘"；有上线事实，需要下结论或总结 | [launch-review](launch-review.md) |
| "线上出问题了""客诉突然暴涨""用户被多扣了钱""有人看到了别人的信息""事故过去了要写复盘"；影响正在发生或刚发生，涉及故障、资金、数据或安全 | [incident-response](incident-response.md) |
| "刚入职/转岗不知道从哪开始""接手了老系统""业务术语听不懂"；进入陌生领域 | [onboarding-new-domain](onboarding-new-domain.md) |
| "要述职了""想晋升差在哪""要不要转 AI/转管理""感觉没成长"；问题指向用户自己的发展 | [career-growth](career-growth.md) |

## 多场景命中时的优先顺序

总原则：先处理决定"问题是什么"的场景，再处理"值不值""怎么做""怎么推进""怎么说"的场景。线上事故、明天就要评审或汇报这类紧急情况，先保住当下，再回到问题本身。

紧急情况优先：线上事故和客诉集中爆发直接用 incident-response，先止损、再同步，影响正在发生时排在一切场景之前。影响停下来之后，用 launch-review 的复盘结构和 [retrospective](../knowledge/methods/retrospective.md) 方法卡复盘，改进项写进 incident-response 的回访里跟踪。

默认顺序：

1. 诊断事实：metric-anomaly、user-research
2. 判断值不值：feature-request、feature-sunset、competitive-market、growth-new-business
3. 取舍与规划：prioritization-planning
4. 设计方案：solution-review
5. 推进与交付：delivery-risk、launch-review
6. 沟通与对齐：alignment-communication

feature-sunset 判断的是反方向的"值不值"：一个已有功能还值不值得继续投入。定下来之后，执行借用 delivery-risk 场景和 [launch-rollout](../knowledge/methods/launch-rollout.md) 方法卡的分阶段做法，释放出的资源回到 prioritization-planning 排序。

onboarding-new-domain 和 career-growth 关注"人"，可以和上面任何一个场景并行：先解决眼前任务，同时用它们的视角安排上手或发展。

常见组合：

| 组合 | 主场景 → 辅场景 | 理由 |
|---|---|---|
| 指标掉了，老板想做某个功能来救 | metric-anomaly → feature-request | 功能是否对症，取决于诊断结果 |
| 老板要做的功能挤占了已有排期 | feature-request → prioritization-planning | 先判断值不值、做多大，再谈挤掉谁 |
| 竞品上线新功能，老板问要不要跟 | feature-request，借 competitive-market 的"替代方案"和"竞品为什么这样做" | 最终要落到做不做；分析服务于这个决定 |
| 评审时研发说做不了 | solution-review → alignment-communication | 先看方案和约束本身；方案没有争议、只是资源不给时，直接用 alignment-communication |
| 项目要延期，需要向老板汇报 | delivery-risk → alignment-communication | 先理清选项和代价，再组织汇报 |
| 上线后数据没变化或下降 | 自己上线的改动用 launch-review；原因不明的整体波动用 metric-anomaly | 有明确改动和目标时评估效果；原因不明时先诊断 |
| 用户反馈说想要某功能 | user-research → feature-request | 先还原反馈背后的任务，再判断需求 |
| 从零规划一个新业务 | growth-new-business → prioritization-planning | 先找最危险的假设，规划围绕验证节奏展开 |
| 新人接手后的第一个需求 | 需求对应的场景为主，onboarding-new-domain 补业务地图 | 用真实任务带动上手 |
| 晋升答辩时被评委挑战 | career-growth → solution-review 的"应对挑战"分类 | 场合是个人发展，答辩技巧借用评审 |
| 上线后出了事故 | incident-response → launch-review | 先止损、恢复和善后；影响停下来后，再评估这次上线并按复盘结构总结 |
| 客诉集中爆发，老板问要不要改功能 | incident-response → user-research | 先止住影响、统一客服口径；再从工单原话还原用户任务，确实要改功能时转 feature-request |
| 想下线一个功能，但有大客户在用 | feature-sunset → alignment-communication | 先算清依赖、合同和替代方案；方案定了再准备和客户、销售的沟通 |
| 下线旧系统，要把用户迁到新系统 | feature-sunset → delivery-risk | 先定下线范围和迁移路径；新旧并行期、依赖和日期风险按交付风险管理 |

## 场景的共同约定

- **补问**：每轮最多问 1–2 项，从场景"必须补的上下文"表中由上往下挑尚未知道的一项；用户答不上来时，给条件性判断和取证动作，不补造数值或公司规则。
- **检查点**：三个标准检查点（问题定义后、选定方案后、行动或上线后）按场景里的具体问法提问；简单问题可以合成一句。
- **回访**：给出方案或约定行动时，把场景建议的回访写进 `problem.check_back`：回访时机（日期或条件）加要问的问题。
- **阶段**：按用户在这项能力上的阶段选择场景里对应的关注点，同一个人的不同能力可以处在不同阶段。
- **能力**：frontmatter 的 `abilities` 是本场景常观察的能力，实际记录以用户本次真正做出的行为为准。

## 扩展

新增场景时复制 [templates/playbook.md](../templates/playbook.md)，ID 用英文 kebab-case，frontmatter 只引用已有的方法卡 ID、能力 ID 和阶段 ID，然后在上面的路由表加一行，必要时补充组合规则。
