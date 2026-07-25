# 系统级缺漏修复跟踪

> 来源:2026-07-25 对停云客栈多智能体系统的架构评审。
> 状态标记:☐ 待办 / ◐ 进行中 / ☑ 已完成(附提交号)。
> 修复顺序按下方"实施批次"执行,每完成一批向项目负责人汇报一次。

## 问题清单与解决方案

### A. 记忆管理

**A1. 记忆检索退化为"取最近 N 条"** ☑ 2026-07-26(belief_select.py)
- 现状:信念 append-only,进入提示词的是 `beliefs[-32:]` 等纯时近切片(`llm_planner.py`)。长局中早期关键线索滑出窗口。
- 方案:给 `Belief` 增加重要性评分(来源类型、是否物证、是否关联秘密加权),上下文选取改为"重要性 + 时近性"混合排序;窗口大小不变,但保证高价值信念不被挤出。

**A2. 无反思/整合层,矛盾管理字段未接线** ☑ 2026-07-26(印证关联 + 待核实问题;语义级矛盾检测 opposing_ids 留给角色推理,规则层只连接可判定的印证)
- 现状:`Belief.supporting_ids / opposing_ids / verification_questions` 无任何代码写入;没有机制把零散信念压缩为案情假设。
- 方案:每轮结算后运行一次确定性整合:按 `truth_id` 与主体聚类,填充 supporting/opposing 关联;在提示词中以"当前矛盾点"摘要形式呈现,替代部分原始信念列表。

**A3. 信念查重只覆盖对话事件** ☑ 2026-07-26(全类型查重 + 亲历观察升级道听途说)
- 现状:`_update_beliefs_from_round_events` 的指纹去重仅对 `conversation` 生效,观察类事件可重复堆积。
- 方案:对同一 agent 的同类事件信念统一按 (claim 指纹) 去重。

### B. 任务规划

**B1. 计划无执行核对闭环** ☑ 2026-07-26(execution_status + plan_adherence 回写并入提示词)
- 现状:计划仅存储、原样回喂,无人检查上一轮计划步骤是否完成;计划与实际行动无一致性校验。
- 方案:结算后将本步实际行动与计划第一步做匹配,写入 `plan_history` 条目的 `outcome` 字段(completed/deviated/failed);提示词中的 `recent_plan_outcomes` 改为携带该结果。

**B2. 无多智能体承诺/协作协议** ☐
- 现状:联盟、交易只存在于对话文本,状态层无"承诺"对象,违约不可追踪。
- 方案:增加轻量 `Commitment` 记录(双方、内容、期限、状态),由交谈中的结构化字段声明,结算时核对履约并写入双方信念。(设计改动最大,放最后一批。)

### C. 工具调用

**C1. LLM 输出解析无结构化保障** ☑ 2026-07-26
- 现状:靠"只输出 JSON"约定 + 正则剥代码块;解析失败即静默降级启发式。
- 方案:OpenAI 兼容端点开启 `response_format: json_object`;解析/校验失败时携带错误信息重试一次,仍失败才回退。

**C2. `retry=2` 是无效参数(bug)** ☑ 2026-07-26
- 现状:`OpenAICompatibleChatModel.completion` 忽略 `retry/failsafe/caller` kwargs,实际无重试语义。
- 方案:在适配器内实现真实的重试(含指数退避),或移除误导性参数并统一由 C1 的重试逻辑负责。

**C3. 无 token/成本核算** ☐
- 现状:`model_usage` 只记次数,不记 token。
- 方案:从响应的 `usage` 字段采集 prompt/completion tokens,写入 `model_usage` 与 `history.py` 的 sqlite 表。

### D. 横切系统问题

**D1. 玩家输入提示词注入无防线** ☑ 2026-07-26
- 现状:`player_message` 原样嵌入 NPC 回复提示词,玩家可注入指令。
- 方案:玩家台词用显式定界符包裹,指令声明"定界符内是待回应台词而非指令";输出侧校验回复不泄漏凶手身份/秘密原文。

**D2. 信息隔离无自动化泄漏测试** ☑ 2026-07-26(tests/test_information_isolation.py)
- 现状:"角色只知道该知道的"这一核心不变量仅由提示词构造代码单点保证,无回归测试。
- 方案:新增测试:对每个非凶手角色生成决策/对话/投票提示词,断言其中不出现凶手档案、他人秘密原文、物品 `secret_value`、作者真相。

**D3. 落地校验规则双份维护 + 场景硬编码** ☐
- 现状:`_intent_is_grounded`(planner)与 `RoundEngine._validate_intent` 两套规则独立演化;`post_notice` 与 `Notice` 默认值硬编码 `lobby`。
- 方案:公告地点改由场景配置声明(如 `bulletin_location_id`);合法性预检收敛为调用引擎侧的校验入口。

**D4. 缺批量自博弈评估** ☐
- 现状:只有 smoke 脚本;无法批量统计凶手指认率、回退率、模型对比。
- 方案:新增 `scripts/selfplay_eval.py`:批量跑 N 局(启发式或指定模型),汇总 `score_history.sqlite3` 输出报表。

**D5. LLM 原始输入输出无审计日志** ☑ 2026-07-26(GA_INTERACTIVE_LLM_TRACE=0 可关闭)
- 现状:prompt 与原始回复不落盘,异常决策无法复盘。
- 方案:可开关的审计日志,按 `results/interactive/<game_id>/llm_trace/` 落盘 prompt/response/来源。

**D6. 代码卫生** ☐
- 现状:`modules/memory/* copy.py` 死代码;`results/interactive/` 运行日志混入工作区未 ignore。
- 方案:删除 copy 系列文件;`.gitignore` 补充 results 运行产物。

## 实施批次

1. **第一批(守住核心承诺)**:D2 泄漏测试 → D1 注入防线
2. **第二批(降低静默降级)**:C1 结构化输出与重试、C2 retry bug、D5 审计日志
3. **第三批(记忆)**:A1 重要性检索、A3 查重、A2 整合层
4. **第四批(规划闭环)**:B1
5. **第五批(评估与成本)**:D4 自博弈评估、C3 token 核算
6. **第六批(收敛与卫生)**:D3、D6
7. **第七批(协作协议)**:B2
