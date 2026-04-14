import os
import sys
import subprocess
import argparse
import time
import shutil

# wrapper to run vivado synthesis with tcl patch
def run_vivado_synthesis(source_file, output_dir, fpga_part, tcl_template_path, vivado_path="vivado"):
    os.makedirs(output_dir, exist_ok=True)
    
    try:
        with open(tcl_template_path, 'r') as f:
            template_content = f.read()
    except FileNotFoundError:
        print(f"Error: tcl template missing at {tcl_template_path}")
        return False

    # replace placeholders in tcl script
    tcl_content = template_content.replace('{__RTL_FILE__}', source_file)
    tcl_content = tcl_content.replace('{__FPGA_PART__}', fpga_part)
    tcl_content = tcl_content.replace('{__OUTPUT_DIR__}', output_dir)

    run_tcl = os.path.join(output_dir, "run_synthesis.tcl")
    with open(run_tcl, 'w') as f:
        f.write(tcl_content)
        
    cmd = f"{vivado_path} -mode batch -source {run_tcl}"
    
    try:
        log_path = os.path.join(output_dir, 'vivado.log')
        with open(log_path, 'w') as log_file:
            # hide output to keep console clean, pipe to log file instead
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
    parser.add_argument("source_dir")
    parser.add_argument("out_dir")
    
    args = parser.parse_args()
    src_root = os.path.abspath(args.source_dir)
    out_root = os.path.abspath(args.out_dir)
    
    # synthesis config
    FPGA_PART = "xczu9eg-ffvb1156-2-e"
    TCL_TEMPLATE = "./synthesis_template_with_dsp.tcl"
    VIVADO_BIN = "/home/user/database/vivado_2023/Vivado/2023.2/bin/vivado"
    
    if not os.path.isdir(src_root):
        print(f"Source path invalid: {src_root}")
        sys.exit(1)

    # find all .v files first
    v_list = []
    for root, _, files in os.walk(src_root):
        for f in files:
            if f.endswith('.v'):
                v_list.append(os.path.join(root, f))
    
    total = len(v_list)
    if total == 0:
        print("No verilog files found.")
        return

    print(f"Found {total} files. Starting batch run...")
    print("-" * 40)

    failed = []
    skipped = 0
    start_all = time.time()

    for i, fpath in enumerate(v_list, 1):
        fname = os.path.basename(fpath)
        base_name = os.path.splitext(fname)[0]
        
        # map output dir to source structure
        rel_dir = os.path.relpath(os.path.dirname(fpath), src_root)
        work_dir = os.path.join(out_root, rel_dir, base_name)
        
        time_file = os.path.join(work_dir, "time.txt")

        # skip check: dont rerun if already finished
        if os.path.exists(work_dir) and os.path.exists(time_file):
            print(f"[{i}/{total}] Skip: {fname}")
            skipped += 1
            continue

        print(f"[{i}/{total}] Running: {fname}", end=" ", flush=True)
        os.makedirs(work_dir, exist_ok=True)
        
        # staging file
        synth_v = os.path.join(work_dir, f"{base_name}_synth.v")

        try:
            shutil.copy2(fpath, synth_v)
            t_start = time.time()

            # call synthesis using specified vivado version
            ok = run_vivado_synthesis(
                source_file=os.path.abspath(synth_v),
                output_dir=os.path.abspath(work_dir),
                fpga_part=FPGA_PART,
                tcl_template_path=TCL_TEMPLATE,
                vivado_path=VIVADO_BIN
            )

            t_end = time.time()
            diff = t_end - t_start

            if ok:
                print(f"-> OK ({diff:.1f}s)")
                with open(time_file, 'w') as tf:
                    tf.write(f"{diff:.4f}\n")
            else:
                print("-> FAIL")
                failed.append(fpath)

        except Exception as e:
            print(f"-> ERR: {e}")
            failed.append(fpath)

    # final summary
    end_all = time.time()
    total_time = end_all - start_all
    
    print("\n" + "="*40)
    print(f"Done. Time: {total_time/60:.2f} min")
    print(f"Total: {total} | Skipped: {skipped} | Failed: {len(failed)}")
    
    if failed:
        log_err = os.path.join(out_root, "failed_cases.txt")
        with open(log_err, 'w') as f:
            for c in failed:
                f.write(f"{c}\n")
        print(f"Check {log_err} for errors.")

if __name__ == '__main__':
    main()