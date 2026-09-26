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
            level = f"〈{a['label']}〉" if a.get("label") else ""
            out.append(f"- 〔{a.get('kind')}〕{level}底本「{a.get('base', '')}」，{wits}作「{a.get('reading', '')}」")
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


# ------------------------------------------------------------------ 版本谱系
KINDS = {"substitution": "异文", "omission": "脱", "addition": "衍", "transposition": "倒", "mixed": "复合", "orthographic": "用字"}


def _witness_table(r: dict[str, Any]) -> list[str]:
    out = ["| 本 | 书名 | 来源 | 年代 | 覆盖 | 缺文字数 | 增出字数 | 独异 |" + (" 避讳下限 |" if any("edition_floor" in w for w in r.get("witnesses", [])) else ""),
           "|---|---|---|---|---|---|---|---|" + ("---|" if any("edition_floor" in w for w in r.get("witnesses", [])) else "")]
    for w in r.get("witnesses", []):
        floor = f" {int(w['edition_floor'])} |" if w.get("edition_floor") is not None else (" |" if "edition_floor" in w else "")
        out.append(f"| {w['id']}{'（底本）' if w['id'] == r.get('base') else ''} | {w.get('title', '')} `{w.get('book_id') or ''}` | "
                   f"{w.get('source', '')} | {_years(w)} | {w.get('coverage', 0):.0%} | {w.get('lacuna_chars', 0)} | "
                   f"{w.get('structural_chars', 0)} | {w.get('singular_readings', 0)} |{floor}")
    return out


def _units(r: dict[str, Any], n: int = 30) -> list[str]:
    out = ["| 位置 | 类型 | 底本 | 异文（本） |", "|---|---|---|---|"]
    for u in [u for u in r.get("units", []) if not u.get("structural") and u.get("kind") != "orthographic"][:n]:
        readings = "；".join(f"「{x['text'] or '（无）'}」{''.join(x['witnesses'])}" for x in u["readings"][1:])
        out.append(f"| {_q(u.get('locator', ''), 24)} | {KINDS.get(u['kind'], u['kind'])} | {_q(u.get('context', ''), 30)} | {readings} |")
    return out


def variants(r: dict[str, Any]) -> list[str]:
    s = r.get("summary", {})
    kinds = "，".join(f"{KINDS.get(k, k)} {v}" for k, v in (s.get("by_kind") or {}).items())
    out = [f"# 版本谱系·异文：{r.get('work', '')}", "",
           f"底本 {r.get('base')}（坐标系，不代表其读法为是）{r.get('base_characters', 0)} 字；异文单位 {s.get('units', 0)}（{kinds}）；"
           f"计入谱系的实质异文 {s.get('substantive', 0)}，每千字 {s.get('per_1000')}；结构性差异（长段增删）{s.get('structural', 0)}。", ""]
    out += _witness_table(r)
    if r.get("excluded"):
        out += ["", "未参校（与底本重合过少）：" + "、".join(f"{x['title']}（{x['siglum']}）" for x in r["excluded"])]
    if r.get("relations"):
        out += ["", "见证关系：" + "；".join(f"{k} {v}" for k, v in r["relations"].items())]
    if r.get("frequent_substitutions"):
        out += ["", "## 高频单字异文（用字习惯候选，复核后可列入 collation.yaml）", ""]
        for x in r["frequent_substitutions"][:12]:
            out.append(f"- {x['characters']}：{x['units']} 处，如 {'；'.join(_q(c, 24) for c in x['contexts'])}")
    if r.get("by_impact"):
        from ..collation.impact import LABELS

        out += ["", "异文分级：" + "，".join(f"{LABELS.get(k, k)} {v}" for k, v in r["by_impact"].items())]
    if r.get("review_queue"):
        out += ["", "## 复核队列（按影响排序：剂量、否定·情态、方药、证候在前）", "", "| 分级 | 位置 | 底本 | 异文（本） | 依据 |",
                "|---|---|---|---|---|"]
        for q in r["review_queue"][:30]:
            readings = "；".join(f"「{x['text'] or '（无）'}」{''.join(x['witnesses'])}" for x in q["readings"])
            out.append(f"| {q['label']} {q['score']:.2f} | {_q(q.get('locator', ''), 20)} | {_q(q.get('context', ''), 26)} | {readings} | "
                       f"{_q(q['reason'], 30)} |")
    out += ["", "## 异文（前 30 条）", ""] + _units(r)
    return out


