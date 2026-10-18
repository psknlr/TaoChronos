# 安全防护（security/）

chat.impf.ai（网站）与 chat-api.impf.ai（道乃久默认服务的中转）的防护分三层，数据都回到这个私有仓库：

```
请求 ──▶ ① Cloudflare 边缘：WAF 自定义规则、速率限制、区域与机器人设置        （rules.yaml → apply.py → Cloudflare）
            扫描器路径、伪装的爬虫、抓取库、非网页来源的中转调用在这里被拒，不进 Worker、不计入 Worker 的每日次数
       ──▶ ② Worker 里的哨兵（sentinel.js，两个 Worker 共用）：
            每个请求的指纹与分数；扫描器路径的地址拒绝一天；可疑请求连同地址整条记下；enforce 模式下超分的地址拒绝六小时；
            中转还把回答的 token 用量计入访客当天的额度
       ──▶ ③ 仓库：chat-logs 工作流每小时取回哨兵的事件（collect.py → data/security-logs/relay、site），
            security 工作流每天取回边缘自己的安全事件与值得一看的请求（events.py → data/security-logs/edge，并汇总 suspects.json）
```

设计与取舍见 [ADR 0018](../docs/adr/0018-sentinel-and-edge-rules.md)。本文说明每一层做什么、怎样启用、平时怎么看、出事怎么办。

## 一、哨兵（Worker 内）

两个 Worker——`relay/`（中转）与 `cloud/site/`（网站）——都引入 `security/sentinel.js`；它只依赖 Worker 的标准 API，在 Node 下跑测试
（`node --test security/test/sentinel.test.js`）。

### 指纹：每个请求记下什么

| 来源 | 字段 | 用处 |
|---|---|---|
| Cloudflare 给每个请求的属性（免费计划都有） | `ip`、`asn`/`asOrg`（网络）、`country`/`region`/`city`、`colo`（节点）、`proto`（HTTP/1.1、2、3）、`tls`/`cipher`、`hello`（ClientHello 长度）、`ext`/`ciphers`（扩展与密码套件列表的摘要，类似 JA3）、`rtt`/`qrtt`、`enc`（客户端自己的 Accept-Encoding——Cloudflare 会改写请求头，所以从属性里读）、`vbc`（已验证爬虫的类别，若有） | 托管网络、旧协议与旧 TLS、同一 TLS 栈换 IP 的识别 |
| 浏览器发 fetch 时一定带的请求头 | `ua`、`accept`、`lang`、`origin`、`referer`（只留来源，不留路径）、`sfSite`/`sfMode`/`sfDest`/`sfUser`（Sec-Fetch-*）、`chUa`/`chMobile`/`chPlatform`（Sec-CH-UA，仅 Chromium 系）、`xrw`（X-Requested-With：安卓应用内浏览器的包名）、`ctype`/`clen`、`ray` | 脚本不发这些；声称是浏览器却不带它们就是伪装 |
| 派生 | `uaClass`（browser / tool / scanner / bot / empty / other）、`traversal`（路径里的 `..`、`%00`） | |
| 中转的模型调用请求体（`bodyShape`） | 消息数、字数、是否以系统提示开头、系统提示与最后一问的 **哈希**（不存正文）、是否流式、`stream_options`、工具数、`max_tokens` 字段名 | 网页自己的请求有固定的形状：系统提示在前、带工具、流式带用量、`max_completion_tokens` |

地址：访客按哈希键计（`SENTINEL_SALT` 设定时跨月不变，否则按月）；IPv6 按 /64 计（隐私扩展每小时换一次接口标识，否则按完整地址计数等于没有限额——中转的每日限额也改为按 /64）。

### 分数与理由

单个请求（`assess`）：

