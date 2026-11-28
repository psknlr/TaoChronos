//! 模型 — the models the developer API offers, and what passes between a developer's program and a model's provider:
//! the request, read strictly (a documented subset of Chat Completions); the same request in the provider's terms; and
//! the answer — whole, or as a stream of server-sent events — put back in the API's: the public model's name, the API's
//! request id, nothing of the provider's own fields (docs/adr/0039-model-relay-and-daily-allowance.md).  Shared by the
//! API Worker, which reads and admits a request, and the private model gateway, which asks the provider.
//!
//! What is changed of an answer is changed by its known fields only, on the parsed event: its top-level `model` and
//! `id`, the provider's own keys, the reasoning's format names.  A tool call's arguments are text the model wrote and
//! are passed on byte for byte, whatever they hold.

use serde_json::{Map, Value as Json, json};

use crate::accounts::Refusal;
use crate::codec::hex;
use crate::crypto::sha256;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Provider {
    /// MiniMax's OpenAI-compatible chat completions (the default service's model, as the website's relay asks it)
    MiniMax,
    /// OpenAI's chat completions
    OpenAI,
}

impl Provider {
    pub fn name(self) -> &'static str {
        match self {
            Provider::MiniMax => "minimax",
            Provider::OpenAI => "openai",
        }
    }
}

/// A model as the API offers it.
#[derive(Debug, Clone, PartialEq)]
pub struct ModelSpec {
    /// its public id: the only name a developer sees
    pub id: &'static str,
    pub provider: Provider,
    /// the provider's model, unless the gateway's configuration names another
    pub upstream: &'static str,
    pub tools: bool,
    /// the provider's prefix of reasoning formats, shown as `Tao-` (MiniMax's `reasoning_details`)
    pub reasoning_prefix: Option<&'static str>,
    /// output tokens: given when none are asked, the most that may be asked, the least the provider accepts
    pub default_output: i64,
    pub max_output: i64,
    pub min_output: i64,
    /// the temperatures it takes (least, most), or None: it takes none (a reasoning model's own)
    pub temperature: Option<(f64, f64)>,
    /// the model's configuration, as a request's digest names it (a repeat of an Idempotency-Key under another
    /// configuration is another request)
    pub version: &'static str,
}

/// The reasoning's format names as a developer sees them.
pub const PUBLIC_FORMAT: &str = "Tao-";

/// Every model the service knows.  Which are offered is the deployment's choice (`MODELS`).
pub const KNOWN: &[ModelSpec] = &[
    ModelSpec {
        id: "Tao-R1",
        provider: Provider::MiniMax,
        upstream: "MiniMax-M3",
        tools: true,
        reasoning_prefix: Some("MiniMax-"),
        default_output: 4096,
        max_output: 8192,
        min_output: 1,
        // MiniMax-M3 takes (0, 1]: 0 is asked of it as the least it takes (upstream_request)
        temperature: Some((0.0, 1.0)),
        version: "tao-r1.2",
    },
    ModelSpec {
        id: "gpt-6-luna",
        provider: Provider::OpenAI,
        upstream: "gpt-6-luna",
        tools: true,
        reasoning_prefix: None,
        default_output: 4096,
        max_output: 8192,
        // a reasoning model refuses a smaller output cap (the relay's OPENAI_MIN_OUTPUT)
        min_output: 2048,
        // nor does it take a temperature (the relay drops it)
        temperature: None,
        version: "gpt-6-luna.2",
    },
];

pub fn find(id: &str) -> Option<&'static ModelSpec> {
    KNOWN.iter().find(|m| m.id == id)
}

/// The models a deployment offers: the known ones its `MODELS` names (comma-separated), in that order.
pub fn offered(list: &str) -> Vec<&'static ModelSpec> {
    let mut out: Vec<&'static ModelSpec> = Vec::new();
    for id in list.split(',').map(str::trim).filter(|s| !s.is_empty()) {
        if let Some(m) = find(id)
            && !out.contains(&m)
        {
            out.push(m);
        }
    }
    out
}

/// A model as `GET /v1/models` lists it.
pub fn listed(m: &ModelSpec) -> Json {
    json!({
        "id": m.id, "object": "model", "owned_by": "taochronos",
        "capabilities": { "streaming": true, "tools": m.tools, "reasoning": m.reasoning_prefix.is_some() },
        "limits": { "max_output_tokens": m.max_output, "default_output_tokens": m.default_output, "max_messages": MOST_MESSAGES },
    })
}

pub const MOST_MESSAGES: usize = 64;
pub const MOST_TOOLS: usize = 32;
pub const MOST_TOOL_CALLS: usize = 32;
pub const MOST_STOPS: usize = 4;
pub const MOST_REASONING_DETAILS: usize = 64;
/// The least temperature MiniMax takes (it refuses 0).
const MINIMAX_LEAST_TEMPERATURE: f64 = 0.01;
/// Fields of an assistant's message that an SDK writes back as they came — empty, since this API never fills them —
/// taken so, and not sent on.
const ECHOED_EMPTY: [&str; 4] = ["refusal", "annotations", "audio", "function_call"];

fn bad(code: &'static str, message: impl Into<String>) -> Refusal {
    Refusal { status: 400, kind: "invalid_request", code, message: message.into(), retry: None }
}

/// A chat request, read: what is sent on, what it asked of the answer.
#[derive(Debug, Clone, PartialEq)]
pub struct ChatRequest {
    pub model: &'static ModelSpec,
    /// the request as read: its fields, nothing else, the defaults written in
    pub body: Json,
    pub stream: bool,
    /// the caller asked for the usage in the stream (`stream_options.include_usage`)
    pub include_usage: bool,
    pub max_output: i64,
}

fn obj<'a>(v: &'a Json, what: &str) -> Result<&'a Map<String, Json>, Refusal> {
    v.as_object().ok_or_else(|| bad("type", format!("{what} is an object")))
}

fn only(o: &Map<String, Json>, allowed: &[&str], what: &str) -> Result<(), Refusal> {
    match o.keys().find(|k| !allowed.contains(&k.as_str())) {
        Some(extra) => {
            Err(bad("unsupported_field", format!("{what} takes no field {extra} (it takes: {})", allowed.join(", "))))
        }
        None => Ok(()),
    }
}

fn string<'a>(v: &'a Json, what: &str, most: usize) -> Result<&'a str, Refusal> {
    let s = v.as_str().ok_or_else(|| bad("type", format!("{what} is text")))?;
    if s.chars().count() > most {
        return Err(bad("length", format!("{what} is at most {most} characters")));
    }
    Ok(s)
}

fn function_name(v: &Json, what: &str) -> Result<String, Refusal> {
    let s = string(v, what, 64)?;
    if s.is_empty() || !s.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-') {
        return Err(bad("value", format!("{what} is 1–64 letters, digits, _ or -")));
    }
    Ok(s.to_string())
}