def stemma(r: dict[str, Any]) -> list[str]:
    out = variants(r)
    out[0] = f"# 版本谱系：{r.get('work', '')}"
    if r.get("ascii"):
        out += ["", "## 谱系图（邻接法，" + ("以 " + r["root_basis"] if r.get("root_basis") else "") + "定根）", "", "```", r["ascii"], "```",
                "", f"Newick：`{r.get('newick', '')}`"]
    if r.get("groups"):
        out += ["", "## 共同异文分组（候选的共同创新）", "", "| 本 | 支持度 | 例 |", "|---|---|---|"]
        for g in r["groups"][:12]:
            out.append(f"| {''.join(g['witnesses'])} | {g['support']} | {', '.join(g['examples'][:2])} |")
    if r.get("patterns"):
        out += ["", "## 一致模式（所有本都存的异文单位）", ""] + [f"- {p['pattern']}：{p['units']} 处（权重 {p['weight']}）" for p in r["patterns"][:8]]
    if r.get("contamination"):
        out += ["", "## 交叉传抄（contamination）", ""]
        for c in r["contamination"]:
            out.append(f"- {c['witness']} 兼抄 {c['source']}：跨支共同异文支持度 {c['support']}，占其分组证据 {c['share']:.0%}")
    if r.get("conflicts"):
        out += ["", "方向未定的冲突：" + "；".join(f"{''.join(c['witnesses'])}（{c['support']}）" for c in r["conflicts"])]
    if r.get("note"):
        out += ["", f"> {r['note']}"]
    return out


def edition(r: dict[str, Any]) -> list[str]:
    out = [f"# 版本概况：{r.get('work', '')} · {r.get('book')}（{r.get('siglum')}）", "",
           f"独异 {r.get('singular_readings', 0)} 处（每千字 {r.get('singular_per_1000')}）；增出（结构性）{r.get('structural_chars', 0)} 字。", "",
           "| 他本 | 书名 | 每千字差异 |", "|---|---|---|"]
    out += [f"| {a['siglum']} | {a['title']} | {a['differences_per_1000']} |" for a in r.get("agreement", [])]
    if r.get("lacunae"):
        out += ["", "缺文：" + "；".join(f"{x['locator']}（{x['end'] - x['start']} 字）" for x in r["lacunae"][:10])]
    return out


# ------------------------------------------------------------------ 语义复用与思想传播
def reuse(r: dict[str, Any]) -> list[str]:
    if "label" in r and "hits" not in r:  # one pair
        f = r.get("features", {})
        return [f"# 语义复用：{r['label_zh']}（{r['label']}）", "", f"规则：{r['rule']}（置信 {r['confidence']}，{r.get('citation') or ''}）", "",
                *[f"- {x}" for x in r.get("reasons", [])], "", f"复用段：{_q(r.get('where', {}).get('text', ''), 120)}", "",
                "| 特征 | 值 |", "|---|---|", *[f"| {k} | {v} |" for k, v in f.items()]]
    s = r.get("summary", {})
    out = [f"# 语义复用：{_q(r.get('query', ''), 40)}", "",
           f"候选：字面 {r['candidates']['wording']}，概念共现 {r['candidates']['concepts']}，审读 {r['candidates']['examined']}；"
           f"判定复用 {s.get('reuses', 0)} 处（{s.get('works', 0)} 部著作），其中仅由概念检索召回 {s.get('found_by_concepts_only', 0)} 处。", "",
           "类型：" + "，".join(f"{k} {v}" for k, v in (s.get("by_label_zh") or {}).items()), "",
           "| 时期 | 类型 | 引法 | 出处 | 复用段 | 依据 |", "|---|---|---|---|---|---|"]
    for h in r.get("hits", [])[:60]:
        out.append(f"| {h.get('period') or ''} | {h['label_zh']} | {h.get('citation', '')} | {h.get('locator', '')}（{_years(h)}） | "
                   f"{_q(h.get('quote', ''), 50)} | {h['rule']} |")
    if s.get("first_of_each_type"):
        out += ["", "## 各类型最早见", ""]
        for k, w in s["first_of_each_type"].items():
            out.append(f"- {k}：{w['locator']}（{_years(w)}）> {_q(w.get('quote', ''), 60)}")
    out += ["", f"> {r.get('note', '')}"]
    return out


