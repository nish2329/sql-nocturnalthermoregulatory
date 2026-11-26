#!/usr/bin/env bash
# Run the whole pipeline end to end.
#   ./run_all.sh          full synthetic dataset (~600 participants, ~10 min)
#   ./run_all.sh --demo   small dataset (~40 participants, < 1 min)
set -euo pipefail
cd "$(dirname "$0")/python"

export DATABASE_URL="${DATABASE_URL:-postgresql://postgres@localhost:5432/thermo}"

DEMO=""
LOO=""
if [[ "${1:-}" == "--demo" ]]; then
  DEMO="--demo"
  LOO="--skip-loo"
fi

echo "== generate synthetic data";  python 00_generate_synthetic.py $DEMO
echo "== SQL: clean, baseline, score, detect, person-nights"; python 01_run_sql.py
echo "== compare groups";          python 02_compare_groups.py > /dev/null
echo "== robustness";              python 03_robustness.py $LOO
echo "== check against truth";     python 04_check_against_truth.py > /dev/null
echo "== figures";                 python 05_figures.py
echo "done: see results/ and figures/"
