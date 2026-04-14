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

## RELY Logic Synthesis Workflow

This document outlines the steps involved in processing and synthesizing RTL code for FPGA designs. It includes the use of various components such as resource-aware evaluation, logic isolation, and synthesis, ultimately generating a final optimized design.


### 1. **Resource-Aware Evaluation** 
   - You can use `src/resource_aware_evaluation/data_builder.py` to convert RTL code into a JSONL format.
   - Next, run `src/resource_aware_evaluation/train.py` to execute the **resource-aware evaluation** component. This will detect and predict DSP synthesis opportunities within the RTL code.

### 2. **Logic Isolation**
   - Execute `src/logic_isolation_template_library/logic_isolation.py` to perform **logic isolation** between specialized primitives (DSPs) and generic primitives. This step ensures that the RTL code is properly partitioned for optimized synthesis.

### 3. **Black Box Annotation**
   - Based on the results of logic isolation, use `src/synthesis/make_black_box.py` to add **black box annotations** to the module and prepare the code for subsequent dual-stream synthesis. The annotations are essential for marking specialized modules for synthesis tools like Vivado.

### 4. **Synthesis**
   - For **specialized primitives** (DSP modules), call **Lakeroad** (linked format required for integration) for compilation and synthesis.
   - For **generic primitive logic**, use `src/synthesis/run_synthesis_batch_without_dsp.py` to synthesize the logic.

### 5. **Final Logic Synthesis and Connection**
   - Call `src/synthesis/get_level_and_area.py` to perform **logic connection** and obtain the final **logic synthesis results**, ensuring that all modules are integrated and synthesized efficiently.
