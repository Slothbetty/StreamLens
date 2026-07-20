#!/bin/sh
set -e

echo "=========================================="
echo "  StreamLens — running synthetic workflow"
echo "=========================================="

python run_comparison.py \
  -n synthetic/network.json \
  -m synthetic/movie.json \
  -sc synthetic/seeks.json,synthetic/seeks_prefetch_hit.json,synthetic/seeks_mixed.json,synthetic/seeks_linear_hit_nonlinear_miss.json,synthetic/seeks_linear_miss_nonlinear_hit.json \
  -pc synthetic/test_prefetch_config.json \
  -a all \
  -o synthetic/results

echo ""
echo "=========================================="
echo "  Results ready. Starting viewer..."
echo "  Open http://localhost:8000/viewer/view_comparison.html"
echo "  Load: synthetic/results/comparison_summary.json"
echo "=========================================="

python serve_viewer.py
