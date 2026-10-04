# P9 最终自审

依据实际代码、自动化测试、浏览器与真实模型记录逐项检查。模型与浏览器验收使用临时合成数据，不证明一般教学效果。

## A–X 完成条件

|条件|结果与证据|
|---|---|
|A 创建 Mission|确认创建接口、项目编辑与浏览器创建流程。|
|B 分里程碑|审查草稿可新增、删除、编辑里程碑；确认后独立存表。|
|C 包含执行任务|审查可新增/删除/编辑任务，检查编号、前置顺序、必需交付。|
|D 记录实验|任务实验 metadata，实验假设/环境/变量/预期结果。|
|E 多次 Run|独立运行记录及递增 run_index，非服务器执行。|
|F 参数与指标|标量参数、有限指标；2–5 条同名指标比较。|
|G 保存产出|本地上传、owned 下载、有限预览、图片与 PDF 选页。|
|H 产出/材料分离|不同表与命名空间，显式 promote 才创建派生 P8。|
|I 版本化|parent_artifact_id/version，父版本删除保护。|
|J 复盘|用户填写并明确确认；可引用产出，删除时保留引用。|
|K 复用导师|QualityTutorService + 原策略/ATIE/ModelGateway，最多两次质量尝试。|
|L 复用计时|原 P5 goal_task；开始、暂停、结束仍使用原计时系统。|
|M 复用材料|已有 P8 引用与 renderer，无新学习资料库。|
|N P4 推荐|practice_missing 与 project/competition 目标建议；已有关联项目优先继续。|
|O 无新 mastery engine|P9 没有知识状态写入器、评分引擎或新能力分。|
|P 产出不直接变成证据|上传、点评、复盘测试保护知识状态与 evidence 表。|
|Q AIReview 非能力事实|只能保存候选观察，不自动 confirmed/verified。|
|R 经原 P2 验证|新独立 design/open_transfer；答案由用户提交、原 rubric 评估。|
|S 项目完成非目标达成|真实模型验收中的确定性场景与原 GoalCompletionAnalyzer 检查。|
|T 失败不降低知识状态|failed/abandoned 前后受保护表一致。|
|U 本地安全|共享 SafeFiles/P8 processing；格式/大小/编码/图片、路径与跨用户测试。|
|V 大产出有限上下文|每份 3,000、最多四份，整体实践上下文含编码开销 ≤10,000。|
|W 移动端|实际 Edge 1440/390 完整操作，未溢出；导师收起不覆盖输入。|
|X 全量回归|862 项（基线 726 + P9 136）及 20 组浏览器检查；结果见验证报告。|

## 25 项边界自审

|问题|回答|
|---|---|
|1 Mission 没有成为第二套 Course？|是；课程仅关联，P9 不生成章节、知识原子或课程内容。|
|2 Planner 没有虚假 mastery？|是；只读取已有状态/缺口，计划协议拒绝掌握字段。|
|3 completion 不自动 achieved？|是；没有写 learning_goals 状态，原 P4 分析仍负责判定。|
|4 Artifact 与 Resource 分离？|是；mission_artifacts 与 knowledge_resources，派生 ID 不相同。|
|5 Artifact 不自动产生 LearningEvidence？|是；P9 不调用 append。只有实际独立提交后原 P2 保存影子观察。|
|6 Experiment 不自动推断因果？|是；有限指标表与 min/max，机制解释不存为事实。|
|7 AI 原因表述为待验证假设？|是；导师提示与因果用语检查，真实 benchmark 场景通过。|
|8 Evidence 先 candidate？|是；user_artifact_claim，candidate 状态；点评无能力分。|
|9 进入原能力闭环必须 P2？|是；验证桥复用原陌生任务、hint 排除与校准规则，不自建结果。|
|10 failure 不降低 KnowledgeState？|是；失败/停止测试无状态或已确认误解变化。|
|11 P5 只记录时间？|是；明确开始、原时段记录，结束不完成任务。|
|12 P8 只作为材料引用？|是；task resource_ids，明确 promote 派生，不自动收集全部产出。|
|13 完整复用 P6/P6.5？|是；context adapter 置于原 QualityTutorService 循环内，原检查算法未改。|
|14 没有第二套 Tutor？|是；原课程聊天记录、浮动入口、模型配置与质量控制。|
|15 没有第二套 Assessment？|是；只调用 AuthenticAssessmentService，原 rubric 与结果语义。|
|16 没有第二套文件安全实现？|是；路径/排他写入/读取提取为共用 SafeFiles，识别与解码复用 P8；P9 只增加产出类型与引用生命周期规则。|
|17 大文件不整体进模型？|是；文件留本地，正文有限；二进制仅 metadata/hash，选页 PDF 不猜正文。|
|18 version lineage？|是；同项目、同类型、同任务验证父版本及删除引用。|
|19 可记录 Reflection？|是；用户文本、方向、关联与时间保存。|
|20 AI 草稿需要用户确认？|是；导师建议不能自动调用保存，保存接口 confirmed 必须为 true。|
|21 Desktop/Mobile？|是；1440/390 实际浏览器完整工作流。|
|22 P0–P8 回归？|是；自动化与旧页面回归，冻结 82 个核心中的 81 个原 SHA 不变。|
|23 明确项目完成≠掌握？|是；项目状态、统计、计时与确认完成用语均提示边界。|
|24 明确 Artifact≠Evidence？|是；产出与候选/独立验证分区，独立任务不含产出答案。|
|25 明确 AIReview≠AbilityFact？|是；模型辅助观察、待验证候选与原独立评分显示明确区分。|

唯一冻结例外是 P8 ResourceService 委托共用 SafeFiles。旧 P8 格式/资料语义未改；原有上传、安全与导师测试全部回归。其余接线在 server/storage/导航/请求边界，不更改知识状态、评分或成长规划算法。

当前限制：无关联课程的项目可执行和留存产出，但需关联真实课程/知识点才能用课程导师与 P2；没有伪课程、代码运行、比赛自动提交、OCR、图像理解或真实能力认证。项目实践效果仍需真实用户试用验证。
