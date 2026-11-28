//! What both Workers need of Cloudflare's runtime, once: the core's `Sql` over a Durable Object's SQLite, entropy from
//! `crypto.getRandomValues`, the clock, JSON answers with the headers every answer carries, a body read only up to
//! what it may weigh, and a call to a Durable Object by its JSON protocol.  Nothing here decides anything.

use futures_util::StreamExt;
use js_sys::{Function, Reflect, Uint8Array};
use serde_json::{Value as Json, json};
use tao_platform::crypto::Entropy;
use tao_platform::sql::{Row, Sql, SqlError, SqlResult, Value};
use wasm_bindgen::{JsCast, JsValue};
use worker::{Headers, Method, Request, RequestInit, Response, Result, SqlStorage, SqlStorageValue, Stub};

/// The core's `Sql` over `ctx.storage.sql`: one statement, its rows with their column names.
pub struct DoSql(pub SqlStorage);

impl Sql for DoSql {
    fn exec(&self, query: &str, args: &[Value]) -> SqlResult<Vec<Row>> {
        let bindings: Vec<SqlStorageValue> = args
            .iter()
            .map(|v| match v {
                Value::Null => SqlStorageValue::Null,
                Value::Int(n) => SqlStorageValue::Integer(*n),
                Value::Real(f) => SqlStorageValue::Float(*f),
                Value::Text(s) => SqlStorageValue::String(s.clone()),
                Value::Blob(b) => SqlStorageValue::Blob(b.clone()),
            })
            .collect();
        let cursor = self.0.exec(query, bindings).map_err(|e| SqlError(e.to_string()))?;
        let names = cursor.column_names();
        let mut rows = Vec::new();
        for raw in cursor.raw() {
            let raw = raw.map_err(|e| SqlError(e.to_string()))?;
            let cols = names
                .iter()
                .cloned()
                .zip(raw.into_iter().map(|v| match v {
                    SqlStorageValue::Null => Value::Null,
                    SqlStorageValue::Boolean(b) => Value::Int(i64::from(b)),
                    SqlStorageValue::Integer(n) => Value::Int(n),
                    SqlStorageValue::Float(f) => Value::Real(f),
                    SqlStorageValue::String(s) => Value::Text(s),
                    SqlStorageValue::Blob(b) => Value::Blob(b),
                }))
                .collect();
            rows.push(Row(cols));
        }
        Ok(rows)
    }
}

/// `crypto.getRandomValues`: the runtime's own source.
pub struct JsEntropy;

impl Entropy for JsEntropy {
    fn fill(&self, buf: &mut [u8]) {
        let crypto = Reflect::get(&js_sys::global(), &JsValue::from_str("crypto")).expect("crypto");
        let get: Function =
            Reflect::get(&crypto, &JsValue::from_str("getRandomValues")).expect("getRandomValues").unchecked_into();
        for chunk in buf.chunks_mut(65_536) {
            let arr = Uint8Array::new_with_length(chunk.len() as u32);
            get.call1(&crypto, &arr).expect("random values");
            arr.copy_to(chunk);
        }
    }
}

/// Milliseconds since 1970, as the runtime's clock says (it moves only between I/O: the same within one step).
pub fn now() -> i64 {
    js_sys::Date::now() as i64
}

/// A JSON answer, with what every answer of these Workers carries: not cached, not sniffed, HTTPS from now on.
pub fn json(status: u16, body: &Json, extra: &[(&str, String)]) -> Result<Response> {
    let headers = Headers::new();
    headers.set("Content-Type", "application/json; charset=utf-8")?;
    headers.set("Cache-Control", "no-store")?;
    headers.set("X-Content-Type-Options", "nosniff")?;
    headers.set("Strict-Transport-Security", "max-age=31536000")?;
    for (k, v) in extra {
        if k.eq_ignore_ascii_case("Set-Cookie") {
            headers.append(k, v)?; // each its own header: set would keep the last
        } else {
            headers.set(k, v)?;
        }
    }
    Ok(Response::ok(body.to_string())?.with_status(status).with_headers(headers))
}

/// A body read only up to `most` bytes: None when it weighs more — by its declared length, or as it is read (a body
/// sent without one is not taken whole into memory first).
pub async fn body(req: &mut Request, most: usize) -> Result<Option<Vec<u8>>> {
    if let Some(declared) = req.headers().get("Content-Length")?.and_then(|v| v.parse::<usize>().ok())
        && declared > most
    {
        return Ok(None);
    }
    if req.inner().body().is_none() {
        return Ok(Some(Vec::new()));
    }
    let mut stream = req.stream()?;
    let mut out = Vec::new();
    while let Some(chunk) = stream.next().await {
        let chunk = chunk?;
        if out.len() + chunk.len() > most {
            return Ok(None);
        }
        out.extend_from_slice(&chunk);
    }
    Ok(Some(out))
}

/// A call to a Durable Object of these Workers: `POST https://do/<op>` with a JSON body, answered with a JSON body.
pub async fn call(stub: &Stub, op: &str, body: &Json) -> Result<(u16, Json)> {
    let headers = Headers::new();
    headers.set("Content-Type", "application/json")?;
    let mut init = RequestInit::new();
    init.with_method(Method::Post).with_headers(headers).with_body(Some(JsValue::from_str(&body.to_string())));
    let req = Request::new_with_init(&format!("https://do/{op}"), &init)?;
    let mut res = stub.fetch_with_request(req).await?;
    let status = res.status_code();
    let text = res.text().await?;
    Ok((status, serde_json::from_str(&text).unwrap_or_else(|_| json!({ "error": "unreadable answer" }))))
}

/// A Worker's variable as text (empty and missing alike: None).
pub fn var(env: &worker::Env, name: &str) -> Option<String> {
    env.var(name).ok().map(|v| v.to_string()).filter(|v| !v.trim().is_empty())
}

/// A Worker's secret as text (None when it is not set).
pub fn secret(env: &worker::Env, name: &str) -> Option<String> {
    env.secret(name).ok().map(|v| v.to_string()).filter(|v| !v.trim().is_empty())
}
