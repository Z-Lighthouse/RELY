# RELY
## Resource-Aware Cooperative Logic Synthesis for Heterogeneous FPGAs
## Introduction
**RELY** is a resource-aware cooperative logic synthesis framework specifically designed for heterogeneous FPGAs. It optimizes logic mapping and synthesis by considering the diverse hardware resources available in modern FPGAs to achieve superior area efficiency and performance.
## Requirements
- **Python 3.8.0+**
- **Pyverilog 1.3.0** 
- **Xilinx Vivado V2023.2，V2024.2，V2025.2** 
- **Yosys0.54+15**

## Project Structure

```text
RELY/
├── src/                        # Core source code
│   ├──logic_isolation_template_library/         
│   ├──resource_aware_evaluation/       
│   ├──synthesis/         # Heterogeneous Synthesis Flow Scripts (RELY & Baselines)
├── benchmarks/                 # RTL design files
