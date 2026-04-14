//
// Top-Level Module: High_Performance_PID_Controller
//
// Description:
//   A fully pipelined PID (Proportional-Integral-Derivative) controller.
//   This design is architected for high-speed control applications and utilizes
//   exactly 5 instances of a dedicated 'PreAdd_Mul_Acc_Unit' core.
//
//   CHANGES:
//   - Adapted to new DSP core with specific bit widths:
//     a(15), b(17), c(16), d(11) -> out(34).
//   - Internal datapaths expanded to 34 bits.
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
    // WIDTH CHANGE: Updated to 34 bits to match new DSP core output
    output signed [33:0] control_out  
);

    // --- Internal Signals ---
    reg  signed [17:0] error;
    reg  signed [17:0] prev_error;
    
    // WIDTH CHANGE: Registers and wires updated to 34 bits
    reg  signed [33:0] integral_term_reg;
    wire signed [33:0] p_term, i_term, d_term;
    wire signed [33:0] p_plus_i_term;

    // --- Error Calculation ---
    // The error is the difference between the setpoint and the current process variable.
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            error <= 18'sd0;
            prev_error <= 18'sd0;
        end else if (enable) begin
            // Calculate error using two's complement addition: A - B = A + (~B + 1)
            error <= setpoint + (~process_var) + 1;
            prev_error <= error; // Store current error for the next cycle's derivative calculation
        end
    end

    // --- INSTANCE 1: Proportional (P) Term Calculation ---
    // P = Kp * error.
    // Logic: out = ((d + a) * b) + c
    // Mapping: ((0 + Kp) * error) + 0
    PreAdd_Mul_Acc_Unit P_Term_Unit (
        .clk(clk),
        .d(11'sd0),             // d: Unused
        .a({{2{Kp[12]}}, Kp}),  // a: Kp (13-bit -> 15-bit sign extended)
        .b(error[16:0]),        // b: error (18-bit -> 17-bit truncated to fit best width)
        .c(16'sd0),             // c: Unused
        .out(p_term)
    );

    // --- INSTANCE 2: Integral (I) Term Calculation and Accumulation ---
    // I_new = I_old + Ki * error. 
    // Logic: out = ((d + a) * b) + c
    // Mapping: ((0 + Ki) * error) + I_old
    PreAdd_Mul_Acc_Unit I_Term_Unit (
        .clk(clk),
        .d(11'sd0),             // d: Unused
        .a({{2{Ki[12]}}, Ki}),  // a: Ki (13-bit -> 15-bit)
        .b(error[16:0]),        // b: error (18-bit -> 17-bit truncated)
        .c(integral_term_reg[15:0]), // c: I_old accumulator (34-bit -> 16-bit truncated)
        .out(i_term)
    );
    
    // Register for the integral accumulator
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            integral_term_reg <= 34'sd0;
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
        // a is 15-bit, d is 11-bit. Truncation is inevitable for 18-bit error.
        .a(error[14:0]),        // a: error (18-bit -> 15-bit truncated)
        .d(-prev_error[10:0]),  // d: -prev_error (18-bit -> 11-bit truncated)
        .b({{4{Kd[12]}}, Kd}),  // b: Kd (13-bit -> 17-bit sign extended)
        .c(16'sd0),             // c: Unused
        .out(d_term)
    );
    
    // --- INSTANCE 4 & 5: Adder Tree for Final Summation ---
    
    // Instance 4: Sum P and I terms. 
    // Logic: out = ((d + a) * b) + c
    // Mapping: ((0 + 1) * P) + I
    PreAdd_Mul_Acc_Unit Adder_P_I (
        .clk(clk),
        .d(11'sd0),             // d: 0
        .a(15'sd1),             // a: 1 (Multiplier factor)
        .b(p_term[16:0]),       // b: P_term (34-bit -> 17-bit, mapped to widest input)
        .c(i_term[15:0]),       // c: I_term (34-bit -> 16-bit)
        .out(p_plus_i_term)
    );

    // Instance 5: Sum (P+I) and D terms. 
    // Logic: out = ((d + a) * b) + c
    // Mapping: ((0 + 1) * D) + (P+I)
    PreAdd_Mul_Acc_Unit Adder_PID (
        .clk(clk),
        .d(11'sd0),             // d: 0
        .a(15'sd1),             // a: 1 (Multiplier factor)
        .b(d_term[16:0]),       // b: D_term (34-bit -> 17-bit)
        .c(p_plus_i_term[15:0]),// c: P+I term (34-bit -> 16-bit)
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
    input signed [14:0] a,
    input signed [16:0] b,
    input signed [15:0] c,
    input signed [11:0] d,
    input clk,
    output signed [33:0] out
);

  reg signed [33:0] stage0;

  always @(posedge clk) begin
    stage0 <= ((d + a) * b) + c;
  end

  assign out = stage0;

endmodule