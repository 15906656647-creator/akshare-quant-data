# 权威证券状态历史（authoritative_security_status_history）

本目录用于存放人工收集、登记并复核的正式证券状态历史（ST/LISTING）。
真实文件 `dataset.yml`、`security_status_history.csv` 与 `sources/` 下的
原始文件已被 `.gitignore` 排除；本目录提交的是字段模板、虚构示例、来源
登记模板、人工审核清单和校验说明。

## 文件约定

| 文件 | 说明 |
| --- | --- |
| `dataset.yml` | 真实数据集清单与来源登记（人工创建，gitignored） |
| `security_status_history.csv` | 状态历史记录（人工创建，gitignored） |
| `sources/` | 官方公告/检索结果等原始证据（gitignored） |
| `dataset.schema.yml` | 字段模板与取值规范（已提交） |
| `dataset.example.yml` | 虚构样例清单，正式构建绝不读取（已提交） |
| `security_status_history.example.csv` | 虚构样例记录（已提交） |
| `source_registry.template.yml` | 来源登记模板（已提交） |
| `review_checklist.template.md` | 双人复核清单（已提交） |
| `validation_notes.md` | 校验规则说明（已提交） |

## 状态类型

- `status_type = ST`：`status_value` 为 `NON_ST`/`ST`/`*ST`/`OTHER`。
- `status_type = LISTING`：`status_value` 为 `LISTED`/`SUSPENDED`/`DELISTED`。

非 ST 区间必须由正式证据（官方列表 + 官方公告检索零变更等）支持，禁止仅凭
当前快照或曾用名推断。
