# 在 Cloudflare Workers 付费配套上部署道乃久

本指南写给 Cloudflare 账户与本仓库的负责人：部署了哪些部分、需要哪些密钥与设置、按什么次序操作、每一步怎样确认成功、
哪些工作会自动运行、费用多少，以及出问题时怎么处理。前提是账户已开通 **Workers Paid 付费配套**（D1、Durable Objects 与
Containers 也随之改为按用量计费）。

English version: [deploy.md](deploy.md)。本指南汇总了以下较早的分步教程：[cloud/SETUP.md](../cloud/SETUP.md)（网站）、
[relay/SETUP.md](../relay/SETUP.md)（默认服务）、[security/README.md](../security/README.md)（边缘防护）。设计决定见 ADR
[0012](adr/0012-default-service-relay.md)、[0016](adr/0016-site-and-full-corpus-on-cloudflare.md)、[0017](adr/0017-d1-backup.md)、
[0018](adr/0018-sentinel-and-edge-rules.md)、[0023](adr/0023-workers-paid.md)。

文中时间同时以 UTC 与新加坡时间（SGT，UTC+8）标示。Cloudflare 控制台是英文界面，按钮与菜单名称照原文引用。

---

## 目录

1. [部署了什么](#1-部署了什么)
2. [开始之前](#2-开始之前)
3. [Cloudflare API 令牌](#3-cloudflare-api-令牌)
4. [GitHub 机密与变量](#4-github-机密与变量)
5. [路线 A 从现有的免费部署升级](#5-路线-a-从现有的免费部署升级)（您多半属于这种情况）
6. [路线 B 新账户从零开始](#6-路线-b-新账户从零开始)
7. [检查部署](#7-检查部署)
8. [自动运行的工作](#8-自动运行的工作)
9. [费用与防护](#9-费用与防护)
10. [日常维护](#10-日常维护)
11. [回滚](#11-回滚)
12. [疑难排解](#12-疑难排解)
13. [参考 文件与工作流](#13-参考-文件与工作流)

---

## 1. 部署了什么

```
访客的浏览器
  │
  ├── https://chat.impf.ai ──────────── Worker  taochronos-site        (cloud/site)
  │      │  网页、安全标头、/api/*                          Durable Object Watch（哨兵、统计）
  │      │  静态文件由 Cloudflare 直接提供                  KV 命名空间 taochronos-store（语料上载）
  │      │
  │      ├── 服务绑定 ──▶ Worker taochronos-corpus          (cloud/corpus，没有公网地址)
  │      │                  └─ Durable Object ▶ 容器：在全量语料（958 部古籍）上运行 taochronos
  │      ├── 没有容器时：D1 数据库 taochronos-d1-0 … -4（D1 备份）
  │      └── 两者都没有时：浏览器自己运行要籍语料
  │
  └── https://chat-api.impf.ai ──────── Worker  taochronos-relay       (relay/)
         用负责人的 MiniMax 密钥调用模型                     Durable Objects Limiter（限额、哨兵、统计）
         访客同意后上载的对话记录                                         LogBook （待取走的记录）
                                                            R2 存储桶（可选）：归档

GitHub Actions ── 部署两个 Worker、构建容器映像、导入 D1、写入边缘规则、
                  每小时取回记录与安全事件、每天取回边缘事件
```

| 部分 | 位置 | 需要 | 缺少时 |
|---|---|---|---|
| 默认服务（中转） | `chat-api.impf.ai` | MiniMax 密钥 | 访客须自行填写模型密钥 |
| 网站 | `chat.impf.ai` | — | — |
| 全量语料：容器 | 网站后面 | Workers 付费配套、令牌有 **Containers · Edit**、语料已上载 | 由 D1 备份回答，否则由浏览器回答 |
| 全量语料：D1 备份 | 网站后面 | 令牌有 **D1 · Edit**、语料已上载 | 浏览器运行要籍语料（535 部） |
| 归档 | R2 存储桶 | 令牌有 **Workers R2 Storage · Edit**、变量 `ARCHIVE_BUCKET` | 记录与事件提交进仓库 |
| 边缘规则 | 区域 `impf.ai` | 两个安全令牌 | 只有 Cloudflare 的托管规则 |

**由哪份语料回答。** 只要容器已部署并绑定，网站就把 API 交给容器；没有绑定容器时才由 D1 备份回答；两者都没有时，页面在
浏览器里运行要籍语料。在付费配套上，容器是完整的服务（全部工具，包括研究任务）；D1 备份成本很低，是部署时找不到容器的
后备。两者都建议部署。

---

## 2. 开始之前

| 需要 | 说明 |
|---|---|
| 已开通 **Workers Paid** 的 Cloudflare 账户 | 控制台 → **Compute (Workers)** → **Plans**。须与区域 `impf.ai` 同一账户 |
| 该账户里的区域 `impf.ai` | 它的名称服务器是 `*.ns.cloudflare.com` |
| `psknlr/TaoChronos` 的管理员权限 | 能打开 **Settings**，设置机密与变量 |
| MiniMax API 密钥 | 建议用按量付费的密钥（账户余额就是模型费用的上限）。在新加坡多半是**国际站**（platform.minimax.io）的密钥，见步骤 A1.3 |
| 装有 Python ≥ 3.11 与本地全量语料的电脑 | 只在全量语料从未上载过时需要（步骤 A3） |
| 账户已启用 R2 | 只在使用归档时需要。R2 会要求一次付款方式；开通付费配套时已经有了 |

---

## 3. Cloudflare API 令牌

共三个令牌，分开保管，各管各的事。在 **My Profile → API Tokens → Create Token**（或 **Manage Account → Account API
Tokens**）建立。

### 3.1 部署令牌：机密 `CLOUDFLARE_API_TOKEN`

从模板 **Edit Cloudflare Workers** 开始，确认权限与下表一致：

| 范围 | 权限 | 级别 | 谁用 |
|---|---|---|---|
| Account | Workers Scripts | Edit | 两个 Worker 及其 Durable Objects |
| Account | Account Settings | Read | wrangler |
| Account | Workers KV Storage | Edit | 语料上载的命名空间 |
| Account | **Containers** | **Edit** | 全量语料的容器 |
| Account | **D1** | **Edit** | D1 备份 |
| Account | **Workers R2 Storage** | **Edit** | 归档（可选） |
| Zone | Workers Routes | Edit | 自定义域名 |

- **Account Resources**：*Include* → 您的账户。**Zone Resources**：*Include* → *Specific zone* → `impf.ai`
  （漏选这一项是 `No access to the specified resource` 最常见的原因）。
- **Client IP Address Filtering**：留空（GitHub 的运行器没有固定地址）。
- 令牌已经存在（设置中转时建立的）的话，点 **Edit**（不是 *Roll*），补上缺少的几行。修改权限不会改变令牌的值，GitHub 里
  不必更新。

### 3.2 安全令牌：机密 `CLOUDFLARE_SECURITY_TOKEN`

自定义令牌，区域 `impf.ai`：Zone · **Zone WAF** · Edit；Zone · **Zone Settings** · Edit；Zone · **Bot Management** · Edit；
Zone · **Zone** · Read；Account · **Account Filter Lists** · Edit。

### 3.3 分析令牌：机密 `CLOUDFLARE_ANALYTICS_TOKEN`

自定义令牌，区域 `impf.ai`：Zone · **Analytics** · Read。

---

## 4. GitHub 机密与变量

仓库 → **Settings → Secrets and variables → Actions**。机密放在 **Secrets** 标签下的 *Repository secrets*（不是
*Environment secrets*）；变量放在 **Variables** 标签下。粘贴时带进来的空格与换行，工作流会自动去掉。

### 机密（Secrets）

| 名称 | 值 | 是否必需 |
|---|---|---|
| `CLOUDFLARE_API_TOKEN` | 部署令牌（3.1） | 必需 |
| `CLOUDFLARE_ACCOUNT_ID` | 控制台 → 任一区域 → **Overview** → *API* → Account ID | 必需 |
| `MINIMAX_API_KEY` | MiniMax 密钥 | 默认服务必需 |
| `LOG_EXPORT_TOKEN` | 16 位以上的随机串：`openssl rand -hex 32` | 必需 |
| `SENTINEL_SALT` | 随机串：`openssl rand -hex 32` | 建议（访客的哈希键跨月不变） |
| `STATS_TOKEN` | 16 位以上的随机串 | 可选（网页的「设置 → 统计」） |
| `CLOUDFLARE_SECURITY_TOKEN` | 安全令牌（3.2） | 边缘规则需要 |
| `CLOUDFLARE_ANALYTICS_TOKEN` | 分析令牌（3.3） | 每天取回边缘事件需要 |

### 变量（Variables）

| 名称 | 值 | 何时需要 |
|---|---|---|
| `CLOUDFLARE_ZONE_ID` | `impf.ai` → **Overview** → *API* → Zone ID | 每天取回边缘事件 |
| `ARCHIVE_BUCKET` | R2 存储桶的名称，如 `taochronos-archive` | 把记录归档到 R2（步骤 A6） |
| `STORE_TOKEN_SHA256` | 一次性上载令牌的 sha256 | **只在上载语料期间**（步骤 A3），完成后删除 |
| `RELAY_URL`、`SITE_URL` | 其他地址 | 只在不用 `chat-api.impf.ai` / `chat.impf.ai` 时 |

机密的值切勿贴进 Issue、Pull Request、聊天或提交里。

---

## 5. 路线 A 从现有的免费部署升级

中转与网站已在免费配套上运行（仓库每小时的 `chat-logs` 提交可以证明）。请按次序操作；每一步都写明怎样确认成功。

### A1. 合并付费配套的改动，检查中转

1. 从分支 `claude/vibrant-pascal-n9a7o2`（即 [ADR 0023](adr/0023-workers-paid.md) 的改动）向 `main` 开一个 Pull Request
   并合并。合并会自动启动 **relay** 与 **site** 两个工作流。
2. **Actions → relay** → 本次运行 → **deploy**：每一步都是绿色；最后一步输出
   `{"relay": "https://chat-api.impf.ai", "model": "Tao-R1", …, "call": "ok"}`。
3. *如果 MiniMax 密钥来自国际站*（platform.minimax.io，中国大陆以外通常如此）：`relay/wrangler.toml` 须写
   `UPSTREAM_BASE = "https://api.minimax.io/v1"`。检查步骤若报 `MiniMax refused the key … api.minimax.io`，在 `main` 上改这一行，
   中转会自动重新部署。

对访客的变化：被拒绝的访客现在会被告知原因（403 / 429，而不是 503），见 ADR 0023。

### A2. 扩大部署令牌的权限

按 3.1 给部署令牌加上 **Containers · Edit**、**D1 · Edit**，以及（使用归档时）**Workers R2 Storage · Edit**。GitHub 里不必改动。

### A3. 确认全量语料已经上载

容器与 D1 备份都由同一份语料构建：一个 143 MB 的压缩 SQLite 文件，分 6 片，由 `cloud/store.json` 锁定（`sha256 ef628936…`，
958 部书、2,038,497 段、122,219,380 字），上载在网站的 KV 命名空间 `taochronos-store` 里。

**是否已经上载？** 打开 **Actions → site** → 最近一次运行 → 任务 **corpus** → 步骤 *The store, from the site's KV namespace*。
若没有出现警告 `the store cloud/store.json names is not (all) in the KV namespace`，就已经上载，请直接做 A4。（若
https://chat.impf.ai/api/info 已返回标签 `全量语料（备份）`，说明语料已上载、D1 备份已在运行。）

**若未上载**（在存有本地全量语料的电脑上操作；全量语料的构建见 README）：

```bash
t=$(openssl rand -hex 32); printf %s "$t" | sha256sum      # 一次性令牌及其 sha256；令牌只留在本机
# GitHub → Settings → Secrets and variables → Actions → Variables：STORE_TOKEN_SHA256 = 上面的 sha256
# 然后 Actions → site → Run workflow（网站随即接受这个令牌的上载）
taochronos web store                                        # 写出 .taochronos/cloud/<sha256>.sqlite.xz 与 cloud/store.json
TAOCHRONOS_STORE_TOKEN=$t taochronos web upload             # 6 片上载到 https://chat.impf.ai/api/store/…（已有的分片跳过）
# 立即删除变量 STORE_TOKEN_SHA256；cloud/store.json 与 cloud/ATTRIBUTION.md 若有改动就提交
```

没有登记的令牌，上载接口一律拒绝；部署时每一片都按 `cloud/store.json` 校验。

### A4. 构建并部署全量语料的容器

1. **Actions → site → Run workflow**，分支选 `main`，勾选 **rebuild**，再按 **Run workflow**。
2. 任务 **corpus**（第一次约 20 分钟）：
   - *Which version … may the account deploy containers?*：输出 `deployed: none; this commit: ef628936d382-…`。
     若出现警告 `the account may not deploy containers yet`，就是付费配套或 Containers · Edit 权限还没到位（A2）。
   - *Build the image and deploy the corpus Worker*：wrangler 构建映像（解压语料、建索引、预热缓存，共 1.8 GB）并推送。
3. 接着任务 **bind** 再部署一次网站、绑定容器，并做一次全量检索；日志最后一行是
   `a search on the full corpus: … ['…', '…', '…']`。
4. 检查：`curl -s https://chat.impf.ai/api/info` 应有 `"label": "全量语料"`、`"books": 958`，而且没有 `"backup"` 字段。
   新映像后的第一次调用可能要等几分钟，容器正在启动。

`cloud/corpus/wrangler.toml` 里的设置（在 `main` 上修改后，勾选 **rebuild** 再 *Run workflow*）：

| 设置 | 默认值 | 含义 |
|---|---|---|
| `instance_type` | `standard-1`（½ vCPU、4 GiB、8 GB 磁盘） | `standard-2` 回答更快，每小时费用更高 |
| `SLEEP_AFTER` | `"15m"` | 闲置多久后休眠（休眠后不计费）；越短越省，冷启动需几十秒 |
| `max_instances` | `2` | 研究任务都交给同一个具名实例；要用更多实例须先改路由（ADR 0023） |
| `LOCATION_HINT` | `"apac"` | 实例所在地区，适合新加坡与东亚的读者。对象第一次建立时即固定 |

### A5. 以 D1 备份作后备（建议，成本很低）

D1 免费配套每天最多写入 10 万行，所以以前分两天导入。**付费配套没有每日上限**（写入按月计费，每月含 5,000 万行），一次
就能导完：

1. **Actions → d1 → Run workflow**，分支选 `main`，**budget** 填 `1000000`，再按 **Run workflow**。（budget 原是免费配套的
   每日上限，在付费配套上只是安全阀；一次完整导入约写 10 万行。）
2. 一次运行最长五小时：先写入语料（约 87,000 行），再计算预先算好的结果（约 12,000 行）。若以 `the run's time is up` 结束，
   再运行一次即可：它从断点继续，不会重复写入。每天 00:07 UTC（新加坡时间 08:07）的定时运行也会接着导入。
3. 导入完成后，运行会记下版本，并自动启动 **site** 工作流；网站绑定数据库（`D1_0` … `D1_4`）并设置 `D1_BACKUP`。
   该次运行的 **Summary** 写着 `complete: yes`。

绑定了容器时，D1 备份不会被用到；部署时找不到容器（例如容器构建失败），它就接手，全量语料不会因此退回浏览器里的要籍语料。
检查方法见第 7 节。

*只用 D1、不用容器：* 从令牌删去 **Containers · Edit**（corpus 任务随即跳过构建并给出警告），再在控制台删除 Worker
`taochronos-corpus`。网站由 D1 回答：14 个工具实时计算、16 个预先算好，研究任务不可用（ADR 0017）。

### A6. 归档：记录不再进仓库（建议）

至今，每小时的 `chat-logs` 工作流把访客同意记录的对话，以及哨兵的事件（含被标记客户端的网络地址）提交进本仓库，历史里
删不掉。启用归档后，两个 Worker 把它们存进一个私有的 R2 存储桶。

1. **R2 Object Storage → Create bucket** → 名称 `taochronos-archive` → 位置 *Automatic*（或 *Asia-Pacific*）。
   然后在存储桶的 **Settings** 里：**Public Development URL (r2.dev)** 保持 **Disabled**；**Custom Domains** 不添加。
2. 部署令牌已有 **Workers R2 Storage · Edit**（A2）。
3. 仓库变量 `ARCHIVE_BUCKET` = `taochronos-archive`。
4. **Actions → relay → Run workflow**，再 **Actions → site → Run workflow**。两边的部署日志都应出现
   `the archive: R2 bucket taochronos-archive (private): records and events are drained there …`。若出现的是 `::warning::`
   或 `::error::`，它会说明为什么没有绑定（找不到、没有权限，或可能是公开的）；Worker 照常部署，只是不绑定存储桶，记录
   照旧进仓库，不会丢失。
5. 下一段经同意的对话结束约半分钟后，存储桶里出现 `chat-logs/年/月/日/编号.json`。下一次 `chat-logs` 运行的日志写着
   `the relay archives its records in its own bucket`，不再提交新记录。
6. 读回某一天（输出目录 `.archive/` 已被 git 忽略，切勿提交）：

   ```bash
   export LOG_EXPORT_TOKEN=…
   python3 relay/collect.py archive --day 2026-10-14            # → .archive/chat-logs/2026/10/14.jsonl
   python3 security/collect.py archive --day 2026-10-14         # → .archive/security-logs/{relay,site}/2026/10/14.jsonl
   ```

7. 保存期限：由发布方决定，并写进网页的记录说明。建议对话保存 90 天、安全事件 30 天：

   ```bash
   npx wrangler@4 r2 bucket lifecycle add taochronos-archive chat-logs-90d chat-logs/ --expire-days 90
   npx wrangler@4 r2 bucket lifecycle add taochronos-archive security-30d security-logs/ --expire-days 30
   ```

停用归档：删除变量 `ARCHIVE_BUCKET`，再运行两个工作流；收集器从各自的游标继续（编号不会重复）。已提交在 `data/` 里的旧
记录仍在仓库历史中，要清除须另行决定、另行操作。

### A7. 边缘规则

1. 3.2、3.3 两个令牌存为机密，`CLOUDFLARE_ZONE_ID` 存为变量（第 4 节）。
2. **Actions → security → Run workflow**，action 选 `plan`：只列出会改动什么，不写入。
3. 再运行一次，action 选 `apply`。
4. 48 小时后：**impf.ai → Security → Events**，按描述 `[taochronos]` 筛选，确认没有真实访客被拦下。

这些规则（`security/rules.yaml`）是按免费配套的限制写的（5 条自定义规则、1 条速率限制，窗口 10 秒）。Workers 付费配套是
Workers 的配套，WAF 的限制取决于区域本身的配套。区域升级到 Pro 或更高时，规则才可以扩充（更长的速率限制窗口；Business
起可用正则表达式）；在此之前维持原样。

### A8. 付费配套的调整

| 项目 | 位置 | 建议 |
|---|---|---|
| 哨兵模式 | `relay/wrangler.toml` 与 `cloud/site/wrangler.toml` 的 `SENTINEL` | `observe` 两周后查看 `shadow` 事件；若没有一条是真实访客，两处都改为 `"enforce"`（security/README.md 第三节） |
| 每位访客的模型费用 | 中转的 `TOKENS_PER_DAY`、`PER_DAY` | 默认每个网络地址每天 1,000 万 token、600 次调用。同一医院或办公室地址后面的许多人共用这份额度；有人反映不够就调高（按访客分配的会话是计划中的根本办法，见 ADR 0023） |
| 全体的模型费用 | 中转的 `TOTAL_TOKENS_PER_DAY`、`TOTAL_PER_DAY` | 每天 2 亿 token、5,000 次调用，是最坏一天的上限。按 MiniMax 预算设定 |
| 网站的读取与调用 | 网站的 `API_READS_PER_DAY`、`API_CALLS_PER_DAY` | 每个地址每天 6,000 / 3,000 次，有意放宽 |
| 待取走的记录 | 中转的 `LOG_KEEP` | 50,000 条；达到后拒收新记录并写一行 `logs full`，已收下的一条不丢 |
| 容器 | `SLEEP_AFTER`、`instance_type` | 见 A4 |

每次修改：在 `main` 上编辑该文件，工作流会自动重新部署。

---

## 6. 路线 B 新账户从零开始

1. 在区域所在的账户开通 Workers 付费配套（第 2 节）。
2. 建立三个令牌（第 3 节），设置机密与变量（第 4 节）。
3. 中转：**Actions → relay → Run workflow**（A1）。**不要**事先为 `chat-api` 建 DNS 记录：Cloudflare 会自动建立记录并签发证书。
4. 网站：若 `chat.impf.ai` 有一条自建的 DNS 记录（指向 GitHub Pages 的 CNAME），先在 **impf.ai → DNS → Records** 删除这一条，
   再 **Actions → site → Run workflow**。几分钟内即以 HTTPS 提供服务。
5. 语料（A3）、容器（A4）、D1 备份（A5）、归档（A6）、边缘规则（A7）、调整（A8）。
6. 可选：确认 `chat.impf.ai` 已由 Cloudflare 提供后，在 GitHub → **Settings → Pages** 移除自定义域名；Pages 网站继续作为镜像，
   地址 `https://psknlr.github.io/TaoChronos/`。

---

## 7. 检查部署

```bash
# 网站：由 Cloudflare 以 HTTPS 提供，有 HSTS，http 自动跳转
curl -sI https://chat.impf.ai/ | grep -iE '^(HTTP|server|strict-transport-security)'
curl -s -o /dev/null -w '%{http_code}\n' http://chat.impf.ai/          # 301

# 由哪份语料回答
curl -s https://chat.impf.ai/api/info | python3 -c 'import json,sys; i=json.load(sys.stdin); c=i.get("corpus",{}); print(i.get("runtime"), c.get("label"), c.get("books"), "backup" if i.get("backup") else "")'
#   容器：      … 全量语料 958
#   D1 备份：   d1 全量语料（备份） 958 backup
#   两者都没有：返回错误与 "corpus": "none"（页面在浏览器里运行要籍语料）

# 默认服务
curl -s https://chat-api.impf.ai/v1/health
python3 relay/collect.py check                                         # 经中转做一次极小的模型调用

# 哨兵此刻看到什么（需要收集器令牌）
LOG_EXPORT_TOKEN=… python3 security/collect.py summary
```

在浏览器里：https://chat.impf.ai 显示锁的图标；问「桂枝汤的组成出自哪部书？」；回答里的引文一点即可核对；
**设置 → 关于** 链接到全量语料的来源与授权。

Cloudflare 控制台：**Workers & Pages** 列出 `taochronos-site`、`taochronos-relay`、`taochronos-corpus`，各有 **Metrics** 与
**Logs**；**D1** 列出 `taochronos-d1-0` … `-4`；**R2** 列出归档存储桶。

---

## 8. 自动运行的工作

| 工作流 | 时间（UTC / 新加坡时间） | 做什么 |
|---|---|---|
| `relay` | 推送到 `main` 且改动了 `relay/` 或 `security/` | 测试、部署、检查中转 |
| `site` | 推送到 `main` 且改动了网站、代码、语料或 `security/` | 测试、部署网站；容器的输入有变时构建容器；绑定并检查 |
| `chat-logs` | 每小时第 17 分钟（新加坡时间同一分钟） | 把记录与哨兵事件收进仓库（只限没有归档的 Worker） |
| `d1` | 每天 00:07 UTC / 08:07 SGT | 继续或检查 D1 导入 |
| `security` | 每天 01:41 UTC / 09:41 SGT；推送 `security/blocklist.yaml` 时 | 取回边缘事件；写入封禁名单 |
| `pages` | 推送到 `main` 且改动了网页客户端 | GitHub Pages 镜像 |
| `ci` | 每次推送与 Pull Request | Python 与 Worker 的测试 |

Worker 内部：归档的定时器（记录或被标记的事件写入约半分钟后）；容器闲置 `SLEEP_AFTER` 后休眠。

---

## 9. 费用与防护

Cloudflare 以美元计费：Workers 付费配套每月 5 美元，各项产品超出所含额度的部分另按用量收费。下表是撰写时 Cloudflare 公布的
数字，使用前请再查阅价格页面（[Workers](https://developers.cloudflare.com/workers/platform/pricing/)、
[Containers](https://developers.cloudflare.com/containers/pricing/)、[D1](https://developers.cloudflare.com/d1/platform/pricing/)、
[Durable Objects](https://developers.cloudflare.com/durable-objects/platform/pricing/)、[R2](https://developers.cloudflare.com/r2/pricing/)）。

| 项目 | 每月所含 | 本网站的用量 |
|---|---|---|
| Workers 请求 / CPU | 1,000 万次请求、3,000 万 CPU 毫秒 | 只有网页与 `/api/*` 经过 Worker；静态文件免费 |
| Containers | 25 GiB·小时内存、375 vCPU·分钟、200 GB·小时磁盘 | `standard-1` 每运行一小时约 0.036 美元：每天运行 4 小时约每月 4 美元，从不休眠约每月 30 美元 |
| D1 | 读取 250 亿行、写入 5,000 万行、存储 5 GB | 约存 1.5 GB；一次导入约写 10 万行 |
| Durable Objects | 100 万次请求（另含时长与 SQLite 存储额度） | 每次 API 调用或模型调用几次 |
| Workers KV | 存储 1 GB | 语料 143 MB |
| R2 | 10 GB·月存储、100 万次 A 类与 1,000 万次 B 类操作 | 每条记录或事件写一次 |
| **MiniMax**（不属 Cloudflare） | 您的账户余额 | 远比其他各项多；由中转的限额约束（A8） |

防护：中转按网络地址与全体、按天的 token 与调用限额；网站的每日上限；容器休眠；哨兵。账单提醒不是上限：仍建议在
**Notifications → Add → Billing** 设一个（按用量计费的提醒，视账户是否提供），并把 MiniMax 余额维持在愿意花费的数目。

---

## 10. 日常维护

| 要做的事 | 怎么做 |
|---|---|
| 更换 MiniMax 密钥 | 在 MiniMax 新建密钥 → 更新机密 `MINIMAX_API_KEY` → **Actions → relay → Run workflow** → 检查通过后删除旧密钥 |
| 更换部署令牌 | 按 3.1 新建 → 更新 `CLOUDFLARE_API_TOKEN` → 运行 **relay** 与 **site** → 删除旧令牌 |
| 更换收集器令牌 | 新的随机串 → 更新 `LOG_EXPORT_TOKEN` → 运行 **relay** 与 **site** |
| 更新全量语料 | 以新语料做 A3；合并新的 `cloud/store.json` 后自动重建容器；d1 工作流重新导入（旧数据库会被替换） |
| 调整限额或模式 | 在 `main` 上修改该 Worker 的 `wrangler.toml` 的 `[vars]` |
| 停止记录对话 | `relay/wrangler.toml` 里 `LOGS = "off"`；网页随即不再询问 |
| 暂停默认服务 | 控制台 → `taochronos-relay` → **Settings → Variables and Secrets** → 删除 `MINIMAX_API_KEY`；网页改请访客填自己的密钥。恢复时运行 **relay** |
| 立即封锁一个地址 | 控制台 → **Manage Account → Configurations → Lists → `taochronos_block`**；之后补进 `security/blocklist.yaml` |
| 查看哨兵 | `LOG_EXPORT_TOKEN=… python3 security/collect.py summary` |
| 读回归档的记录 | 见 A6 第 6 步 |

---

## 11. 回滚

- **某个 Worker**：控制台 → **Workers & Pages** → 该 Worker → **Deployments** → 选一个较早的版本 → **Rollback**；或在 `main`
  上撤销（revert）那个提交，由工作流重新部署。本次改动没有新增 Durable Object 迁移，所以把中转或网站回滚到它之前是安全的。
  归档尚未取走的记录留在中转里，解除存储桶绑定后由仓库的收集器照常取走。
- **容器**：从较早的提交运行 **site** 并勾选 **rebuild**（Run workflow → 选分支或标签）。
- **退回 GitHub Pages**（最后手段）：在网站 Worker 的 **Domains & Routes** 移除 `chat.impf.ai`；新建 CNAME `chat` →
  `psknlr.github.io`，代理状态 **DNS only**；在仓库 **Settings → Pages** 填回自定义域名。

---

## 12. 疑难排解

| 现象 | 原因 | 处理 |
|---|---|---|
| relay：`the relay is not deployed until these repository secrets are set: …` | 缺少机密或名称拼错 | 按第 4 节一字不差地补上，再运行 |
| `Authentication error [code: 10000]` | 令牌权限或账户不对 | 核对 `CLOUDFLARE_ACCOUNT_ID`；按 3.1 修改令牌 |
| `No access to the specified resource`（地址含 `workers/routes`） | 令牌的 Zone Resources 没有 `impf.ai` | 修改令牌，加上该区域 |
| site：`externally managed DNS records` | `chat` 有一条账户自建的 DNS 记录 | 删除那条记录（第 6 节第 4 步），立即运行 **site** |
| corpus：`the account may not deploy containers yet` | 没有付费配套，或没有 Containers · Edit | 做 A2，再勾选 **rebuild** 运行 **site** |
| corpus：`the store … is not (all) in the KV namespace` | 语料尚未上载 | 做 A3 |
| corpus：`container was not deployed` | 构建或部署失败（错误在上一步的日志里） | 修正后勾选 **rebuild** 运行 **site** |
| d1：`the API token may not use D1` | 没有 D1 · Edit | 做 A2，再运行 **d1** |
| d1 停在 `the day's budget` | 达到了 budget（定时运行为 90,000）；同一个 UTC 日的各次运行合并计算 | 以 budget `1000000` 再运行 |
| d1 停在 `the run's time is up` | 用完了五小时 | 再运行一次，会从断点继续 |
| `/api/info` 返回 503、`corpus: none` | 容器与 D1 备份都没有绑定 | 查看 corpus 与 d1 的运行记录，然后运行 **site** |
| 访客看到「该地址因异常访问已被暂时限制」 | 哨兵拒绝了这个地址（403） | 查看它的事件；若是误判，调短 `BLOCK_SECONDS` 或把 `SENTINEL` 改回 `observe` |
| 访客看到「今天的查询次数已用完」 | 该地址达到每日上限（429） | 若是真实访客，调高 `API_READS_PER_DAY` / `API_CALLS_PER_DAY` |
| relay 检查：`MiniMax refused the key … api.minimax.io` | 国际站密钥配了中国大陆的地址（或相反） | 修改 `relay/wrangler.toml` 的 `UPSTREAM_BASE`（A1.3） |
| Workers Logs：`logs full` | 记录很久没有被取走 | 查看 `chat-logs` 的运行；使用归档时查找 `archive … Error` |
| 部署：`the archive's bucket … may be public` | 开了 r2.dev、绑了自定义域名，或令牌读不到这两项 | 关闭 r2.dev、移除域名、确认 R2 权限，再运行 |
| `chat-logs`：`the records could not be pushed` | `main` 受保护，Actions 不能推送 | 允许 GitHub Actions 推送，或改用归档（A6） |
| `chat-logs`：`the relay refused the export: HTTP 401` | GitHub 与 Worker 的 `LOG_EXPORT_TOKEN` 不一致 | 运行 **relay**（及 **site**）重新写入 |

---

## 13. 参考 文件与工作流

| 路径 | 内容 |
|---|---|
| `relay/wrangler.toml`、`relay/src/` | 默认服务（限额、哨兵模式、记录） |
| `cloud/site/wrangler.toml`、`cloud/site/src/`、`cloud/site/deploy.sh` | 网站及其部署（按账户已有的资源加上绑定） |
| `cloud/corpus/wrangler.toml`、`cloud/corpus/Dockerfile` | 全量语料的容器 |
| `cloud/store.json` | 所部署的语料 |
| `security/sentinel.js`、`security/archive.js`、`security/bind-archive.sh` | 哨兵、归档、存储桶检查 |
| `security/rules.yaml`、`security/blocklist.yaml` | 边缘规则与封禁名单 |
| `relay/collect.py`、`security/collect.py` | 仓库的收集器（pull、ack、archive、summary、check） |
| `.github/workflows/` | `relay`、`site`、`d1`、`chat-logs`、`security`、`pages`、`canon`、`ci` |
