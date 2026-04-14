# RELY
## Resource-Aware Cooperative Logic Synthesis for Heterogeneous FPGAs
## Introduction
**RELY** is a resource-aware cooperative logic synthesis framework specifically designed for heterogeneous FPGAs. It optimizes logic mapping and synthesis by considering the diverse hardware resources available in modern FPGAs to achieve superior area efficiency and performance.
## Requirements
- **Python 3.8.0+**
- **Pyverilog 1.3.0** 
- **Xilinx Vivado:** Required for synthesis, implementation, and generating reports (`report_utilization`, `report_design_analysis`).
- **Yosys:** Required for the baseline synthesis flow (`synth_xilinx`).
