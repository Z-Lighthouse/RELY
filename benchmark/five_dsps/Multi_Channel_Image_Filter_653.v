// ===================================================================
// Auto-generated Multi-Channel Image Filter
// ===================================================================
module complex_image_filter_design700 (
    input clk,

    input signed [44:0] ch1_a,
    input signed [44:0] ch1_b,

    input signed [42:0] ch2_a,
    input signed [42:0] ch2_b,

    input signed [15:0] pix3,
    input signed [10:0] k3a,
    input signed [13:0] k3b,
    input signed [8:0]  k3c,

    input signed [9:0]  pix4,
    input signed [12:0] k4a,
    input signed [7:0]  k4b,
    input signed [16:0] k4c,

    input signed [10:0] pix5,
    input signed [11:0] k5a,
    input signed [8:0]  k5b,
    input signed [12:0] k5c,

    output signed [45:0] final_out
);

    // ===================================================================
    // Channel outputs
    // ===================================================================
    wire signed [45:0] channel1_out;  
    wire signed [43:0] channel2_out;  
    wire signed [31:0] channel3_out;
    wire signed [22:0] channel4_out;
    wire signed [17:0] channel5_out;

    // ===================================================================
    // Channel 1 (45-bit add)
    // ===================================================================
    assign channel1_out = ch1_a + ch1_b;

    // ===================================================================
    // Channel 2 (43-bit add)
    // ===================================================================
    assign channel2_out = ch2_a + ch2_b;

    // ===================================================================
    // Channel 3 
    // ===================================================================
    logic signed [31:0] stage0_ch3;
    always @(posedge clk) begin
        stage0_ch3 <= ((k3a + pix3) * k3b) + k3c;
    end
    assign channel3_out = stage0_ch3;

    // ===================================================================
    // Channel 4 
    // ===================================================================
    logic signed [22:0] stage0_ch4, stage1_ch4;
    always @(posedge clk) begin
        stage0_ch4 <= ((k4a + pix4) * k4b) + k4c;
        stage1_ch4 <= stage0_ch4;
    end
    assign channel4_out = stage1_ch4;

    // ===================================================================
    // Channel 5 
    // ===================================================================
    logic signed [17:0] stage0_ch5, stage1_ch5;
    always @(posedge clk) begin
        stage0_ch5 <= ((k5a + pix5) * k5b) & k5c;
        stage1_ch5 <= stage0_ch5;
    end
    assign channel5_out = stage1_ch5;

    // ===================================================================
    // Output Combination

    // ===================================================================
    wire signed [45:0] sum_ext;

    assign sum_ext =
        channel1_out +                                            // 46
        { {2{channel2_out[43]}}, channel2_out } +                 // 44 -> 46
        { {14{channel3_out[31]}}, channel3_out } +                // 32 -> 46
        { {23{channel4_out[22]}}, channel4_out } +                // 23 -> 46
        { {28{channel5_out[17]}}, channel5_out };                 // 18 -> 46

    assign final_out = sum_ext;

endmodule
