# 安全防护（security/）

chat.impf.ai（网站）与 chat-api.impf.ai（道乃久默认服务的中转）的防护分三层，数据都回到这个私有仓库：

```
请求 ──▶ ① Cloudflare 边缘：WAF 自定义规则、速率限制、区域与机器人设置        （rules.yaml → apply.py → Cloudflare）
            扫描器路径、伪装的爬虫、抓取库、非网页来源与别的区域的 Worker 转发的中转调用在这里被拒，不进 Worker、不计入 Worker 的每日次数
       ──▶ ② Worker 里的哨兵（sentinel.js，两个 Worker 共用）：
            每个请求的指纹与分数；扫描器路径的地址拒绝一天；可疑请求连同地址整条记下；enforce 模式下超分的地址拒绝六小时；
            中转还把回答的 token 用量计入访客当天的额度
       ──▶ ③ 仓库：chat-logs 工作流每小时取回哨兵的事件（collect.py → data/security-logs/relay、site），
            security 工作流每天取回边缘自己的安全事件与值得一看的请求（events.py → data/security-logs/edge，并汇总 suspects.json）
```

设计与取舍见 [ADR 0018](../docs/adr/0018-sentinel-and-edge-rules.md)。本文说明每一层做什么、怎样启用、平时怎么看、出事怎么办。

这个目录还放着两个 Worker 共用的另一件东西：**活动账本**（`ledger.js`、`ledger-d1.js`、`visitor.js`）——把每个请求记成一条不含地址的事件，
用来数访客、访问、提问与模型用量。它与哨兵分开：哨兵决定拒绝谁、留下可疑请求的地址；账本不留地址、不做任何决定。见第四节与
[ADR 0035](../docs/adr/0035-the-activity-ledger.md)。

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
| `honeypot` / `honeypot_opened` | 10 / 3 | 扫描器路径（见下）；后者是浏览器的使用者把它当网页打开的头一个 |
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
| `HONEYPOT` | `block` | 扫描器路径的地址拒绝 `HONEYPOT_BLOCK_SECONDS`（默认一天），**observe 模式下也拒绝**——没有人会自己去要这两个主机的 `/wp-config.php`（被别的网站的页面、被一条链接带过来的不算，见「扫描器路径」）；`observe` 则只记 |
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
| 网站：`API_RESEARCH_PER_DAY` | 100 | 每个地址每天**发起**的研究次数，与调用分开计：全量语料一次只跑一项研究（一两分钟），最多二十项排队（`src/taochronos/chat/jobs.py`），一个地址不该把别人都挡在外面。用完答 429（`research_daily`），网页照常读取与调用 |
| 网站：`API_READS_PER_DAY` / `API_CALLS_PER_DAY` | 6000 / 3000 | 每个地址（IPv6 按 /64）每天的读取（原文、目录、轮询）与调用（工具、研究）上限：抓取者一天拿不走多少，也烧不完账户的 Worker 次数。宽，因为运营商 NAT 后面是很多人（0 不限） |

拒绝时访客看到「该地址因异常访问已被暂时限制，请稍后再试」（403，带 `Retry-After`），不说理由。

### 扫描器路径（蜜罐）

`isHoneypot()`：**任何一层以点开头的文件或目录**（`/.git`、`/.env`、`/api/.env`、`/.aws`、`/.ssh/id_rsa`、`/.kube/config`、`/.npmrc`……；2026-11 起扫描器改找
AI 与云的凭据——`/.openai/credentials.json`、`/.anthropic/config.json`、`/.cache/huggingface/token`、`/.config/gcloud/…`——逐个点名追不上，所以不再点名）；
`/wp-*`、`/wordpress`、`/xmlrpc.php`、`/phpmyadmin`、`/adminer`、`/cgi-bin/`、
`/vendor/phpunit`、`/actuator`、`/boaform`、`/HNAP1`、`/eval-stdin`、`/phpinfo`、`/server-status`、`/owa/`、`/autodiscover`…… 以及后缀
`.php .php7 .phtml .asp .aspx .jsp .jspx .cgi .bak .sql .old .orig .swp .save .rar .7z .env .ini .log .pem .key`（完整表在 `sentinel.js` 的
`HONEYPOT_PREFIXES` / `HONEYPOT_SUFFIXES`）。
**列表是保守的**：网站提供的任何文件类型（`.js .json .wasm .whl .zip .xz .svg .css .html .txt .xml .webmanifest`）和 `/.well-known/` 下的路径都不在内。
命中：网站不去查静态文件、直接 404；地址被记下并拒绝（网站拒绝的是它的 API，网页本身照常）。

拒绝的是**自己来要**这些路径的地址。读者的浏览器被带到这里的，分三种（[ADR 0034](../docs/adr/0034-what-the-site-ships.md)）：

1. **别的网站的页面让浏览器发来的**（一张指向这里的图片、一个表单、一段脚本）：不记、不计、不拒绝，见下一节。
2. **浏览器的使用者把它当网页打开的**（`Sec-Fetch-Site: none`、`navigate`、`document`：地址栏、书签、在聊天软件里点开的链接——
   群里发一条链接就能把群友带过来），而且这个浏览器别的方面都正常：十分钟内的**头一个**只计 3 分（`honeypot_opened`），不拒绝；
   **第二个不同的**扫描器路径照旧拒绝。
3. **只是抄了浏览器请求头的**：照旧第一个就拒绝。2026-11 找 `/.ssh/` 的那批扫描器把 Chrome 导航的请求头抄全了，却走 HTTP/1.1——
   用 HTTP/1.x、没有 `Accept-Language`、UA 是工具、或根本没有 `Sec-Fetch-*` 的，都不算第 2 种。

### 别的网站的页面让读者的浏览器发来的请求

