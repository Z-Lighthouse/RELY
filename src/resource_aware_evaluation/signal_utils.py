# signal_utils.py
from pyverilog.vparser.parser import parse
from pyverilog.vparser.ast import *

def eval_expr(node, param_dict):
    if node is None:
        return 0

    if isinstance(node, (IntConst, FloatConst)):
        # eval numeric constants directly
        try:
            return int(node.value)
        except (ValueError, TypeError):
            try:
                return float(node.value)
            except (ValueError, TypeError):
                return None

    if isinstance(node, StringConst):
        # treat strings as symbolic
        return node.value

    if isinstance(node, Identifier):
        # lookup parameter; return None if not found
        if node.name in param_dict:
            try:
                return int(param_dict[node.name]['value'])
            except (ValueError, TypeError):
                return None 
        else:
            return None 

    if isinstance(node, Rvalue):
        return eval_expr(node.var, param_dict)

    # binary operators
    if isinstance(node, Plus):
        left_val = eval_expr(node.left, param_dict)
        right_val = eval_expr(node.right, param_dict)
        return left_val + right_val if left_val is not None and right_val is not None else None

    if isinstance(node, Minus):
        left_val = eval_expr(node.left, param_dict)
        right_val = eval_expr(node.right, param_dict)
        return left_val - right_val if left_val is not None and right_val is not None else None

    if isinstance(node, Times):
        left_val = eval_expr(node.left, param_dict)
        right_val = eval_expr(node.right, param_dict)
        return left_val * right_val if left_val is not None and right_val is not None else None

    if isinstance(node, Divide):
        left_val = eval_expr(node.left, param_dict)
        right_val = eval_expr(node.right, param_dict)
        if left_val is not None and right_val is not None:
            if right_val == 0:
                raise ZeroDivisionError("Division by zero in eval_expr")
            return left_val // right_val  
        return None

    if isinstance(node, Mod):
        left_val = eval_expr(node.left, param_dict)
        right_val = eval_expr(node.right, param_dict)
        if left_val is not None and right_val is not None:
            if right_val == 0:
                raise ZeroDivisionError("Modulo by zero in eval_expr")
            return left_val % right_val
        return None

    if isinstance(node, And):
        left_val = eval_expr(node.left, param_dict)
        right_val = eval_expr(node.right, param_dict)
        return left_val & right_val if left_val is not None and right_val is not None else None

    if isinstance(node, Or):
        left_val = eval_expr(node.left, param_dict)
        right_val = eval_expr(node.right, param_dict)
        return left_val | right_val if left_val is not None and right_val is not None else None

    if isinstance(node, Xor):
        left_val = eval_expr(node.left, param_dict)
        right_val = eval_expr(node.right, param_dict)
        return left_val ^ right_val if left_val is not None and right_val is not None else None

    if isinstance(node, Xnor):
        left_val = eval_expr(node.left, param_dict)
        right_val = eval_expr(node.right, param_dict)
        return ~(left_val ^ right_val) if left_val is not None and right_val is not None else None

    if isinstance(node, Land):
        left_val = eval_expr(node.left, param_dict)
        right_val = eval_expr(node.right, param_dict)
        return int(bool(left_val) and bool(right_val)) if left_val is not None and right_val is not None else None

    if isinstance(node, Lor):
        left_val = eval_expr(node.left, param_dict)
        right_val = eval_expr(node.right, param_dict)
        return int(bool(left_val) or bool(right_val)) if left_val is not None and right_val is not None else None

    if isinstance(node, Ulnot):
        val = eval_expr(node.var if hasattr(node, 'var') else node.expr, param_dict)
        return int(not bool(val)) if val is not None else None

    if isinstance(node, Eq):
        left_val = eval_expr(node.left, param_dict)
        right_val = eval_expr(node.right, param_dict)
        return int(left_val == right_val) if left_val is not None and right_val is not None else None

    if isinstance(node, NotEq):
        left_val = eval_expr(node.left, param_dict)
        right_val = eval_expr(node.right, param_dict)
        return int(left_val != right_val) if left_val is not None and right_val is not None else None

    if isinstance(node, LessThan):
        left_val = eval_expr(node.left, param_dict)
        right_val = eval_expr(node.right, param_dict)
        return int(left_val < right_val) if left_val is not None and right_val is not None else None

    if isinstance(node, GreaterThan):
        left_val = eval_expr(node.left, param_dict)
        right_val = eval_expr(node.right, param_dict)
        return int(left_val > right_val) if left_val is not None and right_val is not None else None

    if isinstance(node, LessEq):
        left_val = eval_expr(node.left, param_dict)
        right_val = eval_expr(node.right, param_dict)
        return int(left_val <= right_val) if left_val is not None and right_val is not None else None

    if isinstance(node, GreaterEq):
        left_val = eval_expr(node.left, param_dict)
        right_val = eval_expr(node.right, param_dict)
        return int(left_val >= right_val) if left_val is not None and right_val is not None else None

    if isinstance(node, Sll):
        left_val = eval_expr(node.left, param_dict)
        right_val = eval_expr(node.right, param_dict)
        return left_val << right_val if left_val is not None and right_val is not None else None

    if isinstance(node, Srl):
        left_val = eval_expr(node.left, param_dict)
        right_val = eval_expr(node.right, param_dict)
        return left_val >> right_val if left_val is not None and right_val is not None else None

    if isinstance(node, Sra):  # arithmetic right shift (sign extension)
        left_val = eval_expr(node.left, param_dict)
        right_val = eval_expr(node.right, param_dict)
        if left_val is not None and right_val is not None:
            if left_val >= 0:
                return left_val >> right_val
            else:
                return (left_val + 0x100000000) >> right_val
        return None

    if isinstance(node, Cond):
        cond_val = eval_expr(node.cond, param_dict)
        if cond_val is not None:
            if cond_val:
                return eval_expr(node.true_value, param_dict)
            else:
                return eval_expr(node.false_value, param_dict)
        return None

    if isinstance(node, UnaryOperator):
        # handle other unary operators
        if hasattr(node, 'var'):
            val = eval_expr(node.var, param_dict)
        elif hasattr(node, 'expr'):
            val = eval_expr(node.expr, param_dict)
        else:
            val = None

        if val is None:
            return None

        op = node.__class__.__name__
        if op == 'Uminus' or op == 'UMINUS':
            return -val
        elif op == 'Uplus' or op == 'UPLUS':
            return +val
        elif op == 'Ulnot' or op == 'ULNOT' or op == 'Unot' or op == 'UNOT':
            return int(not val)
        else:
            return val

    # unhandled nodes
    return None

