"""What the corpus says of its sources outside the pipeline that ingests them.

The site's corpus (:mod:`.webcorpus`) reads two things of the ingestion's: the works a text cites that the corpus does
not hold, and the terms under which 笈成 releases its texts.  They live here, away from :mod:`.ingest`, so that the
runtime in the browser — which indexes the site's corpus and never ingests a source — does not carry the pipeline with
it (distribution-policy.yaml: ``site.package.never``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...protocol.yamlio import load_yaml

JC_SOURCE = {
    "id": "jicheng",
    "name": "笈成（JiCheng）中医古籍整理本 · 笈成檢閱系統 v1.4.8 资料",
    "url": "https://jicheng.tw/",
    "license": "CC0 1.0（中醫笈成对公有领域古籍的筛选、编排、标点、附注等编辑成果；网站自行创作的内容为 CC BY 4.0；"
               "见 https://jicheng.tw/tcm/copyright.html），使用时请注明来自中醫笈成；古籍原文属公有领域；笈成所据今人辑校、"
               "校注本中的今人成分不在 CC0 之列；当代著作与现代整理本除经审定保留者外不入库（保留者的今人整理成分单列为层或移入元数据）",
    "transcription": "笈成志愿者录入、校对并加新式标点（各书“品质”见 [book] 信息）；未经本项目逐字核对",
}


def load_external_works(path: str | Path) -> list[dict[str, Any]]:
    """``corpus/catalog/external-works.yaml``: works cited in the corpus but not in it (lost, or extant elsewhere)."""
    p = Path(path)
    return list((load_yaml(p) or {}).get("works") or []) if p.exists() else []
