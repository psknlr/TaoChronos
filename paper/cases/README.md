# Case figures · 三个对话案例的示意图

Three display items, one for each of three questions put to the conversation agent 道乃久 (Tao-R1) on the full corpus
on 23 November 2026: a herbal formula for a case, a drug through the materia medica, and acupuncture points for a case.
Each figure draws the answer the agent actually gave — its tables, its statistics, its quotations and what it declined
to say — in the display-item style of the paper (`paper/figures/nature_style.py`).

三张图各对应一次真实问答（方剂 · 本草 · 针灸），所画的数值、引文与段落号全部取自智能体当次的回答，并在出图时逐项核对；
英文图注见 [`legends.md`](legends.md)。

| Figure | Question | File |
|---|---|---|
| Case Fig. 1 | Bilateral knee pain for three years in a 58-year-old woman: pattern and formula | [`out/Case1_herbal_formula_knee_pain.pdf`](out/Case1_herbal_formula_knee_pain.pdf) |
| Case Fig. 2 | Huangqi 黄芪 in the materia medica of different periods | [`out/Case2_materia_medica_huangqi.pdf`](out/Case2_materia_medica_huangqi.pdf) |
| Case Fig. 3 | Recurrent low back pain in a 45-year-old desk worker: acupuncture points | [`out/Case3_acupuncture_low_back_pain.pdf`](out/Case3_acupuncture_low_back_pain.pdf) |

Each is 183 × 170 mm (double column), a vector PDF with live text and embedded TrueType fonts, with an SVG and a
600 dpi RGB PNG beside it; text is 5–7 pt, panel labels 8 pt bold, strokes 0.25–1 pt, colours from the Okabe–Ito
palette (blue for what the answer selects, vermillion only for cautions and for what it withholds).

## What is drawn, and how it is checked

- `make_case_data.py` copies from the three result archives (the answer as Markdown, its tables as CSV, its charts
  as SVG) into `source_data/`: every table verbatim, every cited passage with the title, author and composition range
  of its witness from `corpus/catalog`, the answer itself, and the few values only a chart carries (for Case 2, the
  991 decoctions of the dose chart, read back from the vector chart and checked against the n, median and quartiles of
  the agent's own table). Nothing is recomputed and nothing is added.
- The figure scripts assert what they draw while they run: each quotation is a substring of the answer, each passage
  identifier is one the answer cites, each count, ratio and statistic equals the table it comes from (the trend
  statistic of Case 2 is recomputed from the counts). A sentence that does not fit its box stops the build.
- `verify_cases.py` reads the saved PDFs back: page size, fonts, Chinese text drawn by both MuPDF and Poppler, and
  every printed passage identifier and 「quotation」 against the answer.
- `out/qc/*.json` is the per-figure check of the paper's style module (sizes, strokes, collisions, page bounds).

The English renderings and the romanised names are the figures' own, as is the placing of the acupuncture points on
the schematic body (`body_map.py`: by the vertebral level the cited text gives, the popliteal crease, the lateral
malleolus and the hand), which is for orientation and is not an atlas.

## Rebuild

```bash
pip install matplotlib numpy scipy pandas pymupdf pyyaml pillow fonttools
python paper/cases/make_case_data.py --knee K.zip --huangqi H.zip --lbp L.zip   # only to refresh source_data/
cd paper/cases
python case1_formula_knee_pain.py && python case2_huangqi_materia_medica.py && python case3_acupuncture_low_back_pain.py
python verify_cases.py
```

Arial and Noto Sans CJK SC should be installed. The files in `out/` were built where Arial was not available, so
they embed Liberation Sans, which has Arial's metrics: rebuilding with Arial installed changes the typeface and nothing
else (`out/qc/*.json` records the fonts, and lists this as its only warning).

## For the authors

Found while checking the answers against their own tables. The figures draw the tool's values and say so in the
legends; none of these is corrected silently.

1. **Case 3, mother point of the kidney channel.** The answer's text names 大钟 as the kidney channel's metal
   (jing-river) point to supplement. The tool's tables give 复溜 KI7 (表2, 表8); 大钟 KI4 is the luo point (表3).
   Panel g uses the tables.
2. **Case 1, similarity of 独活寄生汤 and 三痹汤.** The Jaccard index of 0.94 is of the compositions the tool read,
   which count 续断 in 独活寄生汤 (16 drugs, from 「桑寄生（無真者續斷代）」 and the 妇人大全良方 variant) and leave
   黄芪 out of 三痹汤. The answer's sentence "differs by adding 续断 + 黄芪 and dropping 桑寄生" describes the
   15-drug formula, for which the index would be lower. Panel c draws the tool's compositions and marks both drugs.
3. **Case 2, the name of the trend test.** The answer calls it "Mann–Whitney/trend"; the statistic is the
   Cochran–Armitage z of the study layer (4.163 from the counts of 表6, recomputed in the script).
4. **Case 2, a blank for 耆.** In about 100 witnesses of the open corpus, all from 笈成 (千金翼方 `jc_d002` among
   them), the second character of 黃耆 is a blank: 「人參、黃　、防風」, 「竹葉黃　湯」 — more than 700 blanks, against
   some 1,600 places where the name is written. The answer quotes three such passages itself (`jc_f009.00036`,
   `jc_f022.01352`, `jc_d075.00096`). The tool does not count them: the compositions it reads for 补中益气汤 and 玉屏风散 hold no
   Huangqi (表10, 表13), and the counts, shares and partners of panels c–e are lower bounds. The low share under
   Song–Jin–Yuan should be re-read once the character is restored.
5. **Case 2, not drawn.** One row of the answer's table of formulas (白术黄耆汤) sets a label on stroke and headache
   beside a passage on 破伤风; and the sentence that honey-frying "dominates from the Ming/Qing onward" holds for the
   Qing only in the chart it rests on (炙 and 蜜炙 together: 14% of notes in the Ming, 56% in the Qing).
6. **Chinese characters in the paper's other PDFs.** matplotlib embeds the CFF outlines of Noto Sans CJK under a
   TrueType descriptor. Poppler and Acrobat tolerate this; MuPDF draws nothing, so `paper/figures/out/*.pdf` show no
   Chinese character in viewers built on it (`verify_cases.cjk_ink` returns 0 for `fig3_end_to_end.pdf`). The case
   figures avoid it with `cjk_truetype.py`; calling `use_truetype_cjk()` from `nature_style.py` would repair the rest.

## Files

```
paper/cases/
  README.md · legends.md
  make_case_data.py        source data from the three result archives
  case_style.py            shared drawing helpers and the strip that opens each figure
  cjk_truetype.py          TrueType-outline copies of Noto Sans CJK SC, so every viewer draws the Chinese text
  body_map.py              the schematic figure seen from behind
  case1_formula_knee_pain.py · case2_huangqi_materia_medica.py · case3_acupuncture_low_back_pain.py
  verify_cases.py          the saved PDFs read back against the answers
  source_data/             caseN_*.json (tables, chart values), caseN_citations.csv, caseN_answer.md,
                           case2_decoction_doses.csv
  out/                     PDF · SVG · PNG; qc/ per-figure checks
```
