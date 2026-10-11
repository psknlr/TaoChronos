"""我的资料 — the user's own data, read, made anonymous and analysed where the runtime runs.

* :mod:`.formats` reads a file as text or as a table (TXT, Markdown, Word; CSV, TSV, Excel, JSON);
* :mod:`.deid` takes out what identifies a person (identity card, telephone and record numbers, names, addresses);
* :mod:`.store` keeps the datasets of a runtime, their passages and rows citable (``mine:…``);
* :mod:`.analysis` describes a table's columns and compares groups (Kruskal–Wallis, χ² or Fisher, Spearman), with
  the charts and three-line tables of the study layer.

It reads prescriptions with the classics' lexicon (:mod:`.rx`: drugs, their families and doses) and sets them beside
the compositions written in the classics.  The chat runtime registers a store as the ``mydata`` capability, and the
tool mesh offers it to the model as the ``mydata.*`` tools.
"""

from .formats import MAX_BYTES, Unreadable
from .store import Dataset, UserData

__all__ = ["MAX_BYTES", "Dataset", "Unreadable", "UserData"]
