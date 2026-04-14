// ===================================================================
// Auto-generated Multi-Channel Image Filter
// ===================================================================
module complex_image_filter_design711 (
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

    // ------------------- Channel 3 : 44-bit adder -------------------
    input signed [43:0] ch3_a,
    input signed [43:0] ch3_b,

    // ------------------- Channel 4 : 45-bit adder -------------------
    input signed [44:0] ch4_a,
    input signed [44:0] ch4_b,

    // ------------------- Channel 5 (unchanged) -------------------
    input signed [8:0] pix5,
    input signed [16:0] k5a,
    input signed [12:0] k5b,
    input signed [9:0] k5c,

    // ------------------- Final Output -------------------
    output signed [44:0] final_out
);

    // ===================================================================
    // Channel outputs
    // ===================================================================
    wire signed [28:0] channel1_out;
    wire signed [31:0] channel2_out;
    wire signed [43:0] channel3_out; // 44-bit adder
    wire signed [44:0] channel4_out; // 45-bit adder
    wire signed [31:0] channel5_out;

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
    // Channel 3 : 44-bit combinational add
    // ===================================================================
    assign channel3_out = ch3_a + ch3_b;

    // ===================================================================
    // Channel 4 : 45-bit combinational add
    // ===================================================================
    assign channel4_out = ch4_a + ch4_b;

    // ===================================================================
    // Channel 5 (unchanged)
    // ===================================================================
    logic signed [31:0]stage0_ch5;
    always @(posedge clk) begin
        stage0_ch5 <= ((k5a + pix5) * k5b) + k5c;
    end
    assign channel5_out = stage0_ch5;

    // ===================================================================
    // Output Combination (对齐到最大位宽 45 位)
    // ===================================================================
    assign final_out = 
        { {16{channel1_out[28]}}, channel1_out } + // 29 → 45
        { {14{channel2_out[31]}}, channel2_out } + // 32 → 45
        { {1{channel3_out[43]}}, channel3_out } +  // 44 → 45
        { {0{channel4_out[44]}}, channel4_out } +  // 45 → 45
        { {14{channel5_out[31]}}, channel5_out };  // 32 → 45

endmodule
