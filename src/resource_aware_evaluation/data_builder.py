import os
import json
import glob
import re
import sys

# 0. Import AST parsing tools
try:
    from signal_utils import extract_all_verilog_signals
except ImportError:
    print("error")
    sys.exit(1)

# 1. Constants and configuration
# Map Verilog types to integer IDs
TYPE_MAP = {
    "Wire": 0, "WIRE": 0, "wire": 0,
    "Reg": 1,  "REG": 1, "reg": 1, "Integer": 1, "integer": 1,
    "Input": 3, "input": 3, "Output": 3, "output": 3, "Inout": 3, "inout": 3,
    "Ioport": 3, 
    "Parameter": 4, "parameter": 4, "localparam": 4, "Localparam": 4,
    "OP": 2,      # Operators
    "OTHER": 5    # Other/Unknown
}

# Common Verilog operators and keywords
OPERATORS = set([
    '+', '-', '*', '/', '%', 
    '<<', '>>', '>>>', '<<<', 
    '&', '|', '^', '~', '!', 
    '==', '!=', '<=', '>=', '<', '>', 
    '&&', '||', 
    '?', ':', '=', '<=', 'assign', 'always', 'begin', 'end', 
    'module', 'endmodule', 'if', 'else', 'case', 'endcase', 'posedge', 'negedge'
])

# 2. Basic utility functions

def tokenize_verilog_code(code_line):
    """
    Tokenizer: keeps identifiers, numbers, operators, and punctuation
    """
    if not code_line: return []
    # Regex matching: comments | identifiers | numbers (including hex) | compound operators | single-character symbols
    token_pattern = r"(\/\/.*)|(\/\*.*?\*\/)|([a-zA-Z_][a-zA-Z0-9_]*)|(\d+\'?[hbdo]?[0-9a-fA-F_xzXZ]+|\d+)|(<=|==|!=|>=|<=|&&|\|\||>>|<<|>>>|<<<)|([\[\]\(\)\{\}\:\;\,\=\+\-\*\/\%\&\|\^\~\!\?\.@])"
    
    tokens = []
    code_line = code_line.strip()
    for match in re.finditer(token_pattern, code_line):
        if match.group(1) or match.group(2): continue # Skip comments
        token = match.group(0)
        if token.strip(): 
            tokens.append(token)
    return tokens

def convert_to_unified_symbol_table(signal_dict, param_dict):
    """
    Convert AST parsing results into a unified symbol table format
    """
    symbol_table = {}
    
    # Signals
    for name, info in signal_dict.items():
        type_str = info.get('type', 'Wire')
        type_id = TYPE_MAP.get(type_str, 0)
        width = info.get('width', 1)
        if width is None: width = 1
        is_signed = 1 if info.get('signed', False) else 0
        symbol_table[name] = {"type": type_id, "width": int(width), "signed": is_signed}
        
    # Parameters
    for name, info in param_dict.items():
        type_str = info.get('type', 'Parameter')
        type_id = TYPE_MAP.get(type_str, 4)
        width = info.get('width', 32)
        if width is None: width = 32
        is_signed = 1 if info.get('signed', False) else 0
        symbol_table[name] = {"type": type_id, "width": int(width), "signed": is_signed}
        
    return symbol_table

def get_token_features(token, symbol_table):
    """Get bitwidth, phy_type, and signed_flag based on the Token"""
    if token in symbol_table:
        info = symbol_table[token]
        return info['width'], info['type'], info['signed']
    
    # Handle numeric literals
    if re.match(r"^\d", token):
        if "'" in token:
            try: return int(token.split("'")[0]), 5, 0 
            except: pass
        return 32, 5, 0
    
    # Operators
    if token in OPERATORS: return 0, 2, 0 
    
    # Others
    return 0, 5, 0

# 3. Dependency and fanout tracking logic
def extract_variables_from_tokens(tokens, symbol_table):
    """Extract variable names belonging to Wire/Reg/Port from the token list"""
    vars_found = set()
    for t in tokens:
        if t in symbol_table:
            # Exclude Parameter (4), only care about logic signals (0, 1, 3)
            if symbol_table[t]['type'] in [0, 1, 3]: 
                vars_found.add(t)
    return vars_found

def extract_LHS_variables(line, symbol_table):
    """
    Extract variables specifically on the left-hand side of assignments (result variables)
    Supports: assign a = ...;  always @... a <= ...;
    """
    line = re.sub(r"//.*", "", line).strip()
    vars_found = set()
    
    assign_op = None
    if "<=" in line: assign_op = "<="
    elif "=" in line: assign_op = "="
    
    if assign_op:
        lhs_part = line.split(assign_op)[0] # Extract the left-hand side part
        tokens = tokenize_verilog_code(lhs_part)
        vars_found = extract_variables_from_tokens(tokens, symbol_table)
    
    return vars_found

