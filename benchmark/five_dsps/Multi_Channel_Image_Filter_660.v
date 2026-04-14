// ===================================================================
// Auto-generated Multi-Channel Image Filter
// ===================================================================
module complex_image_filter_design707 (
    input clk,

    // ===================== Channel 1 : 46-bit adder ===================
    input signed [45:0] ch1_a,
    input signed [45:0] ch1_b,

    // ===================== Channel 2 : 44-bit adder ===================
    input signed [43:0] ch2_a,
    input signed [43:0] ch2_b,

    // ===================== Channel 3 (unchanged) =====================
    input signed [10:0] pix3,
    input signed [8:0] k3a,
    input signed [13:0] k3b,
    input signed [7:0] k3c,

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
    wire signed [45:0] channel1_out;  // 46-bit add
    wire signed [43:0] channel2_out;  // 44-bit add
    wire signed [17:0] channel3_out;
    wire signed [24:0] channel4_out;
    wire signed [29:0] channel5_out;

    // ===================================================================
    // Channel 1 : 46-bit combinational add
    // ===================================================================
    assign channel1_out = ch1_a + ch1_b;

    // ===================================================================
    // Channel 2 : 44-bit combinational add
    // ===================================================================
    assign channel2_out = ch2_a + ch2_b;

    // ===================================================================
    // Channel 3 processing (unchanged)
    // ===================================================================
    logic signed [17:0] stage0_ch3, stage1_ch3;
    always @(posedge clk) begin
        stage0_ch3 <= ((k3a + pix3) * k3b) & k3c;
        stage1_ch3 <= stage0_ch3;
    end
    assign channel3_out = stage1_ch3;

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
        channel1_out +                                // 46
        { {2{channel2_out[43]}}, channel2_out } +    // 44 → 46
        { {28{channel3_out[17]}}, channel3_out } +   // 18 → 46
        { {22{channel4_out[24]}}, channel4_out } +   // 25 → 46
        { {16{channel5_out[29]}}, channel5_out };    // 30 → 46

endmodule
