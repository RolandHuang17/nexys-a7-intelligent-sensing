`timescale 1ns/1ps
module tb_music_half;
 reg clk=0;always #5 clk=~clk;
 reg reset=1;reg [63:0] ticks=0,idx=0;always @(posedge clk)ticks<=ticks+1;
 reg pv=0,cs=0;reg [15:0] len=0,seq=0;reg [127:0] head=0;reg [31:0] eid=0;reg [8:0] addr=0;
 wire [7:0] data;wire done,en;wire [15:0] rlen,led;
 music_core #(.MAX_SAMPLES(32)) dut(.clk(clk),.reset(reset),.ticks(ticks),.pcm_index(idx),.pcm_valid(pv),.pcm(16'sd1000),.xyz_valid(1'b0),.xyz_tick(64'd0),.x(16'sd0),.y(16'sd0),.z(16'sd1000),.center(1'b0),.command_start(cs),.command_length(len),.command_seq(seq),.command_head(head),.command_event(eid),.reply_address(addr),.reply_data(data),.done(done),.reply_length(rlen),.enabled(en),.leds(led),.panel_quiet(1'b0));
 reg [7:0] reply[0:511];integer k,i;reg [31:0] crc,id;
 task request;input [127:0] h;input [15:0] n;
 begin
  @(negedge clk);head=h;len=n;seq=seq+1;cs=1;
  @(negedge clk);cs=0;wait(!done);wait(done);#1;
  for(k=0;k<rlen;k=k+1)begin addr=k;#1;reply[k]=data;end
 end endtask
 task sample;
 begin @(negedge clk);pv=1;idx=idx+1;@(negedge clk);pv=0;repeat(78)@(negedge clk);end endtask
 initial begin
  repeat(10)@(negedge clk);reset=0;
  head=0;head[15:8]=11;head[63:32]=32;head[79:64]=80;head[95:80]=32;head[111:96]=150;head[127:112]=600;
  request(head,16);if(reply[0]!=0)$fatal(1,"half config");
  repeat(70)sample();request(1,1);if(reply[0]!=8)$fatal(1,"half manual bypass");
  @(negedge clk);force dut.triple_pulse=1;
  @(negedge clk);release dut.triple_pulse;dut.triple_pulse=0;repeat(3)@(negedge clk);
  repeat(80)sample();wait(dut.capture_state==3);request(2,1);
  if({reply[19],reply[18],reply[17],reply[16]}!=8000 || {reply[15],reply[14],reply[13],reply[12]}!=32)$fatal(1,"half rate/count");
  $writememh("music_half_status.hex",reply,0,127);crc={reply[23],reply[22],reply[21],reply[20]};id={reply[7],reply[6],reply[5],reply[4]};
  head=3;head[39:8]=0;head[55:40]=32;eid=id;request(head,7);
  if(reply[0]!=0 || {reply[15],reply[14]}!=8000)$fatal(1,"half read header");
  for(i=0;i<32;i=i+1)if({reply[33+2*i],reply[32+2*i]}!=1000)$fatal(1,"half data");
  $display("HALF_CRC %08x",crc);$display("PASS MUSIC HALF filtered capture and rate-aware readback");$finish;
 end
 initial begin #1000000;$fatal(1,"half watchdog");end
endmodule
