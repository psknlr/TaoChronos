# 道乃久 on Cloudflare（chat.impf.ai）

网站与全量语料都在 Cloudflare 上：**https://chat.impf.ai** 由一个 Worker 提供（证书由 Cloudflare 签发，http 一律跳转
https），页面的工具调用由同一域名下的 API 交给**全量语料服务**——一个运行 `taochronos` 的容器，语料是本项目收录的全部古籍中
可随网站发布的 958 部录本（1.22 亿字，204 万段；来源与授权见 [ATTRIBUTION.md](ATTRIBUTION.md)）。页面不再下载浏览器语料和
Pyodide：打开即可提问，引文可在全部古籍中核对。全量语料服务不可用时，页面自动改用浏览器内的要籍语料（与原来一样）。

```
浏览器 ──https──▶ chat.impf.ai：Worker taochronos-site（cloud/site）
                   ├─ 网页文件（taochronos web build：客户端 + 浏览器内运行环境，后者只在全量服务不可用时才下载）
                   ├─ /api/info、/api/catalog、/api/passage、/api/call、/api/research…（白名单，限流）
                   │     └─ 服务绑定 ──▶ Worker taochronos-corpus（cloud/corpus，无公网地址）
                   │                     └─ Durable Object「main」──▶ 容器：python -m taochronos.chat.cloud serve
                   │                          （全量语料 + 索引 + 预热缓存；闲置 15 分钟休眠，来请求时再启动）
                   └─ /api/store/…（带令牌把全量语料分片上传到 Workers KV，供部署时构建镜像）
模型调用照旧：浏览器 ──▶ chat-api.impf.ai（relay/，道乃久默认服务）或访客自己的 API
```

## 各部分

| 部分 | 作用 |
|---|---|
| `site/`（Worker `taochronos-site`） | 以 Workers Static Assets 提供网页：只有网页（`/`、`/attribution`）和 `/api/*` 先经过 Worker（`run_worker_first`；http→https（301）、HSTS、`nosniff`、`Permissions-Policy`、可选的只报告不执行的 CSP），其余文件由 Cloudflare 直接提供（免费、不计次数；安全头见 `site/_headers`）；只放行 `GET /api/info`、`/api/catalog`、`/api/passage`、`/api/research/<job>`、`/api/session/<id>` 与 `POST /api/call`、`/api/research`，只转发路径、查询与请求体（不转发 Cookie、IP 等），每位访客每分钟调用 120 次、读取 600 次（`[[ratelimits]]`，按 Cloudflare 节点计）；`taochronos serve` 的模型代理（`/api/llm`）不开放。**哨兵**（[`security/`](../security/README.md)）看网页、API 与找不到的路径：扫描器路径的地址被拒绝 API 一天，不是网页发出的 API 调用被打分、达到标记线的连同地址记下（`/api/security/*`，由 chat-logs 工作流取回到 `data/security-logs/`）；`SENTINEL = "enforce"` 时超过阻断分数的地址被拒绝 API 六小时。**统计**：浏览器打开的网页按天、国家与省份计数（访客按日去重，不记地址），`GET /api/stats` 供网页「设置 → 统计」读取（需 `STATS_TOKEN`；见 [docs/web.md](../docs/web.md)） |
| `corpus/`（Worker `taochronos-corpus`） | Durable Object 按需启动容器（`standard-1`：1/2 vCPU、4 GiB、8 GB 磁盘），带着它为容器生成的令牌转发请求；`/api/info` 与工具目录按部署版本缓存在 Durable Object 里，容器休眠时也能立刻回答，同时唤醒容器——模型第一次调用工具时它已就绪 |
| `corpus/Dockerfile` | 以仓库根目录为上下文构建：安装 taochronos，放入主目录（profiles、domains、catalog…），解压并校验 `store.json` 指定的全量语料，用本版代码的规范化器建全文索引，预热各工具首次使用时才构建的缓存（句读模型、引书网络、配伍、学派等）。容器每次都从镜像启动，所以这些都在构建时做好 |
| `store.json` | 部署所用的全量语料：sha256、分片（每片 24 MiB，即一个 KV 值）、书数/段数/字数、各来源、排除的来源。`taochronos web store` 生成 |
| `ATTRIBUTION.md` | 全量语料每部录本的来源与授权；只存于仓库，不随网站发布（网站的“语料来源与授权”页是要籍语料的） |

全量语料由 `taochronos web store` 从本地全量库生成：只收 `WEB_SOURCES`（开放授权来源，以及发布方决定随网站发布的笈成转录本），
**绝不收** `NEVER_PACKED`（東亜医学協会、Hugging Face 数据集——条款禁止转载）；段落号与全量库、浏览器语料相同；不带全文索引
（索引在构建镜像时重建，1.24 GB 的库压缩为 143 MB）；不带缓存的判断结果。

