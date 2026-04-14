import os
import re
import shutil
from pyverilog.vparser.parser import parse
from pyverilog.vparser.ast import *
from pyverilog.ast_code_generator.codegen import ASTCodeGenerator
from collections import defaultdict, deque
from signal_utils import eval_expr
from utils import *



codegen = ASTCodeGenerator()


def process_mult_op_in_statement(stmt_node, mul_op_items, signal_dict, param_dict, container_node=None, processed_nodes=None, matched_line_numbers=None):
    """
    Strictly check if the assignment matches the A*B @ C pattern (multiply-add / post-processing).
    @ represents {+, -, &, |, ^}
    """
    if stmt_node.lineno not in matched_line_numbers:
        return  
    if processed_nodes is None:
        processed_nodes = set()

    
    if id(stmt_node) in processed_nodes:
        return
    
    # === 1. get and verify top-level operation (must be post-processing @) ===
    rhs_node = None
    if isinstance(stmt_node, (BlockingSubstitution, NonblockingSubstitution)):
        rhs_node = stmt_node.right
    elif isinstance(stmt_node, Assign):
        if hasattr(stmt_node, 'rightlist') and hasattr(stmt_node.rightlist, 'list') and len(stmt_node.rightlist.list) == 1:
            rhs_node = stmt_node.rightlist.list[0]
        elif hasattr(stmt_node, 'right') and stmt_node.right is not None:
            rhs_node = stmt_node.right
            
    if rhs_node is None:
        return
    
    top_level_op = rhs_node.var if isinstance(rhs_node, Rvalue) else rhs_node
    ALLOWED_POST_OPS = (Plus, Minus, And, Or, Xor)
    if not isinstance(top_level_op, ALLOWED_POST_OPS):
        return

    # === 2.find multiplication node (*) among children of @ ===
    # a. decompose @ to find * and C
    times_node, c_node = (top_level_op.left, top_level_op.right) if isinstance(top_level_op.left, Times) else \
                         (top_level_op.right, top_level_op.left) if isinstance(top_level_op.right, Times) else (None, None)
    if times_node is None: return

    # b. decompose * to find A and B
    a_node, b_node = times_node.left, times_node.right

    # === 3. [Unified Validation] verify all operand types at once ===
    ALLOWED_OPERANDS = (Identifier, Pointer, IntConst, FloatConst)
    all_operand_nodes = [a_node, b_node, c_node]
    if not all(isinstance(op, ALLOWED_OPERANDS) for op in all_operand_nodes):
        return

    # === 4. strict degradation pattern checks ===
    operands = {'A': a_node, 'B': b_node, 'C': c_node}
    operand_values = {}
    is_all_const_or_param = True

    for name, node in operands.items():
        val = eval_expr(node, param_dict) 
        operand_values[name] = val
        if val is None: # eval_expr returns None for signals
            is_all_const_or_param = False
            
    # rule 1: pure constant/parameter expression
    if is_all_const_or_param:
        print(f"DEBUG: REJECTED A*B @ C - All operands are constants. Skipped.")
        return

    # rule 2: zero degradation check
    # if A or B is 0, mult is 0, expression degrades to 0 @ C
    if operand_values.get('A') == 0 or operand_values.get('B') == 0:
        print(f"DEBUG: REJECTED A*B @ C - An input to the multiplier ('A' or 'B') is zero.")
        return

    # rule 3: multiply by one degradation check
    # if A or B is 1, mult is a passthrough, expression degrades to B @ C or A @ C
    if operand_values.get('A') == 1 or operand_values.get('B') == 1:
        print(f"DEBUG: REJECTED A*B @ C - An input to the multiplier ('A' or 'B') is one.")
        return

    # === 5. check bitwidths of A, B, C (tailored for DSP48E2 multiplier inputs) ===
    a_width = get_operand_width(a_node, signal_dict, param_dict) 
    b_width = get_operand_width(b_node, signal_dict, param_dict)
    c_width = get_operand_width(c_node, signal_dict, param_dict)

    if a_width is None or b_width is None or c_width is None:
        print(f"DEBUG: REJECTED A*B @ C - Could not determine width for all operands.")
        return

    # apply DSP48E2 bitwidth rules (A/B are multiplier inputs, C is accumulator input)
    # multiplier input ports: A(27-bit), B(18-bit). Swapping A and B is allowed.
    # accumulator input port: C(48-bit)
    is_mult_width_ok = (a_width <= 27 and b_width <= 18) or \
                       (a_width <= 18 and b_width <= 27)
    is_adder_width_ok = c_width <= 48
    
    if not (is_mult_width_ok and is_adder_width_ok):
        print(f"DEBUG: REJECTED A*B @ C - Operand widths (A:{a_width}, B:{b_width}, C:{c_width}) are not compatible with DSP48E2.")
        return
        
    print(f"DEBUG: PASSED A*B @ C Pattern - All checks are compatible with DSP48E2.")
    
    # === 6. update dictionary if all checks passed ===
    key_node = container_node if container_node is not None else stmt_node
    if key_node not in mul_op_items:
        mul_op_items[key_node] = []
        
    # store top-level op node as it contains complete computation info
    mul_op_items[key_node].append(top_level_op)

def extract_mult_add_info(container_node, signal_dict, param_dict, codegen):
    """
    Extract detailed port, parameter, and code body info for A * B @ C pattern.
    Supports parameters and constants as operands.
    """
    try:
        # --- 1. analyze container_node to find LHS and top-level RHS operations ---
        if not isinstance(container_node, (Assign, BlockingSubstitution, NonblockingSubstitution)):
            return None
        # assuming LHS is a simple signal
        lhs_base_name_list = list(extract_identifier_names(container_node.left))
        if not lhs_base_name_list: return None
        lhs_base_name = lhs_base_name_list[0]
        
        top_level_op = getattr(container_node.right, 'var', container_node.right)
       
        # --- 2. top-level operation must be post-processing @ ---
        ALLOWED_POST_OPS = (Plus, Minus, And, Or, Xor)
        if not isinstance(top_level_op, ALLOWED_POST_OPS):
            return None
            
        # --- 3. decompose @ to find * and C ---
        times_node, c_node = (top_level_op.left, top_level_op.right) if isinstance(top_level_op.left, Times) else \
                             (top_level_op.right, top_level_op.left) if isinstance(top_level_op.right, Times) else \
                             (None, None)
        if times_node is None:
            return None
        # [Relaxed] C can be a signal, parameter, or constant
        if not isinstance(c_node, (Identifier, Pointer, IntConst, FloatConst)):
            return None

        # --- 4.  decompose * to find A and B ---
        a_node, b_node = times_node.left, times_node.right
        # [Relaxed] A and B can be signals, parameters, or constants
        if not (isinstance(a_node, (Identifier, Pointer, IntConst, FloatConst)) and 
                isinstance(b_node, (Identifier, Pointer, IntConst, FloatConst))):
            return None
        
        # --- 5. extract details of all operands and identify parameters ---
        port_info = {}
        rebuild_map = {}
        referenced_params = set()

        # inner helper function to process each operand
        def process_operand(node, node_role):
            nonlocal port_info, rebuild_map, referenced_params
            if isinstance(node, (Identifier, Pointer)):
                base_name = get_base_name(node) 
                if base_name in param_dict:
                    referenced_params.add(base_name)
                    return
                if base_name in signal_dict:
                    conn_str = codegen.visit(node).strip()
                    width = get_expr_width(node, signal_dict, param_dict) 
                    is_signed = signal_dict.get(base_name, {}).get('signed', False)
                    width_str = f"[{width - 1}:0]" if width is not None and width > 1 else ""
                    port_name = f"{base_name}_in"
                    
                    port_info[port_name] = {
                        'direction': 'input', 
                        'width': width_str, 
                        'connect_to': conn_str, 
                        'signed': is_signed,
                        'type': 'wire' 
                    }
                    rebuild_map[base_name] = port_name
                else:
                    print(f"WARNING: {node_role} '{base_name}' not found in signal_dict or param_dict")
            elif not isinstance(node, (IntConst, FloatConst)):
                print(f"WARNING: Unsupported operand type for {node_role}: {type(node)}")

        # process A, B, C sequentially
        process_operand(a_node, 'A')
        process_operand(b_node, 'B')
        process_operand(c_node, 'C')

        # --- 6. extract output info ---
        lhs_conn_str = codegen.visit(container_node.left).strip()
        output_width = signal_dict.get(lhs_base_name, {}).get('width')
        is_p_signed = signal_dict.get(lhs_base_name, {}).get('signed', False)
        if output_width is None:
            print(f"WARNING: Could not determine width for output signal '{lhs_base_name}'.")
            return None

        # --- 7. build port_info and code_body ---
        output_width_str = f"[{output_width - 1}:0]" if output_width > 1 else ""
        p_port_name = f"{lhs_base_name}_out"
        
        port_info[p_port_name] = {
            'direction': 'output', 
            'width': output_width_str, 
            'connect_to': lhs_conn_str, 
            'signed': is_p_signed,
            'type': 'wire' 
        }
        
        # rebuild code_body using RenamingCodegen
        rebuilder = RenamingCodegen(rebuild_map) 
        rebuilt_rhs = rebuilder.visit(top_level_op)
        code_body = f"assign {p_port_name} = {rebuilt_rhs};"
        
        # --- 8. return all info ---
        return {
            'port_info': port_info,
            'code_body': code_body,
            'referenced_params': list(referenced_params)
        }
        
    except Exception as e:
        print(f"Error during A*B @ C info extraction: {e}")
        import traceback
        traceback.print_exc()
        return None

