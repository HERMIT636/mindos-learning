# P5 修改前只读审计（2026-10-02）

基线：855bae5a5eea24473834936cfa877179e28df0b9，发布目录 Git 干净。根目录与发布目录采用同一原生 JavaScript 前端、Python HTTP 服务和 SQLite；无需引入新框架。

| 检查项 | 代码事实与接入决定 |
|---|---|
| GrowthTask | growth.py 的 growth_tasks 保存 goal/roadmap/capability、类型、目标课程、规则估时、状态和 metadata。P5 只引用，不覆写估时或状态。 |
| TodayPlan | GrowthService.dashboard 汇集当前阶段 ready/active、复习与课程；原算法按周预算 /5，最多三项。替换负载选择层，不更改 Gap 和任务生成。 |
| estimated_minutes | growth_policy.json 工程规则；保留 base，P5 返回个人运行时预测。 |
| Task start | task_action(start) 返回 route，写 active 与 started_at/week_reserved。这是任务入口而非计时；P5 仅附建议。 |
| Course entry | app.js openCourse → /api/course → loop/enter → renderCourse。打开不开始 P5；加显式开始按钮。 |
| Review entry | universe.js 的今日复习按钮 → 原 loop.check(review)。设置计时建议，须另点击开始。 |
| Authentic | authentic.js /api/courses/{id}/authentic，growth.startTask 可传目标上下文。P5 独立记录，提交不自动结束。 |
| Final | course-final.js 的原课程终局检测；计时不改变得分或 final gate。 |
| Cross-course | growth 的 atom/prior 路由调用 P3 verify 或 P0 diagnostic；计时只是观察。 |
| 时间字段 | P0 evidence 有 response_time_ms，P4 metadata 有 started_at；都不是用户会话 active/paused 耗时，不能挪用。 |
| 刷新恢复 | 当前 state 前端内存，课程/测验 SQLite 恢复；新增 P5 数据库 current 查询与显式恢复。 |
| 路由 | 单页原生 JS，通过 state.page、MindOSUniverse 切换；独立执行条，不另建聊天或重构布局。 |
| 迁移 | Storage.__init__ 顺序 migrate；新增三个独立表与幂等索引，无课程/目标 FK 避免永久删除被历史引用阻塞。 |
| 用户边界 | HTTP cookie _session；所有 P5 查询和关联校验限定同一用户；本地原型不视为生产多用户认证。 |
| 预算/截止 | P4 goal 保存 optional weekly budget、deadline；P5 只读分析，不自动修改目标/路线。 |
| Task completion | P4 evaluate 由能力缺口、P1 gate 判定；结束学习记录绝不调用完成写入。 |

会话计时基于用户主动开始/暂停/继续与页面存活检查点。检查点不读取窗口焦点、鼠标、键盘、系统软件活动；仅用于避免异常退出时间持续累加，不能证明用户一直专注。超过恢复阈值按最后检查点中断，允许继续、结束或修正。短暂刷新保留当前会话。异常长时段需确认，异常/中断/未完成样本不参与完整任务估时。

冻结 11 个文件 SHA-256 见 validation/learning-loop-p5-frozen.json。P5 不产生 LearningEvidence，不更新知识状态、个人知识档案、能力缺口或小测权重。
