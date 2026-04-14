
// ===================================================================
// Auto-generated Multi-Channel Image Filter
//
// Function: Parallel processing of 5 image channels
//           Each channel is a complete design with original ports and logic
//           All channels use signed arithmetic for consistency
//           Final output width: 35 bits (max of all channels)
// ===================================================================
module complex_image_filter_design259 (
    // ------------------- Port Definitions -------------------
    input clk,
    input signed [10:0] pix1,
    input signed [12:0] k1a,
    input signed [14:0] k1b,
    input signed [11:0] k1c,
    input signed [16:0] pix2,
    input signed [13:0] k2a,
    input signed [10:0] k2b,
    input signed [7:0] k2c,
    input signed [9:0] pix3,
    input signed [12:0] k3a,
    input signed [7:0] k3b,
    input signed [16:0] k3c,
    input signed [15:0] pix4,
    input signed [11:0] k4a,
    input signed [16:0] k4b,
    input signed [17:0] k4c,
    input signed [7:0] pix5,
    input signed [10:0] k5a,
    input signed [14:0] k5b,
    input signed [11:0] k5c,
    output signed [34:0] final_out
);

    // ------------------- Internal Signals -------------------
    // Channel outputs
    
    wire signed [29:0] channel1_out;
    
    wire signed [17:0] channel2_out;
    
    wire signed [22:0] channel3_out;
    
    wire signed [34:0] channel4_out;
    
    wire signed [17:0] channel5_out;
    

    // ===================================================================
    // Channel Processing Modules
    // ===================================================================


    // Channel 1 processing
    // Source: one_stage_add_mul_add_signed_18_bit_xilinx_2_stage_variant_9.sv 
    // Output width: 30 bits
    // Signed processing
    // Stage signals renamed with suffix: _ch1
    logic signed [29:0]stage0_ch1, stage1_ch1;

  always @(posedge clk) begin
    stage0_ch1 <= ((k1a + pix1) * k1b) + k1c;
    stage1_ch1 <= stage0_ch1;
  end

  assign channel1_out = stage1_ch1;
    


    // Channel 2 processing
    // Source: xilinx_addmuland_signed_18_bit_1_stage_variant_7.sv 
    // Output width: 18 bits
    // Signed processing
    // Stage signals renamed with suffix: _ch2
    logic signed [17:0]stage0_ch2;

	always @(posedge clk) begin
	stage0_ch2 <= ((k2a + pix2) * k2b) & k2c;

	end

	assign channel2_out = stage0_ch2;
    


    // Channel 3 processing
    // Source: one_stage_add_mul_add_signed_11_bit_xilinx_2_stage_variant_9.sv 
    // Output width: 23 bits
    // Signed processing
    // Stage signals renamed with suffix: _ch3
    logic signed [22:0]stage0_ch3, stage1_ch3;

  always @(posedge clk) begin
    stage0_ch3 <= ((k3a + pix3) * k3b) + k3c;
    stage1_ch3 <= stage0_ch3;
  end

  assign channel3_out = stage1_ch3;
    


    // Channel 4 processing
    // Source: one_stage_add_mul_add_signed_12_bit_xilinx_2_stage_variant_9.sv 
    // Output width: 35 bits
    // Signed processing
    // Stage signals renamed with suffix: _ch4
    logic signed [34:0]stage0_ch4, stage1_ch4;

  always @(posedge clk) begin
    stage0_ch4 <= ((k4a + pix4) * k4b) + k4c;
    stage1_ch4 <= stage0_ch4;
  end

  assign channel4_out = stage1_ch4;
    


    // Channel 5 processing
    // Source: xilinx_addmuland_signed_18_bit_1_stage_variant_3.sv 
    // Output width: 18 bits
    // Signed processing
    // Stage signals renamed with suffix: _ch5
    logic signed [17:0]stage0_ch5;

	always @(posedge clk) begin
	stage0_ch5 <= ((k5a + pix5) * k5b) & k5c;

	end

	assign channel5_out = stage0_ch5;
    


    // ===================================================================
    // Output Combination
    // ===================================================================
    assign final_out = 
        
        { {5{channel1_out[29]}}, channel1_out } +
        
        { {17{channel2_out[17]}}, channel2_out } +
        
        { {12{channel3_out[22]}}, channel3_out } +
        
        channel4_out +
        
        { {17{channel5_out[17]}}, channel5_out }
        ;

endmodule