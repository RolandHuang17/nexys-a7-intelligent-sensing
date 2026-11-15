`timescale 1ns/1ps
module tb_music_decimator;
 reg clk=0;always #5 clk=~clk;
 reg reset=1,en=0,pv=0;reg signed [15:0] pcm=0;reg [63:0] index=0;
 wire valid;wire signed [15:0] value;wire [63:0] out_index;
 music_decimator dut(clk,reset,en,pv,pcm,index,valid,value,out_index);
 reg [15:0] input_data[0:2047];integer i,fd,count=0;
 always @(posedge clk)if(valid)begin $fwrite(fd,"%0d %0d\n",out_index,$signed(value));count=count+1;end
 initial begin
  $readmemh("fir_input.hex",input_data);fd=$fopen("fir_output.txt","w");
  repeat(10)@(negedge clk);reset=0;en=1;
  for(i=0;i<2048;i=i+1)begin
   @(negedge clk);pv=1;pcm=input_data[i];index=i;
   @(negedge clk);pv=0;repeat(78)@(negedge clk);
  end
  repeat(100)@(negedge clk);$fclose(fd);
  if(count!=1024)$fatal(1,"decimator output count");
  $display("PASS MUSIC DECIMATOR 1024 bit-exact outputs");$finish;
 end
endmodule