def handle_assign_mult_op(container_node, op_node, module, mod_name, modified_filename,
                                    signal_dict, file_lines, out_dir, param_dict,
                                    file_extraction_dict,source_name, module_instance_counts=None):
    try:
        # === case 1: module contains only one multiply-add assign, extract entire module ===
        behavioral_items = [
            item for item in module.items 
            if isinstance(item, (Assign, Always, Initial, Instance)) # Instance represents module instantiation
        ]
        if len(behavioral_items) == 1 and behavioral_items[0] == container_node:
            print(f"Extracting entire module {module.name} (single mult-add assign).")
            
            # --- execute extraction ---
            start_line = module.lineno - 1
            end_line = find_end_line(file_lines, start_line)
            module_lines = file_lines[start_line:end_line + 1]

            with open(os.path.join(out_dir, f"{mod_name}.v"), 'w') as f:
                f.writelines(module_lines)

            modified_lines = remove_module_from_lines(file_lines, module.name)
            with open(os.path.join(out_dir, modified_filename), 'w') as f:
                f.writelines(modified_lines)
            
            # --- update status and return success ---
            line_num = op_node.lineno

            # 2. build dict to store
            update_data = {
                'dsp_module_name': mod_name,
                'source_function': source_name, # source_name is passed as argument
                'dsp_count': module_instance_counts.get(module.name, 1) * 1
            }

            # 3. directly modify the passed "global" dict
            # update value at corresponding line number
            if line_num in file_extraction_dict:
                file_extraction_dict[line_num] = update_data
            else:
                file_extraction_dict[line_num] = update_data

            # 4. return boolean success flag
            return True

        # === fallback to finer-grained processing ===
        is_inside_for, dsp_count = get_assign_count(container_node, param_dict)

        # === case 2: assign is inside a for-loop ===
        if is_inside_for:
            if dsp_count > 0:
                print(f"Assign is inside a for-loop. Estimated DSP usage: {dsp_count}")
                for_loop_node = find_innermost_for_node(container_node)
        
                if for_loop_node is None:
                    print("Error: Inconsistent state. is_inside_for is True, but no for-loop node was found.")
                    return False 

                # --- execute extraction ---
                original_code_str = codegen.visit(container_node)
                extraction_result = extract_loop_logic(
                    original_code_str, for_loop_node, container_node, 
                    signal_dict, param_dict, codegen
                )
                
                transformed_body = extraction_result["transformed_body"]
                port_info = extraction_result["port_info"]
                loop_var = extraction_result["loop_var"]
                params_to_add = extraction_result["referenced_params"]

                # --- 2. generate new reusable submodule ---
                mod_code = generate_module_code(
                    mod_name, 
                    transformed_body, 
                    port_info,
                    # pass parameter info to code generator
                    referenced_params=params_to_add,
                    param_dict=param_dict
                )
                with open(os.path.join(out_dir, f"{mod_name}.v"), 'w') as f:
                    f.write(mod_code)
                
                instance_name_in_loop = f"{mod_name}_inst"
                instance_code = create_instance_code(
                    mod_name, 
                    instance_name_in_loop, 
                    port_info, 
                    loop_var
                )
                
                # b. create unique name for generate block
                gen_block_name = f"gen_{mod_name}"

                # c. rebuild for-loop header
                pre_str = codegen.visit(for_loop_node.pre).strip().rstrip(';')
                cond_str = codegen.visit(for_loop_node.cond).strip()
                post_str = codegen.visit(for_loop_node.post).strip().rstrip(';')
                gen_for_loop_header = f"for ({pre_str}; {cond_str}; {post_str})"
                
                # d. assemble final replacement code
                replacement_code = (
                    f"generate\n"
                    f"  // Original for-loop logic has been extracted into module '{mod_name}'\n"
                    f"  {gen_for_loop_header} begin : {gen_block_name}\n"
                    f"    {instance_code}\n"
                    f"  end\n"
                    f"endgenerate"
                )
                
                # --- 4. replace original code ---
                # trace up to find outermost for/generate container
                node_to_replace = for_loop_node
                while hasattr(node_to_replace, 'parent') and \
                      isinstance(node_to_replace.parent, (ForStatement, GenerateStatement)):
                    node_to_replace = node_to_replace.parent
                
                start_line = node_to_replace.lineno
                end_line = find_end_of_block_lineno(node_to_replace, file_lines)

                modified_lines = replace_code_block_by_lines(
                    file_lines, 
                    start_line, 
                    end_line, 
                    replacement_code
                )
                with open(os.path.join(out_dir, modified_filename), 'w') as f:
                    f.writelines(modified_lines)
                
                # --- update status and return success ---
                line_num = op_node.lineno

                # 2. build dict to store
                update_data = {
                    'dsp_module_name': mod_name,
                    'source_function': source_name, 
                    'dsp_count': dsp_count * module_instance_counts.get(module.name, 1) * 1
                }

                # 3. directly modify the passed "global" dict
                if line_num in file_extraction_dict:
                    file_extraction_dict[line_num] = update_data
                else:
                    file_extraction_dict[line_num] = update_data

                # 4. return boolean success flag
                return True
                
            else: 
                print("Assign is in a for-loop, but loop count failed to parse. Skipping.")
                return False 
        
        # === case 3: simple non-loop assign ===
        else:
            print("Assign is not in a for-loop. Extracting single mult-add.")
            
            extraction_result = extract_mult_add_info(container_node, signal_dict, param_dict, codegen)
            
            if not extraction_result:
                print(" Node does not match (A*B)@C pattern. Skipping.")
                return False 

            print("     Successfully identified mult-add pattern (A*B)@C.")
                        
            
             # a. unpack extraction results
            port_info = extraction_result['port_info']
            code_body = extraction_result['code_body']
            params_to_add = extraction_result.get('referenced_params', []) 

            # b.  generate new module, passing parameter info
            mod_code = generate_module_code(
                mod_name, 
                code_body, 
                port_info,
                referenced_params=params_to_add,
                param_dict=param_dict
            )
            with open(os.path.join(out_dir, f"{mod_name}.v"), 'w') as f:
                f.write(mod_code)
            print(f" Generated module successfully: {mod_name}.v")

            # c. create instance code
            instance_name = f"{mod_name}_inst"
            instance_code = create_instance_code(mod_name, instance_name, extraction_result['port_info'])
            print(f"     Generated instantiation code: {instance_code}")
            
            # d. replace code (single line replacement)
            start_line = container_node.lineno
            modified_lines = replace_code_block_by_lines(file_lines, start_line, start_line, instance_code)
            with open(os.path.join(out_dir, modified_filename), 'w') as f:
                f.writelines(modified_lines)
            
            # e. update status dict 
            line_num = op_node.lineno

            update_data = {
                'dsp_module_name': mod_name,
                'source_function': source_name, 
                'dsp_count': module_instance_counts.get(module.name, 1) * 1
            }

            if line_num in file_extraction_dict:
                file_extraction_dict[line_num] = update_data
            else:
                file_extraction_dict[line_num] = update_data

            return True

    except Exception as e:
        # catch all exceptions to prevent crash
        print(f"Error during handle_assign_multiplication for node at line {container_node.lineno}: {e}")
        import traceback
        traceback.print_exc()
        return False

