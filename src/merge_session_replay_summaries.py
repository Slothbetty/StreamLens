#!/usr/bin/env python3
"""Merge 5 Session-replay scenario comparison_summary.json files into one."""

import json
import os

SCENARIOS = [
    "seeks_miss",
    "prefetch_hit",
    "mixed",
    "linear_hit_nonlinear_miss",
    "linear_miss_nonlinear_hit",
]

BASE_DIR = os.path.join(os.path.dirname(__file__), "session_replay", "results")

# Collect data from each scenario
all_results = {}
algorithms = None
seek_configs_seen = set()
prefetch_configs = []

for scenario in SCENARIOS:
    summary_path = os.path.join(BASE_DIR, scenario, "comparison_summary.json")
    with open(summary_path) as f:
        data = json.load(f)

    if algorithms is None:
        algorithms = data["algorithms"]

    prefetch_configs.append(data["config"]["prefetch_config"])

    # The per-scenario summary has keys like "bola", "bolae", etc.
    for key, value in data["results"].items():
        merged_key = f"{scenario}/{key}"
        all_results[merged_key] = value

# Build combined config referencing all 5 prefetch configs
first_summary_path = os.path.join(BASE_DIR, SCENARIOS[0], "comparison_summary.json")
with open(first_summary_path) as f:
    first_data = json.load(f)

combined = {
    "config": {
        "network": first_data["config"]["network"],
        "movie": first_data["config"]["movie"],
        "seek_configs": first_data["config"]["seek_configs"],
        "prefetch_configs": prefetch_configs,
        "network_multiplier": first_data["config"]["network_multiplier"],
    },
    "algorithms": algorithms,
    "scenarios": SCENARIOS,
    "results": all_results,
}

output_path = os.path.join(BASE_DIR, "comparison_summary.json")
with open(output_path, "w") as f:
    json.dump(combined, f, indent=2)

print(f"Wrote {output_path}")
print(f"  scenarios: {SCENARIOS}")
print(f"  result keys: {list(all_results.keys())[:6]} ...")
