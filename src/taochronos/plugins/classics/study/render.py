"""Markdown for the study results (``taochronos study …``): headings, tables and verbatim quotes with their sources.

Every page ends with the provenance footer — what the result was computed on (books, passages, sources, normaliser,
corpus digest) — and the notices that apply (dosage, machine reading).
"""

from __future__ import annotations

from typing import Any

MACHINE = "规则抽取属机器阅读：每条结论附原文与出处，请回查原文核实。"


def _years(w: dict[str, Any] | None) -> str:
    ys = (w or {}).get("years") or []
    if not ys:
        return "年代未定"
    return f"{int(ys[0])}" if ys[0] == ys[1] else f"{int(ys[0])}–{int(ys[1])}"


def _q(text: str, n: int = 160) -> str:
    text = (text or "").replace("\n", " ").replace("|", "｜")
    return text if len(text) <= n else text[:n] + "…"


def _cite(w: dict[str, Any], n: int = 160) -> str:
    return f"{w.get('locator', '')}（{_years(w)}）`{w.get('passage_id', '')}`\n  > {_q(w.get('quote', ''), n)}"


def footer(signature: dict[str, Any], *notices: str) -> list[str]:
    lines = ["", "---", f"语料：{signature.get('books')} 部 / {signature.get('passages')} 段；来源 {'、'.join(signature.get('sources', []))}；"
             f"规范化 {signature.get('normalizer')}；语料指纹 {signature.get('corpus_digest')}"]
    return lines + [f"> {n}" for n in notices if n]


# ------------------------------------------------------------------ pages
def concordance(r: dict[str, Any]) -> list[str]:
    s = r.get("summary", {})
    out = [f"# 经文互见·集注：{_q(r.get('query', ''), 40)}", "",
           f"{s.get('witnesses', 0)} 处见证，{s.get('works', 0)} 部著作；" + "；".join(f"{k} {v}" for k, v in (s.get("by_relation") or {}).items()), ""]
    if r.get("base"):
        out += ["**底本**：" + _cite(r["base"]), ""]
    out += ["| 时期 | 关系 | 覆盖 | 出处 | 引文 |", "|---|---|---|---|---|"]
    for h in r.get("hits", [])[:60]:
        out.append(f"| {h.get('period') or ''} | {h.get('relation', '')} | {h.get('coverage', 0):.0%} | {h.get('locator', '')}（{_years(h)}） | {_q(h.get('quote', ''), 60)} |")
    if r.get("apparatus"):
        out += ["", "## 校勘记", ""]
        for a in r["apparatus"][:40]:
            wits = "、".join(a.get("witnesses", [])[:6]) + (f" 等 {len(a['witnesses'])} 本" if len(a.get("witnesses", [])) > 6 else "")
            out.append(f"- 〔{a.get('kind')}〕底本「{a.get('base', '')}」，{wits}作「{a.get('reading', '')}」")
    return out


def formula(r: dict[str, Any]) -> list[str]:
    f, s = r["formula"], r.get("summary", {})
    forms = "、".join(x["form"] + (f"（{x['kind']}）" if x["kind"] != "本名" else "") for x in f.get("forms", []))
    out = [f"# 方源考：{f['name']}", "", f"名称：{forms}", "",
           f"写出组成的见证 {s.get('compositions', 0)} 条（{s.get('works', 0)} 部著作）；组成类别 {s.get('groups', 0)}："
           f"加减化裁 {s.get('variants', 0)}，同名异方 {s.get('same_name_different', 0)}，孤例 {s.get('single_witness', 0)}。", ""]
    if r.get("earliest"):
        w = r["earliest"]
        out += ["## 原方（最早见）", "", _cite(w, 240), "", "| 药 | 原文剂量 | 炮制/注 | 当时计量折合（学术估值） |", "|---|---|---|---|"]
        for i in w.get("ingredients", []):
            out.append(f"| {i['surface']} | {i['dose'] or '—'} | {i.get('processing') or ''} | {i.get('reading') or ''} |")
        if w.get("preparation"):
            out += ["", f"煎服法：{w['preparation']}"]
        if w.get("indication"):
            out += [f"主治：{w['indication']}"]
        out.append("")
    out += ["## 组成类别", "", "| 类别 | 核心药味 | 见证 | 年代 | 常见方名 | 最早见 |", "|---|---|---|---|---|---|"]
    for g in r.get("groups", [])[:16]:
        span = g.get("span") or []
        names = "、".join(list(g.get("names", {}))[:3])
        out.append(f"| {g.get('relation', '')} | {'、'.join(g.get('core_terms', []))} | {g.get('witnesses')} | "
                   f"{f'{int(span[0])}–{int(span[1])}' if span else ''} | {names} | {g['earliest'].get('locator', '')} |")
    if r.get("other_names"):
        out += ["", "## 同方异名（组成相同或极近而名称不同）", ""]
        for o in r["other_names"][:12]:
            first = o.get("first") or {}
            out.append(f"- **{o['name']}**：{o['witnesses']} 见证，相似度 {o['similarity']}" + ("，药味全同" if o.get("same_drugs") else "")
                       + (f"；最早 {first.get('locator', '')}（{_years(first)}）" if first else ""))
    if r.get("ratios"):
        out += ["", "## 配伍比例（以最大剂量为 1，与各期计量无关）", ""]
        for x in r["ratios"][:12]:
            out.append(f"- {x['locator']}（{_years(x)}）：" + "，".join(f"{k} {v}" for k, v in x["ratio"].items()))
    if r.get("modifications"):
        out += ["", "## 加减用法", ""]
        out += [f"- {_q(m.get('quote', ''), 80)} —— {m.get('locator', '')}（{_years(m)}）" for m in r["modifications"][:12]]
    if r.get("indications"):
        out += ["", "## 历代主治", ""]
        out += [f"- {_q(x['indication'], 80)} —— {x['locator']}" for x in r["indications"][:12]]
    if r.get("songs"):
        out += ["", "## 方歌", ""]
        out += [f"- {_q(x['quote'], 120)} —— {x.get('locator', '')}" for x in r["songs"]]
    return out


