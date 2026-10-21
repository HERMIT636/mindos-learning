# 视觉打磨与渲染优化记录（2026-10-20）

本轮两部分：对既有深空主题做质感打磨（不改变风格基调），以及削减每次操作触发的全量 DOM 重建。

## 一、视觉打磨（web/universe.css）

界面原本已有良好的基调（深空配色、SVG 星图、清晰的信息层次），本轮只做"质感"而非"改风格"：

- **驾驶舱 hero**：在原有线性渐变上叠加左上角径向光晕，加一道内侧顶部高光和更深的氛围阴影；标题文字改用垂直渐变（白→浅蓝灰）替代纯色。
- **统计卡片**：渐变底面、内侧高光，数字从 29px/500 字重提升到 34px/600 并使用等宽数字（`tabular-nums`），三列数字纵向对齐。
- **主按钮**：垂直渐变底 + 内侧顶部高光，hover 上浮时光晕同步扩散，`box-shadow` 加入过渡属性，新增 `:active` 回落。
- **星云卡片**（课程宇宙总览）：顶部 2px 状态条——当前小节用蓝青渐变、锁定用暗色，配 hover 上浮；锁定态底色压深，让"未开放"一眼可辨。
- **侧边栏导航**：当前项左缘加 2px 渐变指示条。
- **空状态**：居中虚线框 + 顶部柔光，替代原先的左对齐纯文本。

全部为纯 CSS，未改任何结构与文案。由布局敏感的 universe、knowledge、presentation 三个浏览器检查验证（均含移动端无溢出断言），浏览器内核对计算样式确认生效。

## 二、渲染优化：不可变记录 DOM 缓存

### 问题

`renderCourse()` 每次动作（提问、交卷、打开知识点）都重建整个课程 DOM。其中大部分内容是**已持久化、不会再变**的记录：历史小测、对话轮次、旧版讲解、导师消息。每次重建都要重新走一遍 `MindOSTeaching.render`（教学块、SVG 图、公式）和 DOM 构建。

### 做法

在 `web/app.js` 与 `web/components/CourseAssistant/course-assistant.js` 各加一个模块级 `domCache`（Map）与 `cachedNode(key, build)` 辅助函数，把五处渲染路径的历史记录改为按稳定键复用节点：

| 路径 | 缓存键 | 键为何安全 |
| --- | --- | --- |
| 小测历史（`renderQuiz`） | `quiz:{id}` | `submit_quiz` 只在 `submitted_at IS NULL` 时 UPDATE 一次；前端展示字段（题目、答案、解释）之后不再变化 |
| 知识点测试历史（`renderKnowledgeTests`） | `atomtest:{id}` | 同上；按 id 而非容器做键，因为 growth 和 personal 视图也复用该函数渲染同一批测试 |
| 对话轮次（`renderConversation`） | `turn:{courseId}:{ordinal}:{index}` | turns 只追加不重排，节内 index 稳定 |
| 旧版讲解（`renderContentHistory`） | `version:{revision}:{lesson}` | `content_versions` 只 INSERT，从不 UPDATE/DELETE |
| 导师消息（`AssistantPanel`） | `chat:{message.id}` | 消息带自增 id；乐观消息 id 为 `pending-{requestId}`，不在缓存中，天然走新建路径 |

要点：

- 未提交的小测表单、正在编辑的输入**不缓存**，每次重建（含 live 输入状态）。
- 复用同一个 `<details>` 节点，用户展开的历史记录在重新渲染后仍保持展开。
- 缓存上限 400 条，超过即淘汰最早进入的条目，避免乐观消息等一次性条目无限堆积。
- `MindOSTeaching` 的 diagram 用 `crypto.randomUUID()` 生成 marker id，复用节点不会重复注册 id。

### 未做

`renderStarMap`（知识星图 SVG）未纳入：它的节点 class 反映实时知识状态，需要 diff 状态而非整体缓存，改动面远大于收益，留待后续。

## 验证

- 浏览器检查：knowledge、tutor、tutor_p6、production、final 五个目标套件通过；mission_p9、universe_p7、tutor_quality、execution、growth、personal、authentic、loop、presentation、universe、atie、architecture、management、discovery 亦通过。
- `resources_p8` 在本机连续失败（`sessions` 断言 0 !== 1，伴随 `ConnectionAbortedError`）。已在**未包含本轮任何改动的发布版本代码**上连续复现 3 次同样失败，确认是环境性存量问题（该测试含真实 PDF/PNG 解析与服务端会话创建），与本轮及此前各轮改动无关。
- 单元测试：862 项，错误集合与历史基线一致（Windows 临时文件占用与符号链接权限）。
- Prettier 与 `node --check` 通过。