def is_assignment_to_vars(line, target_vars):
    line = re.sub(r"//.*", "", line).strip()
    if not line: return False
    
    for var in target_vars:
        pattern = re.compile(rf"(^|[\s]){re.escape(var)}(\s*\[.*?\])?\s*(<=|=)")
        if pattern.search(line): return True
    return False

def is_declaration_of_vars(line, target_vars):
    line = re.sub(r"//.*", "", line).strip()
    if not line: return False
    # Quick filter: must contain declaration keywords
    if not any(k in line for k in ['input', 'output', 'inout', 'wire', 'reg', 'integer']):
        return False

    for var in target_vars:
        pattern = re.compile(rf"\b{re.escape(var)}\b\s*[,;\[]") 
        pattern_end = re.compile(rf"\b{re.escape(var)}\b\s*$")
        
        if pattern.search(line) or pattern_end.search(line):
            return True
    return False

def is_usage_of_vars(line, target_vars):
    line = re.sub(r"//.*", "", line).strip()
    if not line: return False
    
    # 1. Check if the variable exists
    found_vars = []
    for var in target_vars:
        if re.search(rf"\b{re.escape(var)}\b", line):
            found_vars.append(var)
    if not found_vars: return False
    
    # 2. If it's an Output declaration, count it as Fanout
    if 'output' in line:
        return True
        
    # 3. Exclude other declaration lines
    if any(k in line for k in ['input', 'inout', 'wire', 'reg', 'integer', 'parameter']):
        return False
        
    # 4. Check if it appears on the LHS of an assignment
    assign_op = None
    if "<=" in line: assign_op = "<="
    elif "=" in line: assign_op = "="
    
    if assign_op:
        lhs, rhs = line.split(assign_op, 1)
        # If it appears on the RHS, it's a Usage
        for var in found_vars:
            if re.search(rf"\b{re.escape(var)}\b", rhs):
                return True
        # If it only appears on the LHS, it's not considered Usage (it's a reassignment)
        return False
    
    # 5. Other cases (if, case, instantiation params) -> counts as Usage if it appears
    return True


# 4. Core processing logic (Process Verilog File)
def process_verilog_file(file_path, target_line_num):
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
            lines = content.splitlines()
    except: return None

    try:
        raw_signal_dict, raw_param_dict = extract_all_verilog_signals(file_path)
    except Exception: return None
    symbol_table = convert_to_unified_symbol_table(raw_signal_dict, raw_param_dict)
    
    full_tokens = []
    full_bitwidths = []
    full_phy_types = []
    full_signed_flags = []
    
    # Three types of masks
    full_target_mask = []      # 1.0 / 0.0
    full_dependency_mask = []  # 0.5 / 0.0
    full_fanout_mask = []      # 0.5 / 0.0
    
    target_indices = []
    target_line_tokens = []
    token_line_map = [] 
    
    current_token_idx = 0
    
    for line_idx, line in enumerate(lines):
        current_line_num = line_idx + 1
        tokens = tokenize_verilog_code(line)
        if not tokens: continue
        
        is_target_line = (current_line_num == target_line_num)
        
        for token in tokens:
            bw, ptype, sflag = get_token_features(token, symbol_table)
            
            full_tokens.append(token)
            full_bitwidths.append(bw)
            full_phy_types.append(ptype)
            full_signed_flags.append(sflag)
            token_line_map.append(current_line_num)
            
            full_dependency_mask.append(0.0)
            full_fanout_mask.append(0.0)
            
            if is_target_line:
                full_target_mask.append(1.0) # Target = 1.0
                target_indices.append(current_token_idx)
                target_line_tokens.append(token)
            else:
                full_target_mask.append(0.0)
            
            current_token_idx += 1
            
    if 1.0 not in full_target_mask: return None

    # Calculate explicit features
    operand_bw_product = 0.0
    if target_indices:
        start, end = target_indices[0], target_indices[-1]
        tgt_bws = full_bitwidths[start:end+1]
        tgt_toks = full_tokens[start:end+1]
        if '*' in tgt_toks:
            op_idx = tgt_toks.index('*')
            left_w = 1; right_w = 1
            for i in range(op_idx-1, -1, -1):
                if tgt_bws[i] > 0: left_w = tgt_bws[i]; break
            for i in range(op_idx+1, len(tgt_toks)):
                if tgt_bws[i] > 0: right_w = tgt_bws[i]; break
            operand_bw_product = float(left_w * right_w)

    # 1. All variables in the target line
    all_vars_in_target = extract_variables_from_tokens(target_line_tokens, symbol_table)
    
    # 2. LHS variables
    target_line_str = lines[target_line_num-1]
    lhs_vars = extract_LHS_variables(target_line_str, symbol_table)
    
    # 3. RHS variables (source operands) = all - LHS
    rhs_vars = all_vars_in_target - lhs_vars
    
    # === Pass 2: Dependency Mask (0.5) ===
    if rhs_vars:
        dep_line_nums = set()
        for line_idx, line in enumerate(lines):
            line_num = line_idx + 1
            if line_num == target_line_num: continue 
            
            if is_declaration_of_vars(line, rhs_vars) or is_assignment_to_vars(line, rhs_vars):
                dep_line_nums.add(line_num)
        
        for i, line_num in enumerate(token_line_map):
            if line_num in dep_line_nums:
                full_dependency_mask[i] = 0.5 # Set to 0.5

    # === Pass 3: Fanout Mask (0.5) ===
    if lhs_vars:
        fanout_line_nums = set()
        for line_idx, line in enumerate(lines):
            line_num = line_idx + 1
            if line_num == target_line_num: continue
            
            # As long as it's used, set to 0.5
            if is_usage_of_vars(line, lhs_vars):
                fanout_line_nums.add(line_num)
        
        # Populate the mask
        for i, line_num in enumerate(token_line_map):
            if line_num in fanout_line_nums:
                full_fanout_mask[i] = 0.5 # Set to 0.5

    return {
        "tokens": full_tokens,
        "bitwidths": full_bitwidths,
        "phy_types": full_phy_types,
        "signed_flags": full_signed_flags,
        "target_mask": full_target_mask,       # [0, 0, ..., 1, 1, ..., 0]
        "dependency_mask": full_dependency_mask, # [0.5, ..., 0, ..., 0.5]
        "fanout_mask": full_fanout_mask,         # [0, ..., 0.5, ..., 0.5]
        "explicit_features": {"operand_bw_product": operand_bw_product}
    }

