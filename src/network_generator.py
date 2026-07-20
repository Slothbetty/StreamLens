import numpy as np
import json
import argparse


def generate_network_conditions(num_entries, duration, bandwidth_mean, bandwidth_std, latency_mean, latency_std):
    network_conditions = []
    for _ in range(num_entries):
        bandwidth = int(np.random.normal(bandwidth_mean, bandwidth_std))
        latency = int(np.random.normal(latency_mean, latency_std))
        network_conditions.append({
            "duration_ms": int(duration),
            "bandwidth_kbps": bandwidth,
            "latency_ms": latency
        })
    return network_conditions


def main():
    parser = argparse.ArgumentParser(description='Generate network conditions and save to a JSON file')
    parser.add_argument('-ne', '--num_entries', type=int, required=True, help='Number of entries to generate')
    parser.add_argument('-d', '--duration', type=float, required=True, help='Duration per entry in ms')
    parser.add_argument('-bm', '--bandwidth_mean', type=float, required=True, help='Mean bandwidth in kbps')
    parser.add_argument('-bs', '--bandwidth_std', type=float, required=True, help='Standard deviation of bandwidth in kbps')
    parser.add_argument('-lm', '--latency_mean', type=float, required=True, help='Mean latency in ms')
    parser.add_argument('-ls', '--latency_std', type=float, required=True, help='Standard deviation of latency in ms')
    parser.add_argument('-o', '--output', default='network.json', help='Output file path (default: network.json)')

    args = parser.parse_args()

    network_conditions = generate_network_conditions(
        args.num_entries,
        args.duration,
        args.bandwidth_mean,
        args.bandwidth_std,
        args.latency_mean,
        args.latency_std
    )

    with open(args.output, 'w') as f:
        json.dump(network_conditions, f, indent=4)

    print(f"Wrote {args.output} ({args.num_entries} entries).")


if __name__ == '__main__':
    main()