任何网页都能让它的读者的浏览器向这两个主机发请求：三十张指向不存在路径的图片、一张指向扫描器路径的图片、循环读取 API 的脚本。
读者什么都没选，所以**这些请求不算在读者的地址上**——否则在论坛里贴一张图，就能让看帖的人（运营商 NAT 后面是共用这个地址的所有人）
被拒绝几个小时。此前正是如此：三十张图让每个读者得 12 分（`referer_foreign`、`burst`、`errors`、`probing`），过了拒绝线；
指向扫描器路径的一张图就够（2026-11-25 在当时部署的代码上复现）。

- **怎么认**（`ledFrom()`）：浏览器自己说的——`Sec-Fetch-Site` 是 `cross-site` 或 `same-site`（页面的脚本既设不了也去不掉这个头），
  而且发起的页面（`Origin`，没有就看 `Referer`）不是我们自己的（网页与镜像）。太老、不发这个头的浏览器，只看 `Origin`/`Referer`。
  `none` 不是：那是使用者自己打开的（见上一节第 2、3 种）。
- **怎么答**：中转一律 403（`cross_site`），在别的一切之前；网站的 API 403；不存在的路径照旧 404；网站自己的页面照常给——
  顺着链接来看网页本来就是该有的事（只有当作网页打开的才计入访问统计，被别的网站当图片或框架载入的不计）。
- **不记什么**：不写访客行、不写事件、不计入当天的次数、不影响分数。Workers Logs 里有一行（`led`：发起页面的来源；没有地址）。
- **这也是一条访问规则**，哨兵关着（`SENTINEL = "off"`）也一样：读者当天的读取额度不是别的网站可以替他花掉的。
- 不是浏览器的客户端也可以自己加上这些头：那它要的东西就被拒绝了（403），等于什么也没得到；它自己名义的请求照旧计分。

### 隐私规则

- 分数低于 `FLAG_SCORE` 的请求**不存地址**：访客行里只有哈希键、按日按接口类别的计数、UA 的短哈希（够数不同的 UA）、网络（ASN/国家）与
  它请求过的 404 路径。网页自己的请求都是这样。
- 达到 `FLAG_SCORE`、被拒绝或本应拒绝（`shadow`）的请求，整条记为事件：指纹（含地址与请求头）、分数与理由、当时的决定、该访客的累计。
  事件由收集器取走进仓库后在 Worker 里删除。
- 浏览器的策略报告（`csp`）不论谁发来都记为事件，所以**没被标记的访客的报告不带地址**：只留主机、路径、网络（ASN/国家）、协议、
  浏览器的种类与版本、应用内浏览器的包名（`anonymous()`）。2026-11-25 之前不是这样：此前取回的报告里有 2030 条带着未被标记
  访客的地址与完整请求头；2026-11-26 已按同一规则改写（`data/security-logs/` 的两个哨兵目录里，再没有未被标记的访客的地址）。
- 报告谁都能发，所以留下的每个字段都只是浏览器会发的那一种（`sentinel.js` 的 `keptReport`）：短文本、两种 `disposition` 之一
  （`enforce` / `report`）、非负整数的行号与状态码；别的类型一律不留。此前 `disposition`、行号、状态码是来什么留什么（任意类型、
  任意嵌套），收集器取到这样一条就读不下去。凡是请求带来的文本，留下之前都经 `clipped()`：按长度截断时不把一个字截成两半
  （基本平面之外的字占两个 UTF-16 单元，生僻汉字、表情都是），落单的半个字（孤立代理项，JSON 写作 `"\ud800"`）换成 U+FFFD——
  JSON 带得动它，UTF-8 写不出，收集器曾因此在同一条上每次都停下。事件交给收集器时再按同一规则过一遍（此前存下的也一样）。
  git 历史里仍有原样：要从历史中去掉，只能改写仓库历史，由站长决定。
- 研究任务与研究会话的编号是读取它们的唯一凭据，**不进任何一行、事件或日志**：路径记作 `/api/research/…`、`/api/session/…`
  （`keptPath()`；边缘的记录由 `events.py` 的 `kept_path()` 同样处理）。
- 别的网站的页面让浏览器发来的请求不记地址（上文）。
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

事件里的字符串是发请求的人写的，所以四个收集器（`collect.py`、`events.py`、`activity.py`、`relay/collect.py`）都这样对待取回的 JSON：
**进门**时把落单的半个字换成 U+FFFD（否则写不进文件，游标不动，此后每次都停在同一条上——`chat-logs` 工作流里取事件这一步失败，
连同一次取回的对话记录也不提交）；**写**时一条一行，U+0085、U+2028、U+2029 写成 JSON 自己的转义（JSON 允许字符串里原样带着它们，
而 `str.splitlines` 把它们当换行）；**读**时只按换行符分行，不是对象的行跳过。

取回是一页一页的，一页既按条数、也按分量封顶（`sentinel.js` 的 `pageEnd`：存着的 JSON 至多 400 万字符；第一条再重也给）。
Durable Object 的一次调用最多交回 32 MiB，而带着一个 Latin-1 以外字符的字符串在这条路上每个字符占两个字节：一个地址一天
可发的 500 条对话记录（每条 47 KB）凑成的一页交不出来，取回就每次都失败（HTTP 500），连带整个收集。收集器遇到交不出的一页
（5xx）会把页缩小再要。请求头的值在 Workers 里按 UTF-8 读出，所以指纹里的各个请求头也经 `clipped()`——此前一条带着
生僻字的 User-Agent 在长度上限处被截成两半，一个探测路径的 GET 就够留下半个字。

Workers Logs（两个 Worker 都开了 observability）：分数 ≥ 1、状态 ≥ 400、被拒绝或 shadow 的请求各写一行结构化日志（字段：`tag`、`route`、`status`、`score`、`reasons`、
`who`、`ip`（仅被标记时）、`ua`、`asn`、`cc`、`colo`、`path`、`proto`、`tls`、`ray`），在 Cloudflare 控制台 Workers → 该 Worker → Logs 里按字段筛选。免费计划保留 3 天。

