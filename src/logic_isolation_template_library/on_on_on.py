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



def process_add_mult_op_in_statement(stmt_node, mul_op_items, signal_dict, param_dict, container_node=None, processed_nodes=None, matched_line_numbers=None):
    """
    Check if the assignment statement strictly matches the ((A+/-B)*C) @ D pattern.
    @ represents {+, -, &, |, ^}
    """
    if stmt_node.lineno not in matched_line_numbers:
        return  
    if processed_nodes is None:
        processed_nodes = set()
    
    if id(stmt_node) in processed_nodes:
        return
    
    # 1. get and check top-level operation (must be post-processing @)
    rhs_node = None
    if isinstance(stmt_node, (BlockingSubstitution, NonblockingSubstitution)):
        rhs_node = stmt_node.right
        
    elif isinstance(stmt_node, Assign):
        if hasattr(stmt_node, 'rightlist') and \
           hasattr(stmt_node.rightlist, 'list') and \
           len(stmt_node.rightlist.list) == 1:
            rhs_node = stmt_node.rightlist.list[0]
        
        elif hasattr(stmt_node, 'right') and stmt_node.right is not None:
            rhs_node = stmt_node.right
            
    if rhs_node is None:
        return
    
    top_level_op = rhs_node.var if isinstance(rhs_node, Rvalue) else rhs_node
    ALLOWED_POST_OPS = (Plus, Minus, And, Or, Xor)
    if not isinstance(top_level_op, ALLOWED_POST_OPS):
        return

    # 2. find multiplication node (*) among children of @
    # a. decompose @ to find * and D
    times_node, d_node = (top_level_op.left, top_level_op.right) if isinstance(top_level_op.left, Times) else \
                         (top_level_op.right, top_level_op.left) if isinstance(top_level_op.right, Times) else (None, None)
    if times_node is None: return

    pre_adder_node, c_node = (times_node.left, times_node.right) if isinstance(times_node.left, (Plus, Minus)) else \
                             (times_node.right, times_node.left) if isinstance(times_node.right, (Plus, Minus)) else (None, None)
    if pre_adder_node is None: return

    a_node, b_node = pre_adder_node.left, pre_adder_node.right

    # 3. verify all operand types at once
    ALLOWED_OPERANDS = (Identifier, Pointer, IntConst, FloatConst)
    all_operand_nodes = [a_node, b_node, c_node, d_node]
    if not all(isinstance(op, ALLOWED_OPERANDS) for op in all_operand_nodes):
        return

    # strict degradation pattern checks
    operands = {'A': a_node, 'B': b_node, 'C': c_node, 'D': d_node}
    operand_values = {}
    is_all_const_or_param = True

    for name, node in operands.items():
        val = eval_expr(node, param_dict)
        operand_values[name] = val
        if val is None: 
            is_all_const_or_param = False
            
    if is_all_const_or_param:
        print(f"Rejected ((A+B)*C)+D - All operands are constants.")
        return

    # zero degradation check
    for name, val in operand_values.items():
        if val == 0:
            print(f"Rejected ((A+B)*C)+D - Operand '{name}' is zero.")
            return

    # multiply by one degradation check
    if operand_values.get('C') == 1:
        print(f"Rejected ((A+B)*C)+D - Multiplier 'C' is one.")
        return

    # 4. check bitwidths of A, B, C, D
    a_width = get_operand_width(a_node, signal_dict, param_dict)
    b_width = get_operand_width(b_node, signal_dict, param_dict)
    c_width = get_operand_width(c_node, signal_dict, param_dict)
    d_width = get_operand_width(d_node, signal_dict, param_dict)


    if a_width is None or b_width is None or c_width is None or d_width is None:
        return

    # apply DSP48E2 bitwidth rules 
    if not (a_width <= 27 and b_width <= 27): return
    if not (c_width <= 27): return
    if not (d_width <= 48): return
        
    print("Passed ((A+B)*C)+D pattern - All checks are compatible with DSP48E2.")
    
    # 6. update dictionary if all checks passed
    key_node = container_node if container_node is not None else stmt_node
    if key_node not in mul_op_items:
        mul_op_items[key_node] = []
        
    mul_op_items[key_node].append(top_level_op)

