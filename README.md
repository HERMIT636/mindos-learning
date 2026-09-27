# MindOS

**面向多课程的 AI 逐节教学原型：目标路线、随时追问、节后小测与学习状态。**

An open-source adaptive learning platform built around course packs, retrieval-augmented generation, and evidence-based learner states.

> 当前阶段：本地可运行的学习原型。网页教学需要先在服务端配置对话模型；选定课程目标后，可跳过学前小测，沿先修路线逐节获得深入讲解、随时追问并做节后小测。AI 教学依据课程目录和学习证据生成，不展示旧的本地草稿讲义。课程内容与 AI 出题仍待教师审核；正式用户认证和真实学习效果验证仍待建设。

## 项目解决什么问题

MindOS 希望帮助学习者明确当前薄弱点，获取有来源的学习材料，并通过独立任务检验学习结果。教师与贡献者通过课程包补充内容、练习和评分标准，平台复用学习流程。

当前主课程为机器学习、HPC 高性能计算和昇腾 Ascend C 算子开发；Python 基础与线性代数保留为可选先修示例。机器学习课程覆盖多种模型与评估方法，神经网络单元会使用 PyTorch 示例，但整门课不限定于 PyTorch。

## 设计中的学习流程

连接 AI → 选择课程与目标 → 可做或跳过学前小测 → 逐节讲解、追问与节后小测 → 独立复测 → 更新状态和后续任务。

| 部分 | 作用 |
| --- | --- |
| 课程包 | 配置知识点、能力维度、资料、任务和评分依据 |
| 课程检索 | 教学主流程不依赖 RAG；旧检索接口保留供研究，尚无完整教材向量库 |
| 知识关系 | 表达先修与关联，约束任务顺序 |
| 学习者状态 | 根据作答证据记录各维度的当前判断 |
| 任务规划 | 结合目标、缺口和时间安排下一步 |

## 已有内容

- [完整设计大纲](MindOS_最终设计大纲.md)：产品范围、架构、评估与落地路线。
- [主课程学习路线](docs/learning-paths.md)：三门优先课程的章节、知识点与当前内容边界。
- [AI 教学与检索策略](docs/teaching-content-strategy.md)：逐节对话的分工、边界与旧 RAG 的真实范围。
- [课程包约定](docs/course-packs.md)与 [JSON Schema](schemas/course-pack.schema.json)。
- [机器学习](course-packs/machine-learning/manifest.json)、[HPC](course-packs/hpc-foundations/manifest.json)、[昇腾 Ascend C](course-packs/ascend-c-operators/manifest.json)课程包。
- [Python 基础示例](course-packs/python-foundations/manifest.json)。
- [Python 函数单元内容复核](docs/python-unit-review.md)。
- [线性代数示例](course-packs/linear-algebra/manifest.json)。
- [外部开放资料复核更正](external-resources/manifests/VALIDATION_ADDENDUM.md)与[知识点导读](external-resources/curated/concept-guides.json)：资料问答可检索十二则带原始出处的 MindOS 导读；原始下载文件留在本地供审核，不随项目发布。
- [开发路线](ROADMAP.md)、[贡献指南](CONTRIBUTING.md)与 [开源发布说明](docs/open-source.md)。
- [本地原型运行说明](docs/prototype.md)：五门课程的讲解、练习、状态记录和资料助手。

三门主课程已有贯通的首版章节和逐知识点讲义，但内容仍是入门草稿，工程实操与深度推导尚待扩充；Python、线性代数两个旧包仍是小范围示例。所有课程尚未经过教师审核，不代表已证明学习效果。正式试点题目单独维护。

## 运行本地原型

需要 Python 3.10 或以上版本，运行原型不需要安装额外依赖：

```bash
git clone https://github.com/HERMIT636/mindos-learning.git
cd mindos-learning
python -m mindos.server
```

然后在浏览器打开 <http://127.0.0.1:8765>。先选择学习模式；大模型模式仅在服务端已配置模型时开放，网页不接收 API 密钥。学习记录只保存在本机的 `data/mindos-demo.sqlite3`，请仅使用演示数据。公开课程的单选与数值题可确定性评分；AI 临时小测验只作练习，不计入掌握状态。简答与代码题只保存练习作答，不自动判分或执行代码。

要检查课程包格式，再安装开发依赖并运行：

```bash
python -m pip install -r requirements-dev.txt
python scripts/validate_course_packs.py
```

在使用 `python3` 的环境中替换命令名称即可。格式检查不会判断教学质量。模型接入和原型边界见 [运行说明](docs/prototype.md)。

## 计划采用的技术

当前演示版使用 Python 标准库与 SQLite，以便直接在本机运行；教学资料只从当前课程检索，可选通过兼容接口接入大模型与 Embedding 服务。面向真实用户的后续架构仍规划为 Next.js、FastAPI、PostgreSQL + pgvector，并加入隔离代码执行器。详见 [设计大纲](MindOS_最终设计大纲.md)。

## 如何参与

欢迎讨论使用场景、完善评分标准、纠正课程内容、贡献新的小型课程包和实现平台模块。提交前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)，并在反馈中标明实际测试结果与仍待验证的假设。

## 许可与数据

本项目原创代码、文档和示例采用 [MIT License](LICENSE)。第三方资料、依赖及模型遵循各自许可。

公开仓库不包含模型 API 密钥、学生原始记录、实际测评的私有答案或未获分发许可的教材。开源代码可自行部署；模型服务、算力和内容维护可能产生费用。
