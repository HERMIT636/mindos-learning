# P6 实施前审查

基线：704e62c，工作区干净。以当前代码为准。

现有调用：CourseAssistant → /api/courses/{id}/assistant/chat → CourseTutorService → ContentGenerator.prepare → ATIE → ModelGateway → assistant_message。

问题：保存所有问答；上下文包含整门课结构与宽泛历史；prepare 会刷新继承先验和教学反馈；结构检查失败停止回答；只有悬浮按钮可拖动。

实施：新增 tutor 交互层，复用唯一 ModelGateway、只读 LearningStateManager / TeachingOrchestrator / ATIE、真实搜索入口及 P0 检测接口。每次裁剪课程内相关上下文，不持久化完整模型输入。重要问答限量保存；偏好与候选观察独立保存。旧助教接口保留兼容，前端切换 P6；不导入旧全部聊天作为新上下文。

冻结：learning 全部既有算法及 policy、adaptive 全部算法、teaching.py 的 SHA-256。仅修改存储迁移、网关扩展、服务器接线及 UI；新增 P6 模块。疑似误区不能写入 learning_evidence / knowledge_states。导师求助仅标记已有待答检测的非独立性；必须通过原检测提交才能产生答题证据。读取 P5 时段直接只读，不触发恢复、计时或完成任务。

最终验证：两个目录各 407 项（原有 353 + P6 新增 54）全部通过；11 组浏览器流程通过，最终边界调整后重跑 tutor_p6/tutor/authentic/final 通过；3 组真实模型问答与 9 项检查通过。首次基线 PDF 测试缺临时依赖，补齐后通过。41 文件 SHA 保持，个人数据库验证前后保持。详细记录见 validation/learning-loop-p6-validation.json。