def extract_add_mult_op_info(container_node, signal_dict, param_dict, codegen):
    """
    Generalized ((A+/-B)*C)@D pattern extraction function.
    Supports signals, parameters, and constants as operands.
    """
    try:
        # 1. analyze container_node to find LHS and top-level RHS operations
        if not isinstance(container_node, (Assign, BlockingSubstitution, NonblockingSubstitution)):
            return None
        lhs_base_name = list(extract_identifier_names(container_node.left))[0]
        if not lhs_base_name: return None
        top_level_op = getattr(container_node.right, 'var', container_node.right)
       
        # 2. top-level operation must be post-processing @
        ALLOWED_POST_OPS = (Plus, Minus, And, Or, Xor)
        if not isinstance(top_level_op, ALLOWED_POST_OPS):
            return None
            
        # 3. decompose @ to find * and D
        times_node, d_node = (top_level_op.left, top_level_op.right) if isinstance(top_level_op.left, Times) else \
                             (top_level_op.right, top_level_op.left) if isinstance(top_level_op.right, Times) else \
                             (None, None)
        if times_node is None:
            return None
        
        if not isinstance(d_node, (Identifier, Pointer, IntConst, FloatConst)):
            return None

        # 4. decompose * to find pre-adder (+/-) and C
        ALLOWED_PRE_OPS = (Plus, Minus)
        pre_adder_node, c_node = (times_node.left, times_node.right) if isinstance(times_node.left, ALLOWED_PRE_OPS) else \
                                 (times_node.right, times_node.left) if isinstance(times_node.right, ALLOWED_PRE_OPS) else \
                                 (None, None)
        if pre_adder_node is None:
            return None
        
        if not isinstance(c_node, (Identifier, Pointer, IntConst, FloatConst)):
            return None

        # 5. extract A, B nodes
        a_node, b_node = pre_adder_node.left, pre_adder_node.right
        
        if not (isinstance(a_node, (Identifier, Pointer, IntConst, FloatConst)) and 
                isinstance(b_node, (Identifier, Pointer, IntConst, FloatConst))):
            return None
        
        # 6. extract details of all operands and identify parameters
        port_info = {}
        rebuild_map = {}
        referenced_params = set()

        def process_operand(node, node_role):
            """
            Generalized operand processing.
            """
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
                    print(f"Warning: {node_role} '{base_name}' not found in dictionaries")

            elif isinstance(node, (IntConst, FloatConst)):
                pass
            else:
                print(f"Warning: Unsupported operand type for {node_role}")

        process_operand(a_node, 'A')
        process_operand(b_node, 'B')
        process_operand(c_node, 'C')
        process_operand(d_node, 'D')

        # 7. extract output info
        lhs_conn_str = codegen.visit(container_node.left).strip()
        output_width = signal_dict.get(lhs_base_name, {}).get('width')
        is_p_signed = signal_dict.get(lhs_base_name, {}).get('signed', False)
        if output_width is None: 
            return None

        # 8. build port_info and code_body
        output_width_str = f"[{output_width - 1}:0]" if output_width > 1 else ""
        p_port_name = f"{lhs_base_name}_out"
        
        port_info[p_port_name] = {
            'direction': 'output', 
            'width': output_width_str, 
            'connect_to': lhs_conn_str, 
            'signed': is_p_signed,
            'type': 'wire' 
        }
        
        rebuilder = RenamingCodegen(rebuild_map)
        rebuilt_rhs = rebuilder.visit(top_level_op)
        code_body = f"assign {p_port_name} = {rebuilt_rhs};"
        
        # 9. return all info
        result = {
            'port_info': port_info,
            'code_body': code_body,
            'referenced_params': list(referenced_params)
        }
        
        return result
        
    except Exception as e:
        print(f"Error during ((A+/-B)*C)+D info extraction: {e}")
        import traceback
        traceback.print_exc()
        return None
    
    
def handle_assign_add_mult_op(container_node, op_node, module, mod_name, modified_filename,
                                    signal_dict, file_lines, out_dir, param_dict,file_extraction_dict,
                                     source_name, module_instance_counts=None):
    """
    Handle a complex pre-adder multiplication operation in a top-level assign statement.
    """
    try:
        # case 1: module contains only one complex assign, extract entire module
        behavioral_items = [
            item for item in module.items 
            if isinstance(item, (Assign, Always, Initial, Instance)) 
        ]
        if len(behavioral_items) == 1 and behavioral_items[0] == container_node:
            print(f"Extracting entire module {module.name} (single complex assign).")
            
            start_line = module.lineno - 1
            end_line = find_end_line(file_lines, start_line)
            module_lines = file_lines[start_line:end_line + 1]

            with open(os.path.join(out_dir, f"{mod_name}.v"), 'w') as f:
                f.writelines(module_lines)

            modified_lines = remove_module_from_lines(file_lines, module.name)
            with open(os.path.join(out_dir, modified_filename), 'w') as f:
                f.writelines(modified_lines)
            
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

        # fallback to finer-grained processing
        is_inside_for, dsp_count = get_assign_count(container_node, param_dict)

        # case 2: assign is inside a for-loop
        if is_inside_for:
            if dsp_count > 0:
                print(f"Assign is inside a for-loop. Estimated DSP count: {dsp_count}")
                for_loop_node = find_innermost_for_node(container_node)
        
                if for_loop_node is None:
                    print("Error: is_inside_for is True, but no for-loop node found.")
                    return False 

                # extract logic info for a single iteration
                original_assign_str = codegen.visit(container_node)
                transformed_body, port_info, loop_var = extract_loop_logic(
                    original_assign_str, 
                    for_loop_node, 
                    container_node, 
                    signal_dict,
                )
                
                transformed_body = extraction_result["transformed_body"]
                port_info = extraction_result["port_info"]
                loop_var = extraction_result["loop_var"]
                params_to_add = extraction_result["referenced_params"]

                # generate new reusable submodule
                mod_code = generate_module_code(
                    mod_name, 
                    transformed_body, 
                    port_info,
                    referenced_params=params_to_add,
                    param_dict=param_dict
                )
                with open(os.path.join(out_dir, f"{mod_name}.v"), 'w') as f:
                    f.write(mod_code)
                
                # construct generate for loop block
                
                instance_name_in_loop = f"{mod_name}_inst"
                instance_code = create_instance_code(
                    mod_name, 
                    instance_name_in_loop, 
                    port_info, 
                    loop_var
                )
                
                gen_block_name = f"gen_{mod_name}"

                pre_str = codegen.visit(for_loop_node.pre).strip().rstrip(';')
                cond_str = codegen.visit(for_loop_node.cond).strip()
                post_str = codegen.visit(for_loop_node.post).strip().rstrip(';')
                gen_for_loop_header = f"for ({pre_str}; {cond_str}; {post_str})"
                
                replacement_code = (
                    f"generate\n"
                    f"  // Original for-loop logic extracted into module '{mod_name}'\n"
                    f"  {gen_for_loop_header} begin : {gen_block_name}\n"
                    f"    {instance_code}\n"
                    f"  end\n"
                    f"endgenerate"
                )
                
                # replace original code
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

                line_num = op_node.lineno

                update_data = {
                    'dsp_module_name': mod_name,
                    'source_function': source_name, 
                    'dsp_count': dsp_count * module_instance_counts.get(module.name, 1) * 1
                }

                if line_num in file_extraction_dict:
                    file_extraction_dict[line_num] = update_data
                else:
                    file_extraction_dict[line_num] = update_data

                return True
                
            else: 
                print("Assign in for-loop, but loop count failed to parse. Skipping.")
                return False 
        
        # case 3: simple non-loop assign
        else:
            print("Assign is not in a for-loop. Extracting single mult-add core.")
            
            extraction_result = extract_add_mult_info(
                container_node,
                signal_dict, 
                param_dict, 
                codegen
            )
            
            if not extraction_result:
                print("Node does not match A+B pattern. Skipping.")
                return False

            print("Successfully identified A+B pattern.")
            
            port_info = extraction_result['port_info']
            code_body = extraction_result['code_body']
            params_to_add = extraction_result.get('referenced_params', []) 

            mod_code = generate_module_code(
                mod_name, 
                code_body, 
                port_info,
                referenced_params=params_to_add,
                param_dict=param_dict
            )
            with open(os.path.join(out_dir, f"{mod_name}.v"), 'w') as f:
                f.write(mod_code)
            print(f"Generated module successfully: {mod_name}.v")

            instance_name = f"{mod_name}_inst"
            instance_code = create_instance_code(mod_name, instance_name, extraction_result['port_info'])
            print(f"Generated instantiation code: {instance_code}")
            
            start_line = container_node.lineno
            modified_lines = replace_code_block_by_lines(file_lines, start_line, start_line, instance_code)
            with open(os.path.join(out_dir, modified_filename), 'w') as f:
                f.writelines(modified_lines)
            
            line_num = op_node.lineno

            update_data = {
                'dsp_module_name': mod_name,
                'source_function': source_name, 
                'dsp_count':1 * module_instance_counts.get(module.name, 1)
            }

            if line_num in file_extraction_dict:
                file_extraction_dict[line_num] = update_data
            else:
                file_extraction_dict[line_num] = update_data

            return True
            

    except Exception as e:
        print(f"Error during handle_assign_pre_adder_mult_op for node at line {container_node.lineno}: {e}")
        import traceback
        traceback.print_exc()
        return False


