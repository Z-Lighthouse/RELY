//
// Top-Level Module: High_Performance_PID_Controller
//
// Description:
//   A fully pipelined PID (Proportional-Integral-Derivative) controller.
//   This design utilizes exactly 5 instances of the updated 'PreAdd_Mul_Acc_Unit' core.
//
//   CHANGES:
//   - Adapted to new DSP core with specific bit widths:
//     a(8), b(10), c(17), d(12) -> out(24).
//   - Internal datapaths and output compressed to 24 bits.
//   - Instantiation mappings updated to use the widest available ports.
//
module High_Performance_PID_Controller (
    input clk,
    input rst_n,
    input enable,             // Enable signal to allow the controller to operate

    // PID Parameters (Gains)
    input signed [12:0] Kp,   // Proportional gain
    input signed [12:0] Ki,   // Integral gain
    input signed [12:0] Kd,   // Derivative gain

    // Control Inputs
    input signed [17:0] setpoint,     // The desired target value
    input signed [17:0] process_var,  // The current measured value from the system

    // Control Output
    // WIDTH CHANGE: Updated to 24 bits to match new DSP core output
    output signed [23:0] control_out  
);

    // --- Internal Signals ---
    reg  signed [17:0] error;
    reg  signed [17:0] prev_error;
    
    // WIDTH CHANGE: Registers and wires updated to 24 bits
    reg  signed [23:0] integral_term_reg;
    wire signed [23:0] p_term, i_term, d_term;
    wire signed [23:0] p_plus_i_term;

    // --- Error Calculation ---
    // The error is the difference between the setpoint and the current process variable.
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            error <= 18'sd0;
            prev_error <= 18'sd0;
        end else if (enable) begin
            // Calculate error using two's complement addition
            error <= setpoint + (~process_var) + 1;
            prev_error <= error; 
        end
    end

    // --- INSTANCE 1: Proportional (P) Term Calculation ---
    // P = Kp * error.
    // Logic: out = ((d + a) * b) + c
    // Mapping: ((Kp + 0) * error) + 0
    PreAdd_Mul_Acc_Unit P_Term_Unit (
        .clk(clk),
        .d(Kp[12:1]),           // d: Kp (13-bit -> 12-bit truncated)
        .a(8'sd0),              // a: 0
        .b(error[17:8]),        // b: error (18-bit -> 10-bit truncated)
        .c(17'sd0),             // c: 0
        .out(p_term)
    );

    // --- INSTANCE 2: Integral (I) Term Calculation and Accumulation ---
    // I_new = I_old + Ki * error.
    // Logic: out = ((d + a) * b) + c
    // Mapping: ((Ki + 0) * error) + I_old
    PreAdd_Mul_Acc_Unit I_Term_Unit (
        .clk(clk),
        .d(Ki[12:1]),           // d: Ki (13-bit -> 12-bit truncated)
        .a(8'sd0),              // a: 0
        .b(error[17:8]),        // b: error (18-bit -> 10-bit truncated)
        .c(integral_term_reg[23:7]), // c: I_old (24-bit -> 17-bit truncated)
        .out(i_term)
    );
    
    // Register for the integral accumulator
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            integral_term_reg <= 24'sd0;
        end else if (enable) begin
            integral_term_reg <= i_term; // Update accumulator
        end
    end

    // --- INSTANCE 3: Derivative (D) Term Calculation ---
    // D = Kd * (error - prev_error).
    // Logic: out = ((d + a) * b) + c
    // Mapping: ((error + (-prev_error)) * Kd) + 0
    PreAdd_Mul_Acc_Unit D_Term_Unit (
        .clk(clk),
        .d(error[17:6]),        // d: error (18-bit -> 12-bit truncated)
        .a(-prev_error[17:10]), // a: -prev_error (18-bit -> 8-bit truncated)
        .b(Kd[12:3]),           // b: Kd (13-bit -> 10-bit truncated)
        .c(17'sd0),             // c: 0
        .out(d_term)
    );
    
    // --- INSTANCE 4 & 5: Adder Tree for Final Summation ---
    
    // Instance 4: Sum P and I terms.
    // Logic: out = ((d + a) * b) + c
    // Mapping: ((P + 0) * 1) + I
    PreAdd_Mul_Acc_Unit Adder_P_I (
        .clk(clk),
        .d(p_term[23:12]),      // d: P_term (24-bit -> 12-bit)
        .a(8'sd0),              // a: 0
        .b(10'sd1),             // b: 1 (Multiplier factor)
        .c(i_term[23:7]),       // c: I_term (24-bit -> 17-bit, using widest port for best precision)
        .out(p_plus_i_term)
    );

    // Instance 5: Sum (P+I) and D terms.
    // Logic: out = ((d + a) * b) + c
    // Mapping: ((D + 0) * 1) + (P+I)
    PreAdd_Mul_Acc_Unit Adder_PID (
        .clk(clk),
        .d(d_term[23:12]),      // d: D_term (24-bit -> 12-bit)
        .a(8'sd0),              // a: 0
        .b(10'sd1),             // b: 1 (Multiplier factor)
        .c(p_plus_i_term[23:7]),// c: P+I term (24-bit -> 17-bit)
        .out(control_out)
    );

endmodule


//
// Core Computational Unit
//
// Description:
//   Replaced core logic as requested.
//   Performs ((d + a) * b) + c with 2 pipeline stages.
//
module PreAdd_Mul_Acc_Unit (
    input signed [7:0] a,
    input signed [9:0] b,
    input signed [16:0] c,
    input signed [11:0] d,
    input clk,
    output signed [23:0] out // Added output port definition
);

  reg signed [23:0] stage0, stage1;

  always @(posedge clk) begin
    stage0 <= ((d + a) * b) + c;
    stage1 <= stage0;
  end

  assign out = stage1;

endmodule