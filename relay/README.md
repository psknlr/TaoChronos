# 道乃久默认服务（relay）

网页（chat.impf.ai）与 MiniMax 之间的中转：访客不填 API Key 就能提问。**MiniMax 密钥只作为这个 Cloudflare Worker 的
加密机密（secret）存在**——不进网页、不进仓库、不在任何日志里显示；浏览器发来的请求不带任何密钥，由中转在服务端加上。
（密钥若放进静态网页，无论怎样加密，浏览器都得先解密再用，任何访客都能在开发者工具里看到。）

```
浏览器（chat.impf.ai） ──无密钥──▶ chat-api.impf.ai（本 Worker：加上密钥、限流） ──▶ MiniMax
        └─ 访客同意后：每轮问答一条记录 ──▶ Worker 暂存 ◀── 仓库的 chat-logs 工作流每小时取走，提交到 data/chat-logs/
        └─ 访客提交时：对回答的评价与反馈 ──┘
```

| 接口 | 作用 |
|---|---|
| `POST /v1/chat/completions` | 转发网页的模型调用（流式）；只接受网页来源（`ALLOWED_ORIGINS`）、只接受默认服务的模型（公开名 `PUBLIC_MODEL`，即 Tao-R1）、输出上限 `MAX_OUTPUT_TOKENS`（默认每次回复 32,768 token，含思考）；网页要求不思考（`thinking: disabled`，涉及模型与智能体身份的提问）时，流中的思考内容一律去掉再转发；每人每分钟 `PER_MINUTE`、每天 `PER_DAY` 次，全体每天 `TOTAL_PER_DAY` 次 |
| `GET /v1/health` | 是否配置好、模型的公开名、是否收集记录与反馈、限额（网页据此决定用不用默认服务、显不显示评价按钮） |
| `POST /v1/logs` | 网页在访客**同意后**发来的一轮问答记录（只保留已知字段，截断过长内容；不含密钥、设置、IP）。默认服务自己的记录（`provider: impf`）只收自中转在前 26 小时内答过的地址；访客用自己 Key 的对话记录只看来源 |
| `POST /v1/feedback` | 访客对一条回答的评价（有帮助 / 有问题）、勾选的原因、写下的说明，以及**访客勾选附上时**这一轮的问题和回答；只保留已知字段（说明 ≤2000 字），与对话记录存在一起、一起被取走。不需要访客同意记录（反馈是访客自己提交的），也不要求这一轮经过中转；每人每分钟 `FEEDBACK_PER_MINUTE`、每天 `FEEDBACK_PER_DAY` 条，与记录分开计数 |
| `GET /v1/logs/export`、`POST /v1/logs/ack` | 仓库的收集器取走记录、确认已提交后删除（需 `LOG_EXPORT_TOKEN`） |
| `GET /v1/security/export`、`POST /v1/security/ack`、`GET /v1/security/summary` | 哨兵记下的可疑请求事件（取走、确认删除）与当前概览（按分数排列的访客、正在被拒绝的地址）；需 `LOG_EXPORT_TOKEN` |
| `POST /v1/security/csp` | 浏览器上报的内容安全策略违规（存为事件） |
| `POST /v1/sponsor` | 访客**赞助**的自己的 API Key 与模型名（「设置 → 赞助」，勾选同意后才发送）：只保留已知字段，密钥以 `SPONSOR_SECRET` 派生的密钥 AES-GCM 加密，存在单独的 Durable Object（`SponsorBook`）里——**不与对话记录存在一起，不会被 chat-logs 工作流取进仓库**，不写日志；同一把密钥再交一次只更新说明。每人每天 `SPONSOR_PER_DAY` 次，最多存 `SPONSOR_KEEP` 条；没有 `SPONSOR_SECRET` 时关闭 |
| `GET /v1/sponsors`、`POST /v1/sponsors/delete` | 发布方查看赞助（密钥只显示首尾几位）、`?reveal=编号` 解密一把、删除一条；需 `Authorization: Bearer SPONSOR_SECRET`（`python3 relay/collect.py sponsors`） |
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

## 第二个模型：GPT-6 Luna（OpenAI）

仓库有 Secret `OPENAI_API_KEY` 时，默认服务在 Tao-R1 之外再提供 **GPT-6 Luna**（OpenAI 的 `gpt-6-luna`）：health 的 `models`
多出它的公开名（`OPENAI_PUBLIC_MODEL`），`limits.questions` 写明每人每天可问几个问题；网页「设置 → 模型」在默认服务下显示两个模型供选择。
OpenAI 密钥与 MiniMax 密钥一样**只是这个 Worker 的加密机密**，由 relay 工作流从仓库 Secret 写入，不进网页、仓库或日志。

