# 本地学习原型

这是用于大创／挑战杯项目开发和演示的本地预览版，课程内容仍标记为 `draft`。它可以走通选课、资料查找、作答、状态更新和下一题推荐；所有掌握状态都是工程规则的演示结果，不能当作真实学习效果。

## 启动

需要 Python 3.10 或以上版本。从仓库根目录运行：

```bash
python -m mindos.server
```

浏览器打开 <http://127.0.0.1:8765>。默认只监听本机地址 `127.0.0.1`。如需换端口，运行 `python -m mindos.server --port 8766`。使用 `python3` 的环境可相应替换命令。

不配置模型即可演示两门课程。资料助手用课程范围内的关键词查找 Markdown 原文；单选和数值题由服务器按公开课程包中的答案判分。SQLite 数据位于 `data/mindos-demo.sqlite3`，该目录不会提交到 Git。不同浏览器会话用本地 Cookie 区分，**没有正式账号系统**，因此不要录入真实学生资料。

## 五分钟演示

1. 进入 Python 基础，点击“开始推荐练习”，独立完成函数调用的单选题；观察该知识点变为“初步达标”。
2. 完成另一道考查相同知识点的不同题；观察状态变为“复测通过”，下一题转向返回值。
3. 切换“辅助练习”，问资料助手“return 和 print 有什么区别？”，展开原文出处。
4. 切换线性代数，完成向量题和两道不同的点积数值题；观察课程状态相互隔离。

辅助练习、同题求助和未自动评分的作答不会计入独立掌握证据。同一题多次提交至多提供一份当前证据。一次通过标记为“初步达标”，两道不同题通过标记为“复测通过”；一正一误标记为“待复核”。

## 可选模型与向量检索

把仓库根目录的 `.env.example` 复制为 `.env`，填写你选择的兼容服务的 API 地址、对话模型名称和可选的 Embedding 模型名称。远程服务使用 HTTPS；本机服务可使用 HTTP。密钥只放在 `.env`，不要提交到仓库或输入页面。

```text
MINDOS_MODEL_BASE_URL=https://api.openai.com/v1
MINDOS_CHAT_MODEL=你已开通的对话模型名称
MINDOS_EMBEDDING_MODEL=你已开通的向量模型名称
MINDOS_MODEL_API_KEY=你的密钥
```

只设置对话模型时，系统采用关键词检索后生成带原文入口的讲解；再设置 Embedding 模型时，系统计算课程片段和问题的向量并融合排序。向量缓存在本地 SQLite 中，缓存键包含模型、课程版本与资料内容。模型出错时回到课程原文和关键词检索，提交的作答记录不受影响。模型调用可能产生服务费用；请按服务提供方的政策使用资料。

接口采用 OpenAI 兼容的 [Chat Completions](https://developers.openai.com/api/reference/resources/chat) 与 [Embeddings](https://developers.openai.com/api/reference/resources/embeddings/methods/create) 请求格式。不同兼容服务对模型名称和功能的支持会有差异。本仓库不提供模型密钥，也不默认调用外部服务。

## 当前边界

- 资料只来自当前课程包 `resources` 中的 Markdown；参考答案和评分表不进入资料助手上下文。
- 仅对单选与数值题进行确定性评分；数值题目前要求与示例答案精确相等。简答与代码题不作自动评分，代码不会执行。
- “独立作答”使用公开示例题，答案在仓库里可查，仅供验证产品流程。正式试点要独立制作私有、等价的测评题并由教师审核。
- 状态规则没有经过教学效度验证；当前尚无正式登录、教师审核页、PostgreSQL / pgvector 部署和真实用户试点。

运行检查：`python -m unittest discover -s tests -v`。课程格式检查仍使用 `python scripts/validate_course_packs.py`，后者需要先安装 `requirements-dev.txt`。