/// A message's content: text, or a list of text parts (no images, no files).
fn content(v: &Json, what: &str, may_be_null: bool) -> Result<(), Refusal> {
    match v {
        Json::Null if may_be_null => Ok(()),
        Json::String(_) => Ok(()),
        Json::Array(parts) if !parts.is_empty() => {
            for p in parts {
                let o = obj(p, "a content part")?;
                if o.get("type").and_then(Json::as_str) != Some("text") || !o.get("text").is_some_and(Json::is_string) {
                    return Err(bad(
                        "unsupported_content",
                        format!("{what}: only text parts are taken ({{\"type\":\"text\",\"text\":…}})"),
                    ));
                }
                only(o, &["type", "text"], "a content part")?;
            }
            Ok(())
        }
        _ => Err(bad("type", format!("{what} is text or a list of text parts"))),
    }
}

fn message(m: &Json, i: usize, spec: &ModelSpec) -> Result<(), Refusal> {
    let what = format!("messages[{i}]");
    let o = obj(m, &what)?;
    let role = o.get("role").and_then(Json::as_str).ok_or_else(|| bad("field", format!("{what} has no role")))?;
    match role {
        "system" | "user" => {
            only(o, &["role", "content", "name"], &what)?;
            content(o.get("content").unwrap_or(&Json::Null), &what, false)?;
        }
        "assistant" => {
            only(
                o,
                &[
                    "role",
                    "content",
                    "name",
                    "tool_calls",
                    "reasoning_details",
                    "refusal",
                    "annotations",
                    "audio",
                    "function_call",
                ],
                &what,
            )?;
            // an answer's message given back as an SDK writes it: fields of the protocol this API never fills, empty
            for k in ECHOED_EMPTY {
                if o.get(k).is_some_and(|v| !(v.is_null() || v.as_array().is_some_and(Vec::is_empty))) {
                    return Err(bad("unsupported_field", format!("{what}.{k} is taken empty only (null)")));
                }
            }
            let calls = o.get("tool_calls").filter(|c| !c.is_null());
            content(o.get("content").unwrap_or(&Json::Null), &what, calls.is_some())?;
            if let Some(calls) = calls {
                if !spec.tools {
                    return Err(bad("unsupported_field", format!("{} takes no tool calls", spec.id)));
                }
                let list =
                    calls.as_array().filter(|l| !l.is_empty() && l.len() <= MOST_TOOL_CALLS).ok_or_else(|| {
                        bad("length", format!("{what}.tool_calls is a list of 1–{MOST_TOOL_CALLS} calls"))
                    })?;
                for (j, c) in list.iter().enumerate() {
                    let cw = format!("{what}.tool_calls[{j}]");
                    let co = obj(c, &cw)?;
                    only(co, &["id", "type", "function"], &cw)?;
                    string(co.get("id").unwrap_or(&Json::Null), &format!("{cw}.id"), 128)?;
                    if co.get("type").and_then(Json::as_str) != Some("function") {
                        return Err(bad("value", format!("{cw}.type is function")));
                    }
                    let f = obj(co.get("function").unwrap_or(&Json::Null), &format!("{cw}.function"))?;
                    only(f, &["name", "arguments"], &format!("{cw}.function"))?;
                    function_name(f.get("name").unwrap_or(&Json::Null), &format!("{cw}.function.name"))?;
                    if !f.get("arguments").is_some_and(Json::is_string) {
                        return Err(bad(
                            "type",
                            format!("{cw}.function.arguments is text (JSON, as the model wrote it)"),
                        ));
                    }
                }
            }
            if let Some(details) = o.get("reasoning_details").filter(|d| !d.is_null()) {
                let list = details.as_array().filter(|l| l.len() <= MOST_REASONING_DETAILS).ok_or_else(|| {
                    bad("type", format!("{what}.reasoning_details is a list of at most {MOST_REASONING_DETAILS} objects, as the answer gave them"))
                })?;
                if spec.reasoning_prefix.is_none() || !list.iter().all(Json::is_object) {
                    return Err(bad(
                        "unsupported_field",
                        format!("{what}.reasoning_details is taken by a model that reasons, as its answer gave them"),
                    ));
                }
            }
        }
        "tool" => {
            only(o, &["role", "content", "tool_call_id"], &what)?;
            string(o.get("tool_call_id").unwrap_or(&Json::Null), &format!("{what}.tool_call_id"), 128)?;
            content(o.get("content").unwrap_or(&Json::Null), &what, false)?;
        }
        _ => return Err(bad("value", format!("{what}.role is system, user, assistant or tool"))),
    }
    if let Some(n) = o.get("name") {
        function_name(n, &format!("{what}.name"))?;
    }
    Ok(())
}

fn number(v: &Json, what: &str, least: f64, most: f64, open_low: bool) -> Result<f64, Refusal> {
    let n = v.as_f64().ok_or_else(|| bad("type", format!("{what} is a number")))?;
    let low_ok = if open_low { n > least } else { n >= least };
    if !low_ok || n > most {
        let low = if open_low { format!("above {least}") } else { format!("from {least}") };
        return Err(bad("range", format!("{what} is {low} to {most}")));
    }
    Ok(n)
}

