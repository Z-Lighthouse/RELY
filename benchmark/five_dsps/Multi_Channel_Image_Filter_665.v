// ===================================================================
// Auto-generated Multi-Channel Image Filter
// ===================================================================
module complex_image_filter_design712 (
    input clk,

    // ------------------- Channel 1 (unchanged) -------------------
    input signed [12:0] pix1,
    input signed [16:0] k1a,
    input signed [9:0] k1b,
    input signed [8:0] k1c,

    // ------------------- Channel 2 (unchanged) -------------------
    input signed [15:0] pix2,
    input signed [10:0] k2a,
    input signed [13:0] k2b,
    input signed [8:0] k2c,

    // ------------------- Channel 3 (unchanged) -------------------
    input signed [10:0] pix3,
    input signed [13:0] k3a,
    input signed [15:0] k3b,
    input signed [11:0] k3c,

    // ------------------- Channel 4 : 46-bit adder -------------------
    input signed [45:0] ch4_a,
    input signed [45:0] ch4_b,

    // ------------------- Channel 5 : 44-bit adder -------------------
    input signed [43:0] ch5_a,
    input signed [43:0] ch5_b,

    // ------------------- Final Output -------------------
    output signed [45:0] final_out
);

    // ===================================================================
    // Channel outputs
    // ===================================================================
    wire signed [28:0] channel1_out;
    wire signed [31:0] channel2_out;
    wire signed [31:0] channel3_out;
    wire signed [45:0] channel4_out; // 46-bit adder
    wire signed [43:0] channel5_out; // 44-bit adder

    // ===================================================================
    // Channel 1 (unchanged)
    // ===================================================================
    logic signed [28:0]stage0_ch1, stage1_ch1;
    always @(posedge clk) begin
        stage0_ch1 <= ((k1a + pix1) * k1b) + k1c;
        stage1_ch1 <= stage0_ch1;
    end
    assign channel1_out = stage1_ch1;

    // ===================================================================
    // Channel 2 (unchanged)
    // ===================================================================
    logic signed [31:0]stage0_ch2;
    always @(posedge clk) begin
        stage0_ch2 <= ((k2a + pix2) * k2b) + k2c;
    end
    assign channel2_out = stage0_ch2;

    // ===================================================================
    // Channel 3 (unchanged)
    // ===================================================================
    logic signed [31:0]stage0_ch3;
    always @(posedge clk) begin
        stage0_ch3 <= ((k3a + pix3) * k3b) + k3c;
    end
    assign channel3_out = stage0_ch3;

    // ===================================================================
    // Channel 4 : 46-bit combinational add
    // ===================================================================
    assign channel4_out = ch4_a + ch4_b;

    // ===================================================================
    // Channel 5 : 44-bit combinational add
    // ===================================================================
    assign channel5_out = ch5_a + ch5_b;

    // ===================================================================
    // Output Combination (对齐到最大位宽 46 位)
    // ===================================================================
    assign final_out = 
        { {17{channel1_out[28]}}, channel1_out } + // 29 → 46
        { {15{channel2_out[31]}}, channel2_out } + // 32 → 46
        { {15{channel3_out[31]}}, channel3_out } + // 32 → 46
        channel4_out +                               // 46 → 46
        { {2{channel5_out[43]}}, channel5_out };    // 44 → 46

endmodule
