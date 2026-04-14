// ===================================================================
// Auto-generated Multi-Channel Image Filter
// ===================================================================
module complex_image_filter_design713 (
    input clk,

    // ===================== Channel 1 : 45-bit adder ==================
    input signed [44:0] ch1_a,
    input signed [44:0] ch1_b,

    // ===================== Channel 2 (unchanged) =====================
    input signed [14:0] pix2,
    input signed [16:0] k2a,
    input signed [11:0] k2b,
    input signed [9:0]  k2c,

    // ===================== Channel 3 : 46-bit adder ==================
    input signed [45:0] ch3_a,
    input signed [45:0] ch3_b,

    // ===================== Channel 4 (unchanged) =====================
    input signed [8:0] pix4,
    input signed [9:0] k4a,
    input signed [12:0] k4b,
    input signed [14:0] k4c,

    // ===================== Channel 5 (unchanged) =====================
    input signed [9:0] pix5,
    input signed [16:0] k5a,
    input signed [8:0] k5b,
    input signed [7:0] k5c,

    // ===================== Final Output ===============================
    output signed [46:0] final_out
);

    // ===================================================================
    // Channel outputs
    // ===================================================================
    wire signed [44:0] channel1_out;  // 45-bit adder
    wire signed [30:0] channel2_out;
    wire signed [45:0] channel3_out;  // 46-bit adder
    wire signed [24:0] channel4_out;
    wire signed [27:0] channel5_out;

    // ===================================================================
    // Channel 1 : 45-bit combinational add
    // ===================================================================
    assign channel1_out = ch1_a + ch1_b;

    // ===================================================================
    // Channel 2 processing (unchanged)
    // ===================================================================
    logic signed [30:0] stage0_ch2;
    always @(posedge clk) begin
        stage0_ch2 <= ((k2a + pix2) * k2b) + k2c;
    end
    assign channel2_out = stage0_ch2;

    // ===================================================================
    // Channel 3 : 46-bit combinational add
    // ===================================================================
    assign channel3_out = ch3_a + ch3_b;

    // ===================================================================
    // Channel 4 processing (unchanged)
    // ===================================================================
    logic signed [24:0] stage0_ch4;
    always @(posedge clk) begin
        stage0_ch4 <= ((k4a + pix4) * k4b) + k4c;
    end
    assign channel4_out = stage0_ch4;

    // ===================================================================
    // Channel 5 processing (unchanged)
    // ===================================================================
    logic signed [27:0] stage0_ch5;
    always @(posedge clk) begin
        stage0_ch5 <= ((k5a + pix5) * k5b) - k5c;
    end
    assign channel5_out = stage0_ch5;

    // ===================================================================
    // Output Combination
    // Align all channels to 47 bits (max width)
    // ===================================================================
    assign final_out =
        { {2{channel1_out[44]}}, channel1_out } +     // 45 → 47
        { {16{channel2_out[30]}}, channel2_out } +    // 31 → 47
        { {1{channel3_out[45]}}, channel3_out } +     // 46 → 47
        { {22{channel4_out[24]}}, channel4_out } +    // 25 → 47
        { {20{channel5_out[27]}}, channel5_out };     // 28 → 47

endmodule
