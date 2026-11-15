`timescale 1ns/1ps
module tb_music_triple;
 reg clk=0;always #5 clk=~clk;
 reg reset=1,cs=0,quiet=0;reg [63:0] ticks=0;always @(posedge clk)ticks<=ticks+1;
 reg [15:0] len=0,seq=0;reg [127:0] head=0;reg [31:0] eid=0;reg [8:0] addr=0;
 wire [7:0] data;wire done,en;wire [15:0] rlen,led;
 music_core #(.MAX_SAMPLES(32),.CLOCK_HZ(1000)) dut(.clk(clk),.reset(reset),.ticks(ticks),.pcm_index(64'd0),.pcm_valid(1'b0),.pcm(16'sd0),
  .xyz_valid(1'b0),.xyz_tick(64'd0),.x(16'sd0),.y(16'sd0),.z(16'sd1000),.center(1'b0),
  .command_start(cs),.command_length(len),.command_seq(seq),.command_head(head),.command_event(eid),
  .reply_address(addr),.reply_data(data),.done(done),.reply_length(rlen),.enabled(en),.leds(led),.panel_quiet(quiet));
 reg [63:0] last_tap=0;reg [31:0] id;reg [127:0] cfg;
 task clocks(input integer count);begin repeat(count)@(negedge clk);end endtask
 task request(input [127:0] h,input [15:0] length,input [31:0] record,input [7:0] error);
 begin
  @(negedge clk);head=h;len=length;eid=record;seq=seq+1;cs=1;
  @(negedge clk);cs=0;while(!done)clocks(1);addr=0;#1;
  if(data!==error)$fatal(1,"triple request%0d error%0d expected%0d",h[7:0],data,error);
  clocks(1);
 end endtask
 task configure(input [7:0] flags);
 begin cfg={16'd600,16'd150,16'd32,16'd80,32'd32,16'd0,flags,8'd0};request(cfg,16,0,0);end endtask
 task fresh(input [7:0] flags);
 begin reset=1;quiet=0;clocks(4);reset=0;clocks(3);configure(flags);last_tap=0;end endtask
 task tap(input integer gap);
 begin
  if(gap!=0)while(ticks<last_tap+gap)clocks(1);else clocks(1);
  last_tap=ticks;
  // Test the existing detector's registered pulse boundary. The real XYZ
  // detector and old double diagnostics have their separate unchanged test.
  force dut.tap_pulse=1;
  @(negedge clk);release dut.tap_pulse;dut.tap_pulse=0;clocks(2);
 end endtask
 task require_empty;
 begin if(dut.capture_state!=0 || dut.record_id!=0 || dut.job_active)$fatal(1,"record started without three eligible taps");end endtask
 task concurrent_config(input [7:0] flags);
 begin
  // A real third-tap register pulse may already exist when the UART CONFIG
  // arrives. Enter/exit is a barrier even on that exact capture edge.
  fresh(3);tap(0);tap(150);
  @(negedge clk);head={16'd600,16'd150,16'd32,16'd80,32'd32,16'd0,flags,8'd0};len=16;eid=0;seq=seq+1;cs=1;
  force dut.triple_pulse=1;
  @(negedge clk);cs=0;release dut.triple_pulse;dut.triple_pulse=0;
  while(!done)clocks(1);clocks(1);require_empty();
  if(dut.triple_pending!=0 || en!==flags[0] || dut.wake!==flags[1])$fatal(1,"CONFIG did not clear pending/apply flags");
 end endtask
 task boundary(input integer first_gap,second_gap,input bit expected);
 begin
  fresh(3);tap(0);tap(first_gap);require_empty();tap(second_gap);
  if((dut.capture_state==1)!==expected)$fatal(1,"triple adjacentgap%0d/%0d expected%0d",first_gap,second_gap,expected);
 end endtask
 initial begin
  clocks(5);reset=0;clocks(3);configure(3);
  request(128'd1,1,0,8);require_empty();request(128'd1,0,0,7);require_empty();
  tap(0);require_empty();if(dut.triple_pending!=1)$fatal(1,"first tap");
  tap(150);require_empty();if(dut.triple_pending!=2)$fatal(1,"second tap");
  tap(150);if(dut.record_id!=1 || dut.capture_state!=1)$fatal(1,"third tap did not start");
  request(128'd1,1,0,1);
  $display("TRIPLE_CASE one_two_wait_three_start_no_uart_bypass PASS");
  boundary(149,150,0);boundary(150,150,1);boundary(600,600,1);
  boundary(601,150,0);boundary(150,149,0);boundary(150,601,0);
  $display("TRIPLE_CASE adjacent_min_max_inclusive PASS");
  reset=1;clocks(4);reset=0;clocks(3);last_tap=0;
  tap(0);tap(150);tap(150);require_empty();configure(3);
  tap(0);require_empty();tap(150);require_empty();tap(150);
  if(dut.capture_state!=1)$fatal(1,"pre-entry taps blocked subsequent genuine triple");
  $display("TRIPLE_CASE pre_entry_taps_not_carried PASS");
  fresh(3);tap(0);tap(150);quiet=1;clocks(3);quiet=0;tap(150);require_empty();
  if(dut.triple_pending!=1)$fatal(1,"quiet failed to clear old pending");
  tap(150);tap(150);if(dut.capture_state!=1)$fatal(1,"triple after quiet");
  $display("TRIPLE_CASE quiet_restarts_sequence PASS");
  fresh(3);tap(0);tap(150);request(128'd6,1,0,0);tap(150);require_empty();
  tap(150);tap(150);if(dut.capture_state!=1)$fatal(1,"triple after cancel");
  $display("TRIPLE_CASE cancel_restarts_sequence PASS");
  fresh(3);tap(0);tap(150);configure(3);tap(150);require_empty();
  $display("TRIPLE_CASE configuration_restarts_sequence PASS");
  concurrent_config(0);concurrent_config(3);
  fresh(3);quiet=1;@(negedge clk);force dut.triple_pulse=1;
  @(negedge clk);release dut.triple_pulse;dut.triple_pulse=0;clocks(2);quiet=0;require_empty();
  $display("TRIPLE_CASE same_clock_config_and_quiet_barriers PASS");
  fresh(1);tap(0);tap(150);tap(150);require_empty();configure(3);tap(0);tap(150);tap(150);
  if(dut.capture_state!=1)$fatal(1,"wake rearm");
  $display("TRIPLE_CASE wake_required_and_clean_rearm PASS");
  id=dut.record_id;tap(150);tap(150);tap(150);
  if(dut.record_id!=id || dut.triple_pending!=0)$fatal(1,"busy triple restarted or armed nextjob");
  request(128'd6,1,id,0);tap(150);
  if(dut.capture_state!=0 || dut.record_id!=id || dut.triple_pending!=1)$fatal(1,"busy taps leaked across cancel");
  tap(150);tap(150);if(dut.record_id!=id+1)$fatal(1,"three fresh taps after busy/cancel");
  $display("TRIPLE_CASE busy_taps_never_queue_capture PASS");
  fresh(3);tap(0);tap(150);reset=1;clocks(4);reset=0;clocks(3);configure(3);tap(0);require_empty();
  $display("TRIPLE_CASE reset_clears_pending PASS");
  fresh(7);request(128'd1,1,0,8);tap(0);tap(150);require_empty();tap(150);
  if(!dut.game || dut.capture_state!=1 || dut.record_id!=1)$fatal(1,"game needs same triple");
  request(128'd1,1,0,1);
  $display("TRIPLE_CASE game_has_no_manual_backdoor PASS");
  $display("PASS MUSIC TRIPLE");$finish;
 end
 initial begin #2000000;$fatal(1,"triple test watchdog");end
endmodule
