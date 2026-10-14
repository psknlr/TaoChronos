# 把网站和全量古籍放到 Cloudflare：分步教程

> 账户已开通 Workers Paid（付费套餐）时，请看完整的部署指南：[English](../docs/deploy.md) · [简体中文（新加坡）](../docs/deploy.zh-SG.md)。它涵盖中转、网站、全量语料容器、D1 备份、R2 归档与边缘规则的全部步骤。

完成后：

- **https://chat.impf.ai** 有正式证书（浏览器地址栏显示锁），输入 http 地址会自动跳转到 https；
- 网站从 Cloudflare 的全球节点提供，国内访问一般比 GitHub Pages 快、也更稳定；
- **免费版**（Workers Free）就能做到以上两点：页面和原来一样在浏览器里运行要籍语料（535 部要籍中 533 部的原文）；网页文件（脚本、浏览器语料、
  Python 运行环境）由 Cloudflare 直接提供，免费且不限量；
- **开通全量古籍后**（可选，第 1、2 步，需 Workers Paid）：页面打开即可提问，不再下载浏览器语料和 Python 运行环境；工具检索的是
  **全部古籍**：958 部录本、1.22 亿字（本项目收录的全部古籍中，来源条件允许随网站发布的部分；条款禁止转载的 8 部不收，见
  [ATTRIBUTION.md](ATTRIBUTION.md)）；全量语料服务暂不可用时，页面自动改用浏览器内的要籍语料，照常可用。

技术说明见 [README.md](README.md)。只用免费版：只做第 3 步，约 5 分钟；要全量古籍：再做第 1、2 步。每一步都只需做一次。

## 需要准备

| 项目 | 说明 |
|---|---|
| Cloudflare 账户 | 就是 `impf.ai` 和道乃久默认服务（chat-api.impf.ai）所在的账户 |
| 仓库 Secrets | 已有的 `CLOUDFLARE_API_TOKEN`、`CLOUDFLARE_ACCOUNT_ID`（relay 用的那两个），不需要新建 |
| 付款方式 | 免费版不需要；全量古籍的容器需要 Workers Paid（每月 5 美元，可选）；语料存放在 Workers KV 的免费额度内 |

## 第 1 步（可选）：开通 Workers Paid（全量古籍的容器需要）

1. 登录 https://dash.cloudflare.com ，选中你的账户。
2. 左侧 **Compute (Workers)**（或 **Workers & Pages**）→ **Plans**（套餐）。
3. 选 **Workers Paid**（5 美元/月）→ 按提示完成付款。

没有这一步，网站照样部署到 Cloudflare（HTTPS 生效），只是全量语料服务不会部署，页面继续在浏览器里运行要籍语料。

## 第 2 步（可选）：给 API 令牌加上 Containers 权限

relay 用的令牌（模板 *Edit Cloudflare Workers*）已经能管理 Worker、KV 和路由，只差容器：

1. 右上角头像 → **My Profile → API Tokens**。
2. 找到当初为 GitHub 创建的那个令牌，点右侧 **⋯ → Edit**（编辑，不是 Roll）。
3. **Permissions** 里点 **+ Add more**，加一行：**Account** · **Containers** · **Edit**。
   同时确认已有：Account · Workers Scripts · Edit；Account · Workers KV Storage · Edit；Zone · Workers Routes · Edit。
4. **Continue to summary → Update token**。

编辑权限不会改变令牌本身，GitHub 里的 `CLOUDFLARE_API_TOKEN` 不用更新。

## 第 3 步：把 chat.impf.ai 交给 Cloudflare（删除旧的 DNS 记录，再部署）

Cloudflare 只在没有自建 DNS 记录的名称上建 Worker 的自定义域名，所以先删掉原来指向 GitHub Pages 的那条 CNAME：

1. Cloudflare 控制台 → 选中域名 **impf.ai** → **DNS → Records**。
2. 找到 **类型 CNAME、名称 `chat`、内容 `psknlr.github.io`** 的那一条 → 右侧 **Edit → Delete**，确认删除。
   只删这一条；`chat-api`（道乃久默认服务）等其他记录不要动。
3. 紧接着到 GitHub 仓库 → **Actions** → 左侧 **site** → 右侧 **Run workflow → Run workflow**。

工作流先测试两个 Worker，随即部署网站（约 3 分钟）：Cloudflare 为 `chat.impf.ai` 建立指向网站 Worker 的记录并签发证书，
几分钟内 https 生效；从删除记录到这时，chat.impf.ai 会短暂打不开。与此同时，工作流构建并部署全量语料容器（第一次约 20 分钟：
取回语料并校验、建全文索引、预热缓存、上传镜像），完成后再部署一次网站把它接上，并做一次全量检索检查。

工作流里黄色的警告会指出缺了哪一步（例如"没有 Workers Paid"或"令牌不能管理 Containers"），红色的错误说明失败原因；补上后再
**Run workflow** 即可。以后合入 main 时工作流自动运行，不必再动 DNS。

