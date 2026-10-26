// Physical RTL replay of the known rows of state-no-reset.cpp. Each row is
// sampled before the epoch's clock level is applied, matching a Work
// observation of the committed state.
module tb;
  logic load = 0;
  logic [7:0] value = 0, sample_in = 0;
  logic pyc_7079635f636c6b = 0, pyc_7079635f727374 = 0;
  wire [27:0] result;
  pyc_root dut(.*);
  int epoch = 0;
  task automatic row(input logic c, r, l, input logic [7:0] v, s,
                     input logic [27:0] expected, input bit print);
    pyc_7079635f727374 = r; load = l; value = v; sample_in = s; #1;
    if (print) begin
      if (result !== expected) $fatal(1, "epoch %0d: %h != %h", epoch, result, expected);
      $display("WORK %0d %0h %0h %0h %0h", epoch, result[27:20], result[19:12],
               result[11:4], result[3:0]);
    end
    pyc_7079635f636c6b = c; #1;
    epoch++;
  endtask
  initial begin
    row(0, 0, 0, 8'h00, 8'h00, 'x, 0);  // physical power-up is unspecified
    row(1, 0, 1, 8'h5a, 8'h11, 'x, 0);
    row(0, 0, 0, 8'h00, 8'h00, {8'h5a, 8'h11, 8'h06, 4'ha}, 1);
    row(1, 1, 0, 8'h00, 8'h22, {8'h5a, 8'h11, 8'h06, 4'ha}, 1);
    row(0, 0, 0, 8'h00, 8'h00, {8'h5a, 8'h22, 8'h05, 4'ha}, 1);
    row(1, 1, 1, 8'hc3, 8'h33, {8'h5a, 8'h22, 8'h05, 4'ha}, 1);
    row(0, 0, 0, 8'h00, 8'h00, {8'hc3, 8'h33, 8'h05, 4'h3}, 1);
    row(1, 0, 0, 8'h00, 8'h44, {8'hc3, 8'h33, 8'h05, 4'h3}, 1);
    row(0, 0, 0, 8'h00, 8'h00, {8'hc3, 8'h44, 8'h06, 4'h3}, 1);
    $display("PASS");
    $finish;
  end
endmodule
