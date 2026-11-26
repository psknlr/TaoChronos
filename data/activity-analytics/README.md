# 使用统计（活动账本的汇总）

两个 Worker 的**活动账本**（`security/ledger.js`，见 [`security/README.md`](../../security/README.md)「活动账本」与
[ADR 0035](../../docs/adr/0035-the-activity-ledger.md)）把它们答复的每个请求记成一条事件：网页被打开、接口被读取、一个问题、一次模型调用。
这里是这些事件的**汇总**：只有计数，没有任何一条事件、任何一个访客编号、任何网络地址。由
`.github/workflows/activity.yml` 每天（北京时间零点过后）运行 `security/activity.py` 写入。

**这些数只给站长看**：网站上没有哪一页显示它们，读它们的接口只认收集令牌（`LOG_EXPORT_TOKEN`），这个仓库是私有的。
先看 [`SUMMARY.md`](SUMMARY.md)；要查别的，在 Cloudflare 的 D1 控制台里查（[`security/README.md`](../../security/README.md)「活动账本 → 日常」里有常用的几句）。

```
data/activity-analytics/
  SUMMARY.md              给人看的一页：昨天、近 7 天、近 30 天与全部并排，回来的访客，近 30 天的地区、模型、工具、设备、来源（每次运行重写）
  daily/年/月/日.json     一天
  weekly/年-W周.json      一周（周一至周日，ISO 周）
  monthly/年-月.json      一个月
  yearly/年.json          一年
  lifetime.json           自有记录以来
  pipeline.json           上一次检查时两个 Worker 账本的计数（丢弃、丢失、写入失败……），供下一次比较
```

事件本身与访客编号留在私有的 D1（登记册）与 R2（归档）里，**不进仓库**：仓库的历史删不掉，汇总则不涉及任何个人。

## 两种来源：`ledger` 与 `backfill`

每个文件有两块，没有的那一块是 `null`：

| 块 | 含义 |
|---|---|
| `ledger` | 活动账本启用之后的日子：账本自己的计数。**访客是整段时间内去重的**——一周、一个月的访客是这段时间里不同的匿名编号数，逐日向登记册问出来的，不是把每天的人数相加（`security/ledger-d1.js`：`stats`） |
| `backfill` | 启用之前的日子：从当时留下的东西里补出来的（`security/activity.py backfill`），见下 |

一个跨越启用日的周或月，两块都有：`ledger` 是启用后那几天的，`backfill` 是启用前那几天加起来的。`complete` 为 `false` 表示这段时间还没过完
（`ledger` 只算到昨天）。`min_cell` 是写入时的最小单元（见「不会点到某个人」）。

### `ledger`

| 字段 | 含义 |
|---|---|
| `from`、`to`、`first_day` | 这块计数覆盖的日子（北京时间），以及账本的第一天 |
| `totals` | `visitors` 访客（去重）、`new_visitors` 新访客、`returning_visitors` 回访的访客、`visits` 访问次数、`page_views` 页面访问、`questions` 提问、`questions_archived` / `questions_unarchived` 已存档与未存档的提问、`model_calls`（`model_calls_relay` 默认服务放行的调用 + `model_calls_reported` 网页自报的自备模型调用）、`tokens_in` / `tokens_out`、`tool_calls`、`countries`、`regions` |
| `lifetime` | 账本里**有过**的访客数（`visitors`：现有的 + 已删除的 `removed`），以及发出后没有带回过的编号数 `unconfirmed` |
| `daily`、`days` | 周、月、年的文件才有：逐日的 `active`（当日访客）、`active_7` / `active_30`（到当日为止 7 天 / 30 天内的不同访客）、`page_views`、`sessions`、`questions`、`new_visitors`、`model_calls`、`tokens_in` / `tokens_out`、`returning` |
| `questions` | 提问按来源 `by_basis`（`relay` 默认服务亲眼所见、`client` 网页自报、`record` 只有对话记录为证）、按模型 `by_model`、按板块 `by_module`、按结局 `by_status`、按是否同意记录 `by_consent`，以及被限额拒绝的调用 `refusals` |
| `models` | 默认服务的模型调用：按模型 `calls`、按结局 `outcomes`（`ok`、`open` 没等到结束、`upstream_timeout`……）、向模型服务实际请求的次数 `asks`、token |
| `places` | 国家与省级地区：访客（去重）、页面访问、提问。访客不足 `min_cell` 的合并成一行（`country` 为空，`folded` 是合并了几处） |
| `retention` | 留存：`weekly` 按首次来访的那一周，之后各周回来的人数；`d1` / `d7` / `d30` 首次来访后第 1、7、30 天回来的人数与基数 |
| `features` | 工具调用次数 `tools`、运行环境与语料 `runtimes`、页面 `pages`、接口 `api`、评价 `feedback`、界面语言 `ui_languages`、访客自己的开关 `choices` |
| `audience` | 浏览器种类、系统、设备、浏览器语言、来源网站 `referrers`（只有来源的域名；来访少于 `min_cell` 的合并） |
| `sessions` | 访问次数、总时长、时长中位数、按时长分档 |
| `security` | 请求按类别 `classes`（`human` 访客的浏览器、`suspect` 被标记的浏览器、`crawler`、`automation`、`own`、`cross_site`）与处置 `actions` |
| `coverage` | 数据的完整度：有访客编号的页面访问 `page_views_identified`、网页加载后自报的 `page_ready`、发出后没带回的编号 `unconfirmed`、提问的三种来源、读取时尚未汇总的天数 `pending_days` |

