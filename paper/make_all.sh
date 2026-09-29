#!/usr/bin/env bash
# Rebuild every figure, table and check of the TaoChronos (道乃久) paper from the repository alone (about 7 minutes).
#   pip install -e . matplotlib numpy scipy pandas pymupdf python-docx
# Arial and Noto Sans CJK should be installed; without Arial the figures fall back to Liberation Sans.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 paper/figures/make_data.py --research-value   # source data: catalogues, web corpus store, eval, study layer
python3 paper/figures/mutation_matrix.py        # invariants with each boundary removed (Fig. 3b)
cd paper/figures
for f in fig1_overview fig2_corpus fig3_verification fig4_research_value fig5_case_studies \
         extfig1_generalization extfig2_canon_replication extfig3_resources; do
  python3 "$f.py"
done
python3 check_legends.py
python3 qc_report.py > /dev/null && echo "QC: every figure passes (paper/figures/out/qc/QC_REPORT.md)"
cd ../..
python3 paper/tables/make_tables.py
