import subprocess
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = SCRIPT_DIR

def run_scripts(abrArray):
    try:
        for abr in abrArray:
            # Run extract_data.py for each ABR algorithm
            subprocess.run(
                ['python', 'extract_data.py', '-a', abr, '-o', OUTPUT_DIR],
                check=True
            )

        # Run graph_generate.py with all ABR algorithms in the abrArray
        subprocess.run(
            ['python', 'graph_generate.py', '-a'] + abrArray + ['-i', OUTPUT_DIR],
            check=True
        )
        
        print("All scripts executed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"An error occurred while running scripts: {e}")

if __name__ == "__main__":
    abrArray = ['bola', 'bolae', 'dynamic', 'dynamicdash', 'throughput']
    
    run_scripts(abrArray)
