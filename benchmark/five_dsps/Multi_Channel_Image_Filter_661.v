// ===================================================================
// Auto-generated Multi-Channel Image Filter
// ===================================================================
module complex_image_filter_design708 (
    input clk,

    // ===================== Channel 1 (unchanged) =====================
    input signed [7:0] pix1,
    input signed [11:0] k1a,
    input signed [9:0] k1b,
    input signed [16:0] k1c,

    // ===================== Channel 2 : 45-bit adder ===================
    input signed [44:0] ch2_a,
    input signed [44:0] ch2_b,

    // ===================== Channel 3 : 44-bit adder ===================
    input signed [43:0] ch3_a,
    input signed [43:0] ch3_b,

    // ===================== Channel 4 (unchanged) =====================
    input signed [14:0] pix4,
    input signed [11:0] k4a,
    input signed [7:0]  k4b,
    input signed [8:0]  k4c,

    // ===================== Channel 5 (unchanged) =====================
    input signed [14:0] pix5,
    input signed [16:0] k5a,
    input signed [10:0] k5b,
    input signed [13:0] k5c,

    // ===================== Final Output ===============================
    output signed [45:0] final_out
);

    // ===================================================================
    // Channel outputs
    // ===================================================================
    wire signed [23:0] channel1_out;
    wire signed [44:0] channel2_out;  // 45-bit add
    wire signed [43:0] channel3_out;  // 44-bit add
    wire signed [24:0] channel4_out;
    wire signed [29:0] channel5_out;

    // ===================================================================
    // Channel 1 processing (unchanged)
    // ===================================================================
    logic signed [23:0] stage0_ch1, stage1_ch1;
    always @(posedge clk) begin
        stage0_ch1 <= ((k1a + pix1) * k1b) + k1c;
        stage1_ch1 <= stage0_ch1;
    end
    assign channel1_out = stage1_ch1;

    // ===================================================================
    // Channel 2 : 45-bit combinational add
    // ===================================================================
    assign channel2_out = ch2_a + ch2_b;

    // ===================================================================
    // Channel 3 : 44-bit combinational add
    // ===================================================================
    assign channel3_out = ch3_a + ch3_b;

    // ===================================================================
    // Channel 4 processing (unchanged)
    // ===================================================================
    logic signed [24:0] stage0_ch4, stage1_ch4;
    always @(posedge clk) begin
        stage0_ch4 <= ((k4a + pix4) * k4b) + k4c;
        stage1_ch4 <= stage0_ch4;
    end
    assign channel4_out = stage1_ch4;

    // ===================================================================
    // Channel 5 processing (unchanged)
    // ===================================================================
    logic signed [29:0] stage0_ch5;
    always @(posedge clk) begin
        stage0_ch5 <= ((k5a + pix5) * k5b) + k5c;
    end
    assign channel5_out = stage0_ch5;

    // ===================================================================
    // Output Combination
    // Align all channels to 46 bits (max width)
    // ===================================================================
    assign final_out =
        { {22{channel1_out[23]}}, channel1_out } +    // 24 → 46
        { {1{channel2_out[44]}}, channel2_out } +     // 45 → 46
        { {2{channel3_out[43]}}, channel3_out } +     // 44 → 46
        { {22{channel4_out[24]}}, channel4_out } +    // 25 → 46
        { {16{channel5_out[29]}}, channel5_out };     // 30 → 46

endmodule
