
// ===================================================================
//
// Function: Dynamically selects one of 4 processing modes based on
//           input pixel characteristics to perform real-time contrast
//           and brightness adjustments.
// ===================================================================
module top_complex #(
    parameter integer N_BRANCH = 4
)(
    // ------------------- Port Definitions -------------------
    input signed [12:0] a,
    input signed [10:0] b,
    input signed [8:0] c,
    input signed [17:0] d,
    input clk,
    output signed [30:0] final_out
);

    // ------------------- Internal Signals -------------------
    reg signed [30:0] adjusted_value;
    reg signed [17:0] alpha;
    reg signed [12:0] pixel_in;
    reg signed [8:0] offset;
    reg signed [30:0] temp;
    reg               enable_adj;
    reg               enable_adj_d1;
    reg [2:0]         mode_sel;
    reg signed [30:0] out;

    // ===================================================================
    // Pipeline Stage 1: Mode Control Logic
    // Description: Determines the processing mode based on the relationship
    //              between the input pixel 'a' and a reference value 'b'.
    // ===================================================================
    always @(posedge clk) begin
        pixel_in <= a;

        // --- Mode 0: Dark Area Enhancement - Pixel value is too low, apply contrast boost ---
        if ($signed(a) < 0 && $signed(b) < $signed(a[10:0])) begin
            mode_sel   <= 3'b000;
            enable_adj <= 1'b1;
            alpha      <= d[17:0];
            offset     <= c;
        end
        
        // --- Mode 1: Balanced Mode - Pixel value matches reference, apply slight suppression ---
        else if ($signed(a[10:0]) == $signed(b)) begin
            mode_sel   <= 3'b001;
            enable_adj <= 1'b1;
            alpha      <= d[17:0];
            offset     <= c;
        end
        
        // --- Mode 2: Normal Brightness - Pixel is in normal range, apply standard processing ---
        else if ($signed(a[10:0]) < $signed(b)) begin
            mode_sel   <= 3'b010;
            enable_adj <= 1'b0;
            alpha      <= a[12:0];
            offset     <= c;
        end
        
        // --- Mode 3: Highlight Saturation - Pixel value is too high, clip to prevent overflow ---
        else begin
            mode_sel   <= 3'b011;
            enable_adj <= 1'b1;
            alpha      <= d[17:0];
            offset     <= c;
        end
    end

    // ===================================================================
    // Pipeline Stage 2: Core Arithmetic Unit
    // Description: This core arithmetic logic is extracted from the original design.
    // ===================================================================
reg signed [30:0]stage0, stage1;

  always @(posedge clk) begin
    stage0 <= ((d + a) * b) + c;
    stage1 <= stage0;
  end

  assign out = stage1;

    // ===================================================================
    // Pipeline Stage 3: Post-Processing (Non-Linear Adjustments)
    // Description: Applies specialized adjustments to the pixel based on the
    //              mode selected in Stage 1. These operations fine-tune the
    //              pixel value based on its determined characteristic.
    // ===================================================================
    always @(posedge clk) begin
        case (mode_sel)
            
            3'b000: temp <= out << 1; // Amplify by 2 (shift left by 1)
            
            3'b001: temp <= out >>> 2; // Attenuate to 1/4 (shift right by 2)
            
            3'b010: temp <= out + alpha; // Fine-tune brightness
            
            3'b011: temp <= {1'b0, {30{1'b1}}}; // Saturation (clamp to max positive value)
            
            default: temp <= out; // Safe default: Pass-through to prevent latches.
        endcase
    end

    // ===================================================================
    // Pipeline Stage 3.5: Enable Signal Synchronization
    // Description: Synchronize enable_adj signal with temp signal
    // ===================================================================
    always @(posedge clk) begin
        enable_adj_d1 <= enable_adj;
    end

    // ===================================================================
    // Pipeline Stage 4: Final Output Adjustment
    // Description: Applies a final global tweak based on the 'enable_adj' signal.
    // ===================================================================
    always @(posedge clk) begin
        if (enable_adj_d1)
            // For enhanced modes, apply a slight attenuation (divide by 2).
            // This can help prevent over-saturation or clipping in downstream modules.
            adjusted_value <= temp >>> 1;
        else
            // For normal modes, pass the value through without modification.
            adjusted_value <= temp;
    end

    assign final_out = adjusted_value;

endmodule