# P9 实践空间

用户从“成长路线”的实践建议或主导航“实践空间”进入。先明确要交付的成果，再审查与修改计划，确认后启用。任务、里程碑、实验记录和产出属于执行记录，不是新的课程或知识星辰。

## 实际模块协作

|职责|实现与边界|
|---|---|
|项目与执行计划|`mindos/mission/service.py`、`planner.py`；七张新表。规划读取已有课程、记录中的知识状态和原 P4 缺口；模型草稿只在用户确认后写入任务。|
|实验|实验说明存入任务 metadata；多次运行记录在 mission_experiment_runs，参数与指标必须有限。只记录用户自行运行的结果，不执行代码；比较同名指标不自动判断因果。|
|产出|mission_artifacts 独立于 knowledge_resources，固定随机 ID 文件名、SHA-256、父版本与版本号；代码仅阅读，二进制模型只提供元数据。|
|文件安全|共用 SafeFiles 路径、排他写入和读取检查；格式、UTF-8、图片解码、PDF 选页复用 P8 processing。额外代码/CSV/JSON 扩展名只作为文字预览，不运行。|
|计时|原 StudySessionService，activity_type=goal_task；用户另行点击开始用时记录。session ID 放在任务 metadata，结束计时不会完成任务；UI 展示原 P5 的个人估时，保留任务初始估时。|
|材料|任务引用既有 P8 资料，不拷贝材料表。用户明确“保存为学习资料”才创建派生 P8 记录，附原产出 ID/哈希；仍需关联 owned course/atom。引用中的资料禁止直接删除。|
|导师|MissionContextBuilder/MissionAwareModel 是现有 P6/P6.5 的输入适配器，仍调用 QualityTutorService 与 ModelGateway；沿用原最多两次的质量循环、课程聊天历史和悬浮导师。没有 ProjectChatBot。|
|候选与独立验证|ProjectEvidenceBridge 只保存 user_artifact_claim/candidate；模型点评不可写能力。用户确认后调用原 P2 design/open_transfer，生成新的陌生任务；产出正文和点评不传入独立题目。|
|成长闭环|关联目标能力与原当前成长实践任务时，复用原 practice_context/attach_authentic；合格独立结果由原 P4 判断实践缺口，再由用户检查目标/重规划。未关联时，P2 结果仍有效保存，但不能自动声称已满足具体成长目标。|

独立提交后的原 P2 会保存 `project_evidence` 影子观察并应用原校准条件。这不等于上传产出变成掌握证据，也不直接提高课程掌握率。P9 不修改 P0–P8 的知识状态、校准、评分或目标完成算法。

## 计划与完成要求

模型返回包含 milestones/tasks 的严格执行计划；不存在 mastery 字段。前置依赖必须指向较早任务。缺失课程 ID 但提供了知识点 ID 时，只有实际输入中存在唯一、已开放的 owned course/atom 才补齐；不明确或他人的关联仍拒绝。无效响应至多修订一次，之后显示明确标记的可编辑规则草稿，不能称模型生成成功。

确认草稿使用 draft_version；编辑项目、开始任务、上传产出等会使旧草稿失效。重新规划保留固定、已完成、正在执行或已有产出/实验/复盘/计时记录的任务及其前置里程碑；旧计划有版本记录，旧任务不会物理删除。为保留依赖次序，保护范围采用这些任务所在里程碑之前的完整前缀，而非仅保留孤立任务。

开始下一里程碑必须满足前面必需里程碑，最多一个里程碑进行中。完成任务要求显式开始、前置完成、必要产出和实验记录；任务完成后按实际 gate 更新里程碑。项目完成再次核对所有必需任务、里程碑、产出和运行记录。跳过必需任务不满足完成要求；用户明确编辑 required 才改变项目执行范围。

实际结果 success/partial/failed/withdrawn 与项目执行状态独立。失败不会降低知识状态或生成已确认误解，项目完成不会让目标自动 achieved。

## 文件与模型上下文

