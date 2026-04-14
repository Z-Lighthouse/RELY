import os
import sys
import subprocess
import argparse
import re
import time
from pathlib import Path

# get first module name from verilog source
def extract_top_module_name(file_path):
    try:
        content = Path(file_path).read_text(encoding='utf-8', errors='ignore')
    except:
        return None

    # match module keyword followed by name
    pattern = re.compile(
        r"^\s*module\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*(\(|\s*#|\s*;)", 
        re.MULTILINE
    )
    
    match = pattern.search(content)
    if match:
        top_module = match.group(1).strip()
        if top_module:
            return top_module
            
    return None

# sequential vivado run for each netlist
def run_vivado_analysis(netlist_list, base_output_dir, fpga_part, tcl_template_path):
    failed_tasks = []
    if not netlist_list:
        return failed_tasks
        
    base_out_resolved = str(Path(base_output_dir).resolve())
    os.makedirs(base_out_resolved, exist_ok=True) 
    
    try:
        with open(tcl_template_path, 'r') as f:
            template_content = f.read()
    except FileNotFoundError:
        print(f"Error: TCL template missing at {tcl_template_path}")
        return [{"file": "All", "reason": "TCL Template Missing"}]
        
    total = len(netlist_list)
    print(f"Starting analysis for {total} files...")

    for idx, (fpath, topname) in enumerate(netlist_list, 1):
        file_stem = Path(fpath).stem
        out_subdir = Path(base_out_resolved) / file_stem
        os.makedirs(out_subdir, exist_ok=True)
        
        print(f"[{idx}/{total}] Processing: {file_stem}")

        # setup tcl for this file
        single_item = f'"{fpath},{topname},{out_subdir}"'
        netlist_list_tcl = f"set NETLIST_LIST_TCL {{ {single_item} }}"
        tcl_content = template_content.replace('{__FPGA_PART__}', fpga_part)
        tcl_content = tcl_content.replace('{__NETLIST_LIST_TCL__}', netlist_list_tcl)
        
        tcl_script = out_subdir / "run_this_analysis.tcl"
        with open(tcl_script, 'w') as f:
            f.write(tcl_content)

        # run batch
        cmd = f"vivado -mode batch -source {tcl_script}"
        log_path = out_subdir / 'vivado.log'
        time_txt = out_subdir / 'time.txt'
        t_start = time.time()
        
        try:
            with open(log_path, 'w') as log_file:
                process = subprocess.Popen(
                    cmd, shell=True, 
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                    text=True, encoding='utf-8', errors='replace'
                )
                for line in process.stdout:
                    log_file.write(line)
                process.wait()

            elapsed = time.time() - t_start
            with open(time_txt, 'w') as tf:
                tf.write(f"{elapsed:.4f}\n")

            if process.returncode == 0:
                print(f"OK: {file_stem} ({elapsed:.2f}s)")
            else:
                print(f"FAIL: {file_stem} - check {log_path}")
                failed_tasks.append({"file": file_stem, "reason": f"Exit code {process.returncode}"})

        except Exception as e:
            print(f"Error: Execution failed for {file_stem}: {e}")
            failed_tasks.append({"file": file_stem, "reason": str(e)})

    return failed_tasks

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("netlist_dir")
    parser.add_argument("out_dir")
    parser.add_argument("--fpga_part", default="xczu9eg-ffvb1156-2-e")
    parser.add_argument("--tcl_template", default="./get_level_and_area.tcl")
    
    args = parser.parse_args()
    netlist_dir = Path(args.netlist_dir).resolve()
    report_out_dir = Path(args.out_dir).resolve() 
    
    v_files = sorted([p.resolve() for p in Path(netlist_dir).glob("*.v")])
    
    tasks = [] 
    skipped = 0
    no_top_found = [] 
    
    print(f"Scanning {len(v_files)} files...")
    
    for fpath in v_files:
        stem = fpath.stem
        out_subdir = report_out_dir / stem
        
        # skip if already done (check for 3 valid output files)
        if out_subdir.exists() and out_subdir.is_dir():
            valid_files = [p for p in out_subdir.iterdir() if p.is_file() and p.stat().st_size > 0]
            if len(valid_files) >= 3:
                skipped += 1
                continue
        
        # get module name
        top = extract_top_module_name(fpath)
        if top:
            tasks.append((str(fpath), top))
        else:
            no_top_found.append(fpath.name)
            
    print(f"Found {len(tasks)} to process ({skipped} skipped, {len(no_top_found)} invalid).")

    # execute vivado runs
    errors = []
    if tasks:
        print("-" * 30)
        vivado_failures = run_vivado_analysis(
            tasks, str(report_out_dir), args.fpga_part, args.tcl_template
        )
        errors.extend(vivado_failures)
    
    # log missing modules
    for m in no_top_found:
        errors.append({"file": m, "reason": "No top module found"})

    # final log
    print("\n" + "="*30)
    print("Execution Summary")
    print("-" * 30)
    print(f"Total scanned: {len(v_files)}")
    print(f"Completed:     {skipped}")
    print(f"Errors:        {len(errors)}")
    
    if errors:
        print("\nDetail Errors:")
        for item in errors:
            print(f"{item['file']}: {item['reason']}")
    else:
        print("\nAll tasks finished successfully.")

if __name__ == '__main__':
    main()