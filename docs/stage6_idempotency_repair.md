# 阶段6持久化幂等性与事务异常保留修复

- 修复状态：**PASS**
- 阶段7入口：关闭
- feature_run_id：`48af48ca-2707-4c53-ad51-745a17b6295d`

## 修复结果

- 同run、同路径、同一完整非空输入第二次持久化：`idempotent_reuse`。
- 14/14张表的行数、业务键哈希和内容哈希保持不变。
- 9/9个Feature文件复用，未重写。
- Feature文件和数据库payload冲突均以`Stage6PayloadConflictError`明确拒绝。
- rollback失败仅作为secondary note，未覆盖原始业务异常。
- Raw、Clean、阶段5数据库和正式阶段6产物均未修改。

## 阶段边界

本修复完全离线，只使用临时Feature目录和临时DuckDB执行复跑；未执行正式build-stage6，未生成排名、交易信号、投资建议或阶段7产物。
