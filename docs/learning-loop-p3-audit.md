# P3 只读审计（2026-10-02）

基线 `123045b`，Git 工作区干净。先核查实际文件，再实施。

|检查|实际实现与接入边界|
|---|---|
|课程原子／graph_json|knowledge.py 校验 id、title、type、summary、why、depth、来源、质量；course_graphs 按课程保存 JSON。原子 ID 仅课程内唯一，不能作为用户全局身份。|
|原子生成|模型规划 ID、complete_index 的随机索引 ID、生产导入的随机 ID；必须用 user/course/atom 联合定位。|
|关系与教学范围|prerequisite 是课程原子关系；sections 保存 core/related/future 元数据，TeachingOrchestrator 控制范围，不创建第二套课程图。|
|知识索引生成|手动 build、complete_index、production.import、save_graph；在索引保存后有限自动扫描，失败不阻塞课程使用。|
|课程需求与规划|Discovery 先需求／缺口分析，课程审查 plan_course_review；加入相关历史概念摘要，不能移除关键章节。|
|状态读取|knowledge_states 按 user/course/atom 查询，KnowledgeStateEngine 是唯一写入者，P3 不改其计算与权重。|
|P2 校准|CalibrationService 按用户课程和版本缓存、独立 MCQ 与 shadow 分开；Profile 只读独立校准，证据不足不惩罚。|
|ATIE|LearningStateManager.read → ATIE.decide → blocks；先验独立字段，不填入 cognitive_state 的分数。|
|Tutor|当前课程／原子上下文与 P2 检测隔离；只增加当前主题相关先验，不发送整个长期档案。|
|删除与复制|软删除保留原始数据；永久删除显式依赖表顺序；复制只复制结构，不复制状态，需要重新映射。|
|数据库迁移|Storage 初始化时逐模块 migrate，SQLite 事务与部分唯一索引；新增用户级实体和映射历史。|
|用户隔离|本地 session_id 标识用户，课程所有权检查；Canonical/Profile/Prior 必须均携带 user_id，不跨用户共享。|
|快速验证|LearningLoopService.assessment 已有 diagnostic，模型校验且历史 fallback 标 reused；复用 quizzes 与 submit，新增元数据，不新增评分引擎。|
|界面|原生 JS，课程星图和原子详情；新增小型个人知识档案及原子关联提示，不增加全局图谱。|

冻结 state.py、learning_policy.json、course_mastery.py、final_policy.json、CalibrationAnalyzer 与 calibration_policy.json。新增配置是工程规则，语义匹配不是事实认证，先验不是新课程掌握证明。