def is_simple_always_mult_add(always_node, codegen):
    """
    Check if always block strictly matches a pipeline structure containing only a single core A*B@C computation
    and its related registers.
    """
    # === check 1: verify sequential always block ===
    if not hasattr(always_node, 'sens_list') or not always_node.sens_list:
        return False, None
    
    is_timing = any(
        isinstance(sens, Sens) and sens.type in ('posedge', 'negedge')
        for sens in always_node.sens_list.list
    )
    if not is_timing:
        return False, None
    
    # === check 2: verify block content is a simple begin...end structure ===
    if not hasattr(always_node, 'statement') or not isinstance(always_node.statement, Block):
        return False, None
        
    statements = always_node.statement.statements if hasattr(always_node.statement, 'statements') else []
    if not statements:
        return False, None

    # === 3. find the unique A*B@C computation and separate pipeline registers ===
    core_op_stmt = None # record the full statement containing the core operation
    
    # [Core Diff] helper function to strictly check A*B@C pattern
    def is_mult_add_pattern(node):
        """
        Check if AST node matches A*B @ C structure, where A, B, C must be simple signals.
        """
        ALLOWED_POST_OPS = (Plus, Minus, And, Or, Xor)
        if not isinstance(node, ALLOWED_POST_OPS): return False
        
        times_node = node.left if isinstance(node.left, Times) else node.right if isinstance(node.right, Times) else None
        c_node = node.right if isinstance(node.left, Times) else node.left
        if not times_node or not isinstance(c_node, (Identifier, Pointer)): return False
        
        # ensure multiplier inputs (A, B) are also simple signals
        if not isinstance(times_node.left, (Identifier, Pointer)) or \
           not isinstance(times_node.right, (Identifier, Pointer)):
            return False
            
        return True

    pipeline_stmts = []
    for stmt in statements:
        if not isinstance(stmt, NonblockingSubstitution): return False, None # only allow non-blocking assignments
        rhs = getattr(stmt.right, 'var', stmt.right)
        
        if is_mult_add_pattern(rhs):
            if core_op_stmt is not None:
                print(f"DEBUG: is_simple_always_mult_add FAILED - Found a second core computation.")
                return False, None # only one core computation allowed
            core_op_stmt = stmt
        elif isinstance(rhs, (Identifier, Pointer)):
            pipeline_stmts.append(stmt) # simple register cascade
        else:
            print(f"DEBUG: is_simple_always_mult_add FAILED - Found invalid computation type.")
            return False, None # disallow other complex computations
                
    if core_op_stmt is None:
        print(f"DEBUG: is_simple_always_mult_add FAILED - Core computation not found.")
        return False, None
        
    core_op_node = getattr(core_op_stmt.right, 'var', core_op_stmt.right)

    # === 4. build and verify signal whitelist ===

    # a. extract seed signals from core computation
    related_signals = {name for name in extract_identifier_names(core_op_node)}
    core_op_output_name = codegen.visit(core_op_stmt.left)
    related_signals.add(core_op_output_name)
    
    # b. repeatedly trace dependencies to populate whitelist
    newly_added = True
    while newly_added:
        newly_added = False
        for stmt in pipeline_stmts:
            lhs_name = codegen.visit(stmt.left)
            rhs_name = codegen.visit(stmt.right)
            
            lhs_is_related = lhs_name in related_signals
            rhs_is_related = rhs_name in related_signals

            # bidirectional tracing
            if rhs_is_related and not lhs_is_related: # backward trace
                related_signals.add(lhs_name)
                newly_added = True
            
            if lhs_is_related and not rhs_is_related: # forward trace
                related_signals.add(rhs_name)
                newly_added = True

    # c. final validation: check if all assigned signals in always block are in whitelist
    all_lhs_in_always = {codegen.visit(s.left) for s in statements}
    
    if not all_lhs_in_always.issubset(related_signals):
        unrelated = all_lhs_in_always - related_signals
        print(f"DEBUG: is_simple_always_mult_add FAILED - Found assignment targets unrelated to the core computation: {unrelated}")
        return False, None

    print("DEBUG: Passed all checks for is_simple_always_mult_add.")
    return True, core_op_node


def is_valid_pipelined_mult_op_module(module, always_node):
    """
    [A*B@C Dedicated] Check if module matches a specific multiply-post-processing pipeline structure.
    """
    # === 1. top-level structure check ===
    always_count = 0
    ALLOWED_TOP_LEVEL_TYPES = (Always, Assign, Decl)
    for item in module.items:
        if not isinstance(item, ALLOWED_TOP_LEVEL_TYPES):
            return False # disallow other block types like 'initial'
        if isinstance(item, Always):
            always_count += 1
    
    if always_count != 1: return False # must have exactly one always block
        
    the_only_always_node = [item for item in module.items if isinstance(item, Always)][0]
    if the_only_always_node is not always_node: return False # ensure it's the target always block

    # check if all assign statements are simple connections
    all_assign_stmts = [item for item in module.items if isinstance(item, Assign)]
    for assign_stmt in all_assign_stmts:
        rhs_node = getattr(getattr(assign_stmt, 'right', None), 'var', None)
        if not isinstance(rhs_node, (Identifier, Pointer)):
            print(f"DEBUG: Validation FAILED. Found a complex assign statement (line {assign_stmt.lineno}).")
            return False
     
    # === 2. always block internal structure check ===
    # call dedicated check function for A*B@C pattern
    is_simple, core_op_node = is_simple_always_mult_add(always_node, codegen)
    if not is_simple:
        return False
        
    # === 3. decompose core operation, find A, B, C nodes ===
    try:
        # decompose A*B@C AST
        times_node, c_node = (core_op_node.left, core_op_node.right) if isinstance(core_op_node.left, Times) else \
                             (core_op_node.right, core_op_node.left)
        a_node, b_node = times_node.left, times_node.right
    except AttributeError:
        # validation fails if decomposition fails
        return False

    # ensure all leaf nodes are simple signals
    if not all(isinstance(n, (Identifier, Pointer)) for n in [a_node, b_node, c_node]):
        return False

    # === 4. calculate and verify pipeline depth ===
    depth_map = get_input_pipeline_depths(always_node) 
    
    a_depth = depth_map.get(a_node.name, 0)
    b_depth = depth_map.get(b_node.name, 0)
    c_depth = depth_map.get(c_node.name, 0)

    # apply A*B@C pipeline rules
    # rule 1: A/B are multiplier inputs, pipeline depth <= DSP internal register limit (usually 2)
    if a_depth > 2 or b_depth > 2: 
        print(f"DEBUG: Validation FAILED. Multiplier input pipeline depth for A({a_depth}) or B({b_depth}) exceeds 2.")
        return False

    # rule 2: C is post-adder input, needs enough depth to align with multiplier latency
    # DSP C port has 1 register (CREG), multiplier latency is ~2-3 stages
    # so C's total depth <= 1 (CREG) + 2 (alignment) = 3 (reasonable upper bound)
    if c_depth > 3: 
        print(f"DEBUG: Validation FAILED. Post-adder input pipeline depth for C({c_depth}) exceeds 3.")
        return False

    # rule 3: output pipeline depth <= DSP output register limit (usually 1, PREG)
    if not validate_output_pipeline_depth(always_node, depth_map, core_op_node, max_output_depth=1): 
         return False

    # all checks passed
    print("DEBUG: Validation PASSED for pipelined A*B@C module.")
    return True