- 网页按公开名请求，中转换成 `OPENAI_MODEL`，只把 OpenAI 认得的字段转过去（MiniMax 的 `reasoning_split`、网页的 `thinking`、温度等留在中转），
  输出上限同 `MAX_OUTPUT_TOKENS`；回复里的模型名换回公开名，OpenAI 的报错换成默认服务自己的话。
- **按问题计额度**：每人每天 `OPENAI_QUESTIONS_PER_DAY` 个问题（默认 3），全体每天 `OPENAI_TOTAL_QUESTIONS_PER_DAY` 个。一个问题要调用
  几轮工具、还可能自查一次，网页在这一轮的每次调用都带上请求头 `X-Tao-Turn`（这一轮回答的编号），同一轮只计一次；网页因故重发同一问题也不重复计。
  不带这个头的请求按最后一个问题的内容计，工具轮必须属于今天已计的问题。问题之下另有每人每天的调用次数与 token 上限
  （`OPENAI_CALLS_PER_DAY`、`OPENAI_TOKENS_PER_DAY`……），约束一个问题最多能花多少，也约束不是网页的客户端。
- **从美国线路调用**：Worker 在离访客最近的 Cloudflare 机房运行，OpenAI 拒绝部分地区（如香港）发出的请求（403）。中转经放在
  `OPENAI_LOCATION` 的 Durable Object（`Egress`，不存任何东西；它另起一个只带必要请求头的请求，不转发 Worker 的原请求）调用 OpenAI。
  默认 `"enam,wnam"`：先北美东部，OpenAI 仍拒绝地区时再试北美西部；`"off"` 则直接从访客所在机房调用。
  **`GET /v1/egress`** 显示 OpenAI 的边缘看到的位置（Cloudflare 的 trace：机房与国家），分别是直接从访客所在机房、和从每个地点调用时；
  在受影响的地区打开它，`direct.loc` 若是 `HK`、`places.*.loc` 是 `US`，就说明绕行有效。
- **带工具时不思考**：在 Chat Completions 上，GPT-6 Luna 只有在 `reasoning_effort: "none"` 时才能调用函数（OpenAI 的模型页），
  网页的请求都带工具，中转因此加上它；输出上限至少 `OPENAI_MIN_OUTPUT`（2048，过小会被拒绝）。OpenAI 的拒绝在 Worker 日志里记为
  `upstream openai <状态码> <错误代码> <参数名>`（不记原文）。
- **默认模型**：health 的 `default` 是没有自己选过模型的访客所用的模型：`DEFAULT_MODEL`（须是在提供的模型）在 `DEFAULT_MODEL_UNTIL`
  之前，之后回到 Tao-R1。现设为 GPT-6 Luna，至新加坡时间 2026-11-10 00:00（即 11 月 9 日全天）。访客在网页上选过的模型不受影响。
- **切换**：网页对话框下方有模型选择（各种屏幕宽度都显示），「设置 → 模型」里也可以选；选中即生效，不必按保存。
- 不想再提供：`OPENAI = "off"` 并重新部署（网页随之只显示 Tao-R1）；或在 Cloudflare 删除机密 `OPENAI_API_KEY`。
- 想让访客看不到上游的名字：把 `OPENAI_PUBLIC_MODEL` 改成自己的名字（如 `Tao-Luna`）。

## 赞助：访客交来自己的 API Key

「设置 → 赞助」让访客把自己的 API Key 与模型名交给默认服务，让更多人免费使用。提交前网页说明密钥去哪里、谁能读、费用由谁承担、怎样撤回，
访客勾选同意后才发送，密钥不存进浏览器。中转只做三件事：校验字段、加密保存、交给发布方查看——**它从不自己调用访客的密钥**，
是否用于默认服务由发布方核对后决定。查看与删除：

```bash
SPONSOR_SECRET=… python3 relay/collect.py sponsors              # 列表：编号、模型、服务商、密钥首尾几位
SPONSOR_SECRET=… python3 relay/collect.py sponsors --reveal 3   # 一把完整的密钥（只在自己的电脑上运行，工作流里会被拒绝）
SPONSOR_SECRET=… python3 relay/collect.py sponsors --delete 3
```

更换 `SPONSOR_SECRET` 后，之前存下的密钥无法再解密（`--reveal` 会说明），需要的话先取出再换。停止接收：`SPONSOR = "off"` 并重新部署
（网页随之不再显示「赞助」）。

## 启用（一次）

