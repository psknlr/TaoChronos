"""Word counts of the figure legends in paper/legends.md against Nature's 300-word cap."""

from __future__ import annotations

import re
from pathlib import Path

CAP = 300
text = (Path(__file__).resolve().parents[1] / "legends.md").read_text(encoding="utf-8")
over = 0
for block in re.split(r"^## ", text, flags=re.M)[1:]:
    title, _, body = block.partition("\n")
    if not title.startswith(("Fig.", "Extended Data Fig.")):
        continue
    words = len(re.findall(r"[A-Za-z0-9][\w'’–\-.,;:()/%·≈×]*|[一-鿿]+", title + " " + body))
    over += words > CAP
    print(f"{words:4d} {'OVER' if words > CAP else 'ok  '} {title[:70]}")
raise SystemExit(1 if over else 0)
