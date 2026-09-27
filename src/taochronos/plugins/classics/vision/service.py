"""The ``vision`` capability: layout, reading and comparison of page images (T1–T2) over the study layer's corpus."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from .formats import read_file, read_tokens
from .layout import Token, analyse
from .ocr import compare, read_image

HAN = re.compile(r"[㐀-鿿]")


class VisionService:
    def __init__(self, study: Any) -> None:
        self.study = study

    def layout(self, tokens: list[dict[str, Any]] | list[Token] | None = None, *, path: str | None = None,
               fmt: str | None = None, page: dict[str, Any] | None = None) -> dict[str, Any]:
        """The PageGraph of a page from an OCR engine's output (a file, or tokens {text, bbox})."""
        if path:
            toks = read_file(path, fmt)
            page = {"source": str(path), **(page or {})}
        elif tokens and isinstance(tokens[0], Token):
            toks = list(tokens)  # type: ignore[arg-type]
        else:
            toks = read_tokens(tokens or [])
        return analyse(toks, page=page).to_dict()

    def read(self, image: str | bytes, media_type: str | None = None, *, hint: str = "") -> dict[str, Any]:
        """A vision model's reading of a page image (needs a judge whose model takes images)."""
        judge = self.study.judge
        if judge is None:
            raise ValueError("reading an image needs a model that takes images: --llm provider:model")
        if isinstance(image, (str, Path)):
            path = Path(image)
            data = path.read_bytes()
            media_type = media_type or ("image/png" if path.suffix.lower() == ".png" else "image/jpeg")
        else:
            data = image
        return read_image(judge, data, media_type or "image/jpeg", hint=hint)

    def locate(self, text: str, *, probes: int = 16, width: int = 3) -> list[str]:
        """The passages an OCR text most likely transcribes: three-character probes spread over it (a probe that crosses a
        mark of the transcription finds nothing, so many are sent), voted."""
        han = "".join(HAN.findall(self.study.normalize(text)))
        if len(han) < width:
            return []
        step = max(1, (len(han) - width) // max(1, probes - 1))
        votes: Counter[str] = Counter()
        for k in range(0, len(han) - width + 1, step):
            for pid in self.study.find(han[k: k + width], limit=40):
                votes[pid] += 1
        return [pid for pid, _ in votes.most_common(3)]

    def compare(self, text: str, *, passage_id: str | None = None, reference: str | None = None) -> dict[str, Any]:
        """An OCR text against a transcription of the store (a passage, found by probes when not given) or a reference."""
        located: list[str] = []
        if reference is None:
            if passage_id:
                located = [passage_id]
            else:
                located = self.locate(text)
            if not located:
                raise ValueError("no transcription in the store carries this text (give --passage or a reference)")
            best = self.study.passages(located[:1])[0]
            parts = [best.text]
            if len(HAN.findall(text)) > 1.3 * len(HAN.findall(best.text)):
                parts += [p.text for p in self.study.following(best, 2)]
            reference = "".join(parts)
            out = compare(text, reference, self.study.normalize)
            out["reference"] = self.study.witness(best)
        else:
            out = compare(text, reference, self.study.normalize)
        out["located"] = located
        out["note"] = ("differences are OCR errors or real differences between the print and the transcription: read "
                       "them against the image; variant forms alone are counted apart (variant_only)")
        return out


__all__ = ["VisionService"]