def calculate_required_width(value):
    """Calculate required bit width for a given numeric value."""
    if value is None:
        return 1
    
    try:
        numeric_value = int(value)
    except (ValueError, TypeError):
        # fallback to safe default if conversion fails
        return 32
    
    if numeric_value == 0:
        return 1
    
    if numeric_value < 0:
        # 2's complement for negative numbers
        abs_value = abs(numeric_value)
        bits = 1  # sign bit
        while abs_value > 0:
            bits += 1
            abs_value //= 2
        return bits
    else:
        # positive numbers
        bits = 0
        temp = value
        while temp > 0:
            bits += 1
            temp //= 2
        return bits


def get_width(width_node, param_dict, param_value=None):
    """Get bit width. Infer from parameter value if not explicitly defined."""
    if width_node is not None:
        try:
            msb = eval_expr(width_node.msb, param_dict)
            lsb = eval_expr(width_node.lsb, param_dict)
            
            # check if msb and lsb are evaluable
            if isinstance(msb, (int, float)) and isinstance(lsb, (int, float)):
                return abs(msb - lsb) + 1
            else:
                # return None for unknown width instead of a tuple
                return None
        except Exception as e:
            print(f"Warning: Exception during get_width calculation: {e}")
            return None
    
    # infer from param value if explicit width is missing
    if param_value is not None:
        return calculate_required_width(param_value)
    
    # default to 1-bit signal
    return 1

