import os
import re
import gc
import shutil
import copy
from pyverilog.vparser.parser import parse
from pyverilog.vparser.ast import *
from pyverilog.ast_code_generator.codegen import ASTCodeGenerator
from collections import defaultdict, deque
from signal_utils import eval_expr


def attach_parent(node, parent=None):
    if isinstance(node, Node):
        node.parent = parent
        for c in node.children():
            attach_parent(c, node)


def contains_conditional_logic(ast_node):
    """
    Recursively checks if an AST node or any of its children contain conditional
    statements like 'if' or 'case'.
    """
    if isinstance(ast_node, (IfStatement, CaseStatement, ForStatement)):
        return True
    if hasattr(ast_node, 'children'):
        for child in ast_node.children():
            if contains_conditional_logic(child):
                return True
    return False

def safe_parse(filepath):
    """Safe file parsing to avoid file descriptor leaks."""
    try:
        ast, _ = parse([filepath])
        return ast
    except Exception as e:
        print(f"Error parsing file {filepath}: {e}")
        return None
    finally:
        gc.collect()
        
def find_times_nodes(node):
    times_nodes = []
    if isinstance(node, Times):
        times_nodes.append(node)
    for c in node.children():
        times_nodes.extend(find_times_nodes(c))
    return times_nodes

def get_names_from_node(node):
    names = set()
    if isinstance(node, Identifier):
        names.add(node.name)

    if hasattr(node, 'children'):
        for child_node in node.children():
            names.update(get_names_from_node(child_node))

    return names


def is_pure_combinational_module(module, always_node, core_op_node):
    """
    Determine if a module is "pure", containing only one target combinational logic calculation.
    
    A pure module should have only one always @(*) block at the top level 
    (along with optional simple assigns and Decls). 
    Inside this always block, there must be only one assignment, 
    and its RHS must be our core computation node.
    """
    # 1. check if the module's top-level structure is pure
    always_count = 0
    ALLOWED_TOP_LEVEL_TYPES = (Always, Assign, Decl)
    for item in module.items:
        if not isinstance(item, ALLOWED_TOP_LEVEL_TYPES):
            return False
        if isinstance(item, Always):
            always_count += 1
    
    # a. module must have exactly one always block
    if always_count != 1: 
        return False
        
    # b. ensure we are checking the unique always block
    the_only_always_node = [item for item in module.items if isinstance(item, Always)][0]
    if the_only_always_node is not always_node: 
        return False

    # c. any assign statements must be simple wire connections
    all_assign_stmts = [item for item in module.items if isinstance(item, Assign)]
    for assign_stmt in all_assign_stmts:
        rhs_node = getattr(assign_stmt.right, 'var', assign_stmt.right)
        if not isinstance(rhs_node, (Identifier, Pointer)):
            return False

    # 2. check if the inside of the always block is pure
    
    # a. check if the always block is combinational
    is_combinational = False
    if hasattr(always_node, 'sens_list') and hasattr(always_node.sens_list, 'list'):
        sens_list = always_node.sens_list.list
        if (len(sens_list) == 1 and isinstance(sens_list[0], Sens) and sens_list[0].type == 'star') or not sens_list:
            is_combinational = True
             
    if not is_combinational:
        return False
        
    # b. ensure there are statements inside the always block
    if not hasattr(always_node, 'statement') or not hasattr(always_node.statement, 'statements'):
        return False
    statements = always_node.statement.statements
    
    # c. pure always block must contain only one statement
    if len(statements) != 1:
        return False
    the_only_stmt = statements[0]
    
    # d. the statement must be a valid assignment
    if not isinstance(the_only_stmt, (BlockingSubstitution, NonblockingSubstitution)):
        return False
        
    # e. the RHS of the statement must be our core operation node
    rhs_node = getattr(the_only_stmt.right, 'var', the_only_stmt.right)
    if rhs_node is not core_op_node:
        return False
        
    return True

def is_always_sequential(always_node):
    """Helper to determine if an always block is sequential."""
    if hasattr(always_node, 'sens_list') and hasattr(always_node.sens_list, 'list'):
        for sens in always_node.sens_list.list:
            if sens.type in ('posedge', 'negedge'):
                return True
    return False

def is_node_in_tree(target_node, tree_root_node):
    """
    A recursive helper function to check if target_node is a descendant of 
    tree_root_node (or is the node itself).
    """
    if tree_root_node is target_node:
        return True
    
    if hasattr(tree_root_node, 'children'):
        for child in tree_root_node.children():
            if is_node_in_tree(target_node, child):
                return True
                
    return False


def process_function_multiplications(module, verilog_path, description):
    """
    Process multiplications within functions.
    Extracts the multiplication and finds function call sites.
    """
    from pyverilog.vparser.ast import Input  

    with open(verilog_path, 'r') as f:
        file_lines = f.readlines()

    mul_items_Func = []   

    # Step 1: extract multiplications from functions
    for item in module.items:
        if isinstance(item, Function):
            times_nodes = find_times_nodes(item)
            if times_nodes:
                print(f"Found multiplication in Function '{item.name}'")
                mul_items_Func.append((item, times_nodes))
            else:
                print("no mult")

    # Step 2: find function calls to prepare for replacement
    if mul_items_Func:
        for item, times_nodes in mul_items_Func:
            func_name = item.name
            func_inputs = [child.name for child in item.children() if isinstance(child, Input)]
            func_body = item.children()[1]  

            print("[INFO] Function body:")
            print(func_body)

            for stmt in module.items:
                if isinstance(stmt, Decl):
                    continue  

                if hasattr(stmt, 'children'):
                    for node in stmt.children():
                        call = find_function_call_in_rvalue(node, func_name)
                        if call:
                            print("========= Found FunctionCall =========")
                            print("Function call found in statement:", func_name)
                            print("AST node type:", type(stmt).__name__)
                            print("Call node:", call)
                            print("Original statement:", stmt)
                            print("======================================")

