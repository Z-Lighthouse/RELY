// ===================================================================
// Simplified Design
// Core operation: combinational 44-bit addition
// ===================================================================
module top_complex #(
    parameter integer N_BRANCH = 5
)(
    input  signed [44:0] a,
    input  signed [44:0] b,
    input                clk,
    output signed [44:0] final_out
);

    // ------------------- Internal Signals -------------------
    wire signed [44:0] out;
    reg  signed [44:0] temp;
    reg  signed [44:0] adjusted_value;
    reg                enable_adj;
    reg                enable_adj_d1;
    reg  [2:0]          mode_sel;

    // ===================================================================
    // Stage 1: Mode Control (no c/d involved)
    // ===================================================================
    always @(posedge clk) begin
        if (a < 0)
            mode_sel <= 3'b000;
        else if (a == b)
            mode_sel <= 3'b001;
        else
            mode_sel <= 3'b100;

        enable_adj <= (a < 0);
    end

    // ===================================================================
    // Core Arithmetic (PURE combinational, 44-bit inputs)
    // ===================================================================
    assign out = a + b;

    // ===================================================================
    // Stage 3: Post Processing
    // ===================================================================
    always @(posedge clk) begin
        case (mode_sel)
            3'b000: temp <= out << 1;
            3'b001: temp <= out >>> 2;
            default: temp <= out;
        endcase
    end

    // ===================================================================
    // Enable Synchronization
    // ===================================================================
    always @(posedge clk) begin
        enable_adj_d1 <= enable_adj;
    end

    // ===================================================================
    // Final Output
    // ===================================================================
    always @(posedge clk) begin
        if (enable_adj_d1)
            adjusted_value <= temp >>> 1;
        else
            adjusted_value <= temp;
    end

    assign final_out = adjusted_value;

endmodule
