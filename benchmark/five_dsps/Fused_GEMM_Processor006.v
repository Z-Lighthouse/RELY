//
// Top-Level Module: Compute_Intensive_System
//
// Description:
//   A compute-intensive system featuring a 2x2 systolic array that performs a
//   custom parallel computation, followed by a dedicated post-processing unit.
//
//   This design is architected to synthesize to exactly 5 dedicated DSP slices
//   on a target FPGA, with each 'PreAdd_Mul_Unit' mapping to one slice.
//
module Compute_Intensive_System (
    input clk,
    input rst_n,

    // Data Inputs (Signed, flattened from arrays)
    input signed [17:0] D_in_0,       // Matrix D inputs for the systolic array (Col 0)
    input signed [17:0] D_in_1,       // Matrix D inputs for the systolic array (Col 1)
    input signed [16:0] A_in_0,       // Matrix A inputs for the systolic array (Row 0)
    input signed [16:0] A_in_1,       // Matrix A inputs for the systolic array (Row 1)
    input signed [11:0] B_in_0,       // Matrix B inputs for the systolic array (Col 0)
    input signed [11:0] B_in_1,       // Matrix B inputs for the systolic array (Col 1)
    input signed [11:0] scaling_factor, // Scalar input for the post-processing stage
    
    // Data Output (Signed, bit-width updated for the new core)
    output [30:0] final_result          // Final scalar result after post-processing
);

    // Internal bus for the 2x2 matrix result from the array processor (Flattened).
    wire signed [30:0] c_00;
    wire signed [30:0] c_01;
    wire signed [30:0] c_10;
    wire signed [30:0] c_11;

    // Instantiate the 2x2 Systolic Array Processor (contains 4 core units).
    Systolic_Array_Processor array_proc_inst (
        .clk(clk),
        .rst_n(rst_n),
        .D_in_0(D_in_0), .D_in_1(D_in_1),
        .A_in_0(A_in_0), .A_in_1(A_in_1),
        .B_in_0(B_in_0), .B_in_1(B_in_1),
        .C_out_00(c_00), .C_out_01(c_01),
        .C_out_10(c_10), .C_out_11(c_11)
    );

    /*
     * Instantiate the Post-Processing Unit (5th core unit).
     *
     * This unit performs a final fused operation on the array results.
     * Function: final_result = (C[0][0] + C[1][1]) * scaling_factor
     */
    PreAdd_Mul_Unit post_processor_inst (
        .clk(clk),
        
        // Map function to core inputs: out = (d + a) * b
        .d(c_00[17:0]),   // d <= C[0][0] (truncated)
        .a(c_11[16:0]),   // a <= C[1][1] (truncated)
        .b(scaling_factor), // b <= scaling_factor
        .out(final_result)
    );

endmodule


//
// Module: Systolic_Array_Processor
//
// Description:
//   A 2x2 systolic array for the custom parallel computation C = (D + A) * B.
//   Composed of four Processing Elements arranged in a grid.
//   Ports flattened for compatibility.
//
module Systolic_Array_Processor (
    input clk,
    input rst_n,
    input signed [17:0] D_in_0,
    input signed [17:0] D_in_1,
    input signed [16:0] A_in_0,
    input signed [16:0] A_in_1,
    input signed [11:0] B_in_0,
    input signed [11:0] B_in_1,
    output signed [30:0] C_out_00,
    output signed [30:0] C_out_01,
    output signed [30:0] C_out_10,
    output signed [30:0] C_out_11
);

    // Internal wiring for systolic data propagation.
    wire signed [17:0] d_v_wire_0_to_0, d_v_wire_1_to_1; // Vertical path for D
    wire signed [16:0] a_h_wire_0_to_1, a_h_wire_1_to_1; // Horizontal path for A
    wire signed [11:0] b_v_wire_0_to_0, b_v_wire_1_to_1; // Vertical path for B

    // --- 2x2 Processing Element Array Instantiation ---
    
    // PE [0,0]
    ProcessingElement pe_00 ( 
        .clk(clk), .rst_n(rst_n), 
        .d_in(D_in_0), .a_in(A_in_0), .b_in(B_in_0), 
        .d_out(d_v_wire_0_to_0), .a_out(a_h_wire_0_to_1), .b_out(b_v_wire_0_to_0), 
        .c_out(C_out_00) 
    );

    // PE [0,1]
    ProcessingElement pe_01 ( 
        .clk(clk), .rst_n(rst_n), 
        .d_in(D_in_1), .a_in(a_h_wire_0_to_1), .b_in(B_in_1), 
        .d_out(d_v_wire_1_to_1), .a_out(), .b_out(b_v_wire_1_to_1), 
        .c_out(C_out_01) 
    );

    // PE [1,0]
    ProcessingElement pe_10 ( 
        .clk(clk), .rst_n(rst_n), 
        .d_in(d_v_wire_0_to_0), .a_in(A_in_1), .b_in(b_v_wire_0_to_0), 
        .d_out(), .a_out(a_h_wire_1_to_1), .b_out(), 
        .c_out(C_out_10) 
    );

    // PE [1,1]
    ProcessingElement pe_11 ( 
        .clk(clk), .rst_n(rst_n), 
        .d_in(d_v_wire_1_to_1), .a_in(a_h_wire_1_to_1), .b_in(b_v_wire_1_to_1), 
        .d_out(), .a_out(), .b_out(), 
        .c_out(C_out_11) 
    );

endmodule


//
// Module: ProcessingElement
//
// Description:
//   Basic building block for the systolic array (PE). Wraps one core compute
//   unit and includes data forwarding registers for systolic flow. This PE is
//   a purely feed-forward computational block.
//
module ProcessingElement (
    input clk,
    input rst_n,
    
    input signed [17:0] d_in,   // Input 'D' from top neighbor
    input signed [16:0] a_in,   // Input 'A' from left neighbor
    input signed [11:0] b_in,   // Input 'B' from top neighbor
    
    output reg signed [17:0] d_out, // Output 'D' to bottom neighbor
    output reg signed [16:0] a_out, // Output 'A' to right neighbor
    output reg signed [11:0] b_out, // Output 'B' to bottom neighbor
    output signed [30:0] c_out    // Result of the operation
);

    // Instantiate the core compute unit.
    PreAdd_Mul_Unit core_unit (
        .clk(clk),
        .d(d_in),
        .a(a_in),
        .b(b_in),
        .out(c_out) // Directly connect output
    );

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            d_out <= 18'sd0;
            a_out <= 17'sd0;
            b_out <= 12'sd0;
        end else begin
            // Systolic data forwarding for all three inputs
            d_out <= d_in;
            a_out <= a_in;
            b_out <= b_in;
        end
    end

endmodule


//
// Module: PreAdd_Mul_Unit
//
// Description:
//   Core computational unit performing a fused Pre-Add -> Multiply
//   operation: out = (d + a) * b.
//   This version has a two-stage pipeline for higher frequency timing.
//   This structure is designed to map directly to a single FPGA DSP slice.
//
module PreAdd_Mul_Unit (
    input signed [17:0] d,
    input signed [16:0] a,
    input signed [11:0] b,
    input clk,
    output [30:0] out
);

  // Two-stage pipeline registers
  reg signed [30:0] stage0, stage1;

  always @(posedge clk) begin
    stage0 <= (d + a) * b; // First stage: perform the calculation
    stage1 <= stage0;      // Second stage: register the result
  end

  assign out = stage1;

endmodule