# 教程：接入 MiniMax 密钥，配置 Cloudflare Worker

> 账户已开通 Workers Paid（付费套餐）时，请看完整的部署指南：[English](../docs/deploy.md) · [简体中文（新加坡）](../docs/deploy.zh-SG.md)。它涵盖中转、网站、全量语料容器、D1 备份、R2 归档与边缘规则的全部步骤。

道乃久默认服务的一次性配置，约 20 分钟。完成后访客打开 chat.impf.ai 就能直接提问，不用填 API Key。
中转服务本身的说明见 [README.md](README.md)。

**密钥放在哪里**：MiniMax 密钥只存在两处加密的地方——GitHub 仓库的 Actions Secrets，和 Cloudflare Worker 的机密
（secret）。部署时 GitHub Actions 把它从前者写入后者。它不进任何文件、网页或日志，保存后两边都无法再查看。

```
MiniMax 控制台 → 复制密钥 → GitHub 仓库 Secrets → relay 工作流部署时写入 → Cloudflare Worker 机密
访客浏览器 → 不带密钥的请求 → chat-api.impf.ai（Worker 加上密钥、限流）→ MiniMax
```

## 开始前

| 需要 | 说明 |
|---|---|
| MiniMax 开放平台账号 | 国内站 [platform.minimaxi.com](https://platform.minimaxi.com)（会跳转到 platform.minimax.cn），或国际站 [platform.minimax.io](https://platform.minimax.io) |
| Cloudflare 账号 | `impf.ai` 托管在这个账号里（它的名称服务器是 `*.ns.cloudflare.com`）。免费计划即可，中转用到的 Durable Objects 免费计划也能用 |
| 仓库管理员权限 | 能打开 psknlr/TaoChronos 的 **Settings** |

最后要存进仓库的是四个 Secret：

| 名称 | 是什么 | 在哪一步取得 |
|---|---|---|
| `MINIMAX_API_KEY` | MiniMax 密钥 | 第 1 步 |
| `CLOUDFLARE_API_TOKEN` | 让 GitHub Actions 能部署 Worker 的令牌 | 第 2 步 |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare 账户编号 | 第 3 步 |
| `LOG_EXPORT_TOKEN` | 仓库取回对话记录用的口令，自己生成 | 第 4 步 |
| `STATS_TOKEN`（可选） | 在网页「设置 → 统计」里查看使用次数与地区的令牌，16 位以上随机串（如 `openssl rand -hex 24`）；网站与默认服务共用 | 自己生成（见 docs/web.md） |

取得的值先暂存在密码管理器或本机的临时记事里，存进 GitHub 后就删掉。**不要**把它们发到聊天、Issue、PR 里，也不要提交进仓库。

## 第 1 步　准备 MiniMax 密钥

1. 登录 MiniMax 开放平台，创建密钥：
   - 国内站：左侧 **接口密钥** → **创建新的 API Key**；
   - 国际站：**API Keys** → **Create new secret key**。
2. 名称填 `taochronos-relay`，方便以后辨认、单独停用。创建后立即复制。
3. 记下它来自**国内站还是国际站**，第 6 步要用。

选哪种密钥：

- **推荐按量付费的 API Key**（上面创建的就是）。它按实际用量从账户余额扣费，余额就是费用上限：测试期间只充值你愿意花的金额。
- Token Plan 订阅密钥（**订阅管理 → Token Plan**，以 `sk-cp-` 开头）也能用。但它的额度按 5 小时和每周两种窗口计算，公开网站的访客可能很快用完；
  用完后，网页会提示“默认服务的模型额度暂时用完”，直到下一个窗口。
- 之前在对话里贴出过的那把密钥已经留在聊天记录里。建议为网站新建一把，上线确认无误后，到控制台删除旧的。

## 第 2 步　创建 Cloudflare API Token

1. 登录 [dash.cloudflare.com](https://dash.cloudflare.com)，右上角头像 → **My Profile** → 左侧 **API Tokens** → **Create Token**。
   也可以建账户级令牌：左侧 **Manage Account → API Tokens**，其余步骤相同。
2. 在模板列表里找到 **Edit Cloudflare Workers**，点 **Use template**。
3. **Permissions** 保持模板原样。部署用到其中三项：Account 的 *Workers Scripts: Edit* 与 *Account Settings: Read*，Zone 的 *Workers Routes: Edit*。
4. 设置资源范围。这一步最容易漏：
   - **Account Resources**：`Include` → 选 impf.ai 所在的账户。
   - **Zone Resources**：`Include` → `Specific zone` → `impf.ai`。**必须选**，因为自定义域名 `chat-api.impf.ai` 在这个域名下。
     漏选时，第一次部署可能成功，之后再部署会报 `No access to the specified resource`。
   - **Client IP Address Filtering**：留空，因为 GitHub Actions 的出口地址不固定。
   - **TTL**：可以留空（长期有效）。若设了到期日，到期前要按“日常维护”更换令牌。
5. 可以点页面顶部令牌名旁的铅笔图标，改名为 `taochronos-relay (GitHub Actions)`。
6. 点 **Continue to summary**，核对账户和 `impf.ai` 都在列表里，再点 **Create Token**。
7. 复制显示的令牌。**它只显示这一次**，丢了就删掉重建。

## 第 3 步　复制 Cloudflare Account ID

下面三处任选一处：

- 左侧 **Workers & Pages** → 右侧 **Account Details** → 点 **Account ID** 旁的复制按钮；
- 按 `Ctrl + K`（Mac 上是 `⌘ + K`），搜索 `Copy account ID`；
- **Domains → impf.ai → Overview**，页面靠下的 **API** 区。

Account ID 是 32 位十六进制字符串。它不算机密，但也不必公开。

## 第 4 步　生成收集器令牌 LOG_EXPORT_TOKEN

仓库的 chat-logs 工作流凭这个令牌从 Worker 取走对话记录。Worker 与仓库各存一份，别处不用，你不需要记住它。

任选一种方法生成 64 位随机串：

```bash
openssl rand -hex 32                                        # macOS / Linux
python3 -c "import secrets; print(secrets.token_hex(32))"   # 装有 Python 的任何系统
```

```powershell
# Windows PowerShell
$b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); -join ($b | % { $_.ToString('x2') })
```

令牌至少 16 位（工作流会检查），只用字母和数字。

## 第 5 步　把四个值存为 GitHub 仓库 Secrets

1. 打开 <https://github.com/psknlr/TaoChronos/settings/secrets/actions>，
   也就是仓库 → **Settings** → 左侧 *Security* 下的 **Secrets and variables** → **Actions**。
2. 在 **Secrets** 标签下点 **New repository secret**。
3. **Name** 填名称（全大写，一字不差），**Secret** 粘贴值，再点 **Add secret**。四个依次添加：

   | Name | Secret |
   |---|---|
   | `MINIMAX_API_KEY` | 第 1 步的 MiniMax 密钥 |
   | `CLOUDFLARE_API_TOKEN` | 第 2 步的令牌 |
   | `CLOUDFLARE_ACCOUNT_ID` | 第 3 步的 Account ID |
   | `LOG_EXPORT_TOKEN` | 第 4 步的随机串 |

4. 完成后，**Repository secrets** 列表里应有这四项，只显示名称和更新时间。

注意：

- 要放在 **Repository secrets**。不要放进 *Environment secrets*（工作流没有指定环境），也不要放进 **Variables** 标签（那里是明文）。
- 保存后值无法再查看，只能点 **Update** 覆盖。它在 Actions 日志里会自动显示为 `***`。
- 粘贴时带进来的空格和换行，工作流会自动去掉。
- **Variables** 标签里的 `RELAY_URL` 只有在中转**不用** `chat-api.impf.ai` 时才需要设置，平时不用管。

## 第 6 步　改接口地址（只有国际站密钥需要）

- **国内站**（platform.minimaxi.com / platform.minimax.cn）的密钥：什么都不用改，默认地址就是 `https://api.minimax.cn/v1`。
- **国际站**（platform.minimax.io）的密钥：把 `relay/wrangler.toml` 里的这一行改为

  ```toml
  UPSTREAM_BASE = "https://api.minimax.io/v1"
  ```

  然后提交到 main。可以直接在 GitHub 网页上编辑这个文件。
- 拿不准时先照常部署。第 7 步的检查若报 `MiniMax refused the key`，多半就是站点不对，也可能是密钥有误。

## 第 7 步　部署

**推荐顺序：先完成第 5 步，再合并 PR #3。**

- 打开 [PR #3](https://github.com/psknlr/TaoChronos/pull/3)，点 **Merge pull request** → **Confirm merge**。合并会同时触发两个工作流：
  - **pages**：重建网站，写入中转地址（`site.json`）；
  - **relay**：依次测试、部署 Worker、写入两个机密、检查。
- 如果已经先合并了，或者以后想重新部署：仓库 → **Actions** → 左侧 **relay** → 右侧 **Run workflow** → Branch 选 `main` →
  **Run workflow**。这个按钮要等 PR #3 合并、`relay.yml` 进入 main 之后才会出现。

打开这次运行，点 **deploy**，逐个步骤看：

| 步骤 | 正常时 |
|---|---|
| Test the relay | 10 项测试全部通过 |
| Are its secrets set? | 没有输出。缺了哪个 Secret，这里会出现黄色警告并列出名称，后面的步骤会被跳过：运行仍显示成功，但**什么也没部署** |
| Deploy the Worker, then give it its secrets | 出现类似 `Uploaded taochronos-relay`、`Deployed taochronos-relay triggers`、`chat-api.impf.ai (custom domain)` 的输出，以及两行 `Success! Uploaded secret …` |
| Check it answers, and that MiniMax takes its key | 最多等 4 分钟让新域名生效，再用 MiniMax 做一次极小的调用。成功时最后一行是 `{"relay": "https://chat-api.impf.ai", "model": "Tao-R1", "logs": true, …, "call": "ok"}` |

第一次部署时，Cloudflare 会自动在 impf.ai 的 DNS 里创建 `chat-api` 记录并签发证书。**不要**事先手动添加这条 DNS 记录，已有记录会导致部署失败。

## 第 8 步　验证

1. 用浏览器打开 <https://chat-api.impf.ai/v1/health>，应看到：

   ```json
   {"ok":true,"service":"taochronos-relay","version":"1","model":"Tao-R1","models":["Tao-R1"],"logs":true,"max_output_tokens":32768,"limits":{"per_minute":30,"per_day":600}}
   ```

   如果是 `"ok":false`，说明 Worker 已上线但没有密钥，重跑一次 relay 工作流即可。
2. 打开 <http://chat.impf.ai/>（HTTPS 生效后改用 https，见第 10 步），按 `Ctrl + F5`（Mac 上是 `⌘ + Shift + R`）强制刷新：
   - 首页下方显示“**已接入道乃久默认服务：无需设置，直接提问**”；
   - 第一次提问前弹出记录说明，可以选“同意并继续”或“不记录”；
   - 回答正常出现，引文可以点开核对。
3. Cloudflare 控制台 → **Workers & Pages** → **taochronos-relay**：
   - **Settings → Domains & Routes** 里有 `chat-api.impf.ai`（Custom domain）；
   - **Settings → Variables and Secrets** 里，`MINIMAX_API_KEY` 和 `LOG_EXPORT_TOKEN` 是 Secret（值不显示），`UPSTREAM_BASE`、`PER_DAY` 等是明文变量；
   - **Metrics** 里能看到请求数和错误。中转不记录访客写的内容。

## 第 9 步　收集对话记录

- **chat-logs** 工作流每小时第 17 分钟自动运行。它取回新记录，提交到 `data/chat-logs/年/月/日.jsonl`，推送成功后才通知中转删除已取回的部分。
- 想立即看到：**Actions → chat-logs → Run workflow**。有新记录时会出现一个提交 `chat-logs: N records through #M [skip ci]`；没有新记录就不提交。
- 这里只有同意记录的访客的问答，字段说明见 [`data/chat-logs/README.md`](../data/chat-logs/README.md)。仓库须保持私有。

## 归档：记录与安全事件改存私有 R2 存储桶（Workers 付费计划，可选）

升级到 Workers 付费计划后，可以让中转与网站把对话记录和哨兵事件存进一个**私有**的 R2 存储桶，不再每小时提交进本仓库：
存储桶里的记录可以逐条删除，仓库的历史却删不掉（设计见 [ADR 0023](../docs/adr/0023-workers-paid.md)）。不设置时一切照旧。

1. **建存储桶**：Cloudflare → **R2 Object Storage** → **Create bucket**，名称如 `taochronos-archive`（小写字母、数字、连字符）。
   建好后进入它的 **Settings**：**Public Development URL（r2.dev）保持 Disabled**，**Custom Domains 不添加**。部署时会检查这两项，
   存储桶可能公开就不绑定。命令行也可以：`npx wrangler@4 r2 bucket create taochronos-archive`。
2. **给部署令牌加 R2 权限**：Cloudflare → **API Tokens** → 第 2 步建的令牌 → **Edit** → **Add more** →
   Account · **Workers R2 Storage** · **Edit** → 保存。令牌的值不变，GitHub 里不用改。
3. **设仓库变量**：仓库 → **Settings → Secrets and variables → Actions → Variables** → **New repository variable**：
   名称 `ARCHIVE_BUCKET`，值为存储桶名。（是 Variable 而不是 Secret：桶名不是机密。）
4. **重新部署两个 Worker**：**Actions → relay → Run workflow**，再 **Actions → site → Run workflow**。部署日志里应有一行
   `the archive: R2 bucket … (private)`。若是 `::warning::` 或 `::error::`，按提示处理后重跑；在此之前记录照旧进仓库，不会丢。
5. **验证**：有新记录后约半分钟，存储桶里出现 `chat-logs/年/月/日/编号.json`（哨兵事件在 `security-logs/relay/…`、`security-logs/site/…`）；
   chat-logs 工作流的日志里出现 `archives its records in its own bucket` 的提示，不再提交新记录。
6. **读回某一天**：`LOG_EXPORT_TOKEN=… python3 relay/collect.py archive --day 2026-10-14` 写到 `.archive/chat-logs/2026/10/14.jsonl`；
   `python3 security/collect.py archive --day 2026-10-14` 写到 `.archive/security-logs/…`。`.archive/` 已被 .gitignore，**不要提交**。
7. **保存期限**（建议，由发布方决定，并写进网页的记录说明）：存储桶 **Settings → Object lifecycle rules**，前缀 `chat-logs/` 90 天后删除，
   `security-logs/` 30 天后删除。命令行：
   `npx wrangler@4 r2 bucket lifecycle add taochronos-archive chat-logs-90d chat-logs/ --expire-days 90`。

停用：删除仓库变量 `ARCHIVE_BUCKET`，重新部署两个 Worker；chat-logs 工作流从上次的游标继续收进仓库（编号不会重复），存储桶里已有的不动。
已提交在 `data/chat-logs/`、`data/security-logs/` 里的旧记录仍在仓库历史中，要清除须另行决定、另行操作。

## 第 10 步　为 chat.impf.ai 打开 HTTPS

目前 `chat.impf.ai` 只能用 http 访问，因为 GitHub 还没签发它的证书。默认服务在 http 下也能用，但浏览器无法缓存语料，每次打开都要重新下载。

1. 仓库 → **Settings** → **Pages**：Custom domain 应为 `chat.impf.ai`，下方显示 DNS 检查通过。
2. 证书签发后（通常几分钟到 24 小时），勾选 **Enforce HTTPS**。
3. 超过 24 小时仍不能勾选时，在 Custom domain 里删掉域名并点 **Save**，再填回 `chat.impf.ai` 并点 **Save**，以触发重新签发。
   Cloudflare DNS 里 `chat` 这条 CNAME 记录（指向 `psknlr.github.io`）必须保持 **DNS only**（灰色云朵），不要开代理。

## 日常维护

| 要做的事 | 怎么做 |
|---|---|
| 更换 MiniMax 密钥 | 在 MiniMax 控制台新建密钥 → 在仓库 Secrets 里点 `MINIMAX_API_KEY` 的 **Update**，粘贴新值 → **Actions → relay → Run workflow** → 检查通过后，在 MiniMax 控制台删除旧密钥 |
| 更换 Cloudflare 令牌 | 按第 2 步新建令牌 → 更新 `CLOUDFLARE_API_TOKEN` → 重跑 relay → 在 Cloudflare 删除旧令牌 |
| 更换收集器令牌 | 生成新串 → 更新 `LOG_EXPORT_TOKEN` → 重跑 relay，Worker 与仓库就同时换成新的 |
| 调整限额、模型、允许的网页来源 | 改 `relay/wrangler.toml` 的 `[vars]`，合入 main 后自动重新部署。`PER_MINUTE`、`PER_DAY`、`TOTAL_PER_DAY` 分别是每人每分钟、每人每天、全体每天的模型调用次数；一个问题通常要调用好几次，每轮工具调用一次 |
| 停止收集对话 | 把 `wrangler.toml` 里的 `LOGS` 改为 `"off"`，合入 main。网页随即不再询问，也不再上传 |
| 记录改存 R2 / 读回某一天 | 见上文“归档”一节 |
| 暂停默认服务 | Cloudflare → taochronos-relay → **Settings → Variables and Secrets**，删除 `MINIMAX_API_KEY`。网页检测到中转没有密钥后，自动改回“请访客填自己的 API Key”。恢复时重跑 relay 即可 |
| 看用量 | MiniMax 控制台的用量或账单页；Cloudflare 里 Worker 的 **Metrics** |

## 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| relay 运行成功，但有黄色警告 `the relay is not deployed until these repository secrets are set: …` | 列出的 Secret 没设，或名称拼错 | 按第 5 步补上（名称全大写、一字不差），重跑 relay |
| `LOG_EXPORT_TOKEN must be at least 16 characters` | 收集器令牌太短 | 按第 4 步重新生成 |
| 部署步骤报 `Authentication error [code: 10000]` | 令牌的权限或账户不对，或 `CLOUDFLARE_ACCOUNT_ID` 填错 | 核对 Account ID；按第 2 步重建令牌（模板 Edit Cloudflare Workers，账户选对） |
| 部署步骤报 `No access to the specified resource`（地址里有 `workers/routes`） | 令牌的 Zone Resources 里没有 impf.ai | Cloudflare → API Tokens → 该令牌的 **Edit** → 在 Zone Resources 加上 impf.ai，然后重跑。令牌的值不变，GitHub 里不用改 |
| 部署步骤说 `chat-api.impf.ai` 已有 DNS 记录（`already has externally managed DNS records`） | 事先有人建了这条记录 | Cloudflare → impf.ai → **DNS → Records**，确认 `chat-api` 这条记录没有别的用途后删除，然后重跑 |
| 检查步骤报 `… does not answer` | 新域名或证书还没生效 | 等几分钟后重跑 relay；也可以在 Cloudflare 确认 Worker 的 **Domains & Routes** 里有这个域名 |
| 检查步骤报 `the relay answers but has no MINIMAX_API_KEY` | 写入机密那一步没有成功 | 重跑 relay |
| 检查步骤报 `MiniMax refused the key …` | 国际站密钥配了国内地址（或反之），或者密钥已删除、填错 | 按第 6 步改 `UPSTREAM_BASE`；或更新 `MINIMAX_API_KEY` 后重跑 |
| 检查步骤或网页提示“额度已用完”“调用过于频繁” | MiniMax 余额不足，或 Token Plan 当前窗口的额度用完 | 充值，或等下一个窗口。公开网站建议用按量付费的密钥 |
| 网页仍要求填 API Key | 网站还是旧版本，或者中转没上线 | 确认 PR #3 已合并、pages 工作流成功；打开 `http://chat.impf.ai/site.json`，应看到中转地址；打开 health，应看到 `"ok":true`；再强制刷新。已在“设置 → 模型”里选了其他服务的访客，选回“道乃久默认服务”即可 |
| 网页提示“这个服务只供道乃久网页使用” | 网页的地址不在 `ALLOWED_ORIGINS` 里 | 换了网址时，把新地址加进 `ALLOWED_ORIGINS` 并重新部署 |
| 访客看到“请求太频繁”或“今天的免费额度已用完” | 触发了中转的限额 | 这是正常的保护。需要时调高 `PER_MINUTE`、`PER_DAY` 或 `TOTAL_PER_DAY`；“（按用量计）”的是 token 额度 `TOKENS_PER_DAY`、`TOTAL_TOKENS_PER_DAY` |
| 访客看到“该地址因异常访问已被暂时限制” | 哨兵拒绝了这个地址：它探测过扫描器路径，或（enforce 模式）分数超过阻断线 | 看 `data/security-logs/` 里该地址的事件；误伤时把 `BLOCK_SECONDS` 调短、`SENTINEL` 改回 `observe`，或在 `security/README.md` 的指引下调整阈值 |
| chat-logs 报 `the records could not be pushed` | main 分支有保护规则，工作流不能直接推送 | 放宽 main 的保护规则，允许 GitHub Actions 推送。记录会留在中转，下次运行再取 |
| chat-logs 报 `the relay refused the export: HTTP 401` | 仓库与 Worker 的 `LOG_EXPORT_TOKEN` 不一致 | 重跑 relay，用仓库里的值重写 Worker 的机密 |
| Workers Logs 里出现 `logs full` | 记录很久没有被取走（chat-logs 工作流停了，或归档写不进存储桶），暂存已满，新记录被拒收（已收下的一条不丢） | 查 chat-logs 工作流；有归档时查日志里的 `archive … Error`；处理后积压会自动取走 |
| 部署日志：`the archive's bucket … may be public` | 存储桶开了 r2.dev 地址或绑了自定义域名，或令牌读不到这两项 | 在存储桶 Settings 里关掉 r2.dev、移除自定义域名，确认令牌有 Workers R2 Storage 权限，重跑 |
| 访问中转得到 Cloudflare Error 1027 | Workers 免费计划每天 10 万次请求用完了（UTC 零点重置） | 中转自己的全体日限额（默认 5000 次模型调用）远低于此，一般不会发生。发生时可调低限额，或升级 Workers 付费计划 |

## 安全须知

- 密钥只在 GitHub Secrets 和 Worker 机密里，网页、仓库、日志里都没有。浏览器发给中转的请求不带任何密钥。
- 能改仓库 Secrets 或 Cloudflare Workers 的人就能换掉密钥。只把仓库管理员和 Cloudflare 账户权限给可信的人。
- 令牌泄露时，在 Cloudflare 的 **API Tokens** 里对它 **Roll**（重新生成）或删除，再更新 GitHub Secret。MiniMax 密钥泄露时，
  在 MiniMax 控制台删除它，再按“更换 MiniMax 密钥”换新。
- 中转限制了来源、模型、输出长度和每人、全体的调用次数与 token 用量，这些限定的是被滥用时最多能花多少。真正的费用上限是 MiniMax 账户余额。
- 哨兵（`security/`）记下可疑请求的地址与请求头，取回到私有仓库的 `data/security-logs/`；Cloudflare 边缘的 WAF 规则、速率限制与区域设置由
  security 工作流用两个专用令牌写入与读取（仓库 Secrets `CLOUDFLARE_SECURITY_TOKEN`、`CLOUDFLARE_ANALYTICS_TOKEN` 与变量 `CLOUDFLARE_ZONE_ID`；
  权限清单与步骤见 `security/README.md`「启用」）。
