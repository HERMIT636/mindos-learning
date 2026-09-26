# GitHub 开源发布说明

公开仓库：[HERMIT636/mindos-learning](https://github.com/HERMIT636/mindos-learning)。首批开源文件于 2026-09-27 发布，包含设计文档、课程包格式、原创示例及检查工具；项目目前处于设计与课程包示例阶段，完整应用尚未实现。

## 仓库信息

- 名称：`mindos-learning`
- 可见性：Public
- 描述：`Open-source adaptive learning platform with RAG, learner states and extensible course packs.`
- 许可：根目录的 MIT License
- 初始内容：设计文档、公开课程包示例及其检查工具

后续贡献提交到上述仓库，通过 Issues 和 Pull Requests 协作。

## 首批发布文件

```text
README.md
LICENSE
CONTRIBUTING.md
ROADMAP.md
MindOS_最终设计大纲.md
.gitignore
.gitattributes
requirements-dev.txt
.github/
docs/
schemas/
scripts/
course-packs/
```

本地历史版本、旧评审草稿、配置密钥、运行数据、模型文件和正式试点材料不在首批发布清单中。`.gitignore` 只影响未跟踪文件的添加，发布时仍以实际提交内容为准。

## 两种上传方式

### 网页上传

创建仓库后使用“Add file → Upload files”上传发布清单内的文件，保留目录结构。需要单独添加的隐藏文件可用“Create new file”按完整仓库路径创建。若使用准备好的 ZIP，先解压再上传内容；GitHub 不会自动将 ZIP 展开为项目文件。

### 本地 Git 上传

在一个可以正常使用 Git 的项目副本中初始化仓库，加入上述公开文件，创建首次提交，关联新仓库再推送。若计划从本地已有提交初始化，创建远端时可保持为空，避免自动生成另一份 README 或许可历史。

操作依据：[GitHub 创建仓库说明](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository)。

## 开源边界

本项目有权许可的原创文件采用 MIT；第三方课程内容、依赖和模型各自保留许可。可运行服务需要的 API 和计算资源不随代码仓库自动提供。

公开仓库采用公开练习和合成演示数据。学生原始作答、正式试点评估题和服务配置保存在运行环境中，公开报告只放确认可以发布的结果。

## 开始协作

通过 Issues 讨论缺陷、需求和课程提案，通过 Pull Requests 评审修改。建议首批任务聚焦课程包导入、基础 RAG、量表评分与独立复测。版本发布写明已实现内容、验证方式和已知限制。

每次发布后，将本文件的状态和 ROADMAP 中相应任务更新为实际结果。
