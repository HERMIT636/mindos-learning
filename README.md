# MindOS

**面向多课程的开源自适应学习平台：课程知识库、动态知识状态与个性化学习规划。**

An open-source adaptive learning platform built around course packs, retrieval-augmented generation, and evidence-based learner states.

> 当前阶段：设计与课程包示例。仓库包含设计文档、课程包格式、原创示例和格式检查工具；Web 界面、RAG 服务、状态追踪与自适应教学尚未实现。

## 项目解决什么问题

MindOS 希望帮助学习者明确当前薄弱点，获取有来源的学习材料，并通过独立任务检验学习结果。教师与贡献者通过课程包补充内容、练习和评分标准，平台复用学习流程。

课程包可面向编程、数学、语言等不同方向。首批示例为 Python 基础和线性代数基础；PyTorch 保留为后续进阶课程方向。

## 设计中的学习流程

选择课程与目标 → 短诊断 → 定位薄弱点 → 检索适合的资料 → 学习与练习 → 独立复测 → 更新状态和后续任务。

| 部分 | 作用 |
| --- | --- |
| 课程包 | 配置知识点、能力维度、资料、任务和评分依据 |
| RAG 知识库 | 检索课程证据并提供可追溯的解释 |
| 知识关系 | 表达先修与关联，约束任务顺序 |
| 学习者状态 | 根据作答证据记录各维度的当前判断 |
| 任务规划 | 结合目标、缺口和时间安排下一步 |

## 已准备的内容

- [完整设计大纲](MindOS_最终设计大纲.md)：产品范围、架构、评估与落地路线。
- [课程包约定](docs/course-packs.md)与 [JSON Schema](schemas/course-pack.schema.json)。
- [Python 基础示例](course-packs/python-foundations/manifest.json)。
- [线性代数示例](course-packs/linear-algebra/manifest.json)。
- [开发路线](ROADMAP.md)、[贡献指南](CONTRIBUTING.md)与 [开源发布说明](docs/open-source.md)。

示例包均为少量原创材料与公开练习，用于讨论和验证格式；内容尚未经过教师审核，不代表完整课程或已经证明的学习效果。正式试点题目单独维护。

## 检查课程包

需要 Python 3.10 或以上版本。当前可以运行的是课程包检查工具，尚无应用启动命令。

```bash
git clone https://github.com/HERMIT636/mindos-learning.git
cd mindos-learning
python -m pip install -r requirements-dev.txt
python scripts/validate_course_packs.py
```

在使用 `python3` 的环境中替换命令名称即可。检查涵盖格式、编号引用、先修循环和资料路径；不会调用大模型、执行课程代码或判断教学质量。

## 计划采用的技术

Next.js / React / TypeScript、FastAPI、PostgreSQL + pgvector，以及可替换的大模型和 Embedding 服务。编程课程按需启用隔离代码执行器。上述技术属于实现方案，依赖与部署方式将在开发阶段补齐。

## 如何参与

欢迎讨论使用场景、完善评分标准、纠正课程内容、贡献新的小型课程包和实现平台模块。提交前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)，并在反馈中标明实际测试结果与仍待验证的假设。

## 许可与数据

本项目原创代码、文档和示例采用 [MIT License](LICENSE)。第三方资料、依赖及模型遵循各自许可。

公开仓库不包含模型 API 密钥、学生原始记录、实际测评的私有答案或未获分发许可的教材。开源代码可自行部署；模型服务、算力和内容维护可能产生费用。
