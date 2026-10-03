observations 只是候选：possible_misconception/possible_gap/strong_understanding/preferred_style/confusion_signal。仅在用户本次原话有支持时生成；supporting_quote 必须是本次 message 的原文子串；atom_id 只能取 context.knowledge_atoms。不要把疑似误区称为已确认，也不要生成掌握率。
memories 只保留重要教学偏好、用户明确描述的学习习惯、用户自己的关键理解。类型 preference/explanation_style/learning_habit/important_insight，supporting_quote 必须引用本次原话。无重要信息就返回空数组，寒暄/谢谢/哈哈不生成任何记忆。学习习惯不可从时长、快慢推断。偏好不进入知识状态。所有 observations/memories 需符合给定 JSON Schema。

learning_relevant 表示本次提问是否与当前学习有关。无关闲聊返回 false、空 observations 与 memories；不要把所有对话保存为学习记录。
