#!/usr/bin/env python3
"""
Run all 5 Session-replay prefetch scenarios then merge into a single comparison_summary.json.

When a non-default movie is supplied (via -m), prefetch configs for all 5 scenarios
are regenerated automatically from the real seek events and the movie's actual
segment structure, so results are always meaningful regardless of movie length.

Usage:
    # Default: synthetic movie + pre-built prefetch configs
    python run_session_replay_comparison.py

    # Explicit movie.json (configs regenerated automatically)
    python run_session_replay_comparison.py -m session_replay/my_movie.json
"""

import json
import subprocess
import sys
import argparse
from pathlib import Path

from setup_session_replay import build_prefetch_configs

SCRIPT_DIR = Path(__file__).parent
TRACE_UUID = "56329467-babb-4d75-bb58-70f3906369fe"

SCENARIOS = [
    "seeks_miss",
    "prefetch_hit",
    "mixed",
    "linear_hit_nonlinear_miss",
    "linear_miss_nonlinear_hit",
]

NETWORK = f"session_replay/network_{TRACE_UUID}.json"
SEEKS   = f"session_replay/seeks_{TRACE_UUID}.json"


# ── helpers ────────────────────────────────────────────────────────────────────

def run(cmd):
    print(f"\n>>> {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, cwd=SCRIPT_DIR)
    if result.returncode != 0:
        print(f"ERROR: command failed (exit {result.returncode})", file=sys.stderr)
        sys.exit(result.returncode)


def load_json(path, encoding="utf-8"):
    with open(path, encoding=encoding) as f:
        return json.load(f)


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Run 5 Session-replay ABR comparison scenarios"
    )
    parser.add_argument(
        "-m", "--movie", metavar="PATH",
        help="Path to a movie.json (configs regenerated automatically for this movie)",
    )
    args = parser.parse_args()

    # ── resolve movie data and path ────────────────────────────────────────────
    if args.movie:
        movie_data  = load_json(args.movie)
        movie_path  = args.movie
        regenerate_configs = True

    else:
        movie_data  = None
        movie_path  = "synthetic/movie.json"
        regenerate_configs = False

    # ── build prefetch configs ─────────────────────────────────────────────────
    if regenerate_configs:
        print("\nRegenerating prefetch configs for this movie ...")
        seeks = load_json(SCRIPT_DIR / SEEKS).get("seeks", [])
        scenario_configs = build_prefetch_configs(movie_data, seeks)

        cfg_dir = SCRIPT_DIR / "session_replay"
        prefetch_paths = {}
        for scenario, cfg in scenario_configs.items():
            out_path = cfg_dir / f"prefetch_config_real_{scenario}.json"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            print(f"  wrote {out_path.relative_to(SCRIPT_DIR)}")
            prefetch_paths[scenario] = out_path.relative_to(SCRIPT_DIR)
    else:
        prefetch_paths = {
            sc: f"session_replay/prefetch_config_real_{sc}.json"
            for sc in SCENARIOS
        }

    # ── run all scenarios ──────────────────────────────────────────────────────
    for scenario in SCENARIOS:
        run([
            sys.executable, "run_comparison.py",
            "-n", NETWORK,
            "-m", str(movie_path),
            "-sc", SEEKS,
            "-pc", str(prefetch_paths[scenario]),
            "-a", "all",
            "-o", f"session_replay/results/{scenario}",
        ])

    print("\n>>> Merging scenario summaries ...")
    run([sys.executable, "merge_session_replay_summaries.py"])
    print("\nDone. Load session_replay/results/comparison_summary.json in the viewer.")


if __name__ == "__main__":
    main()
