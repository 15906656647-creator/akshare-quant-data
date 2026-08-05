# 权威涨跌停规则历史（authoritative_limit_rules）

本目录用于存放人工收集、登记并复核的正式涨跌停规则历史。真实文件
`dataset.yml`、`limit_rules.csv` 与 `sources/` 下的原始文件已被
`.gitignore` 排除，不会进入 Git；本目录提交的只是字段模板、虚构示例、
来源登记模板、人工审核清单和校验说明。

## 文件约定

| 文件 | 说明 |
| --- | --- |
| `dataset.yml` | 真实数据集清单与来源登记（人工创建，gitignored） |
| `limit_rules.csv` | 规则历史记录（人工创建，gitignored） |
| `sources/` | 原始正式文件（PDF/官方网页快照等，gitignored） |
| `dataset.schema.yml` | 字段模板与取值规范（已提交） |
| `dataset.example.yml` | 虚构样例清单，正式构建绝不读取（已提交） |
| `limit_rules.example.csv` | 虚构样例记录，正式构建绝不读取（已提交） |
| `source_registry.template.yml` | 来源登记模板（已提交） |
| `review_checklist.template.md` | 双人复核清单（已提交） |
| `validation_notes.md` | 校验规则说明（已提交） |

## 生效区间规范

- 日期一律使用 ISO 格式 `YYYY-MM-DD`。
- 区间采用仓库统一规范：闭区间 `[effective_from, effective_to]`。
- `effective_to` 为空表示仍有效。
- `effective_from` 不得晚于 `effective_to`。

## 来源等级

- A 级：交易所正式交易规则、官方规则摘要或可下载的正式文件，可作为正式输入。
- B 级：辅助校验来源（当前列表、当前快照等），禁止回填历史。
- C 级：不可使用（例如无生效日期的曾用名列表、空检索结果、失败接口）。

仅 `grade: "A"` 的来源可以登记到 `dataset.yml` 并通过校验。
