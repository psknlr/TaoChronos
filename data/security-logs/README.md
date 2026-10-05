# 安全事件记录（哨兵）

两个 Worker 的哨兵（`security/sentinel.js`，见 [`security/README.md`](../../security/README.md)）记下的**可疑请求**：扫描器路径的探测、
非浏览器客户端的调用、超过阻断分数的地址、浏览器上报的内容安全策略（CSP）违规。由 `.github/workflows/chat-logs.yml` 每小时从
中转（`relay/`，`/v1/security/export`）与网站（`cloud/site/`，`/api/security/export`）取回，写成 `<来源>/年/月/日.jsonl`（按 Worker 收到
的日期，UTC），一行一个事件；`cursor.json` 记每个来源已取回的最后一条编号。推送成功后才通知 Worker 删除。

**这里有被标记请求的网络地址与请求头。仓库须保持私有。** 正常访客（分数为 0 的请求）不在这里：他们在 Worker 里只留下一个按哈希计的计数。

| 字段 | 含义 |
|---|---|
| `n`、`received`、`source` | Worker 的事件编号（递增，不重复）、收到的时间（UTC）、来源（`relay` / `site`） |
| `kind` | `honeypot`（扫描器路径）、`flag`（分数 ≥ FLAG_SCORE，已服务）、`shadow`（观察模式下本应阻断）、`block`（本次开始阻断）、`blocked`（阻断期间仍在请求）、`csp`（浏览器的策略违规报告） |
| `score`、`reasons` | 分数与各项理由（`ua_tool`、`no_sec_fetch`、`dc_asn`、`origin_foreign`、`no_system`、`replay`、`burst`、`probing`……，见 `security/README.md` 的表） |
| `route`、`status` | 命中的接口类别（chat / logs / api-read / api-call / page / honeypot / other / csp）与返回的状态码（未知时为 null） |
| `who` | 访客的哈希键（有 `SENTINEL_SALT` 时跨月不变；否则按月） |
| `fp` | 请求指纹：地址（`ip`）、网络（`asn`、`asOrg`）、国家与城市、Cloudflare 节点（`colo`）、协议（`proto`）、TLS 版本与密码套件、ClientHello 长度与扩展摘要、往返时延（`rtt`）、请求头（`ua`、`accept`、`lang`、`origin`、`referer`（只保留来源）、`sfSite`/`sfMode`/`sfDest`、`chUa`……）、`uaClass`、`traversal` |
| `shape` | 中转的模型调用请求的形状：消息数、字数、是否以系统提示开头（`system`）、系统提示与最后一问的哈希（`sys`、`q`，不含正文）、是否流式、工具数、`max_tokens` 字段名 |
| `decision` | 当时的模式与结论：`blocked`、`shadow`、`until`（阻断到何时） |
| `state` | 该访客的累计：请求数 `n`、错误数 `bad`、被标记次数、阻断次数、十秒内与十分钟内的请求数、同一问题的重复数、探测过的路径数、不同 UA 数、最近的 404 路径、网络 |
| `reports` | `csp` 事件：浏览器上报的违规，每条缩减为 `directive`（指令）、`blocked`（被拦资源的来源）、`document`（页面地址，不含查询串）、`disposition`、`source`（出处文件，不含查询串）、`line`、`status`——不留原文、查询串与页面文字 |
