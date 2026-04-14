//
// Top-Level Module: Compute_Intensive_System
//
// Description:
//   A compute-intensive system demonstrating a common ML accelerator pattern.
//   It combines a 2x2 GEMM systolic array for matrix multiplication with a
//   dedicated post-processing unit for result fusion.
//
//   This design is architected to synthesize to exactly 5 dedicated DSP slices
//   on a target FPGA, with each 'PreAdd_Mul_Acc_Unit' mapping to one slice.
//
module Compute_Intensive_System (
    input clk,
    input rst_n,

    // Control Signals
    input load_en,            // High for one cycle to reset accumulators before a new operation

    // Data Inputs (Flattened from arrays)
    input signed [7:0]  A_in_0,       // Matrix A inputs for the GEMM accelerator (Row 0)
    input signed [7:0]  A_in_1,       // Matrix A inputs for the GEMM accelerator (Row 1)
    input signed [13:0] B_in_0,       // Matrix B inputs for the GEMM accelerator (Col 0)
    input signed [13:0] B_in_1,       // Matrix B inputs for the GEMM accelerator (Col 1)
    input signed [13:0] scaling_factor, // Scalar input for the post-processing stage
    
    // Data Output (Bit-width updated for the new core)
    output [24:0] final_result          // Final scalar result after post-processing
);

    // Internal bus for the 2x2 matrix result from the GEMM stage (Flattened).
    wire signed [24:0] c_00;
    wire signed [24:0] c_01;
    wire signed [24:0] c_10;
    wire signed [24:0] c_11;

    // Instantiate the 2x2 GEMM Accelerator (contains 4 core units).
    GEMM_Accelerator gemm_accel_inst (
        .clk(clk),
        .rst_n(rst_n),
        .load_en(load_en),
        .A_in_0(A_in_0), .A_in_1(A_in_1),
        .B_in_0(B_in_0), .B_in_1(B_in_1),
        .C_out_00(c_00), .C_out_01(c_01),
        .C_out_10(c_10), .C_out_11(c_11)
    );

    /*
     * Instantiate the Post-Processing Unit (5th core unit).
     *
     * This unit performs a final fused operation on the GEMM results.
     * Function: final_result = C[0][0] + scaling_factor * (C[0][1] - C[1][0])
     * This utilizes the full (d+a)*b+c capability of the core unit.
     */
    PreAdd_Mul_Acc_Unit post_processor_inst (
        .clk(clk),
        
        // Map function to core inputs: out = ((d + a) * b) + c
        // Connections are updated for the new port widths.
        .d(c_01[8:0]),    // d <= C[0][1] (truncated)
        .a(-c_10[7:0]),   // a <= -C[1][0]
        .b(scaling_factor), // b <= scaling_factor
        .c(c_00[16:0]),   // c <= C[0][0] (truncated)
        .out(final_result)
    );

endmodule


//
// Module: GEMM_Accelerator
//
// Description:
//   A 2x2 systolic array for matrix multiplication (C = C + A*B).
//   Composed of four Processing Elements arranged in a grid.
//   Ports flattened for compatibility.
//
module GEMM_Accelerator (
    input clk,
    input rst_n,
    input load_en,
    input signed [7:0]  A_in_0,
    input signed [7:0]  A_in_1,
    input signed [13:0] B_in_0,
    input signed [13:0] B_in_1,
    output signed [24:0] C_out_00,
    output signed [24:0] C_out_01,
    output signed [24:0] C_out_10,
    output signed [24:0] C_out_11
);

    // Internal wiring for systolic data propagation.
    wire signed [7:0]  a_h_wire_0_to_1, a_h_wire_1_to_1; 
    wire signed [13:0] b_v_wire_0_to_0, b_v_wire_1_to_1;

    // --- 2x2 Processing Element Array Instantiation ---
    
    // PE [0,0]
    ProcessingElement pe_00 ( 
        .clk(clk), .rst_n(rst_n), .load_en(load_en), 
        .a_in(A_in_0),           .b_in(B_in_0), 
        .a_out(a_h_wire_0_to_1), .b_out(b_v_wire_0_to_0), 
        .c_out(C_out_00) 
    );

    // PE [0,1]
    ProcessingElement pe_01 ( 
        .clk(clk), .rst_n(rst_n), .load_en(load_en), 
        .a_in(a_h_wire_0_to_1),  .b_in(B_in_1), 
        .a_out(),                .b_out(b_v_wire_1_to_1), 
        .c_out(C_out_01) 
    );

    // PE [1,0]
    ProcessingElement pe_10 ( 
        .clk(clk), .rst_n(rst_n), .load_en(load_en), 
        .a_in(A_in_1),           .b_in(b_v_wire_0_to_0), 
        .a_out(a_h_wire_1_to_1), .b_out(), 
        .c_out(C_out_10) 
    );

    // PE [1,1]
    ProcessingElement pe_11 ( 
        .clk(clk), .rst_n(rst_n), .load_en(load_en), 
        .a_in(a_h_wire_1_to_1),  .b_in(b_v_wire_1_to_1), 
        .a_out(),                .b_out(), 
        .c_out(C_out_11) 
    );

endmodule


//
// Module: ProcessingElement
//
// Description:
//   Basic building block for the systolic array (PE). Wraps one core compute
//   unit to function as a Multiply-Accumulate (MAC) engine with data
//   forwarding registers for systolic flow.
//
module ProcessingElement (
    input clk,
    input rst_n,
    input load_en,
    
    input signed [7:0]  a_in,   // Input 'A' from left neighbor
    input signed [13:0] b_in,   // Input 'B' from top neighbor
    
    output reg signed [7:0]  a_out, // Output 'A' to right neighbor
    output reg signed [13:0] b_out, // Output 'B' to bottom neighbor
    output signed [24:0] c_out    // Accumulated result
);

    reg signed [24:0] accumulator;
    wire signed [24:0] mac_out;

    // Instantiate the core compute unit. It is configured as a standard MAC
    // engine (a*b + c) by grounding the pre-adder input 'd' to zero.
    PreAdd_Mul_Acc_Unit mac_unit (
        .clk(clk),
        .a(a_in),
        .b(b_in),
        .c(accumulator[16:0]), // Connect to new c width
        .d(9'd0),              // Ground new d width
        .out(mac_out)
    );

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            accumulator <= 25'd0;
            a_out <= 8'd0;
            b_out <= 14'd0;
        end else begin
            // Systolic data forwarding
            a_out <= a_in;
            b_out <= b_in;
            
            // Accumulate or load/reset
            if (load_en) begin
                accumulator <= 25'd0; 
            end else begin
                accumulator <= mac_out;
            end
        end
    end

    assign c_out = accumulator;

endmodule


//
// Module: PreAdd_Mul_Acc_Unit
//
// Description:
//   Core computational unit performing a fused Pre-Add -> Multiply -> Accumulate
//   operation. This version has a two-stage pipeline for higher frequency timing.
//   out = ((d + a) * b) + c, with a 2-cycle latency.
//   This structure is designed to map directly to a single FPGA DSP slice
//   utilizing its internal pipeline registers.
//
module PreAdd_Mul_Acc_Unit (
    input signed [7:0]  a,
    input signed [13:0] b,
    input signed [16:0] c,
    input signed [8:0]  d,
    input clk,
    output [24:0] out
);

  // Two-stage pipeline registers
  reg signed [24:0] stage0, stage1;

  always @(posedge clk) begin
    stage0 <= ((d + a) * b) + c; // First stage: perform the calculation
    stage1 <= stage0;            // Second stage: register the result
  end

  assign out = stage1;

endmodule