def is_simple_always_full_dsp(always_node):
    """
    Check if always block matches a simple pipeline structure.
    """
    if not hasattr(always_node, 'sens_list') or not always_node.sens_list:
        return False, None 
    
    is_timing = any(
        isinstance(sens, Sens) and sens.type in ('posedge', 'negedge')
        for sens in always_node.sens_list.list
    )
    if not is_timing:
        return False, None 
    
    if not hasattr(always_node, 'statement') or not isinstance(always_node.statement, Block):
        return False, None 
        
    statements = always_node.statement.statements if hasattr(always_node.statement, 'statements') else []
    if not statements:
        return False, None 

    # find unique ((A+/-B)*C)@D computation statement
    core_op_stmt = None 
    
    def is_full_dsp_pattern(node):
        ALLOWED_POST_OPS = (Plus, Minus, And, Or, Xor)
        if not isinstance(node, ALLOWED_POST_OPS): return False
        
        times_node = node.left if isinstance(node.left, Times) else node.right if isinstance(node.right, Times) else None
        d_node = node.right if isinstance(node.left, Times) else node.left
        if not times_node or not isinstance(d_node, (Identifier, Pointer)): return False
        
        ALLOWED_PRE_OPS = (Plus, Minus)
        pre_adder_node = times_node.left if isinstance(times_node.left, ALLOWED_PRE_OPS) else \
                         times_node.right if isinstance(times_node.right, ALLOWED_PRE_OPS) else None
        c_node = times_node.right if isinstance(times_node.left, ALLOWED_PRE_OPS) else times_node.left
        if not pre_adder_node or not isinstance(c_node, (Identifier, Pointer)): return False
        
        # ensure pre-adder inputs are also simple signals
        if not isinstance(pre_adder_node.left, (Identifier, Pointer)) or \
           not isinstance(pre_adder_node.right, (Identifier, Pointer)):
            return False
            
        return True

    pipeline_stmts = []
    for stmt in statements:
        if not isinstance(stmt, NonblockingSubstitution): return False, None
        rhs = getattr(stmt.right, 'var', stmt.right)
        if is_full_dsp_pattern(rhs):
            if core_op_stmt is not None:
                return False, None
            core_op_stmt = stmt
        elif isinstance(rhs, (Identifier, Pointer)):
            pipeline_stmts.append(stmt)
        else:
            return False, None
                
    if core_op_stmt is None:
        return False, None
        
    core_op_node = getattr(core_op_stmt.right, 'var', core_op_stmt.right)

    # build and verify signal whitelist

    related_signals = {name for name in extract_identifier_names(core_op_node)}
    core_op_output_name = codegen.visit(core_op_stmt.left)
    related_signals.add(core_op_output_name)
    
    newly_added = True
    while newly_added:
        newly_added = False
        for stmt in pipeline_stmts:
            lhs_name = codegen.visit(stmt.left)
            rhs_name = codegen.visit(stmt.right)
            
            lhs_is_related = lhs_name in related_signals
            rhs_is_related = rhs_name in related_signals

            # bidirectional trace
            if rhs_is_related and not lhs_is_related:
                related_signals.add(lhs_name)
                newly_added = True
            
            if lhs_is_related and not rhs_is_related:
                related_signals.add(rhs_name)
                newly_added = True

    all_lhs_in_always = {codegen.visit(s.left) for s in statements}
    
    if not all_lhs_in_always.issubset(related_signals):
        return False, None

    print("Passed all checks for is_simple_always_full_dsp.")
    return True, core_op_node
                
    
    

