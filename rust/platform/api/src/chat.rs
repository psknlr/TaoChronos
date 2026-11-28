//! `POST /v1/chat/completions` and `GET /v1/models` — a model's chat through the private model gateway
//! (`MODEL_GATEWAY`, a service binding to `taochronos-models`: no public route of its own), under the person's daily
//! allowance (exec.rs).  The gateway holds the providers' keys and speaks to them; this Worker reads and admits the
//! request, hands it on, and passes the answer back — whole, or as the stream the gateway writes, which this Worker
//! watches as it passes: the gateway's own words inside it (comments: the usage, how the answer ended) are read and
//! never passed on.  The stream's end is told to the allowance and the organisation from `waitUntil`, so that a caller
//! who leaves mid-answer is counted as cancelled, and the gateway's call — and the provider's — is aborted.

use std::pin::Pin;
use std::task::{Context as Poll_, Poll};
use std::time::Duration;

use futures_channel::oneshot;
use futures_util::Stream;
use futures_util::future::{Either, select};
use serde_json::{Value as Json, json};
use tao_edge::{json as answer, var};
use tao_platform::accounts::{ModelGate, Product};
use tao_platform::models::{self, ModelSpec, SseItem, SseParser};
use worker::{AbortController, ByteStream, Context, Delay, Env, Headers, Request, Response, Result};

use crate::exec::{self, Admitted, End, Exec, Gate};
use crate::{idempotency, key_of, refusal, refuse_with};

/// The deployment's model settings, read with their bounds (a value out of them: the default).
pub struct ModelSettings {
    pub gate: ModelGate,
    pub gate_word: String,
    pub offered: Vec<&'static ModelSpec>,
    pub cap: i64,
    pub first_event: i64,
    pub idle: i64,
    pub total: i64,
}

impl ModelSettings {
    pub fn read(env: &Env) -> ModelSettings {
        let num = |k: &str, default: i64, least: i64, most: i64| {
            var(env, k)
                .and_then(|v| v.trim().parse::<i64>().ok())
                .filter(|v| (least..=most).contains(v))
                .unwrap_or(default)
        };
        let gate_word = var(env, "MODEL_API").unwrap_or_else(|| "off".into()).trim().to_ascii_lowercase();
        ModelSettings {
            gate: ModelGate::parse(&gate_word),
            gate_word,
            offered: models::offered(&var(env, "MODELS").unwrap_or_else(|| "Tao-R1".into())),
            cap: num("MODEL_MAX_OUTPUT_TOKENS", 8192, 1, 65_536),
            first_event: num("MODEL_FIRST_EVENT_TIMEOUT_SECONDS", 30, 5, 120),
            idle: num("MODEL_IDLE_TIMEOUT_SECONDS", 30, 5, 120),
            total: num("MODEL_TOTAL_TIMEOUT_SECONDS", 180, 10, 600),
        }
    }
}

fn disabled(rid: &str) -> Result<Response> {
    refuse_with(rid, &refusal(503, "unavailable", "model_api_disabled", "the model API is not offered now"), &[])
}

/// `GET /v1/models`: the models this key may call (scope models:read).
pub async fn list(req: &Request, env: &Env, rid: &str) -> Result<Response> {
    let m = ModelSettings::read(env);
    let key = match key_of(req, env, rid).await {
        Ok(k) => k,
        Err(r) => return r,
    };
    let me = match crate::whoami(env, rid, &key, &m.gate_word).await {
        Ok(v) => v,
        Err(r) => return r,
    };
    if me.get("models_listed") != Some(&Json::Bool(true)) {
        return refuse_with(
            rid,
            &refusal(403, "permission", "scope", "this key may not list models (scope models:read)"),
            &[],
        );
    }
    let open = m.gate != ModelGate::Off && me.get("model_access") == Some(&Json::Bool(true));
    let data: Vec<Json> = if open { m.offered.iter().map(|s| models::listed(s)).collect() } else { Vec::new() };
    answer(200, &json!({ "object": "list", "data": data }), &[("X-Request-Id", rid.to_string())])
}

