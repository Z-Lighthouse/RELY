// ===================================================================
// Auto-generated Multi-Channel Image Filter
// ===================================================================
module complex_image_filter_design716 (
    input clk,

    // ===================== Channel 1 : 46-bit adder ==================
    input signed [45:0] ch1_a,
    input signed [45:0] ch1_b,

    // ===================== Channel 2 (unchanged) =====================
    input signed [14:0] pix2,
    input signed [11:0] k2a,
    input signed [16:0] k2b,
    input signed [15:0] k2c,

    // ===================== Channel 3 (unchanged) =====================
    input signed [16:0] pix3,
    input signed [10:0] k3a,
    input signed [12:0] k3b,
    input signed [13:0] k3c,

    // ===================== Channel 4 : 44-bit adder ==================
    input signed [43:0] ch4_a,
    input signed [43:0] ch4_b,

    // ===================== Channel 5 (unchanged) =====================
    input signed [17:0] pix5,
    input signed [7:0]  k5a,
    input signed [12:0] k5b,
    input signed [16:0] k5c,

    // ===================== Final Output ===============================
    output signed [45:0] final_out
);

    // ===================================================================
    // Channel outputs
    // ===================================================================
    wire signed [45:0] channel1_out;  // 46-bit adder
    wire signed [33:0] channel2_out;
    wire signed [29:0] channel3_out;
    wire signed [43:0] channel4_out;  // 44-bit adder
    wire signed [32:0] channel5_out;

    // ===================================================================
    // Channel 1 : 46-bit combinational add
    // ===================================================================
    assign channel1_out = ch1_a + ch1_b;

    // ===================================================================
    // Channel 2 processing (unchanged)
    // ===================================================================
    logic signed [33:0] stage0_ch2;
    always @(posedge clk) begin
        stage0_ch2 <= ((k2a + pix2) * k2b) + k2c;
    end
    assign channel2_out = stage0_ch2;

    // ===================================================================
    // Channel 3 processing (unchanged)
    // ===================================================================
    logic signed [29:0] stage0_ch3;
    always @(posedge clk) begin
        stage0_ch3 <= ((k3a + pix3) * k3b) + k3c;
    end
    assign channel3_out = stage0_ch3;

    // ===================================================================
    // Channel 4 : 44-bit combinational add
    // ===================================================================
    assign channel4_out = ch4_a + ch4_b;

    // ===================================================================
    // Channel 5 processing (unchanged)
    // ===================================================================
    logic signed [32:0] stage0_ch5;
    always @(posedge clk) begin
        stage0_ch5 <= ((k5a + pix5) * k5b) + k5c;
    end
    assign channel5_out = stage0_ch5;

    // ===================================================================
    // Output Combination
    // Align all channels to 46 bits (max width)
    // ===================================================================
    assign final_out =
        channel1_out +                               // 46
        { {13{channel2_out[33]}}, channel2_out } +   // 34 → 46
        { {16{channel3_out[29]}}, channel3_out } +   // 30 → 46
        { {2{channel4_out[43]}}, channel4_out } +    // 44 → 46
        { {13{channel5_out[32]}}, channel5_out };    // 33 → 46

endmodule
