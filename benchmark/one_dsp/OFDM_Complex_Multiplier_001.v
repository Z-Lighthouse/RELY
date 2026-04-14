//
// Top-Level Module: OFDM_Complex_Multiplier
//
// Description:
//   A time-multiplexed complex multiplier.
//   This design utilizes a SINGLE instance of the 'PreAdd_Mul_Acc_Unit' core.
//   
//   CHANGES:
//   - Adapted to new DSP core bit widths (14-bit and 13-bit inputs, 29-bit output).
//   - State machine expanded to account for 2-cycle latency in the DSP core.
//
module OFDM_Complex_Multiplier (
    input clk,
    input rst_n,
    input start,              // Pulse high for one cycle to begin a new multiplication

    // Complex Inputs (A and B)
    // WIDTH CHANGE: ar/ai reduced to 14 bits to match DSP input 'd'
    // br/bi remain 13 bits to match DSP input 'b'
    input signed [13:0] ar_in,  // Real part of A
    input signed [13:0] ai_in,  // Imaginary part of A
    input signed [12:0] br_in,  // Real part of B
    input signed [12:0] bi_in,  // Imaginary part of B

    // Complex Output (C = A * B)
    // WIDTH CHANGE: Output reduced to 29 bits to match DSP output
    output reg signed [28:0] cr_out, // Real part of C
    output reg signed [28:0] ci_out, // Imaginary part of C
    output reg               valid_out // High for one cycle when outputs are valid
);

    // --- Control Logic ---
    // State machine expanded to 4 bits to handle states 0-8
    reg [3:0] state; 
    
    // --- Data Registers ---
    // WIDTH CHANGE: Matching new input/output widths
    reg signed [13:0] ar_reg, ai_reg;
    reg signed [12:0] br_reg, bi_reg;
    reg signed [28:0] p1, p2, p3, p4; // Registers to store intermediate products

    // --- DSP Core I/O ---
    // WIDTH CHANGE: Signals updated to match PreAdd_Mul_Acc_Unit port widths
    wire signed [28:0] dsp_out;
    reg  signed [7:0]  dsp_in_a;
    reg  signed [12:0] dsp_in_b;
    reg  signed [17:0] dsp_in_c;
    reg  signed [13:0] dsp_in_d;

    // --- INSTANTIATE THE SINGLE DSP CORE ---
    PreAdd_Mul_Acc_Unit dsp_core_inst (
        .clk(clk),
        .a(dsp_in_a),
        .b(dsp_in_b),
        .c(dsp_in_c),
        .d(dsp_in_d),
        .out(dsp_out)
    );

    // --- State Machine and Data Path Control ---
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= 4'd0;
            valid_out <= 1'b0;
            cr_out <= 29'sd0;
            ci_out <= 29'sd0;
            // Reset other regs if needed
        end else begin
            valid_out <= 1'b0; // Default to low

            case (state)
                4'd0: // Idle state
                    if (start) begin
                        // Latch the inputs
                        ar_reg <= ar_in;
                        ai_reg <= ai_in;
                        br_reg <= br_in;
                        bi_reg <= bi_in;
                        state <= 4'd1;
                    end
                
                // Note on DSP Operation: out = ((d + a) * b) + c
                // Latency is now 2 cycles.
                
                4'd1: // Cycle 1: Feed P1 inputs (Ar * Br)
                    begin
                        // Map Ar -> d (14-bit), Br -> b (13-bit)
                        dsp_in_d <= ar_reg;
                        dsp_in_b <= br_reg;
                        dsp_in_a <= 8'sd0;
                        dsp_in_c <= 18'sd0;
                        state <= 4'd2;
                    end

                4'd2: // Cycle 2: Feed P2 inputs (Ai * Bi)
                    begin
                        // P1 is in stage0
                        dsp_in_d <= ai_reg;
                        dsp_in_b <= bi_reg;
                        dsp_in_a <= 8'sd0;
                        dsp_in_c <= 18'sd0;
                        state <= 4'd3;
                    end
                
                4'd3: // Cycle 3: Feed P3 inputs (Ar * Bi), Capture P1
                    begin
                        // P1 is appearing at output (latency 2 met)
                        p1 <= dsp_out;

                        dsp_in_d <= ar_reg;
                        dsp_in_b <= bi_reg;
                        dsp_in_a <= 8'sd0;
                        dsp_in_c <= 18'sd0;
                        state <= 4'd4;
                    end

                4'd4: // Cycle 4: Feed P4 inputs (Ai * Br), Capture P2
                    begin
                        // P2 is appearing at output
                        p2 <= dsp_out;

                        dsp_in_d <= ai_reg;
                        dsp_in_b <= br_reg;
                        dsp_in_a <= 8'sd0;
                        dsp_in_c <= 18'sd0;
                        state <= 4'd5;
                    end

                4'd5: // Cycle 5: Feed Cr inputs (P1 - P2), Capture P3
                    begin
                        // P3 is appearing at output
                        p3 <= dsp_out;

                        // Calculation: Cr = P1 - P2
                        // DSP Logic: ((d + a) * b) + c
                        // We set b=1, a=0. Result = d + c.
                        // Map P1 -> d, -P2 -> c
                        // WARNING: Truncation occurs here to fit 29-bit P1/P2 into 14/18-bit inputs
                        dsp_in_d <= p1[13:0];       // Truncated P1
                        dsp_in_c <= -p2[17:0];      // Truncated -P2
                        dsp_in_b <= 13'sd1;
                        dsp_in_a <= 8'sd0;
                        state <= 4'd6;
                    end
                    
                4'd6: // Cycle 6: Feed Ci inputs (P3 + P4), Capture P4
                    begin
                        // P4 is appearing at output
                        p4 <= dsp_out;

                        // Calculation: Ci = P3 + P4
                        // Map P3 -> d, P4 -> c
                        dsp_in_d <= p3[13:0];       // Truncated P3
                        dsp_in_c <= p4[17:0];       // Truncated P4
                        dsp_in_b <= 13'sd1;
                        dsp_in_a <= 8'sd0;
                        
                        state <= 4'd7;
                    end
                
                4'd7: // Cycle 7: Wait state / Capture Cr
                    begin
                        // Cr (started in state 5) is now at output (5->6->7 = 2 cycles)
                        cr_out <= dsp_out; 
                        state <= 4'd8;
                    end

                4'd8: // Cycle 8: Capture Ci
                    begin
                        // Ci (started in state 6) is now at output
                        ci_out <= dsp_out;
                        valid_out <= 1'b1;
                        state <= 4'd0; // Return to idle
                    end
                    
                default:
                    state <= 4'd0;
            endcase
        end
    end

endmodule


//
// Core Computational Unit
//
// Description:
//   Core unit performing a fused Pre-Add -> Multiply -> Accumulate operation.
//   Updated with 2 pipeline stages and specific bit widths as requested.
//
module PreAdd_Mul_Acc_Unit (
    input signed [7:0] a,
    input signed [12:0] b,
    input signed [17:0] c,
    input signed [13:0] d,
    input clk,
    output [28:0] out
);

  reg signed [28:0] stage0, stage1;

  always @(posedge clk) begin
    stage0 <= ((d + a) * b) + c;
    stage1 <= stage0;
  end

  assign out = stage1;

endmodule