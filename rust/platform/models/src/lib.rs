//! taochronos-models — 道乃久模型网关: the private Worker the developer API asks a model's chat of
//! (docs/adr/0039-model-relay-and-daily-allowance.md).  It has no route and no workers.dev address: only the API
//! Worker reaches it, through its service binding `MODEL_GATEWAY`.  It holds the providers' keys (the Worker secrets
//! MINIMAX_API_KEY, OPENAI_API_KEY) and nothing else; a developer's API key never reaches it, let alone a provider.
//!
//!   POST /v1/chat   {request_id, model, request, stream, include_usage, timeouts: {first_event, idle, total}}
//!
//! It reads the request again (tao_platform::models: the API has read it, this side does not take that on trust),
//! puts it in the provider's terms, asks the provider once — no retry, no second place: a second ask after an
//! ambiguous first one is a second answer paid for — and answers in the API's terms:
//!
//!   * a refusal known to have run nothing — this side's own before the provider was asked, or the provider's refusal
//!     of it (its key, its limits, the request's terms): the API's error object, and `X-Tao-Executed: 0`, the only
//!     answer that spends nobody's allowance;
//!   * any other failure — a connection that failed, a provider's failure, a deadline passed: `X-Tao-Executed: 1`;
//!   * a whole answer: the completion, its usage in `X-Tao-Usage`, `X-Tao-Executed: 1`;
//!   * a stream: its events in the API's terms as they come, its usage and its end told in comments the API reads and
//!     drops (`: tao {…}`), within its deadlines — the first event, the silence between two, the whole — and its size.
//!
//! What the provider sends is read through, never whole and then measured: an answer, or a refusal's body, past its
//! size or its time is cut there.  The caller leaving (the API's request aborted) aborts the provider's
//! (`request_signal_passthrough`).

use std::pin::Pin;
use std::task::{Context as TaskContext, Poll};
use std::time::Duration;

use futures_util::future::{Either, select};
use futures_util::{Stream, StreamExt};
use serde_json::{Value as Json, json};
use std::future::Future;
use tao_edge::{json as answer, secret, var};
use tao_platform::api;
use tao_platform::models::{self, Failure, ModelSpec, Provider, SseItem, SseParser};
use worker::{
    ByteStream, Context, Delay, Env, Fetch, Headers, Method, Request, RequestInit, RequestRedirect, Response, Result,
    event,
};

/// An event of the provider's, at the most.
const MOST_EVENT: usize = 64 * 1024;
/// An answer, whole or streamed, at the most.
const MOST_RESPONSE: usize = 1_048_576;
/// Of a provider's refusal, what is read for its code: its first bytes, within a few seconds.
const MOST_REFUSAL: usize = 16 * 1024;
const REFUSAL_MS: i64 = 5_000;

/// A body read through, within a size and a time.
enum Read {
    Whole(Vec<u8>),
    /// past the size: what was read up to it
    Over(Vec<u8>),
    Late,
    Broken,
}

/// A response's body, read chunk by chunk: never more than `most` bytes held, never past `until` (ms since the epoch).
/// What is left unread is cancelled when the stream is dropped.
async fn read_through(res: &mut Response, most: usize, until: i64) -> Read {
    let Ok(mut body) = res.stream() else { return Read::Broken };
    let mut out: Vec<u8> = Vec::new();
    loop {
        let left = until - tao_edge::now();
        if left <= 0 {
            return Read::Late;
        }
        match select(body.next(), Box::pin(Delay::from(Duration::from_millis(left as u64)))).await {
            Either::Left((Some(Ok(chunk)), _)) => {
                if out.len() + chunk.len() > most {
                    out.extend_from_slice(&chunk[..most - out.len()]);
                    return Read::Over(out);
                }
                out.extend_from_slice(&chunk);
            }
            Either::Left((Some(Err(_)), _)) => return Read::Broken,
            Either::Left((None, _)) => return Read::Whole(out),
            Either::Right(_) => return Read::Late,
        }
    }
}

fn refused(rid: &str, f: &Failure) -> Result<Response> {
    let mut headers = vec![("X-Tao-Executed", if f.executed { "1" } else { "0" }.to_string())];
    if let Some(s) = f.retry {
        headers.push(("Retry-After", s.to_string()));
    }
    answer(f.status, &api::error(rid, &f.refusal()), &headers)
}

/// A provider as this deployment has it: where it is asked, with which key, under which model name.
struct Upstream {
    url: String,
    key: String,
    model: String,
}

/// An https address, or one on this machine (the tests' stand-in provider): no other is asked, and none is followed
/// to another.
fn base_ok(base: &str) -> bool {
    base.starts_with("https://") || base.starts_with("http://127.0.0.1:") || base.starts_with("http://localhost:")
}

