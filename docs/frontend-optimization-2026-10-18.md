# 前端优化记录（2026-10-18）

本轮针对 `web/` 前端与静态文件服务做了一批可维护性与体验优化。所有修改均通过既有回归验证：862 项 Python 单元测试（错误数与修改前一致，见文末说明）、20 项 Playwright 浏览器检查全部通过，并在浏览器内实际验证了缓存与懒加载行为。**未改动任何学习规则、掌握记录或评分逻辑。**

## 修改内容

### 1. 代码格式化（可维护性）

- 引入 `.prettierrc`（printWidth 100、单引号、2 空格缩进）。
- 用 Prettier 3.6.2 一次性格式化 `web/**/*.{js,css,html}` 与 `tests/*.cjs`。
- 此前组件文件平均每行 200–250 字符（`mission.js` 32KB 仅 115 行），`style.css` 全部样式挤在数行内，无法进行有意义的 diff 审查。格式化后前端总行数从约 4,170 行扩展到约 15,289 行，属于纯格式变更，行为不变（由浏览器回归覆盖）。

### 2. 静态资源服务（mindos/server.py）

- 手工维护的 `STATIC` 路由字典（每个前端文件一条硬编码）替换为启动时扫描 `web/` 目录、按扩展名映射 MIME 的动态索引；新增前端文件不再需要同步登记。
- 静态资源响应增加 `ETag`（基于 mtime+size）与 `Cache-Control: no-cache`，支持 `If-None-Match` 协商缓存，命中返回 304 空体。此前所有资源（含 277KB 的 KaTeX）都发 `no-store`，每次刷新全量重下约 780KB。
- API 响应保持 `no-store`，学习数据仍不会被浏览器缓存。
- 304 响应不携带 Content-Type/Content-Length，避免与空正文不一致。

### 3. KaTeX 按需加载

- 从 `index.html` 移除 `vendor/katex.min.js`（277KB）的预加载。
- `resource-renderer.js` 在首次渲染公式材料时动态注入脚本；加载完成前先显示原始表达式 `<pre>`，加载或渲染失败回退到原始表达式，不会出现空白。
- 浏览器内验证：普通页面 0 个 katex script 标签、`window.katex` 未定义；进入公式材料后正常渲染 MathML（P8 浏览器检查覆盖）。

### 4. 死代码清理

- 删除 `app.js` 中无任何调用方的 `renderMarkdown()`（已被教学块渲染取代）。

### 5. 等待体验

- `action()` 长任务提示增加等待计时：超过 3 秒后在提示后追加“（已等待 N 秒）”，让用户确认请求仍在进行而非卡死。导航切换时计时器自动停止。
- 课程导师聊天：用户消息乐观上屏（发送后立即显示），服务端返回后用保存的对话记录整体替换；请求失败时移除乐观消息并显示错误。乐观消息仅在 UI 中出现，不写入任何存储。

### 6. 竞态修复（存量问题，本轮暴露后修复）

- `growth.js` 等组件的部分异步按钮回调没有 catch；当请求在飞行中遇到用户切换页面时，`api()` 按设计抛出“页面已切换”取消错误，会以 unhandled rejection 形式冒泡成页面错误。该错误本身就是导航取消信号（`action()` 早已静默处理同类情况），因此在 `app.js` 增加 `unhandledrejection` 兜底：仅拦截以“页面已切换”开头的取消错误，其余未处理拒绝照常上报。

### 7. 文件上传

- `production.js` 两处上传（课程创建资料、知识生产上传）的手写 base64 分块循环替换为 `FileReader.readAsDataURL`，大文件不再长时间阻塞主线程；产物与原实现一致（纯 base64，无 data: 前缀）。

## 验证

- `python -m unittest discover -s tests`：862 项中 840 项通过；22 个错误全部为 Windows 环境性失败——17 个因 SQLite 临时文件被占用导致 `tearDownClass`/迁移清理报 `WinError 32`，4 个因系统符号链接权限受限，均不属于本次修改的模块（静态服务、缓存与前端路径无涉及）。
- `python scripts/check_browser.py <suite>`：knowledge、mission_p9、resources_p8、universe_p7、tutor_quality、tutor_p6、execution、growth、personal、authentic、final、loop、presentation、universe、atie、tutor、architecture、management、production、discovery 共 20 项全部通过。
- 浏览器内实测：ETag 协商缓存 304 生效、KaTeX 不再预加载、深空主题与 SVG 星图渲染正常。
- 为配合公式懒加载，`tests/browser_resources_p8.cjs` 两处公式断言改为先 `waitFor` 再计数，使断言对异步渲染确定化。

## 未做的部分（后续建议）

- 全局 `state.busy` 单锁（一个慢请求期间所有按钮禁用）仍保留：改为按区域 pending 状态涉及全部交互路径，建议与流式输出（SSE）一起在下一轮处理。
- `style.css` 浅色主题与 `universe.css` 深色主题的双层覆盖、`course-assistant.js` 的 MutationObserver 页面状态反推、`confirm()` 原生对话框替换等结构性重构未在本轮范围，建议随迭代逐步处理。
