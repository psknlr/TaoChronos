//! The developer API's own rules (api.impf.ai, `/v1`): what a request may ask, what it becomes on the corpus, how the
//! corpus's answer is read, and the shapes of the answers — apart from the Worker, so that they are tested here.
//!
//! A request is read strictly: an object with the fields a product takes, each within its limit, and nothing else.  A
//! field the API does not know is refused, not ignored, and a value past its limit is refused, not clamped — the
//! harness's own rule for its tools (docs/adr/0037-what-a-call-may-cost.md): a caller who asked for a thousand hits
//! and was given fifty was answered a question they did not ask.  The limits here are narrower than the tools' own:
//! what a paid call may cost is the API's to bound.
//!
//! The corpus answers a call with `{ok, tool, text, result, citations, summary, receipt}` — HTTP 200 whether the tool
//! ran or refused (a tool's failure is a result the model reads).  So a call is *delivered* — and charged — only when
//! the answer is 200 and `ok` is true; a tool that refused its arguments is the caller's 422, released; anything else
//! is the service's failure, released.  What is passed on is the result, its citations, its summary and its text for a
//! model; never the receipt (hashes of the harness's own run).

use serde_json::{Map, Value as Json, json};

use crate::accounts::{Product, Refusal};
use crate::codec::hex;
use crate::crypto::sha256;

/// A request body may weigh this much at the most.
pub const MOST_BODY: usize = 64 * 1024;

#[derive(Debug, Clone, PartialEq)]
pub struct Call {
    pub product: Product,
    /// the tool it becomes
    pub tool: &'static str,
    pub arguments: Json,
}

fn bad(code: &'static str, message: impl Into<String>) -> Refusal {
    Refusal { status: 400, kind: "invalid_request", code, message: message.into(), retry: None }
}

fn text(v: &Json, field: &str, most: usize) -> Result<String, Refusal> {
    let s = v.as_str().ok_or_else(|| bad("type", format!("{field} is text")))?.trim();
    let n = s.chars().count();
    if n == 0 || n > most {
        return Err(bad("length", format!("{field} is 1–{most} characters")));
    }
    if s.chars().any(|c| c.is_control() && c != '\n' && c != '\t') {
        return Err(bad("characters", format!("{field} holds a control character")));
    }
    Ok(s.to_string())
}

fn integer(v: &Json, field: &str, least: i64, most: i64) -> Result<i64, Refusal> {
    let n = v.as_i64().filter(|n| (least..=most).contains(n));
    n.ok_or_else(|| bad("range", format!("{field} is a whole number from {least} to {most}")))
}

/// A product's request, read strictly into the tool call it becomes.
pub fn read_request(product: Product, body: &[u8]) -> Result<Call, Refusal> {
    let v: Json = serde_json::from_slice(body).map_err(|_| bad("json", "the body is not JSON"))?;
    let obj = v.as_object().ok_or_else(|| bad("json", "the body is a JSON object"))?;
    let allowed: &[&str] = match product {
        Product::Search => &["query", "k", "before", "after", "books"],
        Product::Verify => &["quote", "passage_id"],
    };
    if let Some(extra) = obj.keys().find(|k| !allowed.contains(&k.as_str())) {
        return Err(bad(
            "field",
            format!("{} takes no field {extra} (it takes: {})", product.name(), allowed.join(", ")),
        ));
    }
    let mut args = Map::new();
    match product {
        Product::Search => {
            args.insert("query".into(), json!(text(obj.get("query").unwrap_or(&Json::Null), "query", 500)?));
            args.insert("k".into(), json!(obj.get("k").map(|k| integer(k, "k", 1, 50)).transpose()?.unwrap_or(10)));
            let mut years = [None, None];
            for (i, f) in ["after", "before"].iter().enumerate() {
                if let Some(y) = obj.get(*f).filter(|y| !y.is_null()) {
                    let y = integer(y, f, -5000, 5000)?;
                    args.insert((*f).into(), json!(y));
                    years[i] = Some(y);
                }
            }
            if let [Some(after), Some(before)] = years
                && after > before
            {
                return Err(bad("range", "after is not later than before"));
            }
            if let Some(books) = obj.get("books").filter(|b| !b.is_null()) {
                let list = books.as_array().ok_or_else(|| bad("type", "books is a list of titles"))?;
                if list.is_empty() || list.len() > 20 {
                    return Err(bad("length", "books names 1–20 titles"));
                }
                let titles = list.iter().map(|b| text(b, "a title in books", 100)).collect::<Result<Vec<_>, _>>()?;
                args.insert("books".into(), json!(titles));
            }
            Ok(Call { product, tool: "classics.search", arguments: Json::Object(args) })
        }
        Product::Verify => {
            args.insert("quote".into(), json!(text(obj.get("quote").unwrap_or(&Json::Null), "quote", 2000)?));
            if let Some(p) = obj.get("passage_id").filter(|p| !p.is_null()) {
                args.insert("passage_id".into(), json!(text(p, "passage_id", 200)?));
            }
            Ok(Call { product, tool: "validation.verify_quote", arguments: Json::Object(args) })
        }
    }
}