def transmission(r: dict[str, Any]) -> list[str]:
    out = [f"# 思想传播：{r.get('title', '')}", "", f"底本 {'+'.join(r.get('base', []))}，抽取 {len(r.get('clauses', []))} 条经文，"
           f"类型化复用边 {r.get('edges', 0)} 条；同书他本：" + "、".join(f"{k}（{v}）" for k, v in list((r.get("same_work_witnesses") or {}).items())[:6]), "",
           "## 各时期复用方式", "", "| 时期 | 边 | 保留原文 | 改写 | 驳议 |", "|---|---|---|---|---|"]
    for p in r.get("periods", []):
        out.append(f"| {p['period']} | {p['edges']} | {p['retained']:.0%} | {p['transformed']:.0%} | {p['disputed']:.0%} |")
    out += ["", "## 承用最多的著作", "", "| 著作 | 年代 | 经文数 | 主要方式 | 类型分布 |", "|---|---|---|---|---|"]
    for w in r.get("works", [])[:30]:
        labels = "，".join(f"{k} {v}" for k, v in list(w["labels"].items())[:4])
        out.append(f"| {w['title']} | {int(w['year']) if w.get('year') is not None else ''} | {w['clauses']} | {w['dominant_zh']} | {labels} |")
    if r.get("channels"):
        out += ["", "## 传播途径（后世文字更近于中间著作而非原书）", ""]
        for c in r["channels"][:15]:
            out.append(f"- {c['via_title']} → {c['title']}：{c['clauses']} 条经文，相似度高出 {c['closer_by']}")
    if r.get("first_of_each_type"):
        out += ["", "## 各类型最早见", ""] + [f"- {k}：{w['title']}（{int(w['year']) if w.get('year') is not None else ''}）`{w.get('passage_id')}`"
                                          for k, w in r["first_of_each_type"].items()]
    out += ["", f"> {r.get('note', '')}"]
    return out


# ------------------------------------------------------------------ 文本地层
def layers(r: dict[str, Any]) -> list[str]:
    verdict = (f"分层成立（置换检验 p={r['p']}，解释方差 {r['r2']:.1%}，打乱特征后 {r['null_r2']:.1%}）" if r.get("supported")
               else f"分层证据不足（p={r.get('p')}）")
    out = [f"# 文本地层：{r.get('work', '')}", "", f"底本 {'+'.join(r.get('witness', []))}；特征 {r.get('features')}；"
           f"{r.get('k')} 层：{verdict}。", "", "| 层 | 字数 | 占比 | 篇 | 区别性特征 |", "|---|---|---|---|---|"]
    for L in r.get("layers", []):
        feats = "，".join(f"{d['feature']}{'↑' if d['direction'] == 'more' else '↓'}" for d in L.get("distinctive", []))
        out.append(f"| {L['layer']} | {L['chars']} | {L['share']:.0%} | {_q('、'.join(L['chapters']), 120)} | {feats} |")
    if r.get("layer_boundaries"):
        out += ["", "## 层间分界（阅读顺序）", ""] + [f"- {b['before']} ｜ {b['after']}（{b['from_layer']}→{b['to_layer']}）"
                                              for b in r["layer_boundaries"]]
    if r.get("change_points"):
        out += ["", "## 文体突变点（置换检验）", ""] + [f"- {c['before']} ｜ {c['after']}：p={c['p']}（{c.get('method', '')}）"
                                               for c in r["change_points"]]
    if r.get("outliers"):
        out += ["", "## 离群篇章（与全书其余部分的 Delta）", ""] + [f"- {c['chapter']}：z={c['z']}，属第 {c['layer']} 层"
                                                        for c in r["outliers"][:12]]
    out += ["", f"> {r.get('note', '')}"]
    return out


def dating(r: dict[str, Any]) -> list[str]:
    nom = r.get("nominal") or []
    out = [f"# 断代证据：{r.get('work', '')}", "", f"底本 {'+'.join(r.get('witness', []))}；著录年代 "
           f"{f'{int(nom[0])}–{int(nom[1])}' if nom else '未定'}；晚出用语判据：他书始见晚于著录下限 {int(r.get('margin', 0))} 年。", ""]
    for e in r.get("witness_evidence", []):
        out.append(f"- 版本：{e['what']}，不早于 {int(e['after'])} 年")
    out += ["", "## 可能晚于著录年代的篇章", "", "| 篇 | 引书下限 | 晚出用语下限 | 晚出用语 |", "|---|---|---|---|"]
    for x in r.get("later_than_nominal", []):
        out.append(f"| {x['chapter']} | {int(x['after']) if x.get('after') is not None else ''} | "
                   f"{int(x['vocabulary_after']) if x.get('vocabulary_after') is not None else ''} | {'、'.join(x['terms'])} |")
    cited = [(c["chapter"], e) for c in r.get("chapters", []) for e in c.get("evidence", []) if e["kind"] == "citation"]
    if cited:
        out += ["", "## 正文引书", ""] + [f"- {ch}：{e['what']} → {e['target']}（{int(e['after'])}）" for ch, e in cited[:30]]
    out += ["", f"> {r.get('note', '')}"]
    return out