| 理由 | 分 | 含义 |
|---|---|---|
| `honeypot` | 10 | 扫描器路径（见下） |
| `traversal` | 6 | 路径穿越 |
| `no_cf_ip` | 3 | 没有 `CF-Connecting-IP`：不是经边缘进来的请求 |
| `ua_scanner` / `ua_tool` / `no_ua` / `ua_other` | 6 / 3 / 3 / 1 | 扫描器、HTTP 库、没有 UA、叫不出名字的 UA（仓库自己的客户端 `taochronos-*` 不计） |
| `ua_bot_unverified` | 2 | 自称 Googlebot、ChatGPT-User、PerplexityBot…… 而 Cloudflare 没有验证 |
| `no_sec_fetch` / `no_lang` / `no_ch_ua` / `old_proto` / `enc_odd` | 2 / 1 / 1 / 1 / 1 | 自称现代浏览器却没有 Sec-Fetch-*、Accept-Language、Sec-CH-UA（只对 Chromium ≥ 90 要求）、用 HTTP/1.x、不接受压缩 |
| `ch_ua_odd` | 2 | 不是 Chromium 浏览器却带 Sec-CH-UA |
| `sec_fetch_mode` / `sec_fetch_dest` | 2 / 1 | API 请求的 Sec-Fetch 不是 fetch 的样子 |
| `tls_old` | 3 | TLS 1.0/1.1 |
| `dc_asn` | 2 | 托管/云网络（`DATACENTER` 表；VPN 用户也会命中，所以只是两分，不是结论）；`warp`（Cloudflare WARP，ASN 13335）只记不计分 |
| `origin_foreign` / `origin_missing` / `referer_foreign` | 3 / 2 / 2 | 不是网页的来源 |
| `method_odd` | 2 | GET/POST/OPTIONS/HEAD/PUT 之外的方法 |
| 中转：`no_system` / `unknown_prompt` / `no_tools` / `no_stream` / `no_stream_options` / `max_tokens_key` / `many_messages` / `huge_prompt` / `accept_odd` | 2 / 3 / 1 / 1 / 1 / 1 / 1 / 1 / 1 | 请求体不是网页发的形状（`unknown_prompt` 只在设定了 `KNOWN_PROMPTS` 时计） |

访客的近况（`WatchCore`，十分钟窗口，在 Durable Object 里）：`burst`（10 秒内 ≥ 20 次，+2）、`replay`（同一问题十分钟内 ≥ 3 次，+2）、
`errors`（十分钟内 ≥ 10 / ≥ 30 次 4xx——不算我们自己的 429 与 5xx，+2 / +4）、`probing`（十分钟内 ≥ 4 / ≥ 8 个不同的 404 路径，+2 / +4）、
`ua_rotation`（一个地址 ≥ 5 / ≥ 10 个不同 UA，+1 / +2——运营商 NAT 后面本来就有很多人，所以分很轻）。

写入是节制的（免费计划按整个账户计每天写入的行数）：一个访客的行在首次出现、新的阻断、换日或距上次写入一分钟时才写——被标记、被拒绝的访客也一样，
其间的计数、分数与地址留在内存里随下一次写入；事件每个访客十秒最多一条，被拒绝后每分钟一条（扫描器会一直敲门）。普通访客的行里只有 UA 的短哈希
（够数不同的 UA），完整的 UA 只在被标记的事件里。系统提示的哈希也在内存里计，每分钟写一次；只见过一两次的一周后清掉。
网站这边，找不到的路径与非浏览器的页面访问每个地址每分钟只报一次对象（路径随行带上），浏览器的策略报告每次 POST 只问一次对象、并经速率限制。

网页从浏览器发出的请求：**0 分**，只留一个计数。微信、QQ、UC 等应用内浏览器少几个请求头，得一两分，照常服务。

### 模式与阈值（两个 Worker 的 `wrangler.toml` `[vars]`）

