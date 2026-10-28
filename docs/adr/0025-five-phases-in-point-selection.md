# ADR 0025 — The Five Phases in point selection: two decisions between a relation and a point, the levels apart

**Status:** accepted · 2026-10-27

## Context

ADR 0024 put the specific-point system, mother–child points included, into `study.acupoints`.  A revision asked for the
Five Phases (Wu Xing 五行) and the Five-Shu points (Wu Shu Xue 五输穴) to be treated with more care, in standard terms
(Jing-Well, Ying-Spring, Shu-Stream, Jing-River, He-Sea).  Its central principle: a Five-Phase relation becomes a point
only after two decisions in between, identifying the pattern and specifying the selection method.  "Wood excess" alone
does not distinguish Liver Fire, Liver Yang rising, Liver Qi stagnation or Liver stagnation with Spleen deficiency.  The
revision also asked:

* that three attributes stay apart: a channel's phase, a point's phase, the reinforcing or reducing intention (行间 is a
  Fire point reduced under "reduce the child"; 太冲 is an Earth point that stays a Liver point and is the Yuan point, not
  the Liver's same-phase point 大敦);
* that the pathological relations be modelled (mother affecting child, child affecting mother, overacting and
  counteracting, each by excess of one side or by deficiency of the other), along with the five pathogens of *Nanjing* 50,
  which name where a pathogen comes from, not a deficiency or an excess;
* that the mother–child method be read on the affected channel and across channels, with the Saam four-needle templates
  as a Korean school's method and the interior–exterior and same-name extensions as a recent paper's deduction;
* that the named strategies (滋水涵木, 培土生金, 金水相生, 益火补土, 抑木扶土, 培土制水, 佐金平木, 泻南补北) be read through their
  pattern premise and their documented examples;
* that 当先实脾 keep its condition (即勿补之);
* that a stated example (Wood excess, Earth and Metal deficiency) be answered in its several branches;
* that a trigram or a day's stems and branches change nothing in a point's Five-Shu class;
* that theory and clinical evidence stay apart;
* and that each record keep six elements: pattern premise → channels → Five-Phase relation → selection rule → intention →
  source.

## Decision

1. **The reasoning as data** (`acupuncture.yaml` → `five_phases`): terms; the five relations of a point's phase to its
   channel's (same, child, controlled, controller, mother); the six pathological relations with meaning, example and
   implication; the five pathogens; the patterns a phase's state does not tell apart; identified patterns with the states
   they imply (肝郁脾虚: Wood excess, Earth deficiency; 阴虚火旺 is no Fire excess); the strategies with premise, the states
   they fit, the derivation by the Five-Shu and the examples their sources give; the methods with their level; the guards
   (conclusions that do not follow) with when they apply, and the claims (text patterns) that trigger them.  The order of
   the generating and controlling cycles is in code.  Sixteen rules join the rule set (59 in all), with probes for the
   classical ones: Nanjing 50, 69 (不实不虚，以经取之), 75, 77 and 79, the Jin Gui's 当先实脾, Suwen 67's 乘侮, and the
   strategies' terms.  Two levels are new, school (Saam) and deduction (the paired extensions).
2. **One function and one tool** (`study.wuxing`; CLI `study wuxing`).  It takes states read from a text or a list, and
   optionally the methods to keep.  It returns:
   * the patterns still to tell apart;
   * the relations each pair of states allows, both readings listed when the states cannot decide between them, each with
     the *Nanjing* 50 name of what the receiving organ suffers;
   * the classical statements that bear on the states: Nanjing 75 when East is excess and West deficient; 当先实脾 as met,
     not given or not needed; Nanjing 79 for the Heart;
   * the strategies the states fit, or would fit with one more state;
   * every method's points, each with its category, phase, relation and intention: Nanjing 69 on the channel (classical) and
     across channels (teaching), Nanjing 79, Saam, and the interior–exterior and same-name deductions;
   * **the points two methods treat oppositely**, so that a mixed pattern is never merged by formula;
   * the guards, a claim in the text named first.

   `study.point` gains the same attributes for one point (and the methods that take it), `acupoints --framework` gains the
   tables (every channel's points against its phase, the Saam templates, the paired points), and `acupoints` reads states
   organ by organ (肝实脾虚: the Liver's child, the Spleen's mother, not both for both), with a brief Five-Phase reading
   beside the prescription.
3. **Sources as they were checked.**  The Saam trial (Kim et al., *Trials* 2015;16:314) is recorded as its abstract
   reports it.  Only the body-acupuncture arm lowered the primary fatigue score at 5 weeks; the Saam arm did not, though it
   improved stress scores and, at 13 weeks, depression scores.  The record states what the trial shows about one
   intervention in one population, and that it neither validates nor refutes the formulas.  The 2024 paper (张嘉程等, 《天津中医药》
   41(4):436-439) and the strategies' examples (广东省中医院, 北京中医药大学课件, 《重庆医科大学学报》) are cited as given and marked
   unchecked against their full texts.  Each example point is read against the tables, so the reader sees which part of the
   rationale the Five-Shu can give (太白—太渊) and which they cannot (脾俞—肺俞, 三阴交).

## Consequences

* The user's example reads as intended: three relations, Nanjing 75, four strategies with conditional ones, and the
  opposite intentions on 少府 and 鱼际.  The eval `acupuncture` adds the Liver's relations (5/5), the Saam table of the
  twelve channels as the tradition prints it (12/12), the paired examples (2/2) and twelve Five-Phase cases (12/12).
* The reasoning stays a structure, never a prescription.  Weights do not enter; no method is preferred over another; the
  output gives no technique parameters.
* Reading states from text is rule-based: an organ or phase with a word of excess or deficiency, or an identified
  pattern.  Anything else is not read, and the error says what can be.  Time-based and trigram systems are not modelled;
  the tool says they are separate systems when a text invokes them.
* The D1 backup lists `study.wuxing` as unavailable (`data`), like the other acupuncture tools: the server's catalog has
  95 tools.
