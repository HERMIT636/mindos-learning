# 传输与等待优化记录（2026-10-20）

本轮聚焦"打开页面前那几秒"和导师面板的请求行为。所有修改均通过回归：20 项 Playwright 浏览器检查全部通过，862 项单元测试与改动前同等通过（仅 Windows 环境性失败），冷加载传输量与压缩正确性均在浏览器和服务器上实测确认。**未改动任何学习规则、掌握记录或评分逻辑。**

## 修改内容

### 1. 静态资源传输（mindos/server.py）

- 开启 HTTP/1.1 keep-alive（`protocol_version = "HTTP/1.1"`）。此前使用标准库默认的 HTTP/1.0，每个响应后关闭连接，冷加载约 21 个静态资源要走 21 条独立 TCP 连接。
- 增加 gzip 响应压缩：对 ≥1 KB 且客户端声明 `Accept-Encoding: gzip` 的响应体压缩，同时发送 `Content-Encoding: gzip` 与 `Vary: Accept-Encoding`。API 响应保持 `no-store`，语义不变。
- 实测冷加载传输量：JS 363 KB → 113 KB，CSS 80 KB → 19 KB，总计 485 KB → 131 KB（约 3.7 倍）。304 协商缓存仍返回空体，与压缩互不干扰。
- **配套修复**：keep-alive 下未读取的请求体会污染同一连接上的下一个请求，因此 `_request_json` 在所有拒绝路径（Content-Type 不符、长度无效、超限）先排空请求体再返回错误。

### 2. SQLite 并发（mindos/storage.py）

- `connect()` 增加 `PRAGMA journal_mode=WAL`、`busy_timeout=5000`、`synchronous=NORMAL`。此前使用默认回滚日志，读写互斥；本地服务读多写少，WAL 让读取不被写入阻塞，争用时等待而非直接失败。

### 3. 导师面板请求（web/components/CourseAssistant/course-assistant.js）

- 对话历史改为首次展开面板时才加载。此前每次切换课程都会拉取该课程完整对话记录（上限 80 条，含教学块结构），而折叠状态的面板从不展示这些内容。切换课程仍会重置并清空历史，保证再次展开时加载新课程的记录。
- 悬浮气泡位置改为切换课程时单独获取：新增轻量接口 `GET /api/courses/{id}/assistant/position`（仅返回坐标），并在首次渲染前完成，避免气泡先在默认角落闪现再跳到保存位置。
- 拖动/缩放面板与提问的乐观上屏逻辑不变。

### 4. 新接口（mindos/course_tutor.py、mindos/server.py）

- `CourseTutorService.assistant_position()`：只读 `assistant_position` 表，与 `assistant_history()` 共享课程归属校验。
- `_get` 中注册 `GET /api/courses/{id}/assistant/position` 路由；原有的 `PUT` 位置保存路由不受影响。

### 5. 测试适配

历史改为异步加载后，4 个浏览器检查需要在计数前等待记录出现，否则读到的是加载前的空面板：

- `tests/browser_tutor.cjs`：位置断言改轮询新接口；reload 后等第 6 条消息出现再计数。
- `tests/browser_tutor_p6.cjs`：保存基线数量前先等首条消息；reload 后等第 `savedCount` 条出现。
- `tests/browser_tutor_quality.cjs`：两处数量断言前等待第 2 条消息。
- `tests/browser_universe.cjs`：位置断言改轮询新接口。

## 验证

- `python scripts/check_browser.py <suite>`：knowledge、mission_p9、resources_p8、universe_p7、tutor_quality、tutor_p6、execution、growth、personal、authentic、final、loop、presentation、universe、atie、tutor、architecture、management、production、discovery 共 20 项全部通过。
- `python -m unittest discover -s tests`：862 项，23 个错误。22 个与上一轮完全相同的 Windows 环境性失败（临时 SQLite 文件被占用 `WinError 32`、符号链接权限）；新增 1 个 `test_universe_p7_api.test_no_mutation_delete` 的 `ConnectionAbortedError`，单独运行该测试类 19/19 通过、连续 30 次 DELETE 405 请求全部稳定，判定为全量并发下的抖动而非回归。
- 服务器实测：`/style.css` 25 KB → gzip 5.8 KB 且解压后与原文逐字节一致；带 `If-None-Match` 返回 304 空体；不带 `Accept-Encoding` 的客户端仍收到未压缩响应；同一连接顺序请求全部 200。
- 浏览器实测（Performance API）：29 个请求、传输 131 KB、DOM 就绪 175 ms。

## 未做的部分

- "折叠资料面板时不发请求"的方案已实现后**主动放弃**：`/api/sources` 的响应同时填充 `state.data.course.source_conflicts`，而该状态被知识点详情页的来源冲突提示消费。跳过请求会让从未展开面板的用户静默丢失冲突提示，属于功能性回退，不是纯性能优化。若要省掉这笔请求，需要先把冲突数据拆到独立的轻量接口。
- 全局 `state.busy` 单锁、全量重渲染、双主题 CSS 等结构性问题仍在 [上一轮记录](frontend-optimization-2026-10-18.md)的清单中，未在本次处理。