### `backfill`

启用账本之前，没有访客编号，也没有逐条的事件；留下来的只有三样，补出来的就是这三样：

| 字段 | 来自 | 含义 |
|---|---|---|
| `usage` | 两个 Worker 的按日计数（`security/usage.js`，用收集令牌读） | `page_views` 页面访问、`visitor_days` 按日去重的访客（同一个人两天来算两次）、`questions_default_service` / `model_calls_default_service` / `asker_days` 默认服务的提问、模型调用与提问的人 |
| `records` | 仓库里的对话记录（`data/chat-logs/`） | **同意记录的访客**的提问数 `questions`（一轮只算一次，以最后一条记录为准）、按服务 `by_provider`、默认服务的模型 `by_model`、结局 `by_status`、模型调用 `model_calls`、token、工具调用与各工具次数、评价 `feedback`。只有计数，没有一个字的问题或回答；访客自设的接口记作 `custom`，其模型名不记 |
| `edge` | 边缘的记录（`data/security-logs/edge/`，`kind: traffic`） | 当天到两个主机的全部请求 `requests`、Cloudflare 自己数的访问 `visits`、按状态分 `by_status`——包括没有经过 Worker 的静态文件与被边缘拦下的请求 |
| `visitors` | 由 `usage` 推出 | **补不出来的那个数**：这段时间的访客在 `at_least`（人数最多的那一天）与 `at_most`（每天相加）之间。当时的去重键两天后就删了，同一个人跨天来了几次已无从得知 |
| `days` | | 这一块加了几天 |

注意 `usage.questions_default_service` 在 2026-11-25 之前**偏多**：那时一次模型调用只要以用户消息结尾就算一个问题，
自查要求重写、输出上限处接着写、失败后重问都被多算了一次（[ADR 0035](../../docs/adr/0035-the-activity-ledger.md)）。

## 不会点到某个人

- 这里没有访客编号、没有事件、没有地址；`places` 与 `referrers` 里访客不足 `min_cell`（默认 3，仓库变量 `ACTIVITY_MIN_CELL`）的合并成一行。
  `totals.countries` 仍然说一共有几个国家——有几个是可以说的，是哪几个小的不说。
- 网站上没有统计页：不合并的计数只在 D1 里，只有站长在 Cloudflare 里查得到。
- 仓库须保持私有（`data/` 在 `distribution-policy.yaml` 里是 confidential，任何构建产物都不含它）。

## 日常

- 重新生成某一天：Actions → activity → Run workflow，填 `day`。补启用之前的日子：勾选 `backfill`（设了 `LOG_EXPORT_TOKEN` 才有按日计数那一块）。
- 本机：`LOG_EXPORT_TOKEN=… python3 security/activity.py report`；`python3 security/activity.py backfill`（没有令牌时只用仓库里的记录）。
- 检查管道：`LOG_EXPORT_TOKEN=… python3 security/activity.py validate`——丢弃或丢失了事件、发件箱几小时没清空、归档与清单对不上，都会报错并让当次运行失败。
