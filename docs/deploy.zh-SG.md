# 道乃久在 Cloudflare Workers 付费配套上的部署手册

本手册写给 Cloudflare 账户与本仓库的负责人。它说明部署现在到了哪一步、离全量语料还差什么，以及从这里出发的每一步：
经 GitHub Actions 或从您自己的电脑部署全量语料（958 部古籍）、从各来源重建语料、默认服务、归档、边缘规则，以及日常运行。
前提是账户已开通 **Workers Paid 付费配套**（D1、Durable Objects 与 Containers 也随之改为按用量计费）。

English version: [deploy.md](deploy.md)。本手册汇总了以下较早的教程：[cloud/SETUP.md](../cloud/SETUP.md)、
[cloud/README.md](../cloud/README.md)、[relay/SETUP.md](../relay/SETUP.md)、[security/README.md](../security/README.md)。
背后的设计决定见 ADR [0012](adr/0012-default-service-relay.md)、[0016](adr/0016-site-and-full-corpus-on-cloudflare.md)、
[0017](adr/0017-d1-backup.md)、[0018](adr/0018-sentinel-and-edge-rules.md)、[0023](adr/0023-workers-paid.md)。

时间以 UTC 与新加坡时间（SGT，UTC+8）标示。Cloudflare 与 GitHub 的界面是英文，按钮与菜单名称照原文引用。

**通往全量语料的捷径：** 先读第一部分（五分钟），做完第二部分（解除阻碍），再从第三部分的路线 A 与路线 B 中**任选其一**。
第四部分是其余步骤，第五部分供日后运行参考。

---

## 目录

