`timescale 1ns/1ps
// Bounded, requested telemetry. Original event memories and commands are independent.
module monitor_core(
    input wire clk,reset,input wire [63:0] ticks,
    input wire pcm_valid,input wire signed [15:0] pcm,
    input wire xyz_valid,input wire [63:0] xyz_tick,input wire signed [15:0] x,y,z,
    input wire [1535:0] status_header,
    input wire command_start,input wire [7:0] command,input wire [15:0] command_length,
    input wire [127:0] command_head,input wire [31:0] command_event,
    input wire [8:0] reply_address,output wire [7:0] reply_data,
    output reg done=0,output reg [15:0] reply_length=1,
    output reg [31:0] preview_total=0,xyz_total=0,snapshot_id=0
);
    reg [7:0] reply_mem[0:511];assign reply_data=reply_mem[reply_address];
    (* ram_style="block" *) reg [15:0] audio_ring[0:1023],snapshot[0:511];
    (* ram_style="distributed" *) reg [31:0] preview_ring[0:127];
    (* ram_style="distributed" *) reg [127:0] xyz_ring[0:31];
    reg [9:0] audio_write=0,audio_read=0;reg [15:0] audio_q=0,snapshot_q=0;
    reg [8:0] snapshot_read=0;
    reg [6:0] preview_read=0;reg [31:0] preview_q=0;
    reg [4:0] xyz_read=0;reg [127:0] xyz_q=0;
    reg [63:0] audio_total=0,last_pcm_tick=0,last_preview_tick=0;
    reg signed [15:0] low=0,high=0;
    reg [3:0] bin=0;
    wire signed [15:0] next_low=bin==0 || pcm<low ? pcm : low;
    wire signed [15:0] next_high=bin==0 || pcm>high ? pcm : high;
    always @(posedge clk)begin
        audio_q<=audio_ring[audio_read];snapshot_q<=snapshot[snapshot_read];
        preview_q<=preview_ring[preview_read];xyz_q<=xyz_ring[xyz_read];
        if(reset)begin
            audio_write<=0;audio_total<=0;bin<=0;preview_total<=0;xyz_total<=0;
        end else begin
            if(pcm_valid)begin
                audio_ring[audio_write]<=pcm;audio_write<=audio_write+1'b1;
                audio_total<=audio_total+1'b1;last_pcm_tick<=ticks;
                low<=next_low;high<=next_high;bin<=bin+1'b1;
                if(bin==15)begin
                    preview_ring[preview_total[6:0]]<={next_high,next_low};
                    preview_total<=preview_total+1'b1;last_preview_tick<=ticks;
                end
            end
            if(xyz_valid)begin
                xyz_ring[xyz_total[4:0]]<={16'b0,z,y,x,xyz_tick};xyz_total<=xyz_total+1'b1;
            end
        end
    end
    localparam IDLE=0,HEADER=1,READ_REQ=2,READ_WAIT=3,READ_LATCH=4,READ_BYTES=5,COPY_REQ=6,COPY_WAIT=7,COPY_SAVE=8;
    reg [3:0] state=0;
    reg [7:0] mode=0;
    reg [1535:0] header=0;
    reg [9:0] byte_index=0,header_length=0,record_index=0,record_count=0;
    reg [4:0] byte_in_record=0;
    reg [6:0] preview_base=0;reg [4:0] xyz_base=0;
    reg [9:0] audio_base=0;reg [8:0] snapshot_offset=0;
    reg [127:0] record_word=0;
    reg snapshot_ready=0;
    reg [63:0] snapshot_tick=0,snapshot_first=0;
    wire [6:0] preview_n=preview_total<64 ? preview_total[6:0] : 7'd64;
    wire [4:0] xyz_n=xyz_total<16 ? xyz_total[4:0] : 5'd16;
    wire [15:0] requested_offset=command_head[23:8],requested_count=command_head[39:24];
    task audio_header;
        input [7:0] error_code;input [15:0] offset,count;
        begin
            header<=0;header[7:0]<=error_code;header[15:8]<=1;
            header[23:16]<={7'b0,snapshot_ready};header[32+:32]<=snapshot_id;
            header[64+:64]<=snapshot_tick;header[128+:64]<=snapshot_first;
            header[192+:16]<=512;header[208+:16]<=6250;
            header[224+:16]<=offset;header[240+:16]<=count;
            header_length<=32;byte_index<=0;state<=HEADER;
            reply_length<=32+count*2;
        end
    endtask
    always @(posedge clk)begin
        if(reset)begin state<=IDLE;done<=0;snapshot_id<=0;snapshot_ready<=0;end
        else if(command_start && state==IDLE)begin
            done<=0;mode<=command;byte_index<=0;record_index<=0;byte_in_record<=0;
            if(command==12 && command_length==0)begin
                header<=status_header;header[1472+:32]<=xyz_total-xyz_n;
                header[1504+:16]<={11'b0,xyz_n};header[1520+:8]<=1;
                header_length<=192;record_count<={5'b0,xyz_n};xyz_base<=xyz_total[4:0]-xyz_n;
                reply_length<=192+{xyz_n,4'b0};state<=HEADER;
            end else if(command==13 && command_length==0)begin
                header<=0;header[15:8]<=1;header[23:16]<={1'b0,preview_n};
                header[32+:32]<=preview_total-preview_n;header[64+:64]<=last_preview_tick;
                header[128+:32]<=audio_total[31:0];header[160+:16]<=16;header[176+:16]<=16000;
                header_length<=24;record_count<={3'b0,preview_n};preview_base<=preview_total[6:0]-preview_n;
                reply_length<=24+{preview_n,2'b0};state<=HEADER;
            end else if(command==14 && command_length==5)begin
                if(command_head[7:0]==0)begin
                    if(audio_total<512)begin record_count<=0;audio_header(2,0,0);end
                    else begin
                        snapshot_ready<=0;snapshot_id<=snapshot_id+1'b1;audio_base<=audio_write-10'd512;
                        snapshot_tick<=last_pcm_tick-64'd3193750;snapshot_first<=audio_total-64'd512;
                        record_index<=0;record_count<=0;state<=COPY_REQ;
                    end
                end else if(command_head[7:0]==1)begin
                    if(!snapshot_ready)begin record_count<=0;audio_header(2,0,0);end
                    else if(command_event!=snapshot_id)begin record_count<=0;audio_header(3,0,0);end
                    else if(requested_count==0 || requested_count>240 || requested_offset>511 ||
                            {1'b0,requested_offset}+{1'b0,requested_count}>512)begin
                        record_count<=0;audio_header(7,0,0);
                    end else begin
                        snapshot_offset<=requested_offset[8:0];record_count<=requested_count[9:0];
                        audio_header(0,requested_offset,requested_count);
                    end
                end else if(command_head[7:0]==2)begin
                    snapshot_ready<=0;record_count<=0;audio_header(0,0,0);
                end else begin record_count<=0;audio_header(7,0,0);end
            end else begin reply_mem[0]<=7;reply_length<=1;done<=1;end
        end else case(state)
            HEADER:begin
                reply_mem[byte_index[8:0]]<=header[byte_index*8+:8];
                if(byte_index==header_length-1)begin
                    byte_index<=byte_index+1'b1;
                    if(record_count==0)begin done<=1;state<=IDLE;end else state<=READ_REQ;
                end else byte_index<=byte_index+1'b1;
            end
            READ_REQ:begin
                if(mode==12)xyz_read<=xyz_base+record_index[4:0];
                else if(mode==13)preview_read<=preview_base+record_index[6:0];
                else snapshot_read<=snapshot_offset+record_index[8:0];
                state<=READ_WAIT;
            end
            READ_WAIT:state<=READ_LATCH;
            READ_LATCH:begin
                record_word<=mode==12 ? xyz_q : mode==13 ? {96'b0,preview_q} : {112'b0,snapshot_q};
                byte_in_record<=0;state<=READ_BYTES;
            end
            READ_BYTES:begin
                reply_mem[byte_index[8:0]]<=record_word[byte_in_record*8+:8];byte_index<=byte_index+1'b1;
                if(byte_in_record==(mode==12 ? 15 : mode==13 ? 3 : 1))begin
                    record_index<=record_index+1'b1;
                    if(record_index==record_count-1)begin state<=IDLE;done<=1;end
                    else state<=READ_REQ;
                end else byte_in_record<=byte_in_record+1'b1;
            end
            COPY_REQ:begin audio_read<=audio_base+record_index;state<=COPY_WAIT;end
            COPY_WAIT:state<=COPY_SAVE;
            COPY_SAVE:begin
                snapshot[record_index[8:0]]<=audio_q;
                if(record_index==511)begin
                    snapshot_ready<=1;record_index<=0;record_count<=0;
                    audio_header(0,0,0);header[23:16]<=1;
                end else begin record_index<=record_index+1'b1;state<=COPY_REQ;end
            end
        endcase
    end
endmodule