分步教程——每一步在哪里点、怎样验证、常见报错怎么处理——见 **[SETUP.md](SETUP.md)**。概要：

1. 四个仓库 Secrets（GitHub 仓库 → Settings → Secrets and variables → Actions → New repository secret）：
   - `CLOUDFLARE_API_TOKEN`：模板 **Edit Cloudflare Workers**，Account Resources 选你的账户，Zone Resources 选 `impf.ai`；
   - `CLOUDFLARE_ACCOUNT_ID`：Workers & Pages → Account Details；
   - `MINIMAX_API_KEY`：建议为网站单独创建的按量付费密钥（从账户余额扣费，余额就是费用上限）；
   - `LOG_EXPORT_TOKEN`：收集器令牌，32 位以上随机串（如 `openssl rand -hex 32`）。

   可选：`OPENAI_API_KEY`（第二个模型 GPT-6 Luna，见上文）；`SPONSOR_SECRET`（32 位以上随机串，打开「赞助」，见上文）。

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
- **对回答的反馈**：每条回答下有“有帮助 / 有问题”两个按钮，点开后可勾选原因、写几句说明，按“提交”才发送；再点一次已选的按钮即撤回
  （发一条 `rating: null`）。反馈与记录存在一起，`"kind": "feedback"`，字段见 [`data/chat-logs/README.md`](../data/chat-logs/README.md)；
  `taochronos records` 只统计条数与原因，不输出访客写的字。停止收集：`wrangler.toml` 里 `FEEDBACK = "off"` 并重新部署（网页随之不再显示按钮）。
- 付费计划下可改存私有 R2 存储桶（仓库变量 `ARCHIVE_BUCKET`）：记录由中转自己存进去，不再提交到仓库，可逐条删除；暂存满时拒收新记录，
  不丢弃已收下的。步骤见 [SETUP.md](SETUP.md)「归档」，设计见 [ADR 0023](../docs/adr/0023-workers-paid.md)。

## 调整与维护

- 限额、模型、允许的来源：改 `wrangler.toml` 的 `[vars]`，合入 main 后自动重新部署。
- **模型服务迟迟不回应时**（[ADR 0032](../docs/adr/0032-a-turn-that-waits-says-so-and-waits-less.md)）：模型服务在
  `UPSTREAM_FIRST_BYTE_SECONDS`（默认 30 秒）内什么都没发回（连状态行都没有），中转就放弃这一次、自己重新请求，总共
  `UPSTREAM_ATTEMPTS`（默认 3）次；连不上、或模型服务自己报 5xx 时也重新请求（稍作停顿），被拒绝（密钥、地区、频率、参数）
  则不重试。此时回复还没有一个字发给访客，所以不会重复；访客只计一次调用；访客离开或停止，请求随即结束。每次都没有回应时，
  在 90 秒内告诉网页（504 `upstream_timeout`，网页会照常重试），早于网页自己的 120 秒。秒数 × 次数应小于 120。
  设 `UPSTREAM_ATTEMPTS = "1"`、`UPSTREAM_FIRST_BYTE_SECONDS = "0"` 即恢复为只问一次、一直等。
- **额度用完与一时繁忙分开告知**：模型服务以 429 拒绝时，若它说明是额度用完（OpenAI 的 `insufficient_quota`、MiniMax 的
  `base_resp` 1008），访客立刻看到“额度已用完”（`upstream_quota`，网页不再重试）；其余 429 仍按“繁忙”处理，模型服务给出的
  `Retry-After` 会转给网页（最多 60 秒）。它的错误代码（不含原话）记在 Worker 日志里：`upstream 429 …`、`upstream silent ask 1/3`。
- 哨兵的模式与阈值（`SENTINEL`、`HONEYPOT`、`FLAG_SCORE`、`BLOCK_SCORE`、`BLOCK_SECONDS`、`KNOWN_PROMPTS`……）：同样在 `[vars]`；
  含义与建议见 [`security/README.md`](../security/README.md)。可选 Secret `SENTINEL_SALT`（任意长随机串）让访客的哈希键跨月不变。
- 看哨兵现在看到什么：`LOG_EXPORT_TOKEN=… python3 security/collect.py summary --site ""`（只看中转）。
- 更换密钥：更新仓库 Secret `MINIMAX_API_KEY`，再运行一次 relay 工作流（其余维护与排错见 [SETUP.md](SETUP.md)）。
- 本地试运行：`cd relay && npm test`（Node 22）；`npx wrangler@4 dev`（在 `relay/.dev.vars` 写入 `MINIMAX_API_KEY=…` 与
  `LOG_EXPORT_TOKEN=…`，该文件已被 .gitignore）。
