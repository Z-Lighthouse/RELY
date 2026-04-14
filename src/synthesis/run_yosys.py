import os
import subprocess
import re

# config paths
INPUT_DIR = ""
OUTPUT_NETLIST_DIR = ""

os.makedirs(OUTPUT_NETLIST_DIR, exist_ok=True)

def find_top_module(file_path):
    # extract first module name found in file
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            match = re.search(r'\bmodule\s+(\w+)', content)
            if match:
                return match.group(1)
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
    return None

def run_yosys(verilog_file):
    fname = os.path.basename(verilog_file)
    modname = os.path.splitext(fname)[0]
    out_netlist = os.path.join(OUTPUT_NETLIST_DIR, f"{modname}_synth.v")

    top_module = find_top_module(verilog_file)
    
    if top_module:
        print(f"Processing: {fname} (Top: {top_module})")
        hierarchy_cmd = f"hierarchy -check -top {top_module}"
    else:
        print(f"Warning: Top module not found for {fname}, using auto-detect")
        hierarchy_cmd = "hierarchy -check -auto-top"

    # build yosys script
    yosys_cmd = f"""
        read_verilog -sv {verilog_file}
        {hierarchy_cmd}
        proc; opt
        synth_xilinx -family xcup
        write_verilog {out_netlist}
    """

    try:
        subprocess.run(["yosys", "-p", yosys_cmd], check=True)
    except subprocess.CalledProcessError:
        print(f"Failed to synthesize {fname}")

def main():
    if not os.path.exists(INPUT_DIR):
        print(f"Input dir missing: {INPUT_DIR}")
        return

    v_files = [f for f in os.listdir(INPUT_DIR) if f.endswith(".v")]
    if not v_files:
        print("No .v files found.")
        return

    v_files.sort()

    for vf in v_files:
        run_yosys(os.path.join(INPUT_DIR, vf))

    print("\nBatch synthesis finished.")
    print(f"Output saved to: {OUTPUT_NETLIST_DIR}")

if __name__ == "__main__":
    main()