"""``Lexicon.match`` gives what its plain definition gives, mention for mention.

Claim extraction, lineage, the gates and the sense route all read the lexicon through ``match``, so it is arranged for
speed (an index of the surfaces by their first characters); this compares it with the scan written the plain way —
at each position every length from the longest down, the first of a surface's entries in category rank — on the
demonstration corpus in each form callers hand it, on texts made of the lexicon's own surfaces, and on a lexicon made
to try the edges: entries of equal and unequal rank under one surface, weak one-character names, entries added late.
"""

from __future__ import annotations

import json
import random

from taochronos.plugins.classics.domain import Lexicon, LexEntry, Mention
from taochronos.plugins.classics.intertext import HAN
from taochronos.plugins.classics.reuse import strip_punct


# ---------------------------------------------------------------- the plain definition
def plain_match(lex: Lexicon, text: str, *, include_weak: bool = True) -> list[Mention]:
    mentions: list[Mention] = []
    i, n = 0, len(text)
    while i < n:
        found = None
        for length in range(min(lex.max_len, n - i), 0, -1):
            cands = lex._by_surface.get(text[i: i + length])
            if cands:
                entry, kind = sorted(cands, key=lambda t: lex._rank.get(t[0].category, 99))[0]
                found = Mention(entry, text[i: i + length], i, i + length, kind)
                break
        if found is None:
            i += 1
            continue
        if include_weak or not found.weak:
            mentions.append(found)
        i = found.end
    return mentions


def same(lex: Lexicon, text: str) -> bool:
    key = lambda ms: [(id(m.entry), m.surface, m.start, m.end, m.synonym_kind) for m in ms]  # noqa: E731
    return all(key(lex.match(text, include_weak=w)) == key(plain_match(lex, text, include_weak=w)) for w in (True, False))


def made_up(lex: Lexicon, seed: int, n: int) -> list[str]:
    """Texts of the lexicon's surfaces, whole and cut, run together with stray characters of theirs."""
    rng = random.Random(seed)
    surfaces = sorted(lex._by_surface)
    chars = sorted({c for s in surfaces for c in s})
    out = []
    for _ in range(n):
        parts = []
        for _ in range(rng.randint(1, 6)):
            s, cut = rng.choice(surfaces), rng.random()
            if cut < 0.2:
                s = s[: rng.randint(1, len(s))]
            elif cut < 0.4:
                s = s[rng.randint(0, len(s) - 1):]
            elif cut < 0.5:
                s = "".join(rng.choice(chars) for _ in range(rng.randint(1, 4)))
            parts.append(s)
        out.append("".join(parts))
    return out


# ---------------------------------------------------------------- tests
def test_the_demonstration_corpus_in_every_form_callers_use(harness):
    lex, normalize = harness.pack.lexicon, harness.pack.variants.normalize_text
    for p in harness.corpus.passages():
        norm = normalize(p.text)
        han = "".join(ch for ch in norm if HAN.match(ch))
        for text in (p.text, norm, strip_punct(norm)[0], han, norm[1:], norm[:-1]):
            assert same(lex, text), p.id


def test_texts_made_of_the_lexicons_surfaces(harness):
    lex = harness.pack.lexicon
    assert all(same(lex, text) for text in ["", "脉", "脉浮紧", "\U00020000桂枝汤"] + made_up(lex, 7, 3000))


def test_a_lexicon_made_to_try_the_edges(tmp_path):
    blocks = [
        {"category": "herb", "entries": [
            {"term": "甲乙", "aliases": ["丙"]}, {"term": "甲乙丙丁戊"}, {"term": "乙丙", "aliases": ["丁"]},
            {"term": "戊", "weak": True}, {"term": "己庚", "aliases": ["甲乙丙"]}, {"term": "辛", "aliases": ["甲乙丙"]}]},
        {"category": "formula", "entries": [{"term": "甲乙"}, {"term": "丙丁"}]},  # outranks the herbs on 甲乙
        {"category": "unranked", "entries": [{"term": "丙丁"}, {"term": "庚", "weak": True}]},
        {"category": "concept", "entries": [{"term": "丁戊", "weak": True}, {"term": "庚辛", "weak": True}]},
    ]
    path = tmp_path / "edges.yaml"
    path.write_text(json.dumps(blocks, ensure_ascii=False), encoding="utf-8")  # JSON is YAML
    lex = Lexicon([path])
    assert len(lex._by_surface["甲乙"]) == 2 and len(lex._by_surface["甲乙丙"]) == 2  # unequal rank; equal rank
    texts = made_up(lex, 11, 3000) + ["甲乙丙丁戊己庚辛", "戊戊庚庚", "丁戊庚辛甲"]
    assert all(same(lex, text) for text in texts)
    assert [m.term_id for m in lex.match("甲乙丙")] == ["herb:己庚"]  # of equal rank, the first entry
    lex._add(LexEntry(term_id="herb:戊己", term="戊己", category="herb"))  # added after match built its index
    lex._add(LexEntry(term_id="herb:甲乙丙丁戊己庚辛壬", term="甲乙丙丁戊己庚辛壬", category="herb"))  # longer than max_len
    assert all(same(lex, text) for text in texts + ["戊己", "甲乙丙丁戊己庚辛壬"])
    assert [m.term_id for m in lex.match("戊己")] == ["herb:戊己"]
