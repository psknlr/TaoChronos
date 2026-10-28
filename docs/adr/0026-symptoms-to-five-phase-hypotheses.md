# ADR 0026 — Symptoms produce separate Five-Phase hypotheses

**Status:** proposed · 2026-10-28

## Context

`study.wuxing` required a named pattern or an organ/phase with a state. A user asking for Five-Phase selection from symptoms
received an error. Inferring one asserted diagnosis from a symptom keyword would bypass the pattern decision in ADR 0025.

## Decision

1. Add a small, deterministic symptom reader and `wuxing-symptoms.yaml`. The initial ten profiles are 肝郁脾虚、肝火上炎、
   脾气虚、脾肺气虚、肝肾阴虚、脾肾阳虚、心脾两虚、肾阴虚、肾阳虚、肺阴虚. Sources retain their disease-specific scope;
   their symptom descriptions are not validated diagnostic criteria. Aliases and grouping thresholds are engineering
   choices requiring clinical review. No diagnostic probability or claimed clinical accuracy is emitted.
2. Accept free text and a `symptoms` list on the existing service, CLI and chat tool. Return at most three independent
   candidates, each with matched groups, missing groups, opposing findings and sources. Report the omitted count and ask
   at most two questions. Unrecognised wording returns clarification, not invented symptoms. This is a bounded vocabulary,
   not a general clinical NLP system.
3. Only a candidate with every independent symptom group present and no conflicting finding receives a conditional
   selection. Reuse the existing named-pattern → state → point-rule engine **inside** that candidate. Inferred states
   never become top-level asserted states. Default to same-channel Nanjing 69 for symptoms, with explicit alternative
   methods supported. Existing stated-pattern inputs retain their default methods. Preserve point code, phase, intention,
   rule, source, cautions and conflicts. Each chart and table labels its hypothesis; candidates are never combined.
4. Respect common clause-scoped negation, uncertainty and historical wording in both symptom and state parsing.
   Explicitly conflicting statements require clarification. Recognised urgent signals (including uncertain urgent
   mentions), pregnancy or possible pregnancy withhold points even alongside an explicit state. These checks are
   deliberately limited and do not establish safety when absent. No needling instructions or dose parameters are added.
5. Fix prerequisites exposed by the new path: reject unknown methods rather than selecting all; distinguish unknown
   virtual state from explicitly stated 不实不虚; do not substitute the representative zang for a fu sharing its phase in
   clarification, classical prerequisites or full strategy matching. These fixes also protect existing state inputs.

## Consequences and validation

`食欲差，便溏，乏力` proposes 脾气虚 and conditionally explains SP2 大都 as the Spleen channel's mother point. `胁胀，爱叹气，便溏`
proposes 肝郁脾虚 and conditionally explains LR2 行间 (reduce the child) and SP2 (reinforce the mother). `头痛` asks for more
information without points. These are software examples, not advice for an individual patient.

Regression tests cover every profile, negation and uncertainty, missing/conflicting findings, urgent/pregnancy gates,
organ identity, unknown versus neutral, method validation, scheduler calls, CLI, rendering and source links. They verify
the software contract; they do not constitute a clinical-validation dataset. The chat prompt passes the user's actual
wording and preserves conditional status. Generated D1 tool/prompt tables are refreshed, but D1 still reports acupuncture
tools unavailable; its data does not implement this engine. Backend deployment is needed before the live chat supports it.
