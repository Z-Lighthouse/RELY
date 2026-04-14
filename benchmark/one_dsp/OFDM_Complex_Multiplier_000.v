//
// Top-Level Module: OFDM_Complex_Multiplier
//
// Description:
//   A time-multiplexed complex multiplier, a core component for FFT butterfly
//   operations in OFDM demodulators. This design utilizes a SINGLE instance of the
//   'PreAdd_Mul_Acc_Unit' core to perform all required operations (4 multiplies,
//   1 add, 1 subtract) over six clock cycles.
//
//
module OFDM_Complex_Multiplier (
    input clk,
    input rst_n,
    input start,              // Pulse high for one cycle to begin a new multiplication

    // Complex Inputs (A and B)
    input signed [17:0] ar_in,  // Real part of A
    input signed [17:0] ai_in,  // Imaginary part of A
    input signed [12:0] br_in,  // Real part of B
    input signed [12:0] bi_in,  // Imaginary part of B

    // Complex Output (C = A * B)
    output reg signed [32:0] cr_out, // Real part of C
    output reg signed [32:0] ci_out, // Imaginary part of C
    output reg               valid_out // High for one cycle when outputs are valid
);

    // --- Control Logic ---
    reg [2:0] state; // State machine now needs 6 states (0-6)
    
    // --- Data Registers ---
    reg signed [17:0] ar_reg, ai_reg;
    reg signed [12:0] br_reg, bi_reg;
    reg signed [32:0] p1, p2, p3, p4; // Registers to store all four intermediate products

    // --- DSP Core I/O ---
    wire signed [32:0] dsp_out;
    reg  signed [17:0] dsp_in_a;
    reg  signed [12:0] dsp_in_b;
    reg  signed [16:0] dsp_in_c;
    reg  signed [7:0]  dsp_in_d;

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
            state <= 3'd0;
            valid_out <= 1'b0;
            cr_out <= 33'sd0;
            ci_out <= 33'sd0;
            // Reset other regs if needed
        end else begin
            valid_out <= 1'b0; // Default to low

            case (state)
                3'd0: // Idle state
                    if (start) begin
                        // Latch the inputs and start the calculation pipeline
                        ar_reg <= ar_in;
                        ai_reg <= ai_in;
                        br_reg <= br_in;
                        bi_reg <= bi_in;
                        state <= 3'd1;
                    end
                
                3'd1: // Cycle 1: Calculate P1 = Ar * Br
                    begin
                        dsp_in_a <= ar_reg;
                        dsp_in_b <= br_reg;
                        dsp_in_c <= 17'sd0;
                        dsp_in_d <= 8'sd0;
                        state <= 3'd2;
                    end

                3'd2: // Cycle 2: Calculate P2 = Ai * Bi, Store P1
                    begin
                        p1 <= dsp_out;
                        dsp_in_a <= ai_reg;
                        dsp_in_b <= bi_reg;
                        // c and d remain 0
                        state <= 3'd3;
                    end
                
                3'd3: // Cycle 3: Calculate P3 = Ar * Bi, Store P2
                    begin
                        p2 <= dsp_out;
                        dsp_in_a <= ar_reg;
                        dsp_in_b <= bi_reg;
                        // c and d remain 0
                        state <= 3'd4;
                    end

                3'd4: // Cycle 4: Calculate P4 = Ai * Br, Store P3
                    begin
                        p3 <= dsp_out;
                        dsp_in_a <= ai_reg;
                        dsp_in_b <= br_reg;
                        // c and d remain 0
                        state <= 3'd5;
                    end

                3'd5: // Cycle 5: Calculate Cr = P1 - P2, Store P4
                    begin
                        p4 <= dsp_out;
                        // Configure DSP for subtraction: ((P1 + (-P2)) * 1) + 0
                        dsp_in_d <= p1[7:0];       // d <= P1 (truncated)
                        dsp_in_a <= -p2[17:0];     // a <= -P2 (truncated)
                        dsp_in_b <= 13'sd1;        // b <= 1
                        dsp_in_c <= 17'sd0;        // c <= 0
                        state <= 3'd6;
                    end
                    
                3'd6: // Cycle 6: Calculate Ci = P3 + P4, Store Cr
                    begin
                        cr_out <= dsp_out; // Latch the final Cr value
                        
                        // Configure DSP for addition: ((P3 + P4) * 1) + 0
                        dsp_in_d <= p3[7:0];      // d <= P3 (truncated)
                        dsp_in_a <= p4[17:0];     // a <= P4 (truncated)
                        dsp_in_b <= 13'sd1;       // b <= 1
                        dsp_in_c <= 17'sd0;       // c <= 0
                        
                        valid_out <= 1'b1; // Signal that outputs will be valid next cycle
                        state <= 3'd7;
                    end
                    
                3'd7: // Output cycle
                    begin
                        ci_out <= dsp_out; // Latch the final Ci value
                        state <= 3'd0;     // Return to idle
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
//   Core unit performing a fused Pre-Add -> Multiply -> Accumulate operation.
//   This structure is designed to map directly to a single FPGA DSP slice.
//
module PreAdd_Mul_Acc_Unit (
    input signed [17:0] a,
    input signed [12:0] b,
    input signed [16:0] c,
    input signed [7:0]  d,
    input clk,
    output [32:0] out
);

  reg signed [32:0] stage0;

  always @(posedge clk) begin
    stage0 <= ((d + a) * b) + c;
  end

  assign out = stage0;

endmodule