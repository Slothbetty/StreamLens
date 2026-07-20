#!/usr/bin/env python3
"""
Run simulations with and without buffer.py and collect metrics for web
visualisation.

Without buffer.py  : linear buffering, no prefetch, seeks clear the buffer.
With buffer.py     : Nonlinear Buffering + optional prefetch, seeks can hit
                     pre-downloaded chunks and avoid rebuffering.

The JSON output is compatible with view_comparison.html (which auto-detects
prefetch/seek data, seek markers, prefetch info, and per-stall durations when present).
"""

import sys
import subprocess
import json
import argparse
import re
from pathlib import Path


_DOWNLOAD_RE = re.compile(
    r'\[(\d+)-(\d+)\]\s+(\d+):\s+quality=(\d+).*?buffer_level=(-?\d+)->(-?\d+)')
_PREFETCH_RE = re.compile(
    r'\[(\d+)-(\d+)\] prefetch segment (\d+) quality=(\d+) bl=(\d+)->(\d+)')
_SEEK_RE = re.compile(
    r'\[Seek\] At playback time (\d+) ms: seeking from segment (\d+) to (\d+) seconds \(segment index (\d+)\)')

_SUMMARY_KEYS = [
    ('total_rebuffer_time', 'total rebuffer:'),
    ('rebuffer_count',      'total rebuffer events:'),
    ('total_play_time',     'total play time:'),
    ('played_utility',      'total played utility:'),
    ('played_bitrate',      'total played bitrate:'),
    ('rebuffer_ratio',      'rebuffer ratio:'),
    ('rampup_time',         'rampup time:'),
    ('qoe_score',           'qoe score:'),
]

SUPPORTED_ABRS = ['bola', 'bolae', 'dynamic', 'dynamicdash', 'throughput']


def parse_simulation_output(output):
    """Parse verbose simulation output to extract metrics, prefetch and seek events."""
    metrics = {
        'summary': {},
        'download_events': [],
        'prefetch_events': [],
        'seek_events': [],
        'rebuffer_starts_s': None,
        'rebuffer_durations_s': None,
    }

    for line in output.split('\n'):
        stripped = line.strip()
        if stripped.lower().startswith('rebuffer_starts_ms:'):
            rest = stripped.split(':', 1)[1].strip()
            if rest:
                metrics['rebuffer_starts_s'] = [
                    int(p) / 1000.0 for p in rest.split(',') if p.strip()
                ]
            else:
                metrics['rebuffer_starts_s'] = []
            continue

        if stripped.lower().startswith('rebuffer_durations_ms:'):
            rest = stripped.split(':', 1)[1].strip()
            if rest:
                metrics['rebuffer_durations_s'] = [
                    int(p) / 1000.0 for p in rest.split(',') if p.strip()
                ]
            else:
                metrics['rebuffer_durations_s'] = []
            continue

        m = _DOWNLOAD_RE.search(line)
        if m:
            start_time, end_time, segment, quality, bl_before, bl_after = m.groups()
            metrics['download_events'].append({
                'start_time': int(start_time),
                'end_time': int(end_time),
                'segment': int(segment),
                'quality': int(quality),
                'buffer_level_before': int(bl_before),
                'buffer_level_after': int(bl_after),
            })
            continue

        m = _PREFETCH_RE.search(line)
        if m:
            start_time, end_time, seg, quality, bl_before, bl_after = m.groups()
            metrics['prefetch_events'].append({
                'start_time': int(start_time),
                'end_time': int(end_time),
                'segment': int(seg),
                'quality': int(quality),
                'buffer_level_before': int(bl_before),
                'buffer_level_after': int(bl_after),
            })
            continue

        m = _SEEK_RE.search(line)
        if m:
            seek_when_ms, from_seg, seek_to_s, seg_idx = m.groups()
            metrics['seek_events'].append({
                'seek_when_s': int(seek_when_ms) / 1000.0,
                'from_segment': int(from_seg),
                'seek_to_s': int(seek_to_s),
                'segment': int(seg_idx),
            })
            continue

        lower = line.lower()
        for key, label in _SUMMARY_KEYS:
            if label in lower:
                try:
                    val = float(re.search(r':\s*([\d.]+)', line).group(1))
                    if key == 'rebuffer_count':
                        val = int(val)
                    metrics['summary'][key] = val
                except (AttributeError, ValueError):
                    pass
                break

    time_series = {
        'time_points': [],
        'buffer_levels': [],
        'qualities': [],
        'segments': [],
    }
    for ev in metrics['download_events']:
        bl_before = ev['buffer_level_before']
        download_duration = ev['end_time'] - ev['start_time']

        # If the buffer drains to 0 mid-download, insert an extra point at the
        # moment it hit 0 so the chart shows the buffer actually reaching zero
        # rather than interpolating above it during the stall period.
        if bl_before > 0 and download_duration > bl_before:
            stall_start_s = (ev['start_time'] + bl_before) / 1000.0
            time_series['time_points'].append(stall_start_s)
            time_series['buffer_levels'].append(0.0)
            time_series['qualities'].append(ev['quality'])
            time_series['segments'].append(ev['segment'])

        time_series['time_points'].append(ev['end_time'] / 1000.0)
        time_series['buffer_levels'].append(max(0, ev['buffer_level_after']) / 1000.0)
        time_series['qualities'].append(ev['quality'])
        time_series['segments'].append(ev['segment'])

    metrics['time_series'] = time_series
    return metrics


