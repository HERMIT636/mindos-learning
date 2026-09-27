# MindOS 主课程学习路线（草稿）

项目目前优先服务“机器学习 → HPC 性能思维 → 昇腾 Ascend C 算子开发”的学习目标。Python 基础和线性代数保留为可选先修，不要求学习者从头重学；若短诊断显示特定知识缺口，再回到相应先修材料。

| 课程 | 章节与知识点 | 当前可用内容 |
| --- | --- | --- |
| [机器学习](../course-packs/machine-learning/manifest.json) | 问题与数据：任务类型、数据切分、预处理；模型与优化：线性模型、梯度优化；评估与泛化：指标、过拟合；更多模型：树/聚类、神经网络 | 9 篇原创入门讲义、9 道短诊断、18 道公开客观练习 |
| [HPC 高性能计算](../course-packs/hpc-foundations/manifest.json) | 硬件与并行性能：内存层级、加速比；测量：基线与剖析；共享内存：OpenMP、同步；分布式：MPI；加速器：GPU 与分块优化 | 8 篇原创入门讲义、8 道短诊断、16 道公开客观练习 |
| [昇腾 Ascend C](../course-packs/ascend-c-operators/manifest.json) | 题意与环境：算子契约、CANN；核函数与分块：编程模型、Tiling；流水线：TPipe/TQue、矢量 API；验证迭代：精度对拍、性能调优 | 8 篇原创入门讲义、8 道短诊断、16 道公开客观练习 |

三个课程包各自按章节组织，知识点之间有先修链。选择目标后，短诊断只覆盖当前知识点及其直接先修；计划展示通往目标的整条路径。资料模式可阅读这些讲义，大模型模式可结合当前课程片段和学习状态进一步解释。课程之间的跨课先修目前由上面的路线人工说明，应用尚不会自动把三个课程的知识状态联动。

**内容边界：**这批讲义是首版入门材料，重点是建立完整、可运行的学习路径，篇幅和教学深度还不能替代系统教材与真实工程训练。公开三选一练习只验证概念判断，不证明学习者具备训练模型、编写 MPI 程序或在昇腾硬件上实现算子的能力。课程仍标为 `draft`；正式使用前应由懂对应学科的教师或工程师复核，并补充代码任务、真实设备实验和独立测评。Ascend C 的 API、硬件支持和竞赛规则依赖具体 CANN 版本与赛题，实际开发须以所用版本与当届规则为准。

延伸阅读来自原始维护方：[scikit-learn 用户指南](https://scikit-learn.org/stable/user_guide.html)、[PyTorch 基础教程](https://docs.pytorch.org/tutorials/beginner/basics/intro.html)、[OpenMP 规范](https://www.openmp.org/specifications/)、[MPI Forum 文档](https://www.mpi-forum.org/docs/)、[昇腾 Ascend C 编程指南](https://www.hiascend.com/document/detail/zh/canncommercial/900/programug/Ascendcopdevg/atlas_ascendc_map_10_0008.html)。MindOS 只链接这些资料，并未将整站内容复制进课程包。
