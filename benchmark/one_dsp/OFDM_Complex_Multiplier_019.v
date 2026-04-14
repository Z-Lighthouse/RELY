//
// Top-Level Module: OFDM_Complex_Multiplier
//
// Description:
//   A time-multiplexed complex multiplier.
//   This design utilizes a SINGLE instance of the 'PreAdd_Mul_Acc_Unit' core.
//
//   CHANGES:
//   - Inner DSP logic updated to (a * b) - c with 2-stage pipeline.
//   - Bit widths adjusted: A=12bit, B=9bit, Out=22bit.
//   - Final Add/Sub uses substraction logic: (P1*1)-P2 and (P3*1)-(-P4).
//
module OFDM_Complex_Multiplier (
    input clk,
    input rst_n,
    input start,              // Pulse high for one cycle to begin a new multiplication

    // Complex Inputs (A and B)
    // WIDTH CHANGE: Adapted to match DSP Core Inputs 'a' (12-bit) and 'b' (9-bit)
    input signed [11:0] ar_in,  // Real part of A -> Maps to 'a'
    input signed [11:0] ai_in,  // Imaginary part of A -> Maps to 'a'
    input signed [8:0]  br_in,  // Real part of B -> Maps to 'b'
    input signed [8:0]  bi_in,  // Imaginary part of B -> Maps to 'b'

    // Complex Output (C = A * B)
    // WIDTH CHANGE: Output set to 22 bits to match DSP output
    output reg signed [21:0] cr_out, // Real part of C
    output reg signed [21:0] ci_out, // Imaginary part of C
    output reg               valid_out // High for one cycle when outputs are valid
);

    // --- Control Logic ---
    reg [3:0] state; // States 0-8 to handle 2-cycle pipeline latency
    
    // --- Data Registers ---
    reg signed [11:0] ar_reg, ai_reg;
    reg signed [8:0]  br_reg, bi_reg;
    reg signed [21:0] p1, p2, p3, p4; // Registers to store intermediate products

    // --- DSP Core I/O ---
    wire signed [21:0] dsp_out;
    reg  signed [11:0] dsp_in_a;
    reg  signed [8:0]  dsp_in_b;
    reg  signed [15:0] dsp_in_c;

    // --- INSTANTIATE THE SINGLE DSP CORE ---
    // Core Logic: out = (a * b) - c
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
            cr_out <= 22'sd0;
            ci_out <= 22'sd0;
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
                
                // Note on DSP Operation: out = (a * b) - c
                // Latency is 2 cycles.
                
                4'd1: // Cycle 1: Feed P1 inputs (Ar * Br)
                    begin
                        // Formula: (Ar * Br) - 0
                        dsp_in_a <= ar_reg;
                        dsp_in_b <= br_reg;
                        dsp_in_c <= 16'sd0;
                        state <= 4'd2;
                    end

                4'd2: // Cycle 2: Feed P2 inputs (Ai * Bi)
                    begin
                        // Formula: (Ai * Bi) - 0
                        dsp_in_a <= ai_reg;
                        dsp_in_b <= bi_reg;
                        dsp_in_c <= 16'sd0;
                        state <= 4'd3;
                    end
                
                4'd3: // Cycle 3: Feed P3 inputs (Ar * Bi), Capture P1
                    begin
                        // P1 (from Cycle 1) is ready at output
                        p1 <= dsp_out; 

                        // Formula: (Ar * Bi) - 0
                        dsp_in_a <= ar_reg;
                        dsp_in_b <= bi_reg;
                        dsp_in_c <= 16'sd0;
                        state <= 4'd4;
                    end

                4'd4: // Cycle 4: Feed P4 inputs (Ai * Br), Capture P2
                    begin
                        // P2 is ready at output
                        p2 <= dsp_out;

                        // Formula: (Ai * Br) - 0
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
                        // DSP Logic: (a * b) - c
                        // We use: b=1. Result = a - c.
                        // Map: a = P1 (12-bit truncated), c = P2 (16-bit truncated).
                        dsp_in_a <= p1[11:0];       // Truncated P1
                        dsp_in_b <= 9'sd1;          // Multiply by 1
                        dsp_in_c <= p2[15:0];       // Truncated P2
                        state <= 4'd6;
                    end
                    
                4'd6: // Cycle 6: Feed Ci inputs (P3 + P4), Capture P4
                    begin
                        // P4 is ready at output
                        p4 <= dsp_out;

                        // Calculation: Ci = P3 + P4 = P3 - (-P4)
                        // DSP Logic: (a * b) - c
                        // Map: a = P3, c = -P4
                        dsp_in_a <= p3[11:0];       // Truncated P3
                        dsp_in_b <= 9'sd1;          // Multiply by 1
                        dsp_in_c <= -p4[15:0];      // Truncated -P4
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
//   Performs (a * b) - c with 2 pipeline stages.
//   Explicitly marked inputs as 'signed' to ensure correct complex arithmetic.
//
module PreAdd_Mul_Acc_Unit (
    input signed [11:0] a,
    input signed [8:0] b,
    input signed [15:0] c,
    input clk,
    output signed [21:0] out
);

  reg signed [21:0] stage0, stage1;

  always @(posedge clk) begin
    stage0 <= (a * b) - c;
    stage1 <= stage0;
  end

  assign out = stage1;

endmodule