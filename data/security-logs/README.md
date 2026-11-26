# 安全事件记录（哨兵）

两个 Worker 的哨兵（`security/sentinel.js`，见 [`security/README.md`](../../security/README.md)）记下的**可疑请求**：扫描器路径的探测、
非浏览器客户端的调用、超过阻断分数的地址、浏览器上报的内容安全策略（CSP）违规。由 `.github/workflows/chat-logs.yml` 每小时从
中转（`relay/`，`/v1/security/export`）与网站（`cloud/site/`，`/api/security/export`）取回，写成 `<来源>/年/月/日.jsonl`（按 Worker 收到
的日期，UTC），一行一个事件；`cursor.json` 记每个来源已取回的最后一条编号。推送成功后才通知 Worker 删除。

**这里有被标记请求的网络地址与请求头。仓库须保持私有。** 正常访客（分数为 0 的请求）不在这里：他们在 Worker 里只留下一个按哈希计的计数。

Worker 绑定了归档存储桶后（仓库变量 `ARCHIVE_BUCKET`，[ADR 0023](../../docs/adr/0023-workers-paid.md)），它的新事件存进私有 R2 存储桶
（`security-logs/<来源>/年/月/日/编号.json`，一个事件一个对象，字段同下），不再进入本目录；读回某天：`python3 security/collect.py archive --day …`。

| 字段 | 含义 |
|---|---|
| `n`、`received`、`source` | Worker 的事件编号（递增，不重复）、收到的时间（UTC）、来源（`relay` / `site`） |
| `kind` | `honeypot`（扫描器路径）、`flag`（分数 ≥ FLAG_SCORE，已服务）、`shadow`（观察模式下本应阻断）、`block`（本次开始阻断）、`blocked`（阻断期间仍在请求）、`csp`（浏览器的策略违规报告） |
| `score`、`reasons` | 分数与各项理由（`ua_tool`、`no_sec_fetch`、`dc_asn`、`origin_foreign`、`no_system`、`replay`、`burst`、`probing`……，见 `security/README.md` 的表） |
| `route`、`status` | 命中的接口类别（chat / logs / api-read / api-call / api-research / page / honeypot / other / csp）与返回的状态码（未知时为 null） |
| `who` | 访客的哈希键（有 `SENTINEL_SALT` 时跨月不变；否则按月） |
| `fp` | 请求指纹：地址（`ip`）、网络（`asn`、`asOrg`）、国家与城市、Cloudflare 节点（`colo`）、协议（`proto`）、TLS 版本与密码套件、ClientHello 长度与扩展摘要、往返时延（`rtt`）、请求头（`ua`、`accept`、`lang`、`origin`、`referer`（只保留来源）、`sfSite`/`sfMode`/`sfDest`、`chUa`……）、`uaClass`、`traversal` |
| `fp`（未被标记的访客） | 2026-11-25 起，没被标记的访客的事件（只有 `csp` 报告会这样）**不带地址**：只有 `ts`、`method`、`host`、`path`、`asn`、`country`、`proto`、`uaClass`、`browser`（引擎/版本）、`xrw`（应用内浏览器的包名）。研究任务与会话的编号在 `path` 里记作 `…` |
| `shape` | 中转的模型调用请求的形状：消息数、字数、是否以系统提示开头（`system`）、系统提示与最后一问的哈希（`sys`、`q`，不含正文）、是否流式、工具数、`max_tokens` 字段名 |
| `decision` | 当时的模式与结论：`blocked`、`shadow`、`until`（阻断到何时） |
| `state` | 该访客的累计：请求数 `n`、错误数 `bad`、被标记次数、阻断次数、十秒内与十分钟内的请求数、同一问题的重复数、探测过的路径数、不同 UA 数、最近的 404 路径、网络 |
| `reports` | `csp` 事件：浏览器上报的违规，每条缩减为 `directive`（指令）、`blocked`（被拦资源的来源）、`document`（页面地址，不含查询串）、`disposition`、`source`（出处文件，不含查询串）、`line`、`status`——不留原文、查询串与页面文字 |

## 边缘的记录（`edge/`）

`security/events.py` 每天从 Cloudflare 的 GraphQL 分析接口取回（`security/README.md`「数据与日常」）：

| `kind` | 含义 |
|---|---|
| `firewall` | 边缘的安全事件：哪条规则对哪个请求做了什么（`action`、`ruleId`、`rayName`、`clientIP`、`userAgent`、`clientRequestPath`……） |
| `requests` | 值得一看的请求组（同一地址、UA、路径、状态、方法）：`requests`（次数）、`why`（`status_4xx`、`security_block`、`scanner_path`、`ua_tool`、`ua_empty`、`volume`，以及 `artifact_agent`、`artifact_volume`：用工具或成批取走运行环境文件的；后者带 `fetched`，当天的次数）、`bytes`（计划提供时） |
| `artifacts` | 运行环境文件（`/runtime/` 下）一天的下载合计，按 `path`、`status`、`method`、`agent`（UA 的种类）：`requests`、`bytes`、`addresses`（多少个不同的地址）、`complete`（当天的请求组是否取全）。**没有地址**：这是每个读者自己的下载 |
| `traffic` | 当天到这个主机的**全部**请求，按 `country` 与 `status` 合计：`requests`、`bytes` 与 Cloudflare 自己数的 `visits`（计划提供时）、`complete`。**没有地址、路径与 UA**。Worker 看到的与没看到的（不经 Worker 的静态文件、被边缘拦下的请求）都在内：活动账本的计数拿它做对照（`data/activity-analytics/README.md`） |

请求组（`requests`）的次数是**整天的**：同一组在几个时间窗口里出现的合成一行（2026-11-25 之前只是第一个窗口的数）。某天被重新取回时，每行取较大的数。

研究任务与会话的编号不进这里：路径记作 `/api/research/…`、`/api/session/…`。
