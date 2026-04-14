// ===================================================================
// Auto-generated Multi-Channel Image Filter
// ===================================================================
module complex_image_filter_design705 (
    input clk,

    // ------------------- Channel 1 : 44-bit adder -------------------
    input  signed [43:0] ch1_a,
    input  signed [43:0] ch1_b,

    // ------------------- Channel 2 (unchanged) -------------------
    input signed [17:0] pix2,
    input signed [17:0] k2a,
    input signed [12:0] k2b,
    input signed [9:0] k2c,

    // ------------------- Channel 3 (unchanged) -------------------
    input signed [14:0] pix3,
    input signed [14:0] k3a,
    input signed [9:0] k3b,
    input signed [7:0] k3c,

    // ------------------- Channel 4 : 45-bit adder -------------------
    input  signed [44:0] ch4_a,
    input  signed [44:0] ch4_b,

    // ------------------- Channel 5 (unchanged) -------------------
    input signed [10:0] pix5,
    input signed [8:0] k5a,
    input signed [14:0] k5b,
    input signed [7:0] k5c,

    // ------------------- Final Output -------------------
    output signed [46:0] final_out
);

    // ===================================================================
    // Channel outputs
    // ===================================================================
    wire signed [43:0] channel1_out; // 44-bit adder output
    wire signed [17:0] channel2_out;
    wire signed [26:0] channel3_out;
    wire signed [44:0] channel4_out; // 45-bit adder output
    wire signed [17:0] channel5_out;

    // ===================================================================
    // Channel 1 : 44-bit combinational add
    // ===================================================================
    assign channel1_out = ch1_a + ch1_b;

    // ===================================================================
    // Channel 2 (unchanged)
    // ===================================================================
    logic signed [17:0]stage0_ch2, stage1_ch2;
    always @(posedge clk) begin
        stage0_ch2 <= ((k2a + pix2) * k2b) & k2c;
        stage1_ch2 <= stage0_ch2;
    end
    assign channel2_out = stage1_ch2;

    // ===================================================================
    // Channel 3 (unchanged)
    // ===================================================================
    logic signed [26:0]stage0_ch3, stage1_ch3;
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
    // Channel 5 (unchanged)
    // ===================================================================
    logic signed [17:0]stage0_ch5, stage1_ch5;
    always @(posedge clk) begin
        stage0_ch5 <= ((k5a + pix5) * k5b) & k5c;
        stage1_ch5 <= stage0_ch5;
    end
    assign channel5_out = stage1_ch5;

    // ===================================================================
    // Output Combination (对齐到最大位宽 47 位)
    // ===================================================================
    assign final_out =
        { {3{channel1_out[43]}}, channel1_out } +   // 44 → 47
        { {29{channel2_out[17]}}, channel2_out } +  // 18 → 47
        { {20{channel3_out[26]}}, channel3_out } +  // 27 → 47
        { {2{channel4_out[44]}}, channel4_out } +   // 45 → 47
        { {30{channel5_out[17]}}, channel5_out };   // 18 → 47

endmodule
