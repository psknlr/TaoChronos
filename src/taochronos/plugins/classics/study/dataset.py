"""研究数据集 — the study results as open tables for modern research (FAIR: findable, accessible, interoperable,
reusable).

``tables(...)`` turns study results into flat rows — one row per witness, ingredient, drug entry, period or citation
edge — each with the passage id, locator, date range and the licence of the transcription it comes from.
``write_datapackage`` writes them as CSV with a ``datapackage.json`` (Frictionless Data Package): field types, the
sources and licences involved, the corpus signature and the metrology notice.  Only short quotes are exported, never
the texts; the licences of some transcriptions allow local research use only.
"""

from __future__ import annotations

import csv
import datetime as _dt
import json
from pathlib import Path
from typing import Any

SCHEMAS: dict[str, list[tuple[str, str, str]]] = {
    "formula_witnesses": [("formula", "string", "方名（检索名）"), ("name_form", "string", "原文方名"), ("group", "string", "组成类别（原方/通行方/加减化裁/同名异方/孤例）"),
                          ("book_id", "string", ""), ("title", "string", "书名"), ("year_start", "integer", ""), ("year_end", "integer", ""),
                          ("period", "string", "时期"), ("locator", "string", "出处"), ("passage_id", "string", ""),
                          ("herbs", "string", "药味（规范名，以、分隔）"), ("preparation", "string", "煎服法"), ("indication", "string", "主治"),
                          ("quote", "string", "原文（节录）"), ("license", "string", "录文授权")],
    "formula_ingredients": [("formula", "string", ""), ("passage_id", "string", ""), ("year_start", "integer", ""), ("period", "string", ""),
                            ("order", "integer", "药序"), ("herb", "string", "规范药名"), ("surface", "string", "原文药名"),
                            ("dose", "string", "原文剂量"), ("liang", "number", "折合当时之两（重量）"),
                            ("grams_low", "number", "学界估值下限（克）"), ("grams_high", "number", "学界估值上限（克）"),
                            ("processing", "string", "炮制/注")],
    "herb_entries": [("herb", "string", ""), ("book_id", "string", ""), ("title", "string", ""), ("year_start", "integer", ""),
                     ("year_end", "integer", ""), ("period", "string", ""), ("flavor", "string", "味"), ("nature", "string", "性"),
                     ("toxicity", "string", "毒性"), ("channels", "string", "归经"), ("direction", "string", "升降浮沉"),
                     ("indication", "string", "主治（节录）"), ("aliases", "string", "一名"), ("locator", "string", ""),
                     ("passage_id", "string", ""), ("license", "string", "")],
    "term_periods": [("term", "string", ""), ("period", "string", ""), ("passages", "integer", "含该词段落"),
                     ("total", "integer", "该期段落总数"), ("per_10k", "number", "每万段"), ("ci_low", "number", "95%区间下限（每万段）"),
                     ("ci_high", "number", "95%区间上限（每万段）")],
    "citation_edges": [("period", "string", "引用所在时期"), ("kind", "string", "book|person"), ("cited", "string", "被引著作或医家"),
                       ("citations", "number", "引用次数（按候选权重）")],
}


