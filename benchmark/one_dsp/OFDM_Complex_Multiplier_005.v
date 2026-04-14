//
// Top-Level Module: OFDM_Complex_Multiplier
//
// Description:
//   A time-multiplexed complex multiplier.
//   This design utilizes a SINGLE instance of the 'PreAdd_Mul_Acc_Unit' core.
//
//   CHANGES:
//   - Inner DSP logic updated to ((d + a) * b) + c with 1-stage pipeline.
//   - Bit widths adjusted: A=14bit, B=13bit, Out=29bit.
//   - State machine optimized for 1-cycle DSP latency.
//
module OFDM_Complex_Multiplier (
    input clk,
    input rst_n,
    input start,              // Pulse high for one cycle to begin a new multiplication

    // Complex Inputs (A and B)
    // WIDTH CHANGE: Adapted to match DSP Core Inputs 'd' (14-bit) and 'b' (13-bit)
    input signed [13:0] ar_in,  // Real part of A -> Maps to 'd'
    input signed [13:0] ai_in,  // Imaginary part of A -> Maps to 'd'
    input signed [12:0] br_in,  // Real part of B -> Maps to 'b'
    input signed [12:0] bi_in,  // Imaginary part of B -> Maps to 'b'

    // Complex Output (C = A * B)
    // WIDTH CHANGE: Output set to 29 bits to match DSP output
    output reg signed [28:0] cr_out, // Real part of C
    output reg signed [28:0] ci_out, // Imaginary part of C
    output reg               valid_out // High for one cycle when outputs are valid
);

    // --- Control Logic ---
    reg [2:0] state; // States 0-7 are sufficient for 1-cycle latency
    
    // --- Data Registers ---
    reg signed [13:0] ar_reg, ai_reg;
    reg signed [12:0] br_reg, bi_reg;
    reg signed [28:0] p1, p2, p3, p4; // Registers to store intermediate products

    // --- DSP Core I/O ---
    wire signed [28:0] dsp_out;
    reg  signed [10:0] dsp_in_a;
    reg  signed [12:0] dsp_in_b;
    reg  signed [15:0] dsp_in_c;
    reg  signed [13:0] dsp_in_d;

    // --- INSTANTIATE THE SINGLE DSP CORE ---
    // Core Logic: out = ((d + a) * b) + c
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
            state <= 3'd0;
            valid_out <= 1'b0;
            cr_out <= 29'sd0;
            ci_out <= 29'sd0;
        end else begin
            valid_out <= 1'b0; // Default to low

            case (state)
                3'd0: // Idle state
                    if (start) begin
                        // Latch the inputs
                        ar_reg <= ar_in;
                        ai_reg <= ai_in;
                        br_reg <= br_in;
                        bi_reg <= bi_in;
                        state <= 3'd1;
                    end
                
                // Note on DSP Operation: out = ((d + a) * b) + c
                // Latency is 1 cycle.
                
                3'd1: // Cycle 1: Feed P1 inputs (Ar * Br)
                    begin
                        // Formula: ((Ar + 0) * Br) + 0
                        dsp_in_d <= ar_reg;
                        dsp_in_a <= 11'sd0;
                        dsp_in_b <= br_reg;
                        dsp_in_c <= 16'sd0;
                        state <= 3'd2;
                    end

                3'd2: // Cycle 2: Feed P2 inputs (Ai * Bi), Capture P1
                    begin
                        // P1 (from Cycle 1) is ready at output
                        p1 <= dsp_out;

                        // Formula: ((Ai + 0) * Bi) + 0
                        dsp_in_d <= ai_reg;
                        dsp_in_a <= 11'sd0;
                        dsp_in_b <= bi_reg;
                        dsp_in_c <= 16'sd0;
                        state <= 3'd3;
                    end
                
                3'd3: // Cycle 3: Feed P3 inputs (Ar * Bi), Capture P2
                    begin
                        // P2 (from Cycle 2) is ready at output
                        p2 <= dsp_out;

                        // Formula: ((Ar + 0) * Bi) + 0
                        dsp_in_d <= ar_reg;
                        dsp_in_a <= 11'sd0;
                        dsp_in_b <= bi_reg;
                        dsp_in_c <= 16'sd0;
                        state <= 3'd4;
                    end

                3'd4: // Cycle 4: Feed P4 inputs (Ai * Br), Capture P3
                    begin
                        // P3 is ready at output
                        p3 <= dsp_out;

                        // Formula: ((Ai + 0) * Br) + 0
                        dsp_in_d <= ai_reg;
                        dsp_in_a <= 11'sd0;
                        dsp_in_b <= br_reg;
                        dsp_in_c <= 16'sd0;
                        state <= 3'd5;
                    end

                3'd5: // Cycle 5: Feed Cr inputs (P1 - P2), Capture P4
                    begin
                        // P4 is ready at output
                        p4 <= dsp_out;

                        // Calculation: Cr = P1 - P2
                        // DSP Logic: ((d + a) * b) + c
                        // We use: b=1, a=0. Result = d + c.
                        // Map: d = P1 (14-bit), c = -P2 (16-bit)
                        dsp_in_d <= p1[13:0];       // Truncated P1
                        dsp_in_c <= -p2[15:0];      // Truncated -P2
                        dsp_in_b <= 13'sd1;         // Multiply by 1
                        dsp_in_a <= 11'sd0;
                        state <= 3'd6;
                    end
                    
                3'd6: // Cycle 6: Feed Ci inputs (P3 + P4), Capture Cr
                    begin
                        // Cr is ready at output
                        cr_out <= dsp_out; 

                        // Calculation: Ci = P3 + P4
                        // Map: d = P3, c = P4, b = 1
                        dsp_in_d <= p3[13:0];       // Truncated P3
                        dsp_in_c <= p4[15:0];       // Truncated P4
                        dsp_in_b <= 13'sd1;         // Multiply by 1
                        dsp_in_a <= 11'sd0;
                        state <= 3'd7;
                    end
                
                3'd7: // Cycle 7: Capture Ci
                    begin
                        // Ci is ready at output
                        ci_out <= dsp_out;
                        valid_out <= 1'b1;
                        state <= 3'd0; // Return to idle
                    end
                    
                default:
                    state <= 3'd0;
            endcase
        end
    end

endmodule


//
// Core Computational Unit
//
// Description:
//   Replaced core logic as requested.
//   Performs ((d + a) * b) + c with 1 pipeline stage.
//
module PreAdd_Mul_Acc_Unit (
    input signed [10:0] a,
    input signed [12:0] b,
    input signed [15:0] c,
    input signed [13:0] d,
    input clk,
    output signed [28:0] out
);

  reg signed [28:0] stage0;

  always @(posedge clk) begin
    stage0 <= ((d + a) * b) + c;
  end

  assign out = stage0;

endmodule