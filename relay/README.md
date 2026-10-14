# 道乃久默认服务（relay）

网页（chat.impf.ai）与 MiniMax 之间的中转：访客不填 API Key 就能提问。**MiniMax 密钥只作为这个 Cloudflare Worker 的
加密机密（secret）存在**——不进网页、不进仓库、不在任何日志里显示；浏览器发来的请求不带任何密钥，由中转在服务端加上。
（密钥若放进静态网页，无论怎样加密，浏览器都得先解密再用，任何访客都能在开发者工具里看到。）

```
浏览器（chat.impf.ai） ──无密钥──▶ chat-api.impf.ai（本 Worker：加上密钥、限流） ──▶ MiniMax
        └─ 访客同意后：每轮问答一条记录 ──▶ Worker 暂存 ◀── 仓库的 chat-logs 工作流每小时取走，提交到 data/chat-logs/
```

| 接口 | 作用 |
|---|---|
| `POST /v1/chat/completions` | 转发网页的模型调用（流式）；只接受网页来源（`ALLOWED_ORIGINS`）、只接受默认服务的模型（公开名 `PUBLIC_MODEL`，即 Tao-R1）、输出上限 `MAX_OUTPUT_TOKENS`；网页要求不思考（`thinking: disabled`，涉及模型与智能体身份的提问）时，流中的思考内容一律去掉再转发；每人每分钟 `PER_MINUTE`、每天 `PER_DAY` 次，全体每天 `TOTAL_PER_DAY` 次 |
| `GET /v1/health` | 是否配置好、模型的公开名、是否收集记录、限额（网页据此决定用不用默认服务） |
| `POST /v1/logs` | 网页在访客**同意后**发来的一轮问答记录（只保留已知字段，截断过长内容；不含密钥、设置、IP）。默认服务自己的记录（`provider: impf`）只收自中转在前 26 小时内答过的地址；访客用自己 Key 的对话记录只看来源 |
| `GET /v1/logs/export`、`POST /v1/logs/ack` | 仓库的收集器取走记录、确认已提交后删除（需 `LOG_EXPORT_TOKEN`） |
| `GET /v1/security/export`、`POST /v1/security/ack`、`GET /v1/security/summary` | 哨兵记下的可疑请求事件（取走、确认删除）与当前概览（按分数排列的访客、正在被拒绝的地址）；需 `LOG_EXPORT_TOKEN` |
| `POST /v1/security/csp` | 浏览器上报的内容安全策略违规（存为事件） |
| `GET /v1/stats?days=N` | 网页「设置 → 统计」读取的提问与模型调用次数（按天、国家与省份；需 `STATS_TOKEN`，`STATS_PUBLIC = "1"` 时公开；docs/web.md） |

访客按“IP + 日期”的哈希计数，IP 本身不保存；记录里没有 IP。一个问题通常要调用模型几次（每轮工具调用一次）。模型回复末尾报告的
用量（输入 + 输出 token）也计入该访客当天与全体当天的额度（`TOKENS_PER_DAY`、`TOTAL_TOKENS_PER_DAY`）：用完即拒绝下一次调用。

**哨兵**（[`security/`](../security/README.md)，两个 Worker 共用）看每一个请求：地址、网络、国家、协议、TLS、浏览器会带的请求头，以及
模型调用请求的形状（是否以系统提示开头、有没有工具、是否流式……只存哈希，不存正文），给出分数与理由。扫描器路径（`/wp-config.php`、
`/.git/HEAD`……）的地址被拒绝一天；分数达到标记线的请求连同地址整条记下，由 chat-logs 工作流取回到 `data/security-logs/`；
`SENTINEL = "enforce"` 时超过阻断分数的地址被拒绝六小时（默认 `observe`：只记录、不拒绝；网页自己的请求分数为 0，只留一个计数）。

**访客看不到上游。** 网页与中转之间只出现默认服务自己的说法：health 只给模型的公开名 Tao-R1；网页按 Tao-R1 请求，不带任何只有
上游才认的参数——中转换成 `MODELS` 的第一个模型，加上 `UPSTREAM_FIELDS`（`reasoning_split`），并把网页送回的思考格式
`Tao-…` 还原成上游的（`FORMAT_PREFIX`）；回复里的模型名一律是 Tao-R1、思考格式是 `Tao-…`，上游独有的字段（`base_resp`、
`*_sensitive`、`usage.total_characters`）去掉；上游的任何报错（HTTP 错误、200 回复里的失败、流中的错误）都换成默认服务自己的
一句话（检查哪个选项、稍后再试或改用自己的 Key），上游原文只以状态码记进 Worker 日志。对话记录（研究院自己的）仍记下实际作答的
模型：中转把公开名换回 `MODELS` 的模型名。

