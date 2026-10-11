"""脱敏 — personal identifiers taken out of a user's data before anything reads it.

What identifies a person is removed where it is written, and only what it is kept: in any cell or text, an identity
card number (18 or 15 digits, its date checked), a mobile or fixed telephone number, an e-mail address, a number
labelled as a medical record, admission, outpatient, insurance or card number, and a name written after 姓名 /
患者 / 病人：; in a table, a column whose head names a person (姓名, 患者, name …) or an identifier (身份证, 病历号,
住院号 …) is replaced by pseudonyms — P0001, P0002 … one per distinct value, the same value the same pseudonym, so
that a patient's visits stay together — a column of contact details (电话, 手机, 地址, 邮箱 …) is emptied, and a
date of birth keeps only its year.  The pseudonyms are not reversible: the original values are not kept anywhere.

Free text can name people in ways no rule finds (张某某来诊); the import says so, and what it removed, count by count.
"""

from __future__ import annotations

import re
from typing import Any

ID18 = re.compile(r"(?<![0-9A-Za-z])[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[0-9Xx](?![0-9A-Za-z])")
ID15 = re.compile(r"(?<![0-9A-Za-z])[1-9]\d{7}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}(?![0-9A-Za-z])")
MOBILE = re.compile(r"(?<![0-9])(?:\+?86[- ]?)?1[3-9]\d(?:[- ]?\d{4}){2}(?![0-9])")
LANDLINE = re.compile(r"(?<![0-9])(?:\(0\d{2,3}\)|0\d{2,3}-)\d{7,8}(?![0-9])")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
LABELLED = re.compile(r"(病历号|病案号|住院号|门诊号|就诊号|医保号|医保卡号|社保号|社保卡号|就诊卡号|身份证号码?|证件号码?|护照号)"
                      r"([：:\s]*)([A-Za-z0-9-]{4,})")
NAMED = re.compile(r"(姓名|患者姓名|病人姓名|患者|病人|病者|就诊人)([：:]\s*)([一-鿿·]{2,4})")
PATTERNS = (("身份证号", (ID18, ID15), "〔身份证号〕"), ("手机号", (MOBILE,), "〔手机号〕"), ("电话", (LANDLINE,), "〔电话〕"),
            ("邮箱", (EMAIL,), "〔邮箱〕"))

# the heads of the columns that identify a person (pseudonymised), give contact (emptied) or a date of birth (year kept)
# (a head is matched whole where a looser match would take 患者年龄 or 方剂名称 for a person)
PERSON = re.compile(r"^(?:(?:患者|病人|病者|就诊人|联系人|家属|医生|医师)?(?:姓名|名字)|患者|病人|病者|就诊人|联系人|"
                    r"patient|name|full ?name|patient ?name)$", re.I)
STAFF = re.compile(r"^(?:(?:主治|接诊|处方|经治|责任)?(?:医生|医师|大夫)(?:姓名)?|doctor|physician)$", re.I)
IDENTIFIER = re.compile(r"身份证|证件号|病历号|病案号|住院号|门诊号|就诊号|医保|社保|卡号|护照|^(?:mrn|ssn|patient ?id|id ?card)$", re.I)
CONTACT = re.compile(r"电话|手机|联系方式|邮箱|电邮|地址|住址|工作单位|微信|^(?:qq|phone|tel|mobile|e-?mail|address|wechat)$", re.I)
BIRTH = re.compile(r"出生|生日|^(?:dob|birth ?date|date of birth|birthday)$", re.I)
YEAR = re.compile(r"(1[89]\d{2}|20\d{2})")
PREFIX = {"person": "P", "staff": "D", "identifier": "ID"}  # a pseudonymised column's values: P0001, D0001, ID0001 …


def mask_text(text: str, counts: dict[str, int]) -> str:
    """The text with the identifiers it writes replaced by what they were (〔手机号〕 …); ``counts`` tallies them."""
    if not text:
        return text
    for label, patterns, mark in PATTERNS:
        for rx in patterns:
            text, k = rx.subn(mark, text)
            if k:
                counts[label] = counts.get(label, 0) + k

    def labelled(m: re.Match[str]) -> str:
        counts["编号"] = counts.get("编号", 0) + 1
        return f"{m.group(1)}{m.group(2)}〔编号〕"

    def named(m: re.Match[str]) -> str:
        counts["姓名"] = counts.get("姓名", 0) + 1
        return f"{m.group(1)}{m.group(2)}〔姓名〕"

    text = LABELLED.sub(labelled, text)
    return NAMED.sub(named, text)


def column_rule(head: str) -> str | None:
    """What a column of this head is: person, staff (a doctor), identifier, contact or birth — or None (kept, its cells
    masked)."""
    h = re.sub(r"\s+", "", head.strip())
    if BIRTH.search(h):
        return "birth"
    if CONTACT.search(h):
        return "contact"
    if IDENTIFIER.search(h):
        return "identifier"
    if PERSON.search(h):
        return "person"
    if STAFF.search(h):
        return "staff"
    return None


def table(columns: list[str], rows: list[list[str]]) -> tuple[list[list[str]], dict[str, Any]]:
    """A table de-identified: (rows, report) — report {"columns": {head: what was done}, "masked": {kind: count}}."""
    rules = {i: column_rule(c) for i, c in enumerate(columns)}
    pseudonyms: dict[int, dict[str, str]] = {i: {} for i, r in rules.items() if r in PREFIX}
    counts: dict[str, int] = {}
    out = []
    for row in rows:
        new = []
        for i, cell in enumerate(row):
            rule = rules.get(i)
            if rule in PREFIX and cell:
                seen = pseudonyms[i]
                cell = seen.setdefault(cell, f"{PREFIX[rule]}{len(seen) + 1:04d}")
            elif rule == "contact" and cell:
                cell = ""
            elif rule == "birth" and cell:
                m = YEAR.search(cell)
                cell = m.group(1) if m else ""
            elif cell:
                cell = mask_text(cell, counts)
            new.append(cell)
        out.append(new)
    done = {"person": "以化名代替（P0001…）", "staff": "以化名代替（D0001…）", "identifier": "以编号代替（ID0001…）", "contact": "已删除",
            "birth": "只留出生年份"}
    report = {"columns": {columns[i]: done[r] for i, r in rules.items() if r}, "masked": counts}
    return out, report


def text(value: str) -> tuple[str, dict[str, Any]]:
    """A text de-identified: (text, report)."""
    counts: dict[str, int] = {}
    return mask_text(value, counts), {"columns": {}, "masked": counts}


__all__ = ["column_rule", "mask_text", "table", "text"]
