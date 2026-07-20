# StreamLens Simulation Guide

StreamLens is a Python-based simulation environment for evaluating Adaptive Bitrate (ABR) streaming algorithms under realistic seek and prefetch conditions. It extends the original SABRE simulator with a nonlinear multi-region buffer (`MultiRegionBuffer`) that preserves buffered segments across seek events and supports out-of-order prefetch downloads.

---

## Table of Contents

- [System Architecture](#system-architecture)
- [Comparison Workflows](#comparison-workflows)
- **Part I — Core Simulation**
  - [Setup & Prerequisites](#setup--prerequisites)
  - [Network Configuration](#network-configuration)
  - [Running Simulations](#running-simulations)
  - [Regression Testing](#regression-testing)
- **Part II — Nonlinear Buffering (`buffer.py`)**
  - [Overview](#overview)
  - [Running Buffer Comparisons](#running-buffer-comparisons)
  - [Viewing Results](#viewing-results)
  - [Understanding Results](#understanding-results)
  - [Generating Seek & Prefetch Configs](#generating-seek--prefetch-configs)
  - [Prefetch Comparison Workflow (Synthetic)](#prefetch-comparison-workflow-synthetic)
  - [Testing](#testing)
  - [Technical Reference](#technical-reference)
  - [Advanced Usage](#advanced-usage)
  - [Troubleshooting](#troubleshooting)
- **Part III — Session-replay Workflow**
  - [Collecting Traces](#collecting-traces)
  - [Parsing Traces](#parsing-traces)
  - [Session Replay Prefetch Scenarios](#Session-replay-prefetch-scenarios)
  - [Running Session Replay Comparisons](#running-Session-replay-comparisons)
- **Reference**
  - [File Structure](#file-structure)

---

## System Architecture

The diagram below shows the module structure and component relationships of StreamLens.

![System Architecture](architecture_diagram.png)

---

## Comparison Workflows

StreamLens supports two comparison workflows — **Synthetic** and **Session-replay** — both converging into a shared simulation core that runs each scenario with and without `MultiRegionBuffer`.

| | Synthetic | Session-replay |
|---|---|---|
| **Video input** | Handcrafted | Handcrafted |
| **Network input** | Handcrafted | Real YouTube session |
| **Seek input** | Generated from video | Real YouTube session |
| **Prefetch input** | Generated from video | Derived from real seek destinations |
| **How to run** | `run_comparison.py` | `run_session_replay_comparison.py` |
| **Results saved to** | `synthetic/results/` | `session_replay/results/` |
| **Best use case** | Controlled experiments | Replay real user behavior |

---

# Part I — Core Simulation

---

## Setup & Prerequisites

### Install Dependencies
```bash
pip install numpy
```

### Required Files
- `synthetic/network.json` — Network trace file (can be generated)
- `synthetic/movie.json` — Movie manifest file
- `synthetic/seeks.json` — Seek configuration (optional)

---

## Network Configuration

### Generate network.json

Generate network conditions using `network_generator.py`:

```bash
python network_generator.py -ne 10 -d 4000 -bm 3000 -bs 1500 -lm 150 -ls 50
```

**Parameters:**
- `-ne, --num-entries`: Number of network condition entries (default: 10)
- `-d, --duration`: Total duration in milliseconds (default: 4000)
- `-bm, --bandwidth-mean`: Mean bandwidth (default: 3000)
- `-bs, --bandwidth-std`: Bandwidth standard deviation (default: 1500)
- `-lm, --latency-mean`: Mean latency (default: 150)
- `-ls, --latency-std`: Latency standard deviation (default: 50)

**Example:**
```bash
python network_generator.py -ne 20 -d 6000 -bm 5000 -bs 2000 -lm 100 -ls 30
```

---

## Running Simulations

### Basic Simulation

Run simulation with default settings:
```bash
python sabre.py -n synthetic/network.json -m synthetic/movie.json
```

### With Verbose Output
```bash
python sabre.py -v -n synthetic/network.json -m synthetic/movie.json
```

### With Seek Configuration

Run with seeks:
```bash
python sabre.py -v -n synthetic/network.json -m synthetic/movie.json -sc synthetic/seeks.json
```

---

## Regression Testing

Ensure simulation results remain consistent after code changes.

1. **Generate baseline results (run once):**

```bash
python test_simulation_regression.py --generate-baseline
```

**Important:** Regenerate the baseline whenever `synthetic/movie.json`, `synthetic/network.json`, or `synthetic/seeks.json` change.

2. **Run regression test:**

```bash
python test_simulation_regression.py
```

---

# Part II — Nonlinear Buffering (`buffer.py`)

Everything below relates to `MultiRegionBuffer` from `buffer.py` — the nonlinear, multi-region buffer that replaces the simple linear `buffer_contents` list.

---

## Overview

**What `buffer.py` adds:**

| | Linear Buffering (without) | Nonlinear Buffering (with) |
|---|---|---|
| Data structure | `gs.buffer_contents` — flat list of `(segment, quality)` tuples | `gs.multi_region_buffer` — `MultiRegionBuffer` with multiple `BufferRegion` objects |
| Regions | Single contiguous region | Multiple non-contiguous regions |
| Seek behaviour | Clears entire buffer on seeks outside range | Preserves regions after seek position and prefetch regions |
| Prefetch | Not supported | Supported — `add_prefetch_chunk` with provenance tracking |
| Region merging | N/A | Adjacent regions merge automatically |

The `--use-buffer-py` flag in `sabre.py` switches between the two modes. When the flag is absent, the simulation falls back to linear buffering.

---

## Running Buffer Comparisons

`run_comparison.py` runs `sabre.py` twice (with and without `--use-buffer-py`) and produces a JSON file for visualization. It optionally supports prefetch configuration.

### Quick Comparison

```bash
python run_comparison.py -n synthetic/network.json -m synthetic/movie.json -a bola -o comparison_results.json
```

### Compare Multiple ABR Algorithms

All supported algorithms:
```bash
python run_comparison.py -n synthetic/network.json -m synthetic/movie.json -a all -o comparison_results
```

Specific algorithms:
```bash
python run_comparison.py -n synthetic/network.json -m synthetic/movie.json -a bola,bolae,dynamic,dynamicdash,throughput -o comparison_results.json
```

### With Seek Configuration
```bash
python run_comparison.py -n synthetic/network.json -m synthetic/movie.json -a bola -sc synthetic/seeks.json -o my_comparison.json
```

### With Prefetch + Seek (All ABR Algorithms, Multiple Seek Scenarios)

The canonical synthetic workflow — runs all ABR algorithms against all five seek scenarios at once:

```bash
python run_comparison.py \
  -n synthetic/network.json -m synthetic/movie.json \
  -sc synthetic/seeks.json,synthetic/seeks_prefetch_hit.json,synthetic/seeks_mixed.json,synthetic/seeks_linear_hit_nonlinear_miss.json,synthetic/seeks_linear_miss_nonlinear_hit.json \
  -pc synthetic/test_prefetch_config.json \
  -a all -o synthetic/results
```

Results are grouped in subfolders named after each seek file's stem under `synthetic/results/`. Load `synthetic/results/comparison_summary.json` in the viewer for a cross-run table and charts.

### Command Parameters

| Flag | Description | Default |
|------|-------------|---------|
| `-n, --network` | Network trace file | `network.json` |
| `-m, --movie` | Movie manifest file | `movie.json` |
| `-a, --abr` | ABR algorithm(s) — single name, comma-separated list, or `all` | `bola` |
| `-sc, --seek-config` | Seek file(s) — one path, or comma-separated list (each stem gets a subfolder under `-o` when combined with multi-ABR or multi-seek) | *(none)* |
| `-pc, --prefetch-config` | Prefetch JSON (only used with `buffer.py` / prefetch path) | *(none)* |
| `-nm, --network-multiplier` | Network multiplier | `1.0` |
| `-o, --output` | Output JSON file (single run) **or** output **directory** (multiple ABRs and/or multiple `-sc` entries) | `comparison_results.json` |

When **multiple** ABR algorithms or **multiple** seek configs are used, `-o` must be a directory name; the tool writes `comparison_<abr>.json` files under it (and `comparison_summary.json` at the top level). For a single ABR and a single seek config, `-o` is a single JSON file path.

---

## Viewing Results

1. **Start the web server** from the `src/` directory:

```bash
python serve_viewer.py
```

2. Open the viewer (browser opens automatically): `http://localhost:8000/viewer/view_comparison.html`
3. Click **Load Comparison Data** and pick a JSON file.

### Single-run comparison JSON

Use a file produced by `run_comparison.py` for **one** ABR (and **one** seek config, if any), e.g. `comparison_bola.json`.

- **Summary cards** — total rebuffering time, rebuffering events, played utility, rebuffer ratio, Quality of Experience (QoE)
- **Charts** — rebuffering bar chart; buffer level over time; quality over time; quality distribution
- **Buffer level chart** — dashed red curve = baseline without `buffer.py`; solid green curve = with `buffer.py` + prefetching. Seek markers are drawn as numbered vertical lines: green = seek target hit a prefetched chunk; orange = seek target missed. Prefetch download periods are shown as a shaded band.
- **Prefetch / seek panel** — when the JSON includes prefetch and seek events, the viewer shows annotations on the time-series charts

### Multi-run summary (`comparison_summary.json`)

When you load a **`comparison_summary.json`** (synthetic or Session Replay), the viewer shows:

- **Summary run header** — network, movie, prefetch config, and ABR algorithms. For Session Replay summaries (one prefetch config per scenario) this shows `one config per scenario (5 total)` instead of a single filename.
- **Scenario legend cards** — one card per scenario, each showing its prefetch config and a one-line description of which buffering mode hits or misses the prefetch chunk.
- **Cross-Comparison Summary** — table with rows for each **scenario × ABR**. Each metric column shows `without → with` values plus a **Change** column (green = improved, red = worse). Columns: Rebuf Events, Rebuf Time, Utility, QoE.
- **Summary bar charts** — Rebuffering Events and Rebuffering Time across all runs.
- **Row click (drill-down)** — click a row to see per-run detail charts; summary stays visible.

### Loading results in the viewer

| Data | File to load |
|------|-------------|
| Synthetic scenarios | `synthetic/results/comparison_summary.json` |
| Session Replay scenarios | `session_replay/results/comparison_summary.json` |
| Single synthetic run | `synthetic/results/<scenario>/comparison_<abr>.json` |
| Single Session Replay run | `session_replay/results/<scenario>/comparison_<abr>.json` |

---

## Understanding Results

### Quality of Experience (QoE)

The primary single-number metric combining quality and rebuffering:

```
QoE = ū − β·ρ_rebuf − γ·p_switch   where u_i = log(b_i / b_0)
```

- **ū** — average u_i (playback utility normalized by the lowest possible bitrate)
- **ρ_rebuf = rebuffer_time / total_play_time** — rebuffering ratio (fraction of session spent stalled)
- **p_switch = N_switch / T_seconds** — quality-switch rate (each change between adjacent played chunks counts as one switch, regardless of direction or magnitude)
- **β = 10, γ = 1**

Higher QoE is better. A run that gains utility but adds rebuffering will only show a net improvement if the utility gain outweighs the penalty.

### Positive Indicators (Green)
- **Lower rebuffering time/events** — `MultiRegionBuffer` preserves segments after seeks
- **Higher utility** — better quality decisions from improved buffer management
- **Lower rebuffer ratio** — more efficient buffering with preserved segments
- **Higher QoE** — combined improvement across quality and rebuffering

### Negative Indicators (Red)
- **Higher rebuffering** — prefetch fired but targeted wrong segments, wasting bandwidth
- **Lower utility** — quality decisions degraded
- **Lower QoE** — combined degradation outweighs any partial gains

> The comparison uses identical ABR algorithms and network conditions, so differences come purely from buffer management strategy.

### Expected Improvements

With `buffer.py` (`MultiRegionBuffer`) and correct prefetch targets (seeks land on prefetched segments), nonlinear buffering can reduce rebuffering events and rebuffering time while maintaining or improving QoE. When prefetch targets do not align with seek destinations, results are more mixed — some ABR algorithms may reduce rebuffering events but QoE does not reliably improve. Prefetching is not automatically beneficial; its value depends on whether prefetched chunks are reused after seeks and how each ABR policy responds to the changed buffer state.

---

## Generating Seek & Prefetch Configs

`generate_configs.py` reads `synthetic/movie.json` and writes four files for **prefetch hit / miss / mixed** comparisons:

| File | Role |
|------|------|
| `synthetic/test_prefetch_config.json` | Spaced prefetch segment list + buffer threshold |
| `synthetic/seeks_prefetch_hit.json` | Seeks whose targets land on prefetched segments |
| `synthetic/seeks.json` | Seeks whose targets **miss** the prefetch list |
| `synthetic/seeks_mixed.json` | Random mix of hit and miss seeks |

```bash
python generate_configs.py --num-seeks 30 --prefetch-count 35 --buffer-threshold 15000
```

### Command Parameters

| Flag | Description | Default |
|------|-------------|---------|
| `-m, --movie` | Movie manifest file | `movie.json` |
| `-n, --num-seeks` | Number of seek events per scenario | `6` |
| `--prefetch-count` | Number of prefetch segments | `8` |
| `--buffer-threshold` | Buffer level threshold in ms for prefetch | `15000` |
| `--output-prefetch-hit` | Seek file for prefetch-hit scenario | `seeks_prefetch_hit.json` |
| `--output-seeks-miss` | Seek file for prefetch-miss scenario | `seeks.json` |
| `--output-seeks-mixed` | Seek file for mixed hit/miss scenario | `seeks_mixed.json` |
| `-op, --output-prefetch` | Output path for prefetch config | `test_prefetch_config.json` |
| `--mixed-hit-ratio` | Fraction of seeks that hit prefetch in the mixed scenario | `0.5` |
| `--seed` | Random seed for the mixed scenario shuffle | *(random)* |
| `--dry-run` | Print JSON to stdout; do not write files | *(off)* |

---

## Prefetch Comparison Workflow (Synthetic)

The synthetic workflow varies the **seek pattern** across 5 scenarios with a fixed prefetch config and generated network. Each run executes two simulations — **without** `buffer.py` (baseline) and **with** `buffer.py` + prefetch.

### 5 Synthetic Seek Scenarios

| Scenario folder | Seek file | What it tests |
|----------------|-----------|--------------|
| `seeks/` | `seeks.json` | Both buffer modes miss the prefetch cache |
| `seeks_prefetch_hit/` | `seeks_prefetch_hit.json` | Seeks land on prefetched segments; nonlinear wins |
| `seeks_mixed/` | `seeks_mixed.json` | Mix of hits and misses |
| `seeks_linear_hit_nonlinear_miss/` | `seeks_linear_hit_nonlinear_miss.json` | Short seeks within linear buffer range; prefetch targets wrong segments |
| `seeks_linear_miss_nonlinear_hit/` | `seeks_linear_miss_nonlinear_hit.json` | Long seeks beyond linear range; prefetch targets correct segments |

### 1. Create seek + prefetch files

```bash
python generate_configs.py --num-seeks 30 --prefetch-count 35 --buffer-threshold 15000
```

Move outputs to `synthetic/`:
```bash
mv test_prefetch_config.json seeks.json seeks_prefetch_hit.json seeks_mixed.json synthetic/
```

### 2. Run all scenarios

```bash
python run_comparison.py \
  -n synthetic/network.json -m synthetic/movie.json \
  -sc synthetic/seeks.json,synthetic/seeks_prefetch_hit.json,synthetic/seeks_mixed.json,synthetic/seeks_linear_hit_nonlinear_miss.json,synthetic/seeks_linear_miss_nonlinear_hit.json \
  -pc synthetic/test_prefetch_config.json \
  -a all -o synthetic/results
```

### 3. View results

```bash
python serve_viewer.py
# Load: synthetic/results/comparison_summary.json
```

---

## Testing

### Buffer Equivalence Tests

Verify that linear and Nonlinear Buffers produce identical output during sequential chunk downloads:
```bash
python test_buffer_equivalence.py
```

**Options:**
- `--quick` — run quick test only
- `--abr <algorithm>` — test specific ABR algorithm
- `-v, --verbose` — verbose output

### Nonlinear Buffer Case Tests

Run case-based tests that verify the Nonlinear Buffer algorithm handles each scenario correctly:
```bash
python test_nonlinear_buffer_cases.py
```

With verbose output:
```bash
python test_nonlinear_buffer_cases.py -v
```

The suite contains 14 tests across two test classes:

**TestNonlinearBuffering** (Tests 1–10) — buffer seek and prefetch logic:

| # | Test | What it verifies |
|---|------|------------------|
| 1 | Seek to prefetched chunk | Seeking to a prefetched position does not rebuffer |
| 2 | Seek to non-prefetched positions | Adjacent-gap and far-out misses both rebuffer |
| 3 | Multiple seeks with multiple prefetch | Two sequential seeks to different prefetch targets |
| 4 | Prefetch preserved, linear cleaned | Prefetch regions survive across seeks; linear data cleaned |
| 5 | Adjacent prefetch merge | Prefetch chunk adjacent to linear region merges; provenance tracked |
| 6 | Seek within linear buffer (baseline) | Seeking inside a linear-only buffer works without prefetch |
| 7 | Contiguous prefetch buffer level | Buffer level reflects multiple contiguous prefetch chunks |
| 8 | Non-contiguous prefetch regions | Hit and miss across disjoint prefetch regions |
| 9 | Non-prefetch regions after seek preserved | Regions after the seek position are kept regardless of prefetch |
| 10 | Prefetch in same region preserved | Prefetch chunks before seek position are saved as a separate region |

**TestPrefetchModule** (Tests 11–14) — `PrefetchModule` API:

| # | Test | What it verifies |
|---|------|------------------|
| 11 | JSON loading | Config file parsed correctly (segments, threshold) |
| 12 | Trigger logic | `should_prefetch` respects buffer threshold |
| 13 | Segment exhaustion | Returns `None` after all segments are prefetched |
| 14 | Skip already-prefetched | Linear download loop skips prefetched segments |

**Required fixture:** `synthetic/test_prefetch_config_fixture.json`.

---

## Technical Reference

### Buffer Level Calculation

Both modes use the same formula:
```python
buffer_level = segment_time * len(playable_chunks) - buffer_fcc
```

| | `playable_chunks` source |
|---|---|
| Linear | All items in `buffer_contents` |
| Nonlinear | Contiguous chunks from `current_playback_pos` (gaps excluded) |

Nonlinear Buffering does not inflate buffer level with gaps between regions.

### Seek Behavior Comparison

| Scenario | Linear Buffer | Nonlinear Buffer |
|----------|--------------|----------------|
| Seek within range | Trim from front | Trim from front, preserve ahead |
| Forward seek outside | Clear buffer | Clear buffer, can prefetch |
| Backward seek | Clear buffer | Clear buffer, preserve ahead if exists |
| Multiple seeks | Always clear | Preserve segments across seeks |

### Performance Characteristics

| | Linear | Nonlinear |
|---|---|---|
| Append / pop | O(1) / O(n) | O(1) / O(1) |
| Region lookup | N/A | O(log n) |
| Merge | N/A | O(1) |
| Memory | Single list | Slight overhead (region objects) |
| Prefetching | Not supported | Supported |

### When to Use Each Mode

**Linear Buffering (without `buffer.py`):**
- Simple sequential playback
- No seeks expected
- Baseline comparison

**Nonlinear Buffering (with `buffer.py`):**
- Scenarios with user seeks
- Prefetching strategies
- Non-sequential segment access

---

## Advanced Usage

### Custom Metrics

Modify `run_comparison.py` to capture additional fields from `sabre.py` output, merge them into the saved JSON, and extend `viewer/view_comparison.html` to display them.

### Extending the Viewer

`viewer/view_comparison.html` holds both the **summary dashboard** (for `comparison_summary.json`) and the **detail** charts (single-run JSON or drill-down). When adding new seek or prefetch scenarios, extend the `SEEK_SCENARIO_MAP` object in the viewer with the scenario's stem, title, short label, CSS class (`hit`, `miss`, or `mixed`), and description blurb.

---

## Troubleshooting

**Simulation fails:**
- Ensure `synthetic/network.json` and `synthetic/movie.json` exist
- Check ABR algorithm name is correct
- Verify Python dependencies are installed

**Web viewer doesn't load:**
- Check port 8000 is available
- Ensure `serve_viewer.py` is run from `src/`
- Check browser console for errors (F12)

**No data / empty charts:**
- Verify JSON file structure matches expected format
- Check that simulations completed successfully
- Ensure `time_series` data is present in JSON

**Summary bar charts disappear after clicking a table row:**
- Fixed in current viewer: drill-down only destroys **detail** chart instances, not the summary dashboard. Hard-refresh the page (`Ctrl+F5`) if you cached an old HTML file.

---

# Part III — Session Replay Workflow

Session Replays capture actual YouTube viewing sessions (network conditions + seek events) from the browser. The workflow converts a raw CSV into simulation inputs, then runs the same 5-scenario prefetch comparison as the synthetic data — but with fixed real seeks and a varying prefetch strategy instead of varying seek patterns.

---

## Collecting Traces

The `yt_trace_collector/` Chrome extension records bandwidth conditions and seek events while watching YouTube.

### One-time setup

1. Open Chrome and go to `chrome://extensions`
2. Enable **Developer mode** (top-right toggle)
3. Click **Load unpacked** and select the `src/yt_trace_collector/` folder
4. The "YouTube Trace Collector" icon appears in the toolbar

### Collecting a trace

1. Go to YouTube and open any video
2. Watch it — the extension records network conditions, seek events, and stall times automatically
3. Seek, pause, or skip around as desired; all events are captured

### Exporting

1. Click the extension icon in the toolbar
2. The popup shows how many traces have been collected
3. Click **Export CSV** — downloads `yt_traces_<date>.csv`
4. Move the file to `src/session_replay/`
5. Optionally click **Clear all traces** to reset for the next session

> Each YouTube session produces one trace (one UUID). Watching multiple videos before exporting produces multiple traces in one CSV — `parse_session_replays.py` processes all of them and you pick the UUID you want to simulate.

---

## Parsing Traces

`parse_session_replays.py` converts a CSV of traces into SABRE-compatible `network_<uuid>.json` and `seeks_<uuid>.json` files.

```bash
python parse_session_replays.py session_replay/yt_traces_2026-04-18.csv --output-dir session_replay/
```

**Options:**

| Flag | Description | Default |
|------|-------------|---------|
| `--output-dir` | Where to write `network_<uuid>.json` and `seeks_<uuid>.json` | current directory |
| `--min-seek` | Minimum position gap (seconds) to count as a seek event | `0.5` |

---

## Session Replay Prefetch Scenarios

For Session Replays the seeks are fixed (real user behaviour) so the 5 scenarios vary the **prefetch strategy** instead of the seek pattern. Each scenario corresponds to a prefetch config JSON in `session_replay/`.

The example trace (UUID `56329467-babb-4d75-bb58-70f3906369fe`) has a significant 39.7 s forward seek from 148.6 s → 188.3 s, landing at **segment 62** (3 s segments). Network is throttled at 354–1346 kbps, so `buffer_level_threshold` must be ≤ 3500 ms for prefetch to fire.

| Scenario | Config file | Threshold | Prefetch targets | What it tests |
|----------|-------------|-----------|-----------------|--------------|
| `seeks_miss` | `prefetch_config_real_seeks_miss.json` | 3 500 ms | segs 45–46 | Both linear and Nonlinear Buffering miss the prefetch chunk |
| `prefetch_hit` | `prefetch_config_real_prefetch_hit.json` | 3 500 ms | segs 62–63 | Both linear and Nonlinear Buffering hit the prefetch chunk |
| `mixed` | `prefetch_config_real_mixed.json` | 3 500 ms | segs 62–63 + 75–76 | Some seeks hit the prefetch chunk; others miss it |
| `linear_hit_nonlinear_miss` | `prefetch_config_real_linear_hit_nonlinear_miss.json` | 3 500 ms | segs 75–79 | Linear buffering hits the prefetch chunk; Nonlinear Buffering misses it |
| `linear_miss_nonlinear_hit` | `prefetch_config_real_linear_miss_nonlinear_hit.json` | 3 500 ms | segs 62–65 | Nonlinear Buffering hits the prefetch chunk; linear buffering misses it |

To create a new prefetch config:
```json
{
  "buffer_level_threshold": 3500,
  "prefetch": [
    { "segment": 62 },
    { "segment": 63 }
  ]
}
```

**Key rules:**
- `buffer_level_threshold` must be below what the throttled network can sustain (≤ 3500 ms for this trace).
- Prefetch targets must be near the seek destination (segment = `floor(seek_to_seconds / 3)`).
- Targeting too many segments on a throttled network starves the main stream.

---

## Running Session Replay Comparisons

After parsing a new trace, generate its prefetch configs and set the active UUID:

```bash
python setup_session_replay.py <uuid>
```

Then run all 5 scenarios and merge the results:

```bash
python run_session_replay_comparison.py
```

This runs each scenario via `run_comparison.py` (with all ABR algorithms), then calls `merge_session_replay_summaries.py` to produce the merged summary. Each scenario writes `session_replay/results/<scenario>/comparison_<abr>.json` (5 ABR files) and a per-scenario `comparison_summary.json`. The final merged file is `session_replay/results/comparison_summary.json`.

**View Session Replay results:**
```bash
python serve_viewer.py
# Load: session_replay/results/comparison_summary.json
```

---

# File Structure

```
sabre/src/
│
├── sabre.py                          # Core simulator
├── buffer.py                         # MultiRegionBuffer (Nonlinear Buffering)
├── prefetch.py                       # PrefetchModule
├── global_state.py                   # GlobalState singleton
├── abr_algorithms.py                 # ABR algorithm implementations
│
├── run_comparison.py                 # With vs without buffer.py; writes comparison_summary.json
├── run_session_replay_comparison.py      # Runs 5 Session-replay scenarios, regenerates prefetch configs per movie
├── setup_session_replay.py               # Generates prefetch configs from trace UUID + movie; updates run_session_replay_comparison.py
├── serve_viewer.py                   # HTTP server for the viewer (port 8000)
├── network_generator.py              # Generates synthetic network.json (-o flag for output path)
├── generate_configs.py               # Generates seeks + prefetch configs for synthetic scenarios
├── parse_session_replays.py              # Converts YouTube trace CSV → network/seeks JSON
├── merge_session_replay_summaries.py     # Merges 5 Session-replay scenario summaries into one
│
├── test_buffer_equivalence.py        # Linear ↔ Nonlinear Buffer equivalence tests
├── test_nonlinear_buffer_cases.py      # Nonlinear Buffer algorithm case tests
│
├── viewer/
│   └── view_comparison.html          # Main viewer: single-run + comparison_summary.json dashboard
│
├── synthetic/                        # Synthetic scenario inputs and results
│   ├── movie.json                    # Video manifest (shared by synthetic and Session Replay runs)
│   ├── network.json                  # Generated synthetic network trace
│   ├── seeks.json                    # Seeks that miss the prefetch list
│   ├── seeks_prefetch_hit.json       # Seeks aligned with prefetch targets
│   ├── seeks_mixed.json              # Random mix of hit and miss seeks
│   ├── seeks_linear_hit_nonlinear_miss.json
│   ├── seeks_linear_miss_nonlinear_hit.json
│   ├── test_prefetch_config.json     # Prefetch config used for synthetic runs
│   ├── test_prefetch_config_fixture.json  # Fixture for unit tests
│   └── results/                      # Output from synthetic run_comparison.py
│       ├── comparison_summary.json   # Load this in the viewer
│       ├── seeks/
│       │   └── comparison_<abr>.json
│       ├── seeks_prefetch_hit/
│       ├── seeks_mixed/
│       ├── seeks_linear_hit_nonlinear_miss/
│       └── seeks_linear_miss_nonlinear_hit/
│
├── session_replay/                       # Session-replay: real YouTube trace inputs and results
│   ├── yt_traces_2026-04-18.csv      # Raw trace CSV from the browser extension
│   ├── network_<uuid>.json           # Real network trace (from parse_session_replays.py)
│   ├── seeks_<uuid>.json             # Real seek events (from parse_session_replays.py)
│   ├── prefetch_config_real_seeks_miss.json          # Regenerated by run_session_replay_comparison.py
│   ├── prefetch_config_real_prefetch_hit.json        #   whenever a new movie is used
│   ├── prefetch_config_real_mixed.json
│   ├── prefetch_config_real_linear_hit_nonlinear_miss.json
│   ├── prefetch_config_real_linear_miss_nonlinear_hit.json
│   └── results/                      # Output from run_session_replay_comparison.py
│       ├── comparison_summary.json   # Load this in the viewer
│       ├── seeks_miss/
│       │   └── comparison_<abr>.json
│       ├── prefetch_hit/
│       ├── mixed/
│       ├── linear_hit_nonlinear_miss/
│       └── linear_miss_nonlinear_hit/
│
├── yt_trace_collector/               # Chrome extension for collecting YouTube traces
│   ├── manifest.json
│   ├── collector.js
│   ├── content.js
│   ├── bridge.js
│   ├── popup.html
│   └── popup.js
│
```