def find_function_call_in_rvalue(node, func_name):
    return None

def find_task_call_in_node(node, task_name):
    return None
 
def process_task_multiplications(module, verilog_path, description):
    """
    Process multiplications within tasks.
    Extracts the multiplication and finds task call sites.
    """
    with open(verilog_path, 'r') as f:
        file_lines = f.readlines()

    mul_items_Task = []   

    # Step 1: extract tasks with multiplications
    for item in module.items:
        if isinstance(item, Task):
            times_nodes = find_times_nodes(item)
            if times_nodes:
                print(f"Found multiplication in Task '{item.name}'")
                mul_items_Task.append((item, times_nodes))
            else:
                print(f"No multiplication in Task '{item.name}'")

    # Step 2: find task calls
    if mul_items_Task:
        for task_item, times_nodes in mul_items_Task:
            task_name = task_item.name
            print("[INFO] Task Body:")
            for stmt in task_item.statement.statements:
                print("   ", stmt)

            for stmt in module.items:
                if isinstance(stmt, Decl):
                    continue  

                if hasattr(stmt, 'children'):
                    for child in stmt.children():
                        task_call = find_task_call_in_node(child, task_name)
                        if task_call:
                            print("========= Found Task Call =========")
                            print("Task call found in statement:", task_name)
                            print("AST node type:", type(stmt).__name__)
                            print("Call node:", task_call)
                            print("Original statement:", stmt)
                            print("===================================")



def extract_identifier_names(node):
    names = set()
    if isinstance(node, Identifier):
        names.add(node.name)
    for c in node.children():
        names |= extract_identifier_names(c)
    return names


def extract_procedural_assigns(statement):
    """
    Recursively extracts all procedural assignment statements from any block.
    (BlockingSubstitution and NonblockingSubstitution)
    """
    assigns = []

    if statement is None:
        return assigns

    # a. current node is the target
    if isinstance(statement, (BlockingSubstitution, NonblockingSubstitution)):
        assigns.append(statement)

    # b. current node is a Block
    elif isinstance(statement, Block):
        if statement.statements:
            for s in statement.statements:
                assigns.extend(extract_procedural_assigns(s))

    # c. current node is an IfStatement
    elif isinstance(statement, IfStatement):
        assigns.extend(extract_procedural_assigns(statement.true_statement))
        if statement.false_statement:
            assigns.extend(extract_procedural_assigns(statement.false_statement))

    # d. current node is a CaseStatement
    elif isinstance(statement, CaseStatement):
        if statement.caselist:
            for case_item in statement.caselist:
                if isinstance(case_item.statement, Block):
                    if case_item.statement.statements:
                        for s in case_item.statement.statements:
                            assigns.extend(extract_procedural_assigns(s))
                elif case_item.statement is not None:
                    assigns.extend(extract_procedural_assigns(case_item.statement))
                    
    # e. current node is a ForStatement
    elif isinstance(statement, ForStatement):
        assigns.extend(extract_procedural_assigns(statement.statement))

        
    return assigns

def get_expr_width(expr, signal_dict, param_dict=None):
    """
    Find the bit width of an expression in signal_dict or param_dict.
    Returns the integer bit width, or None if unknown.
    """

    # Case 1: Simple Identifier, e.g., 'a'
    if isinstance(expr, Identifier):
        name = expr.name
        if name in signal_dict:
            return signal_dict[name].get('width', None)
        elif param_dict and name in param_dict:
            return param_dict[name].get('width', None)
        else:
            return None  

    # Case 2: Array type, e.g., a[i]
    elif isinstance(expr, Pointer):
        if isinstance(expr.var, Identifier):
            name = expr.var.name
            if name in signal_dict:
                return signal_dict[name].get('width', None)
            elif param_dict and name in param_dict:
                return param_dict[name].get('width', None)
            else:
                return None

    # Case 3: Integer constant
    elif isinstance(expr, IntConst):
        val_str = expr.value.strip().lower()

        if "'" in val_str:
            parts = val_str.split("'")
            if parts[0].isdigit():
                return int(parts[0]) 
        else:
            return 32  # default to 32 bits if unspecified

    return None  

def find_nodes_in_generate(start_node):
    """
    Recursively search and return all nested Assign and Always nodes under a given AST node.
    Handles Block, If, Case, For, and Generate containers.
    """
    found_nodes = []
    if start_node is None:
        return found_nodes

    if isinstance(start_node, (Assign, Always)):
        found_nodes.append(start_node)
        return found_nodes
        
    children_to_visit = []
    
    if isinstance(start_node, (ModuleDef, GenerateStatement)):
        if hasattr(start_node, 'items') and start_node.items:
            children_to_visit = start_node.items
            
    elif isinstance(start_node, Block):
        if hasattr(start_node, 'statements') and start_node.statements:
            children_to_visit = start_node.statements
            
    elif isinstance(start_node, ForStatement):
        children_to_visit = [start_node.statement]
            
    elif isinstance(start_node, IfStatement):
        children_to_visit = [start_node.true_statement, start_node.false_statement]
                
    elif isinstance(start_node, CaseStatement):
        if hasattr(start_node, 'caselist'):
            children_to_visit = [case.statement for case in start_node.caselist]

    for child in children_to_visit:
        if child is not None:
            found_nodes.extend(find_nodes_in_generate(child))
         
    return found_nodes