# 5. Data loading and report parsing
def load_markdown_data(file_path, value_column_name):
    data_map = {}
    if not os.path.exists(file_path): return data_map
    try:
        with open(file_path, 'r', encoding='utf-8') as f: lines = f.readlines()
        header_map = {}; header_found = False
        for line in lines:
            line = line.strip()
            if not line.startswith("|"): continue
            cells = [c.strip() for c in line.strip('|').split('|')]
            if "Subdirectory" in cells and not header_found:
                for idx, col_name in enumerate(cells): header_map[col_name] = idx
                if value_column_name in header_map: header_found = True
                continue
            if header_found and "---" not in line and len(cells) == len(header_map):
                sub_name = cells[header_map["Subdirectory"]]
                try: data_map[sub_name] = float(cells[header_map[value_column_name]])
                except: continue
    except: pass
    return data_map

def parse_extraction_report(report_path):
    extracted_data = []
    try:
        with open(report_path, 'r', encoding='utf-8', errors='replace') as f: lines = f.readlines()
        is_data_section = False
        for line in lines:
            line = line.strip()
            if not line: continue
            if line.startswith("----"): is_data_section = True; continue
            if "CANDIDATE_LINE_NUM" in line: continue
            if is_data_section:
                parts = [p.strip() for p in line.split('|')]
                if len(parts) >= 5:
                    try: extracted_data.append({"line_num": int(parts[0]), "extracted_module_name": parts[4], "status": parts[1]})
                    except: continue
    except: pass
    return extracted_data