/// A chat request read strictly: the subset of Chat Completions the API takes, and nothing else; a field it does not
/// know is refused, not ignored, and a value past its limit is refused, not clamped (api.rs's rule).  `offered`: the
/// models this deployment offers; `cap`: the most output tokens any request may ask.
pub fn read_chat(body: &[u8], offered: &[&'static ModelSpec], cap: i64) -> Result<ChatRequest, Refusal> {
    let v: Json = serde_json::from_slice(body).map_err(|_| bad("json", "the body is not JSON"))?;
    let o = obj(&v, "the body")?;
    only(
        o,
        &[
            "model",
            "messages",
            "stream",
            "stream_options",
            "max_tokens",
            "max_completion_tokens",
            "temperature",
            "top_p",
            "stop",
            "tools",
            "tool_choice",
            "n",
        ],
        "chat.completions",
    )?;
    let id =
        o.get("model").and_then(Json::as_str).ok_or_else(|| bad("field", "model names a model (GET /v1/models)"))?;
    let spec = offered.iter().copied().find(|m| m.id == id).ok_or_else(|| Refusal {
        status: 404,
        kind: "not_found",
        code: "model_not_found",
        message: format!("no model {id} is offered (GET /v1/models lists them)"),
        retry: None,
    })?;
    let messages = o
        .get("messages")
        .and_then(Json::as_array)
        .filter(|m| !m.is_empty() && m.len() <= MOST_MESSAGES)
        .ok_or_else(|| bad("length", format!("messages is a list of 1–{MOST_MESSAGES} messages")))?;
    for (i, m) in messages.iter().enumerate() {
        message(m, i, spec)?;
    }
    let stream = match o.get("stream") {
        None | Some(Json::Null) => false,
        Some(Json::Bool(b)) => *b,
        Some(_) => return Err(bad("type", "stream is true or false")),
    };
    let mut include_usage = false;
    if let Some(so) = o.get("stream_options").filter(|s| !s.is_null()) {
        if !stream {
            return Err(bad("field", "stream_options is taken with stream: true"));
        }
        let so = obj(so, "stream_options")?;
        only(so, &["include_usage"], "stream_options")?;
        include_usage = match so.get("include_usage") {
            None => false,
            Some(Json::Bool(b)) => *b,
            Some(_) => return Err(bad("type", "stream_options.include_usage is true or false")),
        };
    }
    let given = |k: &str| o.get(k).is_some_and(|v| !v.is_null());
    if given("max_tokens") && given("max_completion_tokens") {
        return Err(bad("field", "max_tokens and max_completion_tokens are one limit: send one"));
    }
    let most = spec.max_output.min(cap.max(1));
    let max_output = match o.get("max_completion_tokens").or_else(|| o.get("max_tokens")).filter(|v| !v.is_null()) {
        None => spec.default_output.min(most),
        Some(n) => n.as_i64().filter(|n| (1..=most).contains(n)).ok_or_else(|| {
            bad("range", format!("the output limit is a whole number from 1 to {most} tokens for {}", spec.id))
        })?,
    };
    let mut out = Map::new();
    out.insert("model".into(), json!(spec.id));
    // the messages as they came, less what an SDK writes empty in an answer it is given back
    let mut sent = messages.clone();
    for m in sent.iter_mut() {
        if let Some(mo) = m.as_object_mut() {
            for k in ECHOED_EMPTY {
                mo.remove(k);
            }
        }
    }
    out.insert("messages".into(), Json::Array(sent));
    out.insert("stream".into(), json!(stream));
    if include_usage {
        out.insert("stream_options".into(), json!({ "include_usage": true }));
    }
    out.insert("max_completion_tokens".into(), json!(max_output));
    if let Some(t) = o.get("temperature").filter(|v| !v.is_null()) {
        let Some((least, most)) = spec.temperature else {
            return Err(bad("unsupported_field", format!("{} takes no temperature", spec.id)));
        };
        out.insert("temperature".into(), json!(number(t, "temperature", least, most, false)?));
    }
    if let Some(p) = o.get("top_p").filter(|v| !v.is_null()) {
        out.insert("top_p".into(), json!(number(p, "top_p", 0.0, 1.0, true)?));
    }
    if let Some(n) = o.get("n").filter(|v| !v.is_null())
        && n.as_i64() != Some(1)
    {
        return Err(bad("range", "n is 1: one answer a request"));
    }
    if let Some(stop) = o.get("stop").filter(|v| !v.is_null()) {
        let list: Vec<&Json> = match stop {
            Json::String(_) => vec![stop],
            Json::Array(a) if !a.is_empty() && a.len() <= MOST_STOPS => a.iter().collect(),
            _ => return Err(bad("type", format!("stop is text or a list of 1–{MOST_STOPS} texts"))),
        };
        for s in &list {
            if string(s, "a stop sequence", 64)?.is_empty() {
                return Err(bad("length", "a stop sequence is 1–64 characters"));
            }
        }
        out.insert("stop".into(), stop.clone());
    }
    let mut tool_names: Vec<String> = Vec::new();
    if let Some(tools) = o.get("tools").filter(|v| !v.is_null()) {
        if !spec.tools {
            return Err(bad("unsupported_field", format!("{} takes no tools", spec.id)));
        }
        let list = tools
            .as_array()
            .filter(|l| !l.is_empty() && l.len() <= MOST_TOOLS)
            .ok_or_else(|| bad("length", format!("tools is a list of 1–{MOST_TOOLS} tools")))?;
        for (i, t) in list.iter().enumerate() {
            let what = format!("tools[{i}]");
            let to = obj(t, &what)?;
            only(to, &["type", "function"], &what)?;
            if to.get("type").and_then(Json::as_str) != Some("function") {
                return Err(bad("value", format!("{what}.type is function")));
            }
            let f = obj(to.get("function").unwrap_or(&Json::Null), &format!("{what}.function"))?;
            only(f, &["name", "description", "parameters", "strict"], &format!("{what}.function"))?;
            let name = function_name(f.get("name").unwrap_or(&Json::Null), &format!("{what}.function.name"))?;
            if tool_names.contains(&name) {
                return Err(bad("value", format!("{what}.function.name {name} is named twice")));
            }
            tool_names.push(name);
            if let Some(d) = f.get("description") {
                string(d, &format!("{what}.function.description"), 1024)?;
            }
            if f.get("parameters").is_some_and(|p| !p.is_object()) {
                return Err(bad("type", format!("{what}.function.parameters is a JSON Schema object")));
            }
            if f.get("strict").is_some_and(|s| !s.is_boolean()) {
                return Err(bad("type", format!("{what}.function.strict is true or false")));
            }
        }
        out.insert("tools".into(), tools.clone());
    }
    if let Some(choice) = o.get("tool_choice").filter(|v| !v.is_null()) {
        if tool_names.is_empty() {
            return Err(bad("field", "tool_choice is taken with tools"));
        }
        match choice {
            Json::String(s) if matches!(s.as_str(), "none" | "auto" | "required") => {}
            Json::Object(c) => {
                only(c, &["type", "function"], "tool_choice")?;
                let f = c.get("function").and_then(Json::as_object);
                if let Some(f) = f {
                    only(f, &["name"], "tool_choice.function")?;
                }
                let name = f.and_then(|f| f.get("name")).and_then(Json::as_str).unwrap_or("");
                if c.get("type").and_then(Json::as_str) != Some("function") || !tool_names.iter().any(|n| n == name) {
                    return Err(bad(
                        "value",
                        "tool_choice names one of the tools: {\"type\":\"function\",\"function\":{\"name\":…}}",
                    ));
                }
            }
            _ => return Err(bad("value", "tool_choice is none, auto, required, or a tool named")),
        }
        out.insert("tool_choice".into(), choice.clone());
    }
    Ok(ChatRequest { model: spec, body: Json::Object(out), stream, include_usage, max_output })
}

/// What an Idempotency-Key is checked against: the method, the path, the request as read (its keys in order, its
/// messages as they were), the model resolved and its configuration.
pub fn request_hash(method: &str, path: &str, body: &Json, model: Option<&ModelSpec>) -> String {
    let m = model.map(|m| format!("{}@{}", m.id, m.version)).unwrap_or_default();
    hex(&sha256(format!("{method}\n{path}\n{m}\n{body}").as_bytes()))
}

// ------------------------------------------------------------------ to the provider
/// A message's content as one text (a provider that takes text only: the parts joined).
fn flat(content: &Json) -> Json {
    match content {
        Json::Array(parts) => {
            json!(parts.iter().filter_map(|p| p.get("text").and_then(Json::as_str)).collect::<Vec<_>>().join("\n"))
        }
        other => other.clone(),
    }
}

/// The request as the provider is asked it: its model, its output limit in the provider's field (at least the least
/// it takes), its own fields, the reasoning of the turns before under its own format names — and a stream asked to
/// report its usage, so that what an answer cost is known.
pub fn upstream_request(req: &ChatRequest, upstream_model: &str) -> Json {
    let spec = req.model;
    let mut b = req.body.clone();
    let o = b.as_object_mut().expect("read_chat writes an object");
    o.insert("model".into(), json!(upstream_model));
    o.insert("max_completion_tokens".into(), json!(req.max_output.max(spec.min_output)));
    o.remove("stream_options");
    match spec.provider {
        Provider::MiniMax => {
            o.insert("reasoning_split".into(), json!(true));
            // its temperature is above 0: a request for none of its randomness is asked with the least it takes
            if o.get("temperature").and_then(Json::as_f64).is_some_and(|t| t < MINIMAX_LEAST_TEMPERATURE) {
                o.insert("temperature".into(), json!(MINIMAX_LEAST_TEMPERATURE));
            }
            if let Some(Json::Array(ms)) = o.get_mut("messages") {
                for m in ms.iter_mut() {
                    if let Some(c) = m.get("content").cloned() {
                        m["content"] = flat(&c);
                    }
                    if let (Some(prefix), Some(Json::Array(details))) =
                        (spec.reasoning_prefix, m.get_mut("reasoning_details"))
                    {
                        for d in details.iter_mut() {
                            if let Some(f) =
                                d.get("format").and_then(Json::as_str).and_then(|f| f.strip_prefix(PUBLIC_FORMAT))
                            {
                                d["format"] = json!(format!("{prefix}{f}"));
                            }
                        }
                    }
                }
            }
        }
        Provider::OpenAI => {
            if req.stream {
                o.insert("stream_options".into(), json!({ "include_usage": true }));
            }
        }
    }
    b
}

// ------------------------------------------------------------------ from the provider
/// What a provider's failure is, as the API tells it.  `executed`: whether the provider may have run the request — a
/// request it refused outright ran nothing, and spends no one's allowance.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Failure {
    pub status: u16,
    pub code: &'static str,
    pub message: &'static str,
    pub executed: bool,
    pub retry: Option<i64>,
}