def find_end_line(file_lines, start_line):
    """
    Find the line number of the matching 'endmodule' for a module starting at start_line.
    """
    for i in range(start_line, len(file_lines)):
        line = file_lines[i].strip()
        if line.startswith('endmodule'):
            return i
    return len(file_lines) - 1 

 
def find_end_of_block_lineno(start_node, file_lines):
    """
    Find the line number of the matching end keyword (e.g., end, endgenerate) 
    for an AST node.
    """
    start_line = start_node.lineno
    start_index = start_line - 1

    # 1. Handle single-line statements without begin...end
    statement = getattr(start_node, 'statement', None)
    if statement and not isinstance(statement, Block):
        # check if it has an else branch on the next line
        if isinstance(start_node, IfStatement) and start_node.false_statement:
             if start_node.false_statement.lineno == start_line + 1:
                 return start_line + 1

        return start_line

    # 2. Handle blocks with begin...end
    begin_keywords = re.compile(r'\b(begin|generate|module|task|function|fork)\b')
    end_keywords = re.compile(r'\b(end|endgenerate|endmodule|endtask|endfunction|join)\b')
    
    depth = 0
    first_begin_found = False
    
    for i in range(start_index, len(file_lines)):
        line = file_lines[i]
        
        line_no_comments = line.split('//')[0]
        
        if begin_keywords.search(line_no_comments):
            if i >= start_index:
                depth += 1
                first_begin_found = True

        if end_keywords.search(line_no_comments):
            if first_begin_found: 
                depth -= 1
            
        if first_begin_found and depth == 0:
            return i + 1 
            
    print(f"Warning: Could not find matching 'end' for block starting at line {start_line}. Defaulting to start line.")
    return start_line 


def remove_module_from_lines(file_lines, module_name):
    result = []
    inside_target_module = False

    for line in file_lines:
        if f"module {module_name}" in line:
            inside_target_module = True
            continue
        if inside_target_module and "endmodule" in line:
            inside_target_module = False
            continue
        if not inside_target_module:
            result.append(line)
    return result

def get_for_loop_count(for_node, param_dict):
    """
    Attempt to evaluate the exact loop count from a ForStatement AST node.
    """
    try:
        # a. Parse initial value
        start_val = 0 
        if hasattr(for_node, 'pre') and for_node.pre:
            try:
                init_assign = for_node.pre
                start_val_node = init_assign.right.var if hasattr(init_assign.right, 'var') else init_assign.right
                eval_start = eval_expr(start_val_node, param_dict)
                if eval_start is not None:
                    start_val = eval_start
            except Exception:
                pass

        # b. Parse end condition
        cond_node = for_node.cond
        end_val = eval_expr(cond_node.right, param_dict)
        if end_val is None:
            print(f"DEBUG: Loop count failed at line {for_node.lineno} - Could not evaluate end value from AST node '{cond_node.right.__class__.__name__}'.")
            return 0 

        # c. Parse step size
        step = 1 
        post_assign = for_node.post
        if hasattr(post_assign, 'right') and isinstance(post_assign.right, Plus):
            step_node = post_assign.right.right
            step_val = eval_expr(step_node, param_dict)
            if step_val is not None:
                step = step_val

        # d. Calculate total count based on comparison operator
        count = 0
        if isinstance(cond_node, LessThan): 
            if end_val > start_val:
                count = (end_val - start_val + step - 1) // step
        elif isinstance(cond_node, LessEq): 
            if end_val >= start_val:
                count = (end_val - start_val) // step + 1
        else:
            print(f"DEBUG: Loop count failed at line {for_node.lineno} - Unsupported condition operator: {type(cond_node)}")
            return 0
        
        print(f"DEBUG: Successfully evaluated loop at line {for_node.lineno}: start={start_val}, end={end_val}, step={step}, count={count}")
        return count
        
    except Exception as e:
        print(f"DEBUG: Failed to evaluate for-loop range at line {for_node.lineno} due to an exception: {e}")
        return 0
    


def get_assign_count(assign_node, param_dict):
    
    def find_enclosing_for(node):
        path = []
        current = getattr(node, 'parent', None)
        while current is not None:
            if isinstance(current, ForStatement):
                path.append(current)
            current = getattr(current, 'parent', None)
        return path 

    enclosing_fors = find_enclosing_for(assign_node)
    
    if not enclosing_fors:
        return False, 1  

    total_loop_count = 1
    for f_node in enclosing_fors:
        count = get_for_loop_count(f_node, param_dict)
        if count <= 0:
            print(f"Warning: Failed to parse loop count for for-loop at line {f_node.lineno}. Assuming count of 1.")
            count = 1
        
        total_loop_count *= count
        
    return True, total_loop_count


