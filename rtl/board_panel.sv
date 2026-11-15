`timescale 1ns/1ps
// Independent human display. All measurement taps are registered and read-only.
module board_panel #(parameter integer CLOCK_HZ=100000000)(
 input wire clk,reset,input wire [63:0] ticks,
 input wire [15:0] switches,switches_raw,legacy_leds,
 input wire pcm_valid,input wire signed [15:0] pcm,temperature_raw,input wire temperature_valid,
 input wire music_enabled,input wire [1:0] music_state,
 input wire [31:0] music_target,music_count,music_rate,music_record_id,
 input wire [4:0] music_progress,input wire music_game,music_wake,music_job_active,
 input wire [15:0] music_max_ms,
 input wire command_start,input wire [15:0] command_length,
 input wire [127:0] command_head,input wire [31:0] command_event,
 output reg done=0,output reg [7:0] reply_data=0,output wire quiet,
 output reg [15:0] led=0,output reg [2:0] rgb0=0,rgb1=0,
 output reg [7:0] segments=8'hff,anodes=8'hff
);
 localparam integer MS_CYCLES=(CLOCK_HZ/1000<1)?1:CLOCK_HZ/1000;
 localparam integer PWM_CYCLES=(CLOCK_HZ/1024000<1)?1:CLOCK_HZ/1024000;
 localparam integer SCAN_CYCLES=(CLOCK_HZ/8000<2)?2:CLOCK_HZ/8000;
 localparam integer BLANK_CYCLES=(CLOCK_HZ/2000000<1)?1:CLOCK_HZ/2000000;
 localparam NORMAL=0,READY=1,TRANSFER=2,MATCH=3,PASS=4,MISS=5,ERROR=6,HOLD=7,GAME_READY=8,FAV=9,RECORD=10;
 reg [31:0] ms_div=0,pwm_div=0,scan_counter=0;
 wire ms_enable=ms_div==MS_CYCLES-1;
 reg [31:0] uptime_ms=0;
 reg [7:0] pwm_counter=0;
 reg [2:0] scan_digit=0;
 reg [15:0] raw_previous=0;reg [10:0] quiet_ms=0;
 assign quiet=(quiet_ms!=0)||(switches_raw!=raw_previous);
 always @(posedge clk)begin
  raw_previous<=switches_raw;
  if(reset)begin ms_div<=0;uptime_ms<=0;quiet_ms<=0;raw_previous<=switches_raw;end
  else begin
   if(ms_enable)begin ms_div<=0;uptime_ms<=uptime_ms+1'b1;if(quiet_ms!=0)quiet_ms<=quiet_ms-1'b1;end
   else ms_div<=ms_div+1'b1;
   if(switches_raw!=raw_previous)quiet_ms<={1'b0,music_max_ms[9:0]}+11'd200;
  end
 end
 // PANEL v1 is a set-state transaction, never a business command.
 reg session_valid=0;reg [31:0] session_id=0,last_seq=0;
 reg [7:0] pc_phase=NORMAL;reg [15:0] pc_progress=16'hffff;
 reg [31:0] pc_value=0,pc_record=0;
 reg [11:0] watchdog_ms=0,result_ms=0;
 wire pc_fresh=session_valid && watchdog_ms!=0;
 wire [7:0] incoming_phase=command_head[15:8];
 wire [15:0] incoming_progress=command_head[31:16];
 wire [31:0] incoming_value=command_head[63:32],incoming_session=command_head[95:64],incoming_seq=command_head[127:96];
 always @(posedge clk)begin
  done<=0;
  if(reset)begin session_valid<=0;watchdog_ms<=0;result_ms<=0;pc_phase<=NORMAL;last_seq<=0;end
  else begin
   if(ms_enable)begin
    if(watchdog_ms!=0)watchdog_ms<=watchdog_ms-1'b1;
    if(result_ms!=0)result_ms<=result_ms-1'b1;
   end
   if(command_start)begin
    done<=1;reply_data<=0;
    if(command_length!=16 || command_head[7:0]!=1 ||
       !(incoming_phase<=FAV || incoming_phase==8'hfe) ||
       !(incoming_progress<=1000 || incoming_progress==16'hffff))reply_data<=7;
    else if(incoming_phase==8'hfe)begin
     if(!pc_fresh)begin
      session_valid<=1;session_id<=incoming_session;last_seq<=incoming_seq;watchdog_ms<=3000;
      pc_phase<=NORMAL;pc_progress<=16'hffff;pc_value<=0;pc_record<=music_record_id;result_ms<=0;
     end else if(incoming_session!=session_id || incoming_seq<last_seq)reply_data<=1;
     else begin last_seq<=incoming_seq;watchdog_ms<=3000;end
    end else if(!pc_fresh || incoming_session!=session_id || incoming_seq<last_seq || command_event!=music_record_id)reply_data<=1;
    else begin
     watchdog_ms<=3000;
     if(incoming_seq!=last_seq)begin
      last_seq<=incoming_seq;pc_phase<=incoming_phase;pc_progress<=incoming_progress;pc_value<=incoming_value;pc_record<=command_event;
      if((incoming_phase==PASS || incoming_phase==MISS || incoming_phase==ERROR || incoming_phase==FAV) &&
         (incoming_phase==FAV || pc_phase!=incoming_phase || pc_record!=command_event))result_ms<=incoming_phase==FAV ? 600 : 3000;
     end
    end
   end
  end
 end
 // Stage every local tap before any effect calculations (no new capture fanout).
 reg en_r=0,game_r=0,wake_r=0,job_r=0,temp_valid_r=0;
 reg [1:0] state_r=0;reg [4:0] progress_r=0;
 reg [31:0] target_r=0,count_r=0,rate_r=16000,record_r=0;
 reg signed [15:0] temp_r=0;
 always @(posedge clk)begin
  en_r<=music_enabled;game_r<=music_game;wake_r<=music_wake;job_r<=music_job_active;
  state_r<=music_state;progress_r<=music_progress;target_r<=music_target;count_r<=music_count;
  rate_r<=music_rate;record_r<=music_record_id;temp_r<=temperature_raw;temp_valid_r<=temperature_valid;
 end
 // Real PCM peak-to-peak envelope; display only, uncalibrated relative counts.
 reg signed [15:0] audio_min=16'sh7fff,audio_max=-16'sh8000;reg audio_seen=0;
 reg [7:0] audio_window=0;reg [16:0] audio_level=0;
 reg signed [19:0] temp_scaled=0;
 always @(posedge clk)begin
  if(reset)begin audio_seen<=0;audio_level<=0;audio_window<=0;end
  else begin
   if(pcm_valid)begin
    audio_seen<=1;if(pcm<audio_min)audio_min<=pcm;if(pcm>audio_max)audio_max<=pcm;
   end
   if(ms_enable)begin
    temp_scaled<=($signed(temp_r)<<<3)+($signed(temp_r)<<<1);
    if(audio_window==19)begin
     audio_window<=0;audio_level<=audio_seen ? $signed({audio_max[15],audio_max})-$signed({audio_min[15],audio_min}) : 0;
     audio_min<=16'sh7fff;audio_max<=-16'sh8000;audio_seen<=0;
    end else audio_window<=audio_window+1'b1;
   end
  end
 end
 // Small subtractive quotient engine, bounded at <=200 iterations for real jobs.
 // No combinational variable divider or DSP on the sample-count path.
 reg [31:0] remaining_work=0;reg [15:0] remaining_tenths=0,remaining_q=0;
 reg [10:0] sample_step=1600;reg remaining_busy=0;
 always @(posedge clk)begin
  if(reset)begin remaining_busy<=0;remaining_tenths<=0;end
  else if(ms_enable && !remaining_busy)begin
   remaining_work<=target_r>count_r ? target_r-count_r : 0;
   sample_step<=rate_r==8000 ? 800 : 1600;remaining_q<=0;remaining_busy<=1;
  end else if(remaining_busy)begin
   if(remaining_work>=sample_step)begin remaining_work<=remaining_work-sample_step;remaining_q<=remaining_q+1'b1;end
   else begin remaining_tenths<=remaining_q+(remaining_work!=0);remaining_busy<=0;end
  end
 end
 reg [8:0] animation_phase=0;reg [12:0] animation_fraction=0;
 reg [10:0] waiting_ms=0;reg [12:0] cycle_ms=0;reg [1:0] auto_page=0;
 wire [10:0] animation_step=switches[7:6]==1 ? 256 : switches[7:6]==2 ? 768 : switches[7:6]==3 ? 1024 : 512;
 wire [13:0] animation_sum=animation_fraction+animation_step;
 wire [7:0] breath=animation_phase[8] ? ~animation_phase[7:0] : animation_phase[7:0];
 wire ready_pulse=(waiting_ms<120)||(waiting_ms>=260 && waiting_ms<380)||(waiting_ms>=520 && waiting_ms<640);
 always @(posedge clk)begin
  if(reset)begin animation_phase<=0;animation_fraction<=0;waiting_ms<=0;cycle_ms<=0;auto_page<=0;end
  else if(ms_enable)begin
   if(animation_sum>=3000)begin animation_fraction<=animation_sum-3000;animation_phase<=animation_phase+1'b1;end
   else animation_fraction<=animation_sum;
   if(waiting_ms==1999)waiting_ms<=0;else waiting_ms<=waiting_ms+1'b1;
   if(cycle_ms==4999)begin cycle_ms<=0;auto_page<=auto_page+1'b1;end else cycle_ms<=cycle_ms+1'b1;
  end
 end
 reg [7:0] display_phase=NORMAL;
 wire valid_pc=pc_fresh && pc_record==record_r;
 always @(posedge clk)if(reset)display_phase<=NORMAL;else if(ms_enable)begin
  if(state_r==1 || state_r==2)display_phase<=RECORD;
  else if(state_r==3)display_phase<=TRANSFER;
  else if(valid_pc && pc_phase>=PASS && pc_phase<=ERROR && result_ms!=0 && (!game_r || !job_r))display_phase<=pc_phase;
  else if(valid_pc && pc_phase==FAV && result_ms!=0 && (!game_r || !job_r))display_phase<=FAV;
  else if(valid_pc && (pc_phase==MATCH || pc_phase==HOLD || pc_phase==GAME_READY))display_phase<=pc_phase;
  else if(en_r && !job_r)display_phase<=READY;
  else if(en_r && job_r)display_phase<=HOLD; // exported but no fresh PC truth
  else display_phase<=NORMAL;
 end
 function automatic [7:0] scale(input [7:0] value,input [1:0] brightness);
  begin case(brightness)0:scale=value>>2;1:scale=value>>1;2:scale=(value>>1)+(value>>2);default:scale=value;endcase end
 endfunction
 // Event radii are separately registered so waveform PWM never deepens a
 // measurement path. PASS repeats center-out for3s; MISS makes two1.5s sweeps.
 wire [11:0] event_age=12'd3000-result_ms;
 wire [10:0] miss_age=event_age>=1500 ? event_age-1500 : event_age;
 reg [2:0] pass_radius=0,miss_radius=7;
 always @(posedge clk)if(ms_enable)begin
  pass_radius<=event_age[9:7];
  if(miss_age<188)miss_radius<=7;else if(miss_age<375)miss_radius<=6;
  else if(miss_age<563)miss_radius<=5;else if(miss_age<750)miss_radius<=4;
  else if(miss_age<938)miss_radius<=3;else if(miss_age<1125)miss_radius<=2;
  else if(miss_age<1313)miss_radius<=1;else miss_radius<=0;
 end
 reg [7:0] levels[0:15],raw_levels[0:15];
 reg [7:0] rgb_level=0,rgb_levels[0:5],raw_rgb_levels[0:5];reg [2:0] color0=0,color1=0;
 reg render_pending=0,render_mirror=0;reg [1:0] render_brightness=0;
 integer k;reg [7:0] intensity,magnitude;reg [15:0] pattern;reg [3:0] head_position,boundary;
 reg [2:0] center_distance;reg known_transfer;
 always @(posedge clk)begin
  if(reset)begin
   for(k=0;k<16;k=k+1)raw_levels[k]<=0;
   for(k=0;k<6;k=k+1)raw_rgb_levels[k]<=0;
   rgb_level<=0;color0<=0;color1<=0;render_pending<=0;render_mirror<=0;render_brightness<=0;
  end else begin
   render_pending<=ms_enable;
   if(ms_enable)begin
    render_brightness<=switches[9:8];render_mirror<=switches[3];
   intensity=255;pattern=0;boundary=0;head_position=animation_phase[8:5];
   known_transfer=valid_pc && pc_phase==TRANSFER && pc_progress!=16'hffff;
   color0<=3'b011;color1<=pc_fresh ? 3'b010 : 3'b110;
   case(display_phase)
    RECORD:begin pattern=16'hffff>>(16-progress_r);boundary=progress_r!=0?progress_r-1'b1:0;color0<=3'b110;color1<=3'b110;end
    TRANSFER:begin
     if(known_transfer)begin
      for(k=0;k<16;k=k+1)begin
       pattern[k]=(pc_progress>=(((k+1)*1000+15)/16));
       if(pc_progress>=(((k+1)*1000+15)/16))boundary=k;
      end
     end else pattern=16'h0001<<head_position;
     color0<=3'b001;color1<=3'b001;
    end
    MATCH,GAME_READY:begin pattern=(16'h0001<<head_position)|(16'h0001<<(head_position^4'd8));color0<=3'b001;color1<=3'b101;end
    PASS:begin color0<=3'b010;color1<=3'b010;end
    MISS:begin color0<=3'b110;color1<=3'b110;end
    HOLD:begin pattern=16'h8001;color0<=3'b110;color1<=3'b110;end
    ERROR:begin pattern=waiting_ms[8]?16'haaaa:16'h5555;color0<=3'b100;color1<=3'b100;end
    FAV:begin pattern=16'h03c0;color0<=3'b010;color1<=3'b010;end
    READY:begin pattern=16'h03c0;intensity=wake_r ? (ready_pulse?255:16) : 96;color0<=3'b001;color1<=3'b101;end
    default:begin
     intensity=breath;
     if(switches[11:10]==1)begin pattern=16'h0001<<head_position;intensity=255;end
     else if(switches[11:10]==2)pattern=(16'h0180<<animation_phase[8:6])|(16'h0180>>animation_phase[8:6]);
    end
   endcase
   if(switches[1] && display_phase==NORMAL && audio_level[16:8]>intensity)intensity=audio_level[16]?255:audio_level[15:8];
   for(k=0;k<16;k=k+1)begin
    center_distance=k<8?7-k:k-8;
    magnitude=pattern[k]?intensity:0;
    if(display_phase==NORMAL && switches[11:10]==0)magnitude=center_distance<=breath[7:5]?intensity:0;
    if(display_phase==PASS)magnitude=center_distance<=pass_radius?255:0;
    if(display_phase==MISS)magnitude=center_distance==miss_radius?255:0;
    if(((display_phase==RECORD && progress_r!=0) || (display_phase==TRANSFER && known_transfer && pc_progress>=63)) && k==boundary)magnitude=96+(breath>>1);
    if(switches[11:10]==3)magnitude=legacy_leds[k]?255:0;
    raw_levels[k]<=magnitude;
   end
   rgb_level<=scale(intensity,switches[9:8]);
   // Different channel weights produce teal/orange, instead of yellow/cyan
   // bit masks. Separate registered levels retain one common4kHz PWM clock.
   if(display_phase==RECORD)begin
    raw_rgb_levels[0]<=255;raw_rgb_levels[1]<=70;raw_rgb_levels[2]<=0;
    raw_rgb_levels[3]<=255;raw_rgb_levels[4]<=70;raw_rgb_levels[5]<=0;
   end else begin
    raw_rgb_levels[0]<=(display_phase==ERROR || display_phase==MISS || display_phase==HOLD)?intensity:0;
    raw_rgb_levels[1]<=(display_phase==NORMAL || display_phase==PASS || display_phase==FAV)?intensity:(display_phase==MISS || display_phase==HOLD)?(intensity>>1):0;
    raw_rgb_levels[2]<=(display_phase==READY || display_phase==TRANSFER || display_phase==MATCH || display_phase==GAME_READY)?intensity:(display_phase==NORMAL)?((intensity>>1)+(intensity>>2)):0;
    raw_rgb_levels[3]<=(display_phase==READY || display_phase==MATCH || display_phase==GAME_READY)?(intensity>>1):(display_phase==ERROR || display_phase==MISS || display_phase==HOLD || (!pc_fresh && display_phase==NORMAL))?intensity:0;
    raw_rgb_levels[4]<=(display_phase==PASS || display_phase==FAV || (pc_fresh && display_phase==NORMAL))?intensity:(display_phase==MISS || display_phase==HOLD || (!pc_fresh && display_phase==NORMAL))?(intensity>>1):0;
    raw_rgb_levels[5]<=(display_phase==READY || display_phase==TRANSFER || display_phase==MATCH || display_phase==GAME_READY)?intensity:0;
   end
   end
  end
 end
 // Register the expensive effect mux before mirror/brightness arithmetic.
 // This adds one100MHzclock(10ns), without changing any capture/algorithm path.
 integer scale_index;
 always @(posedge clk)begin
  if(reset)begin
   for(scale_index=0;scale_index<16;scale_index=scale_index+1)levels[scale_index]<=0;
   for(scale_index=0;scale_index<6;scale_index=scale_index+1)rgb_levels[scale_index]<=0;
  end else if(render_pending)begin
   for(scale_index=0;scale_index<16;scale_index=scale_index+1)
    levels[scale_index]<=scale(render_mirror?raw_levels[15-scale_index]:raw_levels[scale_index],render_brightness);
   for(scale_index=0;scale_index<6;scale_index=scale_index+1)
    rgb_levels[scale_index]<=scale(raw_rgb_levels[scale_index],render_brightness);
  end
 end
 // Serial binary-to-BCD, ten parallel nibble adders and one shift per clock.
 reg [31:0] number_binary=0;reg [71:0] bcd_work=0,bcd_adjust;
 reg [39:0] number_bcd=0;reg [5:0] bcd_count=0;reg bcd_busy=0;
 reg [7:0] number_kind=0;reg number_negative=0,number_unknown=0;
 wire [1:0] page=switches[5:4]+(switches[2]?auto_page:2'd0);
 integer j;
 always @*begin
  bcd_adjust=bcd_work;
  for(integer n=0;n<10;n=n+1)if(bcd_work[32+n*4+:4]>=5)bcd_adjust[32+n*4+:4]=bcd_work[32+n*4+:4]+3;
 end
 always @(posedge clk)begin
  if(reset)begin bcd_busy<=0;number_bcd<=0;number_binary<=0;number_kind<=0;number_unknown<=0;number_negative<=0;end
  else begin
   if(ms_enable)begin
    number_kind<=display_phase;number_negative<=0;number_unknown<=0;
    case(display_phase)
     RECORD:number_binary<=remaining_tenths;
     TRANSFER:begin number_binary<=pc_progress;number_unknown<=!valid_pc || pc_phase!=TRANSFER || pc_progress==16'hffff;end
     MATCH:number_binary<=pc_value;
     HOLD:begin number_binary<=pc_value;number_unknown<=!valid_pc || pc_phase!=HOLD;end
     ERROR:number_binary<=pc_value;
     NORMAL:case(page)
      1:begin number_kind<=11;number_binary<=temp_scaled[19] ? -($signed(temp_scaled)>>>7) : ($signed(temp_scaled)>>>7);number_negative<=temp_scaled[19];number_unknown<=!temp_valid_r;end
      2:begin number_kind<=12;number_binary<=audio_level;end
      3:begin number_kind<=13;number_binary<=uptime_ms;end
      default:number_binary<=record_r;
     endcase
     default:number_binary<=record_r;
    endcase
    if(!bcd_busy)begin bcd_work<={40'b0,number_binary};bcd_count<=0;bcd_busy<=1;end
   end
   if(bcd_busy)begin
    bcd_work<=bcd_adjust<<1;
    if(bcd_count==31)begin number_bcd<=(bcd_adjust<<1)>>32;bcd_busy<=0;end else bcd_count<=bcd_count+1'b1;
   end
  end
 end
 // Codes 0..9 decimal; 10 blank, 11 dash; named letters below.
 function automatic [6:0] font(input [4:0] code);
  reg [6:0] lit;
  begin case(code)
   0:lit=7'h3f;1:lit=7'h06;2:lit=7'h5b;3:lit=7'h4f;4:lit=7'h66;5:lit=7'h6d;6:lit=7'h7d;7:lit=7'h07;8:lit=7'h7f;9:lit=7'h6f;
   11:lit=7'h40;12:lit=7'h77;13:lit=7'h73;14:lit=7'h50;15:lit=7'h79;16:lit=7'h06;17:lit=7'h5e;18:lit=7'h78;
   19:lit=7'h3f;20:lit=7'h76;21:lit=7'h54;22:lit=7'h5c;23:lit=7'h76;24:lit=7'h3d;25:lit=7'h71;26:lit=7'h39;27:lit=7'h1c;28:lit=7'h6d;29:lit=7'h38;30:lit=7'h6e;31:lit=7'h3e;
   default:lit=0;
  endcase font=~lit;end
 endfunction
 reg [39:0] next_digits,frame_digits=0;reg [7:0] next_dp,frame_dp=0;
 reg [3:0] decimal_offset;integer numeric_digits;reg leading;reg [4:0] digit_value;
 always @*begin
  for(integer d=0;d<8;d=d+1)next_digits[d*5+:5]=10;
  next_dp=0;decimal_offset=0;numeric_digits=6;leading=1;digit_value=0;
  if(number_kind==MATCH || number_kind==HOLD)decimal_offset=2;
  else if(number_kind==13)decimal_offset=3;
  case(number_kind)
   RECORD,ERROR:numeric_digits=5;
   TRANSFER,MATCH,PASS,HOLD:numeric_digits=4;
   READY,MISS,GAME_READY,FAV:numeric_digits=0;
   default:numeric_digits=6;
  endcase
  for(integer d=5;d>=0;d=d-1)if(d<numeric_digits)begin
   digit_value={1'b0,number_bcd[(d+decimal_offset)*4+:4]};
   if(number_unknown)next_digits[d*5+:5]=11;
   else if(leading && digit_value==0 && d>1)next_digits[d*5+:5]=10;
   else begin next_digits[d*5+:5]=digit_value;leading=0;end
  end
  if(number_negative)next_digits[25+:5]=11;
  case(number_kind)
   READY,GAME_READY:begin
    if(number_kind==READY && wake_r && ready_pulse)begin
     next_digits[25+:5]=18;next_digits[20+:5]=12;next_digits[15+:5]=13;next_digits[10+:5]=3;
    end else begin next_digits[30+:5]=14;next_digits[25+:5]=15;next_digits[20+:5]=12;next_digits[15+:5]=17;next_digits[10+:5]=30;end
   end
   RECORD:begin next_digits[35+:5]=14;next_digits[30+:5]=15;next_digits[25+:5]=26;next_dp[1]=1;end
   TRANSFER:begin next_digits[35+:5]=28;next_digits[30+:5]=15;next_digits[25+:5]=21;next_digits[20+:5]=17;next_dp[1]=!number_unknown;end
   MATCH:begin next_digits[35+:5]=25;next_digits[30+:5]=16;next_digits[25+:5]=21;next_digits[20+:5]=17;next_dp[1]=1;end
   PASS:begin next_digits[35+:5]=13;next_digits[30+:5]=12;next_digits[25+:5]=28;next_digits[20+:5]=28;end
   MISS:begin next_digits[30+:5]=21;next_digits[25+:5]=22;next_digits[20+:5]=28;next_digits[15+:5]=22;next_digits[10+:5]=21;next_digits[5+:5]=24;end
   ERROR:begin next_digits[35+:5]=15;next_digits[30+:5]=14;next_digits[25+:5]=14;end
   HOLD:begin next_digits[35+:5]=23;next_digits[30+:5]=22;next_digits[25+:5]=29;next_digits[20+:5]=17;next_dp[1]=1;end
   FAV:begin next_digits[25+:5]=25;next_digits[20+:5]=12;next_digits[15+:5]=31;end
   11:begin next_digits[35+:5]=18;next_digits[30+:5]=26;next_dp[1]=!number_unknown;end
   12:begin next_digits[35+:5]=12;next_digits[30+:5]=27;end
   13:begin next_digits[35+:5]=27;next_digits[30+:5]=13;end
   default:begin next_digits[35+:5]=16;next_digits[30+:5]=17;end
  endcase
  // Communication loss invalidates PC fields, while real recording counters
  // and temperature/audio/uptime pages stay available independently.
  if(!pc_fresh && number_kind<=10 && number_kind!=RECORD)begin
   for(integer d=0;d<8;d=d+1)next_digits[d*5+:5]=10;
   next_dp=0;next_digits[30+:5]=13;next_digits[25+:5]=26;next_digits[20+:5]=19;
   next_digits[15+:5]=25;next_digits[10+:5]=25;
  end
 end
 integer q;
 always @(posedge clk)begin
  if(reset)begin pwm_div<=0;pwm_counter<=0;scan_counter<=0;scan_digit<=0;led<=0;rgb0<=0;rgb1<=0;segments<=8'hff;anodes<=8'hff;end
  else begin
   if(pwm_div==PWM_CYCLES-1)begin pwm_div<=0;pwm_counter<=pwm_counter+1'b1;end else pwm_div<=pwm_div+1'b1;
   if(scan_counter==SCAN_CYCLES-1)begin scan_counter<=0;scan_digit<=scan_digit+1'b1;end else scan_counter<=scan_counter+1'b1;
   if(scan_counter==0)begin
    if(scan_digit==0)begin frame_digits<=next_digits;frame_dp<=next_dp;end
    segments<=scan_digit==0 ? {~next_dp[0],font(next_digits[0+:5])} : {~frame_dp[scan_digit],font(frame_digits[scan_digit*5+:5])};
   end
   anodes<=8'hff;
   if(!switches[0] && scan_counter>=BLANK_CYCLES && (pwm_counter<scale(8'd255,switches[9:8]) || switches[9:8]==3))anodes<=~(8'b1<<scan_digit);
   for(q=0;q<16;q=q+1)led[q]<=!switches[0] && (pwm_counter<levels[q] || levels[q]==255);
   rgb0[2]<=!switches[0] && (pwm_counter<rgb_levels[0] || rgb_levels[0]==255);
   rgb0[1]<=!switches[0] && (pwm_counter<rgb_levels[1] || rgb_levels[1]==255);
   rgb0[0]<=!switches[0] && (pwm_counter<rgb_levels[2] || rgb_levels[2]==255);
   rgb1[2]<=!switches[0] && (pwm_counter<rgb_levels[3] || rgb_levels[3]==255);
   rgb1[1]<=!switches[0] && (pwm_counter<rgb_levels[4] || rgb_levels[4]==255);
   rgb1[0]<=!switches[0] && (pwm_counter<rgb_levels[5] || rgb_levels[5]==255);
   if(switches[0])segments<=8'hff;
  end
 end
endmodule