/// What an Idempotency-Key is checked against: the product and its arguments as read (the keys in order, so that two
/// spellings of one request are one).
pub fn request_digest(call: &Call) -> String {
    hex(&sha256(format!("{}\n{}", call.product.name(), call.arguments).as_bytes()))
}

/// The body of the corpus's `POST /api/call`.
pub fn corpus_body(call: &Call) -> Json {
    json!({ "name": call.tool, "arguments": call.arguments, "max_chars": 16000 })
}

#[derive(Debug, Clone, PartialEq)]
pub enum Corpus {
    /// the tool ran: what the caller is given
    Delivered(Json),
    /// the tool refused what it was asked: the caller's to change (422), not charged
    Refused(String),
    /// the corpus is starting or full: try again (503), not charged
    Unavailable(i64),
    /// anything else: the service's failure (502), not charged
    Failed,
}

/// The corpus's answer to a call, read.
pub fn read_corpus(status: u16, body: &str, retry_after: Option<&str>) -> Corpus {
    let retry = retry_after.and_then(|r| r.trim().parse::<i64>().ok()).filter(|r| (1..=3600).contains(r)).unwrap_or(10);
    if status == 503 || status == 429 {
        return Corpus::Unavailable(retry);
    }
    let Ok(v) = serde_json::from_str::<Json>(body) else {
        return Corpus::Failed;
    };
    if status == 400 {
        let msg = v.get("error").and_then(Json::as_str).unwrap_or("the corpus refused the call");
        return Corpus::Refused(msg.chars().take(500).collect());
    }
    if status != 200 {
        return Corpus::Failed;
    }
    match v.get("ok").and_then(Json::as_bool) {
        Some(true) => Corpus::Delivered(json!({
            "result": v.get("result").cloned().unwrap_or(Json::Null),
            "citations": v.get("citations").cloned().unwrap_or(json!([])),
            "summary": v.get("summary").cloned().unwrap_or(Json::Null),
            "text": v.get("text").cloned().unwrap_or(Json::Null),
        })),
        Some(false) => Corpus::Refused(
            v.get("error").and_then(Json::as_str).unwrap_or("the tool refused the call").chars().take(500).collect(),
        ),
        None => Corpus::Failed,
    }
}

/// A product's answer.
pub fn success(
    request_id: &str,
    product: Product,
    now_ms: i64,
    data: Json,
    credits: i64,
    env: &str,
    price_version: &str,
) -> Json {
    json!({
        "id": request_id, "object": product.name(), "created": now_ms / 1000, "data": data,
        "usage": { "credits": credits, "environment": env, "price_version": price_version },
    })
}