fn header_json(res: &Response, name: &str) -> Json {
    res.headers().get(name).ok().flatten().and_then(|v| serde_json::from_str(&v).ok()).unwrap_or(Json::Null)
}

fn text_answer(status: u16, text: String, content_type: &str, extra: &[(&'static str, String)]) -> Result<Response> {
    let headers = Headers::new();
    headers.set("Content-Type", content_type)?;
    headers.set("Cache-Control", "no-store")?;
    for (k, v) in extra {
        headers.set(k, v)?;
    }
    Ok(Response::ok(text)?.with_status(status).with_headers(headers))
}

/// `POST /v1/chat/completions`.
pub async fn completions(req: &mut Request, env: &Env, ctx: &Context, rid: &str) -> Result<Response> {
    let m = ModelSettings::read(env);
    if m.gate == ModelGate::Off {
        return disabled(rid);
    }
    let key = match key_of(req, env, rid).await {
        Ok(k) => k,
        Err(r) => return r,
    };
    let Some(body) = tao_edge::body(req, tao_platform::api::MOST_BODY).await? else {
        return refuse_with(
            rid,
            &refusal(
                413,
                "invalid_request",
                "too_large",
                format!("a request body is at most {} bytes", tao_platform::api::MOST_BODY),
            ),
            &[],
        );
    };
    let chat = match models::read_chat(&body, &m.offered, m.cap) {
        Ok(c) => c,
        Err(r) => return refuse_with(rid, &r, &[]),
    };
    // nothing is admitted for a call that cannot be made
    let Ok(gateway) = env.service("MODEL_GATEWAY") else {
        return refuse_with(rid, &models::UNAVAILABLE.refusal(), &[]);
    };
    let idem = match idempotency(req, rid) {
        Ok(i) => i,
        Err(r) => return r,
    };
    let ex = Exec {
        rid,
        org: &key.org,
        digest: &key.digest,
        product: Product::Chat,
        model: Some(chat.model),
        request_hash: models::request_hash("POST", "/v1/chat/completions", &chat.body, Some(chat.model)),
        idem,
        hold_ms: (m.total + 60) * 1000,
        models: &m.gate_word,
    };
    let a = match exec::admit(env, &ex).await? {
        Gate::Done(r) => return Ok(r),
        Gate::Go(a) => a,
    };
    let quota = exec::quota_headers(&a.quota, false);
    let given_back = exec::quota_headers(&a.quota, true);
    // the gateway asked, with a signal: aborted when the caller leaves or this Worker's own deadline passes
    let stop = AbortController::default();
    let signal = stop.signal();
    let payload = json!({
        "request_id": rid, "model": chat.model.id, "request": chat.body, "stream": chat.stream, "include_usage": chat.include_usage,
        "timeouts": { "first_event": m.first_event, "idle": m.idle, "total": m.total },
    });
    let sys = worker::web_sys::RequestInit::new();
    sys.set_method("POST");
    let h = worker::web_sys::Headers::new()?;
    h.set("Content-Type", "application/json")?;
    sys.set_headers(&h);
    sys.set_body(&worker::wasm_bindgen::JsValue::from_str(&payload.to_string()));
    sys.set_signal(Some(&*signal));
    let asked: Request =
        worker::web_sys::Request::new_with_str_and_init("https://models.internal/v1/chat", &sys)?.into();
    // the gateway answers its headers within the model's whole time (or sooner): a backstop, should it not
    let backstop = Delay::from(Duration::from_secs((m.total + 20) as u64));
    let mut res = match select(Box::pin(gateway.fetch_request(asked)), Box::pin(backstop)).await {
        Either::Left((Ok(res), _)) => res,
        Either::Left((Err(e), _)) => {
            // the gateway could not be reached: nothing was asked of the provider
            worker::console_error!("api {rid}: gateway {e}");
            exec::end(env, &a, &End::released(503, "model_unavailable")).await;
            return refuse_with(rid, &models::UNAVAILABLE.refusal(), &given_back);
        }
        Either::Right(_) => {
            stop.abort();
            let r = models::TIMEOUT.refusal();
            exec::end(env, &a, &End::failed(504, r.code, None)).await;
            return refuse_with(rid, &r, &quota);
        }
    };
    let executed = res.headers().get("X-Tao-Executed").ok().flatten().as_deref() == Some("1");
    let status = res.status_code();
    let mut headers = vec![("X-Request-Id", rid.to_string())];
    if status != 200 {
        // the gateway's refusal, in the API's words already: passed on, the end told as it was
        let text = res.text().await.unwrap_or_default();
        let v: Json = serde_json::from_str(&text).unwrap_or(Json::Null);
        let code = v["error"]["code"].as_str().unwrap_or("model_error").to_string();
        let end = if executed {
            End::failed(status, &code, Some((status, text.clone())))
        } else {
            End::released(status, &code)
        };
        exec::end(env, &a, &end).await;
        headers.extend(if executed { quota } else { given_back });
        if let Some(r) = res.headers().get("Retry-After").ok().flatten() {
            headers.push(("Retry-After", r));
        }
        return text_answer(status, text, "application/json", &headers);
    }
    headers.extend(quota);
    if !chat.stream {
        let text = res.text().await?;
        let usage = header_json(&res, "X-Tao-Usage");
        let end = End {
            input_tokens: usage["input_tokens"].as_i64(),
            output_tokens: usage["output_tokens"].as_i64(),
            ..End::succeeded(Some((200, text.clone())))
        };
        exec::end(env, &a, &end).await;
        return text_answer(200, text, "application/json", &headers);
    }
    // a stream: watched as it passes, its end told from waitUntil
    let (tx, rx) = oneshot::channel::<End>();
    let observer = Observer::new(res.stream()?, tx, stop);
    let (env2, a2): (Env, Admitted) = (env.clone(), a);
    let task = async move {
        let end = rx.await.unwrap_or_else(|_| End {
            streamed: true,
            outcome: "cancelled",
            ..End::failed(499, "client_disconnected", None)
        });
        exec::end(&env2, &a2, &end).await;
        Ok::<_, worker::wasm_bindgen::JsValue>(worker::wasm_bindgen::JsValue::UNDEFINED)
    };
    // the runtime's own waitUntil, given a promise of the task: workers-rs's wait_until re-enters, at each poll, the
    // span that was active when it was called — this handler's, which has ended by the time the stream does, and the
    // runtime refuses an ended span (a fatal error in the module)
    let promise = worker::js_sys::futures::future_to_promise(task);
    if AsRef::<worker::worker_sys::Context>::as_ref(ctx).wait_until(&promise).is_err() {
        worker::console_error!("api {rid}: waitUntil refused: the stream's end may go untold (its lease lapses)");
    }
    let h = Headers::new();
    h.set("Content-Type", "text/event-stream; charset=utf-8")?;
    h.set("Cache-Control", "no-store")?;
    for (k, v) in &headers {
        h.set(k, v)?;
    }
    Ok(Response::from_stream(observer)?.with_headers(h))
}

/// A stream from the gateway, passed on as it comes: its events written again as they were read, the gateway's own
/// comments read and dropped.  Its end — the stream's, or the caller's leaving — is told once, through `tx`.
struct Observer {
    inner: Pin<Box<ByteStream>>,
    parser: SseParser,
    tx: Option<oneshot::Sender<End>>,
    stop: Option<AbortController>,
    input_tokens: Option<i64>,
    output_tokens: Option<i64>,
    /// what the gateway said of the end: its outcome and code
    told: Option<(bool, Option<String>)>,
    done: bool,
}

/// The API's own events, when the stream from the gateway breaks.
fn broken_event() -> Vec<u8> {
    models::sse_data(
        &json!({ "error": { "type": "unavailable", "code": "model_error", "message": "the answer was cut off" } })
            .to_string(),
    )
    .into_bytes()
}

impl Observer {
    fn new(inner: ByteStream, tx: oneshot::Sender<End>, stop: AbortController) -> Self {
        Observer {
            inner: Box::pin(inner),
            // the gateway bounds an event at 64 KiB; this side reads what it wrote, with room
            parser: SseParser::new(256 * 1024),
            tx: Some(tx),
            stop: Some(stop),
            input_tokens: None,
            output_tokens: None,
            told: None,
            done: false,
        }
    }

    fn render(&mut self, items: Vec<SseItem>) -> Vec<u8> {
        let mut out = String::new();
        for item in items {
            match item {
                SseItem::Data(d) => out.push_str(&models::sse_data(&d)),
                SseItem::Done => out.push_str("data: [DONE]\n\n"),
                SseItem::Comment(c) => {
                    if let Some(meta) = models::read_meta(&c) {
                        if let Some(u) = meta.get("usage") {
                            self.input_tokens = u.get("input_tokens").and_then(Json::as_i64).or(self.input_tokens);
                            self.output_tokens = u.get("output_tokens").and_then(Json::as_i64).or(self.output_tokens);
                        }
                        if let Some(e) = meta.get("end").and_then(Json::as_str) {
                            self.told = Some((e == "ok", meta.get("code").and_then(Json::as_str).map(String::from)));
                        }
                    }
                }
            }
        }
        out.into_bytes()
    }

    /// The stream's end, told once.
    fn close(&mut self, broke: bool) {
        self.done = true;
        self.stop = None; // ended: nothing to abort
        let (ok, code) = match (&self.told, broke) {
            (Some((ok, code)), false) => (*ok, code.clone()),
            _ => (false, Some("stream_cut".to_string())),
        };
        let end = End {
            executed: true,
            ok,
            outcome: if ok { "succeeded" } else { "failed" },
            http_status: 200,
            code,
            input_tokens: self.input_tokens,
            output_tokens: self.output_tokens,
            streamed: true,
            response: None,
        };
        if let Some(tx) = self.tx.take() {
            let _ = tx.send(end);
        }
    }
}

impl Stream for Observer {
    type Item = Result<Vec<u8>>;

    fn poll_next(self: Pin<&mut Self>, cx: &mut Poll_<'_>) -> Poll<Option<Self::Item>> {
        let this = self.get_mut();
        if this.done {
            return Poll::Ready(None);
        }
        loop {
            match this.inner.as_mut().poll_next(cx) {
                Poll::Pending => return Poll::Pending,
                Poll::Ready(Some(Ok(chunk))) => match this.parser.push(&chunk) {
                    Ok(items) => {
                        let out = this.render(items);
                        if !out.is_empty() {
                            return Poll::Ready(Some(Ok(out)));
                        }
                    }
                    Err(_) => {
                        this.close(true);
                        return Poll::Ready(Some(Ok(broken_event())));
                    }
                },
                Poll::Ready(Some(Err(_))) => {
                    this.close(true);
                    return Poll::Ready(Some(Ok(broken_event())));
                }
                Poll::Ready(None) => {
                    let out = match this.parser.finish() {
                        Ok(items) => this.render(items),
                        Err(_) => broken_event(),
                    };
                    this.close(false);
                    return Poll::Ready(if out.is_empty() { None } else { Some(Ok(out)) });
                }
            }
        }
    }
}

impl Drop for Observer {
    /// The caller left before the end: the gateway's call aborted (and with it the provider's), the end told as
    /// cancelled — counted, as every admitted request whose answer began is.
    fn drop(&mut self) {
        if let Some(stop) = self.stop.take() {
            stop.abort();
        }
        if let Some(tx) = self.tx.take() {
            let _ = tx.send(End {
                executed: true,
                ok: false,
                outcome: "cancelled",
                http_status: 499,
                code: Some("client_disconnected".into()),
                input_tokens: self.input_tokens,
                output_tokens: self.output_tokens,
                streamed: true,
                response: None,
            });
        }
    }
}