| 变量 | 默认 | 含义 |
|---|---|---|
| `SENTINEL` | `observe` | `off` 什么都不记；`observe` 记录与标记、从不拒绝；`enforce` 超过 `BLOCK_SCORE` 的地址拒绝 `BLOCK_SECONDS` |
| `HONEYPOT` | `block` | 扫描器路径的地址拒绝 `HONEYPOT_BLOCK_SECONDS`（默认一天），**observe 模式下也拒绝**——没有人会误把 `/wp-config.php` 当作这两个主机的页面；`observe` 则只记 |
| `FLAG_SCORE` / `BLOCK_SCORE` | 5 / 10 | 从几分起整条记下（含地址）、从几分起拒绝 |
| `BLOCK_SECONDS` / `HONEYPOT_BLOCK_SECONDS` | 21600 / 86400 | 拒绝多久；扫描器路径的一天只给托管网络的地址，家庭/运营商网络的地址（后面可能有很多人）按 `BLOCK_SECONDS` |
| `WATCH_DAYS` / `EVENT_KEEP` | 7 / 20000 | 访客行保留几天；未取走的事件最多留多少条（更早的丢弃） |
| `KNOWN_PROMPTS` | 空 | 网页系统提示**前 1024 字**的 sha256 前缀（逗号分隔，十六进制；只取开头，因为网页会在后面附上访客自己的附加指令）；设了之后别的系统提示 +3。从 `summary` 的 `prompts`（见过的系统提示哈希与次数）里抄最常见的那一两个 |
| `LOG_SAMPLE` | 0 | 除了值得一看的请求，再把 1/N 的普通请求写进 Workers Logs |
| `OWN_UA_PREFIX` | `taochronos-` | 仓库自己的客户端（收集器、部署检查）：在事件里标出来，**不豁免**——UA 谁都能填；它们的调用分数本来就在阻断线之下（测试里钉住） |
| Secret `SENTINEL_SALT`（可选） | — | 任意长随机串（如 `openssl rand -hex 32`）：访客的哈希键跨月不变。两个 Worker 用同一个（relay 工作流与 `cloud/site/deploy.sh` 都从仓库 Secret 写入） |
| 中转：`TOKENS_PER_DAY` / `TOTAL_TOKENS_PER_DAY` | 10,000,000 / 200,000,000 | 回答的 token（输入 + 输出，按模型服务报的用量）每人每天、全体每天的额度，用完拒绝下一次调用（0 不限）。记录里见过的量：一轮 p50 8 万、p90 50 万、最多 150 万；一次对话最多 360 万 |
| 中转：`[[ratelimits]] BURST` | 10 秒 40 次 | 每个地址每个节点的突发闸门，在问计数对象之前（近似、按节点；精确的按日计数仍在对象里）；`/v1/security/csp` 的报告也经它 |
| 中转：记录的来源 | — | 默认服务自己的对话记录（`provider: impf`）只收自中转在前 26 小时内答过的地址（按哨兵的键，不随日期变；跨午夜发来的记录照收）；访客用自己 Key 的对话记录只看来源 |
| 网站：`API_READS_PER_DAY` / `API_CALLS_PER_DAY` | 6000 / 3000 | 每个地址（IPv6 按 /64）每天的读取（原文、目录、轮询）与调用（工具、研究）上限：抓取者一天拿不走多少，也烧不完账户的 Worker 次数。宽，因为运营商 NAT 后面是很多人（0 不限） |

拒绝时访客看到「该地址因异常访问已被暂时限制，请稍后再试」（403，带 `Retry-After`），不说理由。

### 扫描器路径（蜜罐）

`isHoneypot()`：`/wp-*`、`/wordpress`、`/xmlrpc.php`、`/.git`、`/.svn`、`/.env`、`/.aws`、`/.ssh`、`/.DS_Store`、`/phpmyadmin`、`/adminer`、`/cgi-bin/`、
`/vendor/phpunit`、`/actuator`、`/boaform`、`/HNAP1`、`/eval-stdin`、`/phpinfo`、`/server-status`、`/owa/`、`/autodiscover`…… 以及后缀
`.php .php7 .phtml .asp .aspx .jsp .jspx .cgi .bak .sql .old .orig .swp .save .rar .7z .env .ini .log .pem .key`（完整表在 `sentinel.js` 的
`HONEYPOT_PREFIXES` / `HONEYPOT_SUFFIXES`）。
**列表是保守的**：网站提供的任何文件类型（`.js .json .wasm .whl .zip .xz .svg .css .html .txt .xml .webmanifest`）和 `/.well-known/` 下的路径都不在内。
命中：网站不去查静态文件、直接 404；地址被记下并拒绝（网站拒绝的是它的 API，网页本身照常）。

### 隐私规则

- 分数低于 `FLAG_SCORE` 的请求**不存地址**：访客行里只有哈希键、按日按接口类别的计数、UA 的短哈希（够数不同的 UA）、网络（ASN/国家）与
  它请求过的 404 路径。网页自己的请求都是这样。
- 达到 `FLAG_SCORE`、被拒绝或本应拒绝（`shadow`）的请求，整条记为事件：指纹（含地址与请求头）、分数与理由、当时的决定、该访客的累计。
  事件由收集器取走进仓库后在 Worker 里删除。