### 网页的安全头与内容安全策略（网站 Worker）

页面（`/`、`/about`、`/attribution`）带：HSTS、`nosniff`、`Referrer-Policy`、`X-Frame-Options: SAMEORIGIN`、`Permissions-Policy`（关掉页面用不到的设备能力；剪贴板保留）、
`Cross-Origin-Opener-Policy: same-origin`、`Cross-Origin-Resource-Policy: same-origin`，以及两份内容安全策略（`cloud/site/wrangler.toml`；报告都发到 `/api/security/csp`，随哨兵事件取回）：

- **执行**的 `Content-Security-Policy`（`CSP`，2026-10-28 起）：管住不是页面自己的脚本——`script-src`（内联脚本只放行按哈希列出的两段，不许 eval）、`object-src 'none'`、
  `base-uri 'none'`——以及脚本能把页面数据送出去或显示出去的途径：`connect-src`、`img-src`、`worker-src`、`form-action`、`frame-ancestors`。
- **只报告**的 `Content-Security-Policy-Report-Only`（`CSP_REPORT_ONLY`）：整份策略，另外还管样式、字体、媒体与框架。这几项不执行，因为浏览器扩展与应用内浏览器
  正是在这里加它们自己的东西（深色模式或翻译插件的 `<style>`、图标字体、钉钉等 WebView 桥接用的 `<iframe>`）；拦下它们只会让访客的扩展失灵，保护不了页面。

策略按页面实际加载的东西写成：自己的文件；两段内联脚本与两段内联样式按**哈希**放行（`cloud/test/site.test.js` 核对哈希与 `web/` 一致、两份策略的 `script-src` 相同：
改了内联脚本就要更新两份策略，否则页面启动不了）；jsDelivr 上 npm 包的文件（`https://cdn.jsdelivr.net/npm/`：Anthropic SDK 与它 `+esm` 引入的依赖；不含 `/gh/`，那里能取到任何公开仓库的文件）；
Cloudflare Web Analytics 的统计脚本（`static.cloudflareinsights.com`：由边缘插入每个页面，仓库里没有；关掉 Web Analytics 后可从策略里删去）；访客填的任何 https 模型服务与本机服务
（`https:`、`http://localhost:*`）；附图的 `data:`/`blob:`。内置运行环境的两个 Worker 脚本有自己的策略（`cloud/site/_headers`：WebAssembly 需要 `'wasm-unsafe-eval'`），仍只报告。
报告只留目录、被拦的来源与出处（不留查询串与页面文字），同一访客的同一违规十分钟内只记一次；同一违规的「执行」（`disposition: enforce`，真被拦下了）与「报告」分开记。
看报告先按浏览器内核分组：Chromium < 97、Firefox < 102、Safari < 16 不认识 `'wasm-unsafe-eval'`，旧内核（部分应用内 WebView）会为此报 script-src——那不是策略的错。

**为什么可以执行**（[ADR 0026](../docs/adr/0026-pinned-supply-chain-and-enforced-policies.md)）：2026-10-06 至 10-28 整份策略只报告，收到 144 条报告，落在执行的这几项上的 13 条
没有一条出自页面自己的代码：5 条是浏览器扩展（其中一条是 iPhone 上应用内浏览器的桥接脚本），8 条是 Cloudflare 的统计脚本在少数浏览器里被拦（执行后这些访问不进
Web Analytics，访客看不出差别）。上线前用 Chromium 在本地按部署的配置跑过一遍：打开页面、设置、主题、经默认服务的一轮对话、英文界面、关于页与出处页，没有一条违规；
再往页面里注入一段内联脚本和一张外链图片，二者都被拦下，页面照常可用。**出了问题**：把 `wrangler.toml` 里 `CSP` 的值清空合入 main，就回到只报告（`CSP_REPORT_ONLY` 不变）。
两个 Worker 脚本的策略要更谨慎——强制后旧内核上的内置运行环境会失效。

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
| 2 | `tc-scanner-paths` | block | `wp-`、`.php`、`xmlrpc`、`/../`……，以及**任何一层以点开头的文件或目录**（`/.git`、`/.env`、`/.ssh`、`/.openai/credentials.json`……）：这些主机上根本不存在的路径（与哨兵的列表同源） | 无：网站没有这些路径；`/.well-known/` 除外 |
| 3 | `tc-relay-origin` | block | 向中转 `POST /v1/chat/…`、`/v1/logs`、`/v1/feedback`、`/v1/activity` 而 `Origin` 不是网页的来源——中转自己也会拒，但在边缘拒绝**不进 Worker、不计次数**；以及**别的区域的 Worker 转发**到两个中转（`chat-api.impf.ai`、science.impf.ai 的 Tao-S1）`/v1/*` 的请求（`cf.worker.upstream_zone` 既不为空、也不是 `impf.ai`）：Worker 可以随意填写 Origin，来源检查拦不住它（见下文「封禁名单」里的 2a06:98c0:3600::103）；以及中转上 **`/v1/` 之外的一切路径**（中转只有 `/v1/*` 的接口：UCloud 香港的扫描器轮换地址，每个地址一天几百上千次地在这里找交易所与 App 的后台接口，10 至 11 月约 8500 次） | 无：浏览器一定带 Origin，网页的请求也从不经 Worker 转发；本区域自己的 Worker 放行；仓库自己的客户端（收集器、部署检查）只用 `/v1/*`；证书签发（`/.well-known/acme-challenge/`）与 `/cdn-cgi/` 除外；来源表与 `relay/wrangler.toml` 一致，改一处要改另一处 |
| 4 | `tc-tooling-and-spoofed-crawlers` | block | 只为训练模型抓取的爬虫（`training_agents`：GPTBot、ClaudeBot、CCBot、meta-externalagent……，**验证与否都拦**，与站点 robots.txt 的名单一致）；没有 UA；`python*`、`Go-http-client`、`Java/`、扫描器名、Lightpanda（给自动化与 AI 代理用的无头浏览器，按站长要求）；以及自称 Googlebot、bingbot、ChatGPT-User、PerplexityBot…… 却**没有通过 Cloudflare 验证**（`not cf.client.bot`）的 | 真正的搜索引擎与 AI 助手（验证通过）放行；`curl`、`wget` 不拦（站长自己会用）；HeadlessChrome 不拦（本项目自己的检查就是它）；`/.well-known/acme-challenge/` 除外 |
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
它后来的报告还提过三件事，各有不照做的理由：按 UA 拦 HeadlessChrome（2026-11-12）——那些请求来自 160.79.106.0/24，是本项目在 Claude Code 里的检查
（Playwright 的 Chromium），拦了这些检查也过不去；封 175.24.212.0/24（2026-11-25，Lightpanda 的两个地址所在）——那是腾讯云的网段，微信的链接预览与安全检测
也从腾讯云来，所以只按名字拦 Lightpanda（第 4 条），两个地址进名单并写了到期日；给 `/api/passage` 另加速率限制（2026-11-25）——免费计划只有一条，
已经管着全部 `/api/*`，每个地址每天的读取上限在 Worker 里（`API_READS_PER_DAY`）。

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
- **2a06:98c0:3600::103 不是一个访客**：别的 Cloudflare 区域里的 Worker 发来的子请求，地址一律是它（Cloudflare 为跨区域子请求固定填写；
  同一区域的子请求带访客的真实地址），所以它在报告里会是“一个地址”的大量请求。它在 Cloudflare 的网段里（`never`），封它等于封掉所有
  经 Worker 来的请求，也写不进名单；把中转当免费模型接口转发的 Worker 由第 3 条按 `cf.worker.upstream_zone` 拒绝（只管两个中转的
  `/v1/*`）。2026-10-15 至 10-21 它向 `/v1/chat/completions` 发了 2225 次（站长 10-21 的报告），哨兵在中转上一次也没见过它，所以
  多半是 science.impf.ai 的 Tao-S1。
