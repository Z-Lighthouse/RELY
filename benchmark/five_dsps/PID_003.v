//
// Top-Level Module: High_Performance_PID_Controller
//
// Description:
//   A fully pipelined PID (Proportional-Integral-Derivative) controller.
//   This design utilizes exactly 5 instances of the updated 'PreAdd_Mul_Acc_Unit' core.
//
//   CHANGES:
//   - Adapted to new DSP core with specific bit widths:
//     a(17), b(18), c(13), d(10) -> out(37).
//   - Internal datapaths expanded to 37 bits.
//   - Instantiation mappings optimized for the new port widths.
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
    // WIDTH CHANGE: Updated to 37 bits to match new DSP core output
    output signed [36:0] control_out  
);

    // --- Internal Signals ---
    reg  signed [17:0] error;
    reg  signed [17:0] prev_error;
    
    // WIDTH CHANGE: Registers and wires updated to 37 bits
    reg  signed [36:0] integral_term_reg;
    wire signed [36:0] p_term, i_term, d_term;
    wire signed [36:0] p_plus_i_term;

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
    // Mapping: ((0 + Kp) * error) + 0
    PreAdd_Mul_Acc_Unit P_Term_Unit (
        .clk(clk),
        .d(10'sd0),             // d: 0
        .a({{4{Kp[12]}}, Kp}),  // a: Kp (13-bit -> 17-bit sign extended)
        .b(error),              // b: error (18-bit -> 18-bit, perfect match)
        .c(13'sd0),             // c: 0
        .out(p_term)
    );

    // --- INSTANCE 2: Integral (I) Term Calculation and Accumulation ---
    // I_new = I_old + Ki * error.
    // Logic: out = ((d + a) * b) + c
    // Mapping: ((0 + Ki) * error) + I_old
    PreAdd_Mul_Acc_Unit I_Term_Unit (
        .clk(clk),
        .d(10'sd0),             // d: 0
        .a({{4{Ki[12]}}, Ki}),  // a: Ki (13-bit -> 17-bit sign extended)
        .b(error),              // b: error (18-bit -> 18-bit)
        .c(integral_term_reg[36:24]), // c: I_old (37-bit -> 13-bit MSB truncated)
        .out(i_term)
    );
    
    // Register for the integral accumulator
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            integral_term_reg <= 37'sd0;
        end else if (enable) begin
            integral_term_reg <= i_term; // Update accumulator
        end
    end

    // --- INSTANCE 3: Derivative (D) Term Calculation ---
    // D = Kd * (error - prev_error).
    // Logic: out = ((d + a) * b) + c
    // Mapping: (( (-prev_error) + error ) * Kd) + 0
    PreAdd_Mul_Acc_Unit D_Term_Unit (
        .clk(clk),
        .d(-prev_error[17:8]),  // d: -prev_error (18-bit -> 10-bit truncated)
        .a(error[17:1]),        // a: error (18-bit -> 17-bit truncated)
        .b({{5{Kd[12]}}, Kd}),  // b: Kd (13-bit -> 18-bit sign extended)
        .c(13'sd0),             // c: 0
        .out(d_term)
    );
    
    // --- INSTANCE 4 & 5: Adder Tree for Final Summation ---
    
    // Instance 4: Sum P and I terms.
    // Logic: out = ((d + a) * b) + c
    // Mapping: ((0 + P) * 1) + I
    PreAdd_Mul_Acc_Unit Adder_P_I (
        .clk(clk),
        .d(10'sd0),             // d: 0
        .a(p_term[36:20]),      // a: P_term (37-bit -> 17-bit MSB)
        .b(18'sd1),             // b: 1 (Multiplier factor)
        .c(i_term[36:24]),      // c: I_term (37-bit -> 13-bit MSB)
        .out(p_plus_i_term)
    );

    // Instance 5: Sum (P+I) and D terms.
    // Logic: out = ((d + a) * b) + c
    // Mapping: ((0 + D) * 1) + (P+I)
    PreAdd_Mul_Acc_Unit Adder_PID (
        .clk(clk),
        .d(10'sd0),             // d: 0
        .a(d_term[36:20]),      // a: D_term (37-bit -> 17-bit MSB)
        .b(18'sd1),             // b: 1 (Multiplier factor)
        .c(p_plus_i_term[36:24]),// c: P+I term (37-bit -> 13-bit MSB)
        .out(control_out)
    );

endmodule


//
// Core Computational Unit
//
// Description:
//   Replaced core logic as requested.
//   Performs ((d + a) * b) + c with 1 pipeline stage.
//
module PreAdd_Mul_Acc_Unit (
    input signed [16:0] a,
    input signed [17:0] b,
    input signed [12:0] c,
    input signed [9:0] d,
    input clk,
    output signed [36:0] out // Added output port definition
);

  reg signed [36:0] stage0;

  always @(posedge clk) begin
    stage0 <= ((d + a) * b) + c;
  end

  assign out = stage0;

endmodule