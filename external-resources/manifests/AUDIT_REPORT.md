# MindOS 外部资料复核报告

复核日期：2026-09-27。资料均为候选参考内容，**教师内容审核仍未完成**。四则按知识点撰写的中文导读已接入原型的模型模式；下载的原始 HTML/PDF 尚未自动索引。本报告记录文件状态、主题相关性和许可证线索；“允许作为检索参考”与“允许用来训练模型”是不同问题，后者没有在本次审核中作出许可结论。

## 实际文件与完整性

清单中的七个候选资源文件已逐一重新计算 SHA256，现均与两个 manifest 的记录一致。另有许可证和来源页面的 HTML 快照，供人工核对。

先前下载的 Hefferon PDF（1,867,476 字节）缺少 `startxref` 和 `%%EOF`，源码压缩包（2,563,459 字节）在完整解压时报告 `unexpected end of file`。两者虽然与旧清单 SHA256 一致，仍是**不完整下载**。现已从作者提供的站点重新下载并替换：

| 资源 | 完整文件大小 | 新 SHA256 | 结构检查 |
| --- | ---: | --- | --- |
| [Hefferon 教科书 PDF](https://jheffero.w3.uvm.edu/linearalgebra/book.pdf) | 7,626,685 字节 | `5240F2782E645BC6351AD9EBA69D8C19500142A5CCA9C90450C17B3765A1A400` | PDF 头、`startxref`、`%%EOF` 存在；作者站 PDF 为 525 页 |
| Hefferon GitLab 源码压缩包 | 42,226,402 字节 | `267BB061C9A8A6D5284C639DB5C94856E083CFCDBE1763616E8877143047C4D2` | `gzip -t` 与完整 `tar -t` 通过，共 974 个归档条目 |

结构检查不等于逐页公式和代码审核。源码归档还含图片、考试题等不同类型文件，不应整体导入 RAG，也暂不应直接公开发布。

本地复核命令：`python3 scripts/validate_external_resources.py`。脚本检查清单哈希、PDF 结尾、HTML 文档结尾，并完整读取压缩包成员。当前结果：7 个已下载文件通过，3 个链接未下载。所有下载的第三方原件已加入根目录 `.gitignore`；公开项目只需保留资源清单、审核报告与 MindOS 自写导读。公开仓库没有这些下载件，因此该完整性检查只适用于保留了原件的审核工作区。

## 与当前课程知识点的相关性

| 课程知识点 | 优先候选片段 | 不宜直接索引的部分 |
| --- | --- | --- |
| Python：函数定义与调用 | [Python 官方教程“定义函数”](https://docs.python.org/3/tutorial/controlflow.html#defining-functions)；[Google Python Class Introduction](https://developers.google.com/edu/python/introduction) 中的 Functions 段 | 官方教程整页还含多个控制流主题；须按目标小节提取。Google 课程首页只是导航页 |
| Python：返回值 | 上述函数定义段；[官方 `print()` 文档](https://docs.python.org/3/library/functions.html#print)；Google Introduction 的 `return` 示例 | `print()` 下载文件是整张内置函数页面，不是仅 `print()` 小节；Google Basic Exercises 主要是字符串与列表练习，不直接补足当前知识点 |
| 线性代数：二维向量 | [Hefferon 书](https://jheffero.w3.uvm.edu/linearalgebra/book.pdf) Chapter One II.1 “Vectors in Space” | 全书其他章节难度高于当前入门目标 |
| 线性代数：点积 | 同书 Chapter One II.2 “Length and Angle Measures”（含 dot product、角度与正交）；Chapter Three VI “Projection” 可作为进阶 | 原报告把点积主要定位到“第三章 3.7 节”，与书内目录不符 |

MindOS 原创讲义继续作主线。现有四则[外部资料导读](../curated/concept-guides.json)仅概括上表的相关知识点，并给出原始出处；它们是模型讲解的补充依据，尚未通过教师审核。外部练习题及答案不能混进独立测评证据。

## 许可证复核范围

- [Python 官方文档许可](https://docs.python.org/3/license.html)覆盖文档；具体再分发需保留相应声明。
- [Google Developers Site Policies](https://developers.google.com/terms/site-policies)说明页面内容一般为 CC BY 4.0，代码示例为 Apache 2.0，仍需留意页面的例外标记和署名。
- [Hefferon 作者网站](https://hefferon.net/source.html)说明教材可在 GFDL 与 CC BY-SA 3.0 US 之间选择；但下载的 **GitLab 源码归档根目录 `LICENSE` 写的是 CC BY-SA 2.5**。归档又含其他来源的图片和题目，因此源码归档的许可状态记为“待逐项复核”，不作为可直接公开分发或整体入库的材料。教材 PDF 与归档应分别判断。
- 上述许可线索不足以把所有资源统一标记为“允许 RAG/LLM 训练”。本项目当前使用的是检索后放入提示词的讲解流程，**没有训练大模型**；manifest 已移除原先过于笼统的训练许可布尔断言，改为 `model_training_permission: not_assessed`。

## 扩大检索范围前的实际工作

1. 教师确认每个知识点需要的具体段落，并核对公式、例题和难度。
2. 只从审核过的段落提取正文，剔除网页导航、脚本、页脚及无关章节；记录章节号、原始网址、许可与版本。
3. 将抽取片段映射到单一或少量知识点，做检索命中测试，再决定是否需要向量索引。原始 HTML/PDF 不应整页或整书直接送入模型。
4. 独立测评题与答案继续单独保管；外部教材练习仅用于教学参考。
5. 源码归档须解决许可版本差异与内部第三方文件问题后，再决定是否需要保留或发布。
