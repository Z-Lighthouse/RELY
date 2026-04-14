//
// Top-Level Module: Compute_Intensive_System
//
// Description:
//   A compute-intensive system featuring a 2x2 systolic array that performs a
//   custom computation, followed by a dedicated post-processing unit.
//
//   The system is architected to synthesize to exactly 5 dedicated DSP slices
//   on a target FPGA, with each 'PreAdd_Mul_And_Unit' mapping to one slice.
//
module Compute_Intensive_System (
    input clk,
    input rst_n,

    // Control Signals
    input load_en,            // High for one cycle to initialize result registers before operation

    // Data Inputs (Flattened from arrays)
    input signed [14:0] A_in_0,       // Matrix-like A inputs for the systolic array (Row 0)
    input signed [14:0] A_in_1,       // Matrix-like A inputs for the systolic array (Row 1)
    input signed [12:0] B_in_0,       // Matrix-like B inputs for the systolic array (Col 0)
    input signed [12:0] B_in_1,       // Matrix-like B inputs for the systolic array (Col 1)
    input signed [12:0] scaling_factor, // Scalar input for the post-processing stage
    
    // Data Output (Bit-width updated for the new core)
    output [17:0] final_result          // Final scalar result after post-processing
);

    // Internal bus for the 2x2 result matrix from the systolic array (Flattened).
    wire signed [17:0] c_00;
    wire signed [17:0] c_01;
    wire signed [17:0] c_10;
    wire signed [17:0] c_11;

    // Instantiate the 2x2 Systolic Array Processor (contains 4 core units).
    Systolic_Array_Processor array_proc_inst (
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
     * This unit performs a final fused operation on the array results.
     * Function: final_result = ((-C[1][0] + C[0][1]) * scaling_factor) & C[0][0]
     */
    PreAdd_Mul_And_Unit post_processor_inst (
        .clk(clk),
        
        // Map function to core inputs: out = ((d + a) * b) & c
        .d(c_01[10:0]),       // d <= C_01 (truncated)
        .a(-c_10[14:0]),      // a <= -C_10 (truncated)
        .b(scaling_factor),   // b <= scaling_factor
        .c(c_00[16:0]),       // c <= C_00 (truncated)
        .out(final_result)
    );

endmodule


//
// Module: Systolic_Array_Processor
//
// Description:
//   A 2x2 systolic array for a custom parallel computation based on multiplication
//   and bitwise ANDing. Composed of four Processing Elements.
//   Ports flattened for compatibility.
//
module Systolic_Array_Processor (
    input clk,
    input rst_n,
    input load_en,
    input signed [14:0] A_in_0,
    input signed [14:0] A_in_1,
    input signed [12:0] B_in_0,
    input signed [12:0] B_in_1,
    output signed [17:0] C_out_00,
    output signed [17:0] C_out_01,
    output signed [17:0] C_out_10,
    output signed [17:0] C_out_11
);

    // Internal wiring for systolic data propagation.
    wire signed [14:0] a_h_wire_0_to_1, a_h_wire_1_to_1; 
    wire signed [12:0] b_v_wire_0_to_0, b_v_wire_1_to_1;

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
//   unit and includes data forwarding registers for systolic flow.
//   The internal operation is a filtering/masking, not an accumulation.
//
module ProcessingElement (
    input clk,
    input rst_n,
    input load_en,
    
    input signed [14:0] a_in,   // Input 'A' from left neighbor
    input signed [12:0] b_in,   // Input 'B' from top neighbor
    
    output reg signed [14:0] a_out, // Output 'A' to right neighbor
    output reg signed [12:0] b_out, // Output 'B' to bottom neighbor
    output signed [17:0] c_out    // Result of the filtering operation
);

    reg signed [17:0] result_reg;
    wire signed [17:0] core_out;

    // Instantiate the core compute unit. 'd' is grounded. The operation becomes
    // a multiplication followed by a bitwise AND with the previous result.
    PreAdd_Mul_And_Unit core_unit (
        .clk(clk),
        .a(a_in),
        .b(b_in),
        .c(result_reg[16:0]), // Use previous result as the mask 'c'
        .d(11'd0),            // Ground the pre-adder input 'd'
        .out(core_out)
    );

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            result_reg <= 18'd0;
            a_out <= 15'd0;
            b_out <= 13'd0;
        end else begin
            // Systolic data forwarding
            a_out <= a_in;
            b_out <= b_in;
            
            // On load_en, initialize the register to all 1s, which is the
            // identity element for bitwise AND operations.
            if (load_en) begin
                result_reg <= -1; 
            end else begin
                result_reg <= core_out;
            end
        end
    end

    assign c_out = result_reg;

endmodule


//
// Module: PreAdd_Mul_And_Unit
//
// Description:
//   Core computational unit performing a fused Pre-Add -> Multiply -> Bitwise AND
//   operation: out = ((d + a) * b) & c.
//   This is a single-stage pipelined module.
//
module PreAdd_Mul_And_Unit (
    input signed [14:0] a,
    input signed [12:0] b,
    input signed [16:0] c,
    input signed [10:0] d,
    input clk,
    output [17:0] out
);

  reg signed [17:0] stage0;

  always @(posedge clk) begin
    stage0 <= ((d + a) * b) & c;
  end

  assign out = stage0;

endmodule