def authorship(r: dict[str, Any]) -> list[str]:
    out = [f"# 作者归属：{r.get('text', '')}", "", f"{r.get('characters', 0)} 字，以虚字频率计 Burrows' Delta（越小越近）。", "",
           "| 候选 | Delta | 与下一名之差 | 候选字数 |", "|---|---|---|---|"]
    out += [f"| {c['candidate']} | {c['delta']} | {c['margin'] if c['margin'] is not None else ''} | {c.get('characters', '')} |"
            for c in r.get("candidates", [])]
    return out + ["", f"> {r.get('note', '')}"]


# ------------------------------------------------------------------ 医案轨迹
OUTCOMES = {"improved": "好转/愈", "unchanged": "未效", "worse": "加重", "died": "死亡", "": "未记", "unrecorded": "未记"}


def cases(r: dict[str, Any]) -> list[str]:
    out = [f"# 医案：{r.get('book') or r.get('disease') or ''}", "", f"{r.get('count', 0)} 案；转归："
           + "，".join(f"{OUTCOMES.get(k, k)} {v}" for k, v in (r.get("outcomes") or {}).items()), "",
           "| 案 | 病家 | 诊次 | 转归 | 首诊脉 | 方 | 首诊 |", "|---|---|---|---|---|---|---|"]
    for c in r.get("cases", [])[:60]:
        v0 = c["visits"][0] if c["visits"] else {}
        pat = "".join(str(x) for x in (c["patient"].get("name", ""), c["patient"].get("age", ""))) or c.get("opener", "")
        forms = "、".join(dict.fromkeys(f for v in c["visits"] for f in v["formulas"]))
        out.append(f"| {c.get('section', '')} | {pat} | {len(c['visits'])} | {OUTCOMES.get(c.get('outcome', ''), '')} | "
                   f"{'、'.join(v0.get('findings', {}).get('pulse', [])[:2])} | {_q(forms, 30)} | {_q(v0.get('quote', ''), 40)} |")
    return out


def trajectories(r: dict[str, Any]) -> list[str]:
    out = [f"# 医案轨迹：{r.get('disease') or r.get('book') or ''}", "",
           f"{r.get('cases', 0)} 案，{r.get('visits', 0)} 诊次；转归：" + "，".join(f"{OUTCOMES.get(k, k)} {v}" for k, v in (r.get("outcomes") or {}).items()),
           "", "来源：" + "、".join(f"{b['title']}（{b['cases']}）" for b in r.get("books", [])[:10]), "",
           "## 常见序列（跨诊次，按医案数）", ""]
    out += [f"- {' → '.join(p['pattern'])}：{p['cases']} 案" for p in r.get("patterns", [])[:15]]
    changes = [t for t in r.get("transitions", []) if not t["same"]]
    out += ["", "## 诊次间的变化（下一诊出现的概率及提升度）", "", "| 本诊 | 下一诊 | 次数 | P | 提升度 |", "|---|---|---|---|---|"]
    out += [f"| {t['from']} | {t['to']} | {t['count']} | {t['p']} | {t['lift']} |" for t in changes[:15]]
    out += ["", "## 与“好转”相关的选择（记录中的关联，非疗效证据）", "", "| 项 | 医案 | 好转率 | 其余医案 | 方向 | p | 显著(BH) |",
            "|---|---|---|---|---|---|---|"]
    out += [f"| {a['item']} | {a['cases']} | {a['rate']:.0%} | {a['rate_without']:.0%} | {a['direction']} | {a['p']} | "
            f"{'是' if a['significant'] else ''} |" for a in r.get("associations", [])[:15]]
    return out + ["", f"> {r.get('note', '')}"]


# ------------------------------------------------------------------ 医理论证
RELATIONS = {"condition": "条件", "consequence": "推论（则）", "inference": "推断（故）", "cause": "病因", "effect": "归因（所致）",
             "treatment": "施治", "define": "界说", "contrast": "转折", "analogy": "取象比类", "rebut": "驳斥", "support": "说理（盖）"}