## 部署

`.github/workflows/site.yml`：合入 main（网页、代码、语料或 `cloud/` 有改动时）或 **Actions → site → Run workflow**。

1. **test**：两个 Worker 的单元测试（`node --test`）。
2. **site**（测试通过后立即）：构建网站，部署 `taochronos-site`（创建并绑定上传用的 KV 命名空间；全量语料的容器已部署——KV 里记有
   `deployed/corpus`——就绑定 `taochronos-corpus`），然后检查：https 页面可访问、http 跳转、`/api/info`，全量语料已部署时再做一次
   全量检索。部署与检查都在 `site/deploy.sh`。
3. **corpus**（与 site 同时）：本次提交的版本（语料 sha256 + 构建镜像所用文件的 git 树）与已部署的不同时（已部署的版本在容器部署
   成功后记入 KV 命名空间的 `deployed/corpus`；手动 **Run workflow** 时勾选 *rebuild* 可强制重建）：先确认账户能部署容器
   （Workers Paid、令牌有 Containers 权限，否则跳过并给出警告，不白白构建），再从 KV 命名空间 `taochronos-store` 取回
   `store.json` 指定的各分片并逐片校验，构建镜像（约 12 分钟）并部署 `taochronos-corpus`。语料未上传或部署失败时给出警告，
   **不影响网站**。
4. **bind**（部署了新容器之后）：再部署一次网站——第一次部署容器时网站还没有绑定它——并对新容器做一次全量检索检查。

`chat.impf.ai`：Cloudflare 只在没有自建 DNS 记录的名称上建 Worker 的自定义域名，所以切换时先在 Cloudflare 删除原先指向
GitHub Pages 的 `chat` CNAME（[SETUP.md](SETUP.md) 第 3 步）；部署时 Cloudflare 建立记录并签发证书，通常几分钟生效。

需要的仓库 Secrets 与 relay 相同：`CLOUDFLARE_API_TOKEN`、`CLOUDFLARE_ACCOUNT_ID`；`LOG_EXPORT_TOKEN`（relay 已有）由 `deploy.sh` 写入网站 Worker，
供收集器取走哨兵的事件（可选 `SENTINEL_SALT` 同理）。令牌权限、套餐与各步点击位置见 **[SETUP.md](SETUP.md)**。

## 更新全量语料

上传接口平时关闭（`site/wrangler.toml` 的 `STORE_TOKEN_SHA256` 为空）；维护者更新语料时临时登记一个上传令牌：

```bash
t=$(openssl rand -hex 32); printf %s "$t" | sha256sum   # 新令牌及其 sha256（令牌只留在本机）
# GitHub 仓库 → Settings → Secrets and variables → Actions → Variables：新建 STORE_TOKEN_SHA256 = 上面的 sha256，
# 再 Actions → site → Run workflow（网站随即接受该令牌的上传）
taochronos web store                                   # 写 .taochronos/cloud/<sha256>.sqlite.xz，更新 cloud/store.json 与 cloud/ATTRIBUTION.md
TAOCHRONOS_STORE_TOKEN=$t taochronos web upload        # 分片上传到 https://chat.impf.ai/api/store/…（已上传的分片跳过）
# 删除仓库变量 STORE_TOKEN_SHA256，然后：
git add cloud/store.json cloud/ATTRIBUTION.md && git commit … # 合入 main 后工作流构建新镜像，网站的上传接口随之关闭
```

没有有效令牌时上传接口一律拒绝；令牌只以其 sha256 登记，泄露了也只能往 KV 里写分片（部署时逐片按 `store.json` 校验）。

## 费用（Cloudflare 公布的价格）

- Workers Paid：每月 5 美元，含 1000 万次请求、3000 万 CPU 毫秒，以及容器的 25 GiB·小时内存、375 vCPU·分钟、200 GB·小时磁盘。
- 容器只在运行时计费（闲置 15 分钟即休眠，`SLEEP_AFTER`）：`standard-1` 每运行 1 小时约 0.036 美元（内存）＋磁盘与实际 CPU。
  每天运行 4 小时约每月 4 美元；全天不休眠约每月 30 美元。
- Workers KV：存 143 MB（6 个值）在免费额度（1 GB）内。静态文件请求不收费。
- 只用免费版（Workers Free）：0 元。网页文件不经过 Worker、不计次数；打开网页和 `/api` 请求每天 10 万次以内（约 3 万次访问）。

## D1 备份：没有容器时的全量语料

Workers 免费套餐没有容器。此时网站 Worker 自己回答页面的 API：全量语料存在 **Cloudflare D1**（5 个数据库
`taochronos-d1-0…4`，共约 1.5 GB），工具用 JavaScript 重写后在 Worker 里运行（`site/src/backup/`），重活在 SQL 里做——
Worker 每次请求只有 10 毫秒的计算。设计、测量与 74 个工具逐一的归类见
[docs/adr/0017-d1-backup.md](../docs/adr/0017-d1-backup.md)；站长需要做的一步见 [SETUP.md](SETUP.md)「免费套餐下的全量语料」。