# 6. Main program entry 
def build_dataset_for_config(config_name, root_dir, report_base_dir, output_json_path, filenames_dict, match_mode):
    dataset = []
    
    path_dash_util  = os.path.join(report_base_dir, filenames_dict['dash_util'])
    path_dash_delay = os.path.join(report_base_dir, filenames_dict['dash_delay'])
    path_vivado_util  = os.path.join(report_base_dir, filenames_dict['vivado_util'])
    path_vivado_delay = os.path.join(report_base_dir, filenames_dict['vivado_delay'])
    
    print(f"\n>>> [{config_name}] Loading Reports (Mode: {match_mode})...")
    map_dash_area   = load_markdown_data(path_dash_util, "Total")
    map_dash_level  = load_markdown_data(path_dash_delay, "Max_Level")
    map_vivado_area  = load_markdown_data(path_vivado_util, "Total")
    map_vivado_level = load_markdown_data(path_vivado_delay, "Max_Level")
    
    print(f"    Scanning: {root_dir}")
    processed_count = 0
    
    for dirpath, dirnames, filenames in os.walk(root_dir):
        if "extraction_report.txt" in filenames:
            report_path = os.path.join(dirpath, "extraction_report.txt")
            original_v_files = glob.glob(os.path.join(dirpath, "*original.v"))
            if not original_v_files: continue
            verilog_file_path = original_v_files[0]
            subdir_name = os.path.basename(dirpath)
            
            vivado_key = subdir_name
            if vivado_key not in map_vivado_area or vivado_key not in map_vivado_level: 
                continue
            base_area = map_vivado_area[vivado_key]
            base_level = map_vivado_level[vivado_key]
            
            report_entries = parse_extraction_report(report_path)
            file_name_stem = os.path.splitext(os.path.basename(verilog_file_path))[0]
            
            for entry in report_entries:
                line_num = entry['line_num']
                extracted_name = entry['extracted_module_name']
                dash_key = None

                if match_mode == 'one_dsp_style':
                    if subdir_name in map_dash_area and subdir_name in map_dash_level:
                        dash_key = subdir_name

                elif match_mode == 'five_dsp_style':
                    suffix_match = re.search(r'(_module\d+)$', extracted_name)
                    suffix = suffix_match.group(1) if suffix_match else ""

                    key_option_a = subdir_name + suffix
                    
                    key_option_b = extracted_name

                    if key_option_a in map_dash_area and key_option_a in map_dash_level:
                        dash_key = key_option_a
                    elif key_option_b in map_dash_area and key_option_b in map_dash_level:
                        dash_key = key_option_b

                if not dash_key: 
                    continue
                
                opt_area = map_dash_area[dash_key]
                opt_level = map_dash_level[dash_key]
                
                seq_data = process_verilog_file(verilog_file_path, line_num)
                if seq_data is None: continue

                new_meta_id = f"{subdir_name}_{file_name_stem}_{dash_key}"
                labels = {
                    "area_gain": base_area - opt_area, 
                    "delay_gain": base_level - opt_level, 
                    "raw_area_dash": opt_area, 
                    "raw_area_vivado": base_area
                }

                data_item = {
                    "dataset_source": config_name,
                    "meta_id": new_meta_id,
                    "raw_text": {"target_line_number": line_num, "file_path": verilog_file_path},
                    "input_sequence": seq_data,
                    "labels": labels
                }
                dataset.append(data_item)
                processed_count += 1
                if processed_count % 50 == 0: print(f"    Processed {processed_count}...", end='\r')

    print(f"\n    [{config_name}] Done. Total: {processed_count}")
    try:
        output_dir = os.path.dirname(output_json_path)
        if output_dir: os.makedirs(output_dir, exist_ok=True)
        with open(output_json_path, 'w', encoding='utf-8') as f_out:
            for item in dataset: f_out.write(json.dumps(item, ensure_ascii=False) + '\n')
    except Exception as e: print(f"    Write Error: {e}")

def build_all_datasets():
    # One DSP
    config_one = {
        "config_name": "One_DSP", "match_mode": "one_dsp_style",
        "root_dir": r"../../result/one_dsp_logic_isolation_output",
        "report_base_dir": r"../../result/synthesis_results",
        "output_json_path": "./jsonl_files/one_dsp_whole.jsonl",
        "filenames_dict": {
            "dash_util": "dash_utilization.md",
            "dash_delay": "dash_logic_level.md",
            "vivado_util": "vivado_without_dsp_utilization.md",
            "vivado_delay": "vivado_without_dsp_logic_level.md"
        }
    }
    
    # Five DSP
    config_five = {
        "config_name": "Five_DSP", "match_mode": "five_dsp_style",
        "root_dir": r"../../result/five_dsp_logic_isolation_output",
        "report_base_dir": r"../../result/synthsesis_report",
        "output_json_path": "./jsonl_files/five_dsp_whole_v3.jsonl",
        "filenames_dict": {
            "dash_util": "dash_every_dsp_utilization.md",
            "dash_delay": "dash_every_dsp_logic_level.md",
            "vivado_util": "vivado_withoutdsp_utilization.md",
            "vivado_delay": "vivado_withoutdsp_logic_level.md"
        }
    }
    if os.path.exists(config_one["root_dir"]):
        build_dataset_for_config(**config_one) 
    else:
        print(f"Skipping One_DSP ")
        
    if os.path.exists(config_five["root_dir"]):
        build_dataset_for_config(**config_five) 
    else:
        print(f"Skipping Five_DSP")
        
    print("Done.")

if __name__ == "__main__":
    build_all_datasets()