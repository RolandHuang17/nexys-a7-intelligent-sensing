`timescale 1ns/1ps
module tb_music_abort;
 reg clk=0;always #5 clk=~clk;
 reg reset=1;reg [63:0] ticks=0,idx=0;always @(posedge clk)ticks<=ticks+1;
 reg pv=0;reg signed [15:0] pcm=0;
 reg cs=0;reg [15:0] len=0,seq=0;reg [127:0] head=0;reg [31:0] eid=0;
 reg [8:0] addr=0;wire [7:0] data;wire done,en;wire [15:0] rlen,led;
 music_core #(.MAX_SAMPLES(32)) dut(.clk(clk),.reset(reset),.ticks(ticks),.pcm_index(idx),.pcm_valid(pv),.pcm(pcm),
  .xyz_valid(1'b0),.xyz_tick(64'd0),.x(16'sd0),.y(16'sd0),.z(16'sd1000),.center(1'b0),
  .command_start(cs),.command_length(len),.command_seq(seq),.command_head(head),.command_event(eid),
  .reply_address(addr),.reply_data(data),.done(done),.reply_length(rlen),.enabled(en),.leds(led),.panel_quiet(1'b0));
 integer i;reg [31:0] rid,old_id,crc;
 task clocks(input integer n);begin repeat(n)@(negedge clk);end endtask
 task transact(input [127:0] h,input [15:0] length,input [31:0] record,input [7:0] expected);
 begin
  @(negedge clk);head=h;len=length;eid=record;seq=seq+1;cs=1;
  @(negedge clk);cs=0;
  while(!done)clocks(1);
  addr=0;#1;if(data!==expected)$fatal(1,"subcmd%0d response%0d expected%0d",h[7:0],data,expected);
  clocks(1);
 end endtask
 task start_record;
 begin
  // Isolate ABORT at the registered triple-trigger boundary; the independent
  // collector/three actual tap pulses are tested by tb_music_triple.
  @(negedge clk);force dut.triple_pulse=1;
  @(negedge clk);release dut.triple_pulse;dut.triple_pulse=0;clocks(2);
  if(dut.capture_state!=1)$fatal(1,"triple record did not start");rid=dut.record_id;
 end endtask
 task sample(input integer value);
 begin
  @(negedge clk);pv=1;pcm=value;idx=idx+1;
  @(negedge clk);pv=0;
  clocks(2);
 end endtask
 task assert_empty;
 begin
  if(dut.capture_state!=0 || dut.job_active || dut.count!=0 || dut.progress!=0 || dut.crc_phase!=0 || dut.full_crc!=0 || dut.prefix_crc!=0 || dut.ack_cache || dut.start_cache)
   $fatal(1,"abort left capture/CRC/cache state active");
  if(dut.record_id!=rid || !en || !dut.wake || dut.target!=32)$fatal(1,"abort changed ID or configuration");
  if(rlen!=128)$fatal(1,"abort changed status response length");
 end endtask
 initial begin
  clocks(5);reset=0;clocks(3);
  // Same existing configure wire format: enabled+wake, target32, high80/low32,
  // min150/max600. MAX_SAMPLES32 is a digital fixture, not physical recording.
  transact({16'd600,16'd150,16'd32,16'd80,32'd32,16'd0,8'd3,8'd0},16,0,0);
  start_record();sample(100);sample(-200);sample(300);
  transact(128'd6,1,rid,0);assert_empty();
  $display("ABORT_CASE early_record_discard PASS");
  transact(128'd6,1,rid,0);assert_empty();
  $display("ABORT_CASE duplicate_current_id_idempotent PASS");
  // No old bytes may be read after cancellation; existing bounds validation
  // rejects the request before its frozen-state validation (error7).
  transact({72'd0,16'd1,32'd0,8'd3},7,rid,7);
  if(rlen!=32 || dut.count!=0)$fatal(1,"aborted PCM remained readable");
  $display("ABORT_CASE discarded_buffer_unreadable PASS");
  old_id=rid;start_record();sample(1234);
  transact(128'd6,1,old_id,3);
  if(dut.capture_state!=1 || dut.count!=1 || dut.record_id!=rid)$fatal(1,"stale cancel changed new record");
  transact(128'd6,0,rid,7);
  if(dut.capture_state!=1 || dut.count!=1)$fatal(1,"bad length changed capture");
  transact(128'd6,1,rid,0);assert_empty();
  $display("ABORT_CASE old_record_and_bad_length_rejected PASS");
  // ABORT wins over a one-cycle wake/manual start at the same register edge.
  @(negedge clk);head=6;len=1;eid=rid;seq=seq+1;cs=1;
  force dut.triple_pulse=1'b1;
  @(negedge clk);cs=0;release dut.triple_pulse;
  // Release of a forced reg retains its forced value in simulation. Restore
  // the zero that the real detector assigns on every non-pulse clock.
  dut.triple_pulse=0;
  while(!done)clocks(1);clocks(1);assert_empty();
  $display("ABORT_CASE simultaneous_start_priority PASS");
  start_record();
  for(i=0;i<31;i=i+1)sample(i);
  @(negedge clk);pv=1;pcm=31;idx=idx+1;
  @(negedge clk);pv=0;
  if(dut.capture_state!=2)$fatal(1,"fixture did not reach DRAIN");
  transact(128'd6,1,rid,0);assert_empty();
  $display("ABORT_CASE drain_crc_job_cancel PASS");
  start_record();for(i=0;i<32;i=i+1)sample(i+100);clocks(5);
  if(dut.capture_state!=3)$fatal(1,"fixture did not freeze");
  transact(128'd6,1,rid,0);assert_empty();
  $display("ABORT_CASE frozen_record_cancel PASS");
  start_record();for(i=0;i<32;i=i+1)sample(i+200);clocks(5);crc=dut.full_crc;
  transact({56'd0,crc,32'd32,8'd4},9,rid,0);
  if(dut.capture_state!=0 || !dut.job_active || !dut.ack_cache)$fatal(1,"fixture did not reach matching EMPTY");
  transact(128'd6,1,rid,0);assert_empty();
  transact({56'd0,crc,32'd32,8'd4},9,rid,5);
  if(dut.capture_state!=0 || dut.count!=0)$fatal(1,"old ACK affected aborted state");
  $display("ABORT_CASE matching_empty_and_ack_cache_cancel PASS");
  // A new eligible registered triple starts a new record after cancellation.
  old_id=rid;start_record();
  if(rid!=old_id+1)$fatal(1,"record ID did not advance after cancel");
  for(i=0;i<32;i=i+1)sample((i*37)^16'h9a35);clocks(5);
  if(dut.capture_state!=3 || dut.count!=32 || dut.overflow!=0)$fatal(1,"restart recording incomplete");
  $display("ABORT_RESTART_CRC %08x",dut.full_crc);
  $display("ABORT_CASE triple_restart_and_crc PASS");
  $display("PASS MUSIC ABORT");$finish;
 end
 initial begin #1000000;$fatal(1,"abort test watchdog");end
endmodule
