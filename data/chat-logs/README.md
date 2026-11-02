# 对话记录（道乃久默认服务，测试期间）

只有**同意记录**的访客的对话在这里（网页在第一次提问前询问；不同意则不上传）。由 `.github/workflows/chat-logs.yml` 每小时从中转服务
（`relay/`）取回：按中转收到的日期（UTC）写成 `年/月/日.jsonl`，一行一轮问答；`cursor.json` 是已取回的最后一条的编号。

**这些是访客写下的内容：仓库须保持私有；仓库公开前先把本目录移走。** 不含 API Key、设置或网络地址。

中转绑定了归档存储桶后（仓库变量 `ARCHIVE_BUCKET`，[ADR 0023](../../docs/adr/0023-workers-paid.md)），新记录存进私有 R2 存储桶
（`chat-logs/年/月/日/编号.json`，一条一个对象，字段同下），不再进入本目录；读回某天：`python3 relay/collect.py archive --day …`。

| 字段 | 含义 |
|---|---|
| `n` | 中转的记录编号（递增，不重复） |
| `received` | 中转收到的时间（UTC） |
| `conversation`、`turn` | 对话的随机编号（只在该浏览器内有意义）与第几问 |
| `question`、`answer` | 问题（≤4000 字）与回答（Markdown，≤12000 字；含 `[[段落号]]` 引文） |
| `images` | 附图张数（图片本身不记录） |
| `status`、`error` | done / error / stopped，以及出错信息 |
| `model`、`provider` | 底层模型与服务（`impf` 为默认服务；`fixed` 为网页自己给出的固定回复，如问“你是谁”，此时没有 `model`，`rounds` 为 0） |
| `runtime`、`corpus` | 运行环境（browser / server）与语料（canon 要籍语料 / full 全量 / demo） |
| `tools` | 调用的工具：名称、是否成功、耗时、参数（≤300 字）；记录时间的网页另记 `id`、第几轮 `round`、结局 `status`（ok / error / timeout / stopped / skipped / background / refused）、开始于第几毫秒 `at`、等运行环境或排队的毫秒数 `wait`、运行环境自报的计算耗时 `compute` |
| `requests` | 每次模型请求（记录时间的网页才有）：第几轮 `round`、第几次 `attempt`；从本轮开始起算的毫秒数——发出 `sent`、回复开始 `open`、第一段 `first`、回答的第一个字 `text`、最后一段 `last`、结束 `end`；结束方式 `finish`（服务给的原因，如 stop / length / tool_calls）或失败原因 `failed`（stopped / timeout / unfinished / network / 服务的错误类型或 `http 状态码`，不含服务的原话）及 HTTP 状态码 `status`，超时时 `expired` 为哪一个时限（firstReply / silence / whole）；`input` / `output` token；这次请求期间网页隐藏的毫秒数 `hidden` 与完全没有运行的毫秒数 `asleep`（此后的网页才记：网页没人看着时断开的回复，可能是浏览器切断的，而非服务） |
| `events` | 请求之间发生的事：`continued`（在输出上限处截断的回答接着写）、`lighter`（少想一些重问）、`asked` / `time` / `steps`（工具到此为止：访客按了“不再等待”、本轮时间用完、轮数用完）、`resume`（访客按了“继续作答”：根据已有的工具结果接着作答，不再调用工具）、`cut:…`（回复被截断）、`compacted`（为不超出上下文预算，这次请求比上一次少发了内容）、`reused`（同一检索本轮已做过，结果取自那一次，没有重新运行）、`review`（自查：回答所引段落查无此段，请模型重写）、`unchecked`（重写没有完整给出，撤下，原回答保留）、`fallback`（站点服务不可用，改用内置运行环境），各带毫秒数 `at` |
| `hidden`、`asleep`、`was` | 本轮中网页隐藏的毫秒数，网页完全没有运行的毫秒数（手机休眠、标签页被冻结），以及本轮开始时的运行环境与语料（结束时已换了才有） |
| `citations` | 引文核对：总数与 ok（与原文一致）/ warn（存疑）/ bad（查无此段）/ pending，及所引段落号 |
| `usage`、`rounds`、`ms` | 本轮的 token 用量（input / output）、模型调用次数、总耗时（毫秒） |
| `resumed` | 这一轮被“继续作答”接着答了几次（没有则不记）。每答一次网页各发一条记录，`id` 相同，以最后一条为准；`usage`、`rounds`、`ms` 是几次加起来的，`requests`、`tools`、`events` 只是这一次的 |
| `started`、`finished`、`app`、`id`、`v` | 起止时间、TaoChronos 版本、消息编号、记录格式版本 |

## 对回答的反馈

同一批文件里还有访客对回答的**反馈**（`"kind": "feedback"`，一行一条）：访客在回答下点“有帮助 / 有问题”、在弹出的对话框里按
“提交”才发送，不论是否同意记录对话。反馈与它所评的那一轮共用 `id` 与 `conversation`；同一轮可有多条，以最后一条为准。

| 字段 | 含义 |
|---|---|
| `kind`、`v` | `feedback`，格式版本 1 |
| `id`、`conversation`、`turn` | 所评那一轮的消息编号、对话编号与第几问（与那一轮的记录相同） |
| `rating` | `up`（有帮助）/ `down`（有问题）/ `null`（访客撤回了评价，此时没有下面的字段） |
| `reasons` | 勾选的原因（有帮助：accurate 内容准确、sourced 引文可靠出处清楚、clear 条理清楚、thorough 资料全面、insight 有新的发现；有问题：citation 引文有误或查无出处、inaccurate 内容不准确、incomplete 回答不完整、off_topic 没有回答问题、slow 太慢、other 其他） |
| `comment` | 访客写的说明（≤2000 字） |
| `recorded` | 这一轮已按访客的同意记录（问题与回答见那条记录） |
| `question`、`answer` | 访客勾选“附上这一轮的问题和回答”时才有 |
| `given`、`model`、`provider`、`runtime`、`corpus`、`app` | 提交时间，以及那一轮的模型、服务、运行环境、语料与 TaoChronos 版本 |

`taochronos records [目录或文件…] [--since 年-月-日] [--until 年-月-日]` 汇总这些记录（默认读本目录）：从最后一个工具结果到回答第一个字的
时间及其组成、模型请求中断（超时、没说完就断开、连接或服务出错）后仍得到完整回答的比例、中断的请求中有多少发生在网页隐藏或休眠期间（`unseen`）、完整回答与其中引文全部核验通过的比例、时间花在哪里
（模型请求、各轮工具、网页隐藏或休眠，以及工具等待与运行之比），以及反馈（`feedback`：有评价的轮数、有帮助与有问题各几条、
各原因的次数、附了说明或问答的条数）。只输出计数与时长。