def is_valid_pipelined_pre_adder_mult_op_module(module, always_node):
    """
    Check if module matches a complex pipeline structure with a pre-adder.
    """
    always_count = 0
    ALLOWED_TOP_LEVEL_TYPES = (Always, Assign, Decl, GenerateStatement) 
    for item in module.items:
        if not isinstance(item, ALLOWED_TOP_LEVEL_TYPES):
            return False
        if isinstance(item, Always):
            always_count += 1
    
    if always_count != 1: return False
        
    the_only_always_node = [item for item in module.items if isinstance(item, Always)][0]
    if the_only_always_node is not always_node: return False

    all_assign_stmts = [item for item in module.items if isinstance(item, Assign)]
    for assign_stmt in all_assign_stmts:
        rhs_node = None
        if hasattr(assign_stmt, 'right') and hasattr(assign_stmt.right, 'var'):
             rhs_node = assign_stmt.right.var
        
        if not isinstance(rhs_node, (Identifier, Pointer)):
            return False
     
    is_simple, core_op_node = is_simple_always_full_dsp(always_node)
    if not is_simple:
        return False
        
    # decompose core operation
    try:
        times_node, d_node = (core_op_node.left, core_op_node.right) if isinstance(core_op_node.left, Times) else \
                             (core_op_node.right, core_op_node.left)
        pre_adder_node, c_node = (times_node.left, times_node.right) if isinstance(times_node.left, (Plus, Minus)) else \
                                 (times_node.right, times_node.left)
        a_node, b_node = pre_adder_node.left, pre_adder_node.right
    except AttributeError:
        return False

    if not all(isinstance(n, (Identifier, Pointer)) for n in [a_node, b_node, c_node, d_node]):
        return False

    # calculate and verify pipeline depth
    depth_map = get_input_pipeline_depths(always_node)
    
    a_depth = depth_map.get(a_node.name, 0)
    b_depth = depth_map.get(b_node.name, 0)
    c_depth = depth_map.get(c_node.name, 0)
    d_depth = depth_map.get(d_node.name, 0)

    # A/B pipeline depth <= DSP A/D port internal register limit (1-2)
    if a_depth > 2 or b_depth > 2: return False

    # C pipeline depth <= DSP B port internal register limit (2)
    if c_depth > 2: return False

    # D pipeline depth <= DSP C port internal register limit (1) + alignment delay
    if d_depth > 3: return False

    # output pipeline depth <= DSP output register limit (1, PREG)
    if not validate_output_pipeline_depth(always_node, depth_map, core_op_node, max_output_depth=1):
         return False

    return True

def decompose_dsp_pattern(op_node, signal_dict, param_dict, codegen):
    """
    Lightweight decomposer: only breaks down expression and returns operand info.
    Supports (A+/-B)*C and ((A+/-B)*C)@D.
    """
    try:
        a_node, b_node, c_node, d_node = None, None, None, None
        pre_adder_node, times_node, post_adder_node = None, None, None

        ALLOWED_POST_OPS = (Plus, Minus, And, Or, Xor)
        ALLOWED_PRE_OPS = (Plus, Minus)

        if isinstance(op_node, Times): 
            times_node = op_node
            post_adder_node = None 
            pre_adder_node, c_node = (times_node.left, times_node.right) if isinstance(times_node.left, ALLOWED_PRE_OPS) else \
                                     (times_node.right, times_node.left) if isinstance(times_node.right, ALLOWED_PRE_OPS) else (None, None)
        elif isinstance(op_node, ALLOWED_POST_OPS): 
            post_adder_node = op_node
            times_node, d_node = (post_adder_node.left, post_adder_node.right) if isinstance(post_adder_node.left, Times) else \
                                 (post_adder_node.right, post_adder_node.left) if isinstance(post_adder_node.right, Times) else (None, None)
            if times_node:
                pre_adder_node, c_node = (times_node.left, times_node.right) if isinstance(times_node.left, ALLOWED_PRE_OPS) else \
                                         (times_node.right, times_node.left) if isinstance(times_node.right, ALLOWED_PRE_OPS) else (None, None)
        
        if not pre_adder_node or not c_node: return None 
        
        a_node, b_node = pre_adder_node.left, pre_adder_node.right
        
        all_nodes = [a_node, b_node, c_node]
        if d_node: all_nodes.append(d_node)
        if not all(isinstance(n, (Identifier, Pointer)) for n in all_nodes): return None
            
        def get_op_info(node):
            if node is None: return None
            base_name = list(extract_identifier_names(node))[0]
            info = signal_dict.get(base_name, {})
            width = get_expr_width(node, signal_dict, param_dict)
            if width is None: raise ValueError(f"Could not get width for {base_name}")
            return {'name': base_name, 'conn_str': codegen.visit(node).strip(),
                    'width': width, 'signed': info.get('signed', False)}
        
        result = {
            'A': get_op_info(a_node), 'B': get_op_info(b_node), 'C': get_op_info(c_node),
            'pre_op': '+' if isinstance(pre_adder_node, Plus) else '-'
        }
        if d_node:
            result['D'] = get_op_info(d_node)
            result['post_op'] = '+' if isinstance(post_adder_node, Plus) else '-' 
        
        return result

    except Exception as e:
        return None


