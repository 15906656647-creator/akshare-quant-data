# Stage 2 Network Preflight

- Checked at: `2026-07-29T06:50:45.461532+00:00`
- Overall status: **PASS**
- Proxy environment detected: `False`
- CA environment configured: `False`

Only environment-variable presence is reported; proxy and CA values are never recorded.

| host | DNS | TCP 443 | TLS | error layer | error type |
|---|---|---|---|---|---|
| push2his.eastmoney.com | pass | pass | pass | - | - |
| push2.eastmoney.com | pass | pass | pass | - | - |
| quotes.sina.cn | pass | pass | pass | - | - |
| money.finance.sina.com.cn | pass | pass | pass | - | - |
| emweb.securities.eastmoney.com | pass | pass | pass | - | - |
| datacenter-api.jin10.com | pass | pass | pass | - | - |

This diagnostic performs DNS resolution, TCP 443 connection, and TLS handshake only. It does not request or save financial data.
