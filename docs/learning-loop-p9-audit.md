# P9 实施前审计

基线：9877ab6；发布仓库 main 干净。项目根目录不含 Git；发布目录负责提交。

|检查项|实际接口与结论|
|---|---|
|P4 Goal/Task|learning_goals、growth_tasks；GrowthService.goal/gaps/roadmap。P9 读取并推荐，不替代规划与完成分析。|
|P2 Task/Result|authentic_tasks/results；AuthenticAssessmentService.start/get/submit；四种任务，无 artifact_review。采用 design/open_transfer；独立提交会保存原有 project_evidence 影子记录并满足原校准规则；模型评分不直接写课程掌握。|
|P5 StudySession|StudySessionService.start/action；goal_task 可无课程；只记录主动计时，结束不完成任务。P9 仅记录 session ID，不改 policy。|
|P8 Resource|ResourceService，与知识点多对多；P9 产出独立表，显式派生才进入 P8。|
|上传与本地存储|P8 identify/validate_image/extract_pdf 具备大小、编码、图片验证；固定 ID 路径与哈希。提取共用 SafeFiles 路径与写入边界，复用处理器。|
|课程所有权|_knowledge_course/_manage_owned/atom(unlocked=True)；删除与回收站课程不能作为新的执行上下文。|
|Tutor Context|P6 需要真实课程上下文；任务先关联已有课程再用同一浮动导师，不生成伪课程。P9 context 适配器接入原质量循环。|
|ModelGateway|统一 _json/加密模型配置；P9 不建新传输或密钥存储。|
|已有项目/任务表|已有 growth_tasks/authentic_tasks，不是 Mission；新增七张实践表。|
|数据库迁移|Storage 初始化时 migrate；使用幂等新增表，无既有状态重写。|
|哈希/所有权|资源 content_hash；P9 使用同一 digest 与共用安全文件命名，所有访问须先验证 mission/user。|
|Course/Goal 生命周期|回收站及目标删除导致关联不再可用；P9 保留历史 ID 标签，不级联丢失产出。|
|路由|server GET/POST/PATCH/DELETE 边界分发；新增 mission dispatcher 与静态白名单。|
|Dashboard|universe.js 驾驶舱实际课程/成长数据显示；添加当前实践入口，不混入知识星图。|
|GrowthToday|study.js 今日安排原算法最多三项；增加独立实践建议栏最多三项，不改原排序算法。|
|实践入口|authentic.js 原独立任务 UI 与 P2 API 可复用；P9 保留独立作答，不直接评估上传产出成为能力。|

冻结 P0–P8 核心的原始 SHA 见 learning-loop-p9-frozen.json。唯一预定核心例外是 P8 文件路径与写入代码委托共用助手，行为由既有 P8 测试复核。其余变动为 server、storage、页面导航与导师请求的接线。