def extract_preadd_mult_op_pipeline_slice(always_node, core_op_node, signal_dict, param_dict, codegen):
    """
    Extract pipeline slice from complex sequential always blocks.
    Uses line number mapping for accurate AST pruning.
    """
    
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
        
        port_info[new_port_name] = {
            'connect_to': original_signal_name,
            'direction': direction,
            'width': width_str,
            'is_array': False,
            'signed': is_signed,
            'is_reg': is_reg,
            'type': 'reg'  
        }


    clk_name, clk_edge = None, None
    if hasattr(always_node, 'sens_list') and hasattr(always_node.sens_list, 'list'):
        for sens in always_node.sens_list.list:
            if isinstance(sens, Sens) and sens.type in ('posedge', 'negedge'):
                if isinstance(sens.sig, Identifier):
                    clk_name, clk_edge = sens.sig.name, sens.type
                    break
    if not clk_name:
        return None
    
    main_logic_block = None
    reset_logic_block = None
    reset_signal_name = None
    is_reset_active_high = True

    POSSIBLE_RESET_NAMES = {'reset', 'rst', 'reset_n', 'rst_n'}
    
    analysis_mode = 'TREAT_AS_WHOLE'

    if isinstance(always_node.statement, Block) and \
        len(always_node.statement.statements) == 1 and \
        isinstance(always_node.statement.statements[0], IfStatement):
        
        if_stmt = always_node.statement.statements[0]
        
        if if_stmt.false_statement is not None:
            condition_node = if_stmt.cond
            temp_reset_name = None
            temp_is_active_high = None

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
                    return None  
                else:
                    analysis_mode = 'SEPARATE_RESET_AND_MAIN'
                    reset_signal_name = temp_reset_name
                    is_reset_active_high = temp_is_active_high
                    reset_logic_block = if_stmt.true_statement
                    main_logic_block = else_block_node
    
    if analysis_mode == 'TREAT_AS_WHOLE':
        main_logic_block = always_node.statement
        reset_logic_block = None
        reset_signal_name = None
    elif analysis_mode == 'SEPARATE_RESET_AND_MAIN':
        pass
        
    if main_logic_block is None: 
        return None
    
    all_assigns_in_data_path = [s for s in extract_procedural_assigns(main_logic_block)
                                if isinstance(s, NonblockingSubstitution)]
    
    all_assigns_in_always = [s for s in extract_procedural_assigns(always_node.statement)
                             if isinstance(s, NonblockingSubstitution)]
    

    core_stmt = next((s for s in all_assigns_in_data_path if getattr(s.right, 'var', s.right) is core_op_node), None)
    if not core_stmt: 
        return None

    core_inputs = extract_identifier_names(core_op_node)
    core_output_signal = getattr(core_stmt.left.var, 'name', None)
    if not core_output_signal: 
        return None

    # AST pattern match and decompose 
    if not isinstance(core_op_node, Times):
        return None

    times_node = core_op_node
    left_operand = times_node.left
    right_operand = times_node.right

    pre_adder_node = None
    other_operand = None

    if isinstance(left_operand, (Plus, Minus)):
        pre_adder_node = left_operand
        other_operand = right_operand
    elif isinstance(right_operand, (Plus, Minus)):
        pre_adder_node = right_operand  
        other_operand = left_operand
    else:
        return None

    a_node = pre_adder_node.left
    b_node = pre_adder_node.right
    c_node = other_operand 

    ALLOWED_OPERANDS = (Identifier, Pointer, IntConst, FloatConst)
    all_operand_nodes = [a_node, b_node, c_node]
    if not all(isinstance(op, ALLOWED_OPERANDS) for op in all_operand_nodes):
        return None

    is_any_signal = any(isinstance(op, (Identifier, Pointer)) and get_base_name(op) not in param_dict for op in all_operand_nodes)
    if not is_any_signal:
        return None

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

    process_operand(a_node, max_depth=1)
    process_operand(b_node, max_depth=1)
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

    
    module_node = always_node.parent

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
        slice_boundary_outputs = {getattr(following_assign.left.var, 'name', None)}
    else:
        MAX_FORWARD_DEPTH = 1
        forward_stmts, slice_boundary_outputs = trace_forward(
            start_signal_name=core_output_signal,
            max_depth=MAX_FORWARD_DEPTH,
            all_assigns_in_data_path=all_assigns_in_data_path
        )

    stmts_to_keep = [s for s in all_assigns_in_always if s not in pipeline_stmts]
    slice_internal_lhs = {name for s in pipeline_stmts 
                        if hasattr(s.left, 'var') and (name := getattr(s.left.var, 'name', None)) is not None}

    dependency_outputs = set()
    all_other_logic = [s for s in stmts_to_keep] + [i for i in module_node.items if isinstance(i, Assign)]
    for stmt in all_other_logic:
        dependency_outputs.update(slice_internal_lhs.intersection(extract_identifier_names(stmt.right)))

    rename_map = {}
    if following_assign:
        all_outputs = {getattr(following_assign.left.var, 'name', None)}
    else:
        all_outputs = slice_boundary_outputs.union(dependency_outputs)

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

    internal_reg_decls, port_info = [], {}
    
    for sig_name in sorted(list(internal_signals)):
        new_name = rename_map[sig_name]; info = signal_dict.get(sig_name, {})
        width_str = f"[{info.get('width', 1) - 1}:0]" if info.get('width', 1) > 1 else ""
        signed_str = "signed" if info.get('signed', False) else ""
        internal_reg_decls.append(f"reg {signed_str} {width_str} {new_name};".replace("  ", " "))
    
    _add_port_to_info(port_info, rename_map[clk_name], clk_name, 'input', signal_dict)
    
    if reset_signal_name:
         _add_port_to_info(port_info, 
                          reset_signal_name,     
                          reset_signal_name,      
                          'input',                
                          signal_dict)                    
    
    for sig in sorted(list(slice_boundary_inputs)): _add_port_to_info(port_info, rename_map[sig], sig, 'input', signal_dict)
    for sig in sorted(list(all_outputs)): _add_port_to_info(port_info, rename_map[sig], sig, 'output', signal_dict, is_reg=(sig in slice_internal_lhs))

    renamer = RenamingCodegen(rename_map)

    follow_assign_lines = []
    if following_assign is not None:  
        follow_assign_lines.append(renamer.visit(following_assign))

    data_path_lines = []
    for stmt in sorted(list(pipeline_stmts), key=lambda s: s.lineno):
        stmt_code = renamer.visit(stmt)
        data_path_lines.append(f"  {stmt_code}")

    reset_path_lines = []
    if reset_logic_block:
        signals_to_reset_in_new_module = slice_internal_lhs
        all_reset_assigns = extract_procedural_assigns(reset_logic_block)
        for stmt in all_reset_assigns:
            lhs_name = getattr(stmt.left.var,'name',None)
            if lhs_name in signals_to_reset_in_new_module:
                reset_path_lines.append(f"  {renamer.visit(stmt)}")

    if reset_logic_block and reset_path_lines:
        renamed_clk = renamer.visit(Identifier(clk_name))
        renamed_reset = renamer.visit(Identifier(reset_signal_name))
        
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

    new_module_code_body = "\n".join( [always_block_code] + follow_assign_lines)

    remaining_logic_body = ""
    
    all_assigns_in_always = extract_procedural_assigns(always_node.statement)
    final_stmts_to_prune = {
        s for s in all_assigns_in_always
        if hasattr(s.left, 'var') and getattr(s.left.var, 'name', None) in slice_internal_lhs
    }
    
    assign_to_remove = None
    if following_assign is not None:
        assign_to_remove = following_assign
        final_stmts_to_prune.add(following_assign) 
        assign_lineno_to_remove = assign_to_remove.lineno  

    stmts_to_keep = [s for s in all_assigns_in_always if s not in final_stmts_to_prune]

    linenos_to_prune = {s.lineno for s in final_stmts_to_prune}
    remaining_ast = copy.deepcopy(always_node.statement)

    def prune_ast_recursively_by_lineno(node, linenos):
        if node is None:
            return None

        if hasattr(node, "lineno") and node.lineno in linenos:
            return None

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

        if isinstance(node, IfStatement):
            node.true_statement = prune_ast_recursively_by_lineno(node.true_statement, linenos)
            node.false_statement = prune_ast_recursively_by_lineno(node.false_statement, linenos)
            if node.true_statement is None and node.false_statement is None:
                return None
            return node

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

        for child in node.children():
            prune_ast_recursively_by_lineno(child, linenos)
        return node

    pruned_ast = prune_ast_recursively_by_lineno(remaining_ast, linenos_to_prune)

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

  
def handle_always_add_mult(container_node, op_node, module, mod_name, modified_filename,
                                 signal_dict, file_lines, out_dir, param_dict, file_extraction_dict, source_name, module_instance_counts=None):
    """
    Handle a complex multiply-add operation in an always block.
    """
    module_name = module.name
    
    if is_always_sequential(container_node):
        if is_valid_pipelined_add_mult_module(module, container_node):
            try:
                print(f"Extracting entire module {module.name} (valid pipelined structure)")

                start_line = module.lineno - 1
                end_line = find_end_line(file_lines, start_line)
                module_lines = file_lines[start_line:end_line + 1]

                with open(os.path.join(out_dir, f"{mod_name}.v"), 'w') as f:
                    f.writelines(module_lines)

                modified_lines = remove_module_from_lines(file_lines, module.name)
                with open(os.path.join(out_dir, modified_filename), 'w') as f:
                    f.writelines(modified_lines)

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
                print(f"Error during entire module extraction: {e}")
                return False
        else:
            
            print(f"Extracting operation core from module {module_name}...")
            
            slice_result = extract_preadd_mult_pipeline_slice(
                container_node, 
                op_node, 
                signal_dict, 
                param_dict, 
                codegen
            )
            if slice_result and slice_result['status'] == 'success':
                try:
                    dsp_info = slice_result['new_dsp_module']
                    
                    new_mod_filepath = os.path.join(out_dir, f"{mod_name}.v")
                
                    new_mod_code = generate_module_code(
                        mod_name, 
                        dsp_info['code_body'], 
                        dsp_info['port_info'],
                        internal_reg_decls=dsp_info.get('internal_reg_decls'),
                        referenced_params=dsp_info.get('referenced_params', []),
                        param_dict=param_dict
                    )
                    with open(new_mod_filepath, 'w') as f:
                        f.write(new_mod_code)
                    
                    stmts_to_keep = slice_result['remaining_logic']['stmts']
                    regs_to_keep = {
                        name for s in stmts_to_keep 
                        if hasattr(s.left, 'var') and (name := getattr(s.left.var, 'name', None)) is not None
                    }
                    regs_to_declare_str = ""
                    for reg_name in sorted(list(regs_to_keep)):
                        info = signal_dict.get(reg_name, {})
                        width_val = info.get('width')
                        width_str = "" 

                        if isinstance(width_val, int):
                            if width_val > 1:
                                width_str = f"[{width_val - 1}:0]"
                            else: 
                                width_str = "[0:0]"
                        
                        signed_str = "signed" if info.get('signed', False) else ""
                        decl_parts = ["reg", signed_str, width_str, reg_name]
                        regs_to_declare_str += "    " + " ".join(filter(None, decl_parts)).replace("  ", " ") + ";\n"
                    wires_to_declare = slice_result.get('wires_to_declare', set())
                    wires_to_declare_str = ""
                    assign_lineno_to_remove = slice_result['remaining_logic'].get('assign', None)
         
                    for reg_name in sorted(list(wires_to_declare)):
                        signal_info = signal_dict.get(reg_name, {})
                        is_already_a_port = signal_info.get('type') in ['Input', 'Output', 'Inout']
                        if not is_already_a_port:
                            width_val = signal_info.get('width')
                            width_str = f"[{width_val - 1}:0]" if isinstance(width_val, int) and width_val > 1 else ""
                            signed_str = "signed" if signal_info.get('signed', False) else ""
                            
                            decl_type = "wire" if assign_lineno_to_remove is not None else "reg"
                            wires_to_declare_str += "    " + " ".join(filter(None, [decl_type, signed_str, width_str, reg_name])) + ";\n"


                    instance_name = f"{mod_name}_inst"
                    instance_code = create_instance_code(mod_name, instance_name, dsp_info['port_info'])
                    instance_code_indented = f"    {instance_code}\n"
                    
                    remaining_code = slice_result['remaining_logic']['code_body']

                    remaining_code_indented = "\n".join(["    " + line for line in remaining_code.splitlines()]) + "\n" if remaining_code else ""
                    original_always_node = slice_result['original_always_node']
                    start_line_of_always = original_always_node.lineno
                    end_line_of_always = find_end_of_block_lineno(original_always_node, file_lines)

                    modified_lines = []
                    lines_to_skip_for_always = set(range(start_line_of_always - 1, end_line_of_always))
                    
                    for i, line in enumerate(file_lines):
                        if i in lines_to_skip_for_always:
                            continue
                        
                        if assign_lineno_to_remove is not None and i == assign_lineno_to_remove - 1:
                            modified_lines.append(f"// Removed assign by tool: {line.strip()}\n")
                            continue

                        output_signals = set()
                        if 'port_info' in dsp_info:
                            for port_name, info in dsp_info['port_info'].items():
                                if info.get('direction') == 'output':
                                    actual_signal = info.get('connect_to')
                                    if actual_signal:
                                        output_signals.add(actual_signal)
                        
                        if output_signals:  
                            declaration_pattern = re.compile(
                                r'^\s*(reg|wire)\s+(?:signed\s+)?(?:\[\d+:\d+\]\s+)?(\w+)\s*;.*$'
                            )
                            
                            match = declaration_pattern.match(line.strip())
                            if match:
                                decl_type, signal_name = match.groups()
                                if signal_name in output_signals:
                                    modified_lines.append(f"// Removed {decl_type} declaration for output signal '{signal_name}' by tool\n")
                                    continue

                        modified_lines.append(line)
                    insert_pos_index = start_line_of_always - 1
                    
                    lines_to_insert = []
                    if regs_to_declare_str: lines_to_insert.append("\n    // --- Registers kept in main module (re-declared by tool) ---\n" + regs_to_declare_str)
                    if wires_to_declare_str: lines_to_insert.append("\n    // --- Wires connecting to the new module ---\n" + wires_to_declare_str)
                    if instance_code_indented: lines_to_insert.append("\n    // --- Instantiation of the extracted module ---\n" + instance_code_indented)
                    if remaining_code_indented: lines_to_insert.append("\n    // --- Remaining logic from the original always block ---\n" + remaining_code_indented)
                    
                    final_modified_lines = modified_lines[:insert_pos_index] + lines_to_insert + modified_lines[insert_pos_index:]

                    with open(os.path.join(out_dir, modified_filename), 'w') as f:
                        f.writelines(final_modified_lines)
                        
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
                    print(f"Fatal error during pipeline slicing and reconstruction: {e}")
                    import traceback
                    traceback.print_exc()
                    return False
            else:
                print("Pipeline slicing failed. Skipping.")
                return False
    else:
        if is_pure_combinational_module(module, op_node,container_node):
            try:
                print(f"Extracting entire module {module.name} (pure combinational)")
                
                start_line = module.lineno - 1
                end_line = find_end_line(file_lines, start_line)
                module_lines = file_lines[start_line:end_line + 1]

                with open(os.path.join(out_dir, f"{mod_name}.v"), 'w') as f:
                    f.writelines(module_lines)

                modified_lines = remove_module_from_lines(file_lines, module.name)
                with open(os.path.join(out_dir, modified_filename), 'w') as f:
                    f.writelines(modified_lines)

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
                print(f"Error during entire module extraction: {e}")
                return False
        else: 
            print(f"Module {module.name} is mixed combinational. Extracting core logic.")
            try:
                all_assignments = extract_procedural_assigns(container_node.statement)
                target_assign_stmt = None
                for stmt in all_assignments:
                    if is_node_in_tree(op_node, stmt):
                        target_assign_stmt = stmt
                        break
                
                if target_assign_stmt is None:
                    print("Could not locate assignment containing core operation in always @(*).")
                    return False


                extraction_result = extract_add_mult_info(
                    target_assign_stmt, 
                    signal_dict, 
                    param_dict, 
                    codegen
                )
                
                if not extraction_result:
                    print("Node does not match ((A+/-B)*C)@D pattern. Skipping.")
                    return False, 0

                port_info = extraction_result['port_info']
                code_body = extraction_result['code_body']

                referenced_params = extraction_result.get('referenced_params', [])

                new_mod_code = generate_module_code(
                    mod_name, 
                    code_body, 
                    port_info,
                    referenced_params=referenced_params,  
                    param_dict=param_dict                 
                )
                with open(os.path.join(out_dir, f"{mod_name}.v"), 'w') as f:
                    f.write(new_mod_code)

                output_port_info = next((p_info for p_info in port_info.values() if p_info.get('direction') == 'output'), None)
                if not output_port_info:
                        print("Error: Output port info not found in extraction result.")
                        return False, 0
                
                intermediate_wire_name = f"{output_port_info['connect_to']}_core_out"
                wire_width = output_port_info['width']
                wire_signed_str = "signed" if output_port_info['signed'] else ""
                wire_decl_str = f"    reg {wire_signed_str} {wire_width} {intermediate_wire_name};\n".replace("  ", " ")

                output_port_key = next((p_name for p_name, p_info in port_info.items() if p_info.get('direction') == 'output'), None)
                port_info[output_port_key]['connect_to'] = intermediate_wire_name

                instance_name = f"{mod_name}_inst"
                instance_code = create_instance_code(mod_name, instance_name, port_info)
                instance_code_indented = f"    {instance_code}\n"
                
                modified_lines = list(file_lines) 

                insert_pos_index = container_node.lineno - 1
                modified_lines.insert(insert_pos_index, instance_code_indented)
                modified_lines.insert(insert_pos_index, wire_decl_str)

                line_to_modify_index = target_assign_stmt.lineno - 1
                line_to_modify_index_after_insertion = line_to_modify_index + 2

                original_line = file_lines[line_to_modify_index]
                indentation = original_line[:len(original_line) - len(original_line.lstrip())]

                original_lhs_str = codegen.visit(target_assign_stmt.left).strip()

                assignment_op = "=" if isinstance(target_assign_stmt, BlockingSubstitution) else "<="

                new_line = f"{indentation}{original_lhs_str} {assignment_op} {intermediate_wire_name};\n"

                modified_lines[line_to_modify_index_after_insertion] = new_line

                with open(os.path.join(out_dir, modified_filename), 'w') as f:
                    f.writelines(modified_lines)
                
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
                print(f"Error processing combinational always block: {e}")
                import traceback
                traceback.print_exc()
                return False
  
