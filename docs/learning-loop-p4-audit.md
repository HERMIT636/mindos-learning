# P4 只读审计（2026-10-02）

实际基线 `9f01c592e6d1e2b2f4dcdc79d425c6426564c3aa`，发布仓库 main 无未提交修改。先核查代码，未依据需求文档推断已有实现。

|检查项|实际情况与 P4 接入|
|---|---|
|长期目标|尚无用户级长期目标，新增独立 Goal 与版本化能力草稿。|
|Course goal|课程内部文本 goal；保持原义，不复用为长期目标数据库。|
|课程创建|ModelGateway.plan_course_review → save_draft → 用户确认；成长建议仍进入该流程。|
|Personal Profile API|P3 profile 支持筛选与调试；默认读取会刷新缓存。P4 使用批量只读输入和原 P3 compute，不写该缓存。|
|Canonical|用户所属，语义 fingerprint、别名、领域、类型与重定向；引用时校验归属及有效性。|
|Course Manager|原生 JS 与 SQLite；active/paused/completed/archived、软删除、复制。|
|驾驶舱建议|DashboardService 是只读投影，课程规则与今日复习已有。最小增加成长建议入口。|
|ReviewScheduler|state.py 中现有 queue 与 ForgettingService.project；复用，不新增复习算法。|
|Final recommendations|P1 状态与掌握报告缓存；内容完成不同于 mastered，路线不能跳过 Final。|
|P3 prior|独立教学先验，不是掌握证据。路线验证任务进入已有原子详情。|
|偏好|teaching_preferences 保存课程 math_level/styles，反馈独立于掌握；不当作能力证明。|
|学习时间|当前没有用户长期每周预算；P4 增加可选预算，不改变课程教学偏好。|
|课程状态|已有四状态与 deleted_at；回收站／永久删除使任务阻塞，复制不带路线关联。|
|草稿确认|课程大纲审查确认已存在；新增能力草稿审查也需确认，旧路线保留。|
|ModelGateway|统一 JSON 输出与诊断日志，密钥加密本机保存；P4 通过同一 Gateway 并严格校验／最多修复一次。|
|Search Provider|免密钥 Wikipedia/GitHub 有限检索与 Brave/Tavily 可选；P4 第一版不依赖联网搜索。|
|课程资料|SourceDocument、生产候选审查、来源策略保留；P4 仅提供范围建议，不造新来源或认证。|

冻结 P0 state/policy、P1 course_mastery/final_policy、P2 calibration/policy、P3 personal.py/personal_knowledge_policy 与 canonical.py；P4 不写 LearningEvidence、KnowledgeState 或 Personal Profile。UI 保持课程星图，不添加全局知识网。工程路线建议不代表最优教育路径或职业资格认证。
