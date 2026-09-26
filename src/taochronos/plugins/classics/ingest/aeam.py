"""東亜医学協会 (The Association of East-Asian Medicine) · 医学古典テキスト: seven classics as PDF texts.

The association publishes its transcriptions of 素問, 霊枢, 難経, 傷寒論, 金匱要略, 神農本草経 and 扁鵲倉公伝
(https://aeam.jp/koten/), each from a named base edition (顧従徳本, 明無名氏本, 趙開美本, 鄧珍本, 森立之校正本, 嘉永二年影宋本
…), punctuated after the Edo philologists (多紀元堅, 森立之, 渋江抽斎); ``※`` marks a place the editors corrected.
The text of each PDF is read with ``pypdf`` (``pip install -e ".[pdf]"``).

Reading: a line ends where the PDF line ends with a space (a bare line break is a wrap inside the line); every line
is a paragraph, blank lines separate groups; ``◆`` opens a chapter (篇), ``■`` a section; ``●`` opens a formula (…方,
kept with its composition as one prescription) or a drug entry of the 本草经; ``○`` separates the cases of 倉公's
records.  The Japanese editorial lines (any line with kana) are left out, ``※`` is removed (the corrections are counted
in the document's notes), and the stop ``．`` (the editors' single punctuation mark) becomes ``，`` inside a line and
``。`` at its end, so that clauses and sentences read as in the other sources.  The PDFs hold common characters
only: rare ones were typed as look-alikes (``寐咀`` for ``㕮咀``) — the certain substitutions are undone, others remain.

Licence: © 東亜医学協会 — saving and use for non-commercial personal purposes only; no reproduction or
redistribution without permission (https://aeam.jp/terms/).  The classical texts themselves are in the public domain.
Local research use only; exports carry short quotes, never the texts.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from .documents import Block, Document

PAGE = "https://aeam.jp/koten/"
SOURCE = {
    "id": "aeam",
    "name": "東亜医学協会 · 医学古典テキスト（The Association of East-Asian Medicine）",
    "url": PAGE,
    "license": "© 東亜医学協会：限非营利的个人保存与使用，未经许可不得转载、再分发（https://aeam.jp/terms/）；古籍原文属公有领域；仅供本地研究",
    "transcription": "東亜医学協会据所示底本录入（顾从德本、明无名氏本、赵开美本、邓珍本、森立之校正本等），句读参江户考证学派；※为校改处",
    "acquisition": "HTTPS（PDF），本地以 pypdf 抽取文字",
    "edition_name": "東亜医学協会本",
}
TEXTS = {  # file stem → (code, title as the association gives it)
    "somon": ("somon", "素問"),
    "reisu": ("reisu", "霊枢"),
    "nangyo": ("nangyo", "難経"),
    "shanghanlun": ("shanghanlun", "傷寒論"),
    "jinguiyaolue": ("jinguiyaolue", "金匱要略"),
    "shennongbencaojing": ("shennongbencaojing", "神農本草経"),
    "henjyaku": ("henjyaku", "扁鵲倉公列伝"),
}
Log = Callable[[str], None]
# the PDFs hold common characters only: a rare one was typed as a look-alike or a special glyph (a space is left
# where it stood); the substitutions that are certain are undone here
SUBSTITUTIONS = {"寐咀": "㕮咀"}
_KANA = re.compile(r"[぀-ヿ]")
_HAN = re.compile(r"[㐀-鿿\U00020000-\U0003134f]")


def _get(url: str, dest: Path) -> bytes:
    for attempt in range(4):
        p = subprocess.run(["curl", "-sS", "--fail", "-L", "-m", "300", "-A", "TaoChronos corpus fetch (research)", url],
                           capture_output=True)
        if p.returncode == 0:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(p.stdout)
            return p.stdout
        time.sleep(2 ** (attempt + 1))
    raise RuntimeError(f"download failed: {url}: {p.stderr.decode('utf-8', 'replace')[-300:]}")


def fetch(root: Path, log: Log = print) -> dict[str, Any]:
    """Download the PDFs the page links (the seven known texts if the page cannot be read)."""
    root.mkdir(parents=True, exist_ok=True)
    page = _get(PAGE, root / "koten.html").decode("utf-8", "replace")
    links = sorted(set(re.findall(r'href="(https://aeam\.jp/wp/wp-content/uploads/[^"]+\.pdf)"', page)))
    links = [u for u in links if Path(u).stem in TEXTS] or \
        [f"https://aeam.jp/wp/wp-content/uploads/2024/03/{stem}.pdf" for stem in TEXTS]
    files: dict[str, Any] = {}
    for url in links:
        dest = root / Path(url).name
        data = dest.read_bytes() if dest.exists() else _get(url, dest)
        files[dest.stem] = {"url": url, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        log(f"  {dest.name}: {len(data)} bytes")
        time.sleep(0.5)
    return {"page": PAGE, "files": files, "fetched": time.strftime("%Y-%m-%d")}


def _pdf_text(path: Path) -> list[str]:
    try:
        import pypdf
    except ImportError as exc:  # an optional dependency: only this connector needs it
        raise SystemExit('reading the 東亜医学協会 PDFs needs pypdf: pip install -e ".[pdf]"') from exc
    return [p.extract_text() or "" for p in pypdf.PdfReader(str(path)).pages]


def hard_lines(pages: list[str]) -> list[str]:
    """The lines of the text: a line ends where the PDF line ends with a space; a bare break is a wrap (also across
    pages).  Blank lines come out as ``""``."""
    text = ""
    for t in pages:
        text += t if not text or text.endswith((" ", "\n ")) or t.startswith(" ") else t  # pages join like wraps
    out: list[str] = []
    for raw in re.split(r"[ 　]+\n|\n[ 　]*\n", text):
        out.append(re.sub(r"\n", "", raw).strip(" 　"))
    return out


def punctuate(line: str) -> str:
    """The editors' single stop: ``，`` inside the line, ``。`` at its end; spaces the PDF left between characters
    removed; the certain substitutions undone."""
    line = re.sub(r"(?<=\S)[ 　]+(?=\S)", "", line.strip())
    for wrong, right in SUBSTITUTIONS.items():
        line = line.replace(wrong, right)
    line = re.sub(r"．\s*$", "。", line)
    return line.replace("．", "，")


def read_file(path: Path, code: str, title: str) -> Document:
    lines = hard_lines(_pdf_text(path))
    corrections = sum(line.count("※") for line in lines)
    blocks: list[Block] = []
    started = False
    formula: list[str] | None = None

    def close_formula() -> None:
        nonlocal formula
        if formula:
            blocks.append(Block("formula", "　".join(formula)))
        formula = None

    for raw in lines:
        line = raw.replace("※", "").strip(" 　")
        if not line:
            close_formula()
            continue
        if _KANA.search(line) or line.startswith("『") or not _HAN.search(line):
            continue  # the editors' Japanese notes, the title lines, rules of □
        if line.startswith(("◆", "■")):
            close_formula()
            name = re.sub(r"[．。□\s]+$", "", line[1:]).strip("□ ")
            blocks.append(Block("heading", name, level=1 if line.startswith("◆") or not started else 2))
            started = True
            continue
        if line.startswith("●"):
            close_formula()
            body = punctuate(line[1:])
            if re.match(r"^[^，。]{1,20}方[，。]?$", body) or re.match(r"^[^，。]{1,20}方[，。]", body) and code != "shennongbencaojing":
                formula = [body]  # a prescription: its name, then its composition lines
            else:
                blocks.append(Block("para", body))  # a drug entry of the 本草经
            continue
        if line.startswith("○"):
            close_formula()
            line = line[1:]
        text = punctuate(line)
        if formula is not None:
            formula.append(text)
            continue
        if not started:  # front matter: the title block of the edition
            blocks.append(Block("heading", "卷首", level=1))
            started = True
        blocks.append(Block("para", text))
    close_formula()
    return Document(source="aeam", code=code, title=title, blocks=blocks,
                    meta={"notes": f"東亜医学協会校改 {corrections} 处（原标※）"} if corrections else {},
                    punctuation="editorial", url=PAGE, ref=path.name, chartype="traditional")


def read(root: Path) -> list[Document]:
    return [read_file(root / f"{stem}.pdf", code, title) for stem, (code, title) in TEXTS.items() if (root / f"{stem}.pdf").exists()]


__all__ = ["PAGE", "SOURCE", "SUBSTITUTIONS", "TEXTS", "fetch", "hard_lines", "punctuate", "read", "read_file"]