impl Failure {
    pub fn refusal(&self) -> Refusal {
        Refusal {
            status: self.status,
            kind: if self.status == 429 { "rate_limit" } else { "unavailable" },
            code: self.code,
            message: self.message.into(),
            retry: self.retry,
        }
    }
}

pub const UNAVAILABLE: Failure = Failure {
    status: 503,
    code: "model_unavailable",
    message: "the model service is unavailable now; nothing was counted — try again later",
    executed: false,
    retry: Some(60),
};
pub const BUSY: Failure = Failure {
    status: 429,
    code: "model_busy",
    message: "the model service is busy; nothing was counted — try again shortly",
    executed: false,
    retry: Some(10),
};
pub const REJECTED: Failure = Failure {
    status: 400,
    code: "model_rejected",
    message: "the model service could not take this request (its size or its parameters); nothing was counted",
    executed: false,
    retry: None,
};
pub const FAILED: Failure = Failure {
    status: 502,
    code: "model_error",
    message: "the model service failed while it answered",
    executed: true,
    retry: None,
};
pub const TIMEOUT: Failure = Failure {
    status: 504,
    code: "model_timeout",
    message: "the model service did not answer in time",
    executed: true,
    retry: None,
};
/// The connection to the provider failed — before it took the request, or after: which is not known, and a request
/// that may have run is counted (docs/adr/0039-model-relay-and-daily-allowance.md).
pub const LOST: Failure = Failure {
    status: 502,
    code: "model_error",
    message: "the connection to the model service failed; whether it took the request is not known, and it was counted",
    executed: true,
    retry: None,
};
/// An answer, whole or streamed, past what the API passes on.
pub const TOO_LARGE: Failure = Failure {
    status: 502,
    code: "response_too_large",
    message: "the answer was larger than the API passes on",
    executed: true,
    retry: None,
};

/// A provider's HTTP refusal, as the API tells it (its own words are never passed on: they name it and its models).
pub fn failure_of(status: u16, provider_code: &str) -> Failure {
    match status {
        401 | 403 => UNAVAILABLE, // its key refused, or the place the call left from (unsupported_country_region_territory)
        429 if provider_code == "insufficient_quota" => UNAVAILABLE,
        429 => BUSY,
        400 | 404 | 409 | 413 | 422 => REJECTED,
        _ => FAILED,
    }
}

/// MiniMax reports some failures inside a 200's `base_resp` (the relay's BASE_RESP).
fn base_resp_failure(code: i64) -> Failure {
    match code {
        1004 | 2049 | 1008 => UNAVAILABLE,
        1002 | 1039 => BUSY,
        _ => FAILED,
    }
}

/// What an answer, or one event of a stream, told of itself.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Seen {
    pub input_tokens: Option<i64>,
    pub output_tokens: Option<i64>,
    pub failure: Option<Failure>,
    /// an event that carried the usage alone, which the caller did not ask for: not to be passed on
    pub drop: bool,
    pub finish_reason: Option<String>,
}

/// What of an answer the API passes on — the protocol's own fields, the ones a developer's next request may give back
/// (`read_chat`) — and nothing else: a provider's other keys (its moderation flags, its fingerprints, its own names for
/// the reasoning, its billing) would name it, and be refused when given back.
const ANSWER_KEYS: [&str; 6] = ["id", "object", "created", "model", "choices", "usage"];
const CHOICE_KEYS: [&str; 4] = ["index", "message", "delta", "finish_reason"];
const MESSAGE_KEYS: [&str; 4] = ["role", "content", "tool_calls", "reasoning_details"];
const TOOL_CALL_KEYS: [&str; 4] = ["index", "id", "type", "function"];
const FUNCTION_KEYS: [&str; 2] = ["name", "arguments"];
const USAGE_KEYS: [&str; 3] = ["prompt_tokens", "completion_tokens", "total_tokens"];

fn keep(v: &mut Json, keys: &[&str]) {
    if let Some(o) = v.as_object_mut() {
        o.retain(|k, _| keys.contains(&k.as_str()));
    }
}

fn rename_formats(v: &mut Json, prefix: &str) {
    if let Some(Json::Array(details)) = v.get_mut("reasoning_details") {
        for d in details.iter_mut() {
            if let Some(rest) = d.get("format").and_then(Json::as_str).and_then(|f| f.strip_prefix(prefix)) {
                d["format"] = json!(format!("{PUBLIC_FORMAT}{rest}"));
            }
        }
    }
}

/// A message, or a stream's delta, as the API passes it on: its role, its text, its tool calls (their protocol's
/// fields), its reasoning under the API's format names.
fn message_out(m: &mut Json, spec: &ModelSpec) {
    keep(m, &MESSAGE_KEYS);
    if let Some(Json::Array(calls)) = m.get_mut("tool_calls") {
        for c in calls.iter_mut() {
            keep(c, &TOOL_CALL_KEYS);
            if let Some(f) = c.get_mut("function") {
                keep(f, &FUNCTION_KEYS);
            }
        }
    }
    match spec.reasoning_prefix {
        Some(prefix) => rename_formats(m, prefix),
        None => {
            if let Some(o) = m.as_object_mut() {
                o.remove("reasoning_details");
            }
        }
    }
}

