//! The one thing the platform's state needs of storage: SQLite, as a Durable Object's `ctx.storage.sql` gives it —
//! `exec(query, bindings)`, synchronous, one statement at a time.  In a Durable Object nothing else runs while a
//! synchronous method runs, so a method of the cores that reads, decides and writes with no `.await` in between is one
//! step no other request can come between; that is the whole of their concurrency control, and it is why every
//! method of `identity` and `accounts` is synchronous.  The Workers implement `Sql` over workers-rs's `SqlStorage`;
//! the tests over SQLite itself (rusqlite: the same engine, the same SQL).

use std::fmt;

#[derive(Debug, Clone, PartialEq)]
pub enum Value {
    Null,
    Int(i64),
    Real(f64),
    Text(String),
    Blob(Vec<u8>),
}

impl From<i64> for Value {
    fn from(v: i64) -> Self {
        Value::Int(v)
    }
}
impl From<i32> for Value {
    fn from(v: i32) -> Self {
        Value::Int(i64::from(v))
    }
}
impl From<bool> for Value {
    fn from(v: bool) -> Self {
        Value::Int(i64::from(v))
    }
}
impl From<&str> for Value {
    fn from(v: &str) -> Self {
        Value::Text(v.to_string())
    }
}
impl From<String> for Value {
    fn from(v: String) -> Self {
        Value::Text(v)
    }
}
impl From<&String> for Value {
    fn from(v: &String) -> Self {
        Value::Text(v.clone())
    }
}
impl<T: Into<Value>> From<Option<T>> for Value {
    fn from(v: Option<T>) -> Self {
        v.map_or(Value::Null, Into::into)
    }
}

/// A row: its columns in the order the query named them.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Row(pub Vec<(String, Value)>);

impl Row {
    pub fn get(&self, name: &str) -> &Value {
        self.0.iter().find(|(k, _)| k == name).map_or(&Value::Null, |(_, v)| v)
    }

    /// An integer column.  A Durable Object hands integers to JavaScript as numbers: a whole number written as a real
    /// is read as the integer it is.
    pub fn opt_int(&self, name: &str) -> Option<i64> {
        match self.get(name) {
            Value::Int(n) => Some(*n),
            Value::Real(f) if f.fract() == 0.0 && f.abs() < 9.007_199_254_740_992e15 => Some(*f as i64),
            _ => None,
        }
    }

    pub fn int(&self, name: &str) -> i64 {
        self.opt_int(name).unwrap_or(0)
    }

    pub fn opt_text(&self, name: &str) -> Option<String> {
        match self.get(name) {
            Value::Text(s) => Some(s.clone()),
            _ => None,
        }
    }

    pub fn text(&self, name: &str) -> String {
        self.opt_text(name).unwrap_or_default()
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SqlError(pub String);

impl fmt::Display for SqlError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "storage: {}", self.0)
    }
}

impl std::error::Error for SqlError {}

pub type SqlResult<T> = Result<T, SqlError>;

pub trait Sql {
    /// One statement; the rows it returns (none for a statement that returns none).
    fn exec(&self, query: &str, args: &[Value]) -> SqlResult<Vec<Row>>;
}

/// The helpers every core uses over a `Sql`.
pub trait SqlExt: Sql {
    fn run(&self, query: &str, args: &[Value]) -> SqlResult<()> {
        self.exec(query, args).map(|_| ())
    }

    fn rows(&self, query: &str, args: &[Value]) -> SqlResult<Vec<Row>> {
        self.exec(query, args)
    }

    fn row(&self, query: &str, args: &[Value]) -> SqlResult<Option<Row>> {
        Ok(self.exec(query, args)?.into_iter().next())
    }

    fn scalar(&self, query: &str, args: &[Value]) -> SqlResult<i64> {
        Ok(self.row(query, args)?.and_then(|r| r.0.first().and_then(|(k, _)| r.opt_int(k))).unwrap_or(0))
    }
}

impl<T: Sql + ?Sized> SqlExt for T {}

/// The bindings of a statement: `args![a, b, c]`.
#[macro_export]
macro_rules! args {
    ($($v:expr),* $(,)?) => { &[$($crate::sql::Value::from($v)),*] };
}

#[cfg(test)]
pub mod sqlite {
    //! `Sql` over SQLite itself, for the tests.
    use super::*;
    use rusqlite::types::ValueRef;

    pub struct Memory(pub rusqlite::Connection);

    impl Default for Memory {
        fn default() -> Self {
            Self::new()
        }
    }

    impl Memory {
        pub fn new() -> Self {
            Memory(rusqlite::Connection::open_in_memory().expect("an in-memory database"))
        }
    }

    impl Sql for Memory {
        fn exec(&self, query: &str, args: &[Value]) -> SqlResult<Vec<Row>> {
            let mut stmt = self.0.prepare(query).map_err(|e| SqlError(e.to_string()))?;
            let names: Vec<String> = stmt.column_names().map(|s| s.to_string()).collect();
            let params: Vec<rusqlite::types::Value> = args
                .iter()
                .map(|v| match v {
                    Value::Null => rusqlite::types::Value::Null,
                    Value::Int(n) => rusqlite::types::Value::Integer(*n),
                    Value::Real(f) => rusqlite::types::Value::Real(*f),
                    Value::Text(s) => rusqlite::types::Value::Text(s.clone()),
                    Value::Blob(b) => rusqlite::types::Value::Blob(b.clone()),
                })
                .collect();
            let mut rows = stmt.query(rusqlite::params_from_iter(params)).map_err(|e| SqlError(e.to_string()))?;
            let mut out = Vec::new();
            while let Some(r) = rows.next().map_err(|e| SqlError(e.to_string()))? {
                let mut row = Vec::with_capacity(names.len());
                for (i, name) in names.iter().enumerate() {
                    let v = match r.get_ref(i).map_err(|e| SqlError(e.to_string()))? {
                        ValueRef::Null => Value::Null,
                        ValueRef::Integer(n) => Value::Int(n),
                        ValueRef::Real(f) => Value::Real(f),
                        ValueRef::Text(t) => Value::Text(String::from_utf8_lossy(t).into_owned()),
                        ValueRef::Blob(b) => Value::Blob(b.to_vec()),
                    };
                    row.push((name.clone(), v));
                }
                out.push(Row(row));
            }
            Ok(out)
        }
    }

    #[test]
    fn rows_come_back_with_their_columns_and_types() {
        let db = Memory::new();
        db.run("CREATE TABLE t (a INTEGER, b TEXT, c REAL)", &[]).unwrap();
        db.run("INSERT INTO t VALUES (?, ?, ?)", crate::args![7i64, "x", Value::Real(2.0)]).unwrap();
        let r = db.row("SELECT a, b, c FROM t", &[]).unwrap().unwrap();
        assert_eq!((r.int("a"), r.text("b"), r.opt_int("c")), (7, "x".to_string(), Some(2)));
        assert_eq!(db.scalar("SELECT COUNT(*) FROM t", &[]).unwrap(), 1);
        assert!(db.run("INSERT INTO nowhere VALUES (1)", &[]).is_err());
    }
}