def run_simulation(use_buffer_py, config):
    """Run a simulation and return parsed metrics."""
    script_dir = Path(__file__).parent
    cmd = [
        sys.executable, str(script_dir / 'sabre.py'),
        '-n', config['network'],
        '-m', config['movie'],
        '-a', config['abr'],
        '-nm', str(config.get('network_multiplier', 1.0)),
        '-v',
    ]

    if config.get('seek_config'):
        cmd.extend(['-sc', config['seek_config']])

    if use_buffer_py:
        cmd.append('--use-buffer-py')
        if config.get('prefetch_config'):
            cmd.extend(['-pc', config['prefetch_config']])

    label = 'WITH' if use_buffer_py else 'WITHOUT'
    if use_buffer_py and config.get('prefetch_config'):
        label += ' + prefetch'
    print(f"Running simulation {label} buffer.py ...")

    result = subprocess.run(
        cmd, cwd=script_dir, stdout=subprocess.PIPE, stderr=None, text=True)

    if result.returncode != 0:
        print(f"Error: Simulation failed:\n{result.stdout}", file=sys.stderr)
        return None

    return parse_simulation_output(result.stdout)


def print_summary(abr, metrics_without, metrics_with, has_prefetch):
    """Print a comparison summary table for one ABR run."""
    print(f"\nSummary Comparison for {abr}:")
    print(f"{'Metric':<30} {'Without buffer.py':<20} {'With buffer.py':<20} {'Change':<15}")
    print("-" * 85)

    for key in ['total_rebuffer_time', 'rebuffer_count', 'total_play_time',
                'played_utility', 'rebuffer_ratio', 'qoe_score']:
        v0 = metrics_without.get('summary', {}).get(key, 0)
        v1 = metrics_with.get('summary', {}).get(key, 0)
        if v0 != 0:
            pct = ((v1 - v0) / v0) * 100
            change = f"{pct:+.1f}%"
        elif v1 != 0:
            change = "N/A (was 0)"
        else:
            change = "0.0%"
        print(f"{key:<30} {str(v0):<20} {str(v1):<20} {change:<15}")

    if has_prefetch:
        pf = metrics_with.get('prefetch_events', [])
        sk = metrics_with.get('seek_events', [])
        print(f"\nPrefetch events: {len(pf)}")
        print(f"Seek events:     {len(sk)}")


def parse_abr_list(abr_arg):
    """Return a list of ABR algorithm names from the CLI argument."""
    if abr_arg.lower() == 'all':
        return list(SUPPORTED_ABRS)
    if ',' in abr_arg:
        abr_list = [a.strip() for a in abr_arg.split(',')]
        invalid = [a for a in abr_list if a not in SUPPORTED_ABRS]
        if invalid:
            print(f"Error: Invalid ABR algorithm(s): {invalid}", file=sys.stderr)
            print(f"Supported algorithms: {', '.join(SUPPORTED_ABRS)}", file=sys.stderr)
            sys.exit(1)
        return abr_list
    if abr_arg not in SUPPORTED_ABRS:
        print(f"Warning: '{abr_arg}' may not be a supported ABR algorithm.",
              file=sys.stderr)
        print(f"Supported algorithms: {', '.join(SUPPORTED_ABRS)}", file=sys.stderr)
    return [abr_arg]