- **控制台里手动加的地址**（应急，立即生效）不带 `[taochronos]` 标记，写入名单时保留；事后照样补进 `blocklist.yaml`。
- 候选从 `data/security-logs/edge/suspects.json`（边缘）与 `data/security-logs/{site,relay}/` 里哨兵标记的事件（`fp.ip`、`reasons`、`state.paths`）来。
  `suspects.json` 按分数排，分数低的也要看：托管规则拦下的漏洞利用（React、WordPress 的远程代码执行）一个地址只有九、十次请求，
  探测 `/.git/config` 的只有一两次。
- **一个地址只来一两次的代理池不逐个进名单**：2026-11-09，3xK Tech（AS200373）等的七十多个地址各向中转问了一个密钥路径（`/.env.*`、`/.ssh/id_rsa`、
  `/.kube/config`、`/%2f%2eenv`……），每个地址用过即弃，名单追不上也不必追——这类请求由第 2、3 条规则在边缘拒绝。同一网络里持续扫描的单个地址照常进名单。

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
  edge/年/月/日.jsonl     边缘：Cloudflare 的安全事件（kind: firewall）与值得一看的请求组（kind: requests：错误、安全动作、扫描器路径、非浏览器 UA、一天 ≥ 300 次，
                          以及用工具或成批取走运行环境文件的）；运行环境文件每天的下载合计（kind: artifacts，没有地址）；
                          当天全部请求按主机、国家与状态的合计（kind: traffic，没有地址、路径与 UA——Worker 看到的与没看到的都在内）
  edge/suspects.json      近 30 天按地址汇总：事件数、拦截数、请求数、扫描器路径数、取走的运行环境文件数、网络、UA、路径与分数
```

- **谁在下载运行环境的文件**（`/runtime/` 下的五个：程序包、主目录、要籍语料、启动信息、清单——公开的静态文件，不经过 Worker，
  所以只有边缘知道谁取了）：`events.py` 每天按文件、状态（200、206 分段、304 未改……）、方法与 UA 的种类记一条合计（`kind: artifacts`：
  次数、字节数、多少个不同的地址；**不记地址**——这是每个读者自己的下载）。带地址记下的只有两种：取文件的不是浏览器
  （`ua_tool`、`ua_empty`，或 `artifact_agent`：既不是浏览器也不是已知工具的 UA），或一个地址一天取同一个文件 ≥ 30 次（`artifact_volume`，
  `fetched` 是当天的次数）。镜像（GitHub Pages）上的下载哪里都没有记录。更早的日子在计划的保留期内可以补取：
  `python3 security/events.py pull --day 2026-11-20`。
- **请求组按整天计**：接口一次只能问几小时的窗口，同一组（地址、UA、路径、状态、方法）在几个窗口里出现的，合成一行、次数相加，
  「一天 ≥ 300 次」按相加后的数判断（2026-11-25 之前只留第一个窗口的数，也只按它判断）。某天被重新取回（当天没过完就取过，或某个窗口取满了）时，
  每行取较大的那个数，再补上原先没有的。
- **每周看一眼**：`python3 security/events.py suspects`（按分数排）；`LOG_EXPORT_TOKEN=… python3 security/collect.py summary`（哨兵现在看到什么）。
- **从 observe 到 enforce**：看两周的 `shadow` 事件（本应拒绝的）。如果没有一条是真实访客（真实访客的特征：浏览器 UA、Sec-Fetch 齐全、中文或英文的 Accept-Language、
  运营商网络、网页形状的请求体），把两个 `wrangler.toml` 的 `SENTINEL` 改为 `"enforce"` 合入 main。如果有：提高 `BLOCK_SCORE`，或把误判的理由在 `assess()` 里调轻。
  **2026-10-28 已改为 enforce**：此前 22 天（10-06 至 10-28）只有 7 条 `shadow` 事件，全是扫描器——每个地址的请求全部 404（10 到 671 次）、多数来自托管网络、
  没有浏览器的 Sec-Fetch 头（UCLOUD 香港的 4 条、长春的 1 条，以及 Anthropic 出口上两次路径穿越的探测）（[ADR 0026](../docs/adr/0026-pinned-supply-chain-and-enforced-policies.md)）。
  之后若有真实访客被拒（403「该地址因异常访问已被暂时限制」），先看它的事件，再提高 `BLOCK_SCORE` 或改回 `"observe"`。
- **设 `KNOWN_PROMPTS`**：`summary` 的 `prompts` 里次数最多的哈希就是网页自己的系统提示（网页版本更新时会换），抄前 16 位填进中转的 `KNOWN_PROMPTS`。
- **阈值的依据**：`TOKENS_PER_DAY`、速率限制、`BLOCK_SCORE` 的默认值都标注了记录里见到的基线；基线变了（比如语料变大、一轮的 token 翻倍）就按比例调。

## 四、活动账本（与哨兵分开）

哨兵只在请求可疑时才整条记下；按日计数（`usage.js`）只有每天的合计，访客按地址的哈希每天去重、两天后删掉。于是说不出一个月有多少**不同的**访客、
多少人回来过、有多少提问是访客没同意记录的、一个问题花了多少。活动账本补的就是这些（[ADR 0035](../docs/adr/0035-the-activity-ledger.md)）。

```
两个 Worker ──▶ 事件（envelope）──▶ Durable Object 里的发件箱（LedgerCore：网站的 Watch、中转的 Limiter）
                                      ├─▶ D1「登记册」（ledger-d1.js）：访客、每日活跃、访问、事件、提问、模型调用、每日合计 —— 日报与站长读这里
                                      └─▶ R2「归档」（archive.js，绑定了 ARCHIVE 时）：一小时一个 gzip 对象 + 每天一份清单