```
/api/* ──▶ 有容器（CORPUS 绑定）：交给容器，与上文相同
        ├─ 否则 D1 备份已导入完成（D1_BACKUP 与数据库所存版本一致）：Worker 用 D1 回答
        │     /api/info（标明「全量语料（备份）」）、/api/catalog（只列出能回答的工具）、/api/passage、/api/call；
        │     /api/research 答 501 并说明原因
        └─ 否则 503：页面改用浏览器内的要籍语料
```

| 部分 | 作用 |
|---|---|
| `src/taochronos/chat/d1.py` | 导出与导入：段落按「一部书、一种时间背景」切块（≤ 64 段、4000 字，共 41,869 块，块号按年代排序，时间范围即块号范围），FTS5 全文索引（每字一词，在 SQL 里由块建成），书目与块映射、词表、预计算结果、统计。建表之后每条语句都是一条原子的 INSERT（≤ 90 KB、≤ 100 个参数），进度从数据库本身读出：中断后续跑，不会重复写入 |
| `src/taochronos/chat/d1results.py` | Worker 算不了的 16 个治学工具：在 CI 里由 Python 工具在全量语料上对可列举的条目（常见方剂、药物、术语、每部书、要籍、伤寒金匮条文…，共 11,765 条）预先计算，压缩存入 `results` |
| `src/taochronos/chat/d1tables.py` | 生成 `site/src/backup/tables.js`：规范化字表、时期、术语、度量衡、工具目录与说明（测试核对与代码一致） |
| `site/src/backup/` | API（与 Python 服务器同样的返回形状）与 14 个直接计算的工具：检索（bm25、时间、异体、词义四路的倒数排名融合）、原文、书目、要籍、术语、规范化、评估、校勘、溯源、引文核对、度量衡、安全提示、现代证据 |
| `.github/workflows/d1.yml` | 每天 UTC 0 点后（及 **Run workflow**，及推送到 `main` 改动了 `store.json` 或导入程序时）：从 KV 取回并校验 `store.json` 指定的语料，导入下一段（预先算好的结果以多进程并行计算），直到当天额度（默认 100 万行：付费套餐没有每日上限；免费套餐每天 10 万行，设仓库变量 `D1_BUDGET = 90000`）；先检查令牌有无 D1 权限；导入完成后在 KV 记下版本（`deployed/d1`）并重新部署网站 |
| `site/deploy.sh` | 绑定 `taochronos-d1-*`（`D1_0…`），导入完成后设置 `D1_BACKUP` |

全量语料约写 87,000 行、预计算结果约 12,000 行：付费套餐**一次运行**导入完（免费套餐两天）。换了语料（`store.json`）、规范化器或布局即为新版本：数据库删除重建、
重新导入，期间页面用浏览器语料。

```bash
python -m taochronos.chat.d1 plan .taochronos/cloud/<sha256>.sqlite.xz --manifest cloud/store.json     # 各数据库、各步骤的行数
python -m taochronos.chat.d1 import .taochronos/cloud/<sha256>.sqlite.xz --manifest cloud/store.json \
  --sqlite cloud/.d1 --budget 1000000000                                  # 在本地 SQLite 里完整构建（约 1.4 GB）
python -m taochronos.chat.d1 fixture cloud/.d1-fixture                    # 测试用的小备份（10 部书），含 Python 工具的参考答案
REQUIRE_D1_FIXTURE=1 node --test cloud/test/backup.test.js                # 备份的 API 与工具（与 Python 工具逐项比对、CPU 与查询数）
WRANGLER_DIST=…/wrangler-dist/cli.js python -m taochronos.chat.d1 import <store> --manifest cloud/store.json \
  --bridge "node cloud/test/d1-emulator.mjs --state cloud/.d1/emulator"  # 在本地 D1 模拟器里导入：D1 自己计的写入行数
```

## 本地试运行

```bash
node --test cloud/test/site.test.js cloud/test/corpus.test.js      # 两个 Worker 的逻辑
cd cloud/corpus && npm ci && cd ../..
mkdir -p cloud/.store && cp .taochronos/cloud/<sha256>.sqlite.xz cloud/.store/
taochronos web build -o _site
cp cloud/site/wrangler.toml cloud/site/wrangler.deploy.toml && printf '\n[[services]]\nbinding = "CORPUS"\nservice = "taochronos-corpus"\n' >> cloud/site/wrangler.deploy.toml
npx wrangler@4 dev -c cloud/site/wrangler.deploy.toml -c cloud/corpus/wrangler.toml   # 需要 Docker：本地构建并运行容器
```