def parse_seek_configs(sc_arg):
    """Return a list of seek config file paths from the CLI argument.

    Accepts a single filename, a comma-separated list, or None.
    """
    if sc_arg is None:
        return [None]
    if ',' in sc_arg:
        return [s.strip() for s in sc_arg.split(',') if s.strip()]
    return [sc_arg]


def seek_config_label(sc_path):
    """Derive a short directory-safe label from a seek config path."""
    if sc_path is None:
        return 'no_seeks'
    return Path(sc_path).stem


def main():
    parser = argparse.ArgumentParser(
        description='Compare simulation results with vs without buffer.py (+ optional prefetch)')
    parser.add_argument('-n', '--network', default='network.json',
                        help='Network trace file')
    parser.add_argument('-m', '--movie', default='movie.json',
                        help='Movie manifest file')
    parser.add_argument(
        '-a', '--abr', default='bola',
        help='ABR algorithm(s): single name, comma-separated list, or "all"')
    parser.add_argument(
        '-sc', '--seek-config',
        help='Seek config file(s): single name or comma-separated list')
    parser.add_argument('-pc', '--prefetch-config',
                        help='Prefetch JSON config file (only used with buffer.py)')
    parser.add_argument('-nm', '--network-multiplier', type=float, default=1.0,
                        help='Network multiplier')
    parser.add_argument(
        '-o', '--output', default='comparison_results.json',
        help='Output JSON file (single ABR) or output directory (multiple ABRs/seek configs)')
    args = parser.parse_args()

    abr_list = parse_abr_list(args.abr)
    sc_list = parse_seek_configs(args.seek_config)
    has_prefetch = args.prefetch_config is not None
    script_dir = Path(__file__).parent

    multi_abr = len(abr_list) > 1
    multi_sc = len(sc_list) > 1
    multi = multi_abr or multi_sc

    if multi:
        output_dir = script_dir / args.output
        output_dir.mkdir(exist_ok=True)
        all_results = {}

    for sc in sc_list:
        sc_label = seek_config_label(sc)

        if multi_sc:
            sc_dir = output_dir / sc_label
            sc_dir.mkdir(exist_ok=True)
            print(f"\n{'#' * 85}")
            print(f"Seek config: {sc or '(none)'}")
            print(f"{'#' * 85}")

        for abr in abr_list:
            run_label = f"{sc_label}/{abr}" if multi_sc else abr
            print(f"\n{'=' * 85}")
            print(f"Processing: ABR={abr}  seeks={sc or '(none)'}")
            print(f"{'=' * 85}")

            seek_config_data = None
            if sc:
                with open(sc) as f:
                    seek_config_data = json.load(f)

            config = {
                'network': args.network,
                'movie': args.movie,
                'abr': abr,
                'seek_config': sc,
                'seek_config_data': seek_config_data,
                'prefetch_config': args.prefetch_config,
                'network_multiplier': args.network_multiplier,
            }

            metrics_without = run_simulation(use_buffer_py=False, config=config)
            metrics_with = run_simulation(use_buffer_py=True, config=config)

            if metrics_without is None or metrics_with is None:
                print(f"Error: Simulation failed for {run_label}", file=sys.stderr)
                continue

            comparison = {
                'config': config,
                'without_buffer_py': metrics_without,
                'with_buffer_py': metrics_with,
            }

            if multi:
                if multi_sc:
                    output_path = sc_dir / f"comparison_{abr}.json"
                else:
                    output_path = output_dir / f"comparison_{abr}.json"
                all_results[run_label] = comparison
            else:
                output_path = script_dir / args.output

            with open(output_path, 'w') as f:
                json.dump(comparison, f, indent=2)

            print(f"\n-> Results saved to {output_path}")
            print_summary(abr, metrics_without, metrics_with, has_prefetch)

    if multi and all_results:
        summary_path = output_dir / "comparison_summary.json"
        with open(summary_path, 'w') as f:
            json.dump({
                'config': {
                    'network': args.network,
                    'movie': args.movie,
                    'seek_configs': [s for s in sc_list],
                    'prefetch_config': args.prefetch_config,
                    'network_multiplier': args.network_multiplier,
                },
                'algorithms': abr_list,
                'seek_configs': [seek_config_label(s) for s in sc_list],
                'results': all_results,
            }, f, indent=2)
        print(f"\n{'=' * 85}")
        print(f"-> Summary saved to {summary_path}")
        print(f"-> Individual results saved to {output_dir}/")

    print(f"\nOpen view_comparison.html via serve_viewer.py to see visualisations!")


if __name__ == '__main__':
    main()
