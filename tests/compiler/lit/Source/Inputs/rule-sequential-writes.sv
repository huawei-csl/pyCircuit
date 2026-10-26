// Physical RTL replay of rule-sequential-writes.cpp with the same oracle.
module tb;
  logic a = 0, b = 0, c = 0;
  logic [7:0] x = 0, y = 0, z = 0;
  logic pyc_7079635f636c6b = 0, pyc_7079635f727374 = 0;
  wire [7:0] result;
  pyc_root dut(.*);
  int epoch = 0;
  logic [7:0] committed, next;
  initial begin
    // Physical reset edge: the declared initializer is 0.
    pyc_7079635f727374 = 1; #1 pyc_7079635f636c6b = 1; #1 pyc_7079635f636c6b = 0;
    pyc_7079635f727374 = 0; #1;
    committed = 0;
    for (int round = 0; round < 3; round++)
      for (int guards = 0; guards < 8; guards++) begin
        a = guards[0]; b = guards[1]; c = guards[2];
        x = 8'h11 * (round + 1); y = 8'h07 + round; z = 8'ha0 + guards;
        for (int clock = 0; clock < 2; clock++) begin
          #1;
          if (result !== committed) $fatal(1, "epoch %0d: %0d != %0d", epoch, result, committed);
          $display("WORK %0d %0d", epoch, committed);
          epoch++;
          pyc_7079635f636c6b = clock[0]; #1;
        end
        next = committed;
        if (a) next = x;
        if (b) next = y + next;
        if (c) next = z;
        committed = next;
        pyc_7079635f636c6b = 0;
      end
    $display("PASS");
    $finish;
  end
endmodule
