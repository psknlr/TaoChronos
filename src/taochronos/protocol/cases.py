"""Case records (医案): a patient's course of illness and treatment, visit by visit.

A case record tells what the physician saw (symptoms, signs, pulse, tongue), how he read it (disease, pattern), what
he meant to do (the principle of treatment) and did (formula, drugs, doses, changes to the last prescription), and
what happened (the response after so many doses, the outcome).  Structured this way, the records of many physicians
become comparable trajectories — which principle follows which, which changes precede recovery — while every field
keeps the passage it was read from.
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import Model, field_dict, field_list


@dataclass(kw_only=True)
class Visit(Model):
    index: int  # 0 = the first visit
    marker: str = ""  # 初诊, 二诊, 又, 十四日, 次日 …: what opened the visit in the text
    findings: dict[str, list[str]] = field_dict()  # symptom, sign, pulse, tongue → what the text records
    diagnosis: list[str] = field_list()  # diseases and patterns named
    principles: list[str] = field_list()  # 治法: 清热, 养阴, 和胃 …
    formulas: list[str] = field_list()
    herbs: list[dict[str, str]] = field_list()  # {"name", "dose"}
    added: list[str] = field_list()  # changes to the previous prescription (加 …)
    removed: list[str] = field_list()  # (去 …)
    doses: str = ""  # 服二剂, 连进三帖 …
    response: str = ""  # improved | unchanged | worse | died (after this visit's treatment), or ""
    response_words: list[str] = field_list()
    passage_ids: list[str] = field_list()
    quote: str = ""  # the start of the visit, ≤ 120 characters


@dataclass(kw_only=True)
class CaseRecord(Model):
    id: str
    book_id: str
    section: str = ""  # the heading the record is filed under (风温, 中风 …)
    patient: dict[str, str] = field_dict()  # name, sex, age — as written
    opener: str = ""  # the words that opened the case
    visits: list[Visit] = field_list()
    outcome: str = ""  # the last response recorded: improved | unchanged | worse | died, or ""
    passage_ids: list[str] = field_list()
    year: float | None = None  # the book's date


__all__ = ["CaseRecord", "Visit"]