仓库 ◀── activity 工作流每天取回汇总（activity.py → data/activity-analytics/），只有计数
```

**这些数只给站长看**：网站上没有哪一页显示它们，读它们的接口只认收集令牌（`LOG_EXPORT_TOKEN`）、不带 CORS 头（任何网页——本站的或别人的——都读不到），
令牌不在任何网页里。站长在自己的 GitHub（这个私有仓库的 `data/activity-analytics/`）和 Cloudflare（D1 `taochronos-activity`）里看，见下文「日常」。

**没有密钥就没有账本**：仓库 Secret `ACTIVITY_KEY` 未设时，两个 Worker 与从前完全一样——不发 Cookie、不记事件、没有这些接口。

### 一条事件留下什么

| 类别 | 字段 | 不留什么 |
|---|---|---|
| 事件本身 | `event_id`（按时间可排序，重复写入只算一次）、`timestamp`、`day`（北京时间的日子）、`schema_version`、`source`（site / relay）、`event_type` | |
| 请求 | `host`、`route`（网站自己的路径：`/`、`/api/passage`、`/v1/chat/completions`……别的一律 `other`）、`method`、`status`、`latency_ms`、`n`（这一行代表几次请求） | 不存在的路径、查询串、研究任务的编号 |
| 浏览器 | `browser_family`（Chrome / Safari / WeChat……）、`os_family`、`device_type`（手机 / 平板 / 电脑）、`language` —— 四个词，很多访客共有 | UA 原文、版本号、Client Hints、TLS 握手摘要、往返时延：这些能把一个浏览器和另一个分开，只留在哨兵标记的事件里 |
| 网络 | `country`、`region`（省级）、`asn`、`http_protocol`、`tls_version` | **地址**、城市、网络名称 |
| 哨兵怎么看 | `traffic_class`（human 访客的浏览器 / suspect 被标记的浏览器 / crawler / automation / own / cross_site / unknown）、`risk_score`、`security_action`（none / flagged / shadow / blocked / honeypot / rate_limited / cross_site） | |
| 访客 | `visitor_id`（只给 human；归档里换成当天的别名 `visitor_day`） | 见下 |
| 提问与模型 | `turn_id`（账本自己编的）、`basis`（relay / client / record）、`provider`、`model`、`invocation_id`、`execution_status`、`input_tokens` / `output_tokens`、`asks`、`retry_count`、`rounds`、`tool_count`、`tools`（工具名 → 次数）、`module`、`content_consent`、`archive_status` | 问题、回答、工具的参数、对话编号、网页给这一轮起的编号、访客自设接口的地址与模型名 |

事件的种类：`page_view`（浏览器打开网页）、`page_ready`（网页加载完自己报一声）、`api_read`（同一访客一分钟内同样的读取合成一行，`n` 是次数）、
`api_call`、`research_started`、`question_submitted`、`model_invocation`、`model_settled`（这次调用怎么结束、花了多少）、`model_refused`（被限额或哨兵拒绝，`detail` 是原因）、
`turn_finished`（网页报告这一轮的结局）、`record_archived`、`feedback_submitted`、`sponsor_submitted`、`visitor_choice`、`request`（其余的一切；不是访客的——扫描、爬虫——按分钟合成一行）。
别的网站的页面让浏览器发来的请求只记国家，不记访客，不记网络与浏览器。

### 访客是谁：一个浏览器，而不是一个人

- **Cookie** `__Host-tcv`：网站 Worker 在浏览器打开网页时发，128 位随机数加签名，`HttpOnly`（脚本读不到）、只属于 chat.impf.ai 这一个主机、
  **自签发之日起 13 个月失效，来访不延长**。账本里存的是它的 HMAC（`v_` 开头）：拿到账本的人造不出 Cookie，拿到 Cookie 的人没有密钥也找不到它的记录。
- **通行证**：中转是另一个主机，收不到这个 Cookie。网页加载后向自己的主机要一张当天有效的签名通行证（`POST /api/activity/hello`），调用中转时带上（`X-Tao-Visitor`）。
- **不做指纹**：地址、UA、Canvas 之类能认出没同意被认出的人；Cookie 是访客自己可以删的。
- **不给编号的**：浏览器要求不被跟踪的（`Sec-GPC: 1`、`DNT: 1`）；访客在「设置 → 数据 → 访问统计」里关掉的（Cookie 的值变成 `off`，别的什么都不留）；
  不是浏览器的；别的网站带来的请求。他们的请求照样计数，只是不属于任何访客。
- **带回来过一次才算访客**：发出去再没带回来的编号（爬虫、不存 Cookie 的浏览器）只算一次页面访问，不算访客，否则这样的浏览器每开一页就多一个“访客”。
- **访客自己能做的**（设置 → 数据 → 访问统计）：看到自己的编号、关闭统计、**删除本站关于此编号的全部记录**（`POST /api/activity/forget`：
  登记册里他的行、每日活跃与访问删除，事件与提问改为“无主”，删除记录里不写编号；仍在路上的事件两天内也按无主写入）。
- **一段时间的访客是每天访客的并集，不是相加**：登记册里一位访客一天一行，一周、一月、全部时间的访客数是对这段时间做 `COUNT(DISTINCT)`。

| `ACTIVITY_IDS`（两个 `wrangler.toml` 须一致） | 含义 |
|---|---|
| `notice`（默认） | 浏览器打开网页就发编号，除非它要求不被跟踪或访客关掉了；在「设置 → 数据」与「关于」里说明 |
| `optin` | 访客在「设置 → 数据」里打开之后才发 |
| `off` | 谁都不发：照样计数，没有访客、访问与留存 |

### 一个问题是一轮，不是一次调用

网页给每一轮起一个名字（`X-Tao-Turn`，就是那条回答的消息编号），这一轮的每次模型调用都带着它；中转把这一轮的**第一次**调用算作提问，
此后的工具轮、自查要求重写、在输出上限处接着写、失败后重问，都只是这一轮的调用（`relay/src/gate.js`）。**有没有账本都这样计**——此前按
「以用户消息结尾的调用」算提问，上面几种都被多算了一次，按日计数里的「提问」因此偏多。

- **谁回答的都算**：默认服务的（`basis: relay`，中转亲眼所见，连同每次调用的结局、token、向模型服务请求了几次、多久才开始回复）；
  访客用自己的模型或网页自己回答的（`basis: client`，网页在这一轮结束时向中转报一组计数：`POST /v1/activity`）；只有对话记录为证的（`basis: record`，旧版网页）。
- **未存档 = 全部 − 已存档**：中转收下某一轮的对话记录时，把这一轮标为已存档。
- **账本说不出谁问了什么**：不存对话编号；网页给这一轮起的名字不进任何事件——中转的对象只把它的带密钥摘要记一周（`ledger_turns`，不导出），
  事件里用的是账本自己编的 `turn_id`；记录到达的那条事件不带访客。涉及访客自己的健康或资料的一轮（饮食与体重、我的资料）只计数、不归到任何访客。
  归档里的访客按天换名字：数得出一天有多少访客，跟不到第二天。

### 启用

1. 仓库 Secret **`ACTIVITY_KEY`**：`openssl rand -hex 32`（Settings → Secrets and variables → Actions → Secrets）。**设了就不要再改**：
   换了密钥，每个浏览器都成了新访客，历史从那里断开。
2. 部署令牌 `CLOUDFLARE_API_TOKEN` 要有 Account · D1 · Edit（用着 D1 备份的话已经有了）。运行 **relay** 与 **site** 两个工作流（或推送到 main）：
   各自找到或创建 D1 数据库 `taochronos-activity`（`bind-ledger.sh`；仓库变量 `ACTIVITY_DB_NAME` 可改名——但不能以 `taochronos-d1-` 开头：
   那是 D1 备份的库名，备份换数据时会把它们整批删掉重建，脚本遇到这样的名字会报错并不绑定），绑定为 `ACTIVITY_DB`，再把密钥写进 Worker。
   表在第一次写入时自己建。
   **账本是按 Workers Paid 的额度设计的**（[ADR 0023](../docs/adr/0023-workers-paid.md)）。实测的 D1 用量：每条事件写入时约读 15 行、写 5 行；
   每日合计每小时由每个 Worker 重算一次（读统计接口时也会重算），每次把当天的事件读约七遍。一天 300 位访客（约 5900 条事件）合计约读 200 万行、
   写 4 万行——Workers Paid 每月含 250 亿行读、5000 万行写，占不到百分之三；免费计划一天只有 500 万行读、10 万行写，还要与 D1 备份的导入共用，
   会占去一大块：**没有 Workers Paid 就不要开账本**。
3. 运行 **security** 工作流（`plan`，再 `apply`）：第 3 条规则现在也管 `POST /v1/activity` 的来源。
4. （可选）仓库变量 `ARCHIVE_BUCKET`：绑定了归档存储桶的 Worker 也把账本的事件存进去（`activity-logs/…`）。注意这是同一个开关——
   对话记录与哨兵事件也会从此存进桶而不再进仓库（[ADR 0023](../docs/adr/0023-workers-paid.md)）。保留多久由桶的生命周期规则定，没有人替你设；建议 400 天。
5. **activity** 工作流每天北京时间零点后把汇总取回 `data/activity-analytics/`。手动运行一次并勾选 `backfill`，补上启用之前的日子。

| 变量（两个 `wrangler.toml` 的 `[vars]`，须一致） | 默认 | 含义 |
|---|---|---|
| `ACTIVITY` | `on` | `off`：不管别的怎么设，都没有账本 |
| `ACTIVITY_IDS` | `notice` | 见上表 |
| `VISITOR_DAYS` | 390 | 编号自签发起的寿命（天） |
| `ACTIVITY_EVENT_DAYS` | 90 | 逐条事件、模型调用与访问在登记册里留多久；之后只剩每日合计（永久） |
| `ACTIVITY_VISITOR_DAYS` | 760 | 访客最后一次来访之后其记录留多久（25 个月）；到期删除，但仍计入“有过的访客” |
| `ACTIVITY_TURN_DAYS` | 7 | 中转记住「这次调用属于哪一轮」多久 |
| Secret `ACTIVITY_KEY` | — | 32 个字符以上；两个 Worker 同一个 |

### 接口

| 接口 | 谁能用 | 作用 |
|---|---|---|
| 网站 `POST /api/activity/hello` | 本站网页（浏览器、同源） | 网页加载后：返回模式、这个浏览器的状态与编号、给中转的通行证；记一次 `page_ready` |
| 网站 `POST /api/activity/choice` `{ids: "on" \| "off"}`、`POST /api/activity/forget` | 同上 | 访客自己的开关与删除。本站关于一个编号留了什么，不读给任何网页——访客自己的也不读 |
| 网站 `GET /api/activity/stats?days=N` \| `from=&to=` \| `range=all` | 只有 `LOG_EXPORT_TOKEN` | 账本的计数：activity 工作流读它写日报 |
| 网站 `GET /api/stats?days=N`、中转 `GET /v1/stats?days=N` | 只有 `LOG_EXPORT_TOKEN` | 两个 Worker 的按日计数（`usage.js`）：比账本早，工作流补启用之前的日子时读它 |
| 网站 `GET /api/activity/health`、中转 `GET /v1/activity/health` | 只有 `LOG_EXPORT_TOKEN` | 发件箱里等着多少、最老的等了多久、丢弃（`dropped`）、丢失（`lost`）、重复（`duplicates`）、写入失败次数；登记册各表的行数 |
| 网站 `GET /api/activity/archive?day=YYYY-MM-DD` | 只有 `LOG_EXPORT_TOKEN` | 拿这一天（UTC）的归档对清单：缺了哪个对象、哪个对象变了、多了哪个 |
| 中转 `POST /v1/activity` | 本站网页的来源 | 一轮的结局（计数），见上 |

要收集令牌的接口都不带 CORS 头、不看 Cookie：没设令牌时谁也读不到，没有账本时也只对令牌的持有人说「这里没有」。

### 日常与出了问题

- **看数（只有站长）**：
  - **GitHub**：[`data/activity-analytics/SUMMARY.md`](../data/activity-analytics/SUMMARY.md)——昨天、近 7 天、近 30 天与全部并排（访客、新访客、回访的、访问、
    页面、提问与其中未存档的、模型调用、token、国家/地区、有过的访客），回来的访客，近 30 天的地区、模型、工具、设备与浏览器、来源与请求类别；
    每天、每周、每月、每年的报表与 `lifetime.json` 在同一目录；activity 工作流每次运行的摘要页（Actions → activity → 那次运行）是同一张表。
    账本启用之前（或它的第一天还没过完），`SUMMARY.md` 是两个 Worker 的按日计数——页面、按日去重的访客、默认服务的提问与调用、地区——
    每晚的运行也把这些日子存进 `daily/`。仓库是私有的：能读这个仓库的人才看得到，加协作者之前想到这一点。
  - **Cloudflare**：控制台里 D1 → `taochronos-activity` → Console，或在本地 `npx wrangler d1 execute taochronos-activity --remote --command "…"`。
    不同访客只能在一段时间上数，不能把每天的人数相加；逐条的访客与每日活跃留 25 个月，再早的只在仓库的报表里。常用的几句：

```sql
-- 每天的访客、页面与提问（近 14 天；日子按北京时间）
SELECT day, SUM(CASE WHEN metric = 'active' THEN value ELSE 0 END) AS visitors, SUM(CASE WHEN metric = 'page_views' THEN value ELSE 0 END) AS page_views,
  SUM(CASE WHEN metric = 'questions' THEN value ELSE 0 END) AS questions FROM daily_metrics WHERE day >= date('now', '-14 days') GROUP BY day ORDER BY day DESC;
