`timescale 1ns/1ps
module tb_board_panel;
 reg clk=0;always #5 clk=~clk;
 reg reset=1;reg [63:0] ticks=0;always @(posedge clk)ticks<=ticks+1;
 reg [15:0] switches=16'h0c00,switches_raw=0,legacy_leds=16'ha55a;
 reg pcm_valid=0;reg signed [15:0] pcm=0,temperature_raw=3200;reg temperature_valid=1;
 reg music_enabled=0;reg [1:0] music_state=0;
 reg [31:0] music_target=160000,music_count=0,music_rate=8000,music_record_id=7;
 reg [4:0] music_progress=0;reg music_game=0,music_wake=1,music_job_active=0;
 reg [15:0] music_max_ms=1000;
 reg command_start=0;reg [15:0] command_length=16;reg [127:0] command_head=0;reg [31:0] command_event=7;
 wire done,quiet;wire [7:0] reply_data,segments,anodes;wire [15:0] led;wire [2:0] rgb0,rgb1;
 board_panel #(.CLOCK_HZ(1000)) dut(
  .clk(clk),.reset(reset),.ticks(ticks),.switches(switches),.switches_raw(switches_raw),.legacy_leds(legacy_leds),
  .pcm_valid(pcm_valid),.pcm(pcm),.temperature_raw(temperature_raw),.temperature_valid(temperature_valid),
  .music_enabled(music_enabled),.music_state(music_state),.music_target(music_target),.music_count(music_count),
  .music_rate(music_rate),.music_record_id(music_record_id),.music_progress(music_progress),
  .music_game(music_game),.music_wake(music_wake),.music_job_active(music_job_active),.music_max_ms(music_max_ms),
  .command_start(command_start),.command_length(command_length),.command_head(command_head),.command_event(command_event),
  .done(done),.reply_data(reply_data),.quiet(quiet),.led(led),.rgb0(rgb0),.rgb1(rgb1),.segments(segments),.anodes(anodes));
 integer i,n,blank_count,active_count;reg [7:0] prior_anodes,prior_segments;reg [7:0] ack;
 reg [11:0] before_result,before_watchdog;reg [31:0] before_seq;reg [15:0] before_remaining;
 reg [7:0] seen_segments[0:7];reg [7:0] seen_mask;integer digit,bright,red_on,green_on,blue_on,wide,narrow,period;
 reg [8:0] prior_phase;
 task clocks(input integer count);begin repeat(count)@(negedge clk);end endtask
 task request(input [7:0] version,phase,input [15:0] progress,input [31:0] value,session,seq,eid,input [15:0] len);
 begin
  @(negedge clk);command_head={seq,session,value,progress,phase,version};command_event=eid;command_length=len;command_start=1;
  @(negedge clk);if(!done)$fatal(1,"PANEL reply missing");ack=reply_data;command_start=0;
  @(negedge clk);if(done)$fatal(1,"PANEL done must be one cycle");
 end endtask
 task accepted(input [7:0] phase,input [15:0] progress,input [31:0] value,seq);
 begin request(1,phase,progress,value,32'h12345678,seq,music_record_id,16);if(ack!=0)$fatal(1,"PANEL rejected phase %d",phase);end endtask
 task capture_digits;
 begin
  seen_mask=0;
  for(integer c=0;c<48;c=c+1)begin
   @(negedge clk);
   for(integer d=0;d<8;d=d+1)if(anodes==~(8'b1<<d))begin seen_segments[d]=segments;seen_mask[d]=1;end
  end
  if(seen_mask!=8'hff)$fatal(1,"not all physical digits scanned");
 end endtask
 initial begin
  clocks(5);reset=0;clocks(20);
  if(dut.session_valid || dut.pc_fresh || dut.display_phase!=0)$fatal(1,"reset/local fallback");
  $display("PANEL_CASE reset_local_fallback PASS");
  request(1,8'hfe,16'hffff,0,32'h12345678,0,7,15);if(ack!=7)$fatal(1,"bad length");
  request(2,8'hfe,16'hffff,0,32'h12345678,0,7,16);if(ack!=7)$fatal(1,"bad version");
  request(1,10,16'hffff,0,32'h12345678,0,7,16);if(ack!=7)$fatal(1,"bad phase");
  request(1,1,1001,0,32'h12345678,0,7,16);if(ack!=7)$fatal(1,"bad permille");
  if(dut.session_valid)$fatal(1,"invalid command changed state");
  $display("PANEL_CASE invalid_commands PASS");
  request(1,1,0,0,32'h12345678,1,7,16);if(ack!=1)$fatal(1,"must sync first");
  accepted(8'hfe,16'hffff,0,0);
  if(!dut.pc_fresh || dut.session_id!=32'h12345678 || dut.pc_phase!=0)$fatal(1,"SYNC");
  $display("PANEL_CASE session_sync PASS");
  accepted(4,1000,1250,1);clocks(80);before_result=dut.result_ms;before_watchdog=dut.watchdog_ms;
  accepted(4,1000,1250,1);
  if(dut.result_ms>=before_result || dut.watchdog_ms<=before_watchdog)$fatal(1,"duplicate restarted result or failed heartbeat");
  before_seq=dut.last_seq;
  accepted(6,0,9999,1);if(dut.pc_phase!=4 || dut.pc_value!=1250)$fatal(1,"equal sequence changed display");
  $display("PANEL_CASE duplicate_heartbeat_no_restart PASS");
  request(1,6,0,0,32'h12345678,0,7,16);if(ack!=1)$fatal(1,"old sequence");
  request(1,6,0,0,32'h87654321,5,7,16);if(ack!=1)$fatal(1,"old session");
  request(1,6,0,0,32'h12345678,5,6,16);if(ack!=1)$fatal(1,"old record");
  request(1,8'hfe,16'hffff,0,32'h87654321,99,7,16);if(ack!=1)$fatal(1,"fresh session stolen");
  if(dut.last_seq!=before_seq || dut.pc_phase!=4)$fatal(1,"stale input modified state");
  $display("PANEL_CASE stale_session_record_sequence PASS");
  accepted(2,16'hffff,0,2);music_state=3;music_enabled=1;music_job_active=1;clocks(100);
  if(dut.display_phase!=2 || !dut.number_unknown)$fatal(1,"unknown transfer must be unknown");
  accepted(2,375,0,3);clocks(100);
  if(dut.number_unknown || dut.pc_progress!=375 || dut.number_binary!=375)$fatal(1,"actual transfer permille");
  $display("PANEL_CASE actual_or_unknown_progress PASS");
  music_state=1;music_count=40000;music_progress=12;accepted(4,1000,2000,4);clocks(400);
  if(dut.display_phase!=10 || dut.remaining_tenths!=150)$fatal(1,"local recording priority/remaining");
  $display("PANEL_CASE local_record_priority PASS");
  music_state=0;music_game=1;clocks(100);
  if(dut.display_phase!=7 || !dut.number_unknown)$fatal(1,"game leaked pass or invented ready/time");
  accepted(5,1000,2000,5);clocks(100);if(dut.display_phase!=7 || !dut.number_unknown)$fatal(1,"game leaked miss or invented ready/time");
  $display("PANEL_CASE game_neutral PASS");
  music_game=0;music_enabled=0;music_job_active=0;
  accepted(3,16'hffff,9876,6);clocks(20);if(dut.display_phase!=3)$fatal(1,"matching phase");
  clocks(3010);if(dut.pc_fresh || dut.display_phase!=0)$fatal(1,"3s PC watchdog did not fall back");
  request(1,4,1000,0,32'h12345678,7,7,16);if(ack!=1)$fatal(1,"expired nonsync accepted");
  request(1,8'hfe,16'hffff,0,32'h87654321,0,7,16);if(ack!=0 || dut.session_id!=32'h87654321)$fatal(1,"expired SYNC failed");
  $display("PANEL_CASE watchdog_and_new_session PASS");
  // Full brightness: scan must always select <=one active-low digit and blank
  // between digits. Segment data may only change in an all-anodes-off interval.
  switches=16'h0f00;legacy_leds=16'hffff;clocks(40);blank_count=0;active_count=0;prior_anodes=8'hff;prior_segments=segments;
  for(i=0;i<512;i=i+1)begin
   @(negedge clk);n=(~anodes)&8'hff;
   if(n!=0 && (n&(n-1))!=0)$fatal(1,"multiple active anodes");
   if(anodes==8'hff)blank_count=blank_count+1;else active_count=active_count+1;
   if(anodes!=prior_anodes && anodes!=8'hff && prior_anodes!=8'hff)$fatal(1,"no interdigit blank");
   if(segments!=prior_segments && anodes!=8'hff)$fatal(1,"segments changed while lit");
   prior_anodes=anodes;prior_segments=segments;
  end
  if(blank_count==0 || active_count==0)$fatal(1,"scan stuck");
  $display("PANEL_CASE scan_blank_mutual_exclusion PASS");
  // Actual levels generated by the legacy read-only style hit exactly0/255.
  legacy_leds=16'hffff;clocks(30);
  for(i=0;i<512;i=i+1)begin @(negedge clk);if(led!=16'hffff)$fatal(1,"PWM255 must always light");end
  legacy_leds=0;clocks(30);
  for(i=0;i<512;i=i+1)begin @(negedge clk);if(led!=0)$fatal(1,"PWM0 must always be off");end
  $display("PANEL_CASE pwm_endpoints PASS");
  // Blackout is output-only: local record state, count and timing still render
  // internally, and raw switch quiet only inhibits the independent wake path.
  music_enabled=1;music_state=1;music_job_active=1;music_count=80000;music_progress=8;
  switches[0]=1;switches_raw=1;clocks(400);
  if(led!=0 || rgb0!=0 || rgb1!=0 || anodes!=8'hff || segments!=8'hff)$fatal(1,"blackout outputs");
  if(dut.display_phase!=10 || dut.remaining_tenths!=100 || !quiet)$fatal(1,"blackout impacted local display truth/quiet");
  switches[0]=0;switches_raw=0;clocks(1300);if(quiet)$fatal(1,"quiet release");
  if(dut.display_phase!=10 || dut.remaining_tenths!=100)$fatal(1,"display disturbed record truth");
  $display("PANEL_CASE blackout_display_only PASS");
  music_enabled=0;music_state=0;music_job_active=0;switches=16'h0f10;temperature_raw=3200;temperature_valid=1;clocks(150);
  if(dut.number_kind!=11 || dut.number_binary!=250 || dut.number_unknown)$fatal(1,"temperature source");
  temperature_raw=5120;clocks(150);if(dut.number_binary!=400 || dut.number_negative)$fatal(1,"positive40C scaling boundary");
  temperature_raw=-5120;clocks(150);if(dut.number_binary!=400 || !dut.number_negative)$fatal(1,"negative40C scaling boundary");
  temperature_valid=0;clocks(50);if(!dut.number_unknown)$fatal(1,"invalid temperature not marked");
  switches=16'h0f20;pcm_valid=1;
  for(i=0;i<100;i=i+1)begin @(negedge clk);pcm=i[0]?-16'sd200:16'sd300;end
  pcm_valid=0;clocks(5);if(dut.audio_level!=500)$fatal(1,"relative PCM source");
  $display("PANEL_CASE builtin_sources_read_only PASS");
  // New display words are checked at actual segment pins, including decimal
  // position. Expected patterns are common-cathode A..G lit masks inverted.
  reset=1;clocks(5);reset=0;switches=16'h0300;music_enabled=1;music_state=0;music_job_active=0;pcm_valid=0;
  accepted(8'hfe,16'hffff,0,0);accepted(3,16'hffff,12340,1);clocks(80);capture_digits;
  if(seen_segments[7][6:0]!=7'h0e || seen_segments[6][6:0]!=7'h79 || seen_segments[5][6:0]!=7'h2b || seen_segments[4][6:0]!=7'h21)$fatal(1,"FInd glyph");
  if(seen_segments[2][6:0]!=7'h79 || seen_segments[1][6:0]!=7'h24 || seen_segments[0][6:0]!=7'h30 || seen_segments[1][7]!=0)$fatal(1,"elapsed12.3s decimal");
  music_state=3;accepted(2,16'hffff,0,2);clocks(80);capture_digits;
  if(seen_segments[7][6:0]!=7'h12 || seen_segments[6][6:0]!=7'h06 || seen_segments[5][6:0]!=7'h2b || seen_segments[4][6:0]!=7'h21)$fatal(1,"SEnd glyph");
  for(i=0;i<4;i=i+1)if(seen_segments[i][6:0]!=7'h3f)$fatal(1,"unknown transfer fabricated numeric progress");
  accepted(2,375,0,3);clocks(40);
  for(i=0;i<16;i=i+1)if((i<6 && dut.levels[i]==0)||(i>=6 && dut.levels[i]!=0))$fatal(1,"transfer truebarextrahead");
  music_state=0;accepted(4,1000,0,4);clocks(80);capture_digits;
  if(seen_segments[7][6:0]!=7'h0c || seen_segments[6][6:0]!=7'h08 || seen_segments[5][6:0]!=7'h12 || seen_segments[4][6:0]!=7'h12)$fatal(1,"PASS glyph");
  $display("PANEL_CASE physical_glyphs_and_decimal PASS");
  music_state=1;music_progress=8;music_count=80000;clocks(80);
  for(i=0;i<16;i=i+1)if((i<8 && dut.levels[i]==0)||(i>=8 && dut.levels[i]!=0))$fatal(1,"record truebarextrahead");
  red_on=0;green_on=0;blue_on=0;
  for(i=0;i<256;i=i+1)begin @(negedge clk);red_on=red_on+rgb0[2];green_on=green_on+rgb0[1];blue_on=blue_on+rgb0[0];end
  if(red_on!=256 || green_on!=70 || blue_on!=0)$fatal(1,"orange RGB PWM endpoints/mix %d/%d/%d",red_on,green_on,blue_on);
  $display("PANEL_CASE true_progress_bar_and_orange_rgb PASS");
  music_state=0;music_enabled=1;music_job_active=0;accepted(9,16'hffff,0,5);clocks(5);
  if(dut.display_phase!=9 || dut.result_ms<590 || dut.result_ms>600)$fatal(1,"FAV600ms start");
  for(i=0;i<16;i=i+1)if((i>=6 && i<=9 && dut.levels[i]==0)||((i<6 || i>9) && dut.levels[i]!=0))$fatal(1,"FAV central four");
  clocks(650);if(dut.display_phase==9 || dut.result_ms!=0)$fatal(1,"FAV did not expire");
  accepted(9,16'hffff,0,6);clocks(5);if(dut.display_phase!=9 || dut.result_ms<590)$fatal(1,"newSEQ sameFAV failed to retrigger");
  clocks(100);before_result=dut.result_ms;accepted(9,16'hffff,0,6);
  if(dut.result_ms>=before_result)$fatal(1,"duplicateSEQ FAV restarted");
  $display("PANEL_CASE favourite_600ms_retrigger_only_new_sequence PASS");
  accepted(5,16'hffff,0,7);clocks(100);
  if(dut.levels[0]==0 || dut.levels[15]==0 || dut.levels[7]!=0 || dut.levels[8]!=0)$fatal(1,"MISS first wave startsoutside");
  clocks(1300);if(dut.levels[7]==0 || dut.levels[8]==0 || dut.levels[0]!=0)$fatal(1,"MISS firstwave reachescenter");
  clocks(200);if(dut.levels[0]==0 || dut.levels[15]==0 || dut.levels[7]!=0)$fatal(1,"MISS secondwave startsoutside");
  clocks(1300);if(dut.levels[7]==0 || dut.levels[8]==0 || dut.levels[0]!=0)$fatal(1,"MISS secondwave reachescenter");
  $display("PANEL_CASE miss_two_inward_waves PASS");
  accepted(1,16'hffff,0,8);while(dut.waiting_ms>10)clocks(1);
  accepted(1,16'hffff,0,8);clocks(8);capture_digits;
  if(seen_segments[5][6:0]!=7'h07 || seen_segments[4][6:0]!=7'h08 || seen_segments[3][6:0]!=7'h0c || seen_segments[2][6:0]!=7'h30)$fatal(1,"tAP3 glyph");
  clocks(130);capture_digits;
  if(seen_segments[6][6:0]!=7'h2f || seen_segments[5][6:0]!=7'h06 || seen_segments[4][6:0]!=7'h08 || seen_segments[3][6:0]!=7'h21 || seen_segments[2][6:0]!=7'h11)$fatal(1,"rEAdy glyph");
  accepted(1,16'hffff,0,8);bright=0;
  for(i=0;i<2000;i=i+1)begin @(negedge clk);if(dut.levels[7]==255)bright=bright+1;end
  if(bright!=360)$fatal(1,"ready triplepulse2s must contain360ms fullbrightness %d",bright);
  $display("PANEL_CASE ready_triplepulse_and_words PASS");
  music_wake=0;accepted(1,16'hffff,0,8);clocks(8);capture_digits;
  if(seen_segments[6][6:0]!=7'h2f || seen_segments[5][6:0]!=7'h06 || seen_segments[4][6:0]!=7'h08 || seen_segments[3][6:0]!=7'h21 || seen_segments[2][6:0]!=7'h11)$fatal(1,"manual ready falsely advertises tAP");
  for(i=0;i<2000;i=i+1)begin
   @(negedge clk);
   if(dut.levels[7]!=96 || dut.levels[8]!=96 || dut.levels[0]!=0)$fatal(1,"wake0 manual-ready must staysteady, noautomatictriplepulse");
  end
  music_wake=1;
  $display("PANEL_CASE manual_ready_never_advertises_wake PASS");
  music_enabled=0;switches=16'h0300;reset=1;clocks(5);reset=0;
  clocks(300);narrow=0;for(i=0;i<16;i=i+1)begin
   if(dut.levels[i]!=dut.levels[15-i])$fatal(1,"calm symmetry");if(dut.levels[i]!=0)narrow=narrow+1;
  end
  clocks(700);wide=0;for(i=0;i<16;i=i+1)if(dut.levels[i]!=0)wide=wide+1;
  if(wide<=narrow || dut.levels[7]==0 || dut.levels[8]==0)$fatal(1,"calm notcenterout");
  clocks(1700);narrow=0;for(i=0;i<16;i=i+1)if(dut.levels[i]!=0)narrow=narrow+1;
  if(narrow>=wide)$fatal(1,"calm failedcontract");
  for(integer speed=0;speed<4;speed=speed+1)begin
   switches[7:6]=speed;reset=1;clocks(5);reset=0;period=0;prior_phase=0;
   begin:waitcycle
    while(period<7000)begin
     clocks(1);period=period+1;
     if(prior_phase==511 && dut.animation_phase==0)disable waitcycle;
     prior_phase=dut.animation_phase;
    end
   end
   case(speed)0:n=3000;1:n=6000;2:n=2000;3:n=1500;endcase
   if(period<n-2 || period>n+2)$fatal(1,"speed cycle %d got%d expected%d",speed,period,n);
  end
  $display("PANEL_CASE calm_center_out_and_actual_speed PASS");
  switches=16'h0300;music_enabled=1;music_state=0;music_job_active=1;music_game=1;
  accepted(8'hfe,16'hffff,0,0);clocks(80);capture_digits;
  if(dut.display_phase!=7 || !dut.number_unknown)$fatal(1,"SYNC didnotprove machine resultready or knownholdtime");
  if(seen_segments[7][6:0]!=7'h09 || seen_segments[6][6:0]!=7'h23 || seen_segments[5][6:0]!=7'h47 || seen_segments[4][6:0]!=7'h21)$fatal(1,"unknown activejob HoLd glyph");
  for(i=0;i<4;i=i+1)if(seen_segments[i][6:0]!=7'h3f)$fatal(1,"unknown hold fabricated time");
  music_game=0;clocks(20);if(dut.display_phase!=7 || !dut.number_unknown)$fatal(1,"ordinary activejob invented PCstage");
  music_game=1;accepted(8,16'hffff,0,1);clocks(80);capture_digits;
  if(dut.display_phase!=8 || seen_segments[6][6:0]!=7'h2f || seen_segments[5][6:0]!=7'h06)$fatal(1,"explicitGAME_READY notneutral rEAdy");
  accepted(7,16'hffff,5300,2);clocks(80);
  if(dut.display_phase!=7 || dut.number_unknown || dut.number_binary!=5300)$fatal(1,"actualPC HOLDvalue lost");
  $display("PANEL_CASE no_pc_stage_means_unknown_hold PASS");
  $display("PASS BOARD_PANEL");$finish;
 end
 initial begin #1000000;$fatal(1,"testbench watchdog");end
endmodule