def argument(r: dict[str, Any]) -> list[str]:
    if "comparison" in r:
        a, b, c = r["a"], r["b"], r["comparison"]
        out = [f"# 医理论证比较：{a['work']} ｜ {b['work']}", "", f"关系分布的 JS 散度 {c['relations_jsd']}，概念三元组 {c['triples_jsd']}。", "",
               "| 关系 | " + a["work"] + "（每千句） | " + b["work"] + "（每千句） |", "|---|---|---|"]
        for rel in RELATIONS:
            if rel in a["per_1000_clauses"] or rel in b["per_1000_clauses"]:
                out.append(f"| {RELATIONS[rel]} | {a['per_1000_clauses'].get(rel, 0)} | {b['per_1000_clauses'].get(rel, 0)} |")
        out += ["", "## 各自的特征（log-odds z，正值偏向前者）", ""] + [f"- {RELATIONS.get(x['item'], x['item'])}：z={x['z']}" for x in c["relations"][:8]]
        out += [f"- {' → '.join(x['item'])}：z={x['z']}" for x in c["triples"][:8]]
        return out + ["", f"> {r.get('note', '')}"]
    if "per_1000_clauses" in r:
        out = [f"# 医理论证：{r['work']}", "", f"{r['passages']} 段，{r['clauses']} 句，{r['edges']} 条论证关系。", "",
               "| 关系 | 每千句 | 例 |", "|---|---|---|"]
        for rel, v in r["per_1000_clauses"].items():
            ex = (r["examples"].get(rel) or [{}])[0]
            out.append(f"| {RELATIONS.get(rel, rel)} | {v} | {_q(ex.get('from', ''), 16)} →（{ex.get('marker', '')}）{_q(ex.get('to', ''), 16)} |")
        out += ["", "## 概念之间的论证（类别 —关系→ 类别）", ""] + [f"- {t['from']} —{RELATIONS.get(t['relation'], t['relation'])}→ {t['to']}：{t['count']}"
                                                         for t in r["triples"][:15] if t["from"] != "—" or t["to"] != "—"]
        out += ["", "## 论证链", ""] + [f"- {' → '.join(RELATIONS.get(x, x) for x in ch['chain'])}：{ch['count']}" for ch in r["chains"][:10]]
        return out + ["", f"> {r.get('note', '')}"]
    out = [f"# 医理论证：{_q(r.get('text', ''), 40)}", "", "| # | 句 | 概念 |", "|---|---|---|"]
    out += [f"| {i} | {c['text']} | {'、'.join(f'{t}（{k}）' for t, k in c['concepts'])} |" for i, c in enumerate(r.get("clauses", []))]
    out += ["", "## 论证关系", ""] + [f"- {e['source']} —{RELATIONS.get(e['relation'], e['relation'])}（{e['marker']}）→ {e['target']}" for e in r.get("edges", [])]
    return out


# ------------------------------------------------------------------ 语义演变 · 佚书辑佚
def senses(r: dict[str, Any]) -> list[str]:
    out = [f"# 语义演变：{r['term']}", "", f"{r['occurrences']} 处用例（按时期抽样），{r['assigned']} 处由义项线索判定。", ""]
    if r.get("senses"):
        out += ["## 义项", ""] + [f"- **{s['label']}**（{s['id']}）：{s.get('gloss', '')}" for s in r["senses"]] + [""]
    names = [s["id"] for s in r.get("senses", [])] + ["unassigned"]
    out += ["| 时期 | 用例 | " + " | ".join(n.split("#")[-1] for n in names) + " |", "|---|---|" + "---|" * len(names)]
    for row in r.get("series", []):
        out.append(f"| {row['period']} | {row['occurrences']} | " + " | ".join(f"{row['shares'].get(n, 0):.0%}" for n in names) + " |")
    if r.get("change_points"):
        out += ["", "## 转变点（二分切分，逐段置换检验）", ""]
        for cp in r["change_points"]:
            short = lambda d: "，".join(f"{k.split('#')[-1]} {v}" for k, v in d.items())  # noqa: E731
            out.append(f"- 约 {int(cp['year'])} 年（p={cp['p']}）：之前 {short(cp['before'])}；之后 {short(cp['after'])}")
    if r.get("candidate_senses"):
        out += ["", "## 候选新义（未被现有义项覆盖的用例聚类，须人工判读）", ""]
        for c in r["candidate_senses"]:
            words = "、".join(d["token"] for d in c["distinctive"][:8])
            ex = (c["examples"][0].get("quote") or c["examples"][0]["context"]) if c["examples"] else ""
            out.append(f"- {c['size']} 例（{c['span'][0] if c['span'] else ''}–{c['span'][1] if c['span'] else ''}）：{words}　例：{_q(ex, 40)}")
    if r.get("neighbourhood"):
        out += ["", "## 语境邻域的变化", ""] + [f"- {n['period']}（{n['contexts']}）：{'、'.join(n['frequent'][:8])}"
                                          + (f"；与前期重合 {n['overlap_with_previous']:.0%}" if n["overlap_with_previous"] is not None else "")
                                          for n in r["neighbourhood"]]
    ex = r.get("exemplar_check") or {}
    if ex.get("checked"):
        out += ["", f"义项范例核对：{ex['agree']}/{ex['checked']} 与所定义项一致。"]
    return out + ["", f"> {r.get('note', '')}"]


def _cell(text: Any, n: int = 40) -> str:
    t = str(text or "").replace("|", "／").replace("\n", " ")
    return t if len(t) <= n else t[: n - 1] + "…"