def find_innermost_for_node(node):
    """
    Search upwards and return the innermost ForStatement node.
    """
    current = getattr(node, 'parent', None)
    while current is not None:
        if isinstance(current, ForStatement):
            return current
        current = getattr(current, 'parent', None)
    return None

def extract_leaf_nodes(node):
    """Recursively extract all leaf nodes (Identifier, Pointer, IntConst, etc.) from an AST node."""
    leaf_nodes = []
    
    if isinstance(node, (Identifier, Pointer, IntConst, FloatConst)):
        leaf_nodes.append(node)
        return leaf_nodes

    if hasattr(node, 'children'):
        for child in node.children():
            leaf_nodes.extend(extract_leaf_nodes(child))
    return leaf_nodes

def extract_loop_logic(original_code_str, for_loop_node, assign_node, signal_dict, param_dict, codegen):
    """
    Extract logic from an assign statement inside a for-loop.
    Automatically detects arrays and scalars, generating correct ports and instantiation connections.
    """
    # 1. Get loop variable
    try:
        loop_var = for_loop_node.pre.left.var.name
    except AttributeError:
        print("Fatal error: Could not extract loop variable.")
        raise

    # 2. Extract all signals
    all_signals_in_stmt = [s for s in extract_identifier_names(assign_node) if s != loop_var]
    
    all_leaf_nodes = extract_leaf_nodes(assign_node)

    signal_nodes = []
    referenced_params = set()

    for node in all_leaf_nodes:
        if isinstance(node, (Identifier, Pointer)):
            base_name = get_base_name(node)
            
            if base_name == loop_var:
                continue
            
            if base_name in param_dict:
                referenced_params.add(base_name)
            else:
                signal_nodes.append(node)
        
    # 3. Identify array signals
    indexed_signal_pattern = re.compile(r'\b(\w+)\s*\[\s*' + re.escape(loop_var) + r'\s*\]')
    indexed_signals = set(indexed_signal_pattern.findall(original_code_str))

    # 4. Transform code body
    transformed_body = re.sub(r'\[\s*' + re.escape(loop_var) + r'\s*\]', '', original_code_str)

    # 5. Build port_info
    port_info = {}
    
    all_signal_names = sorted(list(set(get_base_name(n) for n in signal_nodes)))
    
    for signal_name in all_signal_names:
        is_output = signal_name in (get_base_name(n) for n in extract_leaf_nodes(assign_node.left))
        direction = 'output' if is_output else 'input'
        is_array = signal_name in indexed_signals
        
        info = signal_dict.get(signal_name, {})
        width_val = info.get('width')
        width_str = f"[{width_val - 1}:0]" if isinstance(width_val, int) and width_val > 1 else ""
        is_signed = info.get('signed', False)
        
        connect_to_str = f"{signal_name}[{loop_var}]" if is_array else signal_name

        port_info[signal_name] = {
            'connect_to': connect_to_str,
            'direction': direction, 
            'width': width_str,
            'is_array': is_array, 
            'signed': is_signed,
            'type': 'wire'
        }
            
    # 6. Return all extracted information
    return {
        "transformed_body": transformed_body,
        "port_info": port_info,
        "loop_var": loop_var,
        "referenced_params": list(referenced_params)
    }



def create_instance_code(module_name, instance_name, port_info, loop_var=None):
    """
    Handles simple connections, for-loop indexing, and mixed array/scalar scenarios.
    """
    connections = []
    
    for port_name in sorted(port_info.keys()):
        info = port_info[port_name]
        
        signal_to_connect = info.get('connect_to', port_name)
        
        if loop_var and info.get('is_array', False):
            signal_to_connect = f"{signal_to_connect}[{loop_var}]"
            
        connections.append(f".{port_name}({signal_to_connect})")
    
    connections_str = ", ".join(connections)
    return f"{module_name} {instance_name} ({connections_str});"

def get_base_name(node):
    """
    Recursively extract the base variable name from an AST node.
    """
    if isinstance(node, Identifier):
        return node.name
    
    if isinstance(node, Pointer):
        return get_base_name(node.var)
    
    return None
def parse_verilog_int(verilog_string):
    """
    Robustly convert Verilog formatted number strings to Python integers.
    """
    if verilog_string is None:
        return None
    
    verilog_string = verilog_string.strip()
    
    if verilog_string.isdigit() or (verilog_string.startswith('-') and verilog_string[1:].isdigit()):
        try:
            return int(verilog_string)
        except (ValueError, TypeError):
            return None

    match = re.search(r"'([bhdoxBHDXO])([0-9a-fA-F_]+)", verilog_string)
    if match:
        base_char = match.group(1).lower()
        value_str = match.group(2).replace('_', '') 

        base = 10
        if base_char == 'h':
            base = 16
        elif base_char == 'b':
            base = 2
        elif base_char == 'd':
            base = 10
        elif base_char == 'o':
            base = 8
        
        try:
            return int(value_str, base)
        except (ValueError, TypeError):
            return None 

    return None