- 对话记录（`data/chat-logs/`）与安全事件是两套存储：记录里没有地址，事件里没有对话（中转的事件只有系统提示与问题的哈希）。
- `data/security-logs/` 有被标记请求的地址与请求头：**仓库须保持私有**。

### 接口与收集

| 接口（中转 `/v1/security/…`，网站 `/api/security/…`） | 作用 |
|---|---|
| `GET export?after=&limit=`、`POST ack {through}` | 收集器取走事件、确认已提交后删除（Bearer `LOG_EXPORT_TOKEN`，与对话记录同一个令牌；网站的由 `deploy.sh` 写入） |
| `GET summary` | 当前概览：按分数排列的访客（有地址的是被标记过的）、正在被拒绝的地址、未取走的事件数、见过的系统提示哈希（Bearer 令牌） |
| `POST csp` | 浏览器上报的内容安全策略违规（不需令牌；每个地址十分钟内最多 20 条；浏览器扩展造成的不记） |
| `GET archive?day=YYYY-MM-DD` | 绑定了归档存储桶时（仓库变量 `ARCHIVE_BUCKET`）：读回某天存进桶里的事件（Bearer 令牌）。此时 `export` 带 `"archive": "r2"`，`ack` 答 409——事件由 Worker 自己存进桶（`archive.js`），收集器不再取 |

`.github/workflows/chat-logs.yml` 每小时在取对话记录之后运行 `python3 security/collect.py pull --relay … --site … --out data/security-logs`，
推送成功后 `ack`；绑定了归档存储桶的 Worker 跳过（`relay/SETUP.md`「归档」，[ADR 0023](../docs/adr/0023-workers-paid.md)）。本机看概览：`LOG_EXPORT_TOKEN=… python3 security/collect.py summary`（`--site ""` 只看中转，`--relay ""` 只看网站）。

Workers Logs（两个 Worker 都开了 observability）：分数 ≥ 1、状态 ≥ 400、被拒绝或 shadow 的请求各写一行结构化日志（字段：`tag`、`route`、`status`、`score`、`reasons`、
`who`、`ip`（仅被标记时）、`ua`、`asn`、`cc`、`colo`、`path`、`proto`、`tls`、`ray`），在 Cloudflare 控制台 Workers → 该 Worker → Logs 里按字段筛选。免费计划保留 3 天。

### 网页的安全头与内容安全策略（网站 Worker）

页面（`/`、`/about`、`/attribution`）带：HSTS、`nosniff`、`Referrer-Policy`、`X-Frame-Options: SAMEORIGIN`、`Permissions-Policy`（关掉页面用不到的设备能力；剪贴板保留）、
`Cross-Origin-Opener-Policy: same-origin`、`Cross-Origin-Resource-Policy: same-origin`，以及 **只报告、不执行** 的 `Content-Security-Policy-Report-Only`
（`cloud/site/wrangler.toml` 的 `CSP_REPORT_ONLY`；报告发到 `/api/security/csp`，随哨兵事件取回）。策略按页面实际加载的东西写成：自己的文件；两段内联脚本与两段内联样式按
**哈希**放行（`cloud/test/site.test.js` 核对哈希与 `web/` 一致：改了内联脚本就要更新策略）；jsDelivr 上的 Anthropic SDK；Cloudflare Web Analytics 的统计脚本
（`static.cloudflareinsights.com`：由边缘插入每个页面，仓库里没有；关掉 Web Analytics 后可从策略里删去）；访客填的任何 https 模型服务与本机服务
（`https:`、`http://localhost:*`）；附图的 `data:`/`blob:`。浏览器内运行环境的两个 Worker 脚本有自己的策略（`cloud/site/_headers`：WebAssembly 需要 `'wasm-unsafe-eval'`）。
报告只留目录、被拦的来源与出处（不留查询串与页面文字），同一访客的同一违规十分钟内只记一次。看报告先按浏览器内核分组：Chromium < 97、Firefox < 102、
Safari < 16 不认识 `'wasm-unsafe-eval'`，旧内核（部分应用内 WebView）会为此报 script-src——那不是策略的错。
两周内没有现代浏览器的真实访客的报告（`data/security-logs/site/` 里 `kind: csp` 的事件），就可以把 `CSP_REPORT_ONLY` 的值改成 `Content-Security-Policy` 执行
（在 `site.js` 的 `secure()` 里换头名）；两个 Worker 脚本的策略要更谨慎——强制后旧内核上的浏览器内运行环境会失效。