def extract_all_verilog_signals(verilog_file):
    try:
        ast, _ = parse([verilog_file])
    except Exception as e:
        print(f"Error parsing Verilog file '{verilog_file}': {e}")
        return {}, {}

    description = ast.description
    param_dict = {}
    signal_dict = {}

    if not description or not description.definitions:
        return signal_dict, param_dict

    for module in description.definitions:
        if not isinstance(module, ModuleDef):
            continue
            
        # phase 1: extract all parameters in the module
        current_param_dict = {}
        unresolved_params = []
        
        # 1a: module header
        if hasattr(module, 'paramlist') and module.paramlist and hasattr(module.paramlist, 'params'):
            for param_decl_container in module.paramlist.params:
                if isinstance(param_decl_container, Decl):
                    for param_node in param_decl_container.list:
                        if isinstance(param_node, Parameter):
                            unresolved_params.append(param_node)
                            
        # 1b: module body
        if hasattr(module, 'items'):
            for item in module.items:
                if isinstance(item, Decl):
                    for decl in item.list:
                        if isinstance(decl, (Parameter, Localparam)):
                            unresolved_params.append(decl)
        
        # 1c: iteratively resolve parameters (value and width)
        last_dict_size = -1
        while len(current_param_dict) > last_dict_size and unresolved_params:
            last_dict_size = len(current_param_dict)
            remaining_params = []
            for param in unresolved_params:
                value = None
                if hasattr(param, 'value') and param.value:
                    value = eval_expr(param.value, current_param_dict)
                
                width = get_width(getattr(param, 'width', None), current_param_dict, value)
                is_signed = getattr(param, 'signed', False)
                
                # add to dict if evaluable
                if value is not None:
                    current_param_dict[param.name] = {
                        'value': value,
                        'width': width,
                        'signed': is_signed,
                        'type': param.__class__.__name__
                    }
                else:
                    remaining_params.append(param)
            unresolved_params = remaining_params
        
        # assign defaults to unresolved params
        for param in unresolved_params:
            # try to get width even if value is unknown
            width = get_width(getattr(param, 'width', None), current_param_dict)
            is_signed = getattr(param, 'signed', False)
            current_param_dict[param.name] = {
                'value': 0, 
                'width': width,
                'signed': is_signed,
                'type': param.__class__.__name__
            }
        
        param_dict.update(current_param_dict)

        # phase 2: extract ports and internal signals
        
        # 2a: parse ANSI-style portlist
        if hasattr(module, 'portlist') and module.portlist and hasattr(module.portlist, 'ports'):
            last_line_signed = False
            last_line_num = -1

            for port in module.portlist.ports:
                if not isinstance(port, Ioport): continue
                
                decl_node = port.first 
                if not hasattr(decl_node, 'name'): continue
                
                name = decl_node.name
                port_type = decl_node.__class__.__name__
                width = get_width(getattr(decl_node, 'width', None), param_dict)
                
                current_line_num = decl_node.lineno
                is_signed_explicit = getattr(decl_node, 'signed', False)
                
                if current_line_num != last_line_num:
                    last_line_num = current_line_num
                    last_line_signed = is_signed_explicit
                
                final_is_signed = is_signed_explicit or last_line_signed

                signal_dict[name] = {
                    'type': port_type, 
                    'width': width,
                    'signed': final_is_signed
                }

        # 2b: parse internal signals and non-ANSI ports
        if hasattr(module, 'items'):
            for item in module.items:
                if not isinstance(item, Decl): continue

                # extract shared properties in this Decl
                shared_is_signed = False
                shared_type_str = None
                if hasattr(item, 'spec') and item.spec:
                    if any(s.__class__.__name__ == '_Signed' for s in item.spec):
                        shared_is_signed = True
                        
                    # find type (Reg/Wire takes priority)
                    for s in item.spec:
                        if isinstance(s, (Reg, Wire, Integer)): 
                            shared_type_str = s.__class__.__name__
                            break 
                            
                    if not shared_type_str:
                         for s in item.spec:
                            if isinstance(s, (Input, Output, Inout)):
                                shared_type_str = s.__class__.__name__
                                break

                # apply shared properties to all signals in this Decl
                for decl_item in item.list:
                    if not hasattr(decl_item, 'name') or isinstance(decl_item, (Parameter, Localparam, Genvar)):
                        continue
                    
                    name = decl_item.name
                    
                    # filter out common loop variables
                    if isinstance(decl_item, Integer) and name in ['i', 'j', 'k']: 
                        continue
                        
                    width = get_width(getattr(decl_item, 'width', None), param_dict)
                    
                    is_item_signed = getattr(decl_item, 'signed', False)
                    final_is_signed = shared_is_signed or is_item_signed

                    if name not in signal_dict:
                        signal_dict[name] = {}
                    
                    # update existing portlist entries or add new ones
                    signal_dict[name].update({
                        'type': shared_type_str if shared_type_str else decl_item.__class__.__name__, 
                        'width': width,
                        'signed': final_is_signed
                    })

    return signal_dict, param_dict