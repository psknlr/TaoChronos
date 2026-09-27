"""Warrants: how a hypothesis is inferred from its evidence, and what could still defeat it.

Evidence → interpretation → inference.  A quote is evidence; a claim is an interpretation of it; a hypothesis is an
inference over claims and statistics.  The **warrant** makes the last step inspectable: the kind of inference, its
premises, the assumptions it needs beyond them, the rival explanations that would account for the same evidence (each
with a test that would tell them apart and its current status), the defeaters (open objections), the evidence for
and against, the scope within which it holds, and what remains uncertain.

Each discovery type has rival explanations that must be addressed — a decline in the texts can be a gap in coverage,
a change of genre, a renaming, an omission in transcription, or the survival of some books and not others.
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import Model, field_dict, field_list

# how a hypothesis of each kind reasons from its evidence
INFERENCE_BY_KIND = {
    "lost_knowledge": "absence",  # an argument from silence: later texts do not state it
    "historical_testimony": "testimony",  # a text says the use changed
    "concept_drift": "statistical_comparison",  # context distributions differ between periods
    "association_rule": "statistical_association",
    "hidden_association": "abduction",  # a link the graph suggests, stated nowhere
    "formula_evolution": "lineage",  # compositions derive from one another
    "renaming": "lineage",
    "lost_source": "abduction",  # citations point to a book no longer extant
    "contradiction": "comparison",
    "cross_space_bridge": "analogy",  # a historical description resembles a modern concept
}

# the assumptions each inference needs beyond its premises
ASSUMPTIONS_BY_KIND = {
    "absence": ["the surveyed later texts represent the later literature on this subject",
                "the later texts would name the association in words the extractor reads"],
    "testimony": ["the witness reports the practice of its time, not a literary topos"],
    "statistical_comparison": ["claims are extracted with the same reliability in every period",
                               "the term is resolved to the right sense in each context"],
    "statistical_association": ["co-occurrence in indications reflects use, not the layout of one book"],
    "abduction": ["the graph's paths reflect shared use, not only frequent vocabulary"],
    "lineage": ["the dates of the witnesses are right", "similar compositions are copied, not convergent"],
    "comparison": ["the two passages speak of the same thing under the same conditions"],
    "analogy": ["a historical description can be compared with a modern category without equating them"],
}

# the discovery type of each hypothesis kind, and the rival explanations that type must address
DISCOVERY_TYPE = {
    "lost_knowledge": "decline", "historical_testimony": "decline", "concept_drift": "semantic_change",
    "contradiction": "conflict", "hidden_association": "new_use", "association_rule": "new_use",
    "formula_evolution": "influence", "renaming": "influence", "lost_source": "influence", "cross_space_bridge": "bridge",
}

ALTERNATIVES: dict[str, list[dict[str, str]]] = {
    "decline": [
        {"id": "coverage", "label": "后世文献覆盖不足", "test": "按时期统计研究范围内的文本量；覆盖薄弱时“不再出现”无证据力"},
        {"id": "genre", "label": "文献类型更替（方书→医论/本草）", "test": "仅在同一文献类型内比较前后时期"},
        {"id": "renaming", "label": "改名或换称，而非失传", "test": "检索同义词、避讳改名与后世新名"},
        {"id": "transcription_omission", "label": "转录时漏抄", "test": "比对转录前代文本的后世文本是否保留该条"},
        {"id": "survival_bias", "label": "存世偏差：早期证据只来自少数存世书", "test": "早期支持是否来自两个以上独立源流"},
    ],
    "semantic_change": [
        {"id": "version", "label": "版本异文造成的差异", "test": "在同一版本系统内比较"},
        {"id": "school", "label": "学派用法不同，而非时代变化", "test": "按学派分层后差异是否仍在"},
        {"id": "quotation_share", "label": "后世用例多为转引前代", "test": "剔除转录与改写的用例后重新估计"},
        {"id": "genre", "label": "文献类型更替", "test": "仅在同一文献类型内比较"},
    ],
    "conflict": [
        {"id": "speaker", "label": "说话者不同（引述他说、或曰）", "test": "核对两说是否为作者本人立场"},
        {"id": "conditions", "label": "适用条件不同", "test": "比较两说的条件从句（若…者、凡…）"},
        {"id": "stage", "label": "病程阶段不同", "test": "比较两说的时间与病程标记（初起、日久）"},
        {"id": "editorial_insertion", "label": "后人增补的文字", "test": "核对文本层次（注文、按语、后世补入）"},
    ],
    "new_use": [
        {"id": "same_name_other_formula", "label": "同名异方", "test": "比较各处方名下的组成"},
        {"id": "same_formula_other_name", "label": "同方异名", "test": "按组成而非方名归并后重新统计"},
        {"id": "single_case", "label": "仅一例或一书", "test": "是否有两个以上独立源流"},
        {"id": "quotation_duplication", "label": "同一记载被反复转引", "test": "剔除转引后是否仍成立"},
    ],
    "influence": [
        {"id": "common_ancestor", "label": "二者共同源于更早的文本", "test": "寻找二者共同引用的更早文本"},
        {"id": "reversed_chronology", "label": "年代先后可能颠倒", "test": "核对成书年代区间是否重叠"},
        {"id": "common_vocabulary", "label": "仅因常用词汇而相似", "test": "剔除高频通用词后相似度是否仍在"},
        {"id": "indirect_citation", "label": "经中间文本间接引用", "test": "检查中间文本的引用链"},
    ],
    "bridge": [
        {"id": "same_name_other_thing", "label": "同名异物（古今所指不同）", "test": "本草考证确定物种与概念对应"},
        {"id": "inspired_not_validated", "label": "现代研究受古籍启发而非验证其用法", "test": "区分线索来源与验证证据"},
    ],
}


@dataclass(kw_only=True)
class CompetingExplanation(Model):
    id: str
    label: str
    status: str  # excluded (a check rules it out) | open (it could still explain the evidence) | not_applicable | unaddressed
    test: str = ""  # the observation that would tell it apart from the hypothesis
    basis: str = ""  # why it is excluded, or what keeps it open
    evidence_ids: list[str] = field_list()


@dataclass(kw_only=True)
class Warrant(Model):
    id: str
    hypothesis_id: str
    hypothesis_version: str
    inference: str
    discovery_type: str
    premises: list[dict] = field_list()  # [{id, kind: evidence|observation|analysis, role}]
    assumptions: list[str] = field_list()
    competing: list[CompetingExplanation] = field_list()
    defeaters: list[dict] = field_list()  # [{objection_id, check, severity, status}]
    supporting: list[str] = field_list()
    opposing: list[str] = field_list()
    scope: dict = field_dict()  # {corpus, periods, qualifiers, families}
    uncertainties: list[str] = field_list()
    analyses: dict = field_dict()  # discriminating analyses run for the rivals (re-estimates, within-family checks)
    strength: str = "consistent_with"  # consistent_with | supported | robust — qualitative, from rules, not a probability

    def open_alternatives(self) -> list[CompetingExplanation]:
        return [c for c in self.competing if c.status in ("open", "unaddressed")]


__all__ = ["ALTERNATIVES", "ASSUMPTIONS_BY_KIND", "CompetingExplanation", "DISCOVERY_TYPE", "INFERENCE_BY_KIND", "Warrant"]
