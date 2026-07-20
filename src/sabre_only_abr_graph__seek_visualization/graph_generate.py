import pandas as pd
import matplotlib.pyplot as plt
import argparse
import os

def generate_graph(abrarray, input_dir):
    # Dictionary to store the DataFrame for each ABR algorithm
    dataframes = {}

    # List of colors
    colors = ['blue', 'orange', 'green', 'red', 'purple', 'brown', 'pink', 'gray', 'olive', 'cyan']
    marker = 'o'  # Use the same marker symbol

    # Resolve relative input dir against this script's location
    if not os.path.isabs(input_dir):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        input_dir = os.path.join(script_dir, input_dir)

    # Load the data from each CSV file and store it in the dictionary
    for abr in abrarray:
        csv_path = os.path.join(input_dir, f'{abr}.csv')
        dataframes[abr] = pd.read_csv(csv_path)

    # Plot network_bandwidth vs time for all ABR algorithms with logarithmic scale
    plt.figure(figsize=(10, 5))
    for i, abr in enumerate(abrarray):
        plt.plot(
            dataframes[abr]['time'], 
            dataframes[abr]['network_bandwidth'], 
            label=f'{abr} Network Bandwidth', 
            color=colors[i % len(colors)], 
            marker=marker,  # Use the same marker symbol
            alpha=0.8  # Set transparency
        )
    plt.xlabel('Time(ms)')
    plt.ylabel('Network Bandwidth(kbps)')
    # plt.yscale('log')  # Set y-axis to logarithmic scale
    plt.title("Network Bandwidth vs Time for All ABR Algorithms Seek")
    plt.legend()
    plt.grid(visible=True, which='both', linestyle='--', alpha=0.5)
    plt.show()

    # Plot bitrate vs time for all ABR algorithms with logarithmic scale
    plt.figure(figsize=(10, 5))
    for i, abr in enumerate(abrarray):
        plt.plot(
            dataframes[abr]['time'], 
            dataframes[abr]['bitrate'], 
            label=f'{abr} Bitrate', 
            color=colors[i % len(colors)], 
            marker=marker,  # Use the same marker symbol
            alpha=0.8  # Set transparency
        )
    plt.xlabel('Time(ms)')
    plt.ylabel('Bitrate(kbps)')
    # plt.yscale('log')  # Set y-axis to logarithmic scale
    plt.title("Bitrate vs Time for All ABR Algorithms Seek")
    plt.legend()
    plt.grid(visible=True, which='both', linestyle='--', alpha=0.5)
    plt.show()

    # Plot buffer_level vs time for all ABR algorithms with logarithmic scale
    plt.figure(figsize=(10, 5))
    for i, abr in enumerate(abrarray):
        plt.plot(
            dataframes[abr]['time'], 
            dataframes[abr]['buffer_level'], 
            label=f'{abr} Buffer Level', 
            color=colors[i % len(colors)], 
            marker=marker,  # Use the same marker symbol
            alpha=0.8  # Set transparency
        )
    plt.xlabel('Time(ms)')
    plt.ylabel('Buffer Level(ms)')
    # plt.yscale('log')  # Set y-axis to logarithmic scale
    plt.title("Buffer Level vs Time for All ABR Algorithms Seek")
    plt.legend()
    plt.grid(visible=True, which='both', linestyle='--', alpha=0.5)
    plt.show()

    # Plot rebuffer_time vs time for all ABR algorithms with logarithmic scale
    plt.figure(figsize=(10, 5))
    for i, abr in enumerate(abrarray):
        plt.plot(
            dataframes[abr]['time'], 
            dataframes[abr]['rebuffer_time'], 
            label=f'{abr} Rebuffer Time', 
            color=colors[i % len(colors)], 
            marker=marker,  # Use the same marker symbol
            alpha=0.8  # Set transparency
        )
    plt.xlabel('Time(ms)')
    plt.ylabel('Rebuffer Time(ms)')
    # plt.yscale('log')  # Set y-axis to logarithmic scale
    plt.title("Rebuffer Time vs Time for All ABR Algorithms Seek")
    plt.legend()
    plt.grid(visible=True, which='both', linestyle='--', alpha=0.5)
    plt.show()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Generate graphs for specified ABR algorithms')
    parser.add_argument('-a', '--abr', type=str, nargs='+', required=True, help='Array of ABR algorithms to use (space-separated)')
    parser.add_argument(
        '-i',
        '--input-dir',
        type=str,
        default='sabre_only_abr_graph__seek_visualization',
        help='Directory to read CSV inputs from'
    )
    args = parser.parse_args()

    # Pass the ABR algorithm array to the generate_graph function
    generate_graph(args.abr, args.input_dir)