def tables(formulas: list[dict[str, Any]] = (), herbs: list[dict[str, Any]] = (), terms: list[dict[str, Any]] = (),
           citations: dict[str, Any] | None = None, metrology: Any = None) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {k: [] for k in SCHEMAS}
    for res in formulas:
        name = res["formula"]["name"]
        group_of: dict[str, str] = {}
        for g in res.get("groups", []):
            for pid in g.get("member_ids") or [g["earliest"]["passage_id"]]:
                group_of.setdefault(pid, g["relation"])
        for w in res.get("witnesses", []):
            ys = w.get("years") or [None, None]
            out["formula_witnesses"].append({
                "formula": name, "name_form": w.get("name_form", ""), "group": group_of.get(w["passage_id"], ""),
                "book_id": w["book_id"], "title": w["title"], "year_start": ys[0], "year_end": ys[1], "period": w.get("period"),
                "locator": w["locator"], "passage_id": w["passage_id"], "herbs": "、".join(i["term"] for i in w["ingredients"]),
                "preparation": w.get("preparation", ""), "indication": w.get("indication", ""), "quote": w["quote"][:120],
                "license": w.get("license", "")})
            for k, i in enumerate(w["ingredients"], 1):
                conv = metrology.convert(i["dose"], ys[0]) if metrology is not None and ys[0] is not None else None
                out["formula_ingredients"].append({
                    "formula": name, "passage_id": w["passage_id"], "year_start": ys[0], "period": w.get("period"), "order": k,
                    "herb": i["term"], "surface": i["surface"], "dose": i["dose"],
                    "liang": (conv or {}).get("liang"), "grams_low": ((conv or {}).get("grams") or [None, None])[0],
                    "grams_high": ((conv or {}).get("grams") or [None, None])[1], "processing": i.get("processing", "")})
    for res in herbs:
        for r in res.get("entries", []):
            ys = r.get("years") or [None, None]
            out["herb_entries"].append({
                "herb": res["herb"]["name"], "book_id": r["book_id"], "title": r["title"], "year_start": ys[0], "year_end": ys[1],
                "period": r.get("period"), "flavor": r["flavor"], "nature": r["nature"], "toxicity": r["toxicity"],
                "channels": "、".join(r["channels"]), "direction": r["direction"], "indication": r["indication"][:80],
                "aliases": "、".join(r["aliases"]), "locator": r["locator"], "passage_id": r["passage_id"], "license": r.get("license", "")})
    for res in terms:
        for row in res.get("periods", []):
            ci = row.get("ci_per_10k") or [None, None]
            out["term_periods"].append({"term": res["term"]["name"], "period": row["period"], "passages": row["passages"],
                                        "total": row["total"], "per_10k": row["per_10k"], "ci_low": ci[0], "ci_high": ci[1]})
    if citations:
        for per in citations.get("periods", []):
            for x in per.get("books", []):
                out["citation_edges"].append({"period": per["period"], "kind": "book", "cited": x["title"], "citations": x["citations"]})
            for x in per.get("persons", []):
                out["citation_edges"].append({"period": per["period"], "kind": "person", "cited": x["name"], "citations": x["citations"]})
    return {k: v for k, v in out.items() if v}


def write_datapackage(path: str | Path, rows: dict[str, list[dict[str, Any]]], *, name: str, title: str,
                      signature: dict[str, Any], licenses: list[str], notice: str = "") -> dict[str, Any]:
    root = Path(path)
    root.mkdir(parents=True, exist_ok=True)
    resources = []
    for table, data in rows.items():
        fields = SCHEMAS[table]
        with open(root / f"{table}.csv", "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[fname for fname, _, _ in fields], extrasaction="ignore")
            writer.writeheader()
            writer.writerows(data)
        resources.append({"name": table, "path": f"{table}.csv", "format": "csv", "encoding": "utf-8", "rows": len(data),
                          "schema": {"fields": [{"name": fname, "type": ftype, **({"description": desc} if desc else {})}
                                                for fname, ftype, desc in fields]}})
    package = {
        "profile": "tabular-data-package", "name": name, "title": title,
        "created": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
        "description": "TaoChronos 治学数据集：由语料库逐字录文计算所得，每行附段落编号与出处，可回查原文。" + (" " + notice if notice else ""),
        "licenses": [{"name": "source-licences", "title": lic} for lic in sorted(set(licenses)) if lic],
        "sources": [{"title": s} for s in signature.get("sources", [])],
        "taochronos": {"corpus": signature},
        "resources": resources,
    }
    (root / "datapackage.json").write_text(json.dumps(package, ensure_ascii=False, indent=1), encoding="utf-8")
    return package


__all__ = ["SCHEMAS", "tables", "write_datapackage"]
