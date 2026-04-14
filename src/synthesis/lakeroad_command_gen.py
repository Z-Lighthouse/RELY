import os
import re

# paths and general config
input_dir = "/home/user/database/zlh/lakeroad/lstm_test_regression/my_dataset/five_dsp_extr/model_ex"
output_dir = "/home/user/database/zlh/lakeroad/lstm_test_regression/my_dataset/five_dsp_extr/lakeroad"

architecture = "xilinx-ultrascale-plus"
clock_name = "clk"
extra_cycles = 3
default_timeout = 1200
outdir_base = "/home/user/database/zlh/lakeroad/lstm_test_regression/my_dataset/five_dsp_extr/lakeroad_output"

# utils
def extract_module_name(file_path):
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(r"\s*module\s+(\w+)", line)
                if m: return m.group(1)
    except Exception: pass
    return None

def extract_output_signal(file_path):
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                # regex to handle formats like [34:0]out_u0
                m = re.match(r"\s*output\s+(?:signed\s+)?(?:\[(\d+):(\d+)\])?\s*(\w+)", line)
                if m:
                    msb = int(m.group(1)) if m.group(1) else 0
                    lsb = int(m.group(2)) if m.group(2) else 0
                    width = msb - lsb + 1 if msb >= lsb else 1
                    name = m.group(3)
                    return f"{name}:{width}", width
    except Exception: pass
    return None, None

def extract_pipeline_depth(file_path):
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f: content = f.read()
        if "always" not in content: return 0
        
        always_blocks = re.finditer(r"always\s*@\s*\([^)]+\)", content)
        total = 0
        for match in always_blocks:
            start = match.end()
            if re.search(r"\bbegin\b", content[start:]):
                block = content[start : start + 500] 
                total += len(re.findall(r"<=", block))
            else:
                end_match = re.search(r";", content[start:])
                if end_match: total += len(re.findall(r"<=", content[start:start+end_match.start()]))
        return total if total > 0 else 1
    except Exception: return 1

# logic for signal generation and pattern matching
def generate_input_signals(file_path):
    port_widths = {}
    content = ""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f: content = f.read()
    except Exception: return [], [], None

    port_pattern = re.compile(r"input\s+(?:signed\s+)?(?:\[(\d+):(\d+)\])?\s*(\w+)")
    for line in content.splitlines():
        m = port_pattern.search(line)
        if m:
            msb = int(m.group(1)) if m.group(1) else 0
            lsb = int(m.group(2)) if m.group(2) else 0
            width = msb - lsb + 1 if msb >= lsb else 1
            port_widths[m.group(3)] = width
    
    if not port_widths: return [], [], None

    # look for core expression in always or assign block
    core_expr_match = re.search(r"always.*?<=\s*(.*?);", content, re.DOTALL)
    if not core_expr_match: core_expr_match = re.search(r"assign\s+\w+\s*=\s*(.*?);", content, re.DOTALL)
    if not core_expr_match: return [], [], None
    
    expression = re.sub(r'\s+', ' ', core_expr_match.group(1).strip())
    OP_ID = r"\w+"
    def cap(r): return rf"\(?\s*(?P<{r}>{OP_ID})\s*\)?"
    
    PART_A_ADD_D = rf"{cap('a')}\s*\+\s*{cap('d')}" 
    PART_A_SUB_D = rf"{cap('a')}\s*\-\s*{cap('d')}" 
    
    patterns = {
        "pure_adder": re.compile(rf"^\(?(?:{cap('a')})\s*\+\s*{cap('b')}\)?$", re.DOTALL),
        "special_submuland_sub": re.compile(rf"^\(?(?:{PART_A_SUB_D})\)?\s*\*\s*{cap('b')}\s*&\s*{cap('c')}$", re.DOTALL),
        "special_submuland_add": re.compile(rf"^\(?(?:{PART_A_ADD_D})\)?\s*\*\s*{cap('b')}\s*&\s*{cap('c')}$", re.DOTALL),
        "special_cvc5_mac": re.compile(rf"^\(?(?:{cap('a')}\s*\*\s*{cap('b')})\)?\s*[\+\-]\s*{cap('c')}$", re.DOTALL),
        "general_full_dsp": re.compile(rf"^\(?(?:{cap('a')}\s*[\+\-]\s*{cap('d')})\)?\s*\*\s*{cap('b')}\s*[\+\-]\s*{cap('c')}$", re.DOTALL),
        "general_preadd_mul": re.compile(rf"^\(?(?:{cap('a')}\s*[\+\-]\s*{cap('d')})\)?\s*\*\s*{cap('b')}$", re.DOTALL),
        "general_mul": re.compile(rf"^\(?(?:{cap('a')}\s*\*\s*{cap('b')})\)?$", re.DOTALL),
        "general_comm_mac": re.compile(rf"^{cap('c')}\s*\+\s*\(?(?:{cap('a')}\s*\*\s*{cap('b')})\)?$", re.DOTALL),
    }

    role_map = {}
    pattern_name = None
    for name, pat in patterns.items():
        m = pat.match(expression)
        if m:
            role_map = {k:v for k,v in m.groupdict().items() if v}
            pattern_name = name
            break
    
    if not role_map: return [], [], None
        
    input_signals = []
    used_fixed = []
    for role in ['a', 'b', 'c', 'd']:
        if role in role_map:
            name = role_map[role]
            if name in port_widths:
                w = port_widths[name]
                input_signals.append(f"{role}:(port {name} {w}):{w}")
                used_fixed.append(role)
            
    return input_signals, used_fixed, pattern_name

