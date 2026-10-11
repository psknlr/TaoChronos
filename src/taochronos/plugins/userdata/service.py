"""The ``mydata`` capability — the user's datasets in a runtime and what the tools do with them.

The page adds and removes datasets (``add``, ``remove``, ``clear``; ``export`` and ``restore`` keep them in the browser
between visits); the model reads them through the ``mydata.*`` tools of the mesh, which call the methods below.  Every
result names the dataset by its id and its file name, and every passage or row it quotes by its ``mine:`` id.
"""

from __future__ import annotations

from typing import Any

from . import analysis
from .formats import ACCEPTED, MAX_BYTES
from .rx import PrescriptionReader
from .store import MAX_DATASETS, UserData

HOW = ("我的资料是用户上传的资料，已在本机脱敏；引用其中的段落或行时写 [[mine:…]]。表格：mydata.describe 描述各列，"
       "mydata.compare 比较组间差异，mydata.prescriptions 分析处方列的用药；文本：mydata.search 检索，mydata.read 阅读。")


class MyData:
    """The user's datasets (:class:`~.store.UserData`) with the analyses of :mod:`.analysis` and :mod:`.rx`.  ``study``
    is the classics' study service: its lexicon reads the drugs of a prescription and its compositions are compared."""

    def __init__(self, study: Any | None = None, *, normalize: Any = None) -> None:
        self.reader = PrescriptionReader(study) if study is not None and hasattr(study, "_pairs") else None
        if normalize is None and study is not None:
            normalize = getattr(study, "normalize", None)
        self.store = UserData(normalize=normalize, detect=self.reader.looks_like if self.reader else None)

    # ------------------------------------------------------------ the page
    def add(self, name: str, data: bytes) -> dict[str, Any]:
        return self.store.add(name, data).summary()

    def datasets(self) -> dict[str, Any]:
        return {"datasets": self.store.list(), "limits": {"bytes": MAX_BYTES, "datasets": MAX_DATASETS, "accepted": list(ACCEPTED)}}

    def remove(self, key: str) -> dict[str, Any]:
        ds = self.store.get(key)
        self.store.remove(ds.id)
        return {"removed": ds.id, "name": ds.name}

    def clear(self) -> dict[str, Any]:
        return {"removed": self.store.clear()}

    def export(self, key: str) -> dict[str, Any]:
        return self.store.export(key)

    def restore(self, data: dict[str, Any]) -> dict[str, Any]:
        return self.store.restore(data).summary()

    def card(self, part_id: str) -> dict[str, Any]:
        return self.store.card(part_id)

    # ------------------------------------------------------------ the tools
    def list(self) -> dict[str, Any]:
        sets = self.store.list()
        return {"datasets": sets, "count": len(sets), "how": HOW if sets else "用户还没有上传资料：请他用输入框旁的“上传资料”添加。"}

    def read(self, dataset: str | None = None, *, start: int = 1, limit: int = 20, columns: list[str] | None = None) -> dict[str, Any]:
        return self.store.read(dataset or "", start=start, limit=limit, columns=columns)

    def search(self, query: str, *, dataset: str | None = None, limit: int = 30) -> dict[str, Any]:
        return self.store.search(query, key=dataset or None, limit=limit)

    def describe(self, dataset: str | None = None, columns: list[str] | None = None) -> dict[str, Any]:
        return analysis.describe(self.store.get(dataset or ""), columns)

    def compare(self, outcome: str, group: str, *, dataset: str | None = None) -> dict[str, Any]:
        return analysis.compare(self.store.get(dataset or ""), outcome, group)

    def prescriptions(self, dataset: str | None = None, *, column: str | None = None, group: str | None = None,
                      merge: str = "written", classics: bool = True) -> dict[str, Any]:
        if self.reader is None:
            raise RuntimeError("处方分析需要古籍语料的词表：此运行环境没有")
        return self.reader.analyse(self.store.get(dataset or ""), column, group=group, merge=merge, classics=classics)


__all__ = ["HOW", "MyData"]
