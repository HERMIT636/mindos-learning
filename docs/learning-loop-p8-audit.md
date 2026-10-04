# Learning Loop P8 只读审计

日期：2026-10-04；基线：5ceba62bd654ceb9dafdc325eaa4807664e3d51e；发布目录 Git 工作区初始干净。以实际文件为准。

| 项目 | 现状与接入决定 |
|---|---|
| Atom | course_graphs JSON；知识点课程内隔离，quality_status 可 deprecated；不增加资源型原子 |
| Course/Lesson | SQLite，课程软删除、章节显式推进；资源关联独立，不写学习表 |
| Markdown | TeachingBlocks 安全 DOM 分段，不执行 HTML；复用 prose |
| Formula | 原公式是 pre 文本；新增本地公式排版，不改变原教学协议 |
| Code | 原有 pre，不执行；新材料视图安全高亮和复制 |
| Image | 没有学习材料图片存储；新增本地文件、安全格式检验和所有权文件接口 |
| Upload | SourceDocument 上传支持 PDF/TXT/MD/DOCX/PPTX，6 MB；会增加课程 revision，不能复用于个人资源保存 |
| 文件目录 | 默认 data/ 数据库；材料文件存数据库同级 resources/，排除 Git |
| 删除/复制 | 软删除保留；永久删除逐表清理；资源 mapping 使用 course FK cascade，边界钩子清理无关联生成资源，复制仅共享非个人生成材料 |
| P6 Context | 服务端课程、章节、知识点选择器，不接受浏览器掌握状态；增加独立资源适配器 |
| P7 Detail | 只读投影，只有小卡片；选择星辰后新增完整知识空间，保留原图与返回入口 |
| Search | 同一个 public Wikipedia/GitHub、Brave、Tavily 入口；不自动查全网论文；确认后关联，URL 默认仅参考链接 |
| Migration | Storage 逐模块 migrate；新增两张表和索引，不改旧结构 |
| Local file | 原上传只保存抽取正文；P8 保存原文件，资源 ID 文件名，禁任意路径 |
| Hash | SourceDocument 已有 SHA；P8 原始文件 SHA、atom/course context fingerprint，与 generated needs_review 独立 |
| Existing imports | 用户来源已进入候选审查流水线；不得未经确认导入图谱，不复制为资源证据 |

## 边界设计

资源类型保持 text/formula/code/image/diagram/paper_excerpt/reference/practice 八种。PDF 原文件采用 reference 资源（pending/failed，metadata.document=true），选页后产生独立 paper_excerpt 子资源；容器不进入导师正文。摘要保持派生关系，不能覆盖原文。图片第一版只传用户说明与替代文字，明确模型未看图，不声称视觉识别。

原 P6/P6.5/P7 后端核心文件冻结。P8 的资源模型适配器在原 QualityTutorService 的两次尝试内添加材料、引用校验与 grounding 规则；最终仍接受原协议和质量控制。资源输入属于不可信资料，不能成为系统指令；引用有效不等于事实正确。强制仅材料模式不调用外部搜索，资料不足必须明确说明。

课程删除/复制仅在现有 HTTP 管理入口增加资源生命周期钩子；资料关联 FK cascade 与独立资源所有权保护原文件。P5 学习计时仅在主动点击后调用已有接口；P2 实践进入既有开放任务，继续原提示标记和评分边界。查看资源与聊天不自动生成掌握证据。

## 验证计划

原 611 项回归；资源类型、文件、所有权、引用、派生/删除/复制、上下文预算、重复请求、grounding、失败路径、真实评分前后隔离；1440/390 浏览器真实导航/上传/选页/渲染/问导师；临时数据库与配置的真实模型四案例；冻结文件 SHA、根目录与发布目录字节同步、远端 HEAD。真实模型能力与模拟验证分别报告。