fn upstream(env: &Env, spec: &ModelSpec) -> Option<Upstream> {
    let (base_var, default_base, key_secret, model_var) = match spec.provider {
        // the key the website's relay uses, from the same platform (a mainland key needs the mainland address)
        Provider::MiniMax => ("MINIMAX_BASE", "https://api.minimax.cn/v1", "MINIMAX_API_KEY", "MINIMAX_MODEL"),
        Provider::OpenAI => ("OPENAI_BASE", "https://api.openai.com/v1", "OPENAI_API_KEY", "OPENAI_MODEL"),
    };
    let base = var(env, base_var).unwrap_or_else(|| default_base.into()).trim().trim_end_matches('/').to_string();
    if !base_ok(&base) {
        worker::console_error!("models: {base_var} is not an https address");
        return None;
    }
    let key = secret(env, key_secret)?;
    Some(Upstream {
        url: format!("{base}/chat/completions"),
        key: key.trim().to_string(),
        model: var(env, model_var).unwrap_or_else(|| spec.upstream.into()),
    })
}

/// A provider's refusal's own word for itself (its error code or type) — read for the mapping, logged, never passed on.
fn provider_code(text: &str) -> String {
    let v: Json = serde_json::from_str(text).unwrap_or(Json::Null);
    let e = &v["error"];
    let word = e["code"].as_str().or_else(|| e["type"].as_str()).unwrap_or("");
    if word.len() <= 80 && word.bytes().all(|c| c.is_ascii_alphanumeric() || b"_.:-".contains(&c)) {
        word.to_string()
    } else {
        String::new()
    }
}

#[event(fetch)]
async fn fetch(mut req: Request, env: Env, _ctx: Context) -> Result<Response> {
    if req.method() != Method::Post || req.path() != "/v1/chat" {
        return answer(404, &json!({ "error": "not_found" }), &[]);
    }
    let Some(raw) = tao_edge::body(&mut req, 256 * 1024).await? else {
        return refused("req_unknown", &models::REJECTED);
    };
    let envelope: Json = serde_json::from_slice(&raw).unwrap_or(Json::Null);
    let rid = envelope["request_id"].as_str().unwrap_or("req_unknown").to_string();
    let offered = models::offered(&var(&env, "MODELS").unwrap_or_else(|| "Tao-R1".into()));
    let Some(spec) = offered.iter().copied().find(|m| Some(m.id) == envelope["model"].as_str()) else {
        return refused(&rid, &models::UNAVAILABLE);
    };
    let cap =
        var(&env, "MODEL_MAX_OUTPUT_TOKENS").and_then(|v| v.parse::<i64>().ok()).filter(|v| *v > 0).unwrap_or(65_536);
    let chat = match models::read_chat(envelope["request"].to_string().as_bytes(), &[spec], cap) {
        Ok(c) => c,
        Err(_) => return refused(&rid, &models::REJECTED),
    };
    let Some(up) = upstream(&env, spec) else {
        worker::console_error!("models {rid}: {} is not configured", spec.provider.name());
        return refused(&rid, &models::UNAVAILABLE);
    };
    let seconds = |k: &str, default: u64, most: u64| {
        envelope["timeouts"][k].as_u64().filter(|s| (1..=most).contains(s)).unwrap_or(default)
    };
    let (first, idle, total) = (seconds("first_event", 30, 120), seconds("idle", 30, 120), seconds("total", 180, 600));
    let started = tao_edge::now();
    let headers = Headers::new();
    headers.set("Content-Type", "application/json")?;
    headers.set("Accept", if chat.stream { "text/event-stream" } else { "application/json" })?;
    headers.set("Authorization", &format!("Bearer {}", up.key))?;
    let mut init = RequestInit::new();
    init.with_method(Method::Post)
        .with_headers(headers)
        .with_redirect(RequestRedirect::Manual)
        .with_body(Some(models::upstream_request(&chat, &up.model).to_string().into()));
    let asked = Request::new_with_init(&up.url, &init)?;
    // the API leaving aborts this: its request's signal is the provider's (request_signal_passthrough)
    let signal = req.signal();
    let waiting = if chat.stream { first.min(total) } else { total };
    let sent = Box::pin(async move { Fetch::Request(asked).send_with_signal(&signal).await });
    let mut res = match select(sent, Box::pin(Delay::from(Duration::from_secs(waiting)))).await {
        Either::Left((Ok(res), _)) => res,
        Either::Left((Err(e), _)) => {
            // the connection failed: before the provider took the request, or after it ran — not known, so counted
            worker::console_error!("models {rid}: {} unreachable: {e}", spec.provider.name());
            return refused(&rid, &models::LOST);
        }
        Either::Right(_) => {
            worker::console_error!("models {rid}: {} silent for {waiting} s", spec.provider.name());
            return refused(&rid, &models::TIMEOUT);
        }
    };
    let status = res.status_code();
    if (300..400).contains(&status) {
        worker::console_error!("models {rid}: {} answered a redirect, not followed", spec.provider.name());
        return refused(&rid, &models::UNAVAILABLE);
    }
    if !(200..300).contains(&status) {
        // its first bytes, for its code: a refusal's body is no answer, and is not waited for long
        let until = (started + total as i64 * 1000).min(tao_edge::now() + REFUSAL_MS);
        let head = match read_through(&mut res, MOST_REFUSAL, until).await {
            Read::Whole(b) | Read::Over(b) => b,
            Read::Late | Read::Broken => Vec::new(),
        };
        let code = provider_code(&String::from_utf8_lossy(&head));
        worker::console_error!("models {rid}: {} {status} {code}", spec.provider.name());
        return refused(&rid, &models::failure_of(status, &code));
    }
    let content_type = res.headers().get("Content-Type")?.unwrap_or_default();
    if !chat.stream || !content_type.contains("event-stream") {
        // a whole answer (or a stream asked and refused in a JSON reply: MiniMax's base_resp), within the time left
        let text = match read_through(&mut res, MOST_RESPONSE, started + total as i64 * 1000).await {
            Read::Whole(b) => b,
            Read::Over(_) => return refused(&rid, &models::TOO_LARGE),
            Read::Late => return refused(&rid, &models::TIMEOUT),
            Read::Broken => {
                worker::console_error!("models {rid}: {} body broken", spec.provider.name());
                return refused(&rid, &models::FAILED);
            }
        };
        let mut v: Json = match serde_json::from_slice(&text) {
            Ok(v) => v,
            Err(_) => return refused(&rid, &models::FAILED),
        };
        let seen = models::normalize(&mut v, spec, &rid, true);
        if let Some(f) = seen.failure {
            worker::console_error!("models {rid}: {} reported {} in a 200", spec.provider.name(), f.code);
            return refused(&rid, &f);
        }
        if chat.stream {
            // asked for a stream and given a whole answer: given on as a stream of one chunk would misname it — a
            // failure the API tells as one
            return refused(&rid, &models::FAILED);
        }
        let usage = json!({ "input_tokens": seen.input_tokens, "output_tokens": seen.output_tokens });
        return answer(200, &v, &[("X-Tao-Executed", "1".to_string()), ("X-Tao-Usage", usage.to_string())]);
    }
    let stream = Watched::new(res.stream()?, spec, rid, chat.include_usage, first, idle, total, started);
    let h = Headers::new();
    h.set("Content-Type", "text/event-stream; charset=utf-8")?;
    h.set("Cache-Control", "no-store")?;
    h.set("X-Tao-Executed", "1")?;
    Ok(Response::from_stream(stream)?.with_headers(h))
}

