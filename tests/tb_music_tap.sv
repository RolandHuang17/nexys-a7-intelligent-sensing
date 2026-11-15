`timescale 1ns/1ps
module tb_music_tap;
 reg clk=0;always #5 clk=~clk;reg reset=1;reg [63:0] ticks=0,idx=0;
 always @(posedge clk)ticks<=ticks+1;
 reg pv=0,xv=0,center=0,cs=0;reg signed [15:0] pcm=0,x=0,y=0,z=1000;reg [63:0] xt=0;
 reg [15:0] len=0,seq=0;reg [127:0] head=0;reg [31:0] eid=0;reg [8:0] addr=0;
 wire [7:0] data;wire done,en;wire [15:0] rlen,led;
 music_core #(.MAX_SAMPLES(32),.CLOCK_HZ(1000)) dut(.clk(clk),.reset(reset),.ticks(ticks),.pcm_index(idx),.pcm_valid(pv),.pcm(pcm),.xyz_valid(xv),.xyz_tick(xt),.x(x),.y(y),.z(z),.center(center),.command_start(cs),.command_length(len),.command_seq(seq),.command_head(head),.command_event(eid),.reply_address(addr),.reply_data(data),.done(done),.reply_length(rlen),.enabled(en),.leds(led),.panel_quiet(1'b0));
 reg [63:0] first;integer gap;
 task configure;
 begin
  reset=1;repeat(4)@(negedge clk);reset=0;
  head=0;head[9:8]=3;head[63:32]=32;head[79:64]=80;head[95:80]=32;head[111:96]=150;head[127:112]=600;
  @(negedge clk);len=16;cs=1;seq=seq+1;@(negedge clk);cs=0;wait(!done);wait(done);repeat(2)@(negedge clk);
 end endtask
 task sample;input signed [15:0] value;
 begin @(negedge clk);x=value;xt=ticks;xv=1;@(negedge clk);xv=0;repeat(4)@(negedge clk);end endtask
 task pair_case;input integer interval;input integer should_pair;
 begin
  configure();sample(0);sample(500);first=dut.tap_tick;sample(500);sample(0);sample(0);
  while(ticks<first+interval-1)@(negedge clk);
  sample(500);repeat(8)@(negedge clk);
  if((dut.double_seq==1)!==should_pair)$fatal(1,"pair boundary gap %0d pairs %0d",interval,dut.double_seq);
  if(dut.record_id!=0 || dut.capture_state!=0)$fatal(1,"only two taps must never record");

 end endtask
 initial begin
  pair_case(149,0);pair_case(150,1);pair_case(600,1);pair_case(601,0);
  configure();center=1;repeat(5)@(negedge clk);center=0;repeat(5)@(negedge clk);center=1;repeat(5)@(negedge clk);
  if(dut.center_seq!=2)$fatal(1,"centre edges");
  $display("PASS MUSIC TAP 149/150/600/601ms, two taps never record, centre edges");$finish;
 end
 initial begin #1000000;$fatal(1,"watchdog");end
endmodule
