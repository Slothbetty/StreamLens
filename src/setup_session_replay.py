#!/usr/bin/env python3
"""
Given a parsed trace UUID, auto-generate the 5 prefetch scenario configs
and update TRACE_UUID in run_session_replay_comparison.py.

Usage:
    python setup_session_replay.py <uuid>
    python setup_session_replay.py <uuid> --movie path/to/movie.json

Run parse_session_replays.py first to produce seeks_<uuid>.json and
network_<uuid>.json, then run this script before run_session_replay_comparison.py.
"""

import json
import math
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
BUFFER_THRESHOLD = 3500       # ms — must be reachable on throttled network
MIN_SIGNIFICANT_SEEK_S = 5.0  # seconds gap to count as a meaningful forward seek
FAR_MISS_OFFSET = 13          # segments past destination for "wrong target" scenarios


def load_json(path):
    with open(path) as f:
        return json.load(f)


def write_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  wrote {path.relative_to(SCRIPT_DIR)}")


def make_config(threshold, segments):
    return {
        "buffer_level_threshold": threshold,
        "prefetch": [{"segment": s} for s in segments],
    }


def find_miss_segs(all_dest_segs, num_segments):
    """Return [s, s+1] from the longest run of non-destination segments."""
    dest_set = set(all_dest_segs)
    best_start, best_len = None, 0
    run_start, run_len = None, 0
    for seg in range(num_segments):
        if seg not in dest_set:
            if run_start is None:
                run_start = seg
            run_len += 1
        else:
            if run_len > best_len:
                best_len, best_start = run_len, run_start
            run_start, run_len = None, 0
    if run_len > best_len:
        best_len, best_start = run_len, run_start

    if best_start is None or best_len < 2:
        raise ValueError("Cannot find 2 consecutive non-destination segments")

    mid = best_start + (best_len - 2) // 2
    return [mid, mid + 1]


def build_prefetch_configs(movie_data, seeks, buffer_threshold=BUFFER_THRESHOLD):
    """
    Generate all 5 prefetch scenario configs for the given movie and seek events.

    Works correctly for any movie length — seek destinations and prefetch indices
    are clamped to the valid segment range, and seeks that fire after the movie
    ends are ignored.

    Returns a dict keyed by scenario name:
        "seeks_miss", "prefetch_hit", "mixed",
        "linear_hit_nonlinear_miss", "linear_miss_nonlinear_hit"
    """
    seg_s = movie_data["segment_duration_ms"] / 1000.0
    num_segments = len(movie_data["segment_sizes_bits"])
    movie_duration_s = num_segments * seg_s

    # Ignore seeks that would fire after the movie ends
    valid_seeks = [s for s in seeks if s.get("seek_when", 0) < movie_duration_s]

    def clamp(seg):
        return max(0, min(num_segments - 1, int(seg)))

    def clamp_unique(segs):
        seen, out = set(), []
        for s in segs:
            s = clamp(s)
            if s not in seen:
                seen.add(s)
                out.append(s)
        return out

    all_dest_segs = [clamp(math.floor(s["seek_to"] / seg_s)) for s in valid_seeks]

    main_seek = max(
        valid_seeks,
        key=lambda s: s["seek_to"] - s["seek_when"],
        default=None,
    )
    if main_seek is None or (main_seek["seek_to"] - main_seek["seek_when"]) < MIN_SIGNIFICANT_SEEK_S:
        print("WARNING: No forward seek > 5 s found within movie duration. "
              "Prefetch configs may not be meaningful.")

    main_dest = (
        clamp(math.floor(main_seek["seek_to"] / seg_s))
        if main_seek else num_segments // 2
    )
    far_miss = clamp(min(main_dest + FAR_MISS_OFFSET, num_segments - 5))

    try:
        miss_segs = find_miss_segs(all_dest_segs, num_segments)
    except ValueError:
        # Fallback: quarter- and three-quarter points of the movie
        miss_segs = [num_segments // 4, num_segments * 3 // 4]

    configs = {
        "seeks_miss": make_config(
            buffer_threshold,
            clamp_unique(miss_segs),
        ),
        "prefetch_hit": make_config(
            buffer_threshold,
            clamp_unique([main_dest, main_dest + 1]),
        ),
        "mixed": make_config(
            buffer_threshold,
            clamp_unique([main_dest, main_dest + 1, far_miss, far_miss + 1]),
        ),
        "linear_hit_nonlinear_miss": make_config(
            buffer_threshold,
            clamp_unique(range(far_miss, far_miss + 5)),
        ),
        "linear_miss_nonlinear_hit": make_config(
            buffer_threshold,
            clamp_unique(range(main_dest, main_dest + 4)),
        ),
    }

    print(f"  Movie: {num_segments} segs x {movie_data['segment_duration_ms']} ms "
          f"= {movie_duration_s:.1f} s")
    print(f"  Valid seeks: {len(valid_seeks)}/{len(seeks)}, "
          f"destinations: {sorted(set(all_dest_segs))}")
    print(f"  Main dest seg: {main_dest},  far-miss seg: {far_miss}")
    for name, cfg in configs.items():
        segs = [p["segment"] for p in cfg["prefetch"]]
        print(f"    {name}: prefetch {segs}")

    return configs


def main():
    if len(sys.argv) < 2:
        print("Usage: python setup_session_replay.py <uuid> [--movie path/to/movie.json]")
        sys.exit(1)

    uuid = sys.argv[1]
    seeks_path = SCRIPT_DIR / "session_replay" / f"seeks_{uuid}.json"

    if not seeks_path.exists():
        print(f"ERROR: {seeks_path} not found. Run parse_session_replays.py first.")
        sys.exit(1)

    # Allow overriding the movie via --movie
    movie_path = SCRIPT_DIR / "synthetic" / "movie.json"
    if "--movie" in sys.argv:
        idx = sys.argv.index("--movie")
        if idx + 1 < len(sys.argv):
            movie_path = Path(sys.argv[idx + 1])

    seeks = load_json(seeks_path).get("seeks", [])
    movie_data = load_json(movie_path)

    print(f"UUID:      {uuid}")
    print(f"Movie:     {movie_path}")

    configs = build_prefetch_configs(movie_data, seeks)

    cfg_dir = SCRIPT_DIR / "session_replay"
    write_json(cfg_dir / "prefetch_config_real_seeks_miss.json",           configs["seeks_miss"])
    write_json(cfg_dir / "prefetch_config_real_prefetch_hit.json",         configs["prefetch_hit"])
    write_json(cfg_dir / "prefetch_config_real_mixed.json",                configs["mixed"])
    write_json(cfg_dir / "prefetch_config_real_linear_hit_nonlinear_miss.json", configs["linear_hit_nonlinear_miss"])
    write_json(cfg_dir / "prefetch_config_real_linear_miss_nonlinear_hit.json", configs["linear_miss_nonlinear_hit"])

    # Update TRACE_UUID in run_session_replay_comparison.py
    runner = SCRIPT_DIR / "run_session_replay_comparison.py"
    text = runner.read_text()
    updated = re.sub(r'TRACE_UUID\s*=\s*"[^"]*"', f'TRACE_UUID = "{uuid}"', text)
    runner.write_text(updated)
    print(f"\n  updated TRACE_UUID in run_session_replay_comparison.py -> {uuid}")
    print("\nDone. Run: python run_session_replay_comparison.py")


if __name__ == "__main__":
    main()