## 第 4 步：验证

1. 打开 **https://chat.impf.ai**：地址栏有锁；输入 `http://chat.impf.ai` 会跳到 https。
2. 左下角显示 **运行环境 · 已就绪**（载入时只显示“加载中”和一条进度条）。页面（包括设置）不显示用的是哪份语料；要确认，
   打开 **https://chat.impf.ai/api/info**：免费版返回 503（“本站的全量语料服务未部署：网页在浏览器里运行要籍语料”），页面在
   浏览器里运行要籍语料；开通全量古籍后返回全量语料的信息（`corpus` 里 `label` 为“全量语料”，`books` 为 958）。
3. 问一个问题（如"桂枝汤的组成出自哪部书？"），回答里的引文可点开核对。
4. **设置 → 关于**：语料一栏链接到全量语料的来源与授权。

全量语料服务（开通后）闲置 15 分钟会休眠（省钱）；休眠后第一位访客打开页面时它开始启动，通常在对方输入问题的时间里就绪。

## 第 5 步（建议）：GitHub Pages 的自定义域名

确认 chat.impf.ai 已由 Cloudflare 提供后：GitHub 仓库 → **Settings → Pages → Custom domain** → **Remove**。
这样 GitHub 不再为这个域名申请证书，`https://psknlr.github.io/TaoChronos/` 继续作为备用镜像（只有浏览器内的要籍语料）。
**不要在第 3 步完成前移除**，否则切换前的几分钟里 chat.impf.ai 会打不开。

## 费用

| 项目 | 价格（Cloudflare 公布） |
|---|---|
| Workers Free（免费版） | 0 元。网页文件由 Cloudflare 直接提供，不计次数；只有打开网页和 `/api` 请求经过网站的 Worker（每次访问约 2–3 次），免费版每天 10 万次，约够每天 3 万次访问。超出后当天剩余时间这些请求返回 429 |
| Workers Paid | 5 美元/月，含每月 1000 万次请求，以及容器 25 GiB·小时内存、375 vCPU·分钟、200 GB·小时磁盘 |
| 全量语料容器（standard-1：1/2 vCPU、4 GiB 内存） | 只在运行时计费，约 0.036 美元/小时＋少量磁盘与实际 CPU；闲置 15 分钟即休眠。每天平均运行 4 小时约 4 美元/月，从不休眠约 30 美元/月 |
| Workers KV | 143 MB，在免费额度（1 GB）内 |
| 网页静态文件 | 不收费 |

想更省：把 `cloud/corpus/wrangler.toml` 的 `SLEEP_AFTER` 改短（如 `"5m"`）。想更快：改长，或 `instance_type` 改为 `standard-2`。

## 常见问题

| 现象 | 原因与处理 |
|---|---|
| 工作流报「chat.impf.ai 还有一条自建的 DNS 记录」（Cloudflare：externally managed DNS records） | 第 3 步的 CNAME 还没删除：删除后再 **Run workflow** |
| 警告"no KV namespace" | 令牌缺 Account · Workers KV Storage · Edit |
| 警告"the store … is not (all) in the KV namespace" | 全量语料尚未上传：由维护者运行 `taochronos web upload`（见 README.md） |
| 警告"the account may not deploy containers yet" | 第 1 步或第 2 步未完成（工作流先检查，不白白构建镜像）；补上后 **Run workflow** |
| 警告"container was not deployed" | 部署容器时出错，日志里有 Cloudflare 的具体报错；修正后 **Run workflow**（可勾选 rebuild 强制重建） |
| https://chat.impf.ai/api/info 返回 503 | 免费版的正常状态：页面在浏览器里运行要籍语料。开通全量古籍后仍返回 503，说明全量语料服务未部署或暂不可用，页面已自动改用浏览器语料，功能不受影响 |
| 地址栏仍显示"不安全" | 证书签发需要几分钟；清除浏览器缓存后重试。确认 DNS 里 `chat` 记录类型为 Worker（由 Cloudflare 管理） |

## 需要时回退到 GitHub Pages

1. Cloudflare → **Workers & Pages → taochronos-site → Settings → Domains & Routes**，移除 `chat.impf.ai`；
2. **impf.ai → DNS → Records**：新建 CNAME，名称 `chat`，目标 `psknlr.github.io`，代理状态 **DNS only**（灰色云朵）；
3. GitHub 仓库 → **Settings → Pages → Custom domain** 填回 `chat.impf.ai`。

回退后网站回到 GitHub Pages（在证书签发前只有 http），页面在浏览器内运行要籍语料。

## 安全说明

- 全量语料容器没有公网地址，只有网站 Worker 能通过服务绑定访问它；每个请求还要带 Worker 为容器生成的令牌。
- 网站 Worker 只放行固定的几个只读接口和工具调用，按访客限流，不转发 Cookie、IP 等信息；不代理任何模型调用。
- 哨兵（`security/`，见其 README）记下扫描与非浏览器调用的地址和请求头，取回到私有仓库的 `data/security-logs/`；Cloudflare 边缘的
  WAF 规则、速率限制与区域设置由 security 工作流用专用令牌写入（`CLOUDFLARE_SECURITY_TOKEN`、`CLOUDFLARE_ANALYTICS_TOKEN`、变量
  `CLOUDFLARE_ZONE_ID`；见 `security/README.md`「启用」）。
