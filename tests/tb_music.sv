`timescale 1ns/1ps
module tb_music;
 reg clk=0;always #5 clk=~clk;
 reg reset=1;reg [63:0] ticks=0,idx=0;
 always @(posedge clk)ticks<=ticks+1;
 reg pv=0,xv=0,center=0,cs=0;reg signed [15:0] pcm=0,x=0,y=0,z=1000;
 reg [63:0] xt=0;reg [15:0] len=0,seq=1;reg [127:0] head=0;reg [31:0] event_id=0;
 reg [8:0] addr=0;wire [7:0] data;wire done,en;wire [15:0] rlen,led;
 music_core dut(.clk(clk),.reset(reset),.ticks(ticks),.pcm_index(idx),.pcm_valid(pv),.pcm(pcm),.xyz_valid(xv),.xyz_tick(xt),.x(x),.y(y),.z(z),.center(center),.command_start(cs),.command_length(len),.command_seq(seq),.command_head(head),.command_event(event_id),.reply_address(addr),.reply_data(data),.done(done),.reply_length(rlen),.enabled(en),.leds(led),.panel_quiet(1'b0));
 reg [7:0] reply[0:511];reg [31:0] id,total,crc;integer i,k;
 task request;
 input [127:0] h;input [15:0] n;input [31:0] eid;
 begin
  @(negedge clk);head=h;len=n;event_id=eid;cs=1;
  @(negedge clk);cs=0;
  wait(!done);wait(done);#1;
  for(k=0;k<rlen;k=k+1)begin addr=k;#1;reply[k]=data;end
 end endtask
 task trigger_record;
 begin
  // Test fixture at the production collector output, never a UART bypass.
  @(negedge clk);force dut.triple_pulse=1;
  @(negedge clk);release dut.triple_pulse;dut.triple_pulse=0;
  repeat(3)@(negedge clk);
 end endtask
 task readcheck;input integer off,num;reg [127:0] h;reg signed [15:0] expected,got;
 begin
  h=3;h[39:8]=off;h[55:40]=num;seq=seq+1;request(h,7,id);
  if(reply[0]!=0 || rlen!=32+num*2)$fatal(1,"READ rejected");
  for(i=0;i<num;i=i+1)begin
   expected=((off+i)*37)^16'h9a35;got={reply[33+2*i],reply[32+2*i]};
   if(got!==expected)$fatal(1,"PCM address %d got %h expected %h",off+i,got,expected);
  end
 end endtask
 initial begin
  repeat(10)@(negedge clk);reset=0;
  head=0;head[9:8]=3;head[63:32]=160000;head[79:64]=80;head[95:80]=32;head[111:96]=150;head[127:112]=600;
  request(head,16,0);if(reply[0]!=0)$fatal(1,"CONFIG");
  seq=2;request(1,1,0);if(reply[0]!=8 || dut.record_id!=0)$fatal(1,"knock required");
  trigger_record();id=dut.record_id;if(id!=1 || dut.capture_state!=1)$fatal(1,"triple trigger");
  request(1,1,0);if(reply[0]!=1 || dut.record_id!=1)$fatal(1,"busy START");
  seq=3;request(1,1,0);if(reply[0]!=1 || dut.record_id!=1)$fatal(1,"busy START");
  for(i=0;i<160000;i=i+1)begin
   @(negedge clk);pv=1;pcm=(i*37)^16'h9a35;idx=i;
   @(negedge clk);pv=0;repeat(6)@(negedge clk);
  end
  wait(dut.capture_state==3);seq=4;request(2,1,0);
  total={reply[15],reply[14],reply[13],reply[12]};crc={reply[23],reply[22],reply[21],reply[20]};
  if(total!=160000 || dut.overflow!=0)$fatal(1,"count / overrun");
  $display("MUSIC_CRC %08x %08x",crc,dut.prefix_crc);
  $writememh("music_status.hex",reply,0,127);
  readcheck(0,240);readcheck(65530,24);readcheck(131065,24);readcheck(159990,10);readcheck(65530,24);
  $writememh("music_read.hex",reply,0,79);
  head=3;head[39:8]=159999;head[55:40]=2;seq=seq+1;request(head,7,id);if(reply[0]==0)$fatal(1,"bounds");
  head=4;head[39:8]=160000;head[71:40]=crc^1;seq=seq+1;request(head,9,id);if(reply[0]!=5 || dut.capture_state!=3)$fatal(1,"bad ack");
  head[71:40]=crc;seq=seq+1;request(head,9,id);if(reply[0]!=0 || dut.capture_state!=0)$fatal(1,"ack");
  request(head,9,id);if(reply[0]!=0)$fatal(1,"duplicate ack");
  seq=seq+1;request(5,1,0);if(dut.job_active)$fatal(1,"finish");
  seq=2;request(1,1,0);if(reply[0]!=8 || dut.record_id!=1)$fatal(1,"no manual bypass after FINISH");trigger_record();if(dut.record_id!=2)$fatal(1,"new triple after FINISH");
  $display("PASS MUSIC 160000 samples, high addresses, repeated read, idempotency, CRC and release");$finish;
 end
 initial begin #30000000;$fatal(1,"watchdog");end
endmodule
