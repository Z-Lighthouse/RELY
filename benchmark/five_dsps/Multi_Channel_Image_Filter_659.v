// ===================================================================
// Auto-generated Multi-Channel Image Filter
// ===================================================================
module complex_image_filter_design706 (
    input clk,

    // ===================== Channel 1 (unchanged) =====================
    input signed [8:0] pix1,
    input signed [16:0] k1a,
    input signed [12:0] k1b,
    input signed [9:0] k1c,

    // ===================== Channel 2 (unchanged) =====================
    input signed [11:0] pix2,
    input signed [8:0]  k2a,
    input signed [16:0] k2b,
    input signed [9:0]  k2c,

    // ===================== Channel 3 (unchanged) =====================
    input signed [9:0] pix3,
    input signed [12:0] k3a,
    input signed [7:0]  k3b,
    input signed [16:0] k3c,

    // ===================== Channel 4 : 45-bit adder ===================
    input signed [44:0] ch4_a,
    input signed [44:0] ch4_b,

    // ===================== Channel 5 : 46-bit adder ===================
    input signed [45:0] ch5_a,
    input signed [45:0] ch5_b,

    // ===================== Final Output ===============================
    output signed [45:0] final_out
);

    // ===================================================================
    // Channel outputs
    // ===================================================================
    wire signed [31:0] channel1_out;
    wire signed [30:0] channel2_out;
    wire signed [22:0] channel3_out;
    wire signed [44:0] channel4_out;  // 45-bit add
    wire signed [45:0] channel5_out;  // 46-bit add

    // ===================================================================
    // Channel 1 processing (unchanged)
    // ===================================================================
    logic signed [31:0] stage0_ch1;
    always @(posedge clk) begin
        stage0_ch1 <= ((k1a + pix1) * k1b) + k1c;
    end
    assign channel1_out = stage0_ch1;

    // ===================================================================
    // Channel 2 processing (unchanged)
    // ===================================================================
    logic signed [30:0] stage0_ch2;
    always @(posedge clk) begin
        stage0_ch2 <= ((k2a + pix2) * k2b) + k2c;
    end
    assign channel2_out = stage0_ch2;

    // ===================================================================
    // Channel 3 processing (unchanged)
    // ===================================================================
    logic signed [22:0] stage0_ch3, stage1_ch3;
    always @(posedge clk) begin
        stage0_ch3 <= ((k3a + pix3) * k3b) + k3c;
        stage1_ch3 <= stage0_ch3;
    end
    assign channel3_out = stage1_ch3;

    // ===================================================================
    // Channel 4 : 45-bit combinational add
    // ===================================================================
    assign channel4_out = ch4_a + ch4_b;

    // ===================================================================
    // Channel 5 : 46-bit combinational add
    // ===================================================================
    assign channel5_out = ch5_a + ch5_b;

    // ===================================================================
    // Output Combination
    // Align all channels to 46 bits (max width)
    // ===================================================================
    assign final_out =
        { {14{channel1_out[31]}}, channel1_out } +   // 32 → 46
        { {15{channel2_out[30]}}, channel2_out } +   // 31 → 46
        { {23{channel3_out[22]}}, channel3_out } +   // 23 → 46
        { {1{channel4_out[44]}},  channel4_out } +   // 45 → 46
        channel5_out;                                 // 46 → 46

endmodule
