"""The Ancient–Modern Bridge (AMBE): ancient findings → HPO → modern disease profiles, explainably, and back.

See ``docs/bridge.md``.  Data: ``domains/bridge`` (phenotypes, disease profiles, the HPO hierarchy among their terms).
"""

from .data import BridgeData, Disease, Phenotype
from .mapping import rank, reverse, score
from .packet import PacketReader
from .service import BridgeService, render_map, render_reverse

__all__ = ["BridgeData", "BridgeService", "Disease", "PacketReader", "Phenotype", "rank", "render_map", "render_reverse",
           "reverse", "score"]