def extract_mult_op_pipeline_slice(always_node, core_op_node, signal_dict, param_dict, codegen):
    """
    [A*B@C Dedicated] Extract a multiply-add pipeline slice from a complex sequential always block.
    Uses line number mapping to resolve AST pruning identity issues.
    """
    
    # === internal helper functions ===
    def _build_always_block(stmts, clk_edge, clk_name, code_generator):
        if not stmts: return ""
        renamed_clk = code_generator.visit(Identifier(clk_name))
        lines = [f"always @({clk_edge} {renamed_clk}) begin"]
        for stmt in sorted(list(stmts), key=lambda s: s.lineno):
            lines.append(f"  {code_generator.visit(stmt)}")
        lines.append("end")
        return "\n".join(lines)

    def _add_port_to_info(port_info, new_port_name, original_signal_name, direction, signal_dict, is_reg=False):
        info = signal_dict.get(original_signal_name, {})
        width_val = info.get('width')
        width_str = f"[{width_val - 1}:0]" if isinstance(width_val, int) and width_val > 1 else ""
        is_signed = info.get('signed', False)
        
        # fix type as 'reg'
        port_info[new_port_name] = {
            'connect_to': original_signal_name,
            'direction': direction,
            'width': width_str,
            'is_array': False,
            'signed': is_signed,
            'is_reg': is_reg,
            'type': 'reg'  
        }


    # === step 0: context analysis ===
    clk_name, clk_edge = None, None
    if hasattr(always_node, 'sens_list') and hasattr(always_node.sens_list, 'list'):
        for sens in always_node.sens_list.list:
            if isinstance(sens, Sens) and sens.type in ('posedge', 'negedge'):
                if isinstance(sens.sig, Identifier):
                    clk_name, clk_edge = sens.sig.name, sens.type
                    break
    if not clk_name:
        print("DEBUG: Slice Error - Could not determine clock signal.")
        return None
    
    # === step A: decompose always block into reset logic and main data path ===
    main_logic_block = None
    reset_logic_block = None
    reset_signal_name = None
    is_reset_active_high = True

    POSSIBLE_RESET_NAMES = {'reset', 'rst', 'reset_n', 'rst_n'}
    
    # by default, entire block is main logic
    analysis_mode = 'TREAT_AS_WHOLE'

    # --- start structural check ---
    if isinstance(always_node.statement, Block) and \
        len(always_node.statement.statements) == 1 and \
        isinstance(always_node.statement.statements[0], IfStatement):
        
        if_stmt = always_node.statement.statements[0]
        
        # must have else branch
        if if_stmt.false_statement is not None:
            condition_node = if_stmt.cond
            temp_reset_name = None
            temp_is_active_high = None

            # check if condition is a reset signal
            if isinstance(condition_node, Identifier) and condition_node.name in POSSIBLE_RESET_NAMES:
                temp_reset_name = condition_node.name
                temp_is_active_high = True
            elif isinstance(condition_node, (Unot, Ulnot)) and \
                 isinstance(condition_node.right, Identifier) and \
                 condition_node.right.name in POSSIBLE_RESET_NAMES:
                temp_reset_name = condition_node.right.name
                temp_is_active_high = False
            
            if temp_reset_name is not None:
                else_block_node = if_stmt.false_statement
                
                if contains_conditional_logic(else_block_node):
                    # fail directly if found
                    print(f"DEBUG: Slice FAILURE at line {always_node.lineno}. "
                          "The 'else' block of the reset structure contains nested conditional logic, "
                          "which is not supported for this extraction pattern.")
                    return None  
                else:
                    # separation accepted
                    analysis_mode = 'SEPARATE_RESET_AND_MAIN'
                    reset_signal_name = temp_reset_name
                    is_reset_active_high = temp_is_active_high
                    reset_logic_block = if_stmt.true_statement
                    main_logic_block = else_block_node
    
    if analysis_mode == 'TREAT_AS_WHOLE':
        print("--- DEBUG: No standard reset structure found. Treating entire block as main logic. ---")
        main_logic_block = always_node.statement
        reset_logic_block = None
        reset_signal_name = None
    elif analysis_mode == 'SEPARATE_RESET_AND_MAIN':
        print("--- DEBUG: Standard reset structure DETECTED. Separating reset/main logic. ---")
        pass
        
    # safety check
    if main_logic_block is None: 
        print(f"DEBUG: Slice Error at line {always_node.lineno} - Could not identify the main data path block.")
        return None

    # === step B: extract assignments for data flow tracing ===
    all_assigns_in_data_path = [s for s in extract_procedural_assigns(main_logic_block)
                                if isinstance(s, NonblockingSubstitution)]
    all_assigns_in_always = [s for s in extract_procedural_assigns(always_node.statement)
                             if isinstance(s, NonblockingSubstitution)]
    
    # === step 1: locate core computation ===
    core_stmt = next((s for s in all_assigns_in_data_path if getattr(s.right, 'var', s.right) is core_op_node), None)
    if not core_stmt: 
        print("DEBUG: Slice Error - Could not locate the core computation in the main data path.")
        return None
    core_output_signal = getattr(core_stmt.left.var, 'name', None)
    if not core_output_signal: 
        print("DEBUG: Slice Error - Could not determine the output signal of the core computation.")
        return None

    # === step 2: data flow tracing ===
    # a. [Core Diff] decompose A*B@C expression tree
    times_node, c_node = (core_op_node.left, core_op_node.right) if isinstance(core_op_node.left, Times) else \
                         (core_op_node.right, core_op_node.left) if isinstance(core_op_node.right, Times) else (None, None)
    if times_node is None: return None

    a_node, b_node = times_node.left, times_node.right

    # b. verify operand types
    ALLOWED_OPERANDS = (Identifier, Pointer, IntConst, FloatConst)
    all_operand_nodes = [a_node, b_node, c_node]
    if not all(isinstance(op, ALLOWED_OPERANDS) for op in all_operand_nodes):
        print("DEBUG: Pattern mismatch - Unsupported operand types.")
        return None
    
    # c. ensure not pure constant/parameter expression
    is_any_signal = any(isinstance(op, (Identifier, Pointer)) and get_base_name(op) not in param_dict for op in all_operand_nodes)
    if not is_any_signal:
        print("DEBUG: Pattern mismatch - All operands are constants/parameters.")
        return None

    # --- step 2.5: data flow analysis and parameter identification ---
    all_backward_stmts = set()
    slice_boundary_inputs = set()
    referenced_params = set()

    def process_operand(node, max_depth):
        nonlocal all_backward_stmts, slice_boundary_inputs, referenced_params
        if isinstance(node, (Identifier, Pointer)):
            base_name = get_base_name(node)
            if base_name in param_dict:
                referenced_params.add(base_name)
                return
            traced_stmts, boundary_inputs = trace_backward_single(
                start_node=node, max_depth=max_depth,
                all_assigns_in_data_path=all_assigns_in_data_path
            )
            all_backward_stmts.update(traced_stmts)
            slice_boundary_inputs.update(boundary_inputs)

    print("\n--- Main Process: Starting iterative backward tracing for A*B@C ---")
    # set different depths for each operand based on hardware limits
    # A/B are multiplier inputs, typically up to 2 register stages
    process_operand(a_node, max_depth=2)
    process_operand(b_node, max_depth=2)
    # C is post-adder input, needs to align with multiplier latency (~2-3 stages)
    # plus its own register (CREG), so depth of 3 is a safe upper bound
    process_operand(c_node, max_depth=1)

    MAX_FORWARD_DEPTH = 1
    forward_stmts, slice_boundary_outputs = trace_forward(
        start_signal_name=core_output_signal,
        max_depth=MAX_FORWARD_DEPTH,
        all_assigns_in_data_path=all_assigns_in_data_path
    )
    
    pipeline_stmts = {core_stmt}
    pipeline_stmts.update(all_backward_stmts)
    pipeline_stmts.update(forward_stmts)
     
    print("\n--- DEBUG: Final Trace Results ---")
    print(f"  - Boundary Inputs : {sorted(list(slice_boundary_inputs))}")
    print(f"  - Boundary Outputs: {sorted(list(slice_boundary_outputs))}")
    print(f"  - Total statements to slice: {len(pipeline_stmts)}")
    print("----------------------------------\n")
    
    
    # === step 3: boundary analysis and dependencies ===
    module_node = always_node.parent

    # check for following assign
    following_assign = None
    if hasattr(module_node, 'items'):
        try:
            idx = module_node.items.index(always_node)
            if idx + 1 < len(module_node.items):
                next_item = module_node.items[idx + 1]
                if isinstance(next_item, Assign):
                    following_assign = next_item
        except ValueError:
            pass

    if following_assign:
        # use assign LHS as boundary output
        slice_boundary_outputs = {getattr(following_assign.left.var, 'name', None)}
        print(f"DEBUG: Found following assign. Boundary output: {slice_boundary_outputs}")
    else:
        # fallback to forward trace boundary
        MAX_FORWARD_DEPTH = 1
        forward_stmts, slice_boundary_outputs = trace_forward(
            start_signal_name=core_output_signal,
            max_depth=MAX_FORWARD_DEPTH,
            all_assigns_in_data_path=all_assigns_in_data_path
        )
        print(f"DEBUG: No following assign. Boundary outputs from forward trace: {slice_boundary_outputs}")

    # --- dependency calculation ---
    stmts_to_keep = [s for s in all_assigns_in_always if s not in pipeline_stmts]
    slice_internal_lhs = {name for s in pipeline_stmts 
                        if hasattr(s.left, 'var') and (name := getattr(s.left.var, 'name', None)) is not None}

    dependency_outputs = set()
    all_other_logic = [s for s in stmts_to_keep] + [i for i in module_node.items if isinstance(i, Assign)]
    for stmt in all_other_logic:
        dependency_outputs.update(slice_internal_lhs.intersection(extract_identifier_names(stmt.right)))
    print("--- DEBUG:dependency_outputs ---")
    print(dependency_outputs)

    # --- step 4: build renaming map ---
    rename_map = {}
    if following_assign:
        # only include assign LHS in all_outputs if found
        all_outputs = {getattr(following_assign.left.var, 'name', None)}
    else:
        # otherwise use boundary outputs + dependencies
        all_outputs = slice_boundary_outputs.union(dependency_outputs)

    print(f"DEBUG: Final all_outputs: {all_outputs}")
    
    for sig_name in sorted(list(slice_boundary_inputs)): rename_map[sig_name] = f"{sig_name}_in"
    for sig_name in sorted(list(all_outputs)): rename_map[sig_name] = f"{sig_name}_out"
    
    all_ports_or_params = slice_boundary_inputs.union(all_outputs)
    all_ports_or_params.add(clk_name)
    if reset_signal_name: all_ports_or_params.add(reset_signal_name)
    all_ports_or_params.update(referenced_params)
    
    internal_signals = slice_internal_lhs - all_ports_or_params

    for sig_name in sorted(list(internal_signals)): rename_map[sig_name] = f"{sig_name}_internal"
    
    rename_map[clk_name] = clk_name
    if reset_signal_name: rename_map[reset_signal_name] = reset_signal_name
    for param_name in referenced_params:
        rename_map[param_name] = param_name

    print("--- DEBUG:rename_map ---")
    print(rename_map)
    
    # === step 5: build new module details using mapping ===
    internal_reg_decls, port_info = [], {}
    for sig_name in sorted(list(internal_signals)):
        new_name = rename_map[sig_name]; info = signal_dict.get(sig_name, {})
        width_str = f"[{info.get('width', 1) - 1}:0]" if info.get('width', 1) > 1 else ""
        signed_str = "signed" if info.get('signed', False) else ""
        internal_reg_decls.append(f"reg {signed_str} {width_str} {new_name};".replace("  ", " "))
    
    _add_port_to_info(port_info, rename_map[clk_name], clk_name, 'input', signal_dict)
    
    if reset_signal_name:
         _add_port_to_info(port_info, 
                          reset_signal_name,      # new port name (unchanged)
                          reset_signal_name,      # original signal name
                          'input',                
                          signal_dict)                    
    
    for sig in sorted(list(slice_boundary_inputs)): _add_port_to_info(port_info, rename_map[sig], sig, 'input', signal_dict)
    for sig in sorted(list(all_outputs)): _add_port_to_info(port_info, rename_map[sig], sig, 'output', signal_dict, is_reg=(sig in slice_internal_lhs))
    print("--- DEBUG @ extract_pipeline_slice: STAGE 5 BLUEPRINT ---") 
    print("Internal REG Declarations for New Module:")
    if not internal_reg_decls:
        print("    (None)")
    else:
        for decl in internal_reg_decls:
            print(f"    {decl}")
            
    print(" Port Info for New Module (pretty-printed):")
    if not port_info:
        print("    (None)")
    else:
        print(port_info)
        

    # === step 6: build final result dict ===
    # 1. prepare renaming tool
    renamer = RenamingCodegen(rename_map)

    # 2. build following assign
    follow_assign_lines = []
    if following_assign is not None:  
        follow_assign_lines.append(renamer.visit(following_assign))

    # 3. build data path code body
    data_path_lines = []
    for stmt in sorted(list(pipeline_stmts), key=lambda s: s.lineno):
        stmt_code = renamer.visit(stmt)
        data_path_lines.append(f"  {stmt_code}")

    # 4. build reset logic (preserve original)
    reset_path_lines = []
    if reset_logic_block:
        signals_to_reset_in_new_module = slice_internal_lhs
        all_reset_assigns = extract_procedural_assigns(reset_logic_block)
        for stmt in all_reset_assigns:
            lhs_name = getattr(stmt.left.var,'name',None)
            if lhs_name in signals_to_reset_in_new_module:
                reset_path_lines.append(f"  {renamer.visit(stmt)}")

    # 5. assemble always block (preserve original)
    if reset_logic_block and reset_path_lines:
        renamed_clk = renamer.visit(Identifier(clk_name))
        renamed_reset = renamer.visit(Identifier(reset_signal_name))
        
        # build sensitivity list
        sensitivity_parts = [f"{clk_edge} {renamed_clk}"]
        original_has_reset = any(
            isinstance(sens, Sens) and getattr(sens.sig, 'name', None)==reset_signal_name
            for sens in getattr(always_node.sens_list,'list',[])
        )
        if not original_has_reset and reset_signal_name:
            reset_edge = "posedge" if is_reset_active_high else "negedge"
            sensitivity_parts.append(f"{reset_edge} {renamed_reset}")
        sensitivity_list = " or ".join(sensitivity_parts)
        
        reset_condition = f"if ({renamed_reset})" if is_reset_active_high else f"if (!{renamed_reset})"

        always_lines = [f"always @({sensitivity_list}) begin",
                        f"  {reset_condition} begin"]
        always_lines.extend(['    ' + line.lstrip() for line in reset_path_lines])
        always_lines.append("  end else begin")
        always_lines.extend(['    ' + line.lstrip() for line in data_path_lines])
        always_lines.append("  end")
        always_lines.append("end")
        always_block_code = "\n".join(always_lines)
    else:
        always_block_code = _build_always_block(pipeline_stmts, clk_edge, clk_name, renamer)

    # 6. assemble final module code body
    new_module_code_body = "\n".join( [always_block_code] + follow_assign_lines)


    print(f"DEBUG: Final new_module_code_body:\n{new_module_code_body}")
        
    
    # use AST pruning for remaining_logic_body
    
    remaining_logic_body = ""
    
    # a. build complete prune list from slice_internal_lhs
    # includes all relevant reset and data path logic
    all_assigns_in_always = extract_procedural_assigns(always_node.statement)
    final_stmts_to_prune = {
        s for s in all_assigns_in_always
        if hasattr(s.left, 'var') and getattr(s.left.var, 'name', None) in slice_internal_lhs
    }
    
    assign_to_remove = None
    if following_assign is not None:
        assign_to_remove = following_assign
        final_stmts_to_prune.add(following_assign)  # add to debug set
        assign_lineno_to_remove = assign_to_remove.lineno  # get line number
        print(f"[INFO] Added the assign statement following the always block to the pruning target: L{assign_lineno_to_remove}")
    else:
        print("[INFO] No assign statement found immediately following the always block. No extra pruning needed.")

    # ======================================================
    # b. debug output for pruned statements
    # ======================================================
    print("\n--- DEBUG: Final Statements to Prune (Complete List) ---")
    if not final_stmts_to_prune:
        print("  -> (List is empty)")
    else:
        print(f"  -> Found {len(final_stmts_to_prune)} statements to be extracted/pruned:")
        for stmt in sorted(list(final_stmts_to_prune), key=lambda s: getattr(s, "lineno", 0)):
            try:
                stmt_code = codegen.visit(stmt)
                print(f"     - L{stmt.lineno}: {stmt_code}")
            except Exception:
                print(f"     - L{getattr(stmt, 'lineno', '?')}: [Unprintable statement]")
    print("----------------------------------------------------------\n")

    # ======================================================
    # c. statements to keep
    # ======================================================
    stmts_to_keep = [s for s in all_assigns_in_always if s not in final_stmts_to_prune]


    
    # c. prune AST using line numbers
    linenos_to_prune = {s.lineno for s in final_stmts_to_prune}
    # deep copy AST
    remaining_ast = copy.deepcopy(always_node.statement)

    # recursively delete matched line numbers
    def prune_ast_recursively_by_lineno(node, linenos):
        if node is None:
            return None

        # remove statement if line number matches
        if hasattr(node, "lineno") and node.lineno in linenos:
            return None

        # block node
        if isinstance(node, Block):
            new_statements = []
            for stmt in node.statements:
                pruned_stmt = prune_ast_recursively_by_lineno(stmt, linenos)
                if pruned_stmt is not None:
                    new_statements.append(pruned_stmt)
            node.statements = new_statements
            if not node.statements:
                return None
            return node

        # if statement
        if isinstance(node, IfStatement):
            node.true_statement = prune_ast_recursively_by_lineno(node.true_statement, linenos)
            node.false_statement = prune_ast_recursively_by_lineno(node.false_statement, linenos)
            if node.true_statement is None and node.false_statement is None:
                return None
            return node

        # case statement
        if isinstance(node, CaseStatement):
            new_caselist = []
            for case in node.caselist:
                pruned_stmt = prune_ast_recursively_by_lineno(case.statement, linenos)
                if pruned_stmt is not None:
                    case.statement = pruned_stmt
                    new_caselist.append(case)
            node.caselist = new_caselist
            if not node.caselist:
                return None
            return node

        # traverse children
        for child in node.children():
            prune_ast_recursively_by_lineno(child, linenos)
        return node

    pruned_ast = prune_ast_recursively_by_lineno(remaining_ast, linenos_to_prune)

    # generate final code
    if pruned_ast is not None:
        temp_remaining_always = Always(always_node.sens_list, pruned_ast)
        remaining_logic_body = codegen.visit(temp_remaining_always)
    else:
        remaining_logic_body = ""
    return {
        'status': 'success',
        'new_dsp_module': {
            'port_info': port_info,
            'internal_reg_decls': internal_reg_decls, 
            'code_body': new_module_code_body,
            'referenced_params': list(referenced_params)
        },
        'remaining_logic': {
            'code_body': remaining_logic_body,
            'stmts': stmts_to_keep,
            'assign': assign_lineno_to_remove
        },
        'wires_to_declare': all_outputs,
        'declarations_to_remove': internal_signals,
        'original_always_node': always_node,
    }


