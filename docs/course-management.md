# 课程管理

侧栏“课程管理 · 我的课程”是课程层管理入口。首页和学习中心的快捷列表默认显示学习中的课程；管理页可查看全部、学习中、暂停、已完成、归档或回收站。课程状态由用户决定，测试和资料导入不会自动把课程标成已完成，也不会开放后续小节。

卡片展示课程名称、简介、封面、标签、难度、学习进度、知识点数量和最近学习时间。编辑支持名称、简介、HTTPS 封面地址、标签、目标、难度和状态。目标编辑不会重写旧讲解或重新生成地图；后续知识发现与新讲解会读取新目标。课程难度“入门／基础／进阶／高级”与个人水平 `learner_level` 分开保存。

学习进度按已进入后续小节、已提交章节测试或已读本节全部知识点计算，不等于掌握率；生成一篇讲解不算完成一节。最近学习时间来自讲解、对话、阅读／复习或已提交测试记录；没有记录显示“尚无学习记录”。知识点数量排除已弃用原子。

全部课程视图支持拖动 ☰ 排序，并提供上移、下移按钮供键盘和移动设备使用。排序按当前浏览器会话保存，提交时校验完整课程列表，防止并发增删和其他用户课程混入。恢复和复制的课程排到末尾。

删除仅写入 `deleted_at`，保留学习、资料、图谱及历史；已删除课程不能从学习接口访问。回收站可恢复，原状态、掌握证据和学习进度仍然保留。永久删除需再次填写完整课程名称，只允许删除回收站课程，事务内清理所有关联数据。自动发现正在运行时暂不允许编辑、复制和删除，避免后台任务与操作冲突。

复制课程会创建新课程 ID 和新小节 ID，保留基本信息、小节顺序、知识原子与关系结构。为了保留有效原文引用，同时复制资料快照并重映射来源 ID；不会重新抓取网页。复制后的非弃用原子标为 candidate，来源冲突重新等待确认。不复制讲解、对话、独立测试、阅读／复习事件、掌握状态、生产批次或自动发现运行记录，课程从第一节开始，状态为学习中。复制本身是用户主动的结构复制，不是模型候选自动导入。

## 数据模型

兼容已有 `courses.id/session_id/title/goal/current_ordinal/created_at` 和来源策略字段。新增 `description`、`cover`、`tags_json`、`status`、`sort_order`、`level`、`updated_at`、`deleted_at`。接口提供 `name` 作为 `title` 的别名。现有 `session_id` 保持课程所有权隔离，当前本机原型没有独立账号体系，因此没有虚构新的 user_id 或迁移既有课程关联。课程审查稿的基本信息保存在 `management_json`，修改审查方向时仍保留。

旧数据库自动加列，原记录默认学习中、入门，初始顺序沿用旧列表顺序，迁移不清空学习记录。迁移再次执行不会重置状态或排序。

## 接口

| 操作 | 接口 | 内容 |
| --- | --- | --- |
| 列表 | GET `/api/courses` | 可传 status；`deleted=true` 查看回收站 |
| 基本信息 | GET `/api/courses/{id}` | 仅返回当前会话拥有的课程 |
| 创建 | POST `/api/courses` | 名称／目标及可选基本信息，返回课程审查稿 |
| 确认创建 | POST `/api/courses` | `confirm:true, draft_id, revision`，用户确认后创建并自动发现 |
| 修改 | PUT `/api/courses/{id}` | name/title、description、cover、tags、goal、level、status |
| 排序 | PUT `/api/courses/order` | 完整数组 `[{id,sort_order},…]` |
| 状态 | PUT `/api/courses/{id}/status` | `{status:"active/paused/completed/archived"}` |
| 移入回收站 | DELETE `/api/courses/{id}` | 保留关联数据 |
| 恢复 | POST `/api/courses/{id}/restore` | 无需新建课程 |
| 复制 | POST `/api/courses/{id}/copy` | `{}` 或指定 name/title |
| 永久删除 | DELETE `/api/courses/{id}/permanent` | `{confirm_title:"完整课程名称"}` |

保留原有 `/api/courses/draft`、`/api/courses/confirm` 和学习接口，创建始终经过方向审查。所有写操作沿用本机请求检查和当前浏览器会话所有权验证。

前端沿用原生 DOM，模块位于 `web/components/CourseManager/course-manager.js`，内部组件为 CourseList、CourseCard、CourseEditor、CourseMenu、SortableCourseList、DeleteConfirm；无需新增前端框架。

验证包含数据库迁移、课程所有权、软删除保留历史、恢复、永久删除的外键完整性、完整排序校验、复制后的来源重映射及掌握隔离，以及真实浏览器中的编辑、归档、拖拽、刷新、回收站、创建和 390px 布局。测试使用临时数据库与模拟模型，不操作真实课程。
