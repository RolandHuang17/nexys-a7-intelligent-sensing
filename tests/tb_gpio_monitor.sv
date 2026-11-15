`timescale 1ns/1ps
module tb_gpio_monitor;
    reg clk=0,reset=1;always #5 clk=~clk;
    reg [15:0] sw=0;reg [4:0] btn=0;
    wire [15:0] raw,stable;wire [4:0] rb,sb;wire [31:0] changes;wire [159:0] pc,rc;
    gpio_monitor #(.MS_CYCLES(10),.DEBOUNCE_MS(3)) dut(clk,reset,sw,btn,raw,rb,stable,sb,changes,pc,rc);
    integer i;
    initial begin
        repeat(5)@(negedge clk);reset=0;
        sw=16'hffff;repeat(6)@(negedge clk);sw=0;
        repeat(60)@(negedge clk);if(stable!=0)$fatal(1,"bounce accepted");
        sw=16'hffff;repeat(60)@(negedge clk);if(stable!=16'hffff)$fatal(1,"switch high");
        sw=0;repeat(60)@(negedge clk);if(stable!=0)$fatal(1,"switch low");
        for(i=0;i<5;i=i+1)begin
            btn=1<<i;repeat(60)@(negedge clk);
            if(sb!=(1<<i) || pc[i*32+:32]!=1)$fatal(1,"button press %d",i);
            btn=0;repeat(60)@(negedge clk);
            if(sb!=0 || rc[i*32+:32]!=1)$fatal(1,"button release %d",i);
        end
        $display("PASS GPIO: 16 switches, 5 press/release counters, rejected bounce");$finish;
    end
    initial begin #100000;$fatal(1,"timeout");end
endmodule