def witnesses(r: dict[str, Any]) -> list[str]:
    out = [f"# 版本与影像见证：{r['work']}", "", f"库中录本 {len(r['text_witnesses'])} 种；影像见证 {r['image_count']} 件"
           f"（含 IIIF 清单 {r['with_manifest']} 件）", "", "## 库中录本", "", "| 录本 | 版本 | 版本年代 | 藏所 | 来源 | 段落 | 页面影像 |",
           "|---|---|---|---|---|---|---|"]
    for t in r["text_witnesses"]:
        yrs = "–".join(str(y) for y in dict.fromkeys(t["edition_years"] or [])) or "?"
        out.append(f"| 《{t['title']}》 | {_cell(t['edition'], 60)} | {yrs} | {t.get('holding') or ''} | {t['source']} | "
                   f"{t['passages'] or ''} | {'有' if t['page_images'] else ''} |")
    if r["image_witnesses"]:
        out += ["", "## 影像见证（按标题关联，须核对）", "", "| 题名 | 年代 | 刊/写 | 藏所 | 索书号 | 关联方式 | 授权 |", "|---|---|---|---|---|---|---|"]
        for w in r["image_witnesses"][:80]:
            link = f"[{_cell(w['title'], 30)}]({w['page']})" if w.get("page") else _cell(w["title"], 30)
            out.append(f"| {link} | {w.get('years') or _cell(w.get('date', ''), 20)} | {w.get('kind', '')} | {_cell(w['holder'], 30)} | "
                       f"{_cell(w.get('shelfmark', ''), 24)} | {w.get('match', '')} | {_cell(w.get('rights', ''), 30)} |")
        out += ["", "各藏所件数：" + "，".join(f"{k} {v}" for k, v in r["holders"].items())]
    return out + ["", f"> {r['note']}"]


def fragments(r: dict[str, Any]) -> list[str]:
    out = [f"# 佚书辑佚：{r['work']}", "", f"引称：{'、'.join(r.get('forms', []))}；{r['quotations']} 处引文，合并为 {r['count']} 条佚文，"
           f"{r['characters']} 字；引用之书：" + "、".join(f"{k}（{v}）" for k, v in list(r.get("quoted_in", {}).items())[:8]), ""]
    if r.get("by_volume"):
        out += ["按原书卷次（据“出第N卷”）：" + "，".join(f"卷{k} {v} 条" for k, v in r["by_volume"].items()), ""]
    v = r.get("verification")
    if v:
        out += [f"与现存本核对：{v['verified']}/{v['fragments']} 条见于现存本（{v['precision']:.0%}），覆盖现存本 {v['coverage']:.1%}。", ""]
        if v.get("by_quoting_book"):
            out += ["| 引用之书 | 佚文 | 见于现存本 |", "|---|---|---|"] + [f"| {b['book']} | {b['fragments']} | {b['precision']:.0%} |"
                                                               for b in v["by_quoting_book"][:12]] + [""]
    out += ["| 卷 | 篇目（引用处） | 佚文 | 出处 |", "|---|---|---|---|"]
    for f in r.get("fragments", [])[:80]:
        wit = "；".join(w["locator"] for w in f["witnesses"][:2])
        out.append(f"| {f['volume'] or ''} | {_q(f.get('topic', ''), 16)} | {_q(f['text'], 50)} | {_q(wit, 40)} |")
    return out + ["", f"> {r.get('note', '')}"]


def _scores(label: str, sc: dict[str, Any] | None) -> str:
    if not sc:
        return f"| {label} | — | — | — | — | — |"
    return (f"| {label} | {sc['boundary_p']:.1%} | {sc['boundary_r']:.1%} | {sc['boundary_f1']:.1%} | {sc['sentence_f1']:.1%} | "
            f"{sc['mark_type_accuracy']:.1%} |")


