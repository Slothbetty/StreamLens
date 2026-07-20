import subprocess
import csv
import argparse
import os

# Function to run sabre.py with the `-g` argument and capture its output
def capture_print_output(abr):
    # Run sabre.py from the src directory so relative paths resolve.
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_src_dir = os.path.abspath(os.path.join(script_dir, '..'))
    sabre_path = os.path.join(repo_src_dir, 'sabre.py')
    seeks_path = os.path.join(repo_src_dir, 'seeks.json')
    result = subprocess.run(
        ['python', sabre_path, '-g', '-a', abr, '-sc', seeks_path],
        capture_output=True,
        text=True,
        cwd=repo_src_dir
    )
    # Split the output into lines
    return result.stdout.splitlines()

# Function to parse each line into a dictionary
def parse_line(line):
    fields = line.split()
    # Filter out invalid fields that don’t contain '='
    valid_fields = [field for field in fields if '=' in field]
    return {field.split('=')[0]: field.split('=')[1] for field in valid_fields}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Generate graph with specified ABR algorithm')
    parser.add_argument('-a', '--abr', type=str, required=True, help='ABR algorithm to use')
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parser.add_argument(
        '-o',
        '--output-dir',
        type=str,
        default=script_dir,
        help='Directory to write CSV output'
    )
    args = parser.parse_args()
    
    # Normalize relative output dir to this script's location
    if not os.path.isabs(args.output_dir):
        args.output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), args.output_dir)

    # Capture the printed data
    data = capture_print_output(args.abr)
    # Filter out any empty lines or lines that are not properly formatted
    parsed_data = [parse_line(line) for line in data if line.strip() and '=' in line]

    # Ensure there is data to write
    if parsed_data:
        # Get the header from the keys of the first dictionary
        header = parsed_data[0].keys()

        os.makedirs(args.output_dir, exist_ok=True)
        output_path = os.path.join(args.output_dir, f'{args.abr}.csv')
        # Write to a CSV file
        with open(output_path, 'w', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=header)
            writer.writeheader()
            writer.writerows(parsed_data)

        print(f"Data successfully written to {output_path}")
    else:
        print("No valid data found to write to CSV.")
    