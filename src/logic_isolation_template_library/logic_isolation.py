import os
import sys
import logging
import shutil
import collections
import time
import re  
import tempfile 

from pyverilog.vparser.parser import parse, ParseError
from pyverilog.vparser.ast import ModuleDef 
from signal_utils import extract_all_verilog_signals
from pyverilog.vparser.ast import *
from preprocess import get_matched_line_numbers
from off_on_off import off_on_off
from off_on_on import off_on_on
from on_on_off import on_on_off
from on_on_on import on_on_on
from on_off_off import on_off_off
from off_off_on import off_off_on


def preprocess_verilog_file(filepath):
    """
    Preprocess Verilog file by removing comments, includes, and attributes.
    Returns the cleaned code string.
    """
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            code = f.read()
    except IOError as e:
        logging.error("Could not read file %s: %s", filepath, e)
        return None

    # remove block comments /* ... */
    code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)

    # remove inline comments // ...
    code = re.sub(r'//.*?$', '', code, flags=re.MULTILINE)
    
    # remove `include statements
    code = re.sub(r'`include\s+".*?"', '', code)

    # remove tool attributes (* ... *)
    code = re.sub(r'\(\*.*?\*\)', '', code)

    # remove empty lines
    code = "\n".join([line for line in code.split('\n') if line.strip()])

    return code

# =============================================================================

def build_instance_hierarchy(ast):
    """
    Build module instantiation hierarchy.
    Returns: {child_module: {parent_module: instance_count}}
    """
    hierarchy = {}
    
    for module in ast.description.definitions:
        if not isinstance(module, ModuleDef):
            continue
            
        for item in module.items:
            if isinstance(item, InstanceList):
                for instance in item.instances:
                    child_module = instance.module
                    parent_module = module.name
                    
                    if child_module not in hierarchy:
                        hierarchy[child_module] = {}
                    
                    if parent_module in hierarchy[child_module]:
                        hierarchy[child_module][parent_module] += 1
                    else:
                        hierarchy[child_module][parent_module] = 1
    
    logging.debug("Instance Hierarchy: %s", hierarchy)
    return hierarchy


def find_top_module(ast):
    """
    Auto-detect the top-level module.
    """
    all_modules = set()
    instantiated_modules = set()
    
    for module in ast.description.definitions:
        if isinstance(module, ModuleDef):
            all_modules.add(module.name)
            
            for item in module.items:
                if isinstance(item, InstanceList):
                    for instance in item.instances:
                        instantiated_modules.add(instance.module)
    
    top_modules = all_modules - instantiated_modules
    
    if len(top_modules) == 1:
        top_module = list(top_modules)[0]
        return top_module
    elif len(top_modules) > 1:
        logging.warning("Multiple potential top modules found: %s, using first one", top_modules)
        return list(top_modules)[0]
    else:
        first_module = next((m.name for m in ast.description.definitions if isinstance(m, ModuleDef)), None)
        logging.warning("No clear top module found, using %s", first_module)
        return first_module


def calculate_total_instance_count(module_name, top_module, hierarchy, current_multiplier=1):
    """
    Recursively calculate total instantiations of a module in the design.
    """
    # return current multiplier if it's the top module
    if module_name == top_module:
        return current_multiplier
    
    # not instantiated by others
    if module_name not in hierarchy:
        return current_multiplier
    
    total_count = 0
    
    for parent_module, instance_count in hierarchy[module_name].items():
        parent_total = calculate_total_instance_count(
            parent_module, 
            top_module, 
            hierarchy, 
            current_multiplier * instance_count
        )
        total_count += parent_total
    
    return total_count if total_count > 0 else current_multiplier

def write_unified_extraction_report(out_dir, extraction_dict):
    """
    Generate a unified extraction report.
    """
    report_path = os.path.join(out_dir, "extraction_report.txt")
    
    header = (f"{'CANDIDATE_LINE_NUM':<25} | {'STATUS':<15} | "
              f"{'SOURCE_FUNCTION':<20} | {'TOTAL_DSPS':<20} | {'EXTRACTED_DSP_MODULE'}\n")
    separator = (f"{'-'*25}-|-{'-'*15}-|-{'-'*20}-|-{'-'*20}-|-{'-'*50}\n")
    
    try:
        with open(report_path, 'w') as f:
            f.write("--- Unified Line-by-Line Extraction Report ---\n")
            f.write(header)
            f.write(separator)
            
            for line_num in sorted(extraction_dict.keys()):
                result_dict = extraction_dict[line_num]
                
                # set defaults if extraction failed
                if result_dict is None:
                    status = 'Failed'
                    source_func = 'N/A'
                    dsp_counts = 'N/A'  
                    dsp_name = 'N/A'
                else:
                    status = 'Success'
                    source_func = result_dict.get('source_function', 'Unknown')
                    dsp_counts = result_dict.get('dsp_count', 'Error') 
                    dsp_name = result_dict.get('dsp_module_name', 'Unnamed_DSP')
                    
                f.write(f"{line_num:<25} | {status:<15} | {source_func:<20} | "
                        f"{str(dsp_counts):<20} | {dsp_name}\n")

        logging.info("Generated unified extraction report at: %s", report_path)
    except IOError as e:
        logging.error("Could not write extraction_report.txt: %s", e)



