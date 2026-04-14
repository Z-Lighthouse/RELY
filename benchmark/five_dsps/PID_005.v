//
// Top-Level Module: High_Performance_PID_Controller
//
// Description:
//   A fully pipelined PID (Proportional-Integral-Derivative) controller.
//   This design utilizes exactly 5 instances of the user-provided 
//   'PreAdd_Mul_Acc_Unit' core (V1).
//
//   CHANGES:
//   - Adapted to V1 DSP core with specific bit widths:
//     a(10), b(18), c(12), d(11) -> out(31).
//   - Internal datapaths and output compressed to 31 bits.
//   - Instantiation mappings optimized: 'b' port (18-bit) is used for the 
//     primary signal path (Error) to maximize precision.
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
    // WIDTH CHANGE: Updated to 31 bits to match new DSP core output
    output signed [30:0] control_out  
);

    // --- Internal Signals ---
    reg  signed [17:0] error;
    reg  signed [17:0] prev_error;
    
    // WIDTH CHANGE: Registers and wires updated to 31 bits
    reg  signed [30:0] integral_term_reg;
    wire signed [30:0] p_term, i_term, d_term;
    wire signed [30:0] p_plus_i_term;

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
        .d(Kp[12:2]),           // d: Kp (13-bit -> 11-bit truncated)
        .a(10'sd0),             // a: 0
        .b(error),              // b: error (18-bit -> 18-bit, perfect match)
        .c(12'sd0),             // c: 0
        .out(p_term)
    );

    // --- INSTANCE 2: Integral (I) Term Calculation and Accumulation ---
    // I_new = I_old + Ki * error.
    // Logic: out = ((d + a) * b) + c
    // Mapping: ((Ki + 0) * error) + I_old
    PreAdd_Mul_Acc_Unit I_Term_Unit (
        .clk(clk),
        .d(Ki[12:2]),           // d: Ki (13-bit -> 11-bit truncated)
        .a(10'sd0),             // a: 0
        .b(error),              // b: error (18-bit -> 18-bit)
        .c(integral_term_reg[30:19]), // c: I_old (31-bit -> 12-bit MSB truncated for feedback)
        .out(i_term)
    );
    
    // Register for the integral accumulator
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            integral_term_reg <= 31'sd0;
        end else if (enable) begin
            integral_term_reg <= i_term; // Update accumulator
        end
    end

    // --- INSTANCE 3: Derivative (D) Term Calculation ---
    // D = Kd * (error - prev_error).
    // Logic: out = ((d + a) * b) + c
    // Mapping: (( error + (-prev_error) ) * Kd) + 0
    PreAdd_Mul_Acc_Unit D_Term_Unit (
        .clk(clk),
        .d(error[17:7]),        // d: error (18-bit -> 11-bit MSB truncated)
        .a(-prev_error[17:8]),  // a: -prev_error (18-bit -> 10-bit MSB truncated)
        .b({{5{Kd[12]}}, Kd}),  // b: Kd (13-bit -> 18-bit sign extended)
        .c(12'sd0),             // c: 0
        .out(d_term)
    );
    
    // --- INSTANCE 4 & 5: Adder Tree for Final Summation ---
    
    // Instance 4: Sum P and I terms.
    // Logic: out = ((d + a) * b) + c
    // Mapping: ((0 + 1) * P) + I
    // We use 'b' for P because it's the widest input (18 bits), and 'c' for I.
    PreAdd_Mul_Acc_Unit Adder_P_I (
        .clk(clk),
        .d(11'sd0),             // d: 0
        .a(10'sd1),             // a: 1 (Multiplier factor)
        .b(p_term[30:13]),      // b: P_term (31-bit -> 18-bit MSB)
        .c(i_term[30:19]),      // c: I_term (31-bit -> 12-bit MSB)
        .out(p_plus_i_term)
    );

    // Instance 5: Sum (P+I) and D terms.
    // Logic: out = ((d + a) * b) + c
    // Mapping: ((0 + 1) * D) + (P+I)
    PreAdd_Mul_Acc_Unit Adder_PID (
        .clk(clk),
        .d(11'sd0),             // d: 0
        .a(10'sd1),             // a: 1 (Multiplier factor)
        .b(d_term[30:13]),      // b: D_term (31-bit -> 18-bit MSB)
        .c(p_plus_i_term[30:19]),// c: P+I term (31-bit -> 12-bit MSB)
        .out(control_out)
    );

endmodule


//
// Core Computational Unit
//
// Description:
//   Replaced core logic with provided "V1" code.
//   Performs ((d + a) * b) + c with 1 pipeline stage.
//
module PreAdd_Mul_Acc_Unit ( 
    input signed [9:0] a, 
    input signed [17:0] b, 
    input signed [11:0] c, 
    input signed [10:0] d, 
    input clk, 
    output [30:0] out 
);
  reg signed [30:0] stage0;
  
  always @(posedge clk) begin 
    stage0 <= ((d + a) * b) + c; 
  end
  
  assign out = stage0;
endmodule