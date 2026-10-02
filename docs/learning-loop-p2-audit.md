# Learning Loop P2 只读审计（2026-10-02）

基线 main `019cce7`，工作区无修改。审计依据为实际代码。

|检查项|当前实现与 P2 接入边界|
|---|---|
|LearningEvidence|evidence.py：课程、用户、原子、来源、结果、分数、信心、难度、提示、用时、误解、元数据、事件键；课程隔离、幂等追加。|
|project_evidence|learning_policy.json 已预留且权重为 0。复用 signal + shadow 元数据，不调用状态引擎。|
|transfer_test|quiz_evidence 把 final_transfer / transfer 映射到正式迁移证据；开放迁移不走此映射。|
|提交链|Storage.submit_quiz 在事务内校验，服务器答案评分 → LearningLoopService.submitted → 状态更新 → FinalAssessmentService.on_submit。P2 单独提交，不走选择题评分链。|
|终局题型|final_assessment.py：理解、应用、陌生情境选择题、延迟回忆；答案与 rubric 私有。|
|预测与结果|final.py 两张表；当前预测主要课程级，策略字段为 course-final-v1，知识策略在 state_json 内；结果只关联最近五个预测，需扩充而非新造预测表。|
|状态历史|KnowledgeStateEngine 唯一写入者；每次调用增加版本并写 history，即使零权重信号也可能改变版本。P2 禁止调用。|
|报告缓存|state_hash 包含课程结构、状态版本、误解、日期、计划和进度；shadow 不能更新这些字段。|
|结构化输出|ModelGateway._json 记录原始返回与解析诊断，严格对象；业务 schema 校验在服务层，再修订一次。|
|ATIE / Tutor|ContentGenerator 根据状态决定教学并验证 blocks；聊天保存会产生 tutor_interaction、更新状态版本。开放任务导师必须隔离该写入并持久化提示标记。|
|自由回答|已有追问、反馈和小测选择题，没有开放评估评分组件。|
|前端输入|原生 JS、textarea 和统一 api/action 辅助；在报告下新增独立组件，不引入 React。|
|执行环境|没有隔离的用户代码沙箱。P2 只收文本，绝不执行用户代码。|

## 实施决定

沿用 P0/P1 权重、阈值和正式迁移状态；评分失败保存回答、分数为空。开放评分与独立选择题分开统计。预测按真实知识策略版本分组，严格检查时间与 evidence_cursor。时间窗口只选最近独立结果；缓存游标增量处理新增证据，重复读取不重算。陌生性只声称文本与结构检查，不声称已证明语义陌生或模型评分有效。

## 审计后发现的明确问题

P1 结果关联只比较 evidence_cursor，未同时验证预测时间早于提交时间。P2 增加时间检查，保留 P1 原有选择题评分、报告规则和阈值。旧关联默认不作为有效校准观察；只有增量匹配重新校验的结果参与统计。
