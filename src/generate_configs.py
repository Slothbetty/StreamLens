#!/usr/bin/env python3
"""
Generate prefetch + seek configs for SABRE comparison demos.

Writes four files in one run:
  - test_prefetch_config.json  — spaced prefetch segment list + buffer threshold
  - seeks_prefetch_hit.json    — seeks that land on prefetched segments
  - seeks.json                 — same seek_when schedule; seek_to miss prefetch
  - seeks_mixed.json           — random mix of hit and miss seeks

Usage
-----
    python generate_configs.py

    python generate_configs.py --num-seeks 6 --prefetch-count 8 --buffer-threshold 15000

    # Control the hit ratio and fix the random seed for reproducibility
    python generate_configs.py --mixed-hit-ratio 0.4 --seed 42
"""

import argparse
import json
import math
import random
import sys
from pathlib import Path


def load_movie(movie_path: str) -> dict:
    with open(movie_path) as f:
        return json.load(f)


def movie_info(movie_data: dict) -> tuple[int, int, float]:
    """Return (num_segments, segment_duration_ms, total_duration_s)."""
    seg_dur_ms = movie_data["segment_duration_ms"]
    num_seg = len(movie_data["segment_sizes_bits"])
    total_s = num_seg * seg_dur_ms / 1000.0
    return num_seg, seg_dur_ms, total_s


def segment_index_for_time(time_s: float, seg_dur_ms: int) -> int:
    """Map a seek-to time (seconds) to the segment index the simulator will use."""
    pos_ms = time_s * 1000
    floor_idx = math.floor(pos_ms / seg_dur_ms)
    prev_boundary = floor_idx * seg_dur_ms
    delta = pos_ms - prev_boundary
    if delta < seg_dur_ms / 2:
        return floor_idx
    else:
        return floor_idx + 1