-- 一段时间里的不同访客
SELECT COUNT(DISTINCT a.visitor_id) AS visitors FROM visitor_daily_activity a JOIN visitors v ON v.visitor_id = a.visitor_id AND v.confirmed = 1
  WHERE a.day BETWEEN '2026-11-01' AND '2026-11-30';
-- 同一段时间里，按国家与省份的不同访客
SELECT a.country, a.region, COUNT(DISTINCT a.visitor_id) AS visitors FROM visitor_daily_activity a JOIN visitors v ON v.visitor_id = a.visitor_id AND v.confirmed = 1
  WHERE a.day BETWEEN '2026-11-01' AND '2026-11-30' GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 30;
-- 提问与其中未存档的（每日合计永久保留；逐条的提问留 25 个月）
SELECT SUM(value) AS questions, SUM(CASE WHEN k2 <> 'archived' THEN value ELSE 0 END) AS unarchived FROM daily_metrics
  WHERE metric = 'questions' AND day BETWEEN '2026-11-01' AND '2026-11-30';
-- 默认服务的模型调用（按模型）与 token
SELECT k1 AS model, SUM(value) AS calls FROM daily_metrics WHERE metric = 'model_calls' AND day BETWEEN '2026-11-01' AND '2026-11-30' GROUP BY 1 ORDER BY 2 DESC;
SELECT SUM(CASE WHEN metric = 'tokens_in' THEN value ELSE 0 END) AS tokens_in, SUM(CASE WHEN metric = 'tokens_out' THEN value ELSE 0 END) AS tokens_out
  FROM daily_metrics WHERE day BETWEEN '2026-11-01' AND '2026-11-30';
