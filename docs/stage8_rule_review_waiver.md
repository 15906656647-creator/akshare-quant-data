# Stage8 人工复核豁免机制

> 文档状态：已启用
> 适用范围：`data/manual/stage8/limit_rules` 与
> `data/manual/stage8/security_status` 的 `dataset.yml` 和记录 CSV
> 基线日期：2026-07-27

## 1. 目的

`approved_with_waiver` 是普通 `approved` 之外的独立审核状态，只允许项目
负责人显式接受“无法完成双人复核”的风险。该状态不替代双人复核，也绝不把
未复核记录伪装成已复核。项目用途为研究与测试，不构成投资建议。

## 2. 必填治理字段

使用 `approved_with_waiver` 时，dataset manifest 和每条记录必须填写：

- `review_status: "approved_with_waiver"`
- `review_mode: "waiver"`
- `waiver_reason`：非空，说明豁免原因与已接受风险
- `waiver_approver`：非空，项目负责人身份
- `waiver_at`：带时区的 ISO 时间
- `waiver_document`：必须为 `docs/stage8_rule_review_waiver.md`

`reviewer` 在豁免记录中留空。任何为通过门禁而伪造 `reviewer`、审核人或
审核时间的行为都属于治理违规，数据不得发布。

## 3. 校验边界

`approved_with_waiver` 只覆盖审核签字方式，不豁免任何数据校验：

- 来源登记等级必须为 A
- 原始文件必须存在且 SHA-256 一致
- 日期区间、冲突规则、覆盖规则全部必须通过
- `pending`、`rejected` 和字段缺失状态仍然 fail-closed
- 普通 `approved` 仍要求真实 `reviewer`

## 4. 输出标记

下游 Stage8、Stage15 和 S15-14 报告必须保留：

```text
review_status = approved_with_waiver
review_mode = waiver
verified_by_dual_review = false
```

豁免记录不得被输出为 `verified_by_dual_review = true`，也不得被描述为
“双人审核完成”。

## 5. 使用步骤

1. 完成全部来源、哈希、区间、冲突和覆盖校验，仅双人签字无法完成。
2. 项目负责人在本机制下填写豁免原因并签字。
3. 将 `dataset.yml` 与每条记录改为 `approved_with_waiver`，填写完整豁免
   字段。
4. 执行 `--validate-only`；全部 PASS 后才允许正式发布。
5. 任何后续记录变化都必须重新执行同一套校验。

## 6. 禁止事项

- 禁止伪造 `reviewer`、审核人或审核时间。
- 禁止把 `approved_with_waiver` 误报为普通 `approved` 或“双人审核完成”。
- 禁止以豁免绕过来源、哈希、区间、冲突和覆盖校验。
- 禁止输出投资建议。

## 7. 本次真实应用记录

本记录仅使用
`reports/stage8_rule_review_waiver/real_decision/waiver_decision.json`
中的真实豁免信息。

- 豁免范围：`Stage8 authoritative limit rules dataset`
- 豁免原因：`无`
- 风险接受人：`zzzf`
- 风险接受时间：`2026-08-06T12:02:32+08:00`
- 豁免文档：`docs/stage8_rule_review_waiver.md`

已完成的专项核验：

- 四份规则正文来源文件存在，且 SHA-256 与 `dataset.yml` 和
  `source_registry.yml` 登记一致。
- 规则日期覆盖 `2025-07-27` 至 `2026-07-27` 无缺口、无重叠。
- 规则矩阵保持 6 组、每组 2 条，共 12 条；2026 版风险警示比例仍为
  深市主板 10%、深市创业板 20%、沪市主板 10%。
- 12 条记录全部为 `approved_with_waiver`、`review_mode=waiver`，
  `reviewer` 为空，`verified_by_dual_review=false`。

未完成事项：

- 双人独立人工审核未完成，本豁免不构成双人复核完成。

剩余风险：

- 未完成双人独立人工审核是主要剩余风险。
- 2026 版深交所/上交所规则正文未单列风险警示比例，草案按一般条款
  3.3.13 处理；该推导仍需在后续独立复核中确认无其他特别规定。
