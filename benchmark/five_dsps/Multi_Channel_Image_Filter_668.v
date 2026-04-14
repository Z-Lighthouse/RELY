// ===================================================================
// Auto-generated Multi-Channel Image Filter
// ===================================================================
module complex_image_filter_design715 (
    input clk,

    // ------------------- Channel 1 -------------------
    input signed [10:0] pix1,
    input signed [15:0] k1a,
    input signed [11:0] k1b,
    input signed [7:0] k1c,

    // ------------------- Channel 2 -------------------
    input signed [9:0] pix2,
    input signed [12:0] k2a,
    input signed [7:0] k2b,
    input signed [16:0] k2c,

    // ------------------- Channel 3 -------------------
    input signed [11:0] pix3,
    input signed [8:0] k3a,
    input signed [16:0] k3b,
    input signed [9:0] k3c,

    // ------------------- Channel 4 : 43-bit adder -------------------
    input signed [42:0] ch4_a,
    input signed [42:0] ch4_b,

    // ------------------- Channel 5 : 47-bit adder -------------------
    input signed [46:0] ch5_a,
    input signed [46:0] ch5_b,

    // ------------------- Final Output -------------------
    output signed [46:0] final_out
);

    // ------------------- Internal Signals -------------------
    wire signed [17:0] channel1_out;
    wire signed [22:0] channel2_out;
    wire signed [30:0] channel3_out;
    wire signed [42:0] channel4_out; // 43-bit adder
    wire signed [46:0] channel5_out; // 47-bit adder

    // ===================================================================
    // Channel 1 (unchanged)
    // ===================================================================
    logic signed [17:0]stage0_ch1;
    always @(posedge clk) begin
        stage0_ch1 <= ((k1a + pix1) * k1b) & k1c;
    end
    assign channel1_out = stage0_ch1;

    // ===================================================================
    // Channel 2 (unchanged)
    // ===================================================================
    logic signed [22:0]stage0_ch2, stage1_ch2;
    always @(posedge clk) begin
        stage0_ch2 <= ((k2a + pix2) * k2b) + k2c;
        stage1_ch2 <= stage0_ch2;
    end
    assign channel2_out = stage1_ch2;

    // ===================================================================
    // Channel 3 (unchanged)
    // ===================================================================
    logic signed [30:0]stage0_ch3;
    always @(posedge clk) begin
        stage0_ch3 <= ((k3a + pix3) * k3b) + k3c;
    end
    assign channel3_out = stage0_ch3;

    // ===================================================================
    // Channel 4 : 43-bit combinational add
    // ===================================================================
    assign channel4_out = ch4_a + ch4_b;

    // ===================================================================
    // Channel 5 : 47-bit combinational add
    // ===================================================================
    assign channel5_out = ch5_a + ch5_b;

    // ===================================================================
    // Output Combination (对齐到最大位宽 47 位)
    // ===================================================================
    assign final_out =
        { {29{channel1_out[17]}}, channel1_out } +   // 18 → 47
        { {24{channel2_out[22]}}, channel2_out } +   // 23 → 47
        { {17{channel3_out[30]}}, channel3_out } +   // 31 → 47
        { {4{channel4_out[42]}}, channel4_out } +    // 43 → 47
        channel5_out;                                 // 47 → 47

endmodule
