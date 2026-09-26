# 课程包格式草案 v0.1.0

课程包将学科内容与平台流程分开，使同一套检索、诊断、规划和记录机制能够接入不同课程。当前只定义公开练习包，应用导入与运行服务尚未实现。

## 目录

```text
course-packs/
  python-foundations/
    manifest.json
    materials/
      functions.md
  linear-algebra/
    manifest.json
    materials/
      dot-product.md
```

每个包有独立课程编号与版本。目录名与 `id` 一致，编号使用小写英文、数字和连字符。课程包之间可以使用相同的局部知识点编号，应用中需以课程与版本共同定位。

## 清单字段

| 字段 | 作用 |
| --- | --- |
| schema_version | 当前固定为 0.1.0，指格式版本 |
| id / version | 课程编号与内容版本，例如 python-foundations / 0.1.0 |
| title / language / level / audience | 课程名称、语言、层级与适用人群 |
| license / review_status | 许可与审核状态，未审核使用 draft |
| learning_goals | 可由任务检查的学习目标 |
| dimensions | 该课程自己的能力维度，包含 id、label、description |
| concepts | 知识点及其适用维度 |
| relations | 知识关系，使用 from、to、type |
| resources | 原文位置、知识点关联、许可和来源说明 |
| tasks | 公开练习及知识点、维度、评分标准和参考答案 |

结构定义见 [JSON Schema](../schemas/course-pack.schema.json)。Schema 负责格式，检查工具补充引用、循环与文件路径检查。

## 知识关系

- `prerequisite`：from 是 to 的先修知识；先修关系不得成环。
- `part_of`：from 是 to 的组成部分。
- `related`：两个知识点相关，不自动推导先修顺序。

课程编辑者负责审核关系的教学合理性。不同课程之间的关联及知识状态迁移不在本格式自动推断。

## 资源

v0.1.0 的资源为课程目录内 UTF-8 Markdown 文件。`path` 使用以课程目录为起点的相对路径。保留标题和完整语义单元，后续导入时再由索引流程切分。

`provenance` 说明原创情况或准确来源，`license` 标明资源自己的许可。新增第三方内容需具备分发权限，并保留要求的声明；只具备阅读权限的资料不能直接复制进公开包。

## 任务与评分

当前支持声明三种任务：`short_answer`、`numeric`、`code`。它们是任务数据类型，目前没有自动评分服务或代码执行器。

每个任务包含：

- `purpose` 固定为 `practice`，标明公开练习用途。
- `prompt` 描述学生任务。
- `concept_ids` 和 `dimension_ids` 指明考查范围。
- `rubric` 逐项记录维度、评分要点和满分。
- `reference_answer` 提供公开参考答案；数值任务使用 JSON 数值，其他任务使用文本。

评分要点中的维度集合必须与任务维度一致，任务维度属于其关联知识点的适用维度。各课程量表独立解释，不将数学计算分数直接映射到代码实现分数。

公开练习的答案可以供读者查看。未来应用导入时，将资料、学生可见题面和评分材料按用途拆分，教学检索不默认索引整份清单。正式前后测、隐藏测试和实际试点答案存放在私有运行数据中，不进入这个公开格式。

## 新增课程

1. 新建课程目录，复制一个现有清单作为起点。
2. 修改课程编号、目标和适用人群，定义本课程维度。
3. 增加知识点、先修关系、原创或可分发资料。
4. 编写少量代表性任务和明确评分标准，保持 `review_status: draft`。
5. 运行 `python scripts/validate_course_packs.py`，提交内容供审核。

结构检查不会评估答案是否正确、题目是否等价或教学是否有效，也不会确认资料许可。审核后再更新状态，并在贡献说明中记录审核方式。
