# MindOS

**面向多课程的开源自适应学习平台：课程知识库、动态知识状态与个性化学习规划。**

An open-source adaptive learning platform built around course packs, retrieval-augmented generation, and evidence-based learner states.

> 当前阶段：本地可运行的学习原型。已支持两门示例课程、资料检索、客观题作答与证据状态；课程内容和评分方式尚待教师审核。大模型讲解与向量检索可按需配置，未配置时使用课程关键词检索。正式用户认证、隔离代码测试和真实学习效果验证仍待建设。

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

## 已有内容

- [完整设计大纲](MindOS_最终设计大纲.md)：产品范围、架构、评估与落地路线。
- [课程包约定](docs/course-packs.md)与 [JSON Schema](schemas/course-pack.schema.json)。
- [Python 基础示例](course-packs/python-foundations/manifest.json)。
- [线性代数示例](course-packs/linear-algebra/manifest.json)。
- [开发路线](ROADMAP.md)、[贡献指南](CONTRIBUTING.md)与 [开源发布说明](docs/open-source.md)。
- [本地原型运行说明](docs/prototype.md)：两门课程的练习、状态记录和资料助手。

示例包均为少量原创材料与公开练习，用于讨论和验证格式；内容尚未经过教师审核，不代表完整课程或已经证明的学习效果。正式试点题目单独维护。

## 运行本地原型

需要 Python 3.10 或以上版本，运行原型不需要安装额外依赖：

```bash
git clone https://github.com/HERMIT636/mindos-learning.git
cd mindos-learning
python -m mindos.server
```

然后在浏览器打开 <http://127.0.0.1:8765>。学习记录只保存在本机的 `data/mindos-demo.sqlite3`，请仅使用演示数据。支持单选与数值题的确定性评分；简答与代码题只保存练习作答，不自动判分或执行代码。

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