def herb(r: dict[str, Any]) -> list[str]:
    h, s = r["herb"], r.get("summary", {})
    forms = "、".join(x["form"] + (f"（{x['kind']}）" if x["kind"] != "本名" else "") for x in h.get("forms", []))
    out = [f"# 药性源流：{h['name']}", "", f"名称：{forms}", "",
           f"{s.get('works', 0)} 部本草著作有条目（{s.get('books', 0)} 个本子）；言归经者 {s.get('with_channels', 0)} 部。", "",
           "| 年代 | 著作 | 味 | 性 | 毒 | 归经 | 升降浮沉 | 主治（节录） |", "|---|---|---|---|---|---|---|---|"]
    for e in r.get("entries", []):
        out.append(f"| {_years(e)} | {e.get('title', '')} | {e['flavor']} | {e['nature']} | {e['toxicity']} | {'、'.join(e['channels'])} | "
                   f"{e['direction']} | {_q(e['indication'], 30)} |")
    if r.get("firsts"):
        out += ["", "## 首见（各项性能的最早表述）", ""]
        out += [f"- {f['field']}「{f['value']}」：{f['locator']}（{_years(f)}）" for f in r["firsts"][:30]]
    return out


def term(r: dict[str, Any]) -> list[str]:
    t = r["term"]
    trend = r.get("trend") or {}
    out = [f"# 术语源流：{t['name']}", "", "形式：" + "、".join(f["form"] for f in t.get("forms", [])), "",
           "| 时期 | 段落 | 该期总段落 | 每万段 | 95% 区间 |", "|---|---|---|---|---|"]
    for row in r.get("periods", []):
        ci = row.get("ci_per_10k") or ["", ""]
        out.append(f"| {row['period']} | {row['passages']} | {row['total']} | {row['per_10k']} | {ci[0]}–{ci[1]} |")
    if trend.get("z") is not None:
        out += ["", f"历期趋势（Cochran–Armitage）：z = {trend['z']:.2f}，p = {trend['p']:.3g}"]
    out += ["", "## 早期用例（每部著作一条）", ""] + [f"- {_cite(w, 90)}" for w in r.get("earliest", [])]
    if r.get("collocates"):
        out += ["", "## 各期常见搭配（按相对该词整体的提升度加权）", ""]
        for c in r["collocates"]:
            out.append(f"- {c['period']}：" + "、".join(f"{x['term']}（{x['count']}）" for x in c["top"][:8]))
    if r.get("dense_books"):
        out += ["", "## 论述最密的著作", ""]
        out += [f"- 《{d['title']}》（{d.get('dynasty') or ''}）：{d['passages']} 段，占全书 {d['share']:.1%}" for d in r["dense_books"][:10]]
    if r.get("senses"):
        out += ["", "## 历史义项（现代概念仅为候选，不等同）", ""]
        for s in r["senses"]:
            cands = "、".join(c.get("label", c.get("concept_id", "")) if isinstance(c, dict) else str(c) for c in s.get("candidates", []))
            out.append(f"- {s['label']}：{s['gloss']}" + (f"（候选：{cands}）" if cands else ""))
    return out + ["", f"> {r.get('notice', '')}"]


