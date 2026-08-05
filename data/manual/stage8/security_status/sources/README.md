# 原始证据文件目录

把交易所官方状态公告、官方检索结果或可下载的正式文件放入本目录，并在
`dataset.yml` 的 `sources` 中登记文件名与 SHA-256。

计算哈希（PowerShell）：

```powershell
Get-FileHash -Algorithm SHA256 .\sources\文件名.pdf | Select-Object Hash
```

本目录内容被 `.gitignore` 排除，仅本说明文件提交。
