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


def get_output_pipeline_depths(always_node, start_node_name):
    """
    Calculate the pipeline depth of subsequent signals starting from a specified node.
    The depth of the starting signal is defined as 0.
    """
    assigns = [stmt for stmt in extract_procedural_assigns(always_node.statement) 
               if isinstance(stmt, NonblockingSubstitution)]
    if not assigns: return {}

    all_lhs_names = {stmt.left.var.name for stmt in assigns if hasattr(stmt.left, 'var')}
    
    depth_map = {}
    depth_map[start_node_name] = 0
    for sig in all_lhs_names:
        if sig != start_node_name:
            depth_map[sig] = -1

    changed = True
    max_iterations = len(all_lhs_names) + 5
    iterations = 0
    
    while changed and iterations < max_iterations:
        changed = False
        iterations += 1
        
        for stmt in assigns:
            if not (hasattr(stmt.left, 'var') and hasattr(stmt.left.var, 'name')): continue

            lhs_name = stmt.left.var.name
            rhs_names = get_names_from_node(stmt.right)
            
            # only care about single-signal RHS 
            if len(rhs_names) != 1: continue
            rhs_name = list(rhs_names)[0]

            if depth_map.get(rhs_name, -1) == -1:
                continue
                
            new_depth = depth_map[rhs_name] + 1
            
            if new_depth != depth_map.get(lhs_name, -1):
                depth_map[lhs_name] = new_depth
                changed = True
    
    return depth_map

def create_port_info(all_signals, signal_dict, container_node=None, loop_var=None, original_code_str=""):
    """
    Build an enhanced port_info dict based on signals and context.
    Detects array signals if loop_var is provided.
    """
    port_info = {}
    
    output_signal_name = None
    if container_node and isinstance(container_node, (Assign, BlockingSubstitution, NonblockingSubstitution)):
        if hasattr(container_node.left, 'var') and hasattr(container_node.left.var, 'name'):
            output_signal_name = container_node.left.var.name
        elif isinstance(container_node.left, Identifier):
            output_signal_name = container_node.left.name

    indexed_signals = set()
    if loop_var and original_code_str:
        indexed_signal_pattern = re.compile(r'\b(\w+)\s*\[\s*' + re.escape(loop_var) + r'\s*\]')
        indexed_signals = set(indexed_signal_pattern.findall(original_code_str))

    for signal_name in all_signals:
        is_array = signal_name in indexed_signals
        
        if signal_name in signal_dict:
            original_info = signal_dict[signal_name]
            
            type_str = original_info.get('type', '').lower()
            if 'output' in type_str: direction = 'output'
            elif 'input' in type_str: direction = 'input'
            else: direction = 'output' if signal_name == output_signal_name else 'input'

            width_val = original_info.get('width')
            width_str = f"[{width_val - 1}:0]" if isinstance(width_val, int) and width_val > 1 else ""
            
            is_signed = original_info.get('signed', False)
            
            port_info[signal_name] = {
                'connect_to': signal_name,  
                'direction': direction, 
                'width': width_str, 
                'is_array': is_array,
                'signed': is_signed 
            }
            
        else:
            direction = 'output' if signal_name == output_signal_name else 'input'
            
            port_info[signal_name] = {
                'connect_to': signal_name, 
                'direction': direction, 
                'width': '', 
                'is_array': is_array,
                'signed': False         
            }
            
    return port_info