def generate_pure_adder_signals(input_signals, output_width):
    port_map = {}
    for entry in input_signals:
        role = entry.split(':')[0] 
        m = re.search(r"\(port\s+(\w+)\s+\d+\)", entry)
        if m:
            port_map[role] = m.group(1)
    
    if 'a' not in port_map or 'b' not in port_map:
        return input_signals 
    
    verilog_port_a = port_map['a'] 
    verilog_port_b = port_map['b'] 
    w = output_width
    
    # splitter logic for pure adders
    new_signals = []
    new_signals.append(f"a:(extract 17 0 (port {verilog_port_a} {w})):18")
    new_signals.append(f"b:(extract {w-1} 18 (port {verilog_port_a} {w})):{w-18}")
    new_signals.append(f"c:(port {verilog_port_b} {w}):{w}")
    
    return new_signals

# template generation
def generate_pure_adder_run_comments(file_path, module_name, out_signal_str, input_signals, current_solver, custom_timeout=None):
    final_timeout = custom_timeout if custom_timeout else default_timeout
    lines = [
        f'// RUN: outdir_base="{outdir_base}"',
        f'// RUN: outfile="${{outdir_base}}/$(basename %s)"',
        f'// RUN: mkdir -p "${{outdir_base}}"',
        f'// RUN: racket $LAKEROAD_DIR/bin/main.rkt \\',
        f'// RUN:   --solver {current_solver} \\',
        f'// RUN:   --verilog-module-filepath %s \\',
        f'// RUN:   --architecture {architecture} \\',
        f'// RUN:   --template dsp \\',
        f'// RUN:   --out-format verilog \\',
        f'// RUN:   --top-module-name {module_name} \\',
        f'// RUN:   --verilog-module-out-signal {out_signal_str} \\',
        f'// RUN:   --pipeline-depth 0 \\',
        f'// RUN:   --module-name {module_name} \\'
    ]
    for sig in input_signals: lines.append(f"// RUN:   --input-signal '{sig}' \\")
    lines.extend([
        f'// RUN:   --timeout {final_timeout} \\',
        f'// RUN:   --out-filepath "${{outfile}}" ',
        f'// RUN: FileCheck %s < "${{outfile}}"'
    ])
    return "\n".join(lines)

def generate_normal_run_comments(file_path, module_name, out_signal_str, pipeline_depth, input_signals, current_solver, custom_timeout=None):
    final_timeout = custom_timeout if custom_timeout else default_timeout
    lines = [
        f'// RUN: outdir_base="{outdir_base}"',
        f'// RUN: outfile="${{outdir_base}}/$(basename %s)"',
        f'// RUN: mkdir -p "${{outdir_base}}"',
        f'// RUN: racket $LAKEROAD_DIR/bin/main.rkt \\',
        f'// RUN:   --solver {current_solver} \\',
        f'// RUN:   --verilog-module-filepath %s \\',
        f'// RUN:   --architecture {architecture} \\',
        f'// RUN:   --template dsp \\',
        f'// RUN:   --out-format verilog \\',
        f'// RUN:   --top-module-name {module_name} \\',
        f'// RUN:   --verilog-module-out-signal {out_signal_str} \\',
        f'// RUN:   --pipeline-depth {pipeline_depth} \\'
    ]
    if pipeline_depth > 0:
        lines.append(f'// RUN:   --clock-name {clock_name} \\')
    lines.append(f'// RUN:   --module-name {module_name} \\')
    for sig in input_signals: lines.append(f"// RUN:   --input-signal '{sig}' \\")
    if pipeline_depth > 0:
        lines.append(f'// RUN:   --extra-cycles {extra_cycles} \\')
    lines.extend([
        f'// RUN:   --timeout {final_timeout} \\',
        f'// RUN:   --out-filepath "${{outfile}}" ',
        f'// RUN: FileCheck %s < "${{outfile}}"'
    ])
    return "\n".join(lines)

