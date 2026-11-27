//! An email address as the platform keeps it.  Conservative, and said so: a dot-atom local part in ASCII (no quoted
//! forms, no comments, nothing that needs SMTPUTF8) at a domain in ASCII — what every provider the service writes to
//! takes, and what no two parsers read differently.  A domain in another script is written in its ASCII form (xn--…);
//! the console says so.  Two spellings are one account only by case: no dots or +tags are removed (a provider's own
//! rule, not every provider's), so two people's addresses never become one.

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Email {
    /// what mail is sent to: the local part as it was written, the domain in lower case
    pub address: String,
    /// what makes two accounts one: the address in lower case
    pub key: String,
    pub domain: String,
}

fn atext(c: u8) -> bool {
    c.is_ascii_alphanumeric() || b"!#$%&'*+/=?^_`{|}~-".contains(&c)
}

fn label(l: &str) -> bool {
    !l.is_empty()
        && l.len() <= 63
        && !l.starts_with('-')
        && !l.ends_with('-')
        && l.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'-')
}

pub fn normalize(input: &str) -> Option<Email> {
    let text = input.trim();
    if text.is_empty() || text.len() > 254 || !text.is_ascii() {
        return None;
    }
    let (local, host) = text.split_once('@')?;
    if host.contains('@') || local.is_empty() || local.len() > 64 {
        return None;
    }
    if !local.split('.').all(|part| !part.is_empty() && part.bytes().all(atext)) {
        return None;
    }
    let domain = host.to_ascii_lowercase();
    let labels: Vec<&str> = domain.split('.').collect();
    if domain.len() > 253
        || labels.len() < 2
        || !labels.iter().all(|l| label(l))
        || labels.last()?.bytes().all(|c| c.is_ascii_digit())
    {
        return None;
    }
    let address = format!("{local}@{domain}");
    Some(Email { key: address.to_ascii_lowercase(), address, domain })
}

/// An address as it is shown to someone who is not its owner: its first character and its domain.
pub fn masked(address: &str) -> String {
    match address.split_once('@') {
        Some((local, domain)) if !local.is_empty() => format!("{}…@{domain}", &local[..1]),
        _ => "…".into(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn kept_as_written_and_made_one_with_its_other_spellings_only_by_case() {
        let e = normalize("  Li.Wei+lab@Example.ORG ").unwrap();
        assert_eq!(
            (e.address.as_str(), e.key.as_str(), e.domain.as_str()),
            ("Li.Wei+lab@example.org", "li.wei+lab@example.org", "example.org")
        );
        assert_eq!(normalize("12345678@QQ.com").unwrap().address, "12345678@qq.com");
        assert_eq!(normalize("a@xn--fsqu00a.xn--0zwm56d").unwrap().domain, "xn--fsqu00a.xn--0zwm56d");
        assert_ne!(normalize("a.b@gmail.com").unwrap().key, normalize("ab@gmail.com").unwrap().key);
        for bad in [
            "",
            "plain",
            "@example.org",
            "a@",
            "a@b",
            "a@@example.org",
            "a b@example.org",
            "a@exa mple.org",
            "\"q\"@example.org",
            "a..b@example.org",
            ".a@example.org",
            "a.@example.org",
            "a@example.org.",
            "a@-example.org",
            "a@example.123",
            "a@[127.0.0.1]",
            "a@example.org:25",
            "a@example.org/x",
            "a\n@example.org",
            "用户@example.org",
            "a@例子.测试",
            "a(c)@example.org",
        ] {
            assert_eq!(normalize(bad), None, "{bad:?} was taken");
        }
        assert_eq!(normalize(&format!("{}@example.org", "a".repeat(65))), None);
        assert_eq!(normalize(&format!("a@{}.org", "b".repeat(250))), None);
        assert_eq!(masked("li.wei@example.org"), "l…@example.org");
        assert_eq!(masked("nothing"), "…");
    }
}