def extract_multiplication_info(container_node, signal_dict, param_dict, codegen):
    """
    Strictly match A * B pattern and extract related info.
    """
    try:
        if not isinstance(container_node, (Assign, BlockingSubstitution, NonblockingSubstitution)):
            return None
        
        lhs_base_name_list = list(extract_identifier_names(container_node.left))
        if not lhs_base_name_list: return None
        lhs_base_name = lhs_base_name_list[0]
        
        top_level_op = getattr(container_node.right, 'var', container_node.right)

        if not isinstance(top_level_op, Times):
            return None
            
        a_node, b_node = top_level_op.left, top_level_op.right
        port_info = {}
        rebuild_map = {}
        
        referenced_params = set()

        def process_operand(node):
            nonlocal port_info, rebuild_map, referenced_params
            
            if isinstance(node, (Identifier, Pointer)):
                base_name = get_base_name(node)
                
                if base_name in param_dict:
                    referenced_params.add(base_name)
                    return
                
                conn_str = codegen.visit(node).strip()
                width = get_expr_width(node, signal_dict, param_dict)
                is_signed = signal_dict.get(base_name, {}).get('signed', False)
                width_str = f"[{width - 1}:0]" if width > 1 else ""
                port_name = f"{base_name}_in"
                
                port_info[port_name] = {'direction': 'input', 'width': width_str, 'connect_to': conn_str, 'signed': is_signed,'type': 'wire' }
                rebuild_map[base_name] = port_name

            elif isinstance(node, (IntConst, FloatConst)):
                pass 
            else:
                raise TypeError(f"Unsupported operand type: {type(node)}")

        process_operand(a_node)
        process_operand(b_node)
        

        lhs_base_name_list = list(extract_identifier_names(container_node.left))
        if not lhs_base_name_list: return None
        lhs_base_name = lhs_base_name_list[0]
        lhs_conn_str = codegen.visit(container_node.left).strip()
        output_width = signal_dict.get(lhs_base_name, {}).get('width')
        is_p_signed = signal_dict.get(lhs_base_name, {}).get('signed', False)
        
        if output_width is None: return None

        output_width_str = f"[{output_width - 1}:0]" if output_width > 1 else ""
        p_port_name = f"{lhs_base_name}_out"
        
        port_info[p_port_name] = {'direction': 'output', 'width': output_width_str, 'connect_to': lhs_conn_str, 'signed': is_p_signed,'type': 'wire' }
        
        rebuilder = RenamingCodegen(rebuild_map)
        rebuilt_rhs = rebuilder.visit(top_level_op)
        code_body = f"assign {p_port_name} = {rebuilt_rhs};"
            
        return {
            'port_info': port_info,
            'code_body': code_body,
            'referenced_params': list(referenced_params)
        }
    except Exception as e:
        print(f"Error extracting mult info at line {getattr(container_node, 'lineno', 'N/A')}: {e}")
        return None
    
def handle_assign_op(container_node, op_node, module, mod_name, modified_filename,
                            signal_dict, file_lines, out_dir,  param_dict, file_extraction_dict,source_name, module_instance_counts=None):
    """Handle A+B pattern in assign statements."""
    try:
        behavioral_items = [
            item for item in module.items 
            if isinstance(item, (Assign, Always, Initial, Instance))
        ]
        if len(behavioral_items) == 1 and behavioral_items[0] == container_node:
            print(f"Module {module.name} has only one A+B assign. Extracting entire module.")
            
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

            file_extraction_dict[line_num] = update_data

            return True

        is_inside_for, dsp_count = get_assign_count(container_node, param_dict)

        if is_inside_for:
            if dsp_count > 0:
                print(f"Assign is inside a for-loop. Estimated DSP count: {dsp_count}")
                for_loop_node = find_innermost_for_node(container_node)

                if for_loop_node is None:
                    print("Error: is_inside_for is True, but no for-loop node found.")
                    return False 

                original_code_str = codegen.visit(container_node)
                extraction_result = extract_loop_logic(
                    original_code_str, for_loop_node, container_node, 
                    signal_dict, param_dict, codegen
                )
                
                transformed_body = extraction_result["transformed_body"]
                port_info = extraction_result["port_info"]
                loop_var = extraction_result["loop_var"]
                params_to_add = extraction_result["referenced_params"]

                mod_code = generate_module_code(
                    mod_name, 
                    transformed_body, 
                    port_info,
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
                
                gen_block_name = f"gen_{mod_name}"

                pre_str = codegen.visit(for_loop_node.pre).strip().rstrip(';')
                cond_str = codegen.visit(for_loop_node.cond).strip()
                post_str = codegen.visit(for_loop_node.post).strip().rstrip(';')
                gen_for_loop_header = f"for ({pre_str}; {cond_str}; {post_str})"
                
                replacement_code = (
                    f"generate\n"
                    f"  // Original for-loop logic extracted to module '{mod_name}'\n"
                    f"  {gen_for_loop_header} begin : {gen_block_name}\n"
                    f"    {instance_code}\n"
                    f"  end\n"
                    f"endgenerate"
                )
                
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
                    'dsp_count': dsp_count * module_instance_counts.get(module.name, 1)
                }

                file_extraction_dict[line_num] = update_data

                return True
                
            else: 
                print("Assign in for-loop, but loop count failed to parse. Skipping.")
                return False 

        else: 
            print("Assign is not in a for-loop. Extracting single A+B core.")
            
            extraction_result = extract_op_info(
                container_node,
                op_node, 
                signal_dict, 
                param_dict, 
                codegen
            )
            
            if not extraction_result:
                print("Node does not match A+B pattern. Skipping.")
                return False

            print("Successfully identified A+B pattern.")
            
            mod_code = generate_module_code(
                mod_name, 
                extraction_result['code_body'], 
                extraction_result['port_info']
            )
            with open(os.path.join(out_dir, f"{mod_name}.v"), 'w') as f:
                f.write(mod_code)
            print(f"Module generated successfully: {mod_name}.v")

            instance_name = f"{mod_name}_inst"
            instance_code = create_instance_code(
                mod_name, 
                instance_name, 
                extraction_result['port_info']
            )
            
            start_line = container_node.lineno
            modified_lines = replace_code_block_by_lines(
                file_lines, 
                start_line, 
                start_line, 
                instance_code
            )
            with open(os.path.join(out_dir, modified_filename), 'w') as f:
                f.writelines(modified_lines)
            
            line_num = op_node.lineno

            update_data = {
                'dsp_module_name': mod_name,
                'source_function': source_name, 
                'dsp_count': module_instance_counts.get(module.name, 1) * 1
            }

            file_extraction_dict[line_num] = update_data

            return True

    except Exception as e:
        print(f"Error handling A+B assign at line {container_node.lineno}: {e}")
        import traceback
        traceback.print_exc()
        return False