- 上传全量语料的接口平时关闭；维护者更新语料时临时在仓库变量 `STORE_TOKEN_SHA256` 登记一个新令牌的 SHA-256，上传完即删除（见 README.md）。令牌本身不在仓库里。

## 免费套餐下的全量语料：D1 备份

没有 Workers Paid（没有容器）时，网站自己的 Worker 从 **Cloudflare D1**（Workers 免费套餐自带的数据库）回答全量语料：检索、
原文、书目、要籍、术语、引文核对等工具都在全部 958 部书上运行（https://chat.impf.ai/api/info 的 `label` 为“全量语料（备份）”）。有容器时仍由
容器回答，D1 备份不起作用；两者都没有时，页面照旧在浏览器里运行要籍语料。技术说明见
[docs/adr/0017-d1-backup.md](../docs/adr/0017-d1-backup.md)。

### 只需一步：给 API 令牌加上 D1 权限

1. Cloudflare 控制台右上角头像 → **My Profile → API Tokens**。
2. 找到当初为 GitHub 创建的那个令牌（`CLOUDFLARE_API_TOKEN`），点右侧 **⋯ → Edit**（编辑，不是 Roll）。
3. **Permissions** 里点 **+ Add more**，加一行：**Account** · **D1** · **Edit**。
4. **Continue to summary → Update token**。令牌本身不变，GitHub 里的 Secret 不用更新。

然后到 GitHub 仓库 → **Actions** → 左侧 **d1** → 右侧 **Run workflow → Run workflow**，开始导入。以后它每天 UTC 0 点
（北京时间 8 点）过后自动运行一次，不必再管。

### 导入要多久、怎么看进度

D1 免费套餐每天最多写入 10 万行。全量语料约 8.7 万行，再加预先算好的治学结果约 1.2 万行，所以**分两天导入**：第一次运行
（手动那天）写入语料和一部分结果，第二天的自动运行写完其余部分，随即自动重新部署网站、接上备份。每次运行约两小时：第一次
主要是逐条写入语料，第二次主要是在全量语料上计算那些预先算好的结果。

- 进度：**Actions → d1 →** 点开某次运行，**Summary** 里列出本次写入的行数、各步骤、各数据库，以及是否已完成。
- 运行结果写着 "the day's budget"（当天额度已用完）或 "the UTC day is over"（到了 UTC 0 点）是正常的：下一次运行自动接着
  导入；中断的运行也会从断点继续，不会重复写入。
- 完成后：打开 https://chat.impf.ai/api/info ，返回的语料信息里 `label` 为“**全量语料（备份）**”。

### 备份能做什么、不能做什么

- **直接计算**（14 个工具）：古籍检索（融合 bm25、时间、异体、词义四路；向量、知识图谱、引用谱系三路需要服务器）、原文、
  书目、要籍、术语词条、引文核对、溯源、异体规范、校勘、度量衡、安全提示、现代证据记录。
- **预先算好的常见条目**（16 个工具）：方剂源流、药性源流、术语源流、名称、方证网络、集注、经文互见、配伍、避讳、引书、学派、
  语义演变、版本见证、阅读门径、主张与共现等——在全量语料上为常见的方剂、药物、术语、条文预先算好；没有收的条目，工具会如实
  说明。
- **不能做**（44 个工具）：多智能体研究、D1–D5 分析、句读与今译、医案与版本谱系等需要服务器计算的工具。模型会向用户说明，
  并改用可用的工具检索原文作答。

### 费用与额度

都在免费额度内：D1 存储约 1.5 GB（免费 5 GB，分在 5 个数据库里，每个不超过 500 MB）；Workers 每天 10 万次请求；每次工具调用
在 Worker 里只用几毫秒的计算。要留意的是 D1 每天 500 万行的读取额度：一次检索约读 3 千～1.2 万行（中位数约 5500 行），
即每天约九百次检索；用完后到 UTC 0 点前，页面自动改用浏览器内的要籍语料。

| 现象 | 原因与处理 |
|---|---|
| d1 工作流警告 "the API token may not use D1" | 上面的一步还没做：令牌缺 Account · D1 · Edit；补上后 **Run workflow** |
| 警告 "the store … is not (all) in the KV namespace" | 全量语料尚未上传（见 README.md「更新全量语料」） |
| https://chat.impf.ai/api/info 仍返回 503 | 导入尚未完成（看 d1 的运行记录），或网站尚未重新部署：**Actions → site → Run workflow** |
| 更新了全量语料（新的 `cloud/store.json`） | d1 工作流会删除旧的 D1 数据库、重新导入（同样约两天），期间页面用浏览器语料 |
