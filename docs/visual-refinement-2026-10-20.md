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

## 三、动效（web/universe.css、web/knowledge-universe.css）

在质感打磨基础上加入克制的动效，全部为 CSS 动画（合成器属性，无 JS 参与、无额外请求）：

- **hero 轨道插画**：三条轨道环以 60/84/108 秒不同速度与方向缓慢旋转（其中一条反向），中心核心与 ✦ 符号做 5–6 秒呼吸，六颗卫星以 7/9/11 秒错相位漂浮。旋转周期取到分钟级，避免干扰阅读。
- **入场序列**：hero → 三张统计卡 → 两张内容卡以 0.02s–0.28s 依次浮现（上移 14px + 淡入），缓动曲线 `cubic-bezier(0.22, 0.68, 0.36, 1)`。
- **主按钮光泽**：hover 时一道高光从左向右扫过（0.9s），与原有的上浮和光晕扩散叠加。
- **知识星图**：星星核心做 5 秒闪烁（缩放 + 透明度），按状态区分周期（学习中 4s、较稳 6s、需补强 3.4s），并用 `nth-of-type` 错开相位，避免整片同步闪成一片。
- **星云卡片**：hover 上浮时附加柔和投影；当前小节的状态条带发光。
- **知识宇宙画布**：画布后方两层径向环境光以 26 秒周期缓慢漂移；画布上的星点仍由 canvas 绘制，两者叠加。

无障碍：所有新增动画均被既有的全局 `prefers-reduced-motion: reduce` 规则（`*, ::before, ::after { animation: none !important }`）覆盖，未新增任何例外。浏览器检查中的 reduced-motion 断言（`.knowledge-star` 的 animationName 必须为 none）保持通过——星点动画加在子元素 `.knowledge-star-core` 上，而该规则通配所有后代元素。

## 四、学习空间打磨（web/universe.css）

学习空间是用户停留最久的界面，此前用纯色卡片、10–11px 字号，层次最弱。本轮：

- **课程主卡**：顶部径向光晕 + 纵向渐变 + 内侧高光和深氛围阴影，标题从 23px 提到 25px 并收紧字距，eyebrow 提亮。
- **星云导航侧栏**：当前项改用渐变底、柔和投影，并加 2px 渐变指示条（与侧边栏导航一致的语言）；未锁定项 hover 有底色和边框反馈；过渡补齐。
- **小测选项**：从扁平边框改为渐变卡片，hover 右移 3px 并高亮边框；用 `:has(input:checked)` 做选中态（渐变加深、文字提亮），键盘焦点有可见轮廓。
- **教学块**：渐变底 + 内侧高光，并按 `nth-child` 做 0–0.2s 依次浮现；三种变体（问题/类比/自查）分别加渐变与对应色光的左侧辉光。
- **课程模式切换**（宇宙总览/学习空间/知识星图/小测反馈/学习记录）：当前项加文字微光和一条居中发光的下划线，hover 有文字提亮。
- **下一步卡片**： radial 光晕 + 渐变 + 外发光，让它成为流程中的视觉锚点。
- **知识点 chip**：渐变底，hover 上浮 1px 并提亮边框。

## 五、星系图与导师面板（web/universe.css）

- **课程宇宙总览的星系 SVG**：小节之间的虚线顺序线做 30 秒缓慢流动（`stroke-dashoffset`），让"学习路径"有方向感；当前星系的 halo 做 5 秒呼吸；hover 时星系核心放大 1.1 倍并提亮描边。
- **导师面板**：面板改渐变底 + 顶部光晕 + 内侧高光，同时把 80px 的大阴影收窄到 60px/-22px（原值在拖动时每帧重绘成本很高）；消息气泡区分角色——助教消息带蓝色左饰条、用户消息带暖色左饰条，均渐变底并有 0.32s 入场。
- **悬浮导师按钮**：加内高光；hover 放大作用于内部 ✦ 图标而非按钮本身（拖动逻辑和保存的位置读取按钮的布局盒，缩放按钮会引入亚像素偏移）；另加一层 4.5 秒的缓慢光环，表示"随时可用"而不抢夺注意力。

无障碍不变：新增动画同样全部落在全局 `prefers-reduced-motion` 规则覆盖范围内。

## 六、成长路线与实践空间（web/universe.css、web/mission.css）

补齐最后两个停留在早期风格的界面：

- **成长路线**：时间线圆点加 4 秒柔和脉冲；缺口卡改渐变底并加 hover 上浮；阶段卡加径向光晕 + 渐变 + 内侧高光。
- **实践空间**：统计卡改渐变底，数字提到 1.4rem/600 字重并用等宽数字；任务/实验/产出卡改渐变底并有 0.36s 入场；时间轴航点补上圆点标记（此前只有竖线，读不出节点位置）。
- `mission.css` 本地定义 `rise-in` keyframes：此前它复用 universe.css 的定义，依赖加载顺序，单独使用时会静默失效。

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

## 七、交互：按区域隔离等待状态（web/app.js、web/index.html）

此前 `action()` 用单一的 `state.busy` 做全局互斥：任何一个慢请求（生成讲解通常 30 秒以上）期间，界面所有按钮都会禁用，连切换章节、打开星图、点开导师都做不到。

现在改为按 scope 跟踪：

- 新增 `busyScopes`（Map）记录每个区域在飞的请求数，`state.busy` 变为派生值（任一线程忙则为 true），因此 13 个浏览器检查里 `idle = () => !state.busy` 的语义完全不变。
- `action()` 的互斥检查从"全局有无操作"改为"同一 scope 有无操作"；禁用范围限定为触发按钮所在 scope 内的按钮（`data-scope-keep` 标记的按钮豁免）。
- `index.html` 给四个独立交互区域打标记：学习空间（learn）、知识星图（stars）、小测（quiz）、资料生产（production）。

实测（拦截讲解生成请求使其挂起）：学习空间内的按钮被禁用，而模式切换、侧边栏课程切换、悬浮导师按钮全部保持可用，星图可以在讲解生成期间正常打开，`state.busy` 仍为 true，无页面错误。