def is_simple_always_op(always_node, op_node_to_check):
    """Check if always block is a pure A+B pipeline."""
    if not hasattr(always_node, 'sens_list') or not always_node.sens_list:
        return False, None
    is_timing = any(isinstance(s, Sens) and s.type in ('posedge', 'negedge') for s in always_node.sens_list.list)
    if not is_timing:
        return False, None
    
    if not hasattr(always_node, 'statement') or not isinstance(always_node.statement, Block):
        return False, None
    statements = getattr(always_node.statement, 'statements', [])
    if not statements:
        return False, None

    core_op_stmt = None
    pipeline_stmts = []

    def is_pre_adder_pattern(node):
        ALLOWED_OPS = (Plus, Minus)
        ALLOWED_OPERANDS = (Identifier, Pointer)
        if not isinstance(node, ALLOWED_OPS):
            return False
        return isinstance(node.left, ALLOWED_OPERANDS) and \
               isinstance(node.right, ALLOWED_OPERANDS)

    for stmt in statements:
        if not isinstance(stmt, NonblockingSubstitution): 
            return False, None
        
        rhs = getattr(stmt.right, 'var', stmt.right)
        
        if is_pre_adder_pattern(rhs):
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
    
    if core_op_node is not op_node_to_check:
        return False, None

    related_signals = {name for name in extract_identifier_names(core_op_node)}
    core_op_output_name = codegen.visit(core_op_stmt.left).strip()
    related_signals.add(core_op_output_name)
    
    newly_added = True
    while newly_added:
        newly_added = False
        for stmt in pipeline_stmts:
            lhs_name = codegen.visit(stmt.left).strip()
            rhs_name = codegen.visit(stmt.right).strip()
            
            lhs_is_related = lhs_name in related_signals
            rhs_is_related = rhs_name in related_signals

            if rhs_is_related and not lhs_is_related:
                related_signals.add(lhs_name)
                newly_added = True
            if lhs_is_related and not rhs_is_related:
                related_signals.add(rhs_name)
                newly_added = True

    all_lhs_in_always = {codegen.visit(s.left).strip() for s in statements}
    
    if not all_lhs_in_always.issubset(related_signals):
        return False, None

    return True, core_op_node


