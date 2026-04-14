import os
import re
import sys
import subprocess
import argparse
import time

# insert use_dsp="no" attribute before module declarations
def add_dsp_attribute_to_content(verilog_content):
    lines = verilog_content.splitlines(True)
    new_lines = []
    
    # regex for module start
    module_pattern = re.compile(r"^\s*\bmodule\b\s+\w+")
    attribute_str = '(* use_dsp = "no" *)'
    
    for i, line in enumerate(lines):
        if module_pattern.search(line):
            # avoid double insertion
            already_exists = False
            if i > 0:
                if lines[i-1].strip() == attribute_str:
                    already_exists = True
            
            if not already_exists:
                new_lines.append(f"{attribute_str}\n")
        
        new_lines.append(line)
    return "".join(new_lines)

# convert seconds to readable format
def format_duration(seconds):
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{int(h)}h {int(m)}m {s:.2f}s"
    elif m > 0:
        return f"{int(m)}m {s:.2f}s"
    else:
        return f"{s:.2f}s"

# wrapper to run vivado synthesis
def run_vivado_synthesis(source_file, output_dir, fpga_part, tcl_template_path):
    if not os.path.exists(tcl_template_path):
        print(f"[ERROR] Tcl template missing: {tcl_template_path}")
        return False

    with open(tcl_template_path, 'r') as f:
        template_content = f.read()

    # fill template
    tcl_content = template_content.replace('{__RTL_FILE__}', source_file)
    tcl_content = tcl_content.replace('{__FPGA_PART__}', fpga_part)
    tcl_content = tcl_content.replace('{__OUTPUT_DIR__}', output_dir)

    run_tcl = os.path.join(output_dir, "run_synthesis.tcl")
    with open(run_tcl, 'w') as f:
        f.write(tcl_content)
        
    cmd = f"vivado -mode batch -source {run_tcl}"
    print(f"\n[INFO] Running Vivado for {os.path.basename(source_file)}...")
    
    try:
        log_path = os.path.join(output_dir, 'vivado.log')
        with open(log_path, 'w') as log_file:
            process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            # stream output to console and log file
            for line in process.stdout:
                sys.stdout.write(line)
                log_file.write(line)
            process.wait()

        return process.returncode == 0
    except Exception as e:
        print(f"[FATAL] Vivado execution failed: {e}")
        return False

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source_directory")
    parser.add_argument("base_output_directory")
    
    args = parser.parse_args()
    source_dir = args.source_directory
    base_out_dir = args.base_output_directory
    
    # settings
    FPGA_PART = "xczu9eg-ffvb1156-2-e" 
    TCL_TEMPLATE_PATH = "./synthesis_template_without_dsp.tcl"
    
    if not os.path.exists(TCL_TEMPLATE_PATH):
        print(f"Tcl template not found at: {TCL_TEMPLATE_PATH}")
        sys.exit(1)

    if not os.path.exists(source_dir):
         print(f"Source dir error: {source_dir}")
         sys.exit(1)

    # find all verilog files
    all_files = []
    for f_name in os.listdir(source_dir):
        f_path = os.path.join(source_dir, f_name)
        if os.path.isfile(f_path) and (f_name.endswith('.v') or f_name.endswith('.sv')):
            all_files.append((f_name, f_path))
    
    total = len(all_files)
    if not all_files:
        print(f"No files found in {source_dir}")
        return

    print(f"Total files to process: {total}")
    failed_cases = []

    for idx, (f_name, fpath) in enumerate(all_files, 1):
        f_base = os.path.splitext(f_name)[0]
        f_out_dir = os.path.join(base_out_dir, f_base)
        
        # skip logic: check if directory has 6 non-empty files already
        should_skip = False
        if os.path.exists(f_out_dir) and os.path.isdir(f_out_dir):
            items = [os.path.join(f_out_dir, f) for f in os.listdir(f_out_dir)]
            files_only = [f for f in items if os.path.isfile(f)]
            
            if len(files_only) == 6:
                if all(os.path.getsize(f) > 0 for f in files_only):
                    should_skip = True
        
        if should_skip:
            print(f"[{idx}/{total}] [SKIP] {f_name} (already finished)")
            continue

        os.makedirs(f_out_dir, exist_ok=True)
        t_start = time.time()
        
        print("\n" + "-"*40)
        print(f"[{idx}/{total}] Processing: {f_name}")
        print("-"*40)
        
        ok = False
        err_msg = ""

        try:
            # Prepare files: read -> modify -> save temp
            temp_v = os.path.join(f_out_dir, f"{f_base}_processed_for_synth.v")
            try:
                with open(fpath, 'r', encoding='utf-8') as fin:
                    raw_content = fin.read()
            except UnicodeDecodeError:
                with open(fpath, 'r', encoding='latin-1') as fin:
                    raw_content = fin.read()

            processed_content = add_dsp_attribute_to_content(raw_content)

            with open(temp_v, 'w', encoding='utf-8') as fout:
                fout.write('`include "koios_no_hb.vh"\n\n')
                fout.write(processed_content)

            # run synth
            if run_vivado_synthesis(os.path.abspath(temp_v), os.path.abspath(f_out_dir), FPGA_PART, TCL_TEMPLATE_PATH):
                ok = True
            else:
                err_msg = "Vivado failure"

        except Exception as e:
            print(f"Processing error for {f_name}: {e}")
            err_msg = str(e)
            ok = False

        t_end = time.time()
        diff_sec = t_end - t_start
        diff_str = format_duration(diff_sec)

        # log timing and status
        time_log = os.path.join(f_out_dir, "time.txt")
        status = "SUCCESS" if ok else "FAILURE"
        
        try:
            with open(time_log, 'w', encoding='utf-8') as tf:
                tf.write(f"File: {f_name}\n")
                tf.write(f"Result: {status}\n")
                tf.write(f"Time (s): {diff_sec:.4f}\n")
                tf.write(f"Time (f): {diff_str}\n")
                if not ok:
                    tf.write(f"Reason: {err_msg}\n")
        except Exception as e:
            print(f"Warning: could not write time.txt: {e}")

        if not ok:
            failed_cases.append(f"{f_name} - {err_msg}")

    print("\n" + "="*40)
    print("Batch finished.")
    
    if failed_cases:
        log_err = os.path.join(base_out_dir, "failed_summary.txt")
        with open(log_err, 'w', encoding='utf-8') as f:
            for c in failed_cases:
                f.write(f"{c}\n")
        print(f"Check {log_err} for failure details.")
    else:
        print("Success: all files processed.")

if __name__ == '__main__':
    main()