// ===================================================================
// Auto-generated Multi-Channel Image Filter
// ===================================================================
module complex_image_filter_design710 (
    input clk,

    // ===================== Channel 1 (unchanged) =====================
    input signed [7:0] pix1,
    input signed [11:0] k1a,
    input signed [9:0] k1b,
    input signed [16:0] k1c,

    // ===================== Channel 2 (unchanged) =====================
    input signed [7:0] pix2,
    input signed [14:0] k2a,
    input signed [13:0] k2b,
    input signed [12:0] k2c,

    // ===================== Channel 3 (unchanged) =====================
    input signed [10:0] pix3,
    input signed [8:0] k3a,
    input signed [13:0] k3b,
    input signed [7:0] k3c,

    // ===================== Channel 4 : 47-bit adder ===================
    input signed [46:0] ch4_a,
    input signed [46:0] ch4_b,

    // ===================== Channel 5 : 44-bit adder ===================
    input signed [43:0] ch5_a,
    input signed [43:0] ch5_b,

    // ===================== Final Output ===============================
    output signed [47:0] final_out
);

    // ===================================================================
    // Channel outputs
    // ===================================================================
    wire signed [23:0] channel1_out;
    wire signed [30:0] channel2_out;
    wire signed [17:0] channel3_out;
    wire signed [46:0] channel4_out;  // 47-bit add
    wire signed [43:0] channel5_out;  // 44-bit add

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
    // Channel 2 processing (unchanged)
    // ===================================================================
    logic signed [30:0] stage0_ch2, stage1_ch2;
    always @(posedge clk) begin
        stage0_ch2 <= ((k2a + pix2) * k2b) + k2c;
        stage1_ch2 <= stage0_ch2;
    end
    assign channel2_out = stage1_ch2;

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
    // Channel 4 : 47-bit combinational add
    // ===================================================================
    assign channel4_out = ch4_a + ch4_b;

    // ===================================================================
    // Channel 5 : 44-bit combinational add
    // ===================================================================
    assign channel5_out = ch5_a + ch5_b;

    // ===================================================================
    // Output Combination
    // Align all channels to 48 bits (max width)
    // ===================================================================
    assign final_out =
        { {24{channel1_out[23]}}, channel1_out } +    // 24 → 48
        { {17{channel2_out[30]}}, channel2_out } +    // 31 → 48
        { {31{channel3_out[17]}}, channel3_out } +    // 18 → 48
        { {1{channel4_out[46]}}, channel4_out } +     // 47 → 48
        { {4{channel5_out[43]}}, channel5_out };      // 44 → 48

endmodule