def is_valid_pipelined_op_module(module, always_node, core_op_node_from_caller):
    """Check if module is a pure A+B pipeline."""
    always_count = 0
    ALLOWED_TOP_LEVEL_TYPES = (Always, Assign, Decl)
    for item in module.items:
        if not isinstance(item, ALLOWED_TOP_LEVEL_TYPES):
            return False
        if isinstance(item, Always):
            always_count += 1
    
    if always_count != 1: 
        return False
        
    the_only_always_node = [item for item in module.items if isinstance(item, Always)][0]
    if the_only_always_node is not always_node: 
        return False

    all_assign_stmts = [item for item in module.items if isinstance(item, Assign)]
    for assign_stmt in all_assign_stmts:
        rhs_node = getattr(getattr(assign_stmt, 'right', None), 'var', None)
        if not isinstance(rhs_node, (Identifier, Pointer)):
            return False
     
    is_simple, core_op_node = is_simple_always_op(always_node, core_op_node_from_caller)
    if not is_simple:
        return False
        
    try:
        adder_node = core_op_node
        a_node = adder_node.left
        b_node = adder_node.right
    except AttributeError:
        return False

    if not all(isinstance(n, (Identifier, Pointer)) for n in [a_node, b_node]):
        return False

    depth_map = get_input_pipeline_depths(always_node, [a_node, b_node])
    
    a_depth = depth_map.get(a_node.name, 0)
    b_depth = depth_map.get(b_node.name, 0)

    if a_depth > 2 or b_depth > 2: 
        return False

    if not validate_output_pipeline_depth(always_node, depth_map, core_op_node, max_output_depth=2):
         return False

    return True


def extract_op_pipeline_slice(always_node, core_op_node, signal_dict, param_dict, codegen):
    """Extract pipeline slice from complex sequential always block."""
    
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

    adder_node = core_op_node
    referenced_params = set()

    if not isinstance(adder_node, (Plus, Minus)):
        return None

    a_node = adder_node.left
    b_node = adder_node.right

    if not (isinstance(a_node, (Identifier, Pointer)) and isinstance(b_node, (Identifier, Pointer))):
        return None
    
    trace_tasks = [
        (a_node, 1),  
        (b_node, 1)   
    ]
    
    all_backward_stmts = set()
    slice_boundary_inputs = set()

    for node, depth in trace_tasks:
        traced_stmts, boundary_inputs = trace_backward_single(
            start_node=node,
            max_depth=depth,
            all_assigns_in_data_path=all_assigns_in_data_path
        )
        all_backward_stmts.update(traced_stmts)
        slice_boundary_inputs.update(boundary_inputs)

    MAX_FORWARD_DEPTH = 2 
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

