"""识读与比对 — a page image read by a vision model, and any OCR text measured against the transcriptions (T1–T2).

``read_image`` asks a multimodal model (``--llm``, a provider whose model takes images: MiniMax, Poe's vision bots,
LiteLLM back ends, Claude …) to transcribe a page as it is written: every character as printed (variants kept), no
punctuation added, in reading order, with the kind of each block (main text, 双行小注, title, 版心, 书眉).  Its answer
is a reading to check, not a transcription: ``compare`` measures it (or any engine's text) against the store.

``compare`` aligns an OCR text with a reference (a passage, or the stretch of a book it is found in) by edit distance
over the Han characters: the character error rate before and after normalising variants (a 異體 is not an OCR error),
the substitutions an engine makes most, and the differences with their context — where the OCR is wrong, or where the
print and the transcription really differ (a collation of the transcription against the print it claims to transcribe).
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Callable

from ....capabilities.judge import Judge
from ....capabilities.llm import ImageBlock

HAN = re.compile(r"[㐀-鿿\U00020000-\U0002ffff〓□]")
KINDS = ["main", "commentary", "title", "header", "page_number", "margin", "seal"]
READ_SYSTEM = ("你是古籍影像的识读者。逐字转录图中文字：字形照录（异体字、俗字不改为通行字），不加任何标点，不补字、不删字；"
               "按原书阅读顺序（竖排自右向左、自上而下）；双行小注、版心（书名、卷次、叶码）、书眉批注、标题分别标出。"
               "看不清的字写作□。")


def read_image(judge: Judge, data: bytes, media_type: str = "image/jpeg", *, hint: str = "") -> dict[str, Any]:
    schema = {"type": "object", "required": ["blocks"], "properties": {"blocks": {"type": "array", "items": {
        "type": "object", "required": ["kind", "text"], "properties": {"kind": {"enum": KINDS}, "text": {"type": "string"}}}}}}
    prompt = ("转录这一页。" + (f"（参考：{hint}）" if hint else "")
              + " 答案为 {\"blocks\": [{\"kind\": main|commentary|title|header|page_number|margin|seal, \"text\": 原文}]}，按阅读顺序。")

    def check(d: Any) -> list[str]:
        marks = [b["text"] for b in d.get("blocks", []) if re.search(r"[，。、；：？！]", b.get("text", ""))]
        return ["punctuation was added: transcribe the characters only"] if marks else []

    res = judge.ask("vision.read", READ_SYSTEM, prompt, schema=schema, check=check, images=[ImageBlock(data, media_type)],
                    max_tokens=6000)
    if not res.ok:
        return {"ok": False, "error": res.error, "judge": judge.label}
    blocks = res.data["blocks"]
    text = "".join(f"（{b['text']}）" if b["kind"] == "commentary" else b["text"] for b in blocks
                   if b["kind"] in ("main", "commentary", "title"))
    return {"ok": True, "blocks": blocks, "text": re.sub(r"）（", "", text), "judge": judge.label,
            "apparatus": [b for b in blocks if b["kind"] not in ("main", "commentary", "title")],
            "note": "a model's reading of the page, to be checked against the transcriptions (compare), not a transcription"}


def _han(text: str) -> str:
    return "".join(HAN.findall(text))


def _levenshtein_ops(a: str, b: str) -> list[tuple[str, int, int]]:
    """Edit operations turning a (the OCR) into b (the reference): (op, i, j) with op in sub/ins/del."""
    n, m = len(a), len(b)
    if n * m > 4_000_000:  # long texts: difflib's matching blocks (an upper bound on the distance)
        import difflib

        ops = []
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if tag == "equal":
                continue
            for k in range(max(i2 - i1, j2 - j1)):
                i, j = i1 + k, j1 + k
                ops.append(("sub" if i < i2 and j < j2 else "del" if i < i2 else "ins", min(i, n - 1), min(j, m - 1)))
        return ops
    prev = list(range(m + 1))
    back = [[0] * (m + 1) for _ in range(n + 1)]
    for j in range(1, m + 1):
        back[0][j] = 2
    for i in range(1, n + 1):
        cur = [i] + [0] * m
        back[i][0] = 1
        for j in range(1, m + 1):
            cost = prev[j - 1] + (a[i - 1] != b[j - 1])
            dele, ins = prev[j] + 1, cur[j - 1] + 1
            best = min(cost, dele, ins)
            cur[j] = best
            back[i][j] = 0 if best == cost else (1 if best == dele else 2)
        prev = cur
    ops, i, j = [], n, m
    while i > 0 or j > 0:
        move = back[i][j]
        if move == 0:
            if a[i - 1] != b[j - 1]:
                ops.append(("sub", i - 1, j - 1))
            i, j = i - 1, j - 1
        elif move == 1:
            ops.append(("del", i - 1, j))
            i -= 1
        else:
            ops.append(("ins", i, j - 1))
            j -= 1
    return ops[::-1]


def window(ocr: str, reference: str) -> str:
    """The stretch of a (longer) reference an OCR text covers: from the first to the last run it shares with it."""
    import difflib

    a, b = _han(ocr), _han(reference)
    blocks = [m for m in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks() if m.size >= 3]
    if not blocks:
        return b
    first, last = blocks[0], blocks[-1]
    start = max(0, first.b - first.a)
    end = min(len(b), last.b + last.size + (len(a) - last.a - last.size))
    return b[start:end]


def compare(ocr: str, reference: str, normalize: Callable[[str], str] | None = None, *, context: int = 6,
            windowed: bool = True) -> dict[str, Any]:
    """Character error rates of an OCR text against a reference (Han characters only; notes' brackets and marks ignored);
    with ``windowed``, against the stretch of the reference the OCR covers (a page of a longer passage)."""
    a, b = _han(ocr), (window(ocr, reference) if windowed else _han(reference))
    ops = _levenshtein_ops(a, b)
    out: dict[str, Any] = {"ocr_chars": len(a), "reference_chars": len(b),
                           "cer": round(len(ops) / len(b), 4) if b else None,
                           "substitutions": sum(1 for o in ops if o[0] == "sub"),
                           "insertions": sum(1 for o in ops if o[0] == "del"),  # in the OCR, not in the reference
                           "deletions": sum(1 for o in ops if o[0] == "ins")}
    if normalize is not None:
        na, nb = normalize(a), normalize(b)
        if len(na) == len(a) and len(nb) == len(b):
            nops = _levenshtein_ops(na, nb)
            out["cer_normalized"] = round(len(nops) / len(nb), 4) if nb else None
            out["variant_only"] = len(ops) - len(nops)  # differences that are only variant forms (not OCR errors)
    conf = Counter(f"{a[i]}→{b[j]}" for op, i, j in ops if op == "sub")
    out["confusions"] = [{"pair": k, "count": v} for k, v in conf.most_common(20)]
    out["differences"] = [{"op": op, "ocr": a[i] if op != "ins" else "", "reference": b[j] if op != "del" else "",
                           "context": b[max(0, j - context): j] + "【" + (b[j] if op != "del" and j < len(b) else "") + "】"
                                      + b[j + 1: j + 1 + context]}
                          for op, i, j in ops[:200]]
    return out


__all__ = ["KINDS", "compare", "read_image", "window"]