/// A refusal's answer.
pub fn error(request_id: &str, r: &Refusal) -> Json {
    json!({ "id": request_id, "error": { "type": r.kind, "code": r.code, "message": r.message } })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn code(r: Result<Call, Refusal>) -> &'static str {
        r.err().map(|e| e.code).unwrap_or("ok")
    }

    #[test]
    fn a_search_is_read_strictly_and_becomes_the_tools_call() {
        let c = read_request(
            Product::Search,
            r#"{"query":"  桂枝汤 ","k":5,"after":200,"before":1600,"books":["伤寒论"]}"#.as_bytes(),
        )
        .unwrap();
        assert_eq!(c.tool, "classics.search");
        assert_eq!(
            c.arguments,
            json!({ "query": "桂枝汤", "k": 5, "after": 200, "before": 1600, "books": ["伤寒论"] })
        );
        assert_eq!(
            read_request(Product::Search, br#"{"query":"x"}"#).unwrap().arguments,
            json!({ "query": "x", "k": 10 })
        );
        // refused, not clamped or ignored
        for (body, want) in [
            (&br#"{"query":"x","k":51}"#[..], "range"),
            (br#"{"query":"x","k":0}"#, "range"),
            (br#"{"query":"x","k":"5"}"#, "range"),
            (br#"{"query":"x","k":5.5}"#, "range"),
            (br#"{"query":""}"#, "length"),
            (br#"{"k":5}"#, "type"),
            (br#"{"query":"x","limit":5}"#, "field"),
            (br#"{"query":"x","after":1600,"before":200}"#, "range"),
            (br#"{"query":"x","before":9999}"#, "range"),
            (br#"{"query":"x","books":[]}"#, "length"),
            (br#"{"query":"x","books":"x"}"#, "type"),
            (br#"[]"#, "json"),
            (br#"{"query":"x""#, "json"),
            (br#"{"query":"a\u0000b"}"#, "characters"),
        ] {
            assert_eq!(code(read_request(Product::Search, body)), want, "{}", String::from_utf8_lossy(body));
        }
        let long = format!(r#"{{"query":"{}"}}"#, "道".repeat(501));
        assert_eq!(code(read_request(Product::Search, long.as_bytes())), "length");
        assert!(
            read_request(Product::Search, format!(r#"{{"query":"{}"}}"#, "道".repeat(500)).as_bytes()).is_ok(),
            "characters, not bytes"
        );
    }

    #[test]
    fn a_verification_and_its_digest_for_a_repeat() {
        let a = read_request(
            Product::Verify,
            r#"{"quote":"太阳之为病，脉浮，头项强痛而恶寒。","passage_id":"shl:1"}"#.as_bytes(),
        )
        .unwrap();
        assert_eq!(a.tool, "validation.verify_quote");
        let b = read_request(
            Product::Verify,
            r#"{"passage_id":"shl:1","quote":" 太阳之为病，脉浮，头项强痛而恶寒。"}"#.as_bytes(),
        )
        .unwrap();
        assert_eq!(request_digest(&a), request_digest(&b), "two spellings of one request are one");
        let c = read_request(Product::Verify, r#"{"quote":"太阳之为病"}"#.as_bytes()).unwrap();
        assert_ne!(request_digest(&a), request_digest(&c));
        assert_eq!(code(read_request(Product::Verify, br#"{"quote":"x","k":1}"#)), "field");
        assert_eq!(
            corpus_body(&c),
            json!({ "name": "validation.verify_quote", "arguments": { "quote": "太阳之为病" }, "max_chars": 16000 })
        );
    }

    #[test]
    fn the_corpus_answer_is_read_for_what_it_is() {
        let ran = r#"{"ok":true,"tool":"classics.search","text":"t","result":{"hits":[1]},"citations":[{"passage_id":"p"}],"summary":"s","receipt":{"actor":"agent:chat"}}"#;
        let Corpus::Delivered(d) = read_corpus(200, ran, None) else { panic!() };
        assert_eq!(
            d,
            json!({ "result": { "hits": [1] }, "citations": [{ "passage_id": "p" }], "summary": "s", "text": "t" })
        );
        assert!(!d.to_string().contains("receipt") && !d.to_string().contains("agent:chat"));
        assert_eq!(
            read_corpus(200, r#"{"ok":false,"error":"invalid arguments: $.k: 500 > maximum 100"}"#, None),
            Corpus::Refused("invalid arguments: $.k: 500 > maximum 100".into())
        );
        assert_eq!(read_corpus(400, r#"{"error":"invalid JSON"}"#, None), Corpus::Refused("invalid JSON".into()));
        assert_eq!(read_corpus(503, r#"{"starting":true}"#, Some("30")), Corpus::Unavailable(30));
        assert_eq!(read_corpus(429, r#"{}"#, None), Corpus::Unavailable(10));
        assert_eq!(read_corpus(500, r#"{"error":"Traceback …"}"#, None), Corpus::Failed);
        assert_eq!(read_corpus(200, "<html>", None), Corpus::Failed);
        assert_eq!(read_corpus(200, r#"{"result":1}"#, None), Corpus::Failed);
    }
}
