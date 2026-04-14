// ===================================================================
// Auto-generated Multi-Channel Image Filter
// ===================================================================
module complex_image_filter_design703 (
    input clk,

    // ===================== Channel 1 (unchanged) =====================
    input signed [15:0] pix1,
    input signed [13:0] k1a,
    input signed [17:0] k1b,
    input signed [12:0] k1c,

    // ===================== Channel 2 (unchanged) =====================
    input signed [12:0] pix2,
    input signed [10:0] k2a,
    input signed [9:0]  k2b,
    input signed [14:0] k2c,

    // ===================== Channel 3 : 42-bit adder =====================
    input signed [41:0] ch3_a,
    input signed [41:0] ch3_b,

    // ===================== Channel 4 : 45-bit adder =====================
    input signed [44:0] ch4_a,
    input signed [44:0] ch4_b,

    // ===================== Channel 5 (unchanged) =====================
    input signed [10:0] pix5,
    input signed [8:0]  k5a,
    input signed [14:0] k5b,
    input signed [7:0]  k5c,

    // ===================== Final Output =====================
    output signed [45:0] final_out
);

    // ===================================================================
    // Channel outputs
    // ===================================================================
    wire signed [17:0] channel1_out;
    wire signed [17:0] channel2_out;
    wire signed [42:0] channel3_out;  // 42-bit add → 43
    wire signed [45:0] channel4_out;  // 45-bit add → 46 (max)
    wire signed [27:0] channel5_out;

    // ===================================================================
    // Channel 1 processing (unchanged)
    // ===================================================================
    logic signed [17:0] stage0_ch1, stage1_ch1;
    always @(posedge clk) begin
        stage0_ch1 <= ((k1a + pix1) * k1b) & k1c;
        stage1_ch1 <= stage0_ch1;
    end
    assign channel1_out = stage1_ch1;

    // ===================================================================
    // Channel 2 processing (unchanged)
    // ===================================================================
    logic signed [17:0] stage0_ch2, stage1_ch2;
    always @(posedge clk) begin
        stage0_ch2 <= ((k2a + pix2) * k2b) & k2c;
        stage1_ch2 <= stage0_ch2;
    end
    assign channel2_out = stage1_ch2;

    // ===================================================================
    // Channel 3 : 42-bit combinational add
    // ===================================================================
    assign channel3_out = ch3_a + ch3_b;

    // ===================================================================
    // Channel 4 : 45-bit combinational add
    // ===================================================================
    assign channel4_out = ch4_a + ch4_b;

    // ===================================================================
    // Channel 5 processing (unchanged)
    // ===================================================================
    logic signed [27:0] stage0_ch5, stage1_ch5;
    always @(posedge clk) begin
        stage0_ch5 <= ((k5a + pix5) * k5b) + k5c;
        stage1_ch5 <= stage0_ch5;
    end
    assign channel5_out = stage1_ch5;

    // ===================================================================
    // Output Combination
    // Align all channels to 46 bits (max width)
    // ===================================================================
    assign final_out =
        { {28{channel1_out[17]}}, channel1_out } +   // 18 → 46
        { {28{channel2_out[17]}}, channel2_out } +   // 18 → 46
        { {3{channel3_out[42]}},  channel3_out } +   // 43 → 46
        channel4_out +                               // 46
        { {18{channel5_out[27]}}, channel5_out };    // 28 → 46

endmodule
