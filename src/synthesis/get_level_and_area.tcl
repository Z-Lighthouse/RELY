# parameters from python script
set FPGA_PART {__FPGA_PART__}
# format: "file_path,top_module,output_subdir_path"
{__NETLIST_LIST_TCL__}

# init in-memory project
create_project -in_memory -part $FPGA_PART

# process each netlist in the list
foreach netlist_item $NETLIST_LIST_TCL {
    
    # parse the comma-separated string
    set netlist_info [split $netlist_item ","]
    set netlist_file [lindex $netlist_info 0]
    set basename [lindex $netlist_info 1] 
    set output_dir [lindex $netlist_info 2] 
    
    set file_rootname [file rootname [file tail $netlist_file]]

    puts "Analyzing: $file_rootname (Top: $basename)"
    
    # cleanup any existing design before starting new iteration
    if {[get_designs] != ""} {
        close_design
    }
    
    # remove old files from sources_1 to avoid conflicts
    if {[get_files -of_objects [get_filesets sources_1]] != ""} {
        remove_files -fileset sources_1 [get_files -of_objects [get_filesets sources_1]]
    }

    file mkdir $output_dir
    
    # load verilog source
    if {[catch {read_verilog $netlist_file} result]} {
        puts "Error: Failed to read $netlist_file - $result"
        continue
    }

    # set top module and refresh compile order
    if {$basename ne ""} {
        set_property top $basename [current_fileset]
    }
    
    update_compile_order -fileset sources_1 
    
    # link design to target fpga part
    if {[catch {link_design -name linked_$basename -part $FPGA_PART} result]} {
        puts "Error: Failed to link design $basename - $result"
        if {[get_designs] != ""} {close_design}
        continue
    }
    
    # save the linked netlist for reference
    set output_netlist_path [file join $output_dir "${file_rootname}_linked.v"]
    puts "Writing linked netlist to: $output_netlist_path"
    if {[catch {write_verilog -force $output_netlist_path} result]} {
        puts "Warning: Failed to write netlist for $basename"
    }
    
    # generate reports on the linked design
    
    # logic level distribution
    set output_rpt_level [file join $output_dir "${file_rootname}_logic_level_distribution.rpt"]
    puts "Generating Logic Level Distribution report: $output_rpt_level"
    report_design_analysis -logic_level_distribution -file $output_rpt_level
    
    # area / utilization
    set output_rpt_util [file join $output_dir "${file_rootname}_utilization_report.rpt"]
    puts "Generating Utilization report: $output_rpt_util"
    report_utilization -file $output_rpt_util
    
    # reset for next file
    if {[get_designs] != ""} {
        close_design
    }
}

puts "Batch analysis complete. All reports saved."

# force exit batch mode
exit