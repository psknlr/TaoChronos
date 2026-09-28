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
| `POST /v1/chat/completions` | 转发网页的模型调用（流式）；只接受网页来源（`ALLOWED_ORIGINS`）、只允许 `MODELS` 里的模型、输出上限 `MAX_OUTPUT_TOKENS`；每人每分钟 `PER_MINUTE`、每天 `PER_DAY` 次，全体每天 `TOTAL_PER_DAY` 次 |
| `GET /v1/health` | 是否配置好、模型、是否收集记录、限额（网页据此决定用不用默认服务） |
| `POST /v1/logs` | 网页在访客**同意后**发来的一轮问答记录（只保留已知字段，截断过长内容；不含密钥、设置、IP） |
| `GET /v1/logs/export`、`POST /v1/logs/ack` | 仓库的收集器取走记录、确认已提交后删除（需 `LOG_EXPORT_TOKEN`） |

访客按“IP + 日期”的哈希计数，IP 本身不保存；记录里没有 IP。一个问题通常要调用模型几次（每轮工具调用一次）。

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

## 调整与维护

- 限额、模型、允许的来源：改 `wrangler.toml` 的 `[vars]`，合入 main 后自动重新部署。
- 更换密钥：更新仓库 Secret `MINIMAX_API_KEY`，再运行一次 relay 工作流（其余维护与排错见 [SETUP.md](SETUP.md)）。
- 本地试运行：`cd relay && npm test`（Node 22）；`npx wrangler@4 dev`（在 `relay/.dev.vars` 写入 `MINIMAX_API_KEY=…` 与
  `LOG_EXPORT_TOKEN=…`，该文件已被 .gitignore）。
