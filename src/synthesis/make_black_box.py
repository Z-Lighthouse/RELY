#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import shutil
import argparse

def extract_number_from_filename(filename):
    """Extract number from filename (e.g., 'modified1.v' -> 1)"""
    match = re.search(r'(\d+)\.v$', filename)
    return int(match.group(1)) if match else None

def process_module_file_content(content, module_name):
    """Process module content: Remove content between ");" and "endmodule", 
    and add black box directive"""
    # Find the position of ");"
    paren_end = content.find(');')
    if paren_end == -1:
        print(f"    [WARNING] No ');' found in module file, using original content")
        return content
    
    # Find the position of "endmodule"
    endmodule_pos = content.find('endmodule', paren_end)
    if endmodule_pos == -1:
        print(f"    [WARNING] No 'endmodule' found after ');', using original content")
        return content
    
    # Extract content from the beginning to ");", then add "endmodule"
    processed_content = content[:paren_end + 2] + '\nendmodule'
    
    # Add black box directive before module declaration
    blackbox_directive = f"(* black_box = \"true\" *)\n"
    
    # Find the module declaration
    module_decl_match = re.search(r'^\s*(module\s+' + re.escape(module_name) + r'\b)', content, re.MULTILINE)
    if module_decl_match:
        # Insert the black box directive before the module declaration
        module_line = module_decl_match.group(1)
        processed_content = processed_content.replace(module_line, blackbox_directive + module_line)
    else:
        # If module declaration is not found, insert black box directive before the first "module"
        first_module_pos = processed_content.find('module')
        if first_module_pos != -1:
            processed_content = (processed_content[:first_module_pos] + 
                               blackbox_directive + 
                               processed_content[first_module_pos:])
    
    # Add header with module name and black box directive
    header = f"// Module {module_name} marked as black box for Vivado\n// Using directive: (* black_box = \"true\" *)\n\n"
    
    return header + processed_content

def find_and_process_file_pairs(root_dir, output_dir):
    """Search for file pairs in the given root directory and process them"""
    
    # Create the output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Store file pairs
    file_pairs = {}
    
    for dirpath, dirnames, filenames in os.walk(root_dir):
        modified_files = {}
        module_files = {}
        
        print(f"\n[DEBUG] Scanning directory: {dirpath}")
        print(f"[DEBUG] Found {len(filenames)} files")
        
        # Classify files: look for "modified" and "module" files with numbers in the names
        for filename in filenames:
            if filename.endswith('.v'):
                # Match modified files: containing "modified" and ending with a number
                if 'modified' in filename.lower() and re.search(r'\d+\.v$', filename):
                    num = extract_number_from_filename(filename)
                    if num is not None:
                        modified_files[num] = os.path.join(dirpath, filename)
                        print(f"[DEBUG] Found modified file: {filename} -> number {num}")
                
                # Match module files: containing "module" and ending with a number
                elif 'module' in filename.lower() and re.search(r'\d+\.v$', filename):
                    num = extract_number_from_filename(filename)
                    if num is not None:
                        module_files[num] = os.path.join(dirpath, filename)
                        print(f"[DEBUG] Found module file: {filename} -> number {num}")
        
        # Show found files
        if modified_files:
            print(f"[DEBUG] Modified files found: {list(modified_files.keys())}")
        if module_files:
            print(f"[DEBUG] Module files found: {list(module_files.keys())}")
        
        # Pair matching files
        for num in modified_files:
            if num in module_files:
                # Use subdirectory name as base name for output file
                subdir_name = os.path.basename(dirpath)
                output_filename = f"{subdir_name}_modified{num}.v"
                output_filepath = os.path.join(output_dir, output_filename)
                
                file_pairs[output_filepath] = {
                    'modified': modified_files[num],
                    'module': module_files[num],
                    'number': num,
                    'subdir': subdir_name
                }
                print(f"[DEBUG] Matched pair: modified{num}.v + module{num}.v")
    
    return file_pairs

def process_single_pair(modified_file, module_file, output_file):
    """Process a single pair of modified and module files"""
    try:
        # Read modified file content
        with open(modified_file, 'r', encoding='utf-8') as f:
            modified_content = f.read()
        
        # Read and process module file content
        with open(module_file, 'r', encoding='utf-8') as f:
            module_content = f.read()
        
        # Extract module name for black box processing
        module_name_match = re.search(r'module\s+(\w+)', module_content)
        module_name = module_name_match.group(1) if module_name_match else "unknown_module"
        
        print(f"    Processing module: {module_name}")
        
        # Process module content
        processed_module_content = process_module_file_content(module_content, module_name)
        
        # Combine modified and processed module contents
        combined_content = f"// Combined file from:\n// - {os.path.basename(modified_file)}\n// - {os.path.basename(module_file)}\n// Generated by automated processing script\n\n"
        combined_content += "// === Modified file content ===\n"
        combined_content += modified_content + "\n\n"
        combined_content += "// === Processed module (as black box) ===\n"
        combined_content += processed_module_content
        
        # Write to output file
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(combined_content)
        
        return True
        
    except Exception as e:
        print(f"    [ERROR] Failed to process file pair: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Process modifiedX.v and moduleX.v file pairs and combine them with black box directives")
    parser.add_argument("source_directory", help="Root directory to search for file pairs")
    parser.add_argument("output_directory", help="Output directory for combined files")
    
    args = parser.parse_args()
    
    source_dir = os.path.abspath(args.source_directory)
    output_dir = os.path.abspath(args.output_directory)
    
    if not os.path.isdir(source_dir):
        print(f"[ERROR] Source directory not found: {source_dir}")
        return
    
    print(f"[INFO] Searching for file pairs in: {source_dir}")
    print(f"[INFO] Output directory: {output_dir}")
    print(f"[INFO] Using black box directive: (* black_box = \"true\" *)")
    
    # Find file pairs and process them
    file_pairs = find_and_process_file_pairs(source_dir, output_dir)
    
    if not file_pairs:
        print("\n[WARNING] No matching file pairs found!")
        print("[INFO] Looking for files with pattern: *modified*X.v and *module*X.v (where X is a number) ")
        return
    
    print(f"\n[INFO] Found {len(file_pairs)} file pair(s) to process")
    
    # Process each file pair
    success_count = 0
    for output_file, files in file_pairs.items():
        print(f"\n[PROCESSING] Pair {files['number']} in '{files['subdir']}':")
        print(f"  Modified: {os.path.basename(files['modified'])}")
        print(f"  Module: {os.path.basename(files['module'])}")
        print(f"  Output: {os.path.basename(output_file)}")
        
        if process_single_pair(files['modified'], files['module'], output_file):
            success_count += 1
            print(f"  [SUCCESS] Created: {os.path.basename(output_file)}")
        else:
            print(f"  [FAILED] Failed to process pair {files['number']}")
    
    print(f"\n[SUMMARY] Successfully processed {success_count}/{len(file_pairs)} file pairs")
    print(f"[INFO] Output files saved to: {output_dir}")

if __name__ == '__main__':
    main()