def on_on_off(verilog_path, ast, signal_dict, param_dict, out_dir, 
             module_extraction_counters,  file_extraction_dict, 
             processed_nodes, instance_hierarchy=None, top_module_name=None, 
             module_instance_counts=None,matched_line_numbers=None, **kwargs):
    """
    Check if assignments match the (A +/- B) * C pattern.
    """
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
    print("--- Starting (A +/- B) * C Check ---")
    
    base_name = os.path.splitext(os.path.basename(verilog_path))[0]
    original_copy_path = os.path.join(out_dir, f"{base_name}_original.v")
    os.makedirs(out_dir, exist_ok=True)
    copy_success = safe_file_copy(verilog_path, original_copy_path)
    if not copy_success:
        print(f"Warning: Failed to copy {verilog_path}. Proceeding anyway.")
    try:
        description = ast.description
        with open(verilog_path, 'r', encoding='utf-8') as f:
            original_file_lines = f.readlines()
    except Exception as e:
        return 
    
    for module in description.definitions:
            
        if not isinstance(module, ModuleDef):
            continue


        add_mult_items = {}
        
        for item in module.items:
            if isinstance(item, Assign):
                process_add_mult_in_statement(
                    item, 
                    add_mult_items, 
                    signal_dict, 
                    param_dict, 
                    container_node=item, 
                    processed_nodes=processed_nodes, 
                    matched_line_numbers=matched_line_numbers)

            elif isinstance(item, Always):
                procedural_assigns = extract_procedural_assigns(item.statement)
                for assign_stmt in procedural_assigns:
                    process_add_mult_in_statement(
                        assign_stmt, 
                        add_mult_items, 
                        signal_dict, 
                        param_dict, 
                        container_node=item,
                        processed_nodes=processed_nodes, 
                        matched_line_numbers=matched_line_numbers)
            
            elif isinstance(item, GenerateStatement):
                nodes_in_generate = find_nodes_in_generate(item)
                for node in nodes_in_generate:
                    if isinstance(node, Assign):
                        process_add_mult_in_statement(
                            node,             
                            add_mult_items, 
                            signal_dict, 
                            param_dict, 
                            container_node=node, 
                            processed_nodes=processed_nodes,
                            matched_line_numbers=matched_line_numbers)
                        
                    elif isinstance(node, Always):
                        procedural_assigns = extract_procedural_assigns(node.statement)
                        for assign_stmt in procedural_assigns:
                            process_add_mult_in_statement(
                                assign_stmt,      
                                add_mult_items, 
                                signal_dict, 
                                param_dict, 
                                container_node=node, 
                                processed_nodes=processed_nodes,
                                matched_line_numbers=matched_line_numbers)
           
            elif isinstance(item, Function):
                print(f"Found function definition '{item.name}', analysis not yet implemented.")

            elif isinstance(item, Task):
                procedural_assigns = extract_procedural_assigns(item.statement, ...)
                for assign_stmt in procedural_assigns:
                    process_add_mult_in_statement(assign_stmt, ..., container_node=item)
                       
        if not add_mult_items:
            continue
        
        else:

            for container_node, times_node_list in add_mult_items.items():
                for op_node in times_node_list:
                    
                    success = False
                    source_name_for_dict = "on_on_off"    
                    if isinstance(container_node, Assign):
                        
                        extraction_index = module_extraction_counters.get(module.name, 0)
                        mod_name = f"{module.name}_module{extraction_index}"
                        modified_filename = f"{module.name}_modified{extraction_index}.v"
                        success = handle_assign_add_mult(
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

                    elif isinstance(container_node, Always):
                        extraction_index = module_extraction_counters.get(module.name, 0)
                        mod_name = f"{module.name}_module{extraction_index}"
                        modified_filename = f"{module.name}_modified{extraction_index}.v"
                        success = handle_always_add_mult(
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
                        print(f"Success: Processed {codegen.visit(op_node)}. Incrementing counters.")
                        processed_nodes.add(op_node)
                        module_extraction_counters[module.name] += 1

                    else:
                        print(f"Info: Processing for {codegen.visit(op_node)} failed or skipped.")