def safe_file_copy(src, dst):
    """
    Safely copy a file, handling potential 'Too many open files' errors.
    """
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        
        with open(src, 'rb') as source_file:
            with open(dst, 'wb') as target_file:
                target_file.write(source_file.read())
        
        print(f"Successfully copied: {src} -> {dst}")
        return True
        
    except OSError as e:
        if e.errno == 24:  
            print(f"Too many open files, attempting garbage collection...")
            gc.collect()
            
            try:
                with open(src, 'rb') as source_file:
                    with open(dst, 'wb') as target_file:
                        target_file.write(source_file.read())
                print(f"Retry successful for copy: {src} -> {dst}")
                return True
            except OSError as retry_error:
                print(f"Retry failed for copy: {retry_error}")
                return False
        else:
            print(f"Failed to copy file {src} -> {dst}: {e}")
            return False
    except Exception as e:
        print(f"Unknown error occurred while copying file: {e}")
        return False

def get_operand_width(node, signal_dict, param_dict):
    """
    Get the bitwidth of an operand node.
    Handles sized/based number literals and retrieves widths robustly.
    """
    # 1. Handle Identifier or Pointer
    if isinstance(node, (Identifier, Pointer)):
        base_name = get_base_name(node)
        if base_name: 
            # Priority: signal_dict
            if base_name in signal_dict:
                width_info = signal_dict[base_name]
                if isinstance(width_info, dict) and 'width' in width_info:
                    print(f"DEBUG_GW_RET: 1a - Identifier/signal_dict (dict-width): {width_info['width']}")
                    return width_info['width']
                elif isinstance(width_info, int):
                    print(f"DEBUG_GW_RET: 1b - Identifier/signal_dict (int): {width_info}")
                    return width_info
                elif isinstance(width_info, tuple) and len(width_info) == 2:
                    print(f"DEBUG_GW_RET: 1c - Identifier/signal_dict (tuple-calc): ")
                    return width_info[0] - width_info[1] + 1

            # Secondary: param_dict
            if base_name in param_dict:
                param_entry = param_dict.get(base_name)

                if isinstance(param_entry, dict) and 'width' in param_entry:
                    return param_entry['width']
                
                if isinstance(param_entry, dict) and 'value' in param_entry:
                    print(f"DEBUG_GW_RET: 1d - Identifier/param_dict (dict-width): {param_entry['width']}")
                    param_val = param_entry['value']
                    
                    val_as_int = None
                    if isinstance(param_val, int):
                        val_as_int = param_val
                    elif isinstance(param_val, str):
                        val_as_int = parse_verilog_int(param_val)
                    
                    if val_as_int is not None:
                        if val_as_int == 0: 
                            print(f"DEBUG_GW_RET: 1e - Identifier/param_dict (value=0): 1")
                            return 1
                        if val_as_int < 0:
                            print(f"DEBUG_GW_RET: 1f - Identifier/param_dict (value<0):")
                            return abs(val_as_int).bit_length() + 1
                        return val_as_int.bit_length()
                
                elif isinstance(param_entry, int):
                    print(f"DEBUG_GW_RET: 1h - Identifier/param_dict (int): {param_entry}")
                    return param_entry

        return 1 

    # 2. Handle IntConst
    elif isinstance(node, IntConst):
        if "'" in node.value:
            try:
                width_str = node.value.split("'")[0]
                if width_str:
                    return int(width_str)
            except (ValueError, IndexError):
                pass 

        val = parse_verilog_int(node.value)
        if val is not None:
            if val == 0: return 1
            if val < 0: 
                return abs(val).bit_length() + 1
            return val.bit_length()
        return 1 

    # 3. Handle FloatConst
    elif isinstance(node, FloatConst):
        return 32
        
    # 4. Handle Operators 
    elif isinstance(node, (Plus, Minus)):
        left_width = get_operand_width(node.left, signal_dict, param_dict)
        right_width = get_operand_width(node.right, signal_dict, param_dict)
        if left_width is not None and right_width is not None:
            return max(left_width, right_width) + 1
        return None

    elif isinstance(node, Times):
        left_width = get_operand_width(node.left, signal_dict, param_dict)
        right_width = get_operand_width(node.right, signal_dict, param_dict)
        if left_width is not None and right_width is not None:
            return left_width + right_width
        return None

    elif isinstance(node, Divide):
        left_width = get_operand_width(node.left, signal_dict, param_dict)
        return left_width

    elif isinstance(node, Mod):
        right_width = get_operand_width(node.right, signal_dict, param_dict)
        return right_width

    elif isinstance(node, (And, Or, Xor, Xnor)): 
        left_width = get_operand_width(node.left, signal_dict, param_dict)
        right_width = get_operand_width(node.right, signal_dict, param_dict)
        if left_width is not None and right_width is not None:
            return max(left_width, right_width)
        return None


    elif isinstance(node, (Sll, Srl, Sla, Sra)): 
        left_width = get_operand_width(node.left, signal_dict, param_dict)
        return left_width

    elif isinstance(node, (Eq, NotEq, GreaterThan, LessThan, Eql, NotEql)): 
        return 1

    elif isinstance(node, Uminus):
        operand_width = get_operand_width(node.right, signal_dict, param_dict) 
        if operand_width is not None:
            return operand_width
        return None

    elif isinstance(node, Ulnot): 
        return 1

    elif isinstance(node, Unot): 
        operand_width = get_operand_width(node.right, signal_dict, param_dict)
        if operand_width is not None:
            return operand_width
        return None

    elif isinstance(node, (Uand, Uor, Uxor)): 
        return 1
        
    elif isinstance(node, Concat):
        total_width = 0
        all_widths_found = True
        for item in node.list:
            item_width = get_operand_width(item, signal_dict, param_dict)
            if item_width is None:
                all_widths_found = False
                break
            total_width += item_width
        if all_widths_found:
            return total_width
        return None

    elif isinstance(node, Repeat):
        repeat_count_node = node.left
        repeated_expr_node = node.right
        
        N = None
        if isinstance(repeat_count_node, IntConst):
            N = parse_verilog_int(repeat_count_node.value)
        elif isinstance(repeat_count_node, Identifier) and repeat_count_node.name in param_dict:
            param_val = param_dict[repeat_count_node.name].get('value')
            if param_val is not None:
                N = parse_verilog_int(param_val)
        
        if N is not None and N > 0:
            expr_width = get_operand_width(repeated_expr_node, signal_dict, param_dict)
            if expr_width is not None:
                return N * expr_width
        return None

    elif isinstance(node, (Partselect)):
        if isinstance(node, Partselect):
            msb_width = get_operand_width(node.msb, signal_dict, param_dict)
            lsb_width = get_operand_width(node.lsb, signal_dict, param_dict)
            if msb_width is not None and lsb_width is not None:
                msb_val = parse_verilog_int(node.msb.value) if isinstance(node.msb, IntConst) else None
                lsb_val = parse_verilog_int(node.lsb.value) if isinstance(node.lsb, IntConst) else None
                if msb_val is not None and lsb_val is not None:
                    return msb_val - lsb_val + 1
            return None 
        

    # Return None for unhandled node types
    return None

