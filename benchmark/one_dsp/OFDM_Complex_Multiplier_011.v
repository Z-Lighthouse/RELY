//
// Top-Level Module: OFDM_Complex_Multiplier
//
// Description:
//   A time-multiplexed complex multiplier.
//   This design utilizes a SINGLE instance of the 'PreAdd_Mul_Acc_Unit' core.
//
//   CHANGES:
//   - Inner DSP logic updated to (a * b) + c with 2-stage pipeline.
//   - Bit widths adjusted: A=10bit, B=8bit, Out=19bit.
//   - Final Add/Sub uses ports 'c' (16-bit) and 'a' (10-bit) with b=1.
//
module OFDM_Complex_Multiplier (
    input clk,
    input rst_n,
    input start,              // Pulse high for one cycle to begin a new multiplication

    // Complex Inputs (A and B)
    // WIDTH CHANGE: Adapted to match DSP Core Inputs 'a' (10-bit) and 'b' (8-bit)
    input signed [9:0] ar_in,   // Real part of A -> Maps to 'a'
    input signed [9:0] ai_in,   // Imaginary part of A -> Maps to 'a'
    input signed [7:0] br_in,   // Real part of B -> Maps to 'b'
    input signed [7:0] bi_in,   // Imaginary part of B -> Maps to 'b'

    // Complex Output (C = A * B)
    // WIDTH CHANGE: Output set to 19 bits to match DSP output
    output reg signed [18:0] cr_out, // Real part of C
    output reg signed [18:0] ci_out, // Imaginary part of C
    output reg               valid_out // High for one cycle when outputs are valid
);

    // --- Control Logic ---
    reg [3:0] state; // States 0-8 to handle 2-cycle pipeline latency
    
    // --- Data Registers ---
    reg signed [9:0] ar_reg, ai_reg;
    reg signed [7:0] br_reg, bi_reg;
    reg signed [18:0] p1, p2, p3, p4; // Registers to store intermediate products

    // --- DSP Core I/O ---
    wire signed [18:0] dsp_out;
    reg  signed [9:0]  dsp_in_a;
    reg  signed [7:0]  dsp_in_b;
    reg  signed [15:0] dsp_in_c;

    // --- INSTANTIATE THE SINGLE DSP CORE ---
    // Core Logic: out = (a * b) + c
    PreAdd_Mul_Acc_Unit dsp_core_inst (
        .clk(clk),
        .a(dsp_in_a),
        .b(dsp_in_b),
        .c(dsp_in_c),
        .out(dsp_out)
    );

    // --- State Machine and Data Path Control ---
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= 4'd0;
            valid_out <= 1'b0;
            cr_out <= 19'sd0;
            ci_out <= 19'sd0;
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
                
                // Note on DSP Operation: out = (a * b) + c
                // Latency is 2 cycles.
                
                4'd1: // Cycle 1: Feed P1 inputs (Ar * Br)
                    begin
                        // Formula: (Ar * Br) + 0
                        dsp_in_a <= ar_reg;
                        dsp_in_b <= br_reg;
                        dsp_in_c <= 16'sd0;
                        state <= 4'd2;
                    end

                4'd2: // Cycle 2: Feed P2 inputs (Ai * Bi)
                    begin
                        // Formula: (Ai * Bi) + 0
                        dsp_in_a <= ai_reg;
                        dsp_in_b <= bi_reg;
                        dsp_in_c <= 16'sd0;
                        state <= 4'd3;
                    end
                
                4'd3: // Cycle 3: Feed P3 inputs (Ar * Bi), Capture P1
                    begin
                        // P1 (from Cycle 1) is ready at output
                        p1 <= dsp_out; 

                        // Formula: (Ar * Bi) + 0
                        dsp_in_a <= ar_reg;
                        dsp_in_b <= bi_reg;
                        dsp_in_c <= 16'sd0;
                        state <= 4'd4;
                    end

                4'd4: // Cycle 4: Feed P4 inputs (Ai * Br), Capture P2
                    begin
                        // P2 is ready at output
                        p2 <= dsp_out;

                        // Formula: (Ai * Br) + 0
                        dsp_in_a <= ai_reg;
                        dsp_in_b <= br_reg;
                        dsp_in_c <= 16'sd0;
                        state <= 4'd5;
                    end

                4'd5: // Cycle 5: Feed Cr inputs (P1 - P2), Capture P3
                    begin
                        // P3 is ready at output
                        p3 <= dsp_out;

                        // Calculation: Cr = P1 - P2
                        // DSP Logic: (a * b) + c
                        // Set b=1. Result = a + c.
                        // We have inputs 'a' (10-bit) and 'c' (16-bit).
                        // Map P1 to 'c' (wider) and -P2 to 'a' (narrower).
                        // WARNING: Truncation occurs! P1(19->16), P2(19->10)
                        dsp_in_c <= p1[15:0];       // Truncated P1
                        dsp_in_a <= -p2[9:0];       // Truncated -P2
                        dsp_in_b <= 8'sd1;          // Multiply by 1
                        state <= 4'd6;
                    end
                    
                4'd6: // Cycle 6: Feed Ci inputs (P3 + P4), Capture P4
                    begin
                        // P4 is ready at output
                        p4 <= dsp_out;

                        // Calculation: Ci = P3 + P4
                        // Map P3 to 'c' (wider) and P4 to 'a' (narrower)
                        dsp_in_c <= p3[15:0];       // Truncated P3
                        dsp_in_a <= p4[9:0];        // Truncated P4
                        dsp_in_b <= 8'sd1;          // Multiply by 1
                        state <= 4'd7;
                    end
                
                4'd7: // Cycle 7: Capture Cr
                    begin
                        // Cr is ready at output
                        cr_out <= dsp_out; 
                        state <= 4'd8;
                    end

                4'd8: // Cycle 8: Capture Ci
                    begin
                        // Ci is ready at output
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
//   Replaced core logic as requested.
//   Performs (a * b) + c with 2 pipeline stages.
//
module PreAdd_Mul_Acc_Unit (
    input signed [9:0] a,
    input signed [7:0] b,
    input signed [15:0] c,
    input clk,
    output signed [18:0] out
);

  reg signed [18:0] stage0, stage1;

  always @(posedge clk) begin
    stage0 <= (a * b) + c;
    stage1 <= stage0;
  end

  assign out = stage1;

endmodule