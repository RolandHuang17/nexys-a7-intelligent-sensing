`timescale 1ns/1ps
module tb_music_panel_quiet;
 reg clk=0;always #5 clk=~clk;
 reg reset=1;reg [63:0] ticks=0,idx=0;always @(posedge clk)ticks<=ticks+1;
 reg pv=0,xv=0,center=0,cs=0,quiet=1;
 reg signed [15:0] pcm=0,x=0,y=0,z=1000;reg [63:0] xt=0;
 reg [15:0] len=0,seq=1;reg [127:0] head=0;reg [31:0] event_id=0;
 reg [8:0] addr=0;wire [7:0] data;wire done,en;wire [15:0] rlen,led;
 music_core #(.CLOCK_HZ(1000)) dut(
  .clk(clk),.reset(reset),.ticks(ticks),.pcm_index(idx),.pcm_valid(pv),.pcm(pcm),
  .xyz_valid(xv),.xyz_tick(xt),.x(x),.y(y),.z(z),.center(center),
  .command_start(cs),.command_length(len),.command_seq(seq),.command_head(head),.command_event(event_id),
  .reply_address(addr),.reply_data(data),.done(done),.reply_length(rlen),.enabled(en),.leds(led),.panel_quiet(quiet));
 reg [7:0] reply[0:511];integer i,k;reg [31:0] id,crc;reg [63:0] probe,locked;
 task request(input [127:0] h,input [15:0] n,input [31:0] eid);
 begin
  @(negedge clk);head=h;len=n;event_id=eid;cs=1;
  @(negedge clk);cs=0;wait(!done);wait(done);#1;
  for(k=0;k<rlen;k=k+1)begin addr=k;#1;reply[k]=data;end
 end endtask
 task configure(input bit game_mode);
 reg [127:0] h;begin
  h=0;h[8]=1;h[9]=1;h[10]=game_mode;h[63:32]=160000;
  h[79:64]=80;h[95:80]=32;h[111:96]=150;h[127:112]=600;
  seq=seq+1;request(h,16,0);if(reply[0]!=0)$fatal(1,"CONFIG");
 end endtask
 initial begin
  repeat(8)@(negedge clk);reset=0;configure(0);
  // Inject the detector's actual pulse at its registered boundary, not a
  // modified detector algorithm; electrical switch noise must not start jobs.
  @(negedge clk);force dut.triple_pulse=1;@(negedge clk);release dut.triple_pulse;dut.triple_pulse=0;
  repeat(4)@(negedge clk);
  if(dut.capture_state!=0 || dut.record_id!=0)$fatal(1,"quiet triple woke capture");
  $display("MUSIC_PANEL_CASE quiet_blocks_triple_wake PASS");
  seq=seq+1;request(1,1,0);
  if(reply[0]!=8 || dut.capture_state!=0 || dut.record_id!=0)$fatal(1,"manual START bypassed triple gate");
  $display("MUSIC_PANEL_CASE manual_start_never_bypasses_triple PASS");
  quiet=0;@(negedge clk);force dut.triple_pulse=1;@(negedge clk);release dut.triple_pulse;dut.triple_pulse=0;
  repeat(4)@(negedge clk);id=dut.record_id;
  if(id!=1 || dut.capture_state!=1)$fatal(1,"triple start");
  for(i=0;i<160000;i=i+1)begin
   @(negedge clk);pv=1;pcm=(i*37)^16'h9a35;idx=i;quiet=(i/1000)&1;
   @(negedge clk);pv=0;repeat(6)@(negedge clk);
  end
  wait(dut.capture_state==3);seq=seq+1;request(2,1,0);
  crc={reply[23],reply[22],reply[21],reply[20]};
  if(dut.count!=160000 || dut.overflow!=0)$fatal(1,"quiet interrupted samples/CRC");
  $display("MUSIC_PANEL_CRC %08x %08x",crc,dut.prefix_crc);
  $display("MUSIC_PANEL_CASE quiet_preserves_160000_pcm_crc PASS");
  head=4;head[39:8]=160000;head[71:40]=crc;seq=seq+1;request(head,9,id);
  if(reply[0]!=0)$fatal(1,"ACK");seq=seq+1;request(5,1,0);configure(0);
  quiet=0;@(negedge clk);force dut.triple_pulse=1;@(negedge clk);release dut.triple_pulse;dut.triple_pulse=0;
  repeat(4)@(negedge clk);
  if(dut.capture_state!=1 || dut.record_id!=2)$fatal(1,"quiet release did not restore triple wake");
  $display("MUSIC_PANEL_CASE unquiet_restores_triple_wake PASS");
  reset=1;repeat(5)@(negedge clk);reset=0;quiet=0;configure(1);
  @(negedge clk);force dut.triple_pulse=1;@(negedge clk);release dut.triple_pulse;dut.triple_pulse=0;
  repeat(4)@(negedge clk);quiet=1;
  if(dut.capture_state!=1 || !dut.game)$fatal(1,"game triple start");
  probe=ticks+1;force dut.tap_tick=probe;force dut.tap_pulse=1;
  repeat(2)@(negedge clk);release dut.tap_tick;release dut.tap_pulse;
  if(dut.human_tick!=0)$fatal(1,"quiet tap locked game answer");
  $display("MUSIC_PANEL_CASE quiet_blocks_game_human_lock PASS");
  quiet=0;probe=ticks+1;force dut.tap_tick=probe;force dut.tap_pulse=1;
  repeat(2)@(negedge clk);release dut.tap_tick;release dut.tap_pulse;
  locked=dut.human_tick;if(locked==0)$fatal(1,"unquiet did not restore game tap");
  probe=ticks+100;force dut.tap_tick=probe;force dut.tap_pulse=1;
  repeat(2)@(negedge clk);release dut.tap_tick;release dut.tap_pulse;
  if(dut.human_tick!=locked)$fatal(1,"first human tap lock overwritten");
  $display("MUSIC_PANEL_CASE unquiet_restores_one_shot_human_lock PASS");
  $display("PASS MUSIC_PANEL_QUIET");$finish;
 end
 initial begin #30000000;$fatal(1,"watchdog");end
endmodule
