`timescale 1ns/1ps
module tb_features;
    reg clk=0,reset=1;
    reg [63:0] ticks=0;
    wire signed [15:0] pcm=ticks==20 ? -32768 : (integer'(ticks%64)-32)*100;
    wire [63:0] xyz_tick=ticks-5;
    wire xyz_valid=ticks>=5 && ticks%40==5 && !(xyz_tick>=160 && xyz_tick<320);
    wire signed [15:0] x=(xyz_tick/40)*7,y=-$signed((xyz_tick/40)*3),z=1000;
    wire valid,av,vv;wire [63:0] ft;
    wire [31:0] af,vf,late;
    wire [15:0] an,xn;
    integer n=0;
    always #5 clk=~clk;
    always @(posedge clk)if(reset)ticks<=0;else ticks<=ticks+1;
    feature_core #(.FRAME(160),.DRAIN(10)) core(clk,reset,ticks,1'b1,pcm,xyz_valid,xyz_tick,x,y,z,
        valid,ft,af,vf,av,vv,an,xn,late);
    always @(negedge clk)if(valid)begin
        $display("FEATURE %0d %0d %0d %0d %0d %0d %0d",ft,af,vf,av,vv,an,xn);n=n+1;
    end
    initial begin
        repeat(5)@(negedge clk);reset=0;wait(ticks==520);@(negedge clk);
        if(n!=3 || late!=0)$fatal(1,"feature count/late mismatch");
        $display("PASS FEATURES late SPI placement, invalid empty XYZ window, signed audio minimum");$finish;
    end
endmodule
