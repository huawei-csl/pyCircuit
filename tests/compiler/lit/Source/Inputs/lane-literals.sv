// Physical RTL replay of lane-literals.cpp; lane 0 is the most significant.
module tb;
  logic [7:0] x = 0;
  logic [3:0] n = 0;
  logic [1:0] pick = 0;
  logic pyc_7079635f636c6b = 0, pyc_7079635f727374 = 0;
  wire [23:0] result;
  pyc_root dut(.*);
  int index = 0;
  task automatic row(input logic [7:0] rx, input logic [3:0] rn,
                     input logic [1:0] rp, input logic [23:0] expected);
    x = rx; n = rn; pick = rp; #1;
    if (result !== expected) $fatal(1, "row %0d: %h != %h", index, result, expected);
    $display("WORK %0d %0h %0h %0h", index, result[23:16], result[15:8], result[7:0]);
    index++;
  endtask
  initial begin
    // Load the Table state image through one reset edge.
    pyc_7079635f727374 = 1; #1 pyc_7079635f636c6b = 1; #1 pyc_7079635f636c6b = 0;
    pyc_7079635f727374 = 0;
    row(8'ha5, 4'h9, 0, 24'ha507a5);
    row(8'ha5, 4'h9, 1, 24'h0102ff);
    row(8'ha5, 4'h9, 2, 24'h010203);
    row(8'ha5, 4'h9, 3, 24'h09a500);
    row(8'h3c, 4'hf, 0, 24'h3c073c);
    row(8'h3c, 4'hf, 1, 24'h0102ff);
    row(8'h3c, 4'hf, 2, 24'h010203);
    row(8'h3c, 4'hf, 3, 24'h0f3c00);
    $display("PASS");
    $finish;
  end
endmodule
