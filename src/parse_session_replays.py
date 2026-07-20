#!/usr/bin/env python3
"""
Parse real playback trace CSV files and convert them to SABRE-compatible
network and seeks JSON files.

CSV columns expected (order matters only for the first header row):
    browserInfo, osInfo, timeSincePageLoad, modified, uuid,
    stallDiffsString, videoId, timestamp, totalWatchTimeSeconds,
    watchRangeFrames, watchRangeSeconds

watchRangeSeconds format:  [[startSec, endSec, heightPx], ...]
stallDiffsString format:   [dur1, dur2, ...]   (stall durations in ms)

Usage
-----
    python parse_session_replays.py traces.csv
    python parse_session_replays.py traces.csv --output-dir out/
    python parse_session_replays.py traces.csv --min-seek 0.5   # gap >= 0.5 s counts as a seek
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_json_field(raw: str):
    """Parse a JSON-like field that may or may not be quoted by the CSV reader."""
    raw = raw.strip()
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Try converting single-quoted or bare brackets to valid JSON.
        cleaned = re.sub(r"'", '"', raw)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return []


def extract_seeks(watch_ranges: list, min_seek_s: float = 0.1) -> list:
    """
    Derive seek events from gaps between consecutive watch ranges.

    A seek is detected when the start of range[i+1] differs from the end of
    range[i] by more than *min_seek_s* seconds.

    Returns a list of {"seek_when": float, "seek_to": float} dicts, compatible
    with the sabre.py -sc (seek config) JSON format.
    """
    seeks = []
    for i in range(len(watch_ranges) - 1):
        prev_end = watch_ranges[i][1]
        next_start = watch_ranges[i + 1][0]
        gap = abs(next_start - prev_end)
        if gap >= min_seek_s:
            seeks.append({
                "seek_when": round(prev_end, 6),
                "seek_to":   round(next_start, 6),
            })
    return seeks


def parse_csv(path: str) -> list:
    """Read the CSV and return a list of raw row dicts."""
    with open(path, newline='', encoding='utf-8') as fh:
        reader = csv.DictReader(fh)
        return list(reader)


def process_row(row: dict, min_seek_s: float) -> dict:
    """
    Convert one CSV row into a structured trace dict suitable for both
    SABRE seek files and the visualisation JSON.
    """
    watch_ranges_raw = _parse_json_field(row.get('watchRangeSeconds', ''))
    stall_diffs_raw  = _parse_json_field(row.get('stallDiffsString', ''))
    network_raw      = _parse_json_field(row.get('networkPeriodsString', ''))

    # Normalise watch ranges to [[start, end, resolution], ...]
    watch_ranges = []
    for entry in watch_ranges_raw:
        if len(entry) >= 3:
            watch_ranges.append([float(entry[0]), float(entry[1]), int(entry[2])])
        elif len(entry) == 2:
            watch_ranges.append([float(entry[0]), float(entry[1]), 0])

    # Ensure stall_diffs is a flat list of numbers
    stall_diffs = []
    if isinstance(stall_diffs_raw, list):
        for v in stall_diffs_raw:
            try:
                stall_diffs.append(float(v))
            except (TypeError, ValueError):
                pass
    elif isinstance(stall_diffs_raw, (int, float)):
        stall_diffs = [float(stall_diffs_raw)]

    # Normalise network periods — keep only the keys sabre.py expects
    network_periods = []
    if isinstance(network_raw, list):
        for p in network_raw:
            if isinstance(p, dict) and 'bandwidth_kbps' in p:
                network_periods.append({
                    'duration_ms':    int(p.get('duration_ms', 5000)),
                    'bandwidth_kbps': float(p['bandwidth_kbps']),
                    'latency_ms':     float(p.get('latency_ms', 0)),
                })

    seeks = extract_seeks(watch_ranges, min_seek_s)

    total_watch = 0.0
    try:
        total_watch = float(row.get('totalWatchTimeSeconds', 0))
    except (TypeError, ValueError):
        pass

    return {
        'uuid':               row.get('uuid', '').strip(),
        'videoId':            row.get('videoId', '').strip(),
        'timestamp':          row.get('timestamp', '').strip(),
        'browserInfo':        row.get('browserInfo', '').strip(),
        'osInfo':             row.get('osInfo', '').strip(),
        'timeSincePageLoad':  float(row.get('timeSincePageLoad', 0) or 0),
        'totalWatchTimeSeconds': total_watch,
        'watchRanges':        watch_ranges,
        'stallDiffs':         stall_diffs,
        'networkPeriods':     network_periods,
        'seeks':              seeks,
    }


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def write_seeks_file(trace: dict, output_dir: Path) -> Path | None:
    """Write a sabre-compatible seeks JSON for one trace (only if it has seeks)."""
    if not trace['seeks']:
        return None
    safe_id = re.sub(r'[^\w\-]', '_', trace['uuid'] or trace['videoId'] or 'trace')
    out_path = output_dir / f"seeks_{safe_id}.json"
    with open(out_path, 'w') as fh:
        json.dump({'seeks': trace['seeks']}, fh, indent=2)
        fh.write('\n')
    return out_path


def write_network_file(trace: dict, output_dir: Path, min_duration_ms: int = 0) -> Path | None:
    """
    Write a sabre-compatible network JSON for one trace.

    The extension collector captures only a handful of 5-second buckets, so
    the recorded periods may be much shorter than the full video.  To avoid
    the simulation running out of network data we tile the recorded periods
    until they cover at least *min_duration_ms* milliseconds (defaults to
    the total watch time of the trace).  If no network periods were captured
    the file is not written and None is returned.
    """
    periods = trace.get('networkPeriods', [])
    if not periods:
        return None

    # Cover at least the full watch time (in ms), plus 10 % headroom.
    target_ms = min_duration_ms or int(trace['totalWatchTimeSeconds'] * 1000 * 1.1)
    total_recorded_ms = sum(p['duration_ms'] for p in periods)

    # Tile until we have enough coverage.
    full_periods = list(periods)
    if total_recorded_ms > 0:
        while sum(p['duration_ms'] for p in full_periods) < target_ms:
            full_periods.extend(periods)

    safe_id = re.sub(r'[^\w\-]', '_', trace['uuid'] or trace['videoId'] or 'trace')
    out_path = output_dir / f"network_{safe_id}.json"
    with open(out_path, 'w') as fh:
        json.dump(full_periods, fh, indent=2)
        fh.write('\n')
    return out_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Convert real playback trace CSV to SABRE seeks JSON + visualisation JSON.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('csv_file', help='Input CSV trace file')
    parser.add_argument(
        '-o', '--output-dir', default=None,
        help='Directory to write output files (default: same as CSV file)',
    )
    parser.add_argument(
        '--min-seek', type=float, default=0.1,
        help='Minimum gap between watch ranges (seconds) to count as a seek (default: 0.1)',
    )
    args = parser.parse_args()

    csv_path = Path(args.csv_file)
    if not csv_path.exists():
        print(f'Error: CSV file not found: {csv_path}', file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir) if args.output_dir else csv_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f'Reading traces from: {csv_path}')
    raw_rows = parse_csv(str(csv_path))
    print(f'Found {len(raw_rows)} trace row(s)')

    traces = [process_row(row, args.min_seek) for row in raw_rows]

    # --- Per-trace seeks + network files ---
    seeks_written   = 0
    network_written = 0
    network_paths   = {}   # uuid -> Path, for the final command hints

    for t in traces:
        safe_id = re.sub(r'[^\w\-]', '_', t['uuid'] or t['videoId'] or 'trace')

        out_seek = write_seeks_file(t, output_dir)
        if out_seek:
            print(f'  Seeks JSON:   {out_seek}  ({len(t["seeks"])} seek(s))')
            seeks_written += 1

        out_net = write_network_file(t, output_dir)
        if out_net:
            total_ms = sum(p['duration_ms'] for p in t['networkPeriods'])
            covered_ms = sum(p['duration_ms'] for p in json.loads(out_net.read_text()))
            print(f'  Network JSON: {out_net}  '
                  f'({len(t["networkPeriods"])} recorded period(s), '
                  f'{total_ms / 1000:.1f}s tiled to {covered_ms / 1000:.1f}s)')
            network_written += 1
            network_paths[t['uuid']] = out_net
        else:
            print(f'  Network JSON: (no networkPeriodsString captured — use default network.json)')

    if seeks_written == 0:
        print('  (No seeks detected — no per-trace seeks files written)')
    print(f'Wrote {seeks_written} seeks file(s), {network_written} network file(s)')

    # --- Summary ---
    print()
    print('--- Trace summary ---')
    for i, t in enumerate(traces, 1):
        ranges_str = ', '.join(
            f'{r[0]:.2f}–{r[1]:.2f}s @{r[2]}p' for r in t['watchRanges']
        )
        seeks_str = (
            ', '.join(f'{s["seek_when"]:.2f}->{s["seek_to"]:.2f}s' for s in t['seeks'])
            or '(none)'
        )
        stall_str = (
            ', '.join(f'{d:.0f}ms' for d in t['stallDiffs']) or '(none)'
        )
        net_str = (
            f'{len(t["networkPeriods"])} period(s)' if t['networkPeriods'] else '(none)'
        )
        print(f'\n  [{i}] {t["videoId"]} / {t["uuid"][:8]}...')
        print(f'      browser: {t["browserInfo"]}  os: {t["osInfo"]}')
        print(f'      total watch: {t["totalWatchTimeSeconds"]}s')
        print(f'      ranges:  {ranges_str}')
        print(f'      seeks:   {seeks_str}')
        print(f'      stalls:  {stall_str}')
        print(f'      network: {net_str}')

    # --- Command hints ---
    print()
    print('--- Run SABRE simulation ---')
    print('(Uses your real network conditions + existing movie.json as the video manifest)')
    print()
    for t in traces:
        safe_id = re.sub(r'[^\w\-]', '_', t['uuid'] or t['videoId'] or 'trace')
        net_arg  = network_paths.get(t['uuid'], 'network.json')
        seek_arg = (output_dir / f"seeks_{safe_id}.json") if t['seeks'] else None
        sc_flag  = f' -sc {seek_arg}' if seek_arg else ''
        print(f'  # Trace: {t["videoId"]} / {t["uuid"][:8]}...')
        print(f'  python run_comparison.py -n {net_arg} -m movie.json{sc_flag} -a all')
        print()


if __name__ == '__main__':
    main()
