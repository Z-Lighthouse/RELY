# synthesis script for batch processing
# parameters passed from python script
set RTL_FILE {__RTL_FILE__}
set FPGA_PART {__FPGA_PART__}
set OUTPUT_DIR {__OUTPUT_DIR__}

# init in-memory project
create_project -in_memory -part $FPGA_PART

# add source
add_files -norecurse $RTL_FILE
set_property FILE_TYPE {SystemVerilog} [get_files $RTL_FILE]

# auto detect top level
puts "Updating compile order..."
update_compile_order -fileset sources_1

# kick off synthesis
# using default directive for now
synth_design \
    -part $FPGA_PART \
    -directive default 

puts "Synthesis done. Dumping reports to $OUTPUT_DIR"

# get utilization and timing reports
report_utilization -file [file join $OUTPUT_DIR "utilization_report.rpt"]
report_timing_summary -file [file join $OUTPUT_DIR "timing_summary_report.rpt"]

# export netlist
write_verilog -force [file join $OUTPUT_DIR "gate_level_netlist.v"]

close_project