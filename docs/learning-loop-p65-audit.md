# P6.5 接入审计

审计基线：`77b60c384722c1628ef022e33857ab059e2f008b`。修改前工作区干净，原有 407 项自动测试通过。以实际文件为准，未依据早期交接推断实现。

实际调用链是 `CourseAssistant → POST /api/tutor/chat → TutorService → TutorContextBuilder → ATIE / TutorStrategyEngine → ModelGateway.tutor_json → protocol.validate → TutorMemoryStore.save`。P6 已有两次生成机会；结构、教学范围、引用、苏格拉底单问题等检查已经存在，但没有单独的回答深度、近期重复、目标偏离和不确定表述检查。

需求同时要求增加质量层和冻结 P0–P6 算法，因此选择在服务器路由边界加入 `quality.api`，调用 `QualityTutorService`，把 `QualityControlledModel` 放入原有 `TutorService` 的生成循环。原有 P6 service/context/strategy/protocol/storage/observations/api 与 ModelGateway 文件均保持原 SHA。适配层使用同一个 ModelGateway 的 JSON 传输、密钥、超时和输出协议，没有第二个网络客户端、学习状态系统或质量裁判模型。原有格式检查和质量检查共用初次生成加一次重试，不能互相嵌套重试。

新增质量表只存策略、规则标记、重试次数、通过状态和时间，不存问题、上下文、被拒原始输出、能力分数或内部思考。原有对话及引用确认管道仅在格式、范围和质量全部通过后执行。失败回答仅在当前窗口展示；质量元数据保留用于开发排查。清除导师记录同时清除质量元数据，永久删除课程通过外键清除元数据，课程复制不复制它。

修改范围是新增质量模块、提示词、开发面板、测试和验证资料；服务器增加路由钩子与开发模式开关，Storage 注册新增表，前端原窗口增加一个开发模式渲染钩子。课程讲解与旧版助教兼容接口继续保留原有规则；P6.5 接入的是当前悬浮导师使用的 P6 对话接口。没有改写课程推进、小测、知识原子或来源生产流程。

55 个冻结文件见 [SHA 清单](learning-loop-p65-frozen.json)，覆盖已有 P0–P5/ATIE 41 个文件，加上 P6 算法、原提示词及 ModelGateway。回归测试还对真实数据库中的学习证据、知识状态、误区、任务、学习时间与个人档案逐表比较。
