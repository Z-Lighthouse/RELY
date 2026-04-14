//
// Top-Level Module: High_Performance_PID_Controller
//
// Description:
//   A fully pipelined PID (Proportional-Integral-Derivative) controller.
//   This design is architected for high-speed control applications and utilizes
//   exactly 5 instances of a dedicated 'PreAdd_Mul_Acc_Unit' core.
//
//   - Instance 1: Calculates the Proportional (P) term.
//   - Instance 2: Calculates and accumulates the Integral (I) term.
//   - Instance 3: Calculates the Derivative (D) term.
//   - Instances 4 & 5: Form a 2-stage adder tree to sum the P, I, and D terms.
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
    output signed [32:0] control_out  // The final output to the actuator
);

    // --- Internal Signals ---
    reg  signed [17:0] error;
    reg  signed [17:0] prev_error;
    reg  signed [32:0] integral_term_reg;

    wire signed [32:0] p_term, i_term, d_term;
    wire signed [32:0] p_plus_i_term;

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
    // P = Kp * error.  Mapped to ((0 + error) * Kp) + 0.
    PreAdd_Mul_Acc_Unit P_Term_Unit (
        .clk(clk),
        .d(8'sd0),              // d is unused, set to 0
        .a(error),              // a <= error
        .b(Kp),                 // b <= Kp
        .c(17'sd0),             // c is unused, set to 0
        .out(p_term)
    );

    // --- INSTANCE 2: Integral (I) Term Calculation and Accumulation ---
    // I_new = I_old + Ki * error. Mapped to ((0 + error) * Ki) + I_old.
    PreAdd_Mul_Acc_Unit I_Term_Unit (
        .clk(clk),
        .d(8'sd0),              // d is unused, set to 0
        .a(error),              // a <= error
        .b(Ki),                 // b <= Ki
        .c(integral_term_reg[16:0]), // c <= I_old
        .out(i_term)
    );
    
    // Register for the integral accumulator
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            integral_term_reg <= 33'sd0;
        end else if (enable) begin
            integral_term_reg <= i_term; // Update accumulator
        end
    end

    // --- INSTANCE 3: Derivative (D) Term Calculation ---
    // D = Kd * (error - prev_error). Mapped to ((error + (-prev_error)) * Kd) + 0.
    PreAdd_Mul_Acc_Unit D_Term_Unit (
        .clk(clk),
        .d(error[7:0]),         // d <= error (truncated)
        .a(-prev_error),        // a <= -prev_error
        .b(Kd),                 // b <= Kd
        .c(17'sd0),             // c is unused, set to 0
        .out(d_term)
    );
    
    // --- INSTANCE 4 & 5: Adder Tree for Final Summation ---
    
    // Instance 4: Sum P and I terms. Mapped to ((0 + P) * 1) + I.
    // Using the core unit as a flexible adder.
    PreAdd_Mul_Acc_Unit Adder_P_I (
        .clk(clk),
        .d(8'sd0),              // d is unused, set to 0
        .a(p_term[17:0]),       // a <= P_term
        .b(13'sd1),             // b = 1 (to implement addition)
        .c(i_term[16:0]),       // c <= I_term
        .out(p_plus_i_term)
    );

    // Instance 5: Sum (P+I) and D terms. Mapped to ((0 + D) * 1) + (P+I).
    PreAdd_Mul_Acc_Unit Adder_PID (
        .clk(clk),
        .d(8'sd0),              // d is unused, set to 0
        .a(d_term[17:0]),       // a <= D_term
        .b(13'sd1),             // b = 1
        .c(p_plus_i_term[16:0]),// c <= P_plus_I_term
        .out(control_out)
    );

endmodule


//
// Core Computational Unit
//
// Description:
//   Core unit performing a fused Pre-Add -> Multiply -> Accumulate operation.
//   This structure is designed to map directly to a single FPGA DSP slice.
//
module PreAdd_Mul_Acc_Unit (
    input signed [17:0] a,
    input signed [12:0] b,
    input signed [16:0] c,
    input signed [7:0]  d,
    input clk,
    output [32:0] out
);

  reg signed [32:0] stage0;

  always @(posedge clk) begin
    stage0 <= ((d + a) * b) + c;
  end

  assign out = stage0;

endmodule