-- 有过的访客（含已删除的）
SELECT (SELECT COUNT(*) FROM visitors WHERE confirmed = 1) + COALESCE((SELECT v FROM ledger_state WHERE k = 'visitors_removed'), 0) AS visitors_ever;
```

  表：`visitors`、`visitor_daily_activity`、`sessions`、`activity_events`、`question_events`、`model_invocations`、`daily_metrics`（`metric` 的名字见
  `ledger-d1.js` 的 `METRICS`）、`archive_manifest`、`deletion_log`。
- **activity 工作流失败了**：看「The pipeline」一步。「outbox is not being drained」——Worker 的对象写不进 D1（令牌、数据库被删、配额），事件留在发件箱里等着，修好后自己补上；
  「dropped / lost」——发件箱满了（20 万条）或 Worker 够不着对象，这些事件没有了，计数缺多少就是报的那个数；「does not match its manifest」——归档里某天的对象与清单不符。
- **写入是可重复的**：发件箱至少送达一次，同一批写两遍、两个 Worker 的批次先后颠倒，登记册都是同一个结果（`security/test/ledger.test.js` 里就是这样验的）。
  所以修好故障后不必清理什么。
- **应访客要求删除**：访客自己在设置里就能删。站长代办：让对方在「设置 → 数据」里读出编号，然后
  `npx wrangler d1 execute taochronos-activity --remote --command "…"` 按 `ledger-d1.js` 的 `forget()` 那几句执行，并在 `deletion_log` 里记一行（不写编号）。
- **关掉**：两个 `wrangler.toml` 里 `ACTIVITY = "off"` 合入 main（Cookie 不再发、不再读，浏览器里的那个到期自灭）；只想不发编号：`ACTIVITY_IDS = "off"`。

### 这一层的局限

- 镜像（GitHub Pages）上的访客背后没有网站 Worker：没有编号，他们的提问只计数。
- 访客中途离开、回复没传完的那次调用没有人报告结局：状态留在 `open`，没有 token。
- 别的网站带来、被中转拒绝的请求仍只在 Workers Logs 里，不进账本（每个都问一次对象，等于让任何网页都能花掉对象的请求数）；网站这边的会计数。
- 网页自报的计数（`basis: client`）是网页说的：改过的客户端可以乱报，受每个地址每天 1000 条的限制，报表里与中转亲眼所见的分开列。
- 13 个月后同一个浏览器算新访客；25 个月没来的访客被删除（仍计入“有过的访客”）。这是不永久保存一个假名的代价。
- 启用之前的访客数补不出来：只有每天去重的人数，同一个人跨天来了几次已无从得知（`data/activity-analytics/README.md`）。

## 五、已知局限

- 区域的免费计划只有一条 10 秒的速率限制，只能平滑突发：真正的保护是第 2–4 条拦截规则、网站的每日读取上限与哨兵（被拦的请求不进 Worker）。
  账户已是 **Workers Paid**（[ADR 0023](../docs/adr/0023-workers-paid.md)）：Worker、Durable Object、D1、KV 都没有每日上限，超出每月所含额度后按量计费——
  所以匀速刷接口的客户端不会再让网站当天停摆，而是**花钱**；每日上限（网站的读取与调用、中转的调用与 token）与哨兵因此仍是费用的防线。
  （免费套餐的额度是整个账户的、每天 UTC 零点重置：Worker 请求 10 万次、Durable Object 请求 10 万次、写入 10 万行、D1 读取 500 万行、KV 写入 1000 次。）
  对象不可用时（故障）：网站的读取照常放行（速率限制绑定仍在，页面察觉不到），网站的工具调用与研究、中转的模型调用答 503
  （不放行未经核对、要花钱的调用；[ADR 0023](../docs/adr/0023-workers-paid.md)），记录丢弃。网站拒绝一个地址答 403、当天读取用完答 429
  （都带 `X-TC-Corpus: refused`），网页改用内置运行环境的要籍语料并说明原因。
  网页本身经过 Worker（`run_worker_first`）是为了安全头与哨兵的可见性，代价是每次打开页面算一次；要省，可把 `/`、`/about`、`/attribution` 从 `run_worker_first` 去掉，把这些头搬进 `_headers`。
- 运营商 NAT：许多真实访客共用一个 IPv4。按地址计数的限额（中转每人每分钟 30 次、每天 600 次）对他们是共用的；哨兵的 `ua_rotation` 为此只给很轻的分。
- Cloudflare WARP（ASN 13335）与各种 VPN 出口让真实访客看起来来自托管网络；`dc_asn` 只是两分，规则 5 只质询网页、不碰 API。
- 中转的计数对象（Durable Object）在首次创建的节点上不会迁移；中国访客每次调用多一次跨洋往返（几十到两百毫秒），远小于模型本身的耗时。
  token 额度在调用放行时先按请求大小（约三字节一个 token）预扣，回答末尾的用量再结清：三十个并发调用也透支不了多少。
- 页面的内容安全策略只执行管脚本与数据外送的几项；样式、字体、媒体、框架与两个 Worker 脚本的策略仍只报告（见上文「网页的安全头与内容安全策略」）。
- 哨兵的记忆在 Durable Object 里：十分钟窗口在内存中，对象被回收时丢失（最坏少算一段突发）；行与事件在 SQLite 里。
- 「被带过来的请求」靠浏览器自己说（`Sec-Fetch-Site`）。**不是浏览器、却在读者的设备上替他取东西的程序**——桌面邮件客户端载入邮件里的远程图片、
  Office 文档里的外链图片——不发这个头，和扫描器分不出来：一封带着指向扫描器路径的图片的邮件，仍可能让打开它的人的地址被拒绝
  （家庭/运营商网络是六小时）。这要对着某个人发邮件，不像在网页上贴一张图那样能波及所有读者；要连这也避免，只有 `HONEYPOT = "observe"`。
  反过来，扫描器若带上完整的浏览器协议栈（真的无头 Chrome），头一个扫描器路径不会被拒绝，第二个才会。