文字最大 5 MB，图片 10 MB，PDF/二进制模型 30 MB；大日志先截取相关片段。SVG/HTML、压缩包和可执行文件不接收。图片复用 P8 实际解码验证，扫描 PDF 不做 OCR。

预览文字最多 12,000 字，导师每份产出最多 3,000 字、最多四份、最近三次运行；整体实践上下文连同参数、说明与编码开销最多 10,000 字，导师总请求最多 32,000 字。代码、JSON、CSV 安全展示，不执行，不把文件名当正文。无选页 PDF 或二进制模型明确说明无法读取。文字导师不声称看到图片细节。

“只根据此产出”模式只发送选中产出的有限原文，移除课程内容、共享课程对话、成长任务正文和其他材料；课程标签和真实知识状态只用于调整教学方式。原文引用必须逐字存在于实际传入片段。普通实践模式也不把同一课程其他项目的历史对话当作当前实验事实。

删除需要确认；父版本、运行记录、复盘、候选、派生资料及必要交付仍引用时拒绝删除。课程回收/删除后不再作为新的导师或独立任务上下文；目标删除后项目历史仍保留，关联需重新选择。MindOS 不替用户运行实验、提交比赛、安装环境或管理 Git。

## 接口

|入口|功能|
|---|---|
|GET/POST /api/missions|本人列表、确认创建|
|GET/PATCH /api/missions/{id}|详情、基本信息/状态/结果修改|
|GET /api/missions/recommendations?goal_id=...|原 P4 目标实践建议；优先继续已有项目|
|POST .../plan/generate、.../plan/confirm、.../replan|草稿、版本确认、重规划草稿|
|POST .../tasks/{task}/start/complete/skip/resume/lock|执行状态与固定|
|PATCH .../tasks/{task}|任务设置与课程/知识点/成长任务/材料关联|
|POST .../tasks/{task}/study/start|明确开始原 P5 计时|
|POST .../tasks/{task}/runs、.../compare|记录实际实验、选择 2–5 条比较|
|POST .../artifacts/upload|上传产出，类型和内容分开校验|
|GET .../artifacts、.../artifacts/{artifact}/file|本人产出与文件|
|GET/POST .../artifacts/{artifact}/preview|有限正文与 PDF 明确选页|
|POST .../artifacts/{artifact}/promote|明确创建派生学习资料|
|DELETE .../artifacts/{artifact}|确认并检查引用后永久删除|
|POST .../reflections|用户确认复盘|
|POST .../evidence/analyze、.../evidence/{candidate}/verify|候选点评、原 P2 独立验证|
|GET .../evidence/{candidate}、.../status|原验证结果、执行要求|
|POST .../tutor/chat|原 P6/P6.5 导师加当前实践上下文|

所有入口验证用户/项目/课程/产出/资料所有权；客户端不能提供评分、知识状态或伪造预览正文。

## 验证与限制

实施前审计见 [learning-loop-p9-audit.md](learning-loop-p9-audit.md)。原始冻结哈希见 [learning-loop-p9-frozen.json](learning-loop-p9-frozen.json)；仅允许 P8 ResourceService 文件路径与写入委托共用 SafeFiles，其余核心语义未改。

实际测试记录见 `docs/validation/learning-loop-p9-2026-10-04.json`、`learning-loop-p9-browser.json`、`learning-loop-p9-regression-browser.json`、`learning-loop-p9-real-2026-10-04.json`。真实模型报告的实验数字是合成验收输入，未执行真实 benchmark；五个场景中的模型调用与确定性规则检查分别记录。不证明真实用户学习效果或一般性事实认证。

当前导师仍需任务关联真实课程；用户可以在无课程时创建和执行项目、记录产出及用时，但需要关联课程/知识点后才能使用课程导师和独立验证。这是原 P6/P2 上下文边界，不创建伪课程。AI 复盘建议可在导师中讨论，只有用户填写并确认才保存；不自动生成用户复盘。没有云端代码执行或比赛自动提交。
