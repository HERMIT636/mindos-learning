# Learning Loop P1 只读审计（2026-10-02）

审计先于业务代码修改。当前发布仓库 main 为 `e446f5a9dec2679b627041c63565052422af5b22`，工作区干净，根目录与发布目录 132 个源码／文档文件一致。未读取或改写个人课程内容。无 AGENTS.md。

| 检查项 | 当前实现与适配结论 |
| --- | --- |
| Course 完成状态 | course_management.py 中 status=active/paused/completed/archived 是用户管理标签，可以直接设置；不能用作掌握判断。 |
| current_ordinal / 小节完成 | storage.advance() 仅手动推进，当前小节需已有讲解；_course_card() 统计进入后续小节、提交章节小测、读完小节所有原子。最后一节无独立完成记录；无图谱时阅读标记不能完整表达内容完成。追加内容完成确认及版本，不改变章节推进。 |
| Quiz 与闭环 | quizzes 存题目、服务器答案、提交结果；assessment_kind / scope / target_atom_id / loop_session_id 已支持短任务。submit_quiz() 在事务内评分→证据→状态；终局继续复用。 |
| transfer_test | /loop/assessment purpose=transfer 生成两道单选，字段严格校验，写 transfer_test；没有课程旧题／讲解的陌生性检查。P1 增加结构化场景、rubric 和重复检查；第一版选择题服务器评分，不扩大开放题评分。 |
| project_evidence | learning_policy.json 预留零权重类型，无项目评分 UI；本次不扩展。 |
| KnowledgeState 接口 | GET /loop 批量读取已存状态及时间投影；GET /loop/state 提供依据。唯一写入为 KnowledgeStateEngine；不重写引擎，不改变 weighted-evidence-v1。 |
| 原子重要性 | 原子含 section/type/depth，无重要度；sections.core_atoms 和 prerequisite 边可推导课程规划中的 criticality，不修改生产模型。 |
| summary / report | 有章节成绩、成长时间线，无课程掌握报告／快照。增加程序生成的报告和按状态版本缓存的解释。 |
| 首页／课程完成展示 | 首页课程卡显示管理标签与进度；最后一节隐藏下一节按钮，仅说明由用户推进。增补内容完成／待检测／补强／带缺口结束标签与连续检测入口。 |
| Course Management 数据 | SQLite courses 元信息 + sections；原生 JS，不需要新框架。管理 completed 与课程 mastery 独立。 |
| 软删除／复制 | 软删除保留记录，永久删除显式清表；复制课程保留结构与资料，讲解重置且不复制学习历史。沿用，不复制终局数据，新表纳入永久删除。 |
| ATIE whole-course context | LearningStateManager 读取当前和此前知识与课程 loop，常规教学受当前小节范围约束。终局 Planner/Analyzer 批量读全课程；Tutor 增加 final 上下文与求助标记，补强继续走单目标 ATIE，不放宽正常小节范围。 |

## 拟定兼容边界

- 增量迁移：内容完成确认、终局规划及会话状态、课程掌握快照、报告、补强编排、预测及后续结果关联；不另造原子、图谱、题目或证据系统。
- 单选终局覆盖理解、应用及陌生情境迁移，按题目真实类型写 P0 证据。无题源／无合格迁移题时标为不可检测，不记错误或伪造分数；长期记忆沿用独立延迟回忆与现有复习调度。
- 限量确定性抽样，兼顾关键依赖、薄弱、混淆、证据不足与稳定核心，不随机全考。最多两个阶段。
- 判断同时检查综合分、系统置信度、关键原子下限、迁移覆盖与独立终局结果；未知维度保持空值。用户可暂缓或带缺口结束。
- 终局补强只增加课程级编排，复用 P0 repair_start / repair_content / assessment，并做 targeted reassessment 后重新分析。
- BEGIN IMMEDIATE、任务所有权、状态及课程版本复查，防止重复 active plan、双击生成、暂缓后旧页交卷和模型生成期间版本变更。
- 报告底层与推荐由程序生成；模型仅解释已经给出的结构化结论，不得修改分数与状态。读报告不调用模型。
- 预测快照只记录规则判断及后续实际答题关联，不训练或自动改参数。保留当前 history 写法，测试增长与批量读取，不做事件溯源重构。