- [第一部分 现况](#第一部分-现况)
- [第二部分 解除阻碍 GitHub Actions 与部署令牌](#第二部分-解除阻碍-github-actions-与部署令牌)
- [第三部分 全量语料](#第三部分-全量语料)
- [第四部分 其他步骤](#第四部分-其他步骤)
- [第五部分 日常运行](#第五部分-日常运行)

---

## 第一部分 现况

根据 2026 年 10 月 17 日仓库工作流的日志整理。

| 部分 | 状态 | 依据 |
|---|---|---|
| 网站 `chat.impf.ai` | **运行中**，10 月 11 日 17:31 UTC 部署（版本 `4c6d9a24…`），只在浏览器里运行要籍语料 | 10 月 11 日的 site 运行：`the site runs without the full corpus` |
| 默认服务 `chat-api.impf.ai` | **运行中**，10 月 11 日 17:30 UTC 部署 | 10 月 11 日的 relay 运行 |
| 全量语料（958 部） | **已上载**到 KV 命名空间 `taochronos-store`：6 个分片齐全，校验和已核对 | 10 月 11 日 00:38 UTC 的 canon 运行取回并核对了每个分片；`cloud/store.json` 自 10 月 1 日以来未变 |
| 全量语料：容器 | **从未部署** | site 运行：Containers 接口返回 `401`，令牌缺 **Containers · Edit**（或当时账户仍是免费配套） |
| 全量语料：D1 备份 | **从未导入** | 10 月 1–11 日启动过的每一次 d1 运行都在 20 秒内停在令牌检查；最后一次是 `the API token may not use D1 (HTTP 401)`：令牌缺 **D1 · Edit** |
| 付费配套的改动（ADR 0023，PR #35） | **已合并到 `main`，尚未部署** | 10 月 14 日的部署根本没有启动（见下） |
| GitHub Actions | **自 10 月 11 日约 20:20 UTC 起不再启动任何任务** | 此后每次运行都在约 4 秒内失败，没有运行器，也没有日志 |

这意味着：

1. **语料不必重建。** 网站所需的语料已经在 Cloudflare 里。缺的是把它变成服务：用它构建容器，以及把它导入 D1。
2. 一直以来挡住这两件事的，是**部署令牌缺两项权限**：Containers · Edit 与 D1 · Edit。
3. **GitHub Actions** 停了，经由它运行的一切也都停了：部署、每小时收集对话记录（这期间记录安全地留在中转里）、
   每天的 D1 与安全任务。请修复它（2.1），或从您自己的电脑部署（第三部分路线 B），或两者都做。

---

## 第二部分 解除阻碍 GitHub Actions 与部署令牌

### 2.1 GitHub Actions

**找出原因。** 打开任意一次最近失败的运行，例如 **Actions → relay →** *Merge pull request #35*。任务为何没有启动，GitHub
写在运行页面的顶部（API 不显示）。私有仓库通常是以下几种之一：

| 讯息（大意） | 原因 | 处理 |
|---|---|---|
| *recent account payments have failed or your spending limit needs to be increased* | 本月所含的 Actions 分钟数已用完，而 Actions 的预算 / 支出上限是 0 或已达到 | GitHub → 头像 → **Settings → Billing and licensing**：在 *Usage* 查看 Actions 分钟数；在 *Budgets*（或 *Spending limits*）调高 Actions 预算，或取消达到上限即停止；确认付款方式有效 |
| *your account is locked due to a billing issue* | 付款失败 | **Billing and licensing → Payment information**：更新信用卡，再重新运行 |
| *Actions is disabled for this repository* | 设置关闭了 | 仓库 **Settings → Actions → General → Actions permissions** |

修复后，重新运行合并触发的两次部署：**Actions → relay →** *Merge pull request #35* **→ Re-run all jobs**，再对 **site**
做同样的操作。（请先做 2.2，这样 site 的运行会顺带构建容器。）

**分钟数为何用完、怎样少用。** GitHub Free 的私有仓库每月有 2,000 分钟 Linux 运行时间（Pro：3,000）；每个任务按整分钟向上取整。

| 工作流 | 大约用量 | 节省办法 |
|---|---|---|
| `ci`：每个分支的每次推送，4 个任务 | 每次推送 10–15 分钟；至今约 180 次 | 用量最大的一项。少推送几次，或把 `ci.yml` 限于 Pull Request 与 `main` |
| `chat-logs`：每小时一次 | 即使无事可做，每月也约 720 分钟 | 两个 Worker 都启用归档后（4.2），**Actions → chat-logs → ⋯ → Disable workflow** |
| `d1` 导入 | 每次最多 300 分钟 | 从自己的电脑导入（路线 B，B5 步） |
| 构建容器的 `site` | 20–30 分钟 | 只在语料或其代码改变时 |
| `security`、`pages`、`relay`、不构建容器的 `site` | 各 1–3 分钟 | — |

### 2.2 Cloudflare 部署令牌

机密 `CLOUDFLARE_API_TOKEN` 就是部署令牌。它需要的权限正好是下表这些（**My Profile → API Tokens →** 该令牌 **→ ⋯ → Edit**；
修改权限不会改变令牌的值）：

| 范围 | 权限 | 级别 | 用途 |
|---|---|---|---|
| Account | Workers Scripts | Edit | 两个 Worker 及其 Durable Objects |
| Account | Account Settings | Read | wrangler |
| Account | Workers KV Storage | Edit | 语料的命名空间 |
| Account | **Containers** | **Edit** | 全量语料的容器：**至今一直缺少** |
| Account | **D1** | **Edit** | D1 备份：**至今一直缺少** |
| Account | **Workers R2 Storage** | **Edit** | 归档（4.2） |
| Zone | Workers Routes | Edit | 自定义域名 |

- **Account Resources**：*Include* → 您的账户。**Zone Resources**：*Include* → *Specific zone* → `impf.ai`。
- **Client IP Address Filtering**：留空。**TTL**：留空，或设一个您会记得提前更换的日期。

**在任何一台电脑上检查**（GitHub 里读不回令牌的值；若手边已没有它，按上表新建一个令牌，存为机密 `CLOUDFLARE_API_TOKEN`，
这里也用它）：

```bash
export CLOUDFLARE_API_TOKEN=…            # 部署令牌
export CLOUDFLARE_ACCOUNT_ID=…           # 控制台 → 任一区域 → Overview → API → Account ID
api="https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID"
for p in containers/me "d1/database?per_page=1" "storage/kv/namespaces?per_page=100" "r2/buckets"; do
  printf '%-36s ' "$p"; curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" "$api/$p"
done
```

每一行都应是 `200`。`containers/me` 返回 `401` 或 `403`：缺 Containers · Edit，或账户不是付费配套；`d1/database`：缺
D1 · Edit；`r2/buckets`：缺 R2 权限（只有归档需要）。这些正是工作流所做的检查。

### 2.3 GitHub 机密与变量

仓库 → **Settings → Secrets and variables → Actions**。机密放在 **Secrets** 标签（*Repository secrets*），变量放在 **Variables** 标签。

| 机密 | 值 | 是否需要 |
|---|---|---|
| `CLOUDFLARE_API_TOKEN` | 部署令牌（2.2） | 需要 |
| `CLOUDFLARE_ACCOUNT_ID` | Account ID | 需要 |
| `MINIMAX_API_KEY` | MiniMax 密钥 | 默认服务需要 |
| `LOG_EXPORT_TOKEN` | 16 位以上随机串：`openssl rand -hex 32` | 需要 |
| `SENTINEL_SALT` | `openssl rand -hex 32` | 建议 |
| `STATS_TOKEN` | 16 位以上随机串 | 可选（「设置 → 统计」） |
| `CLOUDFLARE_SECURITY_TOKEN` | Zone WAF、Zone Settings、Bot Management：Edit；Zone：Read；Account Filter Lists：Edit（区域 `impf.ai`） | 边缘规则需要 |
| `CLOUDFLARE_ANALYTICS_TOKEN` | Zone Analytics：Read（区域 `impf.ai`） | 每天取回边缘事件需要 |

| 变量 | 值 | 何时需要 |
|---|---|---|
| `CLOUDFLARE_ZONE_ID` | `impf.ai` → **Overview** → *API* → Zone ID | 每天取回边缘事件 |
| `ARCHIVE_BUCKET` | 如 `taochronos-archive` | 归档（4.2） |
| `STORE_TOKEN_SHA256` | 一次性上载令牌的 sha256 | 只在上载新语料期间（3.4），完成后删除 |
| `D1_BUDGET` | `90000` | 只在 D1 免费配套（每天导入一段）；付费配套不要设 |
| `RELAY_URL`、`SITE_URL` | 其他地址 | 只在不用 `chat-api.impf.ai` / `chat.impf.ai` 时 |

---

## 第三部分 全量语料

### 3.1 它是什么，怎样到达访客

全量语料是本项目收录、且来源条件允许随网站发布的全部古籍：**958 部书、2,038,497 段、122,219,380 字**（`cloud/store.json`，
sha256 `ef628936…`；来源与授权见 [cloud/ATTRIBUTION.md](../cloud/ATTRIBUTION.md)）。它是一个 143 MB 的压缩 SQLite 文件，分成
6 个 24 MiB 的分片，存在网站的 KV 命名空间里。由它构建出两种服务：

| | 容器（`taochronos-corpus`） | D1 备份（`taochronos-d1-0 … -4`） |
|---|---|---|
| 运行什么 | taochronos 本身（Python），在已建索引、已预热缓存的语料上 | 网站自己的 Worker，语料分布在 5 个 D1 数据库里 |
| 工具 | 全部，包括研究任务 | 14 个实时计算、16 个对常见条目预先算好，其余（研究、句读、D1–D5……）不可用 |
| 由谁构建 | `site` 工作流（corpus 任务），或 `wrangler deploy`（路线 B） | `d1` 工作流，或 `python -m taochronos.chat.d1 import`（路线 B） |
| 所需时间 | 构建约 20 分钟；休眠后唤醒需几十秒 | 导入约 2–2.5 小时，只需一次 |
| 费用 | 运行时计费（闲置 15 分钟即休眠） | 存储约 1.5 GB，每次检索按读取行数计 |

部署了容器时，网站把 API 交给容器；否则在 D1 导入完成时交给 D1 备份；两者都没有时，页面在浏览器里运行要籍语料（535 部）。
**两者都部署**：容器是完整的服务；部署时找不到容器（例如构建失败），D1 就接手，读者不会因此退回浏览器里较小的语料。

### 3.2 路线 A 经 GitHub Actions

前提：2.1 已修复，2.2 已完成。

**A1. 容器。**
1. **Actions → site → Run workflow** → 分支选 `main` → 勾选 **rebuild** → **Run workflow**。
2. 任务 **corpus**：
   - *Which version … may the account deploy containers?* 输出 `deployed: none; this commit: ef628936d382-…`，没有警告。
     （出现 `the account may not deploy containers yet` 就回到 2.2。）
   - *The store, from the site's KV namespace* 取回 6 个分片并逐一校验。
   - *Build the image and deploy the corpus Worker*：约 20 分钟。
3. 接着任务 **bind** 再部署一次网站、绑定容器，并在全量语料上做一次检索；日志最后是 `a search on the full corpus: …`。

**A2. D1 备份。**
1. **Actions → d1 → Run workflow** → 分支选 `main` → **budget** 填 `1000000`（默认值）→ **Run workflow**。（budget 原是免费
   配套每天 10 万行的上限，在付费配套上只是安全阀。导入约写 10 万行。每天 00:07 UTC 的定时运行用同一个默认值，也会一次导完；
   推送到 `main` 的提交若改动了 `cloud/store.json` 或导入程序，也会启动一次运行（若已有运行在进行，等它结束后才开始）。）
2. 先写入语料（约 87,000 行，约一个半小时），再用运行器上所有的处理器并行计算预先算好的结果（约 12,000 行）：私有仓库的运行器
   是双核，约一小时；四核约半小时，单核约两小时（均为估计）。以 `the run's time is up`（五小时）结束，表示被截断了：再运行
   一次就会从断点继续，不会重复写入；每天 00:07 UTC（新加坡时间 08:07）的定时运行也会接着导入。
3. 完成时，该次运行的 **Summary** 写着 `complete: yes`；它在 KV 里记下版本，并自动启动 **site** 工作流，绑定数据库。

**A3. 检查**，见 3.5。

### 3.3 路线 B 从您自己的电脑

用相同的命令，在您自己的机器上做工作流所做的事。适用于 GitHub Actions 受阻时，或为了节省分钟数（单是 D1 导入就要用大约两小时）。

**B0. 机器。**

| 需要 | 原因 |
|---|---|
| **Linux x86-64**：Ubuntu 22.04 或 24.04、云端虚拟机，或 Windows 上的 **WSL2** | `cloud/site/deploy.sh` 用的是 GNU `sed`；Cloudflare 的容器运行 `linux/amd64` 映像，在 ARM 的 Mac 上要靠模拟构建，非常慢 |
| **Docker**（Docker Engine，或配合 WSL2 的 Docker Desktop） | wrangler 在本机构建容器映像 |
| Node.js 22、Python 3.12、git、curl、xz-utils | Worker、taochronos、下载 |
| 约 30 GB 可用磁盘，稳定的上传网速 | 解压并建好索引的语料、映像（1.8 GB）及其分层；映像要上载到 Cloudflare |
| 部署令牌与 Account ID | 2.2 |

耗时的步骤（B3、B5）请在 `tmux` 或 `screen` 里启动，合上笔记本电脑也不会中断。

**B1. 准备。**

```bash
git clone https://github.com/psknlr/TaoChronos.git && cd TaoChronos     # main，含 PR #35
python3 -m venv .venv && . .venv/bin/activate && pip install -e .
export CLOUDFLARE_API_TOKEN=… CLOUDFLARE_ACCOUNT_ID=…
export WRANGLER=wrangler@4.142.0 WRANGLER_SEND_METRICS=false
export STORE_NAMESPACE=taochronos-store SITE_URL=https://chat.impf.ai RELAY_URL=https://chat-api.impf.ai
export ARCHIVE_BUCKET=                                                  # 设好归档后填存储桶名称（4.2）
api="https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID"
auth="Authorization: Bearer $CLOUDFLARE_API_TOKEN"
NS=$(curl -fsS -H "$auth" "$api/storage/kv/namespaces?per_page=100" \
  | python3 -c 'import json,sys,os; print(next(n["id"] for n in json.load(sys.stdin)["result"] if n["title"]==os.environ["STORE_NAMESPACE"]))')
echo "KV 命名空间：$NS"
```

**B2. 从 KV 取回语料并校验**（与工作流相同的命令）：

```bash
mkdir -p cloud/.store/parts
python3 - <<'EOF' > cloud/.store/parts.txt
import json, urllib.parse
m = json.load(open("cloud/store.json"))
for p in m["parts"]:
    print(urllib.parse.quote(m["key"] + p["name"], safe=""), p["name"], p["sha256"])
EOF
while read -r key name sha; do
  curl -fsS -H "$auth" "$api/storage/kv/namespaces/$NS/values/$key" -o "cloud/.store/parts/$name"
  echo "$sha  cloud/.store/parts/$name" | sha256sum -c --quiet
done < cloud/.store/parts.txt
sha=$(python3 -c 'import json; print(json.load(open("cloud/store.json"))["sha256"])')
while read -r _ name _; do cat "cloud/.store/parts/$name"; done < cloud/.store/parts.txt > "cloud/.store/$sha.sqlite.xz"
echo "$sha  cloud/.store/$sha.sqlite.xz" | sha256sum -c && rm -rf cloud/.store/parts cloud/.store/parts.txt
```

最后的校验输出 `… OK`。若出现 `curl: (22) … 404`，说明有分片不在 KV 里：先上载语料（3.4）。

**B3. 构建并部署容器。**

```bash
# 工作流会给这个提交的版本：语料，加上构建映像所用的每一个文件
store=$(python3 -c 'import json; print(json.load(open("cloud/store.json"))["sha256"])')
tree=$(git ls-tree -r HEAD -- pyproject.toml README.md src architecture-policy.yaml profiles domains corpus/catalog corpus/demo \
         corpus/modern agents skills evals/gold cloud/corpus cloud/store.json .dockerignore | sha256sum | cut -c1-12)
VERSION="${store:0:12}-${tree}"; echo "$VERSION"
(cd cloud/corpus && npm ci --no-audit --no-fund && npx --yes "$WRANGLER" deploy --var "VERSION:$VERSION")
# 部署成功之后，才像工作流那样记下“已部署”
curl -fsS -X PUT -H "$auth" -H "Content-Type: text/plain" --data-binary "$VERSION" "$api/storage/kv/namespaces/$NS/values/deployed%2Fcorpus" >/dev/null && echo recorded
```

构建映像时会解压语料、建索引、预热各工具的缓存（视机器而定 10–25 分钟），然后上载 1.8 GB。wrangler 最后显示
`Deployed taochronos-corpus`。

**B4. 部署网站并绑定容器。**

```bash
taochronos web build -o _site --relay "$RELAY_URL" --unlist minimax,minimax-global
CORPUS_DEPLOYED=1 bash cloud/site/deploy.sh
```

`deploy.sh` 绑定账户已有的资源（语料命名空间、容器、导入完成后的 D1 数据库、`ARCHIVE_BUCKET` 指定的私有存储桶），部署，
再检查网站。Worker 会保留它已有的机密：这里不必提供 `LOG_EXPORT_TOKEN` 等（提示未设置，只表示不会重写）。日志最后是
`a search on the full corpus: …`。新映像后的第一次调用可能要等几分钟让容器启动，`deploy.sh` 会等它。

**B5. 导入 D1 备份**（四核机器上约两小时，请在 `tmux` 里运行）：

```bash
xz="cloud/.store/$sha.sqlite.xz"
PYTHONHASHSEED=0 python -m taochronos.chat.d1 import "$xz" --manifest cloud/store.json --work cloud/.d1 \
  --api --budget 1000000 --reset --precompute --workers 0 --report cloud/.d1/report.json
python3 -c 'import json; r=json.load(open("cloud/.d1/report.json")); print(r["version"], "complete" if r["complete"] else r["stopped"])'
```

中断了（网络、电脑）？再运行同一条命令：它从数据库读出进度，不会重复写入。最后一行显示 `complete` 后：

```bash
D1V=$(python -m taochronos.chat.d1 version)
curl -fsS -X PUT -H "$auth" -H "Content-Type: text/plain" --data-binary "$D1V" "$api/storage/kv/namespaces/$NS/values/deployed%2Fd1" >/dev/null && echo recorded
CORPUS_DEPLOYED=1 bash cloud/site/deploy.sh            # 再部署一次网站，这次连五个数据库也绑定
```

**B6. 检查**，见 3.5。**B7.** 从自己的电脑部署默认服务：见 4.1。

完成后可以删除 `cloud/.store/`、`cloud/.d1/` 与 `_site/`，git 不追踪它们。

### 3.4 更新语料 从各来源重建

只在语料本身改变时（新来源、新文本、新的规范化器）才需要。在此之前，KV 里的语料照常使用。

**收哪些。** 网站的语料只收条件允许发布的来源（`WEB_SOURCES`），条件禁止的（`NEVER_PACKED`）一律不收：

| 来源 | 命令中的名称 | 是否进网站语料 | 授权 |
|---|---|---|---|
| 汉籍仓库 KR3e（四库全书 医家类，100 部）及其书目 | `kanripo`、`kr-catalog` | 是 | CC BY-SA 4.0 |
| 中醫笈成 v1.4.8（816 部） | `jicheng`（**存档由您提供**：`jc_1_4_8_all.7z.001 … .003`） | 是 | CC0 1.0（编辑成果） |
| 麦吉尔大学 妇科善本 | `mcgill` | 是 | Public Domain Mark |
| 數位中醫校書郎 CMETA（11 部精校本） | `cmeta` | 是 | CC BY 4.0 |
| 维基文库（数据转储） | `wikisource` | 是 | CC BY-SA 4.0 |
| TCM-Ancient-Books、tcmoc | `tcm-ancient-books`、`tcmoc` | 是，由发布方决定；笈成本的副本不收 | 未声明 |
| 東亜医学協会 | `aeam` | **永不** | 不得转载 |
| Hugging Face classical-tcm-canon | `hf-tcm-canon` | **永不** | 专有授权 |

**在本机建立全量语料**（需要足够的磁盘与时间；文本存放在 `.taochronos/`，git 不追踪）：

```bash
pip install -e ".[pdf,parquet]"          # pypdf 读 aeam 的 PDF，pyarrow 读 Hugging Face 的 Parquet 文件
taochronos corpus fetch kanripo && taochronos corpus ingest kanripo
taochronos corpus fetch kr-catalog && taochronos corpus catalog kr-catalog && taochronos corpus ingest kanripo --changed
taochronos corpus unpack jicheng jc_1_4_8_all.7z.001 jc_1_4_8_all.7z.002 jc_1_4_8_all.7z.003
taochronos corpus catalog jicheng && taochronos corpus ingest jicheng
for s in mcgill cmeta aeam wikisource tcm-ancient-books tcmoc hf-tcm-canon; do
  taochronos corpus fetch $s && taochronos corpus catalog $s && taochronos corpus ingest $s
done
taochronos corpus status                 # 书数、段数、时期；索引是否与异体表一致
taochronos corpus reindex                # 只在 status 说不一致时（笈成的书目会增补异体）
```

`aeam` 与 `hf-tcm-canon` **只在本机使用**，`web store` 绝不把它们放进网站的语料。之所以仍要导入，是因为排名较低的来源
（维基文库、网络文本集）要与它们比对去重：少了它们，它们文本的副本就会被收进来，语料就与已发布的不同。每次取回都锁定在
`corpus/sources.lock.yaml`；来源相同，取回的文本就相同。各来源的细节见 [docs/data.md](data.md)。

**生成并上载网站的语料：**

```bash
t=$(openssl rand -hex 32); printf %s "$t" | sha256sum       # 一次性上载令牌及其 sha256（令牌只留在本机）
# GitHub → Settings → Secrets and variables → Actions → Variables：STORE_TOKEN_SHA256 = 上面的 sha256，然后
# Actions → site → Run workflow；或在路线 B 的机器上：STORE_TOKEN_SHA256=<上面的 sha256> bash cloud/site/deploy.sh
taochronos web store                                         # .taochronos/cloud/<sha256>.sqlite.xz、cloud/store.json、cloud/ATTRIBUTION.md
TAOCHRONOS_STORE_TOKEN=$t taochronos web upload              # 6 个分片上载到 https://chat.impf.ai/api/store/…（已有的分片跳过）
# 立即删除变量 STORE_TOKEN_SHA256，并再部署一次网站，关闭上载
git add cloud/store.json cloud/ATTRIBUTION.md && git commit -m "The site's store: …"   # 再开 Pull Request 合并到 main
```

新的 `cloud/store.json` 就是新版本：合并到 `main` 后，用路线 A（A1、A2）或路线 B（B2–B5）构建新容器、重新导入 D1（旧数据库
会被替换；这期间由容器或页面的浏览器语料回答）。

*本机没有全量语料时：* **canon** 工作流（Actions → canon → Run workflow）用 KV 里现有的语料重排要籍、重新打包浏览器的要籍语料；
它不改变全量语料本身。

### 3.5 检查全量语料

```bash
curl -s https://chat.impf.ai/api/info | python3 -c 'import json,sys; i=json.load(sys.stdin); c=i.get("corpus",{}); print(i.get("runtime"), c.get("label"), c.get("books"), "backup" if i.get("backup") else "")'
#   容器：      … 全量语料 958
#   D1 备份：   d1 全量语料（备份） 958 backup       （只在没有绑定容器时）
#   两者都没有：返回错误与 "corpus": "none"，页面在浏览器里运行要籍语料
curl -s -X POST -H "Content-Type: application/json" -H "Origin: https://chat.impf.ai" \
  -d '{"name":"classics.search","arguments":{"query":"桂枝汤","k":3}}' https://chat.impf.ai/api/call | head -c 400; echo
```

控制台：**Workers & Pages** 列出 `taochronos-corpus`；**Storage & databases → D1** 列出 `taochronos-d1-0` … `-4`。
在网页里：问「桂枝汤的组成出自哪部书？」，点开一条引文；**设置 → 关于** 链接到全量语料的来源与授权。

容器闲置 15 分钟后休眠（`SLEEP_AFTER`）；之后第一位访客会把它唤醒，通常在对方输入问题的时间里就绪。

---

## 第四部分 其他步骤

### 4.1 默认服务（中转）

**经 GitHub Actions：** 重新运行 **relay**（2.1）。**从自己的电脑**（做完 B1 之后）：

```bash
cd relay && cp wrangler.toml wrangler.deploy.toml && bash ../security/bind-archive.sh wrangler.deploy.toml
npx --yes "$WRANGLER" deploy --config wrangler.deploy.toml && cd ..
python3 relay/collect.py check                              # 经中转做一次极小的模型调用：最后显示 "call": "ok"
```

Worker 的机密（`MINIMAX_API_KEY`、`LOG_EXPORT_TOKEN`……）在部署之间保留。要更改某一个：
`printf %s "$VALUE" | npx --yes "$WRANGLER" secret put NAME --config relay/wrangler.deploy.toml`，并更新 GitHub 里同名的机密。

**MiniMax 密钥来自国际站**（platform.minimax.io，中国大陆以外通常如此）：`relay/wrangler.toml` 须写
`UPSTREAM_BASE = "https://api.minimax.io/v1"`；否则检查会报 `MiniMax refused the key … api.minimax.io`。

**Actions 受阻期间收集记录**（可选：记录安全地留在中转里，最多 50,000 条）：

```bash
export LOG_EXPORT_TOKEN=…                                   # 若已遗失：在 GitHub 与两个 Worker 上换一个新的（secret put）
out=$(python3 relay/collect.py pull --out data/chat-logs) && echo "$out"
LAST=$(printf '%s\n' "$out" | tail -1 | python3 -c 'import json,sys; print(json.load(sys.stdin)["last"])')
# 仓库收下之后，中转才删除它交出的记录：只有推送成功，才执行 ack
git add data/chat-logs && git commit -m "chat-logs: through #$LAST" && git push && python3 relay/collect.py ack --through "$LAST"
```

### 4.2 归档 记录不再进仓库

每小时的 `chat-logs` 工作流把访客同意记录的对话，以及哨兵的事件，提交进本仓库；仓库历史不改写就清不掉。启用归档后，
两个 Worker 把它们存进一个私有的 R2 存储桶。

1. **R2 Object Storage → Create bucket** → `taochronos-archive` → 位置 *Automatic*（或 *Asia-Pacific*）。在它的 **Settings** 里：
   **Public Development URL (r2.dev)** 保持 **Disabled**；不添加 **Custom Domains**。
2. 部署令牌已有 **Workers R2 Storage · Edit**（2.2）。
3. 仓库变量 `ARCHIVE_BUCKET` = `taochronos-archive`（路线 B 也要 `export ARCHIVE_BUCKET=taochronos-archive`）。
4. 部署两个 Worker：重新运行 **relay** 与 **site**，或做 4.1 与 B4。两边的部署日志都应显示
   `the archive: R2 bucket taochronos-archive (private): …`；若是 `::warning::` 或 `::error::`，它会说明为什么没有绑定
   （找不到、没有权限、可能公开），记录照旧进仓库，不会丢失。
5. 下一段经同意的对话结束约半分钟后，存储桶里出现 `chat-logs/年/月/日/编号.json`。随后
   **Actions → chat-logs → ⋯ → Disable workflow**，每月可省约 720 分钟。
6. 读回某一天（`.archive/` 已被 git 忽略，切勿提交）：

   ```bash
   export LOG_EXPORT_TOKEN=…
   python3 relay/collect.py archive --day 2026-10-17           # → .archive/chat-logs/2026/10/17.jsonl
   python3 security/collect.py archive --day 2026-10-17        # → .archive/security-logs/{relay,site}/2026/10/17.jsonl
   ```

7. 保存期限：由发布方决定，并写进网页的说明；建议对话 90 天、事件 30 天：

   ```bash
   npx wrangler@4 r2 bucket lifecycle add taochronos-archive chat-logs-90d chat-logs/ --expire-days 90
   npx wrangler@4 r2 bucket lifecycle add taochronos-archive security-30d security-logs/ --expire-days 30
   ```

停用：删除 `ARCHIVE_BUCKET`，部署两个 Worker，重新启用 `chat-logs`；收集器从各自的游标继续。

### 4.3 边缘规则

1. 机密 `CLOUDFLARE_SECURITY_TOKEN`、`CLOUDFLARE_ANALYTICS_TOKEN`，变量 `CLOUDFLARE_ZONE_ID`（2.3）。
2. **Actions → security → Run workflow**，action 选 `plan`（不写入），再运行一次选 `apply`。
   从自己的电脑：`pip install pyyaml && CLOUDFLARE_SECURITY_TOKEN=… CLOUDFLARE_ACCOUNT_ID=… python3 security/apply.py plan`
   （再 `apply`）。
3. 48 小时后：**impf.ai → Security → Events**，按 `[taochronos]` 筛选，确认没有真实访客被拦下。

这些规则按区域本身的配套编写（免费：5 条自定义规则、1 条 10 秒的速率限制）；Workers 付费配套不改变它们。

### 4.4 付费配套的调整

| 项目 | 位置 | 建议 |
|---|---|---|
| 哨兵 | `relay/wrangler.toml`、`cloud/site/wrangler.toml` 的 `SENTINEL` | `observe` 两周后，若 `shadow` 事件里没有真实访客，两处都改为 `"enforce"` |
| 每个地址的模型费用 | 中转的 `TOKENS_PER_DAY`、`PER_DAY` | 每天 1,000 万 token、600 次调用；同一医院或办公室地址后面的许多人共用，不够就调高 |
| 全体的模型费用 | 中转的 `TOTAL_TOKENS_PER_DAY`、`TOTAL_PER_DAY` | 最坏一天的上限：按 MiniMax 预算设定 |
| 每次回复的长度 | 中转的 `MAX_OUTPUT_TOKENS` | 每次回复 32,768 token（含思考）；在此处截断的回答由网页接着续写（至多两次），记录里截断的回答多了再调高；回复的花费由上面两项每日 token 额度约束 |
| 网站的每日上限 | 网站的 `API_READS_PER_DAY`、`API_CALLS_PER_DAY` | 每个地址每天 6,000 / 3,000 次，有意放宽 |
| 待取走的记录 | 中转的 `LOG_KEEP` | 50,000 条；超出后拒收新记录（并写 `logs full`），已收下的不丢 |
| 容器 | `cloud/corpus/wrangler.toml` 的 `SLEEP_AFTER`、`instance_type`、`LOCATION_HINT` | `15m`、`standard-1`、`apac`（适合新加坡与东亚；第一次建立时即固定） |

在 `main` 上修改（经 Pull Request），再部署（Actions 或路线 B）。

### 4.5 全部次序 核对清单

1. ☐ 读完第一部分；找到 Actions 停止的原因（2.1）
2. ☐ 部署令牌：Containers、D1、R2 权限；四项检查都输出 `200`（2.2）
3. ☐ Actions 恢复运行，*或* 准备好路线 B 的 Linux 机器（B0、B1）
4. ☐ 以 PR #35 部署中转（4.1）；`collect.py check` → `"call": "ok"`
5. ☐ 容器已部署，网站已绑定（A1，或 B2–B4）；`/api/info` → `全量语料 958`
6. ☐ D1 已导入并绑定（A2，或 B5）
7. ☐ 归档存储桶与 `ARCHIVE_BUCKET`；两个 Worker 已部署；`chat-logs` 已停用（4.2）
8. ☐ 边缘规则已写入（4.3）
9. ☐ 两周后：哨兵改为 `enforce`（4.4）

---

## 第五部分 日常运行

### 5.1 全面检查

```bash
curl -sI https://chat.impf.ai/ | grep -iE '^(HTTP|server|strict-transport-security)'      # 200、cloudflare、max-age=…
curl -s -o /dev/null -w '%{http_code}\n' http://chat.impf.ai/                              # 301
curl -s https://chat-api.impf.ai/v1/health                                                 # "ok":true
python3 relay/collect.py check                                                             # "call": "ok"
LOG_EXPORT_TOKEN=… python3 security/collect.py summary                                     # 哨兵此刻看到什么
```

语料部分另见 3.5。

### 5.2 自动运行的工作

| 工作流 | 时间（UTC / 新加坡时间） | 做什么 |
|---|---|---|
| `relay` | 推送到 `main` 且改动了 `relay/` 或 `security/` | 测试、部署、检查中转 |
| `site` | 推送到 `main` 且改动了网站、代码、语料或 `security/` | 部署网站；容器的输入有变时构建容器；绑定并检查 |
| `chat-logs` | 每小时第 17 分钟 | 把记录与事件收进仓库（只限没有归档的 Worker） |
| `d1` | 每天 00:07 UTC / 08:07 SGT | 继续或检查 D1 导入 |
| `security` | 每天 01:41 UTC / 09:41 SGT；推送 `security/blocklist.yaml` 时 | 边缘事件；封禁名单 |
| `pages` | 推送改动了网页客户端 | GitHub Pages 镜像 |
| `ci` | 每次推送与 Pull Request | 测试 |

Worker 内部：归档的定时器；容器的休眠。

### 5.3 费用

Cloudflare 以美元计费：Workers 付费配套每月 5 美元，超出各项所含额度的部分另计。下表是撰写时公布的数字，请在价格页面
确认（[Workers](https://developers.cloudflare.com/workers/platform/pricing/)、[Containers](https://developers.cloudflare.com/containers/pricing/)、
[D1](https://developers.cloudflare.com/d1/platform/pricing/)、[Durable Objects](https://developers.cloudflare.com/durable-objects/platform/pricing/)、
[R2](https://developers.cloudflare.com/r2/pricing/)）。

| 项目 | 每月所含 | 本网站 |
|---|---|---|
| Workers | 1,000 万次请求、3,000 万 CPU 毫秒 | 只有网页与 `/api/*` 经过 Worker |
| Containers | 25 GiB·小时内存、375 vCPU·分钟、200 GB·小时磁盘 | `standard-1` 每运行一小时约 0.036 美元：每天 4 小时约每月 4 美元，从不休眠约每月 30 美元 |
| D1 | 读取 250 亿行、写入 5,000 万行、5 GB | 约 1.5 GB；一次导入约 10 万行 |
| Durable Objects | 100 万次请求，另含时长与存储额度 | 每次调用几次 |
| Workers KV | 1 GB | 语料 143 MB |
| R2 | 10 GB·月、100 万次 A 类、1,000 万次 B 类操作 | 每条记录或事件写一次 |
| **MiniMax** | 您的余额 | 远比其他各项多；由中转的限额约束（4.4） |
| **GitHub Actions** | 私有仓库每月 2,000 分钟（Free）/ 3,000 分钟（Pro） | 见 2.1 |

账单提醒不是上限：仍建议设置（Cloudflare **Notifications → Add → Billing**，视账户是否提供；GitHub **Budgets**），并把
MiniMax 余额维持在愿意花费的数目。

### 5.4 日常维护

| 要做的事 | 怎么做 |
|---|---|
| 更换 MiniMax 密钥 | 新密钥 → 机密 `MINIMAX_API_KEY` → 部署中转（Actions，或 4.1 的 `secret put`）→ 删除旧密钥 |
| 更换部署令牌 | 新令牌（2.2）→ 机密 `CLOUDFLARE_API_TOKEN` → 删除旧令牌 |
| 更换收集器令牌 | 新值 → 机密 `LOG_EXPORT_TOKEN` → 在两个 Worker 上 `secret put`（或经 Actions 部署两者） |
| 更新语料 | 3.4，然后 A1+A2 或 B2–B5 |
| 调整限额或模式 | 经 Pull Request 修改该 Worker 的 `wrangler.toml` 的 `[vars]` |
| 停止记录对话 | `relay/wrangler.toml` 里 `LOGS = "off"` |
| 暂停默认服务 | 控制台 → `taochronos-relay` → **Settings → Variables and Secrets** → 删除 `MINIMAX_API_KEY` |
| 立即封锁一个地址 | **Manage Account → Configurations → Lists → `taochronos_block`**，之后补进 `security/blocklist.yaml` |

### 5.5 回滚

- **某个 Worker：** 控制台 → **Workers & Pages** → 该 Worker → **Deployments** → 较早的版本 → **Rollback**；或在 `main` 上
  撤销那个提交再部署。PR #35 没有新增 Durable Object 迁移，所以回滚到它之前是安全的。
- **容器：** 从较早的提交部署（在那个提交上做 A1，或在它的检出上做 B3）。
- **D1 备份：** 不必回滚；没有它的 `deployed/d1` 记录，网站就不用它。
- **退回 GitHub Pages**（最后手段）：从网站 Worker 的 **Domains & Routes** 移除 `chat.impf.ai`；CNAME `chat` →
  `psknlr.github.io`，**DNS only**；在仓库 **Settings → Pages** 填回自定义域名。

### 5.6 疑难排解

| 现象 | 原因 | 处理 |
|---|---|---|
| 每次运行都在几秒内失败，没有日志 | GitHub Actions 不启动任务 | 2.1 |
| `the account may not deploy containers yet` | 缺 Containers · Edit，或不是付费配套 | 2.2 |
| `the API token may not use D1 (HTTP 401)` | 缺 D1 · Edit | 2.2 |
| `the store … is not (all) in the KV namespace` / B2 出现 `curl: (22) … 404` | 语料未上载（或新的 `store.json` 尚未上载） | 3.4 |
| `container was not deployed` | 构建或部署失败（错误在上方） | 修正后勾选 **rebuild** 做 A1，或做 B3 |
| B3：`Cannot connect to the Docker daemon` | Docker 没有运行 | 启动 Docker（`sudo systemctl start docker`，或打开 Docker Desktop） |
| B3：在 Mac 上构建极慢 | 在模拟下构建 amd64 映像 | 改用 Linux x86-64（B0） |
| B4：`sed: … extra characters` 或 `invalid command code` | macOS 的 sed | 在 Linux 或 WSL2 上运行（B0） |
| B4/4.1：`Authentication error [code: 10000]` | 令牌或 Account ID 不对 | 2.2 的检查 |
| `No access to the specified resource`（含 `workers/routes`） | 令牌的 Zone Resources 没有 `impf.ai` | 修改令牌 |
| `externally managed DNS records` | `chat` 有一条账户自建的 DNS 记录 | 在 **impf.ai → DNS** 删除那一条，再部署 |
| d1 停在 `the day's budget` | 达到了 budget（默认 1,000,000；设了 `D1_BUDGET` 则较少） | 以 `1000000` 再运行，或删除 `D1_BUDGET` |
| d1 停在 `the run's time is up` | 用完了五小时 | 再运行，会从断点继续 |
| `/api/info` 返回 503、`corpus: none` | 没有容器，也没有绑定 D1 | A1/A2 或 B3–B5 |
| 访客看到「该地址因异常访问已被暂时限制」 | 哨兵拒绝了这个地址（403） | 查看它的事件；若是误判，调短 `BLOCK_SECONDS` 或把 `SENTINEL` 改回 `observe` |
| 访客看到「今天的查询次数已用完」 | 该地址达到每日上限（429） | 若是真实访客，调高 `API_READS_PER_DAY` / `API_CALLS_PER_DAY` |
| 中转检查：`MiniMax refused the key … api.minimax.io` | 国际站密钥配了中国大陆的地址（或相反） | `UPSTREAM_BASE`（4.1） |
| Workers Logs：`logs full` | 记录很久没有被取走 | 恢复 Actions（2.1）、按 4.1 手动收集，或启用归档（4.2） |
| `the archive's bucket … may be public` | 开了 r2.dev、绑了自定义域名，或令牌读不到这两项 | 4.2 第 1 步、R2 权限 |
| `chat-logs`：`the records could not be pushed` | `main` 受保护，Actions 不能推送 | 允许 Actions 推送，或启用归档 |
| `chat-logs`：export 返回 `HTTP 401` | GitHub 与 Worker 的 `LOG_EXPORT_TOKEN` 不一致 | 两边设为同一个值 |

### 5.7 参考

| 路径 | 内容 |
|---|---|
| `relay/wrangler.toml`、`relay/src/` | 默认服务 |
| `cloud/site/wrangler.toml`、`cloud/site/src/`、`cloud/site/deploy.sh` | 网站及其部署 |
| `cloud/corpus/wrangler.toml`、`cloud/corpus/Dockerfile` | 全量语料的容器 |
| `cloud/store.json`、`cloud/ATTRIBUTION.md` | 所部署的语料、其来源与授权 |
| `src/taochronos/chat/d1.py`、`cloud/site/src/backup/` | D1 备份：导入程序与 Worker 端 |
| `security/sentinel.js`、`security/archive.js`、`security/bind-archive.sh` | 哨兵、归档、存储桶检查 |
| `security/rules.yaml`、`security/blocklist.yaml`、`security/apply.py` | 边缘防护 |
| `relay/collect.py`、`security/collect.py` | 收集器（pull、ack、archive、summary、check） |
| `.github/workflows/` | `relay`、`site`、`d1`、`chat-logs`、`security`、`pages`、`canon`、`ci` |
