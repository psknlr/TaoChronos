"""A text's work kept for the next time the text comes (TextMemo)."""

from __future__ import annotations

import threading
from typing import Generic, TypeVar

V = TypeVar("V")

# the longest text a memo keeps: a passage of the corpus is at most 900 characters (segment.split_long); a caller's own
# text, through the study tools, can be of any length (100,000 characters prepared cost 11 MB), and is worked each time
LONGEST_KEPT = 2_000


class TextMemo(Generic[V]):
    """What a text's work came to, kept under the text itself — a changed text is another key, never an older entry —
    and only read by those it is handed to.  Bounded twice, by texts and by the characters they hold: everything is
    dropped when the next would pass either.  A text longer than LONGEST_KEPT is never kept.  The server's threads
    share one: what is kept is counted under a lock (the bounds hold exactly), and a text two threads worked at once
    has one value, the first kept."""

    def __init__(self, texts: int, chars: int) -> None:
        self.texts = texts
        self.chars = chars
        self._kept: dict[str, V] = {}
        self._held = 0  # characters, of the texts kept
        self._lock = threading.Lock()

    def get(self, text: str) -> V | None:
        return self._kept.get(text)

    def put(self, text: str, value: V) -> V:
        """Keep ``value`` for ``text`` (unless the text is too long to be), and give back what is kept for it."""
        if len(text) > LONGEST_KEPT:
            return value
        with self._lock:
            if text in self._kept:  # another thread worked the same text meanwhile: its value is the text's
                return self._kept[text]
            if len(self._kept) >= self.texts or self._held + len(text) > self.chars:
                self._kept.clear()
                self._held = 0
            self._kept[text] = value
            self._held += len(text)
        return value

    def clear(self) -> None:
        with self._lock:
            self._kept.clear()
            self._held = 0

    def __len__(self) -> int:
        return len(self._kept)

    def __contains__(self, text: object) -> bool:
        return text in self._kept