def handle_always_mult_op(container_node, op_node, module, mod_name, modified_filename,
                                    signal_dict, file_lines, out_dir,  param_dict,
                                   file_extraction_dict, source_name, module_instance_counts=None):
    """
    1. Extract entire module if it contains only one always block with reasonable pipeline depth.
    2. Extract individual multiplications if multiple always blocks exist.
    """
    """
    [New Version - takes op_node]
    Process a complex operation (op_node) in an always block.
    """
    module_name = module.name
    
    if is_always_sequential(container_node):
        if is_valid_pipelined_mult_op_module(module, container_node):
            try:
                print(f"Module {module.name} is a valid pipelined multiplication structure. Extracting the entire module.")

                # --- perform extraction ---
                start_line = module.lineno - 1
                end_line = find_end_line(file_lines, start_line)
                module_lines = file_lines[start_line:end_line + 1]

                # write mod_name
                with open(os.path.join(out_dir, f"{mod_name}.v"), 'w') as f:
                    f.writelines(module_lines)

                modified_lines = remove_module_from_lines(file_lines, module.name)
                with open(os.path.join(out_dir, modified_filename), 'w') as f:
                    f.writelines(modified_lines)

                # --- update status and return success ---
                line_num = op_node.lineno

                # 2. build dict to store
                update_data = {
                    'dsp_module_name': mod_name,
                    'source_function': source_name, # source_name is passed as argument
                    'dsp_count': module_instance_counts.get(module.name, 1) * 1
                }

                # 3. directly modify the passed "global" dict
                # update value at corresponding line number
                if line_num in file_extraction_dict:
                    file_extraction_dict[line_num] = update_data
                else:
                    # update value at corresponding line number
                    file_extraction_dict[line_num] = update_data

                # 4. return boolean success flag
                return True

            except Exception as e:
                print(f"Error during entire module extraction: {e}")
                return False
        else:

            # --- strategy 2: extract (A*B)@C logic core ---
            print(f"Extracting multiply-add operation from module {module_name}...")
            print(container_node)
            
            slice_result = extract_mult_op_pipeline_slice(
                container_node, 
                op_node, 
                signal_dict, 
                param_dict, 
                codegen
            )
            # 2. check if slice was successful
            if slice_result and slice_result['status'] == 'success':
                try:
                    # --- a. generate new sequential DSP module ---
                    dsp_info = slice_result['new_dsp_module']
                    
                    # use mod_name (from caller) to ensure uniqueness
                    new_mod_filepath = os.path.join(out_dir, f"{mod_name}.v")
                
                    new_mod_code = generate_module_code(
                        mod_name, 
                        dsp_info['code_body'], 
                        dsp_info['port_info'],
                        internal_reg_decls=dsp_info.get('internal_reg_decls'),
                        # get referenced parameters from slice result
                        referenced_params=dsp_info.get('referenced_params', []),
                        # pass down global param dict
                        param_dict=param_dict
                    )
                    print(new_mod_code)
                    with open(new_mod_filepath, 'w') as f:
                        f.write(new_mod_code)
                    print(f"     Successfully generated a new reusable pipelined DSP module: {mod_name}.v")
                    
            
                    # --- b. prepare wires and instance ---
                    
                     # 1. fresh declarations for kept registers
                    # identified by analyzing remaining logic output
                    stmts_to_keep = slice_result['remaining_logic']['stmts']
                    regs_to_keep = {
                        name for s in stmts_to_keep 
                        if hasattr(s.left, 'var') and (name := getattr(s.left.var, 'name', None)) is not None
                    }
                    regs_to_declare_str = ""
                    for reg_name in sorted(list(regs_to_keep)):
                        info = signal_dict.get(reg_name, {})
                        width_val = info.get('width')
                        width_str = "" # default to scalar

                        # only process if width is a valid integer
                        if isinstance(width_val, int):
                            if width_val > 1:
                                # generate [N-1:0] for multi-bit signals
                                width_str = f"[{width_val - 1}:0]"
                            else: 
                                # generate [0:0] explicitly for 1-bit signals
                                width_str = "[0:0]"
                        

                        signed_str = "signed" if info.get('signed', False) else ""
                        decl_parts = ["reg", signed_str, width_str, reg_name]
                        regs_to_declare_str += "    " + " ".join(filter(None, decl_parts)).replace("  ", " ") + ";\n"
                    # 2. declare new wires
                    wires_to_declare = slice_result.get('wires_to_declare', set())
                    wires_to_declare_str = ""
                    assign_lineno_to_remove = slice_result['remaining_logic'].get('assign', None)
         
                    for reg_name in sorted(list(wires_to_declare)):
                        signal_info = signal_dict.get(reg_name, {})
                        # skip if already a port
                        is_already_a_port = signal_info.get('type') in ['Input', 'Output', 'Inout']
                        if not is_already_a_port:
                            width_val = signal_info.get('width')
                            width_str = f"[{width_val - 1}:0]" if isinstance(width_val, int) and width_val > 1 else ""
                            signed_str = "signed" if signal_info.get('signed', False) else ""
                            
                            # determine based on assign_lineno_to_remove
                            decl_type = "wire" if assign_lineno_to_remove is not None else "reg"
                            wires_to_declare_str += "    " + " ".join(filter(None, [decl_type, signed_str, width_str, reg_name])) + ";\n"


                    # 3. prepare instance code
                    instance_name = f"{mod_name}_inst"
                    instance_code = create_instance_code(mod_name, instance_name, dsp_info['port_info'])
                    instance_code_indented = f"    {instance_code}\n"
                    
                    # 4. prepare remaining logic code
                    remaining_code = slice_result['remaining_logic']['code_body']

                    remaining_code_indented = "\n".join(["    " + line for line in remaining_code.splitlines()]) + "\n" if remaining_code else ""
                    # --- c. perform code modification ---
                    original_always_node = slice_result['original_always_node']
                    start_line_of_always = original_always_node.lineno
                    end_line_of_always = find_end_of_block_lineno(original_always_node, file_lines)

                    modified_lines = []
                    lines_to_skip_for_always = set(range(start_line_of_always - 1, end_line_of_always))
                    
                    for i, line in enumerate(file_lines):
                        # rule 1: remove old always block
                        if i in lines_to_skip_for_always:
                            continue
                        
                        # rule 2: remove or comment out assign_to_remove
                        if assign_lineno_to_remove is not None and i == assign_lineno_to_remove - 1:
                            # comment out directly
                            modified_lines.append(f"// Removed assign by tool: {line.strip()}\n")
                            continue

                        # rule 3: remove output signal declarations
                        # get actual signal names for output ports
                        output_signals = set()
                        if 'port_info' in dsp_info:
                            for port_name, info in dsp_info['port_info'].items():
                                if info.get('direction') == 'output':
                                    # get actual connected signal name
                                    actual_signal = info.get('connect_to')
                                    if actual_signal:
                                        output_signals.add(actual_signal)
                                        print(f"     Marked output signal '{actual_signal}' for declaration removal.")
                        
                        # accurately match signal declaration lines
                        if output_signals:  
                            declaration_pattern = re.compile(
                                r'^\s*(reg|wire)\s+(?:signed\s+)?(?:\[\d+:\d+\]\s+)?(\w+)\s*;.*$'
                            )
                            
                            match = declaration_pattern.match(line.strip())
                            if match:
                                decl_type, signal_name = match.groups()
                                if signal_name in output_signals:
                                    modified_lines.append(f"// Removed {decl_type} declaration for output signal '{signal_name}' by tool\n")
                                    print(f"     Removed output signal declaration: {decl_type} {signal_name}")
                                    continue

                        # rule 4: preserve other lines
                        modified_lines.append(line)
                    # --- d. insert generated code ---
                    insert_pos_index = start_line_of_always - 1
                    
                    lines_to_insert = []
                    # insertion order: kept regs -> new wires -> instance -> remaining logic
                    if regs_to_declare_str: lines_to_insert.append("\n    // --- Registers kept in main module (re-declared by tool) ---\n" + regs_to_declare_str)
                    if wires_to_declare_str: lines_to_insert.append("\n    // --- Wires connecting to the new module ---\n" + wires_to_declare_str)
                    if instance_code_indented: lines_to_insert.append("\n    // --- Instantiation of the extracted module ---\n" + instance_code_indented)
                    if remaining_code_indented: lines_to_insert.append("\n    // --- Remaining logic from the original always block ---\n" + remaining_code_indented)
                    
                    final_modified_lines = modified_lines[:insert_pos_index] + lines_to_insert + modified_lines[insert_pos_index:]

                    # --- e. write modified file ---
                    with open(os.path.join(out_dir, modified_filename), 'w') as f:
                        f.writelines(final_modified_lines)
                        
                    print("     Successfully executed pipeline slicing and code replacement.")

                    # --- f. update status and return success ---
                    line_num = op_node.lineno

                    # 2. build dict to store
                    update_data = {
                        'dsp_module_name': mod_name,
                        'source_function': source_name, # source_name is passed as argument
                        'dsp_count': module_instance_counts.get(module.name, 1) * 1
                    }

                    # 3.directly modify the passed "global" dict
                    # update value at corresponding line number
                    if line_num in file_extraction_dict:
                        file_extraction_dict[line_num] = update_data
                    else:
                        # update value at corresponding line number
                        file_extraction_dict[line_num] = update_data

                    # 4. return boolean success flag
                    return True

                except Exception as e:
                    print(f"     Fatal error occurred during pipeline slicing and reconstruction: {e}")
                    import traceback
                    traceback.print_exc()
                    return False
            else:
                print("     Pipeline slicing failed. Skipping to ensure consistency.")
                return False
    else:
        print("Combinational logic always block detected...")
        if is_pure_combinational_module(module, container_node,op_node):
            try:
                print(f"Module {module.name} is a pure combinational logic structure. Extracting the entire module.")
                
                # --- perform extraction ---
                start_line = module.lineno - 1
                end_line = find_end_line(file_lines, start_line)
                module_lines = file_lines[start_line:end_line + 1]

                # write mod_name
                with open(os.path.join(out_dir, f"{mod_name}.v"), 'w') as f:
                    f.writelines(module_lines)

                modified_lines = remove_module_from_lines(file_lines, module.name)
                with open(os.path.join(out_dir, modified_filename), 'w') as f:
                    f.writelines(modified_lines)

                # --- update status and return success ---
                line_num = op_node.lineno

                # 2. build dict to store
                update_data = {
                    'dsp_module_name': mod_name,
                    'source_function': source_name, # source_name is passed as argument
                    'dsp_count': module_instance_counts.get(module.name, 1) * 1
                }

                # 3. directly modify the passed "global" dict
                # update value at corresponding line number
                if line_num in file_extraction_dict:
                    file_extraction_dict[line_num] = update_data
                else:
                    # update value at corresponding line number
                    file_extraction_dict[line_num] = update_data

                # 4. return boolean success flag
                return True

            except Exception as e:
                print(f"Error occurred during entire module extraction: {e}")
                return False
        else: # mixed logic, not pure
            # --- strategy 2: fallback to core logic extraction ---
            print(f"Module {module.name} is a mixed structure. Extracting core logic.")
            try:
                all_assignments = extract_procedural_assigns(container_node.statement)
                target_assign_stmt = None
                for stmt in all_assignments:
                    # is_node_in_tree checks if op_node is in stmt's subtree
                    if is_node_in_tree(op_node, stmt):
                        target_assign_stmt = stmt
                        break
                
                if target_assign_stmt is None:
                    print("     Error: Could not locate the assignment statement containing the core operation in the always @(*) block.")
                    return False


                # 2. call extraction function designed for combinational logic
                #    renames with suffixes and returns port_info and code_body
                extraction_result = extract_mult_add_info(
                    target_assign_stmt, 
                    signal_dict, 
                    param_dict, 
                    codegen
                )
                
                if not extraction_result:
                    print("     Node does not match A*B@C pattern. Skipping.")
                    return False

                port_info = extraction_result['port_info']
                code_body = extraction_result['code_body']
                params_to_add = extraction_result.get('referenced_params', [])

                # 3. generate new pure combinational submodule, passing parameters
                new_mod_code = generate_module_code(
                    mod_name, 
                    code_body, 
                    port_info,
                    # pass parameter info to code generator
                    referenced_params=params_to_add,
                    param_dict=param_dict
                )
                with open(os.path.join(out_dir, f"{mod_name}.v"), 'w') as f:
                    f.write(new_mod_code)
                print(f"     Successfully extracted combinational core module: {mod_name}.v")

                # 4. prepare wires and instance
                # a. dynamically find output port's original connection target (for wire naming)
                output_port_info = next((p_info for p_info in port_info.values() if p_info.get('direction') == 'output'), None)
                if not output_port_info:
                        print("     Error: Output port information not found in the extraction results.")
                        return False
                
                intermediate_wire_name = f"{output_port_info['connect_to']}_core_out"
                wire_width = output_port_info['width']
                wire_signed_str = "signed" if output_port_info['signed'] else ""
                wire_decl_str = f"    reg {wire_signed_str} {wire_width} {intermediate_wire_name};\n".replace("  ", " ")

                # b. update port_info to connect new module's output to the new wire
                output_port_key = next((p_name for p_name, p_info in port_info.items() if p_info.get('direction') == 'output'), None)
                port_info[output_port_key]['connect_to'] = intermediate_wire_name

                # c. create instance code
                instance_name = f"{mod_name}_inst"
                instance_code = create_instance_code(mod_name, instance_name, port_info)
                instance_code_indented = f"    {instance_code}\n"
                
                # 5. perform code modification
                #    single-line replacement instead of replacing the entire always block
                
                # a. insert wire and instance declarations before always block
                modified_lines = list(file_lines) # create copy
                insert_pos_index = container_node.lineno - 1
                modified_lines.insert(insert_pos_index, instance_code_indented)
                modified_lines.insert(insert_pos_index, wire_decl_str)
                
                # b. replace original expression with the new intermediate wire
                line_to_modify_index = target_assign_stmt.lineno - 1
                # adjust index due to inserted lines
                line_to_modify_index_after_insertion = line_to_modify_index + 2
 
                
                # get original line to preserve indentation and comments
                original_line = file_lines[line_to_modify_index]
                indentation = original_line[:len(original_line) - len(original_line.lstrip())]

                # get exact original LHS
                original_lhs_str = codegen.visit(target_assign_stmt.left).strip()
                
                # determine assignment operator
                assignment_op = "=" if isinstance(target_assign_stmt, BlockingSubstitution) else "<="

                # rebuild line with new wire
                new_line = f"{indentation}{original_lhs_str} {assignment_op} {intermediate_wire_name};\n"
                
                # precisely replace old line
                modified_lines[line_to_modify_index_after_insertion] = new_line

                # 6. write file and return
                with open(os.path.join(out_dir, modified_filename), 'w') as f:
                    f.writelines(modified_lines)
                
                # update global stats
                line_num = op_node.lineno

                # 2. build dict to store
                update_data = {
                    'dsp_module_name': mod_name,
                    'source_function': source_name, # source_name is passed as argument
                    'dsp_count': module_instance_counts.get(module.name, 1) * 1
                }

                # 3.  directly modify the passed "global" dict
                # update value at corresponding line number
                if line_num in file_extraction_dict:
                    file_extraction_dict[line_num] = update_data
                else:
                    # update value at corresponding line number
                    file_extraction_dict[line_num] = update_data

                # 4. return boolean success flag
                return True

            except Exception as e:
                print(f"     Error occurred while processing combinational always block: {e}")
                import traceback
                traceback.print_exc()
                return False
        