def generate_module_code(module_name, code_body, port_info, internal_reg_decls=None, referenced_params=None, param_dict=None):
    """
    Ensure parameters are re-declared, and force internal regs to match output port widths.
    """
    if internal_reg_decls is None: internal_reg_decls = []
    if referenced_params is None: referenced_params = []
    if param_dict is None: param_dict = {}

    # === 1. Build ANSI style port declarations ===
    input_declarations = []
    output_declarations = []
    
    output_info = None 
    
    for name, info in port_info.items():
        direction = info.get('direction', 'wire')
        
        type_keyword = ""
        if direction == 'input': type_keyword = "" 
        elif direction == 'output': type_keyword = ""
        else: type_keyword = "wire"

        signed_str = "signed" if info.get('signed', False) else ""
        
        width_val = info.get('width')
        if isinstance(width_val, int):
            width_str = f"[{width_val - 1}:0]" if width_val > 1 else ""
        elif isinstance(width_val, str):
            width_str = width_val
        else:
            width_str = ""

        decl_parts = [direction, type_keyword, signed_str, width_str, name]
        declaration = " ".join(filter(None, decl_parts)).replace("  ", " ")
        
        if direction == 'input':
            input_declarations.append(declaration)
        elif direction == 'output':
            output_declarations.append(declaration)
            if output_info is None: 
                output_info = {
                    'signed_str': signed_str,
                    'width_str': width_str
                }

    input_declarations.sort()
    output_declarations.sort()
    port_declarations = input_declarations + output_declarations
    port_list_str = ",\n  ".join(port_declarations)
    
    # === 2. Build localparam declarations ===
    param_declarations_str = ""
    if referenced_params:
        param_lines = ["\n  // --- Referenced Parameters ---"]
        for param_name in sorted(referenced_params):
            if param_name in param_dict:
                param_value_info = param_dict[param_name]
                param_value = param_value_info.get('value') if isinstance(param_value_info, dict) else param_value_info
                if param_value is not None:
                    param_lines.append(f"  localparam {param_name} = {param_value};")
                else:
                    print(f"Warning: Parameter '{param_name}' has no value, skipping")
        if len(param_lines) > 1:
            param_declarations_str = "\n".join(param_lines) + "\n"
            
    # === 3. Regenerate internal reg declarations ===
    internal_decls_str = ""
    if internal_reg_decls:
        if output_info:
            unified_signed_str = output_info['signed_str']
            unified_width_str = output_info['width_str']
            
            new_internal_decls = []
            for decl_str in internal_reg_decls:
                match = re.search(r"reg(?:\s+signed)?(?:\s*\[[^\]]+\])?\s*(\w+);", decl_str)
                if match:
                    reg_name = match.group(1)
                    new_decl_parts = ["reg", unified_signed_str, unified_width_str, reg_name + ";"]
                    new_decl_str = " ".join(filter(None, new_decl_parts)).replace("  ", " ")
                    new_internal_decls.append(new_decl_str)
                else:
                    new_internal_decls.append(decl_str)
                    print(f"Warning: Could not parse internal reg declaration, keeping original: {decl_str}")

            internal_decls_str = "  " + "\n  ".join(new_internal_decls) + "\n"
        else:
            print("Warning: No output port found, using original internal reg declarations.")
            internal_decls_str = "  " + "\n  ".join(internal_reg_decls) + "\n"

    # === 4. Assemble final module code ===
    module_code = (
        f"module {module_name} (\n  {port_list_str}\n);\n"
        f"{param_declarations_str}"
        f"{internal_decls_str}"
        f"{code_body}\n\n"
        f"endmodule"
    )

    return module_code


def replace_code_block_by_lines(file_lines, start_line, end_line, replacement_code):
    replacement_lines = [line + '\n' for line in replacement_code.splitlines()]
    new_lines = file_lines[:start_line-1] + replacement_lines + file_lines[end_line:]
    return new_lines

