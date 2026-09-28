# 对话记录（道乃久默认服务，测试期间）

只有**同意记录**的访客的对话在这里（网页在第一次提问前询问；不同意则不上传）。由 `.github/workflows/chat-logs.yml` 每小时从中转服务
（`relay/`）取回：按中转收到的日期（UTC）写成 `年/月/日.jsonl`，一行一轮问答；`cursor.json` 是已取回的最后一条的编号。

**这些是访客写下的内容：仓库须保持私有；仓库公开前先把本目录移走。** 不含 API Key、设置或网络地址。

| 字段 | 含义 |
|---|---|
| `n` | 中转的记录编号（递增，不重复） |
| `received` | 中转收到的时间（UTC） |
| `conversation`、`turn` | 对话的随机编号（只在该浏览器内有意义）与第几问 |
| `question`、`answer` | 问题（≤4000 字）与回答（Markdown，≤12000 字；含 `[[段落号]]` 引文） |
| `images` | 附图张数（图片本身不记录） |
| `status`、`error` | done / error / stopped，以及出错信息 |
| `model`、`provider` | 底层模型与服务（`impf` 为默认服务） |
| `runtime`、`corpus` | 运行环境（browser / server）与语料（canon 要籍语料 / full 全量 / demo） |
| `tools` | 调用的工具：名称、是否成功、耗时、参数（≤300 字） |
| `citations` | 引文核对：总数与 ok（与原文一致）/ warn（存疑）/ bad（查无此段）/ pending，及所引段落号 |
| `usage`、`rounds`、`ms` | 本轮的 token 用量（input / output）、模型调用次数、总耗时（毫秒） |
| `started`、`finished`、`app`、`id`、`v` | 起止时间、TaoChronos 版本、消息编号、记录格式版本 |
