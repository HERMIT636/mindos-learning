# 三门主课程外部资料复核更正

复核日期：2026-09-27。此文件修正 `AUDIT_REPORT.md` 的交付结论；原报告保留作审计轨迹。下列“可用”只表示文件完整性和来源候选，不等于教师已审核或已接入 RAG。

| 课程 | 实际清单 | 完整性复核 | 当前教学价值 |
| --- | --- | --- | --- |
| 机器学习 | 12 条：11 个 HTML、1 个 ZIP | 11 个 HTML 经 SHA-256 复核；ZIP 缺少中央目录，无法打开 | HTML 主要是 scikit-learn 参考文档；不能把损坏 ZIP 算作全量教材 |
| HPC | 3 个 PDF | 文件头尾与 SHA-256 可核对 | OpenMP 与 MPI 标准适合作权威参考；MPI Forum Procedures 3.5 讲的是标准制定流程，不是 MPI 编程教程 |
| Ascend C | 1 个 HTML | SHA-256 与基本 HTML 完整性可核对 | MindSpore 2.3.1 自定义算子单页案例，不能覆盖完整 Ascend C 课程 |

机器学习原报告称“13 个”是重复列出 `sklearn-svm.html`；清单和磁盘均只有 12 个。`sklearn-preprocessing.html` 与 `sklearn-neural-networks.html` 的原 SHA-256 被对调；`sklearn-clustering.html` 与 `sklearn-decomposition.html` 虽已在磁盘上，清单却写 `PENDING_DOWNLOAD`。四项已按当前文件重新计算 SHA-256。11 个 HTML 含页标题和完整 HTML 结构，尚未验证所有相对图片、公式资源可离线显示。损坏 ZIP 的当前 SHA-256 原本就与清单相符，说明**哈希匹配不代表归档完整**。本地文件约 35.4 MB，[scikit-learn 官方版本页](https://scikit-learn.org/dev/versions)将 1.9.1 完整 ZIP 标为约 99.8 MB；官方页面的下载链接本次重试返回 404。保留损坏文件供排查，禁止索引或发布它。

许可结论需分开写：[OpenMP 5.2 规范](https://www.openmp.org/spec-html/5.2/openmp.html)和 [MPI 4.0 官方 PDF](https://www.mpi-forum.org/docs/mpi-4.0/mpi40-report.pdf)均在首页允许附条件免费复制全部或部分文本。原报告声称 MPI 4.0 没有明确复制许可是错误的；这项许可也不应被自动解释为允许翻译、改编、商用的所有情形或任意长度的生成式输出。这两份规范暂不纳入公开索引，先复核署名和实际使用方式。[MPI Forum Procedures 3.5](https://www.mpi-forum.org/docs/other/procedures-35.pdf)标注 CC BY 4.0，但与初学者学习 MPI 通信关系很小。

[scikit-learn](https://github.com/scikit-learn/scikit-learn/blob/main/COPYING) 文档站标明 BSD 许可；[MindSpore 文档仓](https://gitee.com/mindspore/docs/blob/master/README_CN.md)标明 Apache 2.0。重新使用或发布仍应保留适用的许可与来源信息。原报告把 `ai_training` 写为明确允许或禁止，依据不足；新清单改为 `null`（未单独核查），不影响本项目当前只做教学检索的目标。

原报告的机器学习 85%、HPC 60%、Ascend C 20% 属未说明分母和评估方法的估计，**不作为课程覆盖率**。按概念附上资料链接不等于初学者已有完整讲解。三门课均仍需以人工打磨的讲解稿为主，外部文档用于核对术语、接口和延伸阅读。现已将机器学习七则、Ascend C 一则 MindOS 中文导读加入资料问答检索，并用代表性问题验证命中；下载原件仍未自动切分、索引。后续要进行原文级检索，还须完成章节级映射、文本提取与引用校验，并用学习者问题验证是否比现有关键词检索更有帮助。
