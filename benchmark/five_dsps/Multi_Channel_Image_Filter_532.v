
// ===================================================================
// Auto-generated Multi-Channel Image Filter
//
// Function: Parallel processing of 5 image channels
//           Each channel is a complete design with original ports and logic
//           All channels use signed arithmetic for consistency
//           Final output width: 31 bits (max of all channels)
// ===================================================================
module complex_image_filter_design533 (
    // ------------------- Port Definitions -------------------
    input clk,
    input signed [16:0] pix1,
    input signed [14:0] k1a,
    input signed [9:0] k1b,
    input signed [11:0] pix2,
    input signed [14:0] k2a,
    input signed [12:0] k2b,
    input signed [10:0] pix3,
    input signed [17:0] k3a,
    input signed [11:0] k3b,
    input signed [16:0] pix4,
    input signed [17:0] k4a,
    input signed [11:0] k4b,
    input signed [17:0] pix5,
    input signed [15:0] k5a,
    input signed [9:0] k5b,
    output signed [30:0] final_out
);

    // ------------------- Internal Signals -------------------
    // Channel outputs
    
    wire signed [27:0] channel1_out;
    
    wire signed [28:0] channel2_out;
    
    wire signed [30:0] channel3_out;
    
    wire signed [30:0] channel4_out;
    
    wire signed [28:0] channel5_out;
    

    // ===================================================================
    // Channel Processing Modules
    // ===================================================================


    // Channel 1 processing
    // Source: xilinx_preaddmul_signed_18_bit_2_stage_variant_8_0.sv 
    // Output width: 28 bits
    // Signed processing
    // Stage signals renamed with suffix: _ch1
    logic signed [27:0]stage0_ch1, stage1_ch1;

  always @(posedge clk) begin
    stage0_ch1 <= (k1a + pix1) * k1b;
    stage1_ch1 <= stage0_ch1;
  end

  assign channel1_out = stage1_ch1;
    


    // Channel 2 processing
    // Source: xilinx_preaddmul_signed_18_bit_2_stage_variant_4.sv 
    // Output width: 29 bits
    // Signed processing
    // Stage signals renamed with suffix: _ch2
    logic signed [28:0]stage0_ch2, stage1_ch2;

  always @(posedge clk) begin
    stage0_ch2 <= (k2a + pix2) * k2b;
    stage1_ch2 <= stage0_ch2;
  end

  assign channel2_out = stage1_ch2;
    


    // Channel 3 processing
    // Source: xilinx_preaddmul_signed_18_bit_2_stage_variant_1.sv 
    // Output width: 31 bits
    // Signed processing
    // Stage signals renamed with suffix: _ch3
    logic signed [30:0]stage0_ch3, stage1_ch3;

  always @(posedge clk) begin
    stage0_ch3 <= (k3a + pix3) * k3b;
    stage1_ch3 <= stage0_ch3;
  end

  assign channel3_out = stage1_ch3;
    


    // Channel 4 processing
    // Source: xilinx_preaddmul_signed_18_bit_2_stage_variant_5.sv 
    // Output width: 31 bits
    // Signed processing
    // Stage signals renamed with suffix: _ch4
    logic signed [30:0]stage0_ch4, stage1_ch4;

  always @(posedge clk) begin
    stage0_ch4 <= (k4a + pix4) * k4b;
    stage1_ch4 <= stage0_ch4;
  end

  assign channel4_out = stage1_ch4;
    


    // Channel 5 processing
    // Source: xilinx_preaddmul_signed_18_bit_2_stage_variant_8.sv 
    // Output width: 29 bits
    // Signed processing
    // Stage signals renamed with suffix: _ch5
    logic signed [28:0]stage0_ch5, stage1_ch5;

  always @(posedge clk) begin
    stage0_ch5 <= (k5a + pix5) * k5b;
    stage1_ch5 <= stage0_ch5;
  end

  assign channel5_out = stage1_ch5;
    


    // ===================================================================
    // Output Combination
    // ===================================================================
    assign final_out = 
        
        { {3{channel1_out[27]}}, channel1_out } +
        
        { {2{channel2_out[28]}}, channel2_out } +
        
        channel3_out +
        
        channel4_out +
        
        { {2{channel5_out[28]}}, channel5_out }
        ;

endmodule