/// An answer (`chat.completion`) or one event of a stream (`chat.completion.chunk`) in the API's terms, in place:
/// the public model and the API's request id, only the protocol's fields (`ANSWER_KEYS` and below), the reasoning's
/// formats renamed, the usage read (and dropped when the caller did not ask for it in a stream).
pub fn normalize(v: &mut Json, spec: &ModelSpec, request_id: &str, keep_usage: bool) -> Seen {
    let mut seen = Seen::default();
    let Some(o) = v.as_object_mut() else {
        seen.failure = Some(FAILED);
        return seen;
    };
    if let Some(code) = o.get("base_resp").and_then(|b| b.get("status_code")).and_then(Json::as_i64).filter(|c| *c != 0)
    {
        seen.failure = Some(base_resp_failure(code));
        return seen;
    }
    if o.get("error").is_some_and(|e| !e.is_null()) {
        seen.failure = Some(FAILED);
        return seen;
    }
    o.retain(|k, _| ANSWER_KEYS.contains(&k.as_str()));
    if o.contains_key("model") || o.contains_key("choices") {
        o.insert("model".into(), json!(spec.id));
    }
    if o.contains_key("id") {
        o.insert("id".into(), json!(request_id));
    }
    if let Some(Json::Array(choices)) = o.get_mut("choices") {
        for c in choices.iter_mut() {
            keep(c, &CHOICE_KEYS);
            if let Some(r) = c.get("finish_reason").and_then(Json::as_str) {
                seen.finish_reason = Some(r.to_string());
            }
            for part in ["delta", "message"] {
                if let Some(p) = c.get_mut(part) {
                    message_out(p, spec);
                }
            }
        }
    }
    if let Some(u) = o.get_mut("usage").filter(|u| u.is_object()) {
        seen.input_tokens = u.get("prompt_tokens").and_then(Json::as_i64);
        seen.output_tokens = u.get("completion_tokens").and_then(Json::as_i64);
        keep(u, &USAGE_KEYS);
    }
    let is_chunk = o.get("object").and_then(Json::as_str) == Some("chat.completion.chunk");
    if is_chunk && !keep_usage && o.contains_key("usage") {
        o.remove("usage");
        if o.get("choices").and_then(Json::as_array).is_none_or(|c| c.is_empty()) {
            seen.drop = true;
        }
    }
    seen
}

// ------------------------------------------------------------------ server-sent events
/// One thing a stream said.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SseItem {
    /// an event's data (its `data:` lines, joined)
    Data(String),
    /// a comment line's text (after the colon)
    Comment(String),
    /// `data: [DONE]`
    Done,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SseError {
    /// an event, or a line, past the limit
    TooLarge,
}

/// A stream of server-sent events read as it arrives: lines ended by CRLF, LF or CR, an event's `data:` lines joined,
/// comments kept apart, a character split between two chunks read whole (a line is decoded only when it has ended).
/// Bounded: an event, or a line still without its end, of more than `most` bytes is refused.
#[derive(Debug)]
pub struct SseParser {
    pending: Vec<u8>,
    data: Option<String>,
    most: usize,
    /// a CR ended the last line: an LF that comes first in the next chunk is its pair, not an empty line
    after_cr: bool,
    /// a line has been read: a byte order mark the stream begins with is behind
    begun: bool,
}

impl SseParser {
    pub fn new(most: usize) -> Self {
        SseParser { pending: Vec::new(), data: None, most, after_cr: false, begun: false }
    }

    fn line(&mut self, line: &[u8], out: &mut Vec<SseItem>) -> Result<(), SseError> {
        // the stream's first line may begin with a byte order mark, which is not the line's (the protocol's own rule)
        let line = if self.begun {
            line
        } else {
            self.begun = true;
            line.strip_prefix(b"\xEF\xBB\xBF".as_slice()).unwrap_or(line)
        };
        if line.is_empty() {
            if let Some(d) = self.data.take() {
                out.push(if d == "[DONE]" { SseItem::Done } else { SseItem::Data(d) });
            }
            return Ok(());
        }
        let text = String::from_utf8_lossy(line);
        if let Some(c) = text.strip_prefix(':') {
            out.push(SseItem::Comment(c.strip_prefix(' ').unwrap_or(c).to_string()));
            return Ok(());
        }
        let (field, value) = match text.find(':') {
            Some(i) => (&text[..i], text[i + 1..].strip_prefix(' ').unwrap_or(&text[i + 1..])),
            None => (&text[..], ""),
        };
        if field == "data" {
            // an event's data lines are joined with a newline between them (the first may be empty)
            match &mut self.data {
                Some(d) => {
                    d.push('\n');
                    d.push_str(value);
                }
                None => self.data = Some(value.to_string()),
            }
            if self.data.as_ref().is_some_and(|d| d.len() > self.most) {
                return Err(SseError::TooLarge);
            }
        }
        // event:, id:, retry: and anything else: not used here
        Ok(())
    }

    /// What `chunk` completes.
    pub fn push(&mut self, chunk: &[u8]) -> Result<Vec<SseItem>, SseError> {
        let mut out = Vec::new();
        let mut start = 0;
        let mut i = 0;
        let bytes = chunk;
        if bytes.is_empty() {
            return Ok(out); // nothing: a CR that ended the last chunk still waits for its LF
        }
        if self.after_cr && bytes.first() == Some(&b'\n') {
            start = 1;
            i = 1;
        }
        self.after_cr = false;
        while i < bytes.len() {
            match bytes[i] {
                b'\n' | b'\r' => {
                    let mut line = std::mem::take(&mut self.pending);
                    line.extend_from_slice(&bytes[start..i]);
                    if line.len() > self.most {
                        return Err(SseError::TooLarge);
                    }
                    self.line(&line, &mut out)?;
                    if bytes[i] == b'\r' {
                        if i + 1 < bytes.len() {
                            if bytes[i + 1] == b'\n' {
                                i += 1;
                            }
                        } else {
                            self.after_cr = true;
                        }
                    }
                    start = i + 1;
                }
                _ => {}
            }
            i += 1;
        }
        self.pending.extend_from_slice(&bytes[start..]);
        if self.pending.len() > self.most {
            return Err(SseError::TooLarge);
        }
        Ok(out)
    }

    /// The stream's end: a last line without its end, and an event without its blank line, are read.
    pub fn finish(&mut self) -> Result<Vec<SseItem>, SseError> {
        let mut out = Vec::new();
        if !self.pending.is_empty() {
            let line = std::mem::take(&mut self.pending);
            self.line(&line, &mut out)?;
        }
        self.line(&[], &mut out)?;
        Ok(out)
    }
}

/// One event as the API writes it.
pub fn sse_data(data: &str) -> String {
    format!("data: {data}\n\n")
}

/// The gateway's word to the API inside a stream (a comment, which the API reads and never passes on).
pub const META: &str = "tao ";

pub fn sse_meta(v: &Json) -> String {
    format!(": {META}{v}\n\n")
}