def punctuate(r: dict[str, Any]) -> list[str]:
    head = r.get("unpunctuated") or r.get("input") or ""
    out = [f"# 句读：{_q(head, 30)}", ""]
    if r.get("passage"):
        out += ["**原文**：" + _cite(r["passage"], 80), ""]
    out += ["## 机器句读", "", "> " + (r.get("punctuated") or "").replace("\n", "\n> "), "",
            f"插入标点 {r.get('inserted', 0)} 处；原字保留：{'是（只插入标点，未改动任何字符）' if r.get('preserved') else '否——请报告此错误'}。"]
    review = r.get("review") or []
    if review:
        doubtful = [x for x in review if x["kind"] == "doubtful"]
        possible = [x for x in review if x["kind"] == "possible"]
        out += ["", f"## 待复核（接近判定阈值：{len(doubtful)} 处断得勉强，{len(possible)} 处几乎要断）", "",
                "| 位置 | 类型 | 标点 | 概率 | 上下文（▲ 为断点） |", "|---|---|---|---|---|"]
        for x in review[:40]:
            out.append(f"| {x['at']} | {'断得勉强' if x['kind'] == 'doubtful' else '可能漏断'} | {x['mark']} | {x['p']:.2f} | {_q(x.get('context', ''), 40)} |")
    head_row = ["| | 断点精确率 | 断点召回率 | 断点 F1 | 句末 F1 | 标点类型准确率 |", "|---|---|---|---|---|---|"]
    if r.get("against_editors"):
        out += ["", "## 与编者句读对照（输入原有标点：去掉后重断，再与原标点比较）", ""] + head_row
        out += [_scores("本模型", r["against_editors"]), _scores("规则基线", r.get("baseline_rules"))]
    m = r.get("measured")
    if m:
        out += ["", f"## 模型的留出评测（{m['works']} 部著作、{m['books']} 种录本、{m['characters']:,} 字，训练时整部留出）", ""] + head_row
        out += [_scores("本模型", m["model"]), _scores("规则基线", m["rules"]),
                _scores("本模型（兼用句、读两类标点的文本）", (m.get("typed") or {}).get("model")),
                "", f"保字率 {m.get('preservation_rate', 0):.0%}（去标点重断后逐字核对）。"]
    bw = r.get("measured_baiwen")
    if bw:
        out += ["", f"## 真实白文上的评测（{len(bw['works'])} 部留出著作的四库白文，与其点校本的标点经对齐比较）", ""] + head_row
        out += [_scores("本模型", bw["model"]), _scores("规则基线", bw["rules"])]
    info = r.get("model") or {}
    out += ["", f"模型 {info.get('version', '')}：训练 {info.get('passages', 0):,} 段 / {info.get('characters', 0):,} 字；"
            f"断点阈值 {info.get('threshold')}，句末阈值 {info.get('threshold_sentence')}。", "", f"> {r.get('method', '')}"]
    if r.get("note"):
        out.append(f"> {r['note']}")
    return out


RELATION_LABELS = {"驳": "驳（明引而驳之）", "从": "从（明引而赞同）", "引": "引（明引）", "照录": "照录（整段相同）",
                   "承袭": "承袭（沿用前注文字）", "自录": "自录（同一注家重出）", "增益": "增益（涵盖前注概念并有新增）",
                   "同解": "同解（新增概念大体相同）", "异解": "异解（新增概念几无重合）"}


def commentaries(r: dict[str, Any]) -> list[str]:
    units = r.get("commentaries") or []
    dated_units = [u["years"] for u in units if u.get("years")]
    span = f"{int(min(y[0] for y in dated_units))}—{int(max(y[1] for y in dated_units))}" if dated_units else "年代未定"
    out = [f"# 集注：{_q(r.get('clause', ''), 40)}", "",
           f"注家 {r.get('count', 0)} 家（{span}）；另有 {r.get('quotation_count', 0)} 处引文（条文见于他书行文中，非注文之首）。"
           f"条文自身概念：{'、'.join(r.get('concepts_in_clause') or []) or '—'}。", "",
           "| 编号 | 年代 | 注家 | 书 | 注文位置 | 新增的诠释概念 | 注文（节录） |", "|---|---|---|---|---|---|---|"]
    layout = {"row": "条后另行", "run_on": "条下接写", "inline": "条中夹注", "anchored": "附于条下"}
    for u in units:
        where = "、".join(dict.fromkeys(layout.get(k, k) for k in u.get("layout", [])))
        out.append(f"| {u['id']} | {_years(u)} | {u['commentator']} | 《{_cell(u['title'], 20)}》 | {where} | "
                   f"{_cell('、'.join(u.get('reading') or []), 40)} | {_q(u.get('quote', ''), 60)} |")
    rels = r.get("relations") or []
    if rels:
        out += ["", "## 注家之间", ""]
        for kind, label in RELATION_LABELS.items():
            group = [x for x in rels if x["type"] == kind]
            if not group:
                continue
            out.append(f"**{label}**")
            for x in group[:12]:
                extra = ""
                if x.get("evidence"):
                    extra = f"：「{_q(x['evidence'], 50)}」"
                elif x.get("share") is not None:
                    extra = f"（共有文字 {x['share']:.0%}，最长连续 {x.get('longest_run', 0)} 字）"
                elif x.get("shared"):
                    extra = f"（共有：{'、'.join(x['shared'][:8])}）"
                elif x.get("a_only") is not None:
                    extra = f"（前者：{'、'.join(x['a_only'][:5])}；后者：{'、'.join(x['b_only'][:5])}）"
                out.append(f"- {x['from']} {x['from_commentator']} → {x['to']} {x['to_commentator']}{extra}")
            out.append("")
    if r.get("consensus"):
        out += ["## 共识（半数以上注家新增的概念）", ""] + [f"- {c['concept']}（{c['group']}）：{c['commentaries']} 家" for c in r["consensus"]] + [""]
    if r.get("first_readings"):
        out += ["## 诠释的源头（首见于哪家注，后来多少家沿用）", "", "| 概念 | 类 | 首见 | 年代 | 后来沿用 |", "|---|---|---|---|---|"]
        out += [f"| {f['concept']} | {f['group']} | {f['commentary']} {f['commentator']} | {_years(f)} | {f['followed_by']} |"
                for f in r["first_readings"][:20]]
    if r.get("unique"):
        by: dict[str, list[str]] = {}
        for x in r["unique"]:
            by.setdefault(f"{x['commentary']} {x['commentator']}", []).append(x["concept"])
        out += ["", "## 独见（仅一家新增的概念）", ""] + [f"- {k}：{'、'.join(v[:10])}" for k, v in list(by.items())[:20]]
    return out + ["", f"> {r.get('note', '')}"]