def off_on_on(verilog_path, ast, signal_dict, param_dict, out_dir, 
             module_extraction_counters, file_extraction_dict, 
             processed_nodes, instance_hierarchy=None, top_module_name=None, 
             module_instance_counts=None,matched_line_numbers=None, **kwargs):
    """
    Check if assignments match the (A * B) @ C pattern.
    @ can be Plus, Minus, And, Or, Xor, etc.
    """
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
    print("================ Entering (A * B) @ C Check ================")
    # original filename
    base_name = os.path.splitext(os.path.basename(verilog_path))[0]

    original_copy_path = os.path.join(out_dir, f"{base_name}_original.v")
    os.makedirs(out_dir, exist_ok=True)
    copy_success = safe_file_copy(verilog_path, original_copy_path)
    if not copy_success:
        print(f"Warning: Failed to copy file {verilog_path}. Proceeding anyway.")

    try:
        description = ast.description
        with open(verilog_path, 'r', encoding='utf-8') as f:
            original_file_lines = f.readlines()
    except Exception as e:
        return 
    
 
    for module in description.definitions:          
        if not isinstance(module, ModuleDef):
            continue


        mul_op_items = {}
        
        for item in module.items:
            # 1. process top-level assign
            if isinstance(item, Assign):
                process_mult_op_in_statement(
                    item, 
                    mul_op_items, 
                    signal_dict, 
                    param_dict, 
                    container_node=item, 
                    processed_nodes=processed_nodes, 
                    matched_line_numbers=matched_line_numbers)

            # 2. process always block
            elif isinstance(item, Always):
                procedural_assigns = extract_procedural_assigns(item.statement)
                for assign_stmt in procedural_assigns:
                    # check procedural assignments
                    process_mult_op_in_statement(
                        assign_stmt, 
                        mul_op_items, 
                        signal_dict, 
                        param_dict, 
                        container_node=item, 
                        processed_nodes=processed_nodes, 
                        matched_line_numbers=matched_line_numbers)
            # 3. process generate block
            elif isinstance(item, GenerateStatement):
                # a. find all deeply nested Assign and Always nodes
                nodes_in_generate = find_nodes_in_generate(item)
                
                # b. iterate found nodes
                for node in nodes_in_generate:
                    
                    # c. dispatch by node type
                    if isinstance(node, Assign):
                        # use the Assign container itself as container_node
                        process_mult_op_in_statement(
                            node,             # stmt_node is Assign itself
                            mul_op_items, 
                            signal_dict, 
                            param_dict, 
                            container_node=node, # <-- container_node is Assign itself
                            processed_nodes=processed_nodes, 
                            matched_line_numbers=matched_line_numbers)
                        
                    elif isinstance(node, Always):
                        # use the Always container itself as container_node
                        procedural_assigns = extract_procedural_assigns(node.statement)
                        for assign_stmt in procedural_assigns:
                            process_mult_op_in_statement(
                                assign_stmt,      # stmt_node is assignment inside Always
                                mul_op_items, 
                                signal_dict, 
                                param_dict, 
                                container_node=node, # <-- container_node is the Always block
                                processed_nodes=processed_nodes, 
                                matched_line_numbers=matched_line_numbers)
           
            # 4. process function
            elif isinstance(item, Function):
                # function body is a statement
                # reuse extract_procedural_assigns to find assignments
                # note: return statement is special in AST
                # skip return statements for now
                print(f"DEBUG: Found a function definition '{item.name}', analysis for it is not yet fully implemented.")

            # 5. process task
            elif isinstance(item, Task):
                # task body is also a statement
                procedural_assigns = extract_procedural_assigns(item.statement, ...)
                for assign_stmt in procedural_assigns:
                    # find mults in task, context unknown
                    process_mult_op_in_statement(assign_stmt, ..., container_node=item)
                       
        if not mul_op_items:
            continue
        
        else:
            
            # container_node stores the parent assign/always
            for container_node, times_node_list in mul_op_items.items():
                for op_node in times_node_list:
                    
                    success = False
                    source_name_for_dict = "off_on_on"    
                    # combinational assign
                    if isinstance(container_node, Assign):
                        #print(module_mark_dict[module.name])
                        #print(mod_name)
                        
                        extraction_index = module_extraction_counters.get(module.name, 0)
                        mod_name = f"{module.name}_module{extraction_index}"
                        modified_filename = f"{module.name}_modified{extraction_index}.v"
                        success = handle_assign_mult_op(
                            container_node=container_node,
                            op_node=op_node,
                            module=module,
                            mod_name=mod_name,
                            modified_filename=modified_filename,
                            signal_dict=signal_dict,
                            file_lines=original_file_lines,
                            out_dir=out_dir,
                            param_dict=param_dict,
                            file_extraction_dict=file_extraction_dict,
                            source_name=source_name_for_dict,
                            module_instance_counts=module_instance_counts
                        )
                        
                        #print("----------------")
                        #print(module_mark_dict[module.name])

                    # always block
                    elif isinstance(container_node, Always):
                        
                        extraction_index = module_extraction_counters.get(module.name, 0)
                        mod_name = f"{module.name}_module{extraction_index}"
                        modified_filename = f"{module.name}_modified{extraction_index}.v"
                        
                        success = handle_always_mult_op(
                            container_node=container_node,
                            op_node=op_node,
                            module=module,
                            mod_name=mod_name,
                            modified_filename=modified_filename,
                            signal_dict=signal_dict,
                            file_lines=original_file_lines,
                            out_dir=out_dir,
                            param_dict=param_dict,
                            file_extraction_dict=file_extraction_dict,
                            source_name=source_name_for_dict,
                            module_instance_counts=module_instance_counts
                        )
                        
                    
                    if success:
                        print(f"--- SUCCESS: Processing for {codegen.visit(op_node)} succeeded. Incrementing counters. ---")
                        processed_nodes.add(op_node)
                        module_extraction_counters[module.name] += 1


                    else:
                        print(f"--- INFO: Processing for {codegen.visit(op_node)} failed or was skipped. Counters not incremented. ---")