# setup build env
set RTL_FILE {__RTL_FILE__}
set FPGA_PART {__FPGA_PART__}
set OUTPUT_DIR {__OUTPUT_DIR__}

# run in memory to save time
create_project -in_memory -part $FPGA_PART

# include rtl source
add_files -norecurse $RTL_FILE
set_property FILE_TYPE {SystemVerilog} [get_files $RTL_FILE]

puts "Detecting top module and updating compile order..."
update_compile_order -fileset sources_1

# run synthesis
# note: -max_dsp 0 to avoid using dsp primitives
synth_design \
    -part $FPGA_PART \
    -directive default \
    -max_dsp 0

puts "Synthesis finished, generating reports now..."

# export utilization, timing and gate-level netlist
report_utilization -file [file join $OUTPUT_DIR "utilization_report.rpt"]
report_timing_summary -file [file join $OUTPUT_DIR "timing_summary_report.rpt"]
write_verilog -force [file join $OUTPUT_DIR "gate_level_netlist.v"]

puts "All outputs saved to $OUTPUT_DIR"

close_project