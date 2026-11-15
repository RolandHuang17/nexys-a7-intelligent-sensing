`timescale 1ns/1ps
module record_bank #(
    parameter integer PRE_SAMPLES=8000,POST_SAMPLES=16000,XYZ_DEPTH=512,
    parameter integer PRE_TICKS=50000000,POST_TICKS=100000000,
    parameter integer PCM_PERIOD=6250,DRAIN_TICKS=10000
)(
    input wire clk,reset,input wire [63:0] ticks,
    input wire pcm_valid,input wire signed [15:0] pcm,input wire [63:0] pcm_index,
    input wire xyz_valid,input wire signed [15:0] x,y,z,input wire [63:0] xyz_tick,
    input wire capture,input wire [31:0] capture_id,input wire [63:0] capture_tick,
    input wire ack,input wire [31:0] ack_id,ack_length,ack_crc,
    input wire read_en,input wire [31:0] read_offset,
    output wire read_valid,output reg [7:0] read_data=0,
    output wire ready,frozen,post_active,output reg ack_ok=0,
    output reg [31:0] event_id=0,event_crc=0,xyz_count=0,
    output reg [63:0] anchor=0,first_pcm_index=0,first_pcm_tick=0,
    output wire [31:0] payload_length,
    output reg [31:0] history_wraps=0
);
    import recorder_pkg::*;
    localparam integer NS=PRE_SAMPLES+POST_SAMPLES;
    localparam integer PW=$clog2(NS),XW=$clog2(XYZ_DEPTH);
    localparam IDLE=0,POST=1,SCAN_REQ=2,SCAN_WAIT=3,CRC_REQ=4,CRC_WAIT=5,FROZEN=6;
    (* ram_style="block" *) reg [15:0] pcm_mem[0:NS-1];
    (* ram_style="block" *) reg [79:0] xyz_mem[0:XYZ_DEPTH-1];
    reg [PW-1:0] pcm_wp=0,pcm_start=0;
    reg [XW-1:0] xyz_wp=0,xyz_start=0,scan_ptr=0;
    reg [31:0] history_count=0,xyz_retained=0,scan_left=0;
    reg [63:0] last_pcm_tick=0;
    reg [31:0] history_ticks=0;
    reg [$clog2(POST_SAMPLES+1)-1:0] post_remaining=0;
    reg [3:0] state=IDLE;
    reg [31:0] crc=32'hffffffff,crc_offset=0;
    reg [31:0] released_id=0,released_length=0,released_crc=0;
    reg metadata_pending=0,metadata_lag=0;
    reg [63:0] metadata_index=0,metadata_next_tick=0;
    reg [PW-1:0] metadata_wp=0;
    wire [63:0] window_start=anchor-PRE_TICKS;
    wire [63:0] window_end=anchor+POST_TICKS;
    assign ready=state==IDLE && history_count>PRE_SAMPLES && history_ticks>=PRE_TICKS;
    assign frozen=state==FROZEN;
    wire [31:0] post_elapsed=ticks[31:0]-anchor[31:0];
    wire [31:0] xyz_window_offset=xyz_tick[31:0]-window_start[31:0];
    wire signed [31:0] last_vs_anchor=last_pcm_tick[31:0]-capture_tick[31:0];
    // Trigger decisions can arrive a few fabric clocks after their timestamp.
    // At most one PCM may have arrived meanwhile; include it in the post-window.
    wire anchor_lag_one=!pcm_valid && last_vs_anchor>=0;
    // Register the next-cycle deadline so the time subtraction cannot feed
    // all capture/metadata enables through the top-level busy decision.
    // ticks advances by one each clock; comparing POST_TICKS-1 keeps the
    // externally visible busy boundary at the original POST_TICKS instant.
    reg post_closed=0;
    always @(posedge clk)begin
        if(reset || (state==IDLE && capture && ready))post_closed<=0;
        else post_closed<=post_elapsed>=POST_TICKS-1;
    end
    assign post_active=state==POST && !post_closed;
    assign payload_length=NS*2+xyz_count*10;
    wire internal_scan=state==SCAN_REQ;
    wire internal_crc=state==CRC_REQ;
    wire access_en=internal_scan || internal_crc || (state==FROZEN && read_en);
    wire [31:0] offset=internal_crc ? crc_offset : read_offset;
    // All valid event offsets fit 16 bits. Pipeline address arithmetic; no
    // 32-bit add/subtract/divide chain is allowed between read control and BRAM.
    reg [5:0] read_pipeline=0;
    assign read_valid=read_pipeline[5];
    reg [15:0] offset0=0,pcm_linear1=0,xyz_offset1=0,xyz_offset2=0;
    reg audio1=0,audio2=0,audio3=0,low_bit1=0,low_bit2=0;
    reg scan0=0,scan1=0,scan2=0;
    reg [XW-1:0] scanptr0=0,scanptr1=0,scanptr2=0,xyz_address3=0;
    reg [PW-1:0] pcm_address2=0,pcm_address3=0;
    reg [31:0] quotient_product2=0;
    wire [12:0] xyz_quotient=quotient_product2[31:19];
    reg [3:0] byte_position3=0;
    reg [15:0] pcm_q=0;
    reg [79:0] xyz_q=0;
    reg audio_selected=0;
    reg [3:0] byte_selected=0;
    wire [31:0] relative_xyz_tick=xyz_q[31:0]-window_start[31:0];
    wire [79:0] export_xyz={xyz_q[79:32],relative_xyz_tick};
    wire [31:0] next_crc=crc32_byte(crc,read_data);
    always @(posedge clk)begin
        read_pipeline<={read_pipeline[4:0],access_en};
        if(access_en)begin
            offset0<=offset[15:0];scan0<=internal_scan;scanptr0<=scan_ptr;
        end
        if(read_pipeline[0])begin
            pcm_linear1<=pcm_start+(offset0>>1);audio1<=offset0<NS*2;
            xyz_offset1<=offset0<NS*2 ? 0 : offset0-NS*2;
            low_bit1<=offset0[0];scan1<=scan0;scanptr1<=scanptr0;
        end
        if(read_pipeline[1])begin
            pcm_address2<=pcm_linear1>=NS ? pcm_linear1-NS : pcm_linear1;
            // floor(n/10) = (n*52429)>>19 for all unsigned 16-bit n.
            quotient_product2<=xyz_offset1*16'd52429;xyz_offset2<=xyz_offset1;
            audio2<=audio1;low_bit2<=low_bit1;scan2<=scan1;scanptr2<=scanptr1;
        end
        if(read_pipeline[2])begin
            xyz_address3<=scan2 ? scanptr2 : xyz_start+xyz_quotient;
            pcm_address3<=pcm_address2;audio3<=audio2;
            byte_position3<=audio2 ? {3'b0,low_bit2} : xyz_offset2-xyz_quotient*10;
        end
        if(read_pipeline[3])begin
            pcm_q<=pcm_mem[pcm_address3];xyz_q<=xyz_mem[xyz_address3];
            audio_selected<=audio3;byte_selected<=byte_position3;
        end
        if(read_pipeline[4])begin
            read_data<=audio_selected ? (byte_selected==0 ? pcm_q[7:0] : pcm_q[15:8]) :
                       export_xyz[byte_selected*8+:8];
        end
        ack_ok<=0;
        metadata_pending<=0;
        if(reset)begin
            pcm_wp<=0;xyz_wp<=0;history_count<=0;xyz_retained<=0;state<=IDLE;
            history_ticks<=0;post_remaining<=0;event_id<=0;event_crc<=0;xyz_count<=0;history_wraps<=0;
            released_id<=0;read_pipeline<=0;
            metadata_pending<=0;
        end else begin
            if(pcm_valid)last_pcm_tick<=ticks;
            if(state==IDLE && history_ticks<PRE_TICKS)history_ticks<=history_ticks+1'b1;
            if(pcm_valid && (state==IDLE || (state==POST && post_remaining!=0)))begin
                pcm_mem[pcm_wp]<=pcm;
                if(pcm_wp==NS-1)begin pcm_wp<=0;history_wraps<=history_wraps+1'b1;end
                else pcm_wp<=pcm_wp+1'b1;
                if(history_count<PRE_SAMPLES+1)history_count<=history_count+1'b1;
                if(state==POST)post_remaining<=post_remaining-1'b1;
            end
            if(xyz_valid && (state==IDLE || (state==POST && xyz_window_offset<PRE_TICKS+POST_TICKS)))begin
                xyz_mem[xyz_wp]<={z,y,x,xyz_tick[31:0]};xyz_wp<=xyz_wp+1'b1;
                if(xyz_retained<XYZ_DEPTH)xyz_retained<=xyz_retained+1'b1;
            end
            if(ack && ack_id!=0 && ack_id==released_id && ack_length==released_length && ack_crc==released_crc)ack_ok<=1;
            if(metadata_pending)begin
                first_pcm_index<=metadata_index-(metadata_lag ? PRE_SAMPLES+1 : PRE_SAMPLES);
                first_pcm_tick<=metadata_next_tick-(metadata_lag ? (PRE_SAMPLES+1)*PCM_PERIOD : PRE_SAMPLES*PCM_PERIOD);
                pcm_start<=metadata_wp>=(metadata_lag ? PRE_SAMPLES+1 : PRE_SAMPLES) ?
                    metadata_wp-(metadata_lag ? PRE_SAMPLES+1 : PRE_SAMPLES) :
                    metadata_wp+(metadata_lag ? NS-PRE_SAMPLES-1 : NS-PRE_SAMPLES);
            end
            case(state)
            IDLE:if(capture && ready)begin
                event_id<=capture_id;anchor<=capture_tick;
                // The two cases are mutually exclusive (anchor_lag_one includes
                // !pcm_valid). Select constants instead of serial subtractors.
                post_remaining<=(pcm_valid || anchor_lag_one) ? POST_SAMPLES-1 : POST_SAMPLES;
                metadata_pending<=1;metadata_lag<=anchor_lag_one;metadata_index<=pcm_index;metadata_wp<=pcm_wp;
                metadata_next_tick<=pcm_valid ? ticks : last_pcm_tick+PCM_PERIOD;
                xyz_count<=0;state<=POST;
            end
            POST:if(post_elapsed>=POST_TICKS+DRAIN_TICKS && post_remaining==0)begin
                scan_ptr<=xyz_wp-xyz_retained;scan_left<=xyz_retained;
                state<=xyz_retained==0 ? CRC_REQ : SCAN_REQ;
                crc<=32'hffffffff;crc_offset<=0;
            end
            SCAN_REQ:state<=SCAN_WAIT;
            SCAN_WAIT:if(read_valid)begin
                if(relative_xyz_tick<PRE_TICKS+POST_TICKS)begin
                    if(xyz_count==0)xyz_start<=scan_ptr;
                    xyz_count<=xyz_count+1'b1;
                end
                scan_ptr<=scan_ptr+1'b1;scan_left<=scan_left-1'b1;
                state<=scan_left==1 ? CRC_REQ : SCAN_REQ;
            end
            CRC_REQ:state<=CRC_WAIT;
            CRC_WAIT:if(read_valid)begin
                crc<=next_crc;
                if(crc_offset==payload_length-1)begin event_crc<=~next_crc;state<=FROZEN;end
                else begin crc_offset<=crc_offset+1'b1;state<=CRC_REQ;end
            end
            FROZEN:if(ack && ack_id==event_id && ack_length==payload_length && ack_crc==event_crc)begin
                ack_ok<=1;released_id<=event_id;released_length<=payload_length;released_crc<=event_crc;
                event_id<=0;history_count<=0;xyz_retained<=0;history_ticks<=0;state<=IDLE;
            end
            default:state<=IDLE;
            endcase
        end
    end
endmodule