class MySimpleVisitor:
    """A simplified AST visitor implementation."""
    def visit(self, node):
        if node is None:
            return
        method = 'visit_' + node.__class__.__name__
        visitor = getattr(self, method, self.generic_visit)
        return visitor(node)

    def generic_visit(self, node):
        """Visit all children by default."""
        if hasattr(node, 'children'):
            for c in node.children():
                self.visit(c)


class PruningVisitor(MySimpleVisitor):
    """
    An AST visitor to prune nodes from a subtree based on line numbers.
    """
    def __init__(self, linenos_to_prune):
        self.linenos_to_prune = linenos_to_prune

    def visit_Block(self, node):
        new_statements = []
        for s in node.statements:
            if hasattr(s, 'lineno') and s.lineno in self.linenos_to_prune:
                continue
            else:
                self.visit(s)
                new_statements.append(s)
        node.statements = new_statements
                
    def visit_IfStatement(self, node):
        self.visit(node.true_statement)
        self.visit(node.false_statement)
    
    def visit_IfStatement_alternative(self, node):
        if hasattr(node.true_statement, 'lineno') and node.true_statement.lineno in self.linenos_to_prune:
            node.true_statement = None
        else:
            self.visit(node.true_statement)
            
        if hasattr(node.false_statement, 'lineno') and node.false_statement.lineno in self.linenos_to_prune:
            node.false_statement = None
        else:
            self.visit(node.false_statement)

class RenamingCodegen(ASTCodeGenerator):
    def __init__(self, rename_map):
        super().__init__(); self.rename_map = rename_map
    def visit_Identifier(self, node):
        return self.rename_map.get(node.name, node.name)


def trace_backward_single(start_node, max_depth, all_assigns_in_data_path):
    """
    Trace backward through the pipeline starting from a specific node.
    """
    traced_stmts = set()
    boundary_inputs = set()

    def get_signal_name(node):
        if isinstance(node, Identifier): return node.name
        return None

    start_sig_name = get_signal_name(start_node)
    if not start_sig_name:
        print(f"Skipping trace - start node is not a simple signal.")
        return traced_stmts, boundary_inputs
    
    print(f"Executing trace_backward_single from '{start_sig_name}' with max depth {max_depth}")

    queue = [(start_sig_name, 0)]
    visited_in_path = {start_sig_name}
    head = 0

    while head < len(queue):
        current_sig, current_depth = queue[head]; head += 1

        if current_depth >= max_depth:
            boundary_inputs.add(current_sig)
            print(f"Boundary found: '{current_sig}' (depth limit reached).")
            continue

        driver_stmt = next((s for s in all_assigns_in_data_path if getattr(s.left.var, 'name', '') == current_sig), None)

        if driver_stmt:
            traced_stmts.add(driver_stmt)
            
            inputs_of_driver = extract_identifier_names(driver_stmt.right)
            for inp_sig in inputs_of_driver:
                if inp_sig not in visited_in_path:
                    visited_in_path.add(inp_sig)
                    queue.append((inp_sig, current_depth + 1))
        else:
            boundary_inputs.add(current_sig)
            print(f"Boundary found: '{current_sig}' (no driver).")

    return traced_stmts, boundary_inputs

def trace_forward(start_signal_name, max_depth, all_assigns_in_data_path):
    """
    Trace forward through pure pipeline stages starting from a specific signal.
    """
    traced_stmts = set()
    boundary_outputs = set()
    
    print(f"Executing trace_forward from '{start_signal_name}' with max depth {max_depth}")

    if not start_signal_name:
        return traced_stmts, boundary_outputs

    queue = [(start_signal_name, 0)]
    visited = {start_signal_name}
    head = 0

    while head < len(queue):
        sig, depth = queue[head]; head += 1

        if depth >= max_depth:
            boundary_outputs.add(sig)
            print(f"Boundary found: '{sig}' (depth limit reached).")
            continue

        driven_stmts = [
            s for s in all_assigns_in_data_path
            if len(extract_identifier_names(s.right)) == 1 and sig in extract_identifier_names(s.right)
        ]

        if not driven_stmts:
            boundary_outputs.add(sig)
            print(f"Boundary found: '{sig}' (no forward pipe).")
        else:
            for stmt in driven_stmts:
                traced_stmts.add(stmt)
                next_reg = getattr(stmt.left.var, 'name', None)
                if next_reg and next_reg not in visited:
                    visited.add(next_reg)
                    queue.append((next_reg, depth + 1))

    return traced_stmts, boundary_outputs


            