def attach_parent(node, parent=None):
    if isinstance(node, Node):
        node.parent = parent
        for c in node.children():
            attach_parent(c, node)
            
def setup_logging(output_dir):
    os.makedirs(output_dir, exist_ok=True)
    log_filepath = os.path.join(output_dir, 'main_processing.log') 

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    if logger.hasHandlers():
        logger.handlers.clear()

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    file_handler = logging.FileHandler(log_filepath, mode='w')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    logging.info("Logging setup complete. Main log will be saved to %s", log_filepath)

def write_parse_errors_to_file(error_list, output_dir):
    """Write files with parse errors to a separate log."""
    error_file_path = os.path.join(output_dir, "parse_errors.txt")
    with open(error_file_path, 'w') as f:
        f.write("Files with ParseError (no output directories created):\n")
        f.write("=" * 60 + "\n")
        for filepath, error_msg in error_list:
            f.write(f"File: {filepath}\n")
            f.write(f"Error: {error_msg}\n")
            f.write("-" * 60 + "\n")
    logging.info("Parse error list saved to: %s", error_file_path)


def main():
    if len(sys.argv) != 3:
        print("Usage: python main.py <source_directory> <base_output_directory>")
        sys.exit(1)

    source_dir = sys.argv[1]
    base_out_dir = sys.argv[2]
    
    setup_logging(base_out_dir)

    if not os.path.isdir(source_dir):
        logging.error("Source directory not found at '%s'", source_dir)
        sys.exit(1)
        
    verilog_files_to_process = []
   
    for root, _, files in os.walk(source_dir):
        for filename in files:
            if filename.endswith(('.v', '.sv')):
                verilog_files_to_process.append(os.path.join(root, filename))

    if not verilog_files_to_process:
        logging.warning("No Verilog files (.v, .sv) found in '%s'", source_dir)
        return

    logging.info("Found %d Verilog files to process.", len(verilog_files_to_process))

    successful_files_count = 0
    failed_files_list = []
    parse_error_files = []
    
    for filepath in verilog_files_to_process:
        logging.info("=================================================")
        logging.info("Processing file: %s", filepath)
        
        start_time = time.time()
        base_filename = os.path.splitext(os.path.basename(filepath))[0]
        file_specific_out_dir = os.path.join(base_out_dir, base_filename)
        
        temp_file = None  
        try:
            logging.info("Step 1: Running regex pre-screening to find candidate lines...")
            candidate_line_numbers = get_matched_line_numbers(filepath)
            
            if not candidate_line_numbers:
                logging.info("No candidate patterns found by regex. Skipping deep analysis for this file.")
                # treat as success since there are no errors, but no output generated
                successful_files_count += 1 
                continue 
                
            logging.info(f"Regex found {len(candidate_line_numbers)} candidate(s) on lines: {sorted(list(candidate_line_numbers))}")
            signal_dict, param_dict = extract_all_verilog_signals(filepath)
            ast, _ = parse([filepath])
            attach_parent(ast)
            
            # create output dir only if parsing succeeds
            os.makedirs(file_specific_out_dir, exist_ok=True)
            logging.info("Output will be saved to: %s", file_specific_out_dir)
            
            # set up file-specific logger
            file_log_path = os.path.join(file_specific_out_dir, f"{base_filename}.log")
            file_logger = logging.getLogger(base_filename)
            file_logger.setLevel(logging.INFO)

            if file_logger.hasHandlers():
                file_logger.handlers.clear()

            fh = logging.FileHandler(file_log_path, mode='w')
            fh.setLevel(logging.INFO)
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            fh.setFormatter(formatter)
            file_logger.addHandler(fh)

            ch = logging.StreamHandler(sys.stdout)
            ch.setFormatter(formatter)
            file_logger.addHandler(ch)

            file_logger.info("Processing original file: %s", filepath)
            file_logger.info("Output will be saved to: %s", file_specific_out_dir)

            file_logger.info("AST parsing completed successfully.")
            print("\n" + "="*20 + " Initial Parameter Dictionary " + "="*20)
            print(param_dict)
            print(signal_dict)
            print("="*57 + "\n")
            
            instance_hierarchy = build_instance_hierarchy(ast)
            top_module_name = find_top_module(ast)
            logging.info("Instance hierarchy built for %s", filepath)
            logging.info("Top module: %s", top_module_name)
            
            module_instance_counts = {}
            for module in ast.description.definitions:
                if isinstance(module, ModuleDef):
                    total_instances = calculate_total_instance_count(
                        module.name, 
                        top_module_name, 
                        instance_hierarchy
                    )
                    module_instance_counts[module.name] = total_instances
                    logging.info("Module %s: total instances = %d", module.name, total_instances)
            
            # init extraction dict with None (indicates failure by default)
            file_total_extraction_dict = {line_num: None for line_num in candidate_line_numbers}
            
            processed_nodes = set()
            module_extraction_counters = {
                module.name: 0 for module in ast.description.definitions if isinstance(module, ModuleDef)
            }

            logging.info("--- Running Configuration ---")
            common_args = {
                'verilog_path': filepath,
                'ast': ast,
                'signal_dict': signal_dict,
                'param_dict': param_dict,
                'out_dir': file_specific_out_dir,
                'module_extraction_counters': module_extraction_counters,
                'file_extraction_dict': file_total_extraction_dict, 
                'processed_nodes': processed_nodes,
                'instance_hierarchy': instance_hierarchy,
                'top_module_name': top_module_name,
                'module_instance_counts': module_instance_counts,
                'matched_line_numbers': candidate_line_numbers
            }


            on_on_on(**common_args)
            on_on_off(**common_args)
            off_on_on(**common_args)
            off_on_off(**common_args)
            off_off_on(**common_args)
            
            if file_total_extraction_dict:
                write_unified_extraction_report(file_specific_out_dir, file_total_extraction_dict)

            successful_files_count += 1
            file_logger.info("Successfully processed file: %s", filepath)


        except ParseError as pe:
            error_msg = f"ParseError: {pe}"
            logging.error("ParseError while processing %s: %s", filepath, pe)
            failed_files_list.append((filepath, error_msg))
            parse_error_files.append((filepath, error_msg))
            
            if os.path.exists(file_specific_out_dir):
                try:
                    shutil.rmtree(file_specific_out_dir)
                    logging.info("Removed output directory for failed file: %s", file_specific_out_dir)
                except OSError as e:
                    logging.warning("Could not remove directory %s: %s", file_specific_out_dir, e)

            
        finally:
    
            if os.path.exists(file_specific_out_dir):
                end_time = time.time()
                elapsed_time = end_time - start_time
                time_report_path = os.path.join(file_specific_out_dir, "time.txt")
                with open(time_report_path, 'w') as tf:
                    tf.write(f"File: {os.path.basename(filepath)}\n")
                    tf.write(f"Start Time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))}\n")
                    tf.write(f"End Time:   {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(end_time))}\n")
                    tf.write(f"Elapsed Time (seconds): {elapsed_time:.3f}\n")
                logging.info("Processing time: %.3f seconds", elapsed_time)

    # --- summary report ---
    logging.info("\n\n=================================================")
    logging.info("           PROCESSING SUMMARY")
    logging.info("=================================================")
    logging.info("Total files attempted:  %d", len(verilog_files_to_process))
    logging.info("Successfully processed: %d", successful_files_count)
    logging.info("Failed or skipped:      %d", len(failed_files_list))
    
    if parse_error_files:
        write_parse_errors_to_file(parse_error_files, base_out_dir)
        logging.info("Files with ParseError (no directories created): %d", len(parse_error_files))
    
    if failed_files_list:
        logging.info("--- Failed/Skipped Files ---")
        for fpath, reason in failed_files_list:
            error_type = reason.split(':')[0] 
            logging.warning("  - %s: %s", error_type, os.path.basename(fpath))
    
    logging.info("=================================================")

    if failed_files_list:
        failed_log_path = os.path.join(base_out_dir, "failed_files.log")
        logging.info("A detailed list of failed/skipped files has been saved to: %s", failed_log_path)
        
        with open(failed_log_path, 'w') as f:
            f.write("The following files could not be processed successfully:\n")
            f.write("------------------------------------------------------\n")
            for fpath, reason in failed_files_list:
                f.write(f"File:   {fpath}\n")
                f.write(f"Reason: {reason}\n")
                f.write("------------------------------------------------------\n")
        
        success_dir = os.path.join(base_out_dir, "success_files")
        os.makedirs(success_dir, exist_ok=True)

        failed_file_paths = {os.path.abspath(fpath) for fpath, _ in failed_files_list}

        for root, subdirs, files in os.walk(source_dir):
            verilog_files = [
                os.path.join(root, f)
                for f in files
                if f.endswith(('.v', '.sv'))
            ]
            if not verilog_files:
                continue

            all_success = all(
                os.path.abspath(f) not in failed_file_paths
                for f in verilog_files
            )

            if all_success:
                relative_path = os.path.relpath(root, source_dir)
                target_path = os.path.join(success_dir, relative_path)

                try:
                    shutil.copytree(root, target_path, dirs_exist_ok=True)
                    logging.info("[SUCCESS COPY] Copied %s --> %s", root, target_path)
                except Exception as e:
                    logging.warning("Failed to copy success directory %s: %s", root, e)

        logging.info("All successful subdirectories have been copied to: %s", success_dir)

if __name__ == '__main__':
    main()