def handle_always_pre_adder(container_node, op_node, module, mod_name, modified_filename,
                            signal_dict, file_lines, out_dir, param_dict, file_extraction_dict, source_name, module_instance_counts=None):
    """Handle A+B pattern in always blocks."""
    module_name = module.name
    
    if is_always_sequential(container_node):

        if is_valid_pipelined_op_module(module, container_node, op_node):
            try:
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

                file_extraction_dict[line_num] = update_data

                return True

            except Exception as e:
                print(f"Error during entire module extraction for Pre-Adder: {e}")
                return False
            
        else:
            slice_result = extract_op_pipeline_slice(
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
                        internal_reg_decls=dsp_info.get('internal_reg_decls')
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

                    file_extraction_dict[line_num] = update_data

                    return True

                except Exception as e:
                    print(f"Fatal error during pipeline slicing and reconstruction: {e}")
                    import traceback
                    traceback.print_exc()
                    return False
            else:
                print("Pipeline slicing failed.")
                return False
    else:
        
        if is_pure_combinational_module(module,  container_node, op_node):
            try:
                
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

                file_extraction_dict[line_num] = update_data

                return True

            except Exception as e:
                print(f"Error during entire combinational module extraction: {e}")
                return False
        
        else: 
        
            try:
                all_assignments = extract_procedural_assigns(container_node.statement)
                target_assign_stmt = None
                for stmt in all_assignments:
                    if is_node_in_tree(op_node, stmt):
                        target_assign_stmt = stmt
                        break
                
                if target_assign_stmt is None:
                    return False

                extraction_result = extract_op_info(
                    target_assign_stmt, 
                    op_node, 
                    signal_dict, 
                    param_dict, 
                    codegen
                )
                
                if not extraction_result:
                    return False

                port_info = extraction_result['port_info']
                code_body = extraction_result['code_body']

                new_mod_code = generate_module_code(mod_name, code_body, port_info)
                with open(os.path.join(out_dir, f"{mod_name}.v"), 'w') as f:
                    f.write(new_mod_code)

                output_port_info = next((p for p in port_info.values() if p['direction'] == 'output'), None)
                if not output_port_info:
                    return False
                
                original_lhs_name = output_port_info['connect_to']
                intermediate_wire_name = f"{original_lhs_name}_core_out"
                
                wire_width = output_port_info['width']
                wire_signed_str = "signed" if output_port_info['signed'] else ""
                wire_decl_str = f"    reg {wire_signed_str} {wire_width} {intermediate_wire_name};\n".replace("  ", " ")

                output_port_key = next(p_name for p_name, p_info in port_info.items() if p_info['direction'] == 'output')
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

                file_extraction_dict[line_num] = update_data

                return True

            except Exception as e:
                print(f"Error processing combinational always block: {e}")
                import traceback
                traceback.print_exc()
                return False
            
            
def off_off_on(verilog_path, ast, signal_dict, param_dict, out_dir, 
             module_extraction_counters, file_extraction_dict,
             processed_nodes, instance_hierarchy=None, top_module_name=None, 
             module_instance_counts=None,matched_line_numbers=None, **kwargs):
    
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
    print("--- Starting A+B Check ---")
    
    base_name = os.path.splitext(os.path.basename(verilog_path))[0]

    original_copy_path = os.path.join(out_dir, f"{base_name}_original.v")
    os.makedirs(out_dir, exist_ok=True)
    copy_success = safe_file_copy(verilog_path, original_copy_path)
    if not copy_success:
        print(f"Warning: Could not copy file {verilog_path}, but proceeding.")

    try:
        description = ast.description
        with open(verilog_path, 'r', encoding='utf-8') as f:
            original_file_lines = f.readlines()
    except Exception as e:
        return 
    
    if not hasattr(description, 'definitions'): return
  
    
    for module in description.definitions:
        
        if not isinstance(module, ModuleDef):
            continue


        op_items = {}


        for item in module.items:
            
            if isinstance(item, Assign):
                process_op_in_statement(
                    item, 
                    op_items, 
                    signal_dict, 
                    param_dict, 
                    container_node=item, 
                    processed_nodes=processed_nodes, 
                    matched_line_numbers=matched_line_numbers)

            elif isinstance(item, Always):
                procedural_assigns = extract_procedural_assigns(item.statement)
                for assign_stmt in procedural_assigns:
                    process_op_in_statement(
                        assign_stmt, 
                        op_items, 
                        signal_dict, 
                        param_dict, 
                        container_node=item, 
                        processed_nodes=processed_nodes, 
                        matched_line_numbers=matched_line_numbers)
            
            elif isinstance(item, GenerateStatement):
                nodes_in_generate = find_nodes_in_generate(item)
                
                for node in nodes_in_generate:
                    
                    if isinstance(node, Assign):
                        process_op_in_statement(
                            node,             
                            op_items, 
                            signal_dict, 
                            param_dict, 
                            container_node=node, 
                            processed_nodes=processed_nodes, 
                            matched_line_numbers=matched_line_numbers)
                        
                    elif isinstance(node, Always):
                        procedural_assigns = extract_procedural_assigns(node.statement)
                        for assign_stmt in procedural_assigns:
                            process_op_in_statement(
                                assign_stmt,      
                                op_items, 
                                signal_dict, 
                                param_dict, 
                                container_node=node, 
                                processed_nodes=processed_nodes, 
                                matched_line_numbers=matched_line_numbers)
           
            elif isinstance(item, Function):
                print(f"Found a function definition '{item.name}', analysis not yet implemented.")

            elif isinstance(item, Task):
                procedural_assigns = extract_procedural_assigns(item.statement, ...)
                for assign_stmt in procedural_assigns:
                    process_op_in_statement(assign_stmt, ..., container_node=item)
            
        print("-----------------------------")
        print(op_items)
        
        if not op_items:
            continue
        else:
            
            for container_node, times_node_list in op_items.items():
                for op_node in times_node_list:
                    
                    success = False
                    source_name_for_dict = "off_off_on"     
                    if isinstance(container_node, Assign):
                        
                        extraction_index = module_extraction_counters.get(module.name, 0)
                        mod_name = f"{module.name}_module{extraction_index}"
                        modified_filename = f"{module.name}_modified{extraction_index}.v"
                        
                        success = handle_assign_op(
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
                        
                        success = handle_always_pre_adder(
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
                        print(f"Success: Processed {codegen.visit(op_node)} succeeded. Incrementing counters.")
                        processed_nodes.add(op_node)
                        module_extraction_counters[module.name] += 1

                    else:
                        print(f"Info: Processing for {codegen.visit(op_node)} failed or was skipped.")