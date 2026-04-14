//
// Top-Level Module: OFDM_Complex_Multiplier
//
// Description:
//   A time-multiplexed complex multiplier.
//   This design utilizes a SINGLE instance of the 'PreAdd_Mul_Acc_Unit' core.
//
//   CHANGES:
//   - Inner DSP logic updated to (d + a) * b with 2-stage pipeline.
//   - Bit widths adjusted: A=18bit, B=12bit, Out=31bit.
//   - Final accumulation uses the pre-adder structure ((d+a)*1).
//
module OFDM_Complex_Multiplier (
    input clk,
    input rst_n,
    input start,              // Pulse high for one cycle to begin a new multiplication

    // Complex Inputs (A and B)
    // WIDTH CHANGE: Adapted to match DSP Core Inputs 'd' (18-bit) and 'b' (12-bit)
    input signed [17:0] ar_in,  // Real part of A
    input signed [17:0] ai_in,  // Imaginary part of A
    input signed [11:0] br_in,  // Real part of B
    input signed [11:0] bi_in,  // Imaginary part of B

    // Complex Output (C = A * B)
    // WIDTH CHANGE: Output set to 31 bits to match DSP internal registers
    output reg signed [30:0] cr_out, // Real part of C
    output reg signed [30:0] ci_out, // Imaginary part of C
    output reg               valid_out // High for one cycle when outputs are valid
);

    // --- Control Logic ---
    reg [3:0] state; // States 0-8 to handle pipeline latency
    
    // --- Data Registers ---
    reg signed [17:0] ar_reg, ai_reg;
    reg signed [11:0] br_reg, bi_reg;
    reg signed [30:0] p1, p2, p3, p4; // Registers to store intermediate products

    // --- DSP Core I/O ---
    wire signed [30:0] dsp_out;
    reg  signed [17:0] dsp_in_d;
    reg  signed [10:0] dsp_in_a;
    reg  signed [11:0] dsp_in_b;

    // --- INSTANTIATE THE SINGLE DSP CORE ---
    // The core now strictly matches the provided snippet: (d + a) * b
    PreAdd_Mul_Acc_Unit dsp_core_inst (
        .clk(clk),
        .d(dsp_in_d),
        .a(dsp_in_a),
        .b(dsp_in_b),
        .out(dsp_out)
    );

    // --- State Machine and Data Path Control ---
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= 4'd0;
            valid_out <= 1'b0;
            cr_out <= 31'sd0;
            ci_out <= 31'sd0;
            // Reset regs if needed
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
                
                // Note on DSP Operation: out = (d + a) * b
                // Latency is 2 cycles.
                
                4'd1: // Cycle 1: Feed P1 inputs (Ar * Br)
                    begin
                        // Formula: (Ar + 0) * Br
                        dsp_in_d <= ar_reg;
                        dsp_in_a <= 11'sd0;
                        dsp_in_b <= br_reg;
                        state <= 4'd2;
                    end

                4'd2: // Cycle 2: Feed P2 inputs (Ai * Bi)
                    begin
                        // Formula: (Ai + 0) * Bi
                        dsp_in_d <= ai_reg;
                        dsp_in_a <= 11'sd0;
                        dsp_in_b <= bi_reg;
                        state <= 4'd3;
                    end
                
                4'd3: // Cycle 3: Feed P3 inputs (Ar * Bi), Capture P1
                    begin
                        // P1 (from Cycle 1) is now at output
                        p1 <= dsp_out; 

                        // Formula: (Ar + 0) * Bi
                        dsp_in_d <= ar_reg;
                        dsp_in_a <= 11'sd0;
                        dsp_in_b <= bi_reg;
                        state <= 4'd4;
                    end

                4'd4: // Cycle 4: Feed P4 inputs (Ai * Br), Capture P2
                    begin
                        // P2 (from Cycle 2) is now at output
                        p2 <= dsp_out;

                        // Formula: (Ai + 0) * Br
                        dsp_in_d <= ai_reg;
                        dsp_in_a <= 11'sd0;
                        dsp_in_b <= br_reg;
                        state <= 4'd5;
                    end

                4'd5: // Cycle 5: Feed Cr inputs (P1 - P2), Capture P3
                    begin
                        // P3 is at output
                        p3 <= dsp_out;

                        // Calculation: Cr = P1 - P2
                        // DSP Logic: (d + a) * b
                        // Map: d = P1, a = -P2, b = 1
                        // Result: (P1 + (-P2)) * 1
                        // WARNING: Truncation occurs! P1(31->18), P2(31->11)
                        dsp_in_d <= p1[17:0];       // Truncated P1
                        dsp_in_a <= -p2[10:0];      // Truncated -P2 (Unary minus for subtraction)
                        dsp_in_b <= 12'sd1;         // Multiply by 1
                        state <= 4'd6;
                    end
                    
                4'd6: // Cycle 6: Feed Ci inputs (P3 + P4), Capture P4
                    begin
                        // P4 is at output
                        p4 <= dsp_out;

                        // Calculation: Ci = P3 + P4
                        // Map: d = P3, a = P4, b = 1
                        // Result: (P3 + P4) * 1
                        // WARNING: Truncation occurs!
                        dsp_in_d <= p3[17:0];       // Truncated P3
                        dsp_in_a <= p4[10:0];       // Truncated P4
                        dsp_in_b <= 12'sd1;         // Multiply by 1
                        state <= 4'd7;
                    end
                
                4'd7: // Cycle 7: Capture Cr
                    begin
                        // Cr is at output
                        cr_out <= dsp_out; 
                        state <= 4'd8;
                    end

                4'd8: // Cycle 8: Capture Ci
                    begin
                        // Ci is at output
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
//   Performs (d + a) * b with 2 pipeline stages.
//
module PreAdd_Mul_Acc_Unit (
    input signed [17:0] d,
    input signed [10:0] a,
    input signed [11:0] b,
    input clk,
    output signed [30:0] out
);

  reg signed [30:0] stage0, stage1;

  always @(posedge clk) begin
    stage0 <= (d + a) * b;
    stage1 <= stage0;
  end

  assign out = stage1;

endmodule