def disputes(r: dict[str, Any]) -> list[str]:
    if r.get("term") is None and r.get("person") is None:
        out = ["# 争议：全库谁驳谁", "", f"扫描 {r.get('passages_scanned') or 0} 段（引书网络）。", "",
               "| 驳者 | 被驳者 | 驳 | 从 | 引 | 例句 |", "|---|---|---|---|---|---|"]
        for x in r.get("who_rejects_whom", [])[:40]:
            ex = x["examples"][0]["sentence"] if x.get("examples") else ""
            out.append(f"| {x['by']} | {x['target']} | {x['rejections']} | {x['approvals']} | {x['citations']} | {_q(ex, 50)} |")
        if r.get("most_disputed"):
            out += ["", "## 最常被驳的医家", ""] + [f"- {x['target']}：被驳 {x['rejections']} 次（被引 {x['citations']} 次）"
                                                   for x in r["most_disputed"][:20]]
        return out + ["", f"> {r.get('note', '')}"]
    what = "、".join(x for x in (r.get("term"), r.get("person")) if x)
    counts = r.get("counts") or {}
    out = [f"# 争议：{what}", "", f"读 {r.get('passages_scanned', 0)} 段；具名引述 {counts.get('cite', 0)} 处未表态，"
           f"驳 {counts.get('reject', 0)} 处，从 {counts.get('endorse', 0)} 处。", "",
           "| 年代 | 驳者 | 被驳者 | 标记 | 语句 | 出处 |", "|---|---|---|---|---|---|"]
    for d in r.get("disputes", [])[:60]:
        by = d["by"] + (f"（见《{d['reported_in']}》）" if d.get("reported_in") else "")
        out.append(f"| {_years(d)} | {by} | {d['target']} | {d['marker']} | {_q(d['sentence'], 60)} | {_q(d['locator'], 30)} |")
    if r.get("who_rejects_whom"):
        out += ["", "## 谁驳谁", ""] + [f"- {x['by']} → {x['target']}：{x['count']} 处" for x in r["who_rejects_whom"][:20]]
    if r.get("endorsements"):
        out += ["", "## 赞同", ""] + [f"- {_years(d)} {d['by']} → {d['target']}（{d['marker']}）：{_q(d['sentence'], 60)}"
                                      for d in r["endorsements"][:20]]
    if r.get("about"):
        out += ["", "争议所涉概念：" + "、".join(f"{a['concept']}（{a['count']}）" for a in r["about"][:15])]
    if r.get("later_layers"):
        out += ["", f"另有 {len(r['later_layers'])} 处出现在被引者生前的书中（未分离的后人注文），未计入。"]
    return out + ["", f"> {r.get('note', '')}"]


PAGES = {"concordance": concordance, "formula": formula, "herb": herb, "term": term, "taboo": taboo, "citations": citations,
         "cards": cards, "reading": reading, "variants": variants, "stemma": stemma, "edition": edition, "reuse": reuse,
         "transmission": transmission, "layers": layers, "dating": dating, "authorship": authorship, "cases": cases,
         "trajectories": trajectories, "argument": argument, "senses": senses, "fragments": fragments, "witnesses": witnesses,
         "punctuate": punctuate, "commentaries": commentaries, "disputes": disputes}


def markdown(kind: str, result: dict[str, Any], signature: dict[str, Any], notice: str = "") -> str:
    lines = PAGES[kind](result)
    return "\n".join(lines + footer(signature, notice, MACHINE)) + "\n"


__all__ = ["PAGES", "footer", "markdown"]
