# 学习闭环只读审计与兼容方案（2026-10-02）

修改前发布仓库 main 为 d0b27f9，工作区干净；根目录与发布目录 112 个文件一致。未修改个人数据库。

| 检查项 | 当前代码与结论 |
| --- | --- |
| 数据库与迁移 | storage.py：SQLite，启动时 CREATE IF NOT EXISTS / PRAGMA / ALTER，事务与课程所有权检查；新迁移沿用方式，不删除旧表。 |
| Course / Chapter / Lesson | courses → sections；一个 section 即一个教学小节，含 objective、purpose、core/related/future_atoms、难度、范围、lesson 与版本。无需重复建立 Chapter。 |
| KnowledgeAtom | knowledge.py：课程 graph_json 内 atoms，ID、所属小节、标题、类型、summary、why、depth，另有来源质量信息。 |
| KnowledgeGraph | graph_json 的 edges，prerequisite 为 from 前置 → to 后继；已有环路校验。复用，不建另一套图。 |
| 用户状态 | adaptive/teaching_state.py：读独立测验、反馈、偏好和教学动作；未知置信度保留空值。 |
| Quiz / Answer | quizzes：questions_json、服务器 answers_json、提交答案、分数、scope / target_atom_id；题目可有 atom_ids 与 assessment_type。无原子标记的旧题不能推断到整个章节的每个原子。 |
| AI导师 | course_tutor.py：可拖动悬浮入口，课程上下文、独立历史、搜索摘要、ATIE；目前不写掌握度。 |
| 讲解生成 | adaptive/content_generator.py：状态 → ATIE → ModelGateway → 内容与范围检查 → 保存；一次修订预算。 |
| 模型调用 | model.py：统一 ModelGateway，所有扩展继续经过此入口；密钥 SecretStore 加密。 |
| Prompt | model.py 与 teaching.py RULES；展示形式已允许模型选择，知识状态与展示策略继续分离。 |
| API | server.py：原生 HTTP 路由，课程、章节、小测、原子、助教；本机会话与课程校验。新增路由附加而不替换。 |
| 前端状态 | web/app.js + components/mindos/state.js，共享 state，异步响应有课程/小节保护；原生 JS，无需引入框架。 |
| mastery / progress | 章节近两次小测正确率、原子近两次标记题正确率与手动 current_ordinal；它们是旧兼容展示指标，不是状态向量。 |
| 复习 | knowledge_state() 以最后阅读/测试距今三天提醒；无有效记忆模型、无独立复习结果、无补救返回上下文。 |
| 删除/复制 | course_management.py：软删除保留历史，永久删除显式清表；复制不复制学习记录。新表须纳入永久清理。 |

## 兼容实现

增加 mindos/learning：统一证据、状态引擎、误区、前置补救、遗忘/调度与流程服务。先证据迁移，再状态回放，再误区/补救/复习/恢复，最后追加 UI。

旧 mastery、rate、progress 与 quiz result 保留为独立测验正确率和手动进度；新 knowledge_state 追加多维估计、置信度、有效记忆和可解释依据。历史题按实际 atom_ids / assessment_type 回放，未标注维度保持未知，不凭总体分数伪造迁移或延迟记忆。聊天、阅读、自查为零掌握权重信号；用户自报答题信心是证据属性，不等于系统置信度。

评分、证据、状态和日志在同一事务提交；AI诊断不影响选择题提交。选择题使用受校验的错误选项映射，开放题诊断仅产生候选，失败修订一次后跳过。补救与复习沿用 quizzes 和 ModelGateway；未配置或调用失败可复用已校验的历史题（明确标记），没有题源时保持可返回课程，不编造测验。

时间衰减只计算 effective 状态，不写坏长期 mastery。复习/补救/长时间返回均不会解锁未来章节。用户主动开始短检测；补救结束回到已保存课程/小节/知识点/阅读位置。未知前置仅建议诊断，不判作薄弱；循环、深度、尝试次数与冷却受集中策略约束。

P1 课程终局报告、跨课程复用、项目评估不扩展 UI；证据类型与后端协议预留。

## 实施后的核验

评分事务内写证据及状态，新增模块唯一写多维状态；ATIE 读取新状态与闭环上下文，自动前置补救由显式短任务承担，常规讲解仍保持当前小节范围。暂缓任务隐藏待答题并拒绝旧页面交卷；导师帮助持久标记为有提示，不能冒充独立延迟回忆。原分数／进度、课程隔离、软删除、复制和来源质量语义保留。实际自动化、浏览器与受控真实模型结果另见 [验证记录](validation/learning-loop-2026-10-02.json)。
