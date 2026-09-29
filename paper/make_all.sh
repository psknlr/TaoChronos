#!/usr/bin/env bash
# Rebuild every figure, table, check and the Supplementary Information of the TaoChronos (道乃久) paper from the
# repository alone (about 12 minutes).
#   pip install -e . matplotlib numpy scipy pandas pymupdf python-docx
# Arial and Noto Sans CJK should be installed; without Arial the figures fall back to Liberation Sans.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 paper/figures/make_data.py --research-value   # source data: catalogues, web corpus store, eval, study layer,
                                                      # the harness's configuration and the end-to-end case (Fig. 3)
python3 paper/figures/mutation_matrix.py        # invariants with each boundary removed (Fig. 4b)
cd paper/figures
for f in fig1_architecture fig2_corpus fig3_end_to_end fig4_verification fig5_research_value fig6_case_studies \
         extfig1_generalization extfig2_canon_replication extfig3_resources suppfig1_failures; do
  python3 "$f.py"
done
python3 check_legends.py
python3 qc_report.py > /dev/null && echo "QC: every figure passes (paper/figures/out/qc/QC_REPORT.md)"
cd ../..
python3 paper/tables/make_tables.py
python3 paper/supplementary/make_supplementary.py
