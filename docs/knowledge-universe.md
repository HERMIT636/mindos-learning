# 知识宇宙界面与接口适配

P7 新增跨课程的个人知识宇宙，统一课程＝星系、章节＝星云、知识原子＝星辰；新增只读适配层与二维 Canvas，详见 [P7 说明](learning-loop-p7.md)。下文保留课程内原有 SVG 视图及接口适配说明。

MindOS 的首页是学习驾驶舱。创建课程仍通过原有方向审查、用户确认、自动发现知识候选、用户审查导入的流程；没有预置正式课程。知识宇宙是课程知识及学习证据的展示方式，不会改变掌握算法或解锁规则。

## 页面与已有数据的对应

| 页面 | 展示 | 数据来源 |
| --- | --- | --- |
| 学习驾驶舱 | 当前课程、当前星云、进度、下一步建议、概念与应用表现 | 课程管理、LearningStateManager、knowledge_state.queue |
| 我的课程 | 新建、编辑、拖拽排序、状态、复制、回收站 | 既有 `/api/courses` 接口 |
| 宇宙总览 | 小节星云及学习顺序 | course.sections 与 mastery.sections |
| 学习空间 | 星云导航、结构化教学、追问、自查、小测、手动进入下一节 | 既有 lesson/ask/quiz/advance 接口与 ATIE |
| 知识星图 | 章节筛选、知识星辰、真实保存的知识关系、原子学习入口 | knowledge.atoms/edges 与原子 API |
| 小测反馈 | 当前小节的独立题目与历史结果 | 与学习空间共用同一个小测组件及提交逻辑 |
| 学习记录、成长档案 | 实际活动时间线与已提交测验曲线 | SQLite 教学记录、quizzes、learning_events、assistant_message |

星云图虚线仅表示课程顺序；星图实线表示后端保存的关系，其类型可悬停查看。AI 生成的关系和引用审查不代表独立事实认证。星辰亮度使用后端的未测、阅读、正确率和“较稳固”状态，不能把看完当掌握。完成两次高正确率测试的状态与单次测试区分，直接复用后端标签。

## 与需求中理想架构的取舍

现有项目采用 Python HTTP 服务、静态 HTML/CSS/JavaScript，无 React 构建。这次保留直接运行方式：统一状态层 `MindOSStore`、原生 SVG 图谱、CSS 设计变量与少量动画，不引入 Zustand、React Flow、Framer Motion 或 Tailwind。`state` 本身是可订阅对象，不另外维护一份可修改的能力模型。

`web/components/mindos/universe.js` 包含 LearningDashboard、CognitiveStatus、CourseUniverse、GalaxyMap、LearningSpace、KnowledgeStar、GrowthTimeline、ProgressVisualization；原有独立课程管理与导师组件继续负责各自交互。页面所有权由导航版本控制，离开页面后的慢响应不能覆盖当前课程。状态快照在未选课程时返回空上下文。

教学块沿用现有 ATIE 协议：text/concept/question/analogy、flow、diagram、formula、comparison、example、checkpoint。它们分别承担文字、引入、步骤、结构、公式、比较、案例和口头理解检查。独立小测使用原有四道题组件，保持独立掌握证据的含义；不会把口头自查当独立小测，也不为视觉方案更改知识原子结构。

## 只读驾驶舱接口

新增 `GET /api/dashboard`，可带 `course_id`。返回 `courses`、`current`、`learning_state`、`recommendations`、`timeline`、`context` 和 `boundary`。

未指定课程时，选择最近有学习记录的 active 课程；没有 active 课程则不生成虚构状态。显式选择可查看暂停或归档课程。服务按浏览器会话检查所有权，排除回收站课程，未知或其他会话的课程返回错误。

能力维度直接读取当前课程当前进度以内最近 8 次已提交独立测验；不合并其他课程的记录。概念理解与知识应用呈现已测题的正确比例，迁移能力无独立测量，显示“尚未测量”。推荐使用已有复习队列及当前小节状态，明确标注“规则建议”，不是新调用模型规划的个性化路径。

时间线最多返回最新 36 项，不返回题目、答案、私人提问正文或模型密钥。未提交测验不画图。曲线仅是每次测验正确率：题型与难度可能不同，不能当标准化能力增长证据。课程内历史按课程过滤；首页活动列表可展示本会话其他课程的足迹，但导师只获取当前选定课程的上下文。

接口不调用模型，不生成教学内容、不写学习记录、不更新掌握率、不推进小节。

## 悬浮导师与阅读

导师入口全局可见。驾驶舱与成长档案使用所选课程，课程学习绑定小节，星图知识详情绑定知识原子。弱知识提示只展示当前课程实际独立测试记录，不凭空诊断矩阵或迁移能力。未选择课程时显示课程选择入口，不能发送；切换课程时先清除可见旧聊天，再读取新课程历史。回答中的关联知识点可从驾驶舱跳入对应课程星图。

拖动结束吸附到最近的左右边缘，位置仍使用原有课程级 position API 保存；无课程时使用 localStorage 保存界面位置。可用 Alt+方向键移动图标，Escape 收起。手机面板与图标限制在可视区域内。页面含少量星光与静态轨道图，正文使用较实的阅读面板，支持减少动态效果的系统偏好；星图在手机可局部横向滚动，页面本身不横向溢出。

## 验证与后续范围

自动化测试：`python3 -m unittest discover -s tests -v`。新增驾驶舱测试覆盖空状态、选课、所有权、删除隔离、题型表现、时间线脱敏与只读性。

可选浏览器检查使用 Playwright、Microsoft Edge 与 Node，不是产品运行依赖。设置 `MINDOS_NODE` 为 Node 可执行文件路径；若使用 Windows Node，`PLAYWRIGHT_MODULE_WINDOWS` 填 Windows 格式的 Playwright 模块路径（普通 Node 安装可使用默认 `playwright`）。在项目根目录或发布仓库执行：

```bash
python3 scripts/check_browser.py universe atie tutor architecture management knowledge production discovery
# 仅在需要重新保存界面验收截图时使用：
python3 scripts/check_browser.py universe --screenshots
```

检查使用临时 SQLite、模拟模型与搜索响应，不读取个人数据库或调用付费模型。截图中的 Transformer 与图论课程来自临时测试夹具，百分比是夹具的独立作答记录，不是真实用户试验；教学可理解性与学习效果仍需要实际用户评估。

本次实现第一阶段和星图／状态／教学块展示。第三阶段的复杂动画、主动提醒、新的个性化路径规划和迁移能力测量尚未实现。已有 ATIE 的用户状态决策继续生效。