## 二、边缘（Cloudflare 免费计划）

### 免费计划能做什么

| 项目 | 免费计划 | 出处 |
|---|---|---|
| WAF 自定义规则 | 5 条；动作 block / managed_challenge / js_challenge / challenge / skip（没有 log）；运算符 `eq contains starts_with ends_with wildcard in {…}`，函数 `lower() len() any()`；**没有正则**（`matches` 要 Business） | [custom-rules#availability](https://developers.cloudflare.com/waf/custom-rules/#availability)、[operators](https://developers.cloudflare.com/ruleset-engine/rules-language/operators/) |
| 可用字段 | `http.host`、`http.request.uri.path`、`http.request.method`、`http.user_agent`、`http.request.headers[…]`、`ip.src`、`ip.src.asnum`、`ip.src.country`、`cf.client.bot`（Cloudflare 验证过的爬虫）、`cf.tls_version`……；**没有** bot score、JA3/JA4、attack score（Enterprise） | [fields](https://developers.cloudflare.com/ruleset-engine/rules-language/fields/reference/) |
| 速率限制规则 | **1 条**；表达式只能看路径；按 IP（加节点）计；窗口与封禁都只能 10 秒 | [rate-limiting-rules#availability](https://developers.cloudflare.com/waf/rate-limiting-rules/#availability) |
| 自定义 IP 列表 | 1 个（账户级，最多 1 万条），规则里 `ip.src in $名字` | [lists#availability](https://developers.cloudflare.com/waf/tools/lists/#availability) |
| 托管规则 | Cloudflare Free Managed Ruleset 默认开（上周拦下的 23 次就是它） | [managed-rules#availability](https://developers.cloudflare.com/waf/managed-rules/#availability) |
| Bot Fight Mode | 有，但**全站生效、不能开例外**（会质询收集器、部署检查，可能质询网页自己的 API 调用）——不开 | [bot-fight-mode](https://developers.cloudflare.com/bots/get-started/bot-fight-mode/) |
| AI 爬虫、托管 robots.txt | 所有计划都能设（`bot_management` 接口） | [block-ai-bots](https://developers.cloudflare.com/bots/additional-configurations/block-ai-bots/) |
| Workers 每日次数 | 10 万次（超出后 run_worker_first 的路径答 429 / 1027）；被 WAF 拦下的请求不计——**所以在边缘拦截才是配额的保护** | [limits](https://developers.cloudflare.com/workers/platform/limits/#daily-requests) |
| 安全事件数据 | GraphQL `firewallEventsAdaptive`、`httpRequestsAdaptiveGroups`，保留约 31 天，一次查询最多 72 小时 | [graphql limits](https://developers.cloudflare.com/analytics/graphql-api/limits/) |

### 规则（`rules.yaml`）

| 序 | ref | 动作 | 拦什么 | 误伤 |
|---|---|---|---|---|
| 1 | `tc-own-clients` | skip（只跳过浏览器完整性检查） | 仓库自己的客户端：`taochronos-collector/1`（收集器）、`taochronos-deploy/1`（`deploy.sh` 的检查） | 冒充这个 UA 只能绕过这一项（突发限制也不免：自己的客户端一小时只发几十个请求），其余规则照常 |
| 2 | `tc-scanner-paths` | block | `wp-`、`/.git`、`/.env`、`.php`、`xmlrpc`、`/../`…… 这两个主机上根本不存在的路径（与哨兵的列表同源） | 无：网站没有这些路径；`/.well-known/` 除外 |
| 3 | `tc-relay-origin` | block | 向中转 `POST /v1/chat/…`、`/v1/logs` 而 `Origin` 不是网页的来源——中转自己也会拒，但在边缘拒绝**不进 Worker、不计次数** | 无：浏览器一定带 Origin；来源表与 `relay/wrangler.toml` 一致，改一处要改另一处 |
| 4 | `tc-tooling-and-spoofed-crawlers` | block | 只为训练模型抓取的爬虫（`training_agents`：GPTBot、ClaudeBot、CCBot、meta-externalagent……，**验证与否都拦**，与站点 robots.txt 的名单一致）；没有 UA；`python*`、`Go-http-client`、`Java/`、扫描器名；以及自称 Googlebot、bingbot、ChatGPT-User、PerplexityBot…… 却**没有通过 Cloudflare 验证**（`not cf.client.bot`）的 | 真正的搜索引擎与 AI 助手（验证通过）放行；`curl`、`wget` 不拦（站长自己会用）；`/.well-known/acme-challenge/` 除外 |
| 5 | `tc-block-list` | block | 列表 `taochronos_block` 里的地址与网段（全站），由 `security/blocklist.yaml` 管理，见下文「封禁名单」。没有列表时这条省略 | 只拦名单上的 |
| 速率 | `tc-api-burst` | block 10 秒 | `/api/*`、`/v1/*`（两个主机共用计数；`/api/security/csp` 除外）每个地址每个节点 10 秒 240 次 | 网页核对引文时几秒内最多取 60 段原文、再做最多 60 次规范化调用，仍在其下 |

对托管/云网络（DigitalOcean、GCP、OVH、Hetzner、Vultr、Linode……）的网页请求出质询的表达式写在第 5 条的注释里，默认不用：这些网络也是
大陆访客常用的 VPN 出口，而质询页在大陆不一定打得开——哨兵只把它当两分的信号。要用先在 Security → Analytics 看这些 ASN 占正常页面访问的比例。

另有区域设置（强制 HTTPS、TLS ≥ 1.2、TLS 1.3、浏览器完整性检查、质询有效期 30 分钟、边缘 HSTS 半年不含子域）与机器人设置
（Bot Fight Mode 关；三类 AI 设置都是 `disabled`：搜索引擎与 AI 助手代用户的抓取放行——网页本来就是可索引的。
训练用的爬虫由第 4 条按名字拦下，**不用** `ai_training: block`：它的托管规则（Block AI training crawlers，BOBA-199）在 2026-10-07 至 10-10
把真正的 Googlebot（66.249.66.43–45）与 Bingbot（40.77.167.4、.46，52.167.144.25）的首页请求也拦了，网站因此进不了谷歌与必应的索引。
`tests/test_security_apply.py` 按 Cloudflare 的规则语言算一遍渲染出的第 4 条：验证过的 Googlebot、Bingbot、百度、头条与 AI 助手放行，
训练爬虫与冒名的拦下，`ai_training` 不是 `block`。
托管 robots.txt **关**：Cloudflare 的名单把百度、花瓣、头条的搜索爬虫也列为训练爬虫并整站禁止，网站会从这些搜索结果里消失；
对训练爬虫的声明由构建写进站点自己的 robots.txt，不点名任何搜索引擎（`tests/test_chat.py` 逐个核对各搜索引擎都能抓页面），
与 `training_agents` 同一份名单（测试核对两处一致）。不想拦训练爬虫就把 `training_agents` 清空）。

**与控制台助手方案的差别**：它提的两条 60 秒窗口、300 秒封禁的速率限制在免费计划上写不进去（只有 1 条、10 秒）；12 个固定 IP 的拦截名单一周就过时
（扫描器换网段），其中 160.79.106.129 还是 Anthropic 公布的 ClaudeBot 网段——真爬虫该由验证字段与 AI 爬虫设置处理，固定名单改用随时可改的列表；
任何依赖 bot score、威胁分数、正则的规则在免费计划上无效。

### 启用

1. **建一个专用令牌**（不要扩大部署令牌）：Cloudflare 头像 → My Profile → API Tokens → Create Token → Custom token，权限：
   Zone · Zone WAF · Edit；Zone · Zone Settings · Edit；Zone · Bot Management · Edit；Zone · Zone · Read；Account · Account Filter Lists · Edit。
   Zone Resources 选 `impf.ai`。存为仓库 Secret `CLOUDFLARE_SECURITY_TOKEN`（Settings → Secrets and variables → Actions →
   **Secrets** 选项卡 → New repository secret；不是 Variables，也不是某个 Environment 的 Secret，名称一字不差）。
2. **再建一个只读令牌**：Zone · Analytics · Read（`impf.ai`）。同样存为仓库 Secret `CLOUDFLARE_ANALYTICS_TOKEN`。
3. 仓库 Variables 里新建 `CLOUDFLARE_ZONE_ID`（Cloudflare → impf.ai → Overview 右侧 API 区的 Zone ID）。
4. **Actions → security → Run workflow**，action 选 `plan`：只读，列出会改什么。再运行一次选 `apply`。
   手动运行时缺了哪个令牌或变量，对应的任务会失败并写出名称；每天的定时运行只提示、不失败。
   本机：`CLOUDFLARE_SECURITY_TOKEN=… CLOUDFLARE_ACCOUNT_ID=… python3 security/apply.py plan`（需要 `pip install pyyaml`）。
5. 验证：手动运行一次 chat-logs 工作流（收集器要能过）、site 工作流（部署检查要能过）；48 小时后看 Cloudflare → impf.ai → Security → Events，
   按描述里的 `[taochronos] n` 筛选，确认没有真实访客被拦。
6. security 工作流每天 01:41 UTC 把前一天的边缘事件取回 `data/security-logs/edge/`，并更新 `suspects.json`；
   没跑成的日子（Actions 分钟数用完、令牌未设）由下一次运行补上：从已存的最后一天的次日取到昨天，最多回看 31 天（`CATCH_UP_DAYS`，约为计划保留的时长）。查询按区域自己报的限额来写
   （字段名、能回看多久、单次窗口多宽、一次能要多少字段）；运行日志末行的 `limits` 就是这些限额，前一天有够不着的时段会以 notice 写明。

### 封禁名单

`security/blocklist.yaml` 是列表 `taochronos_block` 的内容：每条写明地址或网段（`ip`）、看到了什么（`why`）、何时（`seen`）。封禁是
**永久**的；只想封一段时间的写上到期日（`until`），过期的条目下次写入时自动移出。扫描器的地址多是租来的，日后若有真实访客因此
打不开网站，删掉那一行即解封。改动合并进 main 后，security 工作流自动执行 `apply --only list`，只同步名单，不动规则与设置；
`plan` 也会列出名单的增减。

- **收什么**：表现出攻击意图的地址——找漏洞与密钥的路径（`.git`、`.env`、`wp-`、模型网关的配置……）、冒充爬虫、成批的探测。
  只是请求头不像浏览器、只抓了首页、来自机房网络，都**不够**：大陆访客常走机房 VPN；微信/QQ 的链接预览与安全检测（腾讯云地址、
  iPhone UA、会执行页面脚本）、360 浏览器的网址检测（`180.163.*`）也长这样，封掉它们网站会在微信里打不开、在 360 里报风险。
- **永不封禁**（`never`）：Cloudflare 自己的网段、Googlebot、360 的爬虫与检测、Anthropic 的出口（本项目在 Claude Code 里的检查与测试）。
  名单里任何一条与之重叠，整份名单都不写入、运行失败，直到改正；`tests/test_security_apply.py` 在 CI 里先查一遍。
- **控制台里手动加的地址**（应急，立即生效）不带 `[taochronos]` 标记，写入名单时保留；事后照样补进 `blocklist.yaml`。
- 候选从 `data/security-logs/edge/suspects.json`（边缘）与 `data/security-logs/{site,relay}/` 里哨兵标记的事件（`fp.ip`、`reasons`、`state.paths`）来。

### 应急

- **某个地址在捣乱**：Cloudflare → Manage Account → Configurations → Lists → `taochronos_block` 加上地址或网段，立即生效，不用动规则
  （再补进 `security/blocklist.yaml`）；或在 enforce 模式下让哨兵自己处理。
- **正在被打**：Cloudflare → impf.ai → Security → Settings → Under Attack Mode（会让 API 调用失败，只在网页被打时开）；`rules.yaml` 的速率限制调低后 `apply`。
- **误伤了真实访客**：在 Security → Events 找到规则与原因；临时把该规则的 `enabled` 改为 `false` 后 `apply`，再按路径或来源修改表达式。
  不要以 UA 开例外——UA 谁都能填（第 1 条只免除浏览器完整性检查，正因为此）。

## 三、数据与日常

```
data/security-logs/
  cursor.json             两个 Worker 已取回的事件编号
  relay/年/月/日.jsonl    中转哨兵的事件（字段见 data/security-logs/README.md）
  site/年/月/日.jsonl     网站哨兵的事件（含 csp 报告）
  edge/年/月/日.jsonl     边缘：Cloudflare 的安全事件（kind: firewall）与值得一看的请求组（kind: requests：错误、安全动作、扫描器路径、非浏览器 UA、一天 ≥ 300 次）
  edge/suspects.json      近 30 天按地址汇总：事件数、拦截数、请求数、扫描器路径数、网络、UA、路径与分数
```

- **每周看一眼**：`python3 security/events.py suspects`（按分数排）；`LOG_EXPORT_TOKEN=… python3 security/collect.py summary`（哨兵现在看到什么）。
- **从 observe 到 enforce**：看两周的 `shadow` 事件（本应拒绝的）。如果没有一条是真实访客（真实访客的特征：浏览器 UA、Sec-Fetch 齐全、中文或英文的 Accept-Language、
  运营商网络、网页形状的请求体），把两个 `wrangler.toml` 的 `SENTINEL` 改为 `"enforce"` 合入 main。如果有：提高 `BLOCK_SCORE`，或把误判的理由在 `assess()` 里调轻。
- **设 `KNOWN_PROMPTS`**：`summary` 的 `prompts` 里次数最多的哈希就是网页自己的系统提示（网页版本更新时会换），抄前 16 位填进中转的 `KNOWN_PROMPTS`。
- **阈值的依据**：`TOKENS_PER_DAY`、速率限制、`BLOCK_SCORE` 的默认值都标注了记录里见到的基线；基线变了（比如语料变大、一轮的 token 翻倍）就按比例调。

## 四、已知局限

- 区域的免费计划只有一条 10 秒的速率限制，只能平滑突发：真正的保护是第 2–4 条拦截规则、网站的每日读取上限与哨兵（被拦的请求不进 Worker）。
  账户已是 **Workers Paid**（[ADR 0023](../docs/adr/0023-workers-paid.md)）：Worker、Durable Object、D1、KV 都没有每日上限，超出每月所含额度后按量计费——
  所以匀速刷接口的客户端不会再让网站当天停摆，而是**花钱**；每日上限（网站的读取与调用、中转的调用与 token）与哨兵因此仍是费用的防线。
  （免费套餐的额度是整个账户的、每天 UTC 零点重置：Worker 请求 10 万次、Durable Object 请求 10 万次、写入 10 万行、D1 读取 500 万行、KV 写入 1000 次。）
  对象不可用时（故障）：网站的读取照常放行（速率限制绑定仍在，页面察觉不到），网站的工具调用与研究、中转的模型调用答 503
  （不放行未经核对、要花钱的调用；[ADR 0023](../docs/adr/0023-workers-paid.md)），记录丢弃。网站拒绝一个地址答 403、当天读取用完答 429
  （都带 `X-TC-Corpus: refused`），网页改用浏览器内的要籍语料并说明原因。
  网页本身经过 Worker（`run_worker_first`）是为了安全头与哨兵的可见性，代价是每次打开页面算一次；要省，可把 `/`、`/about`、`/attribution` 从 `run_worker_first` 去掉，把这些头搬进 `_headers`。
- 运营商 NAT：许多真实访客共用一个 IPv4。按地址计数的限额（中转每人每分钟 30 次、每天 600 次）对他们是共用的；哨兵的 `ua_rotation` 为此只给很轻的分。
- Cloudflare WARP（ASN 13335）与各种 VPN 出口让真实访客看起来来自托管网络；`dc_asn` 只是两分，规则 5 只质询网页、不碰 API。
- 中转的计数对象（Durable Object）在首次创建的节点上不会迁移；中国访客每次调用多一次跨洋往返（几十到两百毫秒），远小于模型本身的耗时。
  token 额度在调用放行时先按请求大小（约三字节一个 token）预扣，回答末尾的用量再结清：三十个并发调用也透支不了多少。
- 内容安全策略尚在只报告阶段；执行前要确认报告为零。
- 哨兵的记忆在 Durable Object 里：十分钟窗口在内存中，对象被回收时丢失（最坏少算一段突发）；行与事件在 SQLite 里。
