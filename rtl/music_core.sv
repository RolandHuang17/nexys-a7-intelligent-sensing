`timescale 1ns/1ps
// Independent, frozen PCM recording. No reconstruction from preview/event buffers.
module music_core #(parameter integer MAX_SAMPLES=160000,CLOCK_HZ=100000000)(
 input wire clk,reset,input wire [63:0] ticks,pcm_index,
 input wire pcm_valid,input wire signed [15:0] pcm,
 input wire xyz_valid,input wire [63:0] xyz_tick,input wire signed [15:0] x,y,z,
 input wire center,
 input wire command_start,input wire [15:0] command_length,command_seq,
 input wire [127:0] command_head,input wire [31:0] command_event,
 input wire [8:0] reply_address,output wire [7:0] reply_data,
 output reg done=0,output reg [15:0] reply_length=128,
 output reg enabled=0,output wire [15:0] leds,
 input wire panel_quiet,
 output wire [1:0] panel_capture_state,
 output wire [31:0] panel_target,panel_count,panel_rate,panel_record_id,
 output wire [4:0] panel_progress,
 output wire panel_game,panel_wake,panel_job_active,
 output wire [15:0] panel_max_ms
);
 import recorder_pkg::*;
 localparam AW=$clog2(MAX_SAMPLES),EMPTY=0,RECORD=1,DRAIN=2,FROZEN=3;
 reg [1:0] capture_state=EMPTY;
 (* ram_style="block" *) reg [15:0] memory[0:MAX_SAMPLES-1];
 reg [AW-1:0] read_address=0;
 reg [15:0] memory_q0=0,memory_q1=0,memory_q2=0;
 always @(posedge clk)begin memory_q0<=memory[read_address];memory_q1<=memory_q0;memory_q2<=memory_q1;end
 reg [31:0] count=0,target=MAX_SAMPLES,record_id=0,crc=32'hffffffff,full_crc=0,prefix_crc=0,overflow=0;
 reg [63:0] first_tick=0,last_tick=0,first_index=0,start_tick=0;
 reg [1:0] crc_phase=0;reg [15:0] crc_sample=0;reg [31:0] crc_number=0;
 wire [31:0] next_crc=crc32_byte(crc,crc_phase==1 ? crc_sample[7:0] : crc_sample[15:8]);
 reg wake=0,game=0,half_rate=0,job_active=0;reg [15:0] threshold_high=80,threshold_low=32,min_ms=150,max_ms=600;
 wire filtered_valid;wire signed [15:0] filtered_pcm;wire [63:0] filtered_index;
 music_decimator decimator(clk,reset,half_rate,pcm_valid,pcm,pcm_index,filtered_valid,filtered_pcm,filtered_index);
 wire stored_valid=half_rate ? filtered_valid : pcm_valid;
 wire signed [15:0] stored_pcm=half_rate ? filtered_pcm : pcm;
 wire [63:0] stored_index=half_rate ? filtered_index : pcm_index;
 wire [31:0] sample_rate=half_rate ? 8000 : 16000;
 reg [31:0] tap_seq=0,double_seq=0,center_seq=0,last_delta=0;
 reg [63:0] tap_tick=0,double_tick=0,center_tick=0,human_tick=0,first_tap=0;
 reg signed [15:0] px=0,py=0,pz=0;reg xyz_seen=0,tap_rearmed=1,pair_pending=0,previous_center=0;
 reg tap_pulse=0,pair_pulse=0;
 // Three-stage impulse path: differences, magnitude, threshold decision.
 // Countdown timers remove full-width timestamp subtraction from capture enables.
 reg signed [16:0] dx_r=0,dy_r=0,dz_r=0;
 wire [17:0] adx=dx_r[16] ? -dx_r : dx_r,ady=dy_r[16] ? -dy_r : dy_r,adz=dz_r[16] ? -dz_r : dz_r;
 reg [19:0] delta_r=0;reg v0=0,v1=0;reg [63:0] sample_t0=0,sample_t1=0;
 reg [26:0] refractory=0,pair_remaining=0,pair_min_remaining=0;
 wire [26:0] max_ticks=max_ms*(CLOCK_HZ/1000),min_ticks=min_ms*(CLOCK_HZ/1000);
 always @(posedge clk)begin
  tap_pulse<=0;pair_pulse<=0;previous_center<=center;
  v0<=0;v1<=v0;
  if(reset || !enabled)begin
   xyz_seen<=0;tap_rearmed<=1;pair_pending<=0;refractory<=0;v0<=0;v1<=0;
  end else begin
   if(refractory!=0)refractory<=refractory-1'b1;
   if(pair_pending)begin
    if(pair_remaining!=0)pair_remaining<=pair_remaining-1'b1;else pair_pending<=0;
    if(pair_min_remaining!=0)pair_min_remaining<=pair_min_remaining-1'b1;
   end
   if(center && !previous_center)begin center_seq<=center_seq+1'b1;center_tick<=ticks;end
   if(xyz_valid)begin
    dx_r<=$signed(x)-$signed(px);dy_r<=$signed(y)-$signed(py);dz_r<=$signed(z)-$signed(pz);
    sample_t0<=xyz_tick;v0<=xyz_seen;px<=x;py<=y;pz<=z;xyz_seen<=1;
   end
   if(v0)begin delta_r<={2'b0,adx}+{2'b0,ady}+{2'b0,adz};sample_t1<=sample_t0;end
   if(v1)begin
    last_delta<={12'b0,delta_r};
    if(delta_r<=threshold_low)tap_rearmed<=1;
    if(tap_rearmed && delta_r>=threshold_high && refractory==0)begin
     tap_rearmed<=0;tap_pulse<=1;tap_seq<=tap_seq+1'b1;tap_tick<=sample_t1;
     refractory<=CLOCK_HZ/10-1;
     if(!game && wake && !job_active)begin
      if(pair_pending && pair_min_remaining==0)begin
       pair_pending<=0;pair_pulse<=1;double_seq<=double_seq+1'b1;double_tick<=sample_t1;
      end else if(!pair_pending)begin
       first_tap<=sample_t1;pair_pending<=1;pair_remaining<=max_ticks-1'b1;pair_min_remaining<=min_ticks-1'b1;
      end
     end
    end
   end
  end
  if(reset)begin tap_seq<=0;double_seq<=0;center_seq<=0;tap_tick<=0;double_tick<=0;end
 end
 reg start_cache=0;reg [15:0] last_start_seq=0;
 wire duplicate_start=start_cache && last_start_seq==command_seq;
 // The original impulse detector and double-tap diagnostics above are intact.
 // Only this independent three-tap collector is allowed to start recording.
 wire triple_eligible=enabled && wake && !job_active && capture_state==EMPTY && !panel_quiet;
 reg [1:0] triple_pending=0;reg triple_pulse=0;
 reg [26:0] triple_max_remaining=0,triple_min_remaining=0;
 wire triple_config=command_start && command_head[7:0]==0;
 wire capture_start=triple_pulse && triple_eligible && !triple_config;
 // Explicit, record-bound cancellation. No RAM clearing is necessary: EMPTY
 // and count=0 make old words unreadable; the next START takes a new record ID.
 wire abort_request=command_start && command_length==1 && command_head[7:0]==6;
 wire abort_good=abort_request && command_event==record_id;
 always @(posedge clk)begin
  triple_pulse<=0;
  if(reset || !triple_eligible || triple_config || abort_good)begin
   triple_pending<=0;triple_max_remaining<=0;triple_min_remaining<=0;
  end else begin
   if(triple_pending!=0)begin
    if(triple_max_remaining!=0)triple_max_remaining<=triple_max_remaining-1'b1;
    else triple_pending<=0;
    if(triple_min_remaining!=0)triple_min_remaining<=triple_min_remaining-1'b1;
   end
   if(tap_pulse)begin
    if(triple_pending!=0 && triple_max_remaining!=0 && triple_min_remaining==0)begin
     if(triple_pending==2)begin triple_pulse<=1;triple_pending<=0;end
     else triple_pending<=2;
    end else triple_pending<=1; // A bad adjacent gap starts a new sequence here.
    // MAX includes a tap exactly max_ticks clocks later; MIN opens at min_ticks.
    triple_max_remaining<=max_ticks;
    triple_min_remaining<=min_ticks==0 ? 0 : min_ticks-1'b1;
   end
  end
 end
 wire ack_request=command_start && command_length==9 && command_head[7:0]==4;
 wire ack_good=ack_request && capture_state==FROZEN && command_event==record_id &&
               command_head[39:8]==count && command_head[71:40]==full_crc;
 reg ack_cache=0;reg [31:0] ack_id=0,ack_count=0,ack_crc=0;
 wire duplicate_ack=ack_request && ack_cache && command_event==ack_id && command_head[39:8]==ack_count && command_head[71:40]==ack_crc;
 reg [4:0] progress=0;reg [31:0] next_led=10000,led_step=10000;
 assign panel_capture_state=capture_state;assign panel_target=target;assign panel_count=count;assign panel_rate=sample_rate;
 assign panel_record_id=record_id;assign panel_progress=progress;assign panel_game=game;assign panel_wake=wake;
 assign panel_job_active=job_active;assign panel_max_ms=max_ms;
 assign leds=capture_state==RECORD ? (16'hffff>>(16-progress)) : capture_state==FROZEN ? 16'hffff : {15'b0,ticks[25]};
 always @(posedge clk)begin
  if(reset)begin
   capture_state<=EMPTY;record_id<=0;count<=0;crc_phase<=0;overflow<=0;job_active<=0;human_tick<=0;ack_cache<=0;
  end else if(abort_good)begin
   // Highest priority, including a simultaneous stored sample or wake pulse.
   // Configuration and detector history intentionally keep their old meaning.
   capture_state<=EMPTY;job_active<=0;count<=0;progress<=0;crc_phase<=0;
   crc<=32'hffffffff;full_crc<=0;prefix_crc<=0;crc_number<=0;crc_sample<=0;
   overflow<=0;human_tick<=0;ack_cache<=0;
   first_tick<=0;last_tick<=0;first_index<=0;start_tick<=0;
  end else begin
   if(command_start && command_head[7:0]==5 && command_length==1 && capture_state==EMPTY)job_active<=0;
   if(game && job_active && human_tick==0 && tap_pulse && tap_tick>=start_tick && !panel_quiet)human_tick<=tap_tick;
   if(capture_start)begin
    capture_state<=RECORD;record_id<=record_id+1'b1;count<=0;crc<=32'hffffffff;full_crc<=0;prefix_crc<=0;
    crc_phase<=0;overflow<=0;start_tick<=ticks;job_active<=1;human_tick<=0;progress<=0;
    led_step<=target==128000 ? 8000 : target==160000 ? 10000 : target>>4;
    next_led<=target==128000 ? 8000 : target==160000 ? 10000 : target>>4;
   end else begin
    if(capture_state==RECORD && stored_valid)begin
     memory[count[AW-1:0]]<=stored_pcm;
     if(count==0)begin first_tick<=ticks;first_index<=stored_index;end
     last_tick<=ticks;count<=count+1'b1;
     if(crc_phase!=0)overflow<=overflow+1'b1;
     crc_sample<=stored_pcm;crc_number<=count+1'b1;crc_phase<=1;
     if(count+1'b1>=next_led && progress<16)begin progress<=progress+1'b1;next_led<=next_led+led_step;end
     if(count+1'b1==target)capture_state<=DRAIN;
    end
    if(crc_phase!=0)begin
     crc<=next_crc;
     if(crc_phase==1)crc_phase<=2;
     else begin crc_phase<=0;if(crc_number==(half_rate ? 64000 : 128000))prefix_crc<=~next_crc;end
    end
    if(capture_state==DRAIN && crc_phase==0)begin full_crc<=~crc;capture_state<=FROZEN;end
    if(ack_good)begin
     capture_state<=EMPTY;ack_cache<=1;ack_id<=record_id;ack_count<=count;ack_crc<=full_crc;
    end
   end
  end
 end
 reg [7:0] reply_mem[0:511];assign reply_data=reply_mem[reply_address];
 reg [1023:0] image=0,header=0;
 always @*begin
  image=0;image[8+:8]=1;image[16+:8]={6'b0,capture_state};image[24+:8]={3'b0,half_rate,job_active,game,wake,enabled};
  image[32+:32]=record_id;image[64+:32]=target;image[96+:32]=count;image[128+:32]=sample_rate;
  image[160+:32]=full_crc;image[192+:64]=first_tick;image[256+:64]=last_tick;image[320+:64]=first_index;
  image[384+:64]=start_tick;image[448+:64]=ticks;image[512+:32]=tap_seq;image[544+:32]=double_seq;
  image[576+:64]=tap_tick;image[640+:64]=double_tick;image[704+:32]=center_seq;
  image[736+:16]=threshold_high;image[752+:16]=threshold_low;image[768+:64]=center_tick;
  image[832+:64]=human_tick;image[896+:32]=prefix_crc;image[928+:32]=overflow;
  image[960+:32]=last_delta;image[992+:32]=MAX_SAMPLES;
 end
 localparam Q_IDLE=0,Q_SETTLE=1,Q_HEADER=2,Q_REQ=3,Q_W1=4,Q_W2=5,Q_W3=6,Q_LO=7,Q_HI=8;
 reg [3:0] state=Q_IDLE;reg [1:0] settle=0;
 reg [8:0] output_pos=0;reg [15:0] header_size=128,read_n=0,read_i=0;
 reg [31:0] read_base=0;reg [7:0] error=0;
 wire [31:0] requested_base=command_head[39:8];wire [15:0] requested_n=command_head[55:40];
 always @(posedge clk)begin
  if(reset)begin state<=Q_IDLE;done<=0;enabled<=0;wake<=0;game<=0;half_rate<=0;start_cache<=0;end
  else if(command_start && state==Q_IDLE)begin
   done<=0;error<=0;read_n<=0;output_pos<=0;header_size<=128;reply_length<=128;settle<=0;state<=Q_SETTLE;
   case(command_head[7:0])
    0:if(command_length!=16 || command_head[63:32]>MAX_SAMPLES || command_head[63:32]<16 ||
         (MAX_SAMPLES>4096 && command_head[63:32]!=128000 && command_head[63:32]!=160000) ||
         command_head[79:64]<command_head[95:80] || command_head[95:80]==0 ||
         command_head[127:112]>1000 || command_head[111:96]>command_head[127:112])error<=7;
      else if(capture_state!=EMPTY || job_active)error<=1;
      else begin
       enabled<=command_head[8];wake<=command_head[9];game<=command_head[10];half_rate<=command_head[11];target<=command_head[63:32];
       threshold_high<=command_head[79:64];threshold_low<=command_head[95:80];min_ms<=command_head[111:96];max_ms<=command_head[127:112];
      end
    1:if(command_length!=1)error<=7;
      else if(job_active || capture_state!=EMPTY)error<=1;
      else error<=8; // KNOCK_REQUIRED: GUI/SW enter waiting, never bypass taps.
    2:if(command_length!=1)error<=7;
    3:begin
     header_size<=32;
     if(command_length!=7 || requested_n==0 || requested_n>240 || requested_base>=MAX_SAMPLES ||
        {1'b0,requested_base}+requested_n>{1'b0,count})error<=7;
     else if(capture_state!=FROZEN)error<=2;
     else if(command_event!=record_id)error<=3;
     else begin read_base<=requested_base;read_n<=requested_n;read_i<=0;reply_length<=32+requested_n*2;end
    end
    4:if(!ack_good && !duplicate_ack)error<=5;
    5:if(command_length!=1 || capture_state!=EMPTY)error<=1;
      else start_cache<=0; // FINISH is a transaction barrier; a new host may reuse the sequence.
    6:if(command_length!=1)error<=7;
      else if(command_event!=record_id)error<=3;
      else start_cache<=0; // ABORT is also a START transaction barrier.
    default:error<=6;
   endcase
  end else case(state)
   Q_SETTLE:if(settle==2)begin
    header<=image;header[7:0]<=error;
    if(header_size==32)begin
     header[64+:32]<=read_base;header[96+:16]<=read_n;header[112+:16]<=sample_rate[15:0];
     header[128+:32]<=count;header[160+:32]<=full_crc;header[192+:64]<=first_tick;
     if(error!=0)reply_length<=32;
    end
    state<=Q_HEADER;
   end else settle<=settle+1'b1;
   Q_HEADER:begin
    reply_mem[output_pos]<=header[output_pos*8+:8];
    if(output_pos==header_size-1)begin
     if(read_n==0 || error!=0)begin done<=1;state<=Q_IDLE;end else begin state<=Q_REQ;output_pos<=32;end
    end else output_pos<=output_pos+1'b1;
   end
   Q_REQ:begin read_address<=read_base[AW-1:0]+read_i;state<=Q_W1;end
   Q_W1:state<=Q_W2;Q_W2:state<=Q_W3;Q_W3:state<=Q_LO;
   Q_LO:begin reply_mem[output_pos]<=memory_q2[7:0];output_pos<=output_pos+1'b1;state<=Q_HI;end
   Q_HI:begin
    reply_mem[output_pos]<=memory_q2[15:8];output_pos<=output_pos+1'b1;
    if(read_i==read_n-1)begin done<=1;state<=Q_IDLE;end else begin read_i<=read_i+1'b1;state<=Q_REQ;end
   end
   default:begin end
  endcase
 end
endmodule
