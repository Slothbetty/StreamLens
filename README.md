# StreamLens

StreamLens is an open-source ABR simulation environment for multi-region buffering, seeking, and prefetching. It extends [SABRE](https://github.com/UMass-LIDS/sabre) with nonlinear buffering, configurable seek and prefetch scenarios, synthetic and session-replay workflows, and a browser-based viewer for comparing ABR algorithms.

## Demo Video

[Watch the StreamLens software demo](https://youtu.be/Iin3fGVeDJQ)

The demo shows the StreamLens workflow for running ABR simulations with multi-region buffering, seeking, prefetching, cross-ABR comparison, and browser-based QoE visualization.

## Requirements

- Python >= 3.10
- `numpy` (see `requirements.txt`)

## Quick Start

```bash
git clone https://github.com/Slothbetty/sabre.git
cd sabre
pip install -r requirements.txt
cd src
```

**Single ABR run:**
```bash
python run_comparison.py -n synthetic/network.json -m synthetic/movie.json -a bola -o results.json
python serve_viewer.py
# Open http://localhost:8000/viewer/view_comparison.html and load results.json
```

**Cross-ABR comparison across seek scenarios (main workflow from the paper):**

macOS / Linux / Git Bash:
```bash
python run_comparison.py \
  -n synthetic/network.json -m synthetic/movie.json \
  -sc synthetic/seeks.json,synthetic/seeks_prefetch_hit.json,synthetic/seeks_mixed.json,synthetic/seeks_linear_hit_nonlinear_miss.json,synthetic/seeks_linear_miss_nonlinear_hit.json \
  -pc synthetic/test_prefetch_config.json \
  -a all -o synthetic/results
python serve_viewer.py
# Open http://localhost:8000/viewer/view_comparison.html and load synthetic/results/comparison_summary.json
```

Windows PowerShell (use backtick `` ` `` for line continuation, not `\`):
```powershell
python run_comparison.py `
  -n synthetic/network.json -m synthetic/movie.json `
  -sc synthetic/seeks.json,synthetic/seeks_prefetch_hit.json,synthetic/seeks_mixed.json,synthetic/seeks_linear_hit_nonlinear_miss.json,synthetic/seeks_linear_miss_nonlinear_hit.json `
  -pc synthetic/test_prefetch_config.json `
  -a all -o synthetic/results
python serve_viewer.py
# Open http://localhost:8000/viewer/view_comparison.html and load synthetic/results/comparison_summary.json
```

## Docker

```bash
docker build -t streamlens .
docker run --rm -p 8000:8000 streamlens
# Open http://localhost:8000/viewer/view_comparison.html
# Load: synthetic/results/comparison_summary.json
```

## Documentation

Full documentation and workflow guides are in [src/README.md](src/README.md).

## License

BSD 2-Clause — see [LICENSE](LICENSE).

## Based On

StreamLens builds on [SABRE](https://github.com/UMass-LIDS/sabre) by Kevin Spiteri, Ramesh Sitaraman, and Daniel Sparacio (MMSys '18).