## 启用（一次）

分步教程——每一步在哪里点、怎样验证、常见报错怎么处理——见 **[SETUP.md](SETUP.md)**。概要：

1. 四个仓库 Secrets（GitHub 仓库 → Settings → Secrets and variables → Actions → New repository secret）：
   - `CLOUDFLARE_API_TOKEN`：模板 **Edit Cloudflare Workers**，Account Resources 选你的账户，Zone Resources 选 `impf.ai`；
   - `CLOUDFLARE_ACCOUNT_ID`：Workers & Pages → Account Details；
   - `MINIMAX_API_KEY`：建议为网站单独创建的按量付费密钥（从账户余额扣费，余额就是费用上限）；
   - `LOG_EXPORT_TOKEN`：收集器令牌，32 位以上随机串（如 `openssl rand -hex 32`）。

   Secrets 保存后加密存放、无法再查看，只在工作流运行时注入。
2. 合并含 `relay/` 改动的提交到 main，或运行 **Actions → relay → Run workflow**。它先跑测试，再部署 Worker、写入两个机密，
   最后检查 `https://chat-api.impf.ai/v1/health` 并用 MiniMax 做一次极小的调用。网页（chat.impf.ai）刷新后即显示
   “已接入道乃久默认服务”。`chat-api.impf.ai` 不要事先建 DNS 记录——部署时 Cloudflare 自动创建它和证书。
3. 密钥来自 MiniMax **国际站**（platform.minimax.io）时，把 `wrangler.toml` 里的 `UPSTREAM_BASE` 改为 `https://api.minimax.io/v1`
   （国内站为 `https://api.minimax.cn/v1`）；检查步骤遇到密钥被拒时会提示这一点。

## 对话记录

- 网页在访客**第一次提问前**说明记录的内容与用途，访客选“同意”或“不记录”；选择保存在其浏览器，可随时在“设置 → 数据”更改。
  不同意的访客照常使用，什么也不上传。
- **chat-logs** 工作流每小时（也可手动运行）取走新记录，按接收日期（UTC）追加到 `data/chat-logs/年/月/日.jsonl`，游标在
  `data/chat-logs/cursor.json`；推送成功后才通知中转删除。字段见 [`data/chat-logs/README.md`](../data/chat-logs/README.md)。
- 记录只在这个**私有仓库**里；仓库若要公开，先把 `data/chat-logs/` 移走。停止收集：`wrangler.toml` 里 `LOGS = "off"` 并重新部署。
- 付费计划下可改存私有 R2 存储桶（仓库变量 `ARCHIVE_BUCKET`）：记录由中转自己存进去，不再提交到仓库，可逐条删除；暂存满时拒收新记录，
  不丢弃已收下的。步骤见 [SETUP.md](SETUP.md)「归档」，设计见 [ADR 0023](../docs/adr/0023-workers-paid.md)。

## 调整与维护

- 限额、模型、允许的来源：改 `wrangler.toml` 的 `[vars]`，合入 main 后自动重新部署。
- 哨兵的模式与阈值（`SENTINEL`、`HONEYPOT`、`FLAG_SCORE`、`BLOCK_SCORE`、`BLOCK_SECONDS`、`KNOWN_PROMPTS`……）：同样在 `[vars]`；
  含义与建议见 [`security/README.md`](../security/README.md)。可选 Secret `SENTINEL_SALT`（任意长随机串）让访客的哈希键跨月不变。
- 看哨兵现在看到什么：`LOG_EXPORT_TOKEN=… python3 security/collect.py summary --site ""`（只看中转）。
- 更换密钥：更新仓库 Secret `MINIMAX_API_KEY`，再运行一次 relay 工作流（其余维护与排错见 [SETUP.md](SETUP.md)）。
- 本地试运行：`cd relay && npm test`（Node 22）；`npx wrangler@4 dev`（在 `relay/.dev.vars` 写入 `MINIMAX_API_KEY=…` 与
  `LOG_EXPORT_TOKEN=…`，该文件已被 .gitignore）。
