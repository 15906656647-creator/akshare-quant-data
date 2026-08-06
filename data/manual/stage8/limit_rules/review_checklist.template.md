# 权威涨跌停规则人工审核清单

> 每条规则必须由两人独立复核并签字；任何一项未通过都不得发布。

## 来源核查
- [ ] 来源属于 A 级（交易所正式规则或官方可下载文件）。
- [ ] 来源不是当前快照、曾用名列表或辅助校验来源。
- [ ] `source_document_id`、`source_reference` 与原始文件一一对应。
- [ ] `sources/` 原始文件存在，且 `Get-FileHash` 与登记 SHA-256 一致。

## 规则内容
- [ ] `market` 与 `exchange` 一致（SH/SZ/BJ）。
- [ ] `board` 与 `security_type` 与正式规则适用范围一致。
- [ ] `rule_type` 正确区分普通/ST/上市首日/无涨跌幅限制。
- [ ] `limit_ratio`（及 `limit_down_ratio`）与规则原文一致。
- [ ] `effective_from`/`effective_to` 与规则生效/废止日期一致。
- [ ] 同一市场、板块、证券类型不存在重叠或冲突区间。

## 覆盖
- [ ] 覆盖分析窗口 `2025-07-27` 至 `2026-07-27`。
- [ ] 覆盖 16 只样本股票所需的市场/板块/ST 组合。
- [ ] 上市首日规则覆盖样本股票的实际上市首日。

## 人工复核豁免（仅在无法完成双人复核时使用）
- [ ] `review_status` 必须为 `approved_with_waiver`，`review_mode` 必须为
      `waiver`，不得把豁免记录标成普通 `approved`。
- [ ] `reviewer` 留空，不得伪造复核人；项目负责人以 `waiver_approver`
      身份显式接受风险。
- [ ] `waiver_reason` 非空，说明为何无法完成双人复核及已接受的风险。
- [ ] `waiver_at` 为带时区的 ISO 时间。
- [ ] `waiver_document` 必须为 `docs/stage8_rule_review_waiver.md`，且该文档
      已随仓库存在。
- [ ] 来源、区间、覆盖、哈希与规则内容核查仍全部通过；豁免只覆盖审核签字
      方式，不豁免数据校验。

## 复核签字
- 整理人：____________ 日期：____________
- 复核人 1：____________ 日期：____________
- 复核人 2：____________ 日期：____________
- 结论：`approved` / `approved_with_waiver` / `rejected`
  （`approved_with_waiver` 必须同时完成豁免字段；`rejected` 时说明原因并重新整理）
