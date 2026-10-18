# corpus/aliases: published lists of other names of drugs

The lists of other names (别名) of drugs that the alias layer ([ADR 0023](../../docs/adr/0023-alias-layer.md),
[docs/data.md](../../docs/data.md) "Alias layer") reads and that the repository may carry. Each file is a faithful copy
of a dataset under its own licence, credited in its header. hurbTable and the GitHub copy of the 本草纲目别名录 state
no licence: they are never here, only under `<data>/aliases/local/` (`taochronos aliases import hurb|bielu-gb FILE`).

## ntu40k.tsv

**What it is.** An extract of *Large List of Chinese Drug Names 40K*, published by DR-NTU (Data), Nanyang
Technological University, <https://doi.org/10.21979/N9/V2XBOH>: 50,606 one-to-one records, each pairing a primary
drug name (8,240 distinct names) with one alternate name (32,571 distinct), as given by 《中华本草》 (31,404 rows),
《全国中草药汇编》 (11,063), 《中药大辞典》 (5,073), both 《中华本草》 and 《中药大辞典》 (1,801), 《中国药典》 (1,264)
and 《标准藏药》 (1). Names are in simplified characters.

**Citation.** Chong, William Eng Keat; Stanley-Baker, Michael, 2019, "Large List of Chinese Drug Names 40K",
https://doi.org/10.21979/N9/V2XBOH, DR-NTU (Data), V1. The author order and the version come from search results and
are **unverified**. Confirm them with the Cite button of the dataset's page before quoting them anywhere else. The
workbook's metadata names Gail Chen as its creator.

**Licence.** [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/): non-commercial use only, with credit.
This extract is shared under the same licence. It was added to the repository at the maintainer's request on
2026-10-18, credited to NTU, with the site staying non-commercial. Anything built on this file inherits the
non-commercial condition. The licensor offers the dataset as-is, without warranties (section 5 of the licence).

**What was changed.** The file was converted from the dataset's workbook (`ChineseDrugEthnonymsSynonymyTable.xlsx`,
sha256 `3a4cf287234f69dea286b136a293baea85d2ad8ad9cd187b83b17b9ab981342c`) to UTF-8 TSV with LF line ends. The columns
are kept and nothing else was changed: every cell is written as the workbook holds it, including the leading or
trailing space of 54 alternate names, the bracketed or pinyin spellings of characters the GB2312 set lacked
(鸡（土从）, 水麻tiao), and unclosed titles in Remarks. Only the sheet "1-to-1 records" is extracted. The workbook's
summary sheet, "SimpleStats", is not, and cell formatting is not kept. The file's own `#` lines record all of this.

**Format.** The file opens with `#` lines: the title, source, citation, licence, the original file (name, sheet,
sha256, rows), the modifications, the disclaimer and how to regenerate the file. Then comes the header row and one row
per record, in the workbook's order:

| column | holds |
|---|---|
| `PrimaryDrugNameNo.` | the number of the primary name's entry, one per dictionary: 11,768 numbers for 8,240 names |
| `PrimaryDrugName` | the primary name |
| `DictionarySource` | the dictionary or dictionaries the pair is from, in 《》 |
| `AlternateName` | the other name |
| `Remarks` | what the dictionary adds (3,990 rows): the book a name is cited from (《纲目》, 《本经》: about 620 titles), a place ([云南], （江苏）), an ethnic-language label (（藏名）, [傣语], [蒙名]), a person (（陶弘景）), a part (根名) |

Cells are separated by tabs, and nothing is quoted. A backslash, tab, newline or carriage return inside a cell would be
written `\\ \t \n \r`, but none occurs in this file. An empty cell has no value.

**How it is read.** `read_ntu("corpus/aliases/ntu40k.tsv")` (`src/taochronos/plugins/classics/ingest/aliases.py`)
reads it like the workbook and gives one entry per row:

- **Names.** Each name goes through the pack's normaliser. A character written by its parts or in pinyin becomes a lost
  character (〓, flag `lost_char`), so it never turns into another drug's name (鸡, 水麻). The 40 primary names
  holding one give no pair.
- **Remarks.** These are parsed into `books`, `regions`, `language`, `persons` and `other`. A language label makes the
  row's name a folk name in that language.

The alias build then takes the pairs through its usual gates: stop names, the cue and candidate statuses, and blockers.

**Regenerating.** Run this from the repository, with the dataset's workbook or its Dataverse `.tab` or `.zip`:

```sh
taochronos aliases import ntu ChineseDrugEthnonymsSynonymyTable.xlsx --publish   # -o PATH writes elsewhere
```

The same workbook gives the same bytes. The command reports the rows read and written, the extract's size and
sha256, how the Remarks parse and the names the rows give. It refuses the extract itself as input. Without
`--publish`, `aliases import ntu` writes only the local layer (`<data>/aliases/local/ntu.jsonl` and its manifest).

**Where it goes.** The file is part of the repository. It is not part of what the browser downloads: `chat/build.py`
packs only `corpus/demo`, `corpus/catalog` and `corpus/modern` of `corpus/` into `home.zip`. It is not part of the
corpus server's image either, because `.dockerignore` admits the same three folders. The site serves only what the
alias build writes into `domains/classics/aliases/`, where `sources.yaml` decides whether the `ntu40k` pairs ship
(credited as "NTU 40K").