/// A provider's stream in the API's terms, as it comes, within its deadlines and its size.
struct Watched {
    inner: Pin<Box<ByteStream>>,
    timer: Pin<Box<Delay>>,
    parser: SseParser,
    spec: &'static ModelSpec,
    rid: String,
    include_usage: bool,
    /// the first event's deadline and the whole's (ms since the epoch, from when the provider was asked)
    first_until: i64,
    total_until: i64,
    idle_ms: i64,
    events: usize,
    sent: usize,
    input_tokens: Option<i64>,
    output_tokens: Option<i64>,
    finished: bool,
    done: bool,
}

impl Watched {
    #[allow(clippy::too_many_arguments)]
    fn new(
        inner: ByteStream,
        spec: &'static ModelSpec,
        rid: String,
        include_usage: bool,
        first: u64,
        idle: u64,
        total: u64,
        started: i64,
    ) -> Self {
        let mut w = Watched {
            inner: Box::pin(inner),
            timer: Box::pin(Delay::from(Duration::from_secs(1))),
            parser: SseParser::new(MOST_EVENT),
            spec,
            rid,
            include_usage,
            first_until: started + first as i64 * 1000,
            total_until: started + total as i64 * 1000,
            idle_ms: idle as i64 * 1000,
            events: 0,
            sent: 0,
            input_tokens: None,
            output_tokens: None,
            finished: false,
            done: false,
        };
        w.arm();
        w
    }

    /// The next deadline: the first event's (counted from when the provider was asked, not again from its headers),
    /// or the silence between two — never past the whole's.
    fn arm(&mut self) {
        let now = tao_edge::now();
        let until = if self.events == 0 { self.first_until } else { now + self.idle_ms }.min(self.total_until);
        self.timer = Box::pin(Delay::from(Duration::from_millis((until - now).max(1) as u64)));
    }