def generate_xilinx_submuland_run_comments(file_path, module_name, out_signal_str, input_signals, pipeline_depth):
    lines = [
        '// RUN: outdir_base="lakeroad_output"',
        '// RUN: outfile="${outdir_base}/$(basename %s)"',
        '// RUN: mkdir -p "${outdir_base}"',
        '// RUN: ($LAKEROAD_DIR/bin/lakeroad-portfolio.py \\',
        '// RUN:  --bitwuzla \\',
        '// RUN:  --cvc5 \\',
        '// RUN:  --verilog-module-filepath %s \\',
        '// RUN:  --architecture xilinx-ultrascale-plus \\',
        '// RUN:  --template dsp \\',
        '// RUN:  --out-format verilog \\',
        f'// RUN:  --top-module-name {module_name} \\',
        f'// RUN:  --verilog-module-out-signal {out_signal_str} \\',
        f'// RUN:  --pipeline-depth {pipeline_depth} \\'
    ]
    if pipeline_depth > 0: lines.append(f'// RUN:  --clock-name {clock_name} \\')
    lines.append(f'// RUN:  --module-name {module_name} \\')
    for sig in input_signals: lines.append(f"// RUN:  --input-signal '{sig}' \\")
    if pipeline_depth > 0: lines.append(f'// RUN:  --extra-cycles {extra_cycles} \\')
    lines.extend([
        '// RUN:  --timeout 120 \\',
        '// RUN:  --out-filepath "${outfile}" \\',
        '// RUN:  || true ) \\',
        '// RUN:  2>&1 \\',
        '// RUN:  | FileCheck %s --input-file="${outfile}"'
    ])
    return "\n".join(lines)

def generate_check_comments(module_name, used_fixed, output_port):
    return "// CHECK: module"

# main execution loop
os.makedirs(output_dir, exist_ok=True)
module_file_pattern = re.compile(r".*module\d+\.v$")
success_count = 0
failed_count = 0

for root, dirs, files in os.walk(input_dir):
    for file in files:
        if module_file_pattern.search(file):
            file_path = os.path.join(root, file)
            rel_dir = os.path.relpath(root, input_dir)
            file_prefix = "" if rel_dir == "." else rel_dir.replace(os.sep, "_") + "_"
            
            print(f"File: {file_path}")
            
            module_name = extract_module_name(file_path)
            out_signal_str, out_width = extract_output_signal(file_path)
            input_signals, used_fixed, pattern_name = generate_input_signals(file_path)
            
            is_valid = all([module_name, out_signal_str, input_signals])

            if is_valid:
                try:
                    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                        orig_content = f.read().strip()
                except: orig_content = ""
                
                if not orig_content:
                    failed_count += 1
                    continue

                pipeline_depth = extract_pipeline_depth(file_path)
                
                if pattern_name == "pure_adder":
                    special_signals = generate_pure_adder_signals(input_signals, out_width)
                    run_comments = generate_pure_adder_run_comments(
                        file_path, module_name, out_signal_str, special_signals, "bitwuzla"
                    )
                elif pattern_name == "special_submuland_sub":
                    run_comments = generate_xilinx_submuland_run_comments(
                        file_path, module_name, out_signal_str, input_signals, pipeline_depth
                    )
                elif pattern_name == "special_submuland_add":
                    run_comments = generate_normal_run_comments(
                        file_path, module_name, out_signal_str, pipeline_depth, input_signals, "bitwuzla", 300
                    )
                elif pattern_name == "special_cvc5_mac":
                    run_comments = generate_normal_run_comments(
                        file_path, module_name, out_signal_str, pipeline_depth, input_signals, "cvc5", 600
                    )
                else:
                    run_comments = generate_normal_run_comments(
                        file_path, module_name, out_signal_str, pipeline_depth, input_signals, "bitwuzla"
                    )
                
                final_output = f"{run_comments}\n\n{orig_content}\n\n{generate_check_comments(module_name, used_fixed, None)}\n"
                out_path = os.path.join(output_dir, f"{file_prefix}{file}")
                
                try:
                    with open(out_path, "w", encoding="utf-8") as f: f.write(final_output)
                    success_count += 1
                except: failed_count += 1
            else:
                failed_count += 1

print("-" * 30)
print(f"Done. Success: {success_count} | Failed: {failed_count}")