/// A gateway's comment, read: its JSON, if it is one.
pub fn read_meta(comment: &str) -> Option<Json> {
    serde_json::from_str(comment.strip_prefix(META)?).ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn offered() -> Vec<&'static ModelSpec> {
        offered_list("Tao-R1,gpt-6-luna")
    }

    fn offered_list(s: &str) -> Vec<&'static ModelSpec> {
        super::offered(s)
    }

    fn read(body: &str) -> Result<ChatRequest, Refusal> {
        read_chat(body.as_bytes(), &offered(), 8192)
    }

    fn code(r: Result<ChatRequest, Refusal>) -> &'static str {
        r.err().map(|e| e.code).unwrap_or("ok")
    }

    #[test]
    fn a_chat_request_is_read_strictly_with_its_defaults_written_in() {
        let r = read(r#"{"model":"Tao-R1","messages":[{"role":"user","content":"桂枝汤主治？"}]}"#).unwrap();
        assert_eq!((r.model.id, r.stream, r.include_usage, r.max_output), ("Tao-R1", false, false, 4096));
        assert_eq!(r.body["max_completion_tokens"], 4096);
        assert_eq!(r.body["stream"], false);
        let s = read(r#"{"model":"Tao-R1","stream":true,"stream_options":{"include_usage":true},"max_tokens":100,"messages":[{"role":"user","content":[{"type":"text","text":"a"},{"type":"text","text":"b"}]}]}"#).unwrap();
        assert!(s.stream && s.include_usage && s.max_output == 100);
        assert!(s.body.get("max_tokens").is_none(), "one field for the limit: max_completion_tokens");
        for (body, want) in [
            (r#"{"model":"Tao-R1","messages":[{"role":"user","content":"x"}],"user":"me"}"#, "unsupported_field"),
            (r#"{"model":"Tao-R9","messages":[{"role":"user","content":"x"}]}"#, "model_not_found"),
            (r#"{"messages":[{"role":"user","content":"x"}]}"#, "field"),
            (r#"{"model":"Tao-R1","messages":[]}"#, "length"),
            (r#"{"model":"Tao-R1","messages":[{"role":"robot","content":"x"}]}"#, "value"),
            (
                r#"{"model":"Tao-R1","messages":[{"role":"user","content":[{"type":"image_url","image_url":{"url":"x"}}]}]}"#,
                "unsupported_content",
            ),
            (r#"{"model":"Tao-R1","messages":[{"role":"user","content":"x","extra":1}]}"#, "unsupported_field"),
            (r#"{"model":"Tao-R1","messages":[{"role":"tool","content":"x"}]}"#, "type"),
            (r#"{"model":"Tao-R1","messages":[{"role":"user","content":"x"}],"max_tokens":9000}"#, "range"),
            (r#"{"model":"Tao-R1","messages":[{"role":"user","content":"x"}],"max_tokens":0}"#, "range"),
            (
                r#"{"model":"Tao-R1","messages":[{"role":"user","content":"x"}],"max_tokens":5,"max_completion_tokens":5}"#,
                "field",
            ),
            (r#"{"model":"Tao-R1","messages":[{"role":"user","content":"x"}],"n":2}"#, "range"),
            (
                r#"{"model":"Tao-R1","messages":[{"role":"user","content":"x"}],"stream_options":{"include_usage":true}}"#,
                "field",
            ),
            (r#"{"model":"Tao-R1","messages":[{"role":"user","content":"x"}],"temperature":3}"#, "range"),
            (r#"{"model":"Tao-R1","messages":[{"role":"user","content":"x"}],"top_p":0}"#, "range"),
            (r#"{"model":"Tao-R1","messages":[{"role":"user","content":"x"}],"stop":["a","b","c","d","e"]}"#, "type"),
            (r#"{"model":"Tao-R1","messages":[{"role":"user","content":"x"}],"tool_choice":"auto"}"#, "field"),
            (
                r#"{"model":"Tao-R1","messages":[{"role":"user","content":"x"}],"tools":[{"type":"function","function":{"name":"a b"}}]}"#,
                "value",
            ),
        ] {
            assert_eq!(code(read(body)), want, "{body}");
        }
        // the deployment's cap is below the model's own
        assert_eq!(
            code(read_chat(
                br#"{"model":"Tao-R1","messages":[{"role":"user","content":"x"}],"max_tokens":3000}"#,
                &offered(),
                2048
            )),
            "range"
        );
        // a model not offered here is not found, though the service knows it
        assert_eq!(
            code(read_chat(
                br#"{"model":"gpt-6-luna","messages":[{"role":"user","content":"x"}]}"#,
                &offered_list("Tao-R1"),
                8192
            )),
            "model_not_found"
        );
    }

    #[test]
    fn tool_calls_and_their_answers_are_taken_as_the_protocol_has_them() {
        let body = r#"{"model":"Tao-R1","messages":[
            {"role":"user","content":"find 桂枝汤"},
            {"role":"assistant","content":null,"tool_calls":[{"id":"call_1","type":"function","function":{"name":"evidence_search","arguments":"{\"query\":\"桂枝汤\",\"model\":\"MiniMax-M3\"}"}}],
             "reasoning_details":[{"type":"reasoning.text","text":"…","format":"Tao-reasoning-v1"}]},
            {"role":"tool","tool_call_id":"call_1","content":"[{\"passage_id\":\"shl:12\"}]"}],
          "tools":[{"type":"function","function":{"name":"evidence_search","description":"search","parameters":{"type":"object"}}}],
          "tool_choice":{"type":"function","function":{"name":"evidence_search"}}}"#;
        let r = read(body).unwrap();
        let up = upstream_request(&r, "MiniMax-M3");
        assert_eq!(up["model"], "MiniMax-M3");
        assert_eq!(up["reasoning_split"], true);
        // the reasoning given back goes under the provider's format again; the arguments stay as the model wrote them
        assert_eq!(up["messages"][1]["reasoning_details"][0]["format"], "MiniMax-reasoning-v1");
        assert_eq!(
            up["messages"][1]["tool_calls"][0]["function"]["arguments"],
            r#"{"query":"桂枝汤","model":"MiniMax-M3"}"#
        );
        assert!(up.get("stream_options").is_none());
        // a tool_choice naming no tool; reasoning given to a model that does not reason
        assert_eq!(code(read(&body.replace(r#""name":"evidence_search"}}}"#, r#""name":"other"}}}"#))), "value");
        let luna = body.replace("Tao-R1", "gpt-6-luna");
        assert_eq!(code(read(&luna)), "unsupported_field");
    }

    #[test]
    fn the_provider_is_asked_in_its_terms_and_a_stream_reports_its_usage() {
        let r = read(r#"{"model":"gpt-6-luna","stream":true,"max_tokens":100,"messages":[{"role":"user","content":[{"type":"text","text":"a"}]}]}"#).unwrap();
        let up = upstream_request(&r, "gpt-6-luna");
        assert_eq!(up["max_completion_tokens"], 2048, "at least what the provider takes");
        assert_eq!(up["stream_options"]["include_usage"], true, "asked of the provider, whatever the caller asked");
        assert!(up["messages"][0]["content"].is_array(), "a provider that takes parts is given them");
        let m = read(r#"{"model":"Tao-R1","messages":[{"role":"user","content":[{"type":"text","text":"a"},{"type":"text","text":"b"}]}]}"#).unwrap();
        assert_eq!(upstream_request(&m, "MiniMax-M3")["messages"][0]["content"], "a\nb");
    }

    #[test]
    fn a_request_hash_is_its_meaning_not_its_spelling() {
        let a = read(r#"{"model":"Tao-R1","temperature":0.5,"messages":[{"role":"user","content":"x"}]}"#).unwrap();
        let b = read(r#"{"messages":[{"content":"x","role":"user"}],"temperature":0.5,"model":"Tao-R1"}"#).unwrap();
        let c = read(r#"{"model":"Tao-R1","messages":[{"role":"user","content":"x"},{"role":"user","content":"y"}]}"#)
            .unwrap();
        let d = read(r#"{"model":"Tao-R1","messages":[{"role":"user","content":"y"},{"role":"user","content":"x"}]}"#)
            .unwrap();
        let h = |r: &ChatRequest| request_hash("POST", "/v1/chat/completions", &r.body, Some(r.model));
        assert_eq!(h(&a), h(&b));
        assert_ne!(h(&c), h(&d), "the messages' order is the request's");
        assert_ne!(h(&a), request_hash("POST", "/v1/chat/completions", &a.body, find("gpt-6-luna")));
    }

    #[test]
    fn an_answer_is_put_in_the_apis_terms_by_its_known_fields_only() {
        let spec = find("Tao-R1").unwrap();
        let mut v: Json = serde_json::from_str(r#"{"id":"0a1b2c","object":"chat.completion","model":"MiniMax-M3","created":1,
            "choices":[{"index":0,"finish_reason":"tool_calls","message":{"role":"assistant","content":"model: MiniMax-M3",
              "reasoning_details":[{"type":"reasoning.text","text":"…","format":"MiniMax-response-v1"}],
              "tool_calls":[{"id":"c1","type":"function","function":{"name":"f","arguments":"{\"model\":\"MiniMax-M3\"}"}}]},
              "input_sensitive":false}],
            "usage":{"prompt_tokens":12,"completion_tokens":34,"total_tokens":46,"total_characters":0},
            "input_sensitive":false,"output_sensitive":false,"base_resp":{"status_code":0,"status_msg":""}}"#).unwrap();
        let seen = normalize(&mut v, spec, "req_1", true);
        assert_eq!((seen.input_tokens, seen.output_tokens, seen.failure.clone()), (Some(12), Some(34), None));
        assert_eq!(seen.finish_reason.as_deref(), Some("tool_calls"));
        assert_eq!((v["model"].as_str(), v["id"].as_str()), (Some("Tao-R1"), Some("req_1")));
        let text = v.to_string();
        assert!(!text.contains("base_resp") && !text.contains("sensitive") && !text.contains("total_characters"));
        assert_eq!(v["choices"][0]["message"]["reasoning_details"][0]["format"], "Tao-response-v1");
        // what the model wrote is untouched: its text and its arguments may name anything
        assert_eq!(v["choices"][0]["message"]["content"], "model: MiniMax-M3");
        assert_eq!(v["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"], r#"{"model":"MiniMax-M3"}"#);
        // a failure inside a 200, and an error event
        let mut quota: Json =
            serde_json::from_str(r#"{"base_resp":{"status_code":1008,"status_msg":"insufficient balance"}}"#).unwrap();
        assert_eq!(normalize(&mut quota, spec, "req_2", true).failure, Some(UNAVAILABLE));
        let mut err: Json =
            serde_json::from_str(r#"{"error":{"message":"overloaded","type":"server_error"}}"#).unwrap();
        assert_eq!(normalize(&mut err, spec, "req_3", true).failure, Some(FAILED));
        // a stream's usage event the caller did not ask for is read, then dropped
        let mut last: Json = serde_json::from_str(r#"{"id":"x","object":"chat.completion.chunk","model":"gpt-6-luna","choices":[],"usage":{"prompt_tokens":5,"completion_tokens":6}}"#).unwrap();
        let s = normalize(&mut last, find("gpt-6-luna").unwrap(), "req_4", false);
        assert!(s.drop && s.output_tokens == Some(6));
        assert_eq!(failure_of(429, "insufficient_quota"), UNAVAILABLE);
        assert!(!failure_of(400, "").executed && failure_of(500, "").executed);
    }

    #[test]
    fn a_stream_is_read_the_same_however_it_is_cut() {
        let stream = "data: {\"a\":\"桂枝汤\"}\r\n\r\n: tao {\"usage\":1}\n\ndata: line one\ndata: line two\n\nevent: x\nid: 7\ndata: {\"b\":2}\r\rdata: [DONE]\n\n";
        let whole = {
            let mut p = SseParser::new(1024);
            let mut items = p.push(stream.as_bytes()).unwrap();
            items.extend(p.finish().unwrap());
            items
        };
        assert_eq!(
            whole,
            vec![
                SseItem::Data("{\"a\":\"桂枝汤\"}".into()),
                SseItem::Comment("tao {\"usage\":1}".into()),
                SseItem::Data("line one\nline two".into()),
                SseItem::Data("{\"b\":2}".into()),
                SseItem::Done,
            ]
        );
        // cut at every byte (a character's bytes apart, a CR from its LF): the same events
        let bytes = stream.as_bytes();
        for cut in 1..bytes.len() {
            let mut p = SseParser::new(1024);
            let mut items = p.push(&bytes[..cut]).unwrap();
            items.extend(p.push(&bytes[cut..]).unwrap());
            items.extend(p.finish().unwrap());
            assert_eq!(items, whole, "cut at {cut}");
        }
        // one byte at a time
        let mut p = SseParser::new(1024);
        let mut items = Vec::new();
        for b in bytes {
            items.extend(p.push(std::slice::from_ref(b)).unwrap());
        }
        items.extend(p.finish().unwrap());
        assert_eq!(items, whole);
        // an event without its blank line, at the end; an event past the limit
        let mut p = SseParser::new(1024);
        assert!(p.push(b"data: tail").unwrap().is_empty());
        assert_eq!(p.finish().unwrap(), vec![SseItem::Data("tail".into())]);
        let mut small = SseParser::new(16);
        assert_eq!(small.push(b"data: 0123456789abcdefghij\n"), Err(SseError::TooLarge));
        let mut no_end = SseParser::new(16);
        assert_eq!(no_end.push(b"data: 0123456789abcdefghij"), Err(SseError::TooLarge));
        assert_eq!(read_meta("tao {\"end\":\"ok\"}"), Some(json!({ "end": "ok" })));
        assert_eq!(read_meta("keep-alive"), None);
        assert_eq!(sse_data("{}"), "data: {}\n\n");
    }

    #[test]
    fn what_an_answer_holds_beyond_the_protocol_is_not_passed_on_and_what_is_passed_on_may_be_given_back() {
        let spec = find("Tao-R1").unwrap();
        // the provider's keys inside the message, its tool calls and its usage
        let mut v: Json = serde_json::from_str(r#"{"id":"0a","object":"chat.completion","created":1,"model":"MiniMax-M3",
            "system_fingerprint":"fp","choices":[{"index":0,"finish_reason":"stop","logprobs":null,"audio_content":"",
              "message":{"role":"assistant","name":"MiniMax AI","content":"答","reasoning_content":"想","refusal":null,
                "annotations":[],"audio_content":"","reasoning_details":[{"type":"reasoning.text","text":"想","format":"MiniMax-response-v1"}],
                "tool_calls":[{"id":"c1","type":"function","extra":1,"function":{"name":"f","arguments":"{}","strict":true}}]}}],
            "usage":{"prompt_tokens":3,"completion_tokens":4,"total_tokens":7,"total_characters":0,"prompt_tokens_details":{"cached_tokens":0}}}"#).unwrap();
        normalize(&mut v, spec, "req_9", true);
        let m = &v["choices"][0]["message"];
        let keys = |j: &Json| j.as_object().unwrap().keys().cloned().collect::<Vec<_>>();
        assert_eq!(keys(m), vec!["content", "reasoning_details", "role", "tool_calls"]);
        assert_eq!(keys(&v["choices"][0]), vec!["finish_reason", "index", "message"]);
        assert_eq!(keys(&m["tool_calls"][0]), vec!["function", "id", "type"]);
        assert_eq!(keys(&m["tool_calls"][0]["function"]), vec!["arguments", "name"]);
        assert_eq!(keys(&v["usage"]), vec!["completion_tokens", "prompt_tokens", "total_tokens"]);
        assert!(v.get("system_fingerprint").is_none());
        // the message given back in the next request, as it was passed on: taken
        let next = json!({ "model": "Tao-R1", "messages": [{ "role": "user", "content": "x" }, m.clone(), { "role": "tool", "tool_call_id": "c1", "content": "[]" }] });
        assert!(read(&next.to_string()).is_ok(), "{next}");
        // a stream's delta the same
        let mut d: Json = serde_json::from_str(
            r#"{"id":"0a","object":"chat.completion.chunk","choices":[{"index":0,
            "delta":{"role":"assistant","name":"MiniMax AI","reasoning_content":"想","content":"答"}}]}"#,
        )
        .unwrap();
        normalize(&mut d, spec, "req_9", true);
        assert_eq!(keys(&d["choices"][0]["delta"]), vec!["content", "role"]);
        // an assistant's message as an SDK writes it back: the protocol's fields this API never fills, empty — taken,
        // and not sent on; any of them filled is refused
        let sdk = r#"{"model":"Tao-R1","messages":[{"role":"user","content":"x"},
            {"role":"assistant","content":"答","refusal":null,"annotations":[],"audio":null,"function_call":null,"tool_calls":null},
            {"role":"user","content":"y"}]}"#;
        let r = read(sdk).unwrap();
        assert_eq!(keys(&r.body["messages"][1]), vec!["content", "role", "tool_calls"]);
        assert_eq!(code(read(&sdk.replace(r#""refusal":null"#, r#""refusal":"no""#))), "unsupported_field");
        assert_eq!(code(read(&sdk.replace(r#""audio":null"#, r#""audio":{"id":"a"}"#))), "unsupported_field");
    }

    #[test]
    fn a_models_own_terms_are_kept_the_temperature_its_range_and_tool_choice_its_fields() {
        let base = r#"{"model":"Tao-R1","messages":[{"role":"user","content":"x"}]"#;
        let with = |extra: &str| format!("{base},{extra}}}");
        // MiniMax-M3 takes (0, 1]: 0 is the least it takes, past 1 is refused here, not counted against anyone there
        let zero = read(&with(r#""temperature":0"#)).unwrap();
        assert_eq!(zero.body["temperature"], 0.0);
        assert_eq!(upstream_request(&zero, "MiniMax-M3")["temperature"], MINIMAX_LEAST_TEMPERATURE);
        assert_eq!(upstream_request(&read(&with(r#""temperature":0.7"#)).unwrap(), "MiniMax-M3")["temperature"], 0.7);
        assert_eq!(code(read(&with(r#""temperature":1.5"#))), "range");
        let luna = with(r#""temperature":0.5"#).replace("Tao-R1", "gpt-6-luna");
        assert_eq!(code(read(&luna)), "unsupported_field", "a reasoning model takes no temperature");
        // a limit given as null is not given
        assert!(read(&with(r#""max_tokens":null,"max_completion_tokens":64"#)).is_ok_and(|r| r.max_output == 64));
        // tool_choice's function names a tool, and nothing else
        let tools = r#""tools":[{"type":"function","function":{"name":"f"}}]"#;
        assert!(
            read(&with(&format!(r#"{tools},"tool_choice":{{"type":"function","function":{{"name":"f"}}}}"#))).is_ok()
        );
        assert_eq!(
            code(read(&with(&format!(
                r#"{tools},"tool_choice":{{"type":"function","function":{{"name":"f","arguments":"{{}}"}}}}"#
            )))),
            "unsupported_field"
        );
    }

    #[test]
    fn a_stream_begun_with_a_byte_order_mark_or_given_an_empty_chunk_between_cr_and_lf_reads_the_same() {
        let stream = "\u{feff}data: {\"first\":1}\r\ndata: {\"more\":2}\r\n\r\ndata: [DONE]\n\n";
        let want = vec![SseItem::Data("{\"first\":1}\n{\"more\":2}".into()), SseItem::Done];
        let bytes = stream.as_bytes();
        for cut in 0..=bytes.len() {
            for empty in [false, true] {
                let mut p = SseParser::new(1024);
                let mut items = p.push(&bytes[..cut]).unwrap();
                if empty {
                    items.extend(p.push(b"").unwrap()); // an empty chunk: a CR before it still waits for its LF
                }
                items.extend(p.push(&bytes[cut..]).unwrap());
                items.extend(p.finish().unwrap());
                assert_eq!(items, want, "cut at {cut}, an empty chunk: {empty}");
            }
        }
        // a byte order mark later in the stream is no mark: it is the line's
        let mut p = SseParser::new(1024);
        let items = p.push("data: a\n\n\u{feff}data: b\n\n".as_bytes()).unwrap();
        assert_eq!(items, vec![SseItem::Data("a".into())]);
    }

    #[test]
    fn the_offered_models_are_the_known_ones_named() {
        assert_eq!(offered_list(" Tao-R1 , nothing, Tao-R1").iter().map(|m| m.id).collect::<Vec<_>>(), vec!["Tao-R1"]);
        assert!(offered_list("").is_empty());
        let l = listed(find("Tao-R1").unwrap());
        assert_eq!((l["id"].as_str(), l["capabilities"]["tools"].as_bool()), (Some("Tao-R1"), Some(true)));
        assert!(!l.to_string().contains("MiniMax"), "the provider is not named");
    }
}