def get_input_pipeline_depths(always_node):
    
    def get_names_from_node(node):
        names = set()
        if isinstance(node, Identifier):
            names.add(node.name)
        for child in node.children():
            names.update(get_names_from_node(child))
        return names

    assigns = [stmt for stmt in extract_procedural_assigns(always_node.statement) 
               if isinstance(stmt, NonblockingSubstitution)]

    if not assigns:
        return {}

    all_lhs_names = set()
    all_rhs_names = set()

    for stmt in assigns:
        if hasattr(stmt.left, 'var') and hasattr(stmt.left.var, 'name'):
            all_lhs_names.add(stmt.left.var.name)
        if hasattr(stmt, 'right'):
            all_rhs_names.update(get_names_from_node(stmt.right))
            
    input_signals = all_rhs_names - all_lhs_names

    depth_map = {}
    for sig in input_signals:
        depth_map[sig] = 0
    for sig in all_lhs_names:
        depth_map[sig] = -1 

    changed = True
    max_iterations = len(all_lhs_names) + 5
    iterations = 0
    
    while changed and iterations < max_iterations:
        changed = False
        iterations += 1
        
        for stmt in assigns:
            if not (hasattr(stmt.left, 'var') and hasattr(stmt.left.var, 'name')):
                continue

            lhs_name = stmt.left.var.name
            rhs_names = get_names_from_node(stmt.right)

            max_rhs_depth = -1
            all_rhs_known = True
            
            for rhs_name in rhs_names:
                if depth_map.get(rhs_name, -1) == -1:
                    all_rhs_known = False
                    break
                max_rhs_depth = max(max_rhs_depth, depth_map.get(rhs_name, 0))

            if not all_rhs_known:
                continue

            new_depth = max_rhs_depth + 1
            
            if new_depth != depth_map.get(lhs_name, -1):
                depth_map[lhs_name] = new_depth
                changed = True

    if iterations >= max_iterations:
        print("Warning: Register depth calculation reached max iterations. Possible combinational loop.")

    for key, value in depth_map.items():
        if value == -1:
            depth_map[key] = 0
            
    return depth_map


def validate_output_pipeline_depth(always_node, depth_map, core_op_node, max_output_depth):
    """
    Check the pipeline depth of a core calculation result and its downstream registers.
    Ensures they don't exceed max_output_depth relative to the core result.
    """
    procedural_assigns = extract_procedural_assigns(always_node.statement)

    # a. find the direct output signal of the core operation
    core_result_signal_name = None
    for stmt in procedural_assigns:
        rhs = getattr(stmt.right, 'var', stmt.right)
        if rhs is core_op_node:
            core_result_signal_name = getattr(stmt.left.var, 'name', None)
            break
    
    if not core_result_signal_name:
        print(f"Output Validation FAILED. Internal error: Could not find the LHS of the core operation.")
        return False
        
    core_result_depth = depth_map.get(core_result_signal_name, 0)

    # b. trace all downstream registers driven by the core result
    downstream_signals = {core_result_signal_name}
    queue = [core_result_signal_name]
    visited = {core_result_signal_name}
    
    while queue:
        current_signal = queue.pop(0)
        for stmt in procedural_assigns:
            rhs_names = list(extract_identifier_names(stmt.right))
            if len(rhs_names) == 1 and current_signal == rhs_names[0]:
                next_reg_name = getattr(stmt.left.var, 'name', None)
                if next_reg_name and next_reg_name not in visited:
                    downstream_signals.add(next_reg_name)
                    queue.append(next_reg_name)
                    visited.add(next_reg_name)

    print(f"Signals downstream from core operation to check for depth: {downstream_signals}")

    # c. verify relative depth for all downstream registers
    for signal_name in downstream_signals:
        absolute_depth = depth_map.get(signal_name, 0)
        relative_depth = absolute_depth - core_result_depth
        
        if relative_depth > max_output_depth:
            print(f"Output Validation FAILED for downstream signal '{signal_name}'.")
            print(f"Relative depth ({relative_depth}) exceeds max allowed ({max_output_depth}).")
            return False
            
    return True

def find_final_output_port(module_node):
    """
    Traverse a module's declarations to find and return the name of the final output port.
    Returns None if no output or multiple outputs are found.
    """
    output_ports = []
    
    if not hasattr(module_node, 'items'):
        return None

    for item in module_node.items:
        if isinstance(item, Decl):
            if hasattr(item, 'list') and item.list:
                declaration = item.list[0]
                
                if isinstance(declaration, Output):
                    if hasattr(declaration, 'name'):
                        output_ports.append(declaration.name)

    if len(output_ports) == 1:
        return output_ports[0]
    else:
        print(f"Validation FAILED. Found {len(output_ports)} output ports in module '{module_node.name}'. Expected 1.")
        return None
    
    
def find_driver_of_output(always_node, assign_stmts, final_output_port_name):
    
    all_lhs_in_always = {
        stmt.left.var.name 
        for stmt in extract_procedural_assigns(always_node.statement) 
        if hasattr(stmt.left, 'var') and hasattr(stmt.left.var, 'name')
    }
    
    if final_output_port_name in all_lhs_in_always:
        return final_output_port_name
    
    if len(assign_stmts) == 1:
        the_assign = assign_stmts[0]
        if (hasattr(the_assign.left, 'var') and 
            the_assign.left.var.name == final_output_port_name and
            isinstance(the_assign.right.var, Identifier)):
            return the_assign.right.var.name
    return None

def is_simple_assign(assign_node):
    """
    Check if an assign statement is a simple signal-to-signal connection.
    Example: `assign p = out;`
    """
    if not isinstance(assign_node, Assign):
        return False

    lhs_is_simple = False
    if isinstance(assign_node.left, Lvalue) and isinstance(assign_node.left.var, Identifier):
        lhs_is_simple = True
    elif isinstance(assign_node.left, Identifier):
        lhs_is_simple = True

    if not lhs_is_simple:
        return False
        
    rhs_is_simple = False
    if isinstance(assign_node.right, Rvalue) and isinstance(assign_node.right.var, Identifier):
        rhs_is_simple = True
    elif isinstance(assign_node.right, Identifier):
        rhs_is_simple = True

    if not rhs_is_simple:
        return False

    return True