def taboo(r: dict[str, Any]) -> list[str]:
    if "books" in r:  # survey: the informative cases first — an edition later than the composition
        books = sorted(r["books"], key=lambda b: (not b.get("edited_after_composition"), b.get("title", "")))
        n = sum(1 for b in books if b.get("edited_after_composition"))
        out = ["# 避讳断代：全库概览", "", f"{len(books)} 部著作中，{n} 部的避讳用字表明其传本（刻本/抄本）晚于成书年代。", "",
               "| 著作 | 来源 | 成书 | 版本下限（据避讳） | 依据 | 避 | 未避 |", "|---|---|---|---|---|---|---|"]
        for b in books[:120]:
            comp = b.get("composition") or []
            out.append(f"| {b.get('title', '')} | {b.get('source', '')} | {'–'.join(str(int(x)) for x in comp) if comp else ''} | "
                       f"{b.get('edition_floor') or '—'}{'（晚于成书）' if b.get('edited_after_composition') else ''} | {b.get('decisive') or ''} | "
                       f"{len(b.get('avoided', []))} | {len(b.get('not_avoided', []))} |")
        return out + ["", "> 避讳证据只能说明版本（刻本/抄本）的年代下限，不等于成书年代；属提示性证据。"]
    comp = r.get("composition") or []
    out = [f"# 避讳断代：《{r.get('title', r.get('book_id', ''))}》", "",
           f"成书：{'–'.join(str(int(x)) for x in comp) if comp else '未定'}；来源 {r.get('source', '')}；{r.get('characters', 0)} 字。",
           f"版本下限（据避讳）：{r.get('edition_floor') or '无明确证据'}" + (f"，依据{r['decisive']}" if r.get("decisive") else "")
           + ("；晚于成书年代，当为后世刻本/抄本所改" if r.get("edited_after_composition") else ""), "",
           "| 讳 | 始讳 | 本字形 | 讳改形 | 讳改比例 | 判定 | 例 |", "|---|---|---|---|---|---|---|"]
    for v in r.get("rules", []):
        ex = "、".join(f"{k}{n}" for k, n in (v.get("examples") or {}).items())
        out.append(f"| {v.get('ruler', v.get('rule'))}（{v.get('char', '')}） | {v.get('from', '')} | {v.get('original', 0)} | "
                   f"{v.get('substitute', 0)} | {v.get('ratio', '')} | {v.get('verdict', '')} | {ex} |")
    return out + ["", "> 避讳证据只能说明版本（刻本/抄本）的年代下限，不等于成书年代；属提示性证据。"]


def citations(r: dict[str, Any]) -> list[str]:
    if "citing_books" in r:  # reception of one work or physician
        out = [f"# 引用接受史：{r.get('target')}", ""]
        if r.get("person"):
            ps = r["person"]
            out += [f"{ps.get('name')}（{ps.get('dynasty', '')}，{'、'.join(ps.get('names', []))}）", ""]
        out += ["| 时期 | 引用次数 |", "|---|---|"] + [f"| {k} | {v} |" for k, v in (r.get("by_period") or {}).items()]
        out += ["", "## 引用者（按引用所在时期、成书年代排列）", ""]
        out += [f"- 《{c['title']}》（{c.get('period') or _years(c)}{'，' + str(c['copies']) + ' 个本子' if c.get('copies', 1) > 1 else ''}）：{c['citations']}"
                for c in r.get("citing_books", [])[:30]]
        return out
    later = r.get("set_aside_later_layers") or {}
    out = ["# 引书与引人：各期被引最多的著作与医家", "",
           f"扫描 {r.get('passages_scanned', '')} 段；本书自引、同书他本互引、作者自称均已排除。"
           + (f"被引者晚于引用所在时期的 {sum(later.values()):.0f} 次（多为注本中后人按语，随正文断代）另计，不入各期统计。" if later else ""), ""]
    for per in r.get("periods", []):
        out.append(f"## {per['period']}")
        out.append("- 著作：" + "、".join(f"《{x['title']}》{x['citations']:.0f}" for x in per.get("books", [])[:10]))
        out.append("- 医家：" + "、".join(f"{x['name']} {x['citations']:.0f}" for x in per.get("persons", [])[:10]))
        out.append("")
    if r.get("lineage"):
        out += ["## 医家引称（甲引乙）", ""] + [f"- {e['from']} → {e['to']}：{e['citations']}" for e in r["lineage"][:30]]
    return out


def cards(r: dict[str, Any]) -> list[str]:
    out = [f"# 学习卡片（{r.get('count', 0)} 张）", ""]
    for c in r.get("cards", []):
        out += [f"**{c['type']}** {c['front']}", "", f"<details><summary>答案</summary>{c['back'].replace(chr(10), '<br>')}"
                f"<br><small>{c['source']} · {c['passage_id']}</small></details>", ""]
    return out


def reading(r: dict[str, Any]) -> list[str]:
    out = [f"# 阅读门径：{r['topic']}", ""]
    for st in r.get("stages", []):
        out += [f"## {st['stage']}", f"_{st.get('note', '')}_", ""]
        for b in st.get("books", []):
            out.append(f"- 《{b['title']}》（{b.get('dynasty') or ''} {_years(b)}，{'、'.join(b.get('authors', [])[:2])}）—— {b['why']}")
        out.append("")
    return out


PAGES = {"concordance": concordance, "formula": formula, "herb": herb, "term": term, "taboo": taboo, "citations": citations,
         "cards": cards, "reading": reading}


def markdown(kind: str, result: dict[str, Any], signature: dict[str, Any], notice: str = "") -> str:
    lines = PAGES[kind](result)
    return "\n".join(lines + footer(signature, notice, MACHINE)) + "\n"


__all__ = ["PAGES", "footer", "markdown"]