def build_spaced_prefetch_indices(num_segments: int, count: int) -> list[int]:
    """Pick `count` segment indices spread across the movie."""
    if count <= 0:
        return []
    margin = max(3, num_segments // 25)
    lo, hi = margin, num_segments - 1 - margin
    if hi <= lo:
        return [max(0, min(num_segments - 1, num_segments // 2))]

    if count == 1:
        return [(lo + hi) // 2]

    out: list[int] = []
    for i in range(count):
        t = i / (count - 1)
        idx = int(round(lo + t * (hi - lo)))
        idx = max(0, min(num_segments - 1, idx))
        out.append(idx)
    seen: set[int] = set()
    unique: list[int] = []
    for idx in sorted(out):
        if idx not in seen:
            seen.add(idx)
            unique.append(idx)
    while len(unique) < count and len(unique) < num_segments:
        for j in range(num_segments):
            if j not in seen:
                seen.add(j)
                unique.append(j)
                break
        else:
            break
    return sorted(unique[:count])


def seek_to_seconds_for_segment(seg_idx: int, seg_dur_ms: int) -> float:
    """
    Seek target time (seconds) in the first quarter of the segment so
    segment_index_for_time() in sabre matches seg_idx (midpoint can round up).
    """
    pos_ms = seg_idx * seg_dur_ms + seg_dur_ms * 0.25
    return round(pos_ms / 1000.0, 1)


def pick_spaced_subset(indices: list[int], count: int) -> list[int]:
    """Pick `count` values spread across sorted `indices` (may repeat if count > len)."""
    if not indices or count <= 0:
        return []
    idx_sorted = sorted(set(indices))
    if len(idx_sorted) <= count:
        out = []
        for i in range(count):
            out.append(idx_sorted[i % len(idx_sorted)])
        return out
    out = []
    for i in range(count):
        pos = int(round(i * (len(idx_sorted) - 1) / max(count - 1, 1)))
        out.append(idx_sorted[pos])
    return out


def build_seek_when_schedule(
    num_seeks: int, total_s: float, seg_dur_ms: int
) -> list[float]:
    """Spread seek_when times evenly across available playback time."""
    margin = seg_dur_ms / 1000.0 * 3
    if num_seeks < 1:
        return []
    hi = total_s - margin
    available = max(hi - margin, 0.0)
    step = available / max(num_seeks + 1, 1)
    times = []
    t = margin + step
    for _ in range(num_seeks):
        times.append(round(min(t, hi - 5.0), 1))
        t += step
    return times


def generate_seeks_for_segment_targets(
    segment_targets: list[int | None],
    seek_when_times: list[float],
    seg_dur_ms: int,
    num_segments: int,
) -> list[dict]:
    seeks = []
    for i, seg_idx in enumerate(segment_targets):
        if seg_idx is None:
            continue
        seg_idx = max(0, min(num_segments - 1, seg_idx))
        st = seek_to_seconds_for_segment(seg_idx, seg_dur_ms)
        when = seek_when_times[i] if i < len(seek_when_times) else seek_when_times[-1]
        seeks.append({"seek_when": when, "seek_to": st})
    return seeks


def build_forward_seek_targets(
    candidates: list[int],
    seek_when_times: list[float],
    seg_dur_ms: int,
    min_forward_ms: int = 0,
) -> list[int | None]:
    """
    For each seek_when time W, pick one candidate segment whose seek_to time is
    strictly greater than W (forward-only).  Candidates are spread evenly across
    the valid forward pool at each seek position so the chosen seek_to values
    grow roughly in step with the seek_when schedule.

    min_forward_ms: if > 0, every chosen seek_to must be at least this many ms
    ahead of seek_when.  Use the player's max buffer size to guarantee the target
    lies outside the linear buffer window (so linear buffering always misses).

    Returns None for positions where no valid forward candidate exists (e.g. when
    a prior seek already jumped the player near the end of the movie).  Callers
    must handle None entries.
    """
    pool = sorted(set(candidates))
    n = len(seek_when_times)
    targets: list[int | None] = []
    last_target = -1  # track last chosen target so each seek lands strictly ahead
    for i, when in enumerate(seek_when_times):
        # Current segment the player is on at seek_when time.
        current_seg = math.floor(when * 1000 / seg_dur_ms)
        # After a prior seek the player's video position is the previous target,
        # so require the new target to be strictly ahead of both.
        effective_min = max(current_seg, last_target)
        # Enforce minimum forward distance so the seek lands beyond the linear
        # buffer window (linear miss → dynamic prefetch hit is the desired test).
        if min_forward_ms > 0:
            min_seg = math.floor((when * 1000 + min_forward_ms) / seg_dur_ms)
            effective_min = max(effective_min, min_seg)
        valid = [s for s in pool if s > effective_min]
        if not valid:
            targets.append(None)
            continue
        frac = i / max(n - 1, 1)
        idx = int(round(frac * (len(valid) - 1)))
        targets.append(valid[idx])
        last_target = valid[idx]
    return targets


def build_mixed_seek_targets(
    hit_targets: list[int],
    miss_targets: list[int],
    num_seeks: int,
    hit_ratio: float,
    rng: random.Random,
    seg_dur_ms: int,
) -> list[int]:
    """
    Build a list of `num_seeks` segment targets where approximately
    `hit_ratio` fraction land on prefetched segments and the rest miss.

    Targets are sorted by seek-to time so every seek moves playback forward
    in roughly the same direction as the seek_when schedule — preventing an
    early seek from jumping to the end of the movie and making all later
    seek_when times already-past.

    Within each pool (hits / misses) pick_spaced_subset already draws evenly
    across the available segments.  The rng is used to randomly interleave
    the two sorted pools rather than concatenating them, so the hit/miss
    pattern is still varied.
    """
    num_hits = max(0, min(num_seeks, round(num_seeks * hit_ratio)))
    num_misses = num_seeks - num_hits

    hit_pool = sorted(
        pick_spaced_subset(hit_targets, num_hits) if num_hits > 0 else [],
        key=lambda s: seek_to_seconds_for_segment(s, seg_dur_ms),
    )
    miss_pool = sorted(
        pick_spaced_subset(miss_targets, num_misses) if num_misses > 0 else [],
        key=lambda s: seek_to_seconds_for_segment(s, seg_dur_ms),
    )

    # Randomly decide which schedule positions are hits vs misses, then
    # consume each sorted pool in order so seek-to times increase monotonically.
    assignment = [True] * num_hits + [False] * num_misses
    rng.shuffle(assignment)

    hi = mi = 0
    combined: list[int] = []
    for is_hit in assignment:
        if is_hit and hi < len(hit_pool):
            combined.append(hit_pool[hi]); hi += 1
        elif not is_hit and mi < len(miss_pool):
            combined.append(miss_pool[mi]); mi += 1

    return combined


def generate_linear_hit_nonlinear_miss_seeks(
    seek_when_times: list[float],
    prefetch_set: set[int],
    seg_dur_ms: int,
    num_segments: int,
    forward_window_ms: int = 12000,
) -> list[dict]:
    """
    Generate short forward seeks that fall within the linear buffer window but
    target non-prefetched segments (linear buffering hit, Nonlinear Buffering miss).

    For each seek_when time W, picks the non-prefetch segment whose seek_to time
    is closest to W + forward_window_ms / 2, constrained to (W, W + forward_window_ms].
    """
    seeks = []
    for when in seek_when_times:
        when_ms = when * 1000
        # First segment strictly after the one currently playing.
        seg_lo = math.floor(when_ms / seg_dur_ms) + 1
        seg_hi = min(math.floor((when_ms + forward_window_ms) / seg_dur_ms), num_segments - 1)
        mid = (seg_lo + seg_hi) // 2

        target_seg = None
        for offset in range(max(seg_hi - seg_lo + 1, 1)):
            for candidate in [mid + offset, mid - offset]:
                if seg_lo <= candidate <= seg_hi and candidate not in prefetch_set:
                    target_seg = candidate
                    break
            if target_seg is not None:
                break

        if target_seg is None:
            # Fallback: first non-prefetch segment in range
            for s in range(seg_lo, seg_hi + 1):
                if s not in prefetch_set:
                    target_seg = s
                    break

        if target_seg is None:
            target_seg = max(0, min(num_segments - 1, seg_lo))

        seeks.append({"seek_when": when, "seek_to": seek_to_seconds_for_segment(target_seg, seg_dur_ms)})
    return seeks


def generate_linear_miss_nonlinear_hit_seeks(
    seek_when_times: list[float],
    prefetch_indices: list[int],
    seg_dur_ms: int,
    min_forward_ms: int = 20000,
) -> list[dict]:
    """
    Generate far forward seeks that jump beyond the linear buffer window but
    land on prefetched segments (linear buffering miss, Nonlinear Buffering hit).

    For each seek_when time W, picks the first prefetch segment whose seek_to
    time exceeds W + min_forward_ms.  Falls back to the last prefetch segment
    when near the end of the movie.
    """
    prefetch_sorted = sorted(prefetch_indices)
    prefetch_times = [seek_to_seconds_for_segment(s, seg_dur_ms) for s in prefetch_sorted]

    seeks = []
    for when in seek_when_times:
        target_time = when + min_forward_ms / 1000.0
        target_seg = None
        for seg, t in zip(prefetch_sorted, prefetch_times):
            if t > target_time:
                target_seg = seg
                break
        if target_seg is None:
            target_seg = prefetch_sorted[-1]

        seeks.append({"seek_when": when, "seek_to": seek_to_seconds_for_segment(target_seg, seg_dur_ms)})
    return seeks


def generate_comparison_bundle(
    num_seeks: int,
    total_s: float,
    seg_dur_ms: int,
    num_segments: int,
    buffer_threshold_ms: int,
    prefetch_count: int,
    mixed_hit_ratio: float = 0.5,
    seed: int | None = None,
    max_buffer_ms: int = 25000,
) -> tuple[dict, dict, dict, dict, dict, dict]:
    """
    Build (test_prefetch_config, seeks_prefetch_hit, seeks_miss, seeks_mixed,
           seeks_linear_hit_nonlinear_miss, seeks_linear_miss_nonlinear_hit):
    one shared prefetch list; hit seeks land on prefetched segments;
    miss seeks land on segments outside that list;
    mixed seeks have a random mix of hits and misses;
    linear_hit_nonlinear_miss seeks are short forward seeks to non-prefetched segments;
    linear_miss_nonlinear_hit seeks are far forward seeks to prefetched segments.
    """
    prefetch_indices = build_spaced_prefetch_indices(num_segments, prefetch_count)
    prefetch_set = set(prefetch_indices)

    complement = [i for i in range(num_segments) if i not in prefetch_set]
    if len(complement) < num_seeks:
        raise ValueError(
            f"Not enough non-prefetched segments ({len(complement)}) for "
            f"{num_seeks} miss seeks — lower --prefetch-count or --num-seeks."
        )

    schedule = build_seek_when_schedule(num_seeks, total_s, seg_dur_ms)

    # Per-seek forward-only targets: each entry is for the corresponding seek_when.
    # Hit seeks must land beyond the linear buffer window (max_buffer_ms) so that
    # the linear buffer always misses while the prefetched Nonlinear Buffer hits.
    hit_targets = build_forward_seek_targets(
        prefetch_indices, schedule, seg_dur_ms, min_forward_ms=max_buffer_ms
    )
    miss_targets = build_forward_seek_targets(complement, schedule, seg_dur_ms)

    seeks_hit = generate_seeks_for_segment_targets(
        hit_targets, schedule, seg_dur_ms, num_segments
    )
    seeks_miss = generate_seeks_for_segment_targets(
        miss_targets, schedule, seg_dur_ms, num_segments
    )

    # Mixed: randomly assign each seek position to hit or miss, then pick the
    # corresponding per-seek forward target so seek_to > seek_when always holds.
    rng = random.Random(seed)
    num_hits = max(0, min(num_seeks, round(num_seeks * mixed_hit_ratio)))
    assignment = [True] * num_hits + [False] * (num_seeks - num_hits)
    rng.shuffle(assignment)
    mixed_targets = []
    for i in range(num_seeks):
        h = hit_targets[i] if i < len(hit_targets) else None
        m = miss_targets[i] if i < len(miss_targets) else None
        if assignment[i]:
            mixed_targets.append(h if h is not None else m)
        else:
            mixed_targets.append(m if m is not None else h)
    seeks_mixed = generate_seeks_for_segment_targets(
        mixed_targets, schedule, seg_dur_ms, num_segments
    )

    seeks_lin_hit_nonlin_miss = generate_linear_hit_nonlinear_miss_seeks(
        schedule, prefetch_set, seg_dur_ms, num_segments
    )
    seeks_lin_miss_nonlin_hit = generate_linear_miss_nonlinear_hit_seeks(
        schedule, prefetch_indices, seg_dur_ms
    )

    prefetch_config = {
        "buffer_level_threshold": buffer_threshold_ms,
        "prefetch": [{"segment": s} for s in prefetch_indices],
    }

    return (
        prefetch_config,
        {"seeks": seeks_hit},
        {"seeks": seeks_miss},
        {"seeks": seeks_mixed},
        {"seeks": seeks_lin_hit_nonlin_miss},
        {"seeks": seeks_lin_miss_nonlin_hit},
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Write test_prefetch_config.json, seeks_prefetch_hit.json, and seeks.json "
            "(prefetch hit vs miss comparison)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "-m", "--movie", default="movie.json",
        help="Movie manifest file (default: movie.json)",
    )
    parser.add_argument(
        "-n", "--num-seeks", type=int, default=6,
        help="Number of seek events per scenario (default: 6)",
    )
    parser.add_argument(
        "--prefetch-count",
        type=int,
        default=8,
        help="Number of prefetch segments (default: 8)",
    )
    parser.add_argument(
        "--buffer-threshold", type=int, default=15000,
        help="Buffer level threshold in ms (default: 15000)",
    )
    parser.add_argument(
        "-op", "--output-prefetch", default="test_prefetch_config.json",
        help="Output path for prefetch config (default: test_prefetch_config.json)",
    )
    parser.add_argument(
        "--output-prefetch-hit",
        default="seeks_prefetch_hit.json",
        help="Seek file for prefetch-hit scenario (default: seeks_prefetch_hit.json)",
    )
    parser.add_argument(
        "--output-seeks-miss",
        default="seeks.json",
        help="Seek file for prefetch-miss scenario (default: seeks.json)",
    )
    parser.add_argument(
        "--output-seeks-mixed",
        default="seeks_mixed.json",
        help="Seek file for mixed hit/miss scenario (default: seeks_mixed.json)",
    )
    parser.add_argument(
        "--output-linear-hit-nonlinear-miss",
        default="seeks_linear_hit_nonlinear_miss.json",
        help="Seek file for linear-hit/nonlinear-miss scenario (default: seeks_linear_hit_nonlinear_miss.json)",
    )
    parser.add_argument(
        "--output-linear-miss-nonlinear-hit",
        default="seeks_linear_miss_nonlinear_hit.json",
        help="Seek file for linear-miss/nonlinear-hit scenario (default: seeks_linear_miss_nonlinear_hit.json)",
    )
    parser.add_argument(
        "--mixed-hit-ratio", type=float, default=0.5,
        help="Fraction of seeks that hit prefetch in the mixed scenario (default: 0.5)",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Random seed for the mixed scenario shuffle (default: random)",
    )
    parser.add_argument(
        "--output-dir", default=None, metavar="DIR",
        help="Directory to write all output files into (default: same directory as this script)",
    )
    parser.add_argument(
        "--max-buffer", type=int, default=25,
        help="Player max buffer size in seconds (default: 25). Hit seeks are placed "
             "beyond this window so the linear buffer always misses them.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print JSON to stdout; do not write files",
    )
    args = parser.parse_args()

    script_dir = Path(__file__).parent
    out_dir = Path(args.output_dir) if args.output_dir else script_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    movie_path = script_dir / args.movie
    if not movie_path.exists():
        print(f"Error: Movie file not found: {movie_path}", file=sys.stderr)
        sys.exit(1)

    movie_data = load_movie(str(movie_path))
    num_segments, seg_dur_ms, total_s = movie_info(movie_data)

    print(f"Movie: {num_segments} segments x {seg_dur_ms}ms = {total_s:.1f}s total")

    if not (0.0 <= args.mixed_hit_ratio <= 1.0):
        print("Error: --mixed-hit-ratio must be between 0.0 and 1.0", file=sys.stderr)
        sys.exit(1)

    try:
        (
            prefetch_config,
            seeks_hit_cfg,
            seeks_miss_cfg,
            seeks_mixed_cfg,
            seeks_lin_hit_nonlin_miss_cfg,
            seeks_lin_miss_nonlin_hit_cfg,
        ) = generate_comparison_bundle(
            num_seeks=args.num_seeks,
            total_s=total_s,
            seg_dur_ms=seg_dur_ms,
            num_segments=num_segments,
            buffer_threshold_ms=args.buffer_threshold,
            prefetch_count=args.prefetch_count,
            mixed_hit_ratio=args.mixed_hit_ratio,
            seed=args.seed,
            max_buffer_ms=args.max_buffer * 1000,
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    pf_segs = set(e["segment"] for e in prefetch_config["prefetch"])
    num_hits = sum(
        1 for s in seeks_mixed_cfg["seeks"]
        if segment_index_for_time(s["seek_to"], seg_dur_ms) in pf_segs
    )
    print("\n--- Comparison bundle ---")
    print(f"Prefetch ({args.output_prefetch}): threshold={args.buffer_threshold}ms, "
          f"segments={sorted(pf_segs)}")
    print(f"Seeks (hit):                   {args.output_prefetch_hit} -> all seek_to land on prefetched segments")
    print(f"Seeks (miss):                  {args.output_seeks_miss} -> all seek_to miss prefetch")
    print(f"Seeks (mixed):                 {args.output_seeks_mixed} -> {num_hits}/{args.num_seeks} hit "
          f"(ratio={args.mixed_hit_ratio}, seed={args.seed})")
    print(f"Seeks (linear hit, nonlinear miss):  {args.output_linear_hit_nonlinear_miss} -> short forward seeks, non-prefetch targets")
    print(f"Seeks (linear miss, nonlinear hit):  {args.output_linear_miss_nonlinear_hit} -> far forward seeks, prefetch targets")

    for label, cfg in (
        ("prefetch_hit", seeks_hit_cfg),
        ("prefetch_miss", seeks_miss_cfg),
        ("mixed", seeks_mixed_cfg),
        ("linear_hit_nonlinear_miss", seeks_lin_hit_nonlin_miss_cfg),
        ("linear_miss_nonlinear_hit", seeks_lin_miss_nonlin_hit_cfg),
    ):
        print(f"\n  {label}:")
        for i, s in enumerate(cfg["seeks"], 1):
            seg_idx = segment_index_for_time(s["seek_to"], seg_dur_ms)
            hit = "HIT" if seg_idx in pf_segs else "miss"
            fwd = s["seek_to"] - s["seek_when"]
            print(f"    {i}. when={s['seek_when']}s -> {s['seek_to']}s (seg {seg_idx}, {hit}, {fwd:+.1f}s)")

    if args.dry_run:
        print("\n--- test_prefetch_config.json ---")
        print(json.dumps(prefetch_config, indent=2))
        print("\n--- seeks_prefetch_hit ---")
        print(json.dumps(seeks_hit_cfg, indent=2))
        print("\n--- seeks (miss) ---")
        print(json.dumps(seeks_miss_cfg, indent=2))
        print("\n--- seeks (mixed) ---")
        print(json.dumps(seeks_mixed_cfg, indent=2))
        print("\n--- seeks_linear_hit_nonlinear_miss ---")
        print(json.dumps(seeks_lin_hit_nonlin_miss_cfg, indent=2))
        print("\n--- seeks_linear_miss_nonlinear_hit ---")
        print(json.dumps(seeks_lin_miss_nonlin_hit_cfg, indent=2))
        print("\n(dry run — no files written)")
        return

    paths = [
        (out_dir / args.output_prefetch, prefetch_config),
        (out_dir / args.output_prefetch_hit, seeks_hit_cfg),
        (out_dir / args.output_seeks_miss, seeks_miss_cfg),
        (out_dir / args.output_seeks_mixed, seeks_mixed_cfg),
        (out_dir / args.output_linear_hit_nonlinear_miss, seeks_lin_hit_nonlin_miss_cfg),
        (out_dir / args.output_linear_miss_nonlinear_hit, seeks_lin_miss_nonlin_hit_cfg),
    ]
    for path, obj in paths:
        with open(path, "w") as f:
            json.dump(obj, f, indent=2)
            f.write("\n")
        print(f"\n-> Wrote {path}")

    sc_list = ",".join(str(out_dir / f) for f in [
        args.output_seeks_miss,
        args.output_prefetch_hit,
        args.output_seeks_mixed,
        args.output_linear_hit_nonlinear_miss,
        args.output_linear_miss_nonlinear_hit,
    ])
    print("\nRun multi-scenario comparison with:")
    print(
        f"  python run_comparison.py"
        f" -n {out_dir / 'network.json'}"
        f" -m {movie_path}"
        f" -sc {sc_list}"
        f" -pc {out_dir / args.output_prefetch}"
        f" -a all"
        f" -o {out_dir / 'results'}"
    )


if __name__ == "__main__":
    main()
