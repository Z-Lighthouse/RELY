import os
import re
import sys
import subprocess
import argparse
import time

# regex to find module definition and insert use_dsp attribute
def add_dsp_attribute_to_content(verilog_content):
    lines = verilog_content.splitlines(True)
    new_lines = []
    module_pattern = re.compile(r"^\s*\bmodule\b\s+\w+")
    attribute_str = '(* use_dsp = "yes" *)'
    
    for i, line in enumerate(lines):
        if module_pattern.search(line):
            already_exists = False
            if i > 0 and lines[i - 1].strip() == attribute_str:
                already_exists = True
            if not already_exists:
                new_lines.append(f"{attribute_str}\n")
        new_lines.append(line)
    return "".join(new_lines)

# generate tcl and run vivado in batch mode
def run_vivado_synthesis(source_file, output_dir, fpga_part, tcl_template_path):
    os.makedirs(output_dir, exist_ok=True)
    
    try:
        with open(tcl_template_path, 'r') as f:
            template_content = f.read()
    except FileNotFoundError:
        print(f"Error: TCL template not found: {tcl_template_path}")
        return False

    # replace placeholders in tcl template
    tcl_content = template_content.replace('{__RTL_FILE__}', source_file)
    tcl_content = tcl_content.replace('{__FPGA_PART__}', fpga_part)
    tcl_content = tcl_content.replace('{__OUTPUT_DIR__}', output_dir)

    run_script = os.path.join(output_dir, "run_synthesis.tcl")
    with open(run_script, 'w') as f:
        f.write(tcl_content)
        
    cmd = f"vivado -mode batch -source {run_script}"
    
    try:
        log_path = os.path.join(output_dir, 'vivado.log')
        with open(log_path, 'w') as log_file:
            process = subprocess.Popen(
                cmd, 
                shell=True, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True, 
                encoding='utf-8', 
                errors='replace'
            )
            for line in process.stdout:
                log_file.write(line)
            process.wait()

        return process.returncode == 0
    except Exception as e:
        print(f"Vivado execution failed: {e}")
        return False

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source_dir", help="directory containing .v files")
    parser.add_argument("out_dir", help="synthesis output root")
    
    args = parser.parse_args()
    source_dir = os.path.abspath(args.source_dir)
    base_out_dir = os.path.abspath(args.out_dir)
    
    # config
    FPGA_PART = "xczu9eg-ffvb1156-2-e"
    TCL_TEMPLATE = "./synthesis_template_with_dsp.tcl"
    
    if not os.path.isdir(source_dir):
        print(f"Source dir does not exist: {source_dir}")
        sys.exit(1)

    # find all verilog files
    v_files = []
    for root, _, files in os.walk(source_dir):
        for f in files:
            if f.endswith('.v'):
                v_files.append(os.path.join(root, f))
    
    total = len(v_files)
    if total == 0:
        print("No .v files found.")
        return

    print(f"Processing {total} files...")
    print("-" * 40)

    failed = []
    start_time = time.time()

    for i, fpath in enumerate(v_files, 1):
        fname = os.path.basename(fpath)
        print(f"[{i}/{total}] {fname}", end=" ", flush=True)

        # map source tree to output directory
        rel_path = os.path.relpath(os.path.dirname(fpath), source_dir)
        work_dir = os.path.join(base_out_dir, rel_path, os.path.splitext(fname)[0])
        os.makedirs(work_dir, exist_ok=True)
        
        synth_v = os.path.join(work_dir, f"{os.path.splitext(fname)[0]}_synth.v")

        try:
            with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # toggle dsp attribute injection here if needed:
            # content = add_dsp_attribute_to_content(content)

            with open(synth_v, 'w', encoding='utf-8') as f:
                f.write(content)

            ok = run_vivado_synthesis(
                source_file=os.path.abspath(synth_v),
                output_dir=os.path.abspath(work_dir),
                fpga_part=FPGA_PART,
                tcl_template_path=TCL_TEMPLATE
            )

            if ok:
                print("-> OK")
            else:
                print("-> FAIL")
                failed.append(fpath)

        except Exception as e:
            print(f"-> ERR: {e}")
            failed.append(fpath)

    # summary
    end_time = time.time()
    elapsed = end_time - start_time
    
    print("-" * 40)
    print(f"Batch finished in {elapsed/60:.2f} min")
    print(f"Success: {total - len(failed)} / {total}")
    
    if failed:
        log_path = os.path.join(base_out_dir, "failed_cases.txt")
        with open(log_path, 'w', encoding='utf-8') as f:
            for case in failed:
                f.write(f"{case}\n")
        print(f"Failed cases logged to {log_path}")
    else:
        print("All files processed successfully.")

if __name__ == '__main__':
    main()