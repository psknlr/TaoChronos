// A stand-in for a model provider (MiniMax's OpenAI-compatible chat completions), for cloud/api/test/run.sh: the
// private model gateway (cloud/models) is pointed at it, and the scenario asks it, through the API, for what each word
// of the last message names — an answer whole or streamed, a stream cut in pieces of any size, a tool call, reasoning,
// a refusal, a busy moment, a failure inside a 200, a provider slow to begin or silent half-way.  It also says what it
// was asked (GET /seen): the last request, and whether anything of a developer's (an API key, a cookie) ever reached it.
//   node cloud/api/test/provider.mjs 8795
import http from "node:http";

const port = Number(process.argv[2] || 8795);
const KEY = "Bearer test-provider-key";
const seen = { requests: 0, tao_seen: false, cookie_seen: false, wrong_auth: 0, last: null, last_headers: null, aborted: 0 };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function chunk(id, delta, finish = null, extra = {}) {
  return { id, object: "chat.completion.chunk", created: 1, model: "MiniMax-M3", choices: [{ index: 0, delta, finish_reason: finish }],
    input_sensitive: false, ...extra };
}

http.createServer(async (req, res) => {
  if (req.method === "GET" && req.url === "/seen") {
    res.writeHead(200, { "Content-Type": "application/json" });
    return res.end(JSON.stringify(seen));
  }
  let raw = "";
  for await (const part of req) raw += part;
  seen.requests += 1;
  const text = raw + JSON.stringify(req.headers);
  if (text.includes("tao_live_") || text.includes("tao_test_")) seen.tao_seen = true;
  if (req.headers.cookie) seen.cookie_seen = true;
  if (req.headers.authorization !== KEY) {
    seen.wrong_auth += 1;
    res.writeHead(401, { "Content-Type": "application/json" });
    return res.end(JSON.stringify({ error: { type: "authentication_error", code: "invalid_api_key" } }));
  }
  let body;
  try { body = JSON.parse(raw); } catch { res.writeHead(400); return res.end("{}"); }
  seen.last = body;
  seen.last_headers = { accept: req.headers.accept, authorization: req.headers.authorization ? "present" : "absent" };
  // the connection closed before the answer ended: the caller aborted it
  res.on("close", () => { if (!res.writableEnded) seen.aborted += 1; });
  const last = body.messages?.at(-1);
  const q = typeof last?.content === "string" ? last.content : (last?.content || []).map((p) => p.text).join(" ");
  const id = "0a1b2c3d";
  const usage = { prompt_tokens: 11, completion_tokens: 7, total_tokens: 18, total_characters: 0 };
  if (q.includes("reject")) {
    res.writeHead(400, { "Content-Type": "application/json" });
    return res.end(JSON.stringify({ error: { type: "invalid_request_error", code: "context_length_exceeded", message: "MiniMax-M3: too long" } }));
  }
  if (q.includes("busy")) {
    res.writeHead(429, { "Content-Type": "application/json", "Retry-After": "3" });
    return res.end(JSON.stringify({ error: { type: "rate_limit", code: "rate_limit_exceeded" } }));
  }
  if (q.includes("base_resp")) {
    res.writeHead(200, { "Content-Type": "application/json" });
    return res.end(JSON.stringify({ base_resp: { status_code: 1008, status_msg: "insufficient balance" } }));
  }
  if (q.includes("slow-start")) await sleep(8000);
  if (!body.stream) {
    const message = { role: "assistant", content: `Tao answers: ${q}`, reasoning_details: [{ type: "reasoning.text", text: "…", format: "MiniMax-response-v1" }] };
    res.writeHead(200, { "Content-Type": "application/json" });
    return res.end(JSON.stringify({ id, object: "chat.completion", created: 1, model: "MiniMax-M3", choices: [{ index: 0, message, finish_reason: "stop" }],
      usage, input_sensitive: false, output_sensitive: false, base_resp: { status_code: 0, status_msg: "" } }));
  }
  res.writeHead(200, { "Content-Type": "text/event-stream" });
  const events = [];
  if (q.includes("tool")) {
    // the arguments name the upstream's model: what the model wrote is passed on as it wrote it
    const args = '{"query":"桂枝汤","model":"MiniMax-M3"}';
    events.push(chunk(id, { role: "assistant", content: null, tool_calls: [{ index: 0, id: "call_1", type: "function", function: { name: "evidence_search", arguments: "" } }] }));
    for (const piece of [args.slice(0, 7), args.slice(7, 19), args.slice(19)]) {
      events.push(chunk(id, { tool_calls: [{ index: 0, function: { arguments: piece } }] }));
    }
    events.push(chunk(id, {}, "tool_calls"));
  } else {
    events.push(chunk(id, { role: "assistant", reasoning_details: [{ type: "reasoning.text", text: "想一想", format: "MiniMax-response-v1" }] }));
    for (const word of ["桂枝汤", "主治", "太阳中风。"]) events.push(chunk(id, { content: word }));
    events.push(chunk(id, {}, "stop"));
  }
  events.push({ id, object: "chat.completion.chunk", created: 1, model: "MiniMax-M3", choices: [], usage });
  const wire = events.map((e) => `data: ${JSON.stringify(e)}\r\n\r\n`).join("") + ": keep-alive\n\n" + "data: [DONE]\n\n";
  if (q.includes("drip")) {
    // an event every 200 ms for six seconds: a caller who leaves is noticed at the next write
    for (let i = 0; i < 30 && !res.destroyed; i++) {
      res.write(`data: ${JSON.stringify(chunk(id, { content: `${i} ` }))}\n\n`);
      await sleep(200);
    }
    if (!res.destroyed) res.end("data: [DONE]\n\n");
    return;
  }
  if (q.includes("stall")) {
    res.write(wire.slice(0, wire.indexOf("\r\n\r\n") + 4)); // the first event, then nothing
    await sleep(8000);
    return res.end();
  }
  if (q.includes("fragment")) {
    // in pieces of 1 to 7 bytes: a character's bytes apart, a CR from its LF
    const bytes = Buffer.from(wire);
    for (let i = 0, n = 1; i < bytes.length; i += n, n = (n % 7) + 1) {
      res.write(bytes.subarray(i, i + n));
      await sleep(2);
    }
    return res.end();
  }
  res.end(wire);
}).listen(port, "127.0.0.1", () => console.log(`stand-in provider on ${port}`));