    fn meta(&self, end: &str, code: Option<&str>) -> String {
        let mut out = models::sse_meta(
            &json!({ "usage": { "input_tokens": self.input_tokens, "output_tokens": self.output_tokens } }),
        );
        out.push_str(&models::sse_meta(&json!({ "end": end, "code": code })));
        out
    }

    /// The stream ended by a failure: an error event, the end told, and nothing more.
    fn fail(&mut self, f: &Failure) -> Vec<u8> {
        self.done = true;
        let mut out = models::sse_data(&api::error(&self.rid, &f.refusal()).to_string());
        out.push_str(&self.meta("error", Some(f.code)));
        out.into_bytes()
    }

    fn render(&mut self, items: Vec<SseItem>) -> std::result::Result<Vec<u8>, Failure> {
        let mut out = String::new();
        for item in items {
            match item {
                SseItem::Data(d) => {
                    self.events += 1;
                    let line = match serde_json::from_str::<Json>(&d) {
                        Ok(mut v) => {
                            let seen = models::normalize(&mut v, self.spec, &self.rid, self.include_usage);
                            if let Some(f) = seen.failure {
                                return Err(f);
                            }
                            self.input_tokens = seen.input_tokens.or(self.input_tokens);
                            self.output_tokens = seen.output_tokens.or(self.output_tokens);
                            if seen.finish_reason.is_some() {
                                self.finished = true;
                            }
                            if seen.drop {
                                continue;
                            }
                            models::sse_data(&v.to_string())
                        }
                        // not JSON: not the protocol — a failure rather than a guess
                        Err(_) => return Err(models::FAILED),
                    };
                    out.push_str(&line);
                }
                SseItem::Done => {
                    out.push_str(&self.meta("ok", None));
                    out.push_str("data: [DONE]\n\n");
                    self.done = true;
                    break; // the answer's end: whatever follows it is not the answer's
                }
                SseItem::Comment(_) => {} // a provider's keep-alive: not passed on
            }
        }
        self.sent += out.len();
        if self.sent > MOST_RESPONSE {
            return Err(models::TOO_LARGE);
        }
        Ok(out.into_bytes())
    }
}

impl Stream for Watched {
    type Item = Result<Vec<u8>>;

    fn poll_next(self: Pin<&mut Self>, cx: &mut TaskContext<'_>) -> Poll<Option<Self::Item>> {
        let this = self.get_mut();
        if this.done {
            return Poll::Ready(None);
        }
        loop {
            match this.inner.as_mut().poll_next(cx) {
                Poll::Ready(Some(Ok(chunk))) => {
                    let items = match this.parser.push(&chunk) {
                        Ok(items) => items,
                        Err(_) => return Poll::Ready(Some(Ok(this.fail(&models::TOO_LARGE)))),
                    };
                    let had = this.events;
                    match this.render(items) {
                        Ok(out) => {
                            if this.events > had {
                                this.arm();
                            }
                            if !out.is_empty() {
                                return Poll::Ready(Some(Ok(out)));
                            }
                            if this.done {
                                return Poll::Ready(None);
                            }
                        }
                        Err(f) => return Poll::Ready(Some(Ok(this.fail(&f)))),
                    }
                }
                Poll::Ready(Some(Err(_))) => return Poll::Ready(Some(Ok(this.fail(&models::FAILED)))),
                Poll::Ready(None) => {
                    // the provider closed: what was left is read; an answer that told its end is whole
                    let mut out = match this.parser.finish() {
                        Ok(items) => match this.render(items) {
                            Ok(out) => out,
                            Err(f) => return Poll::Ready(Some(Ok(this.fail(&f)))),
                        },
                        Err(_) => return Poll::Ready(Some(Ok(this.fail(&models::FAILED)))),
                    };
                    if !this.done {
                        if this.finished {
                            out.extend(this.meta("ok", None).into_bytes());
                            out.extend(b"data: [DONE]\n\n");
                        } else {
                            out.extend(this.fail(&Failure {
                                code: "stream_cut",
                                message: "the answer was cut off",
                                ..models::FAILED
                            }));
                        }
                    }
                    this.done = true;
                    return Poll::Ready(if out.is_empty() { None } else { Some(Ok(out)) });
                }
                Poll::Pending => {
                    if this.timer.as_mut().poll(cx).is_ready() {
                        let f = if this.events == 0 {
                            models::TIMEOUT
                        } else {
                            Failure { code: "model_stalled", message: "the model stopped answering", ..models::TIMEOUT }
                        };
                        return Poll::Ready(Some(Ok(this.fail(&f))));
                    }
                    return Poll::Pending;
                }
            }
        }
    }
}
