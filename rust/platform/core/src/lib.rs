//! 道乃久平台 — what the platform decides, apart from where it runs (docs/adr/0038-accounts-keys-and-credits.md).
//!
//! Every decision is here, synchronous, over any SQLite (`sql::Sql`): who a person is (`identity`), what a passkey
//! proves (`webauthn`), what an API key may do and what a call costs (`accounts`, `keys`), the mails that are sent
//! (`mail`).  The two Workers (../api, ../console) carry requests to it and its answers back; in a Durable Object a
//! synchronous method is one step no other request comes between, so these methods are the platform's transactions.
//! Compiled and tested natively (`cargo test`), and for wasm32 in the Workers.

pub mod accounts;
pub mod api;
pub mod cbor;
pub mod codec;
pub mod crypto;
pub mod email;
pub mod identity;
pub mod keys;
pub mod mail;
pub mod models;
pub mod quota;
pub mod sql;
pub mod time;
pub mod webauthn;
