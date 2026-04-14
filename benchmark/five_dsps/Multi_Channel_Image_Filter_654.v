// ===================================================================
// Auto-generated Multi-Channel Image Filter
// ===================================================================
module complex_image_filter_design701 (
    input clk,

    // Channel 1
    input signed [15:0] pix1,
    input signed [7:0]  k1a,
    input signed [12:0] k1b,
    input signed [9:0]  k1c,

    // Channel 2 : 42-bit + 42-bit
    input signed [41:0] ch2_a,
    input signed [41:0] ch2_b,

    // Channel 3 : 41-bit + 41-bit
    input signed [40:0] ch3_a,
    input signed [40:0] ch3_b,

    // Channel 4
    input signed [7:0]  pix4,
    input signed [8:0]  k4a,
    input signed [13:0] k4b,
    input signed [16:0] k4c,

    // Channel 5
    input signed [14:0] pix5,
    input signed [10:0] k5a,
    input signed [12:0] k5b,
    input signed [16:0] k5c,

    // ⭐ final_out 改为最大位宽 43 bits
    output signed [42:0] final_out
);

    // ===================================================================
    // Channel outputs
    // ===================================================================
    wire signed [30:0] channel1_out;
    wire signed [42:0] channel2_out;   // 42+42 -> 43
    wire signed [41:0] channel3_out;   // 41+41 -> 42
    wire signed [24:0] channel4_out;
    wire signed [17:0] channel5_out;

    // ===================================================================
    // Channel 1 (原逻辑保持)
    // ===================================================================
    logic signed [30:0] stage0_ch1, stage1_ch1;
    always @(posedge clk) begin
        stage0_ch1 <= ((k1a + pix1) * k1b) + k1c;
        stage1_ch1 <= stage0_ch1;
    end
    assign channel1_out = stage1_ch1;

    // ===================================================================
    // Channel 2 (42-bit combinational add)
    // ===================================================================
    assign channel2_out = ch2_a + ch2_b;

    // ===================================================================
    // Channel 3 (41-bit combinational add)
    // ===================================================================
    assign channel3_out = ch3_a + ch3_b;

    // ===================================================================
    // Channel 4 (原逻辑保持)
    // ===================================================================
    logic signed [24:0] stage0_ch4, stage1_ch4;
    always @(posedge clk) begin
        stage0_ch4 <= ((k4a + pix4) * k4b) + k4c;
        stage1_ch4 <= stage0_ch4;
    end
    assign channel4_out = stage1_ch4;

    // ===================================================================
    // Channel 5 (原逻辑保持)
    // ===================================================================
    logic signed [17:0] stage0_ch5;
    always @(posedge clk) begin
        stage0_ch5 <= ((k5a + pix5) * k5b) & k5c;
    end
    assign channel5_out = stage0_ch5;

    // ===================================================================
    // Output Combination
    // 所有通道显式符号扩展到 43 bits（最大位宽）
    // ===================================================================
    assign final_out =
        { {12{channel1_out[30]}}, channel1_out } +   // 31 -> 43
        channel2_out +                               // 43
        { {1{channel3_out[41]}}, channel3_out } +   // 42 -> 43
        { {18{channel4_out[24]}}, channel4_out } +  // 25 -> 43
        { {25{channel5_out[17]}}, channel5_out };   // 18 -> 43

endmodule
