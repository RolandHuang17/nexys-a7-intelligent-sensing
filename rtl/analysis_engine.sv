`timescale 1ns/1ps
module analysis_engine(
    input wire clk,reset,input wire [63:0] ticks,
    input wire pcm_valid,input wire signed [15:0] pcm,
    input wire xyz_valid,input wire [63:0] xyz_tick,input wire signed [15:0] x,y,z,
    input wire command_start,input wire [7:0] command,input wire [15:0] command_length,
    input wire [127:0] command_head,output reg [8:0] rx_address=0,input wire [7:0] rx_data,
    input wire [8:0] reply_address,output wire [7:0] reply_data,
    output reg command_done=0,output reg [15:0] reply_length=1,
    input wire [7:0] storage_reason,
    output reg armed=0,output reg [1:0] mode=3,
    output reg [31:0] config_id=0,audio_threshold=100,accel_threshold=10,window_ticks=5000000,
    output wire result_valid,audio_cross,accel_cross,joint_pair,joint_confirm,deduplicated,
    output reg [63:0] result_tick=0,output wire [63:0] t_audio,t_accel,t_confirm,
    output reg [63:0] history_count=0,output wire [31:0] late_xyz,
    output reg replay_mode=0
);
    reg [7:0] reply_mem[0:511];
    assign reply_data=reply_mem[reply_address];
    reg [63:0] virtual_tick=0;
    wire [63:0] core_time=replay_mode ? virtual_tick : ticks;
    reg [2:0] reset_count=0;
    reg pair_reset=0,history_reset=0,inject_pcm=0,inject_xyz=0;
    reg signed [15:0] injected_pcm=0,injected_x=0,injected_y=0,injected_z=0;
    wire core_reset=reset || reset_count!=0;
    wire feature_valid,aval,vval;
    wire [63:0] feature_tick;
    wire [31:0] afeature,vfeature;
    wire [15:0] an,xn;
    feature_core features(clk,core_reset,core_time,
        replay_mode ? inject_pcm : pcm_valid,replay_mode ? injected_pcm : pcm,
        replay_mode ? inject_xyz : xyz_valid,replay_mode ? virtual_tick : xyz_tick,
        replay_mode ? injected_x : x,replay_mode ? injected_y : y,replay_mode ? injected_z : z,
        feature_valid,feature_tick,afeature,vfeature,aval,vval,an,xn,late_xyz);
    trigger_core triggers(clk,core_reset||pair_reset,feature_valid,feature_tick,aval,vval,
        afeature,vfeature,audio_threshold,accel_threshold,window_ticks,
        result_valid,audio_cross,accel_cross,joint_pair,joint_confirm,deduplicated,t_audio,t_accel,t_confirm);
    reg [31:0] hold_audio=0,hold_accel=0;
    reg [15:0] hold_an=0,hold_xn=0;
    reg hold_aval=0,hold_vval=0;
    reg [15:0] hold_config=0;
    (* ram_style="block" *) reg [255:0] history[0:255];
    wire [31:0] audio_age=result_tick[31:0]-t_audio[31:0];
    wire [31:0] accel_age=result_tick[31:0]-t_accel[31:0];
    wire [255:0] history_word={joint_pair ? accel_age : 32'b0,joint_pair ? audio_age : 32'b0,
        hold_config,storage_reason,{1'b0,deduplicated,joint_confirm,joint_pair,accel_cross,audio_cross,hold_vval,hold_aval},
        hold_xn,hold_an,hold_accel,hold_audio,result_tick};
    always @(posedge clk)begin
        if(feature_valid)begin
            result_tick<=feature_tick;hold_audio<=afeature;hold_accel<=vfeature;
            hold_an<=an;hold_xn<=xn;hold_aval<=aval;hold_vval<=vval;
            hold_config<=config_id[15:0];
        end
        if(reset || history_reset)history_count<=0;
        else if(result_valid && !core_reset)begin
            history[history_count[7:0]]<=history_word;history_count<=history_count+1'b1;
        end
    end
    localparam S_IDLE=0,S_DECODE=1,S_BOUNDS=2,S_PREP=3,S_HEADER=4,S_ROW_REQ=5,
        S_ROW_WAIT=6,S_ROW_LATCH=7,S_ROW_BYTES=8,S_RESET_WAIT=9,
        S_ENTRY_WAIT=10,S_ENTRY_READ=11,S_ENTRY_COMMIT=12,S_INJECT_WAIT=13,S_INJECT=14,S_NEXT=15;
    reg [4:0] state=0;
    reg [7:0] cmd=0;
    reg [15:0] cmd_length=0;
    reg [127:0] head=0;
    reg [63:0] cal_start=0,cal_count_limit=0,cal_available=0;
    reg [4:0] cal_n=0,row_index=0;
    reg [5:0] byte_index=0,entries_left=0;
    reg [3:0] wait_cycles=0;
    reg [7:0] history_read_address=0;
    reg [255:0] history_q=0,row_cache=0;
    reg [103:0] entry=0;
    reg [1:0] injection_flags=0;
    wire [63:0] oldest=cal_count_limit>255 ? cal_count_limit-255 : 0;
    wire [111:0] cal_header={config_id,cal_start,{3'b0,cal_n},8'b0};
    always @(posedge clk)history_q<=history[history_read_address];
    always @(posedge clk)begin
        pair_reset<=0;history_reset<=0;inject_pcm<=0;inject_xyz<=0;
        if(reset_count!=0)reset_count<=reset_count-1'b1;
        if(reset)begin
            state<=S_IDLE;armed<=0;replay_mode<=0;command_done<=0;reset_count<=0;
            audio_threshold<=100;accel_threshold<=10;window_ticks<=5000000;config_id<=0;
        end else if(command_start && state==S_IDLE)begin
            cmd<=command;cmd_length<=command_length;head<=command_head;
            command_done<=0;reply_length<=1;reply_mem[0]<=0;state<=S_DECODE;
        end else case(state)
        S_DECODE:case(cmd)
        3:begin
            if(cmd_length!=9 || head[71:64]==0 || head[71:64]>15)begin
                reply_mem[0]<=7;command_done<=1;state<=S_IDLE;
            end else begin cal_start<=head[63:0];cal_n<=head[68:64];state<=S_BOUNDS;end
        end
        4:begin
            if(cmd_length!=16 || head[31:0]==0 || head[63:32]==0 || head[95:64]==0 || head[95:64]>8000000)reply_mem[0]<=7;
            else begin
                audio_threshold<=head[31:0];accel_threshold<=head[63:32];
                window_ticks<=head[95:64];config_id<=head[127:96];pair_reset<=1;
                armed<=0;
            end
            command_done<=1;state<=S_IDLE;
        end
        5:begin
            if(cmd_length!=2 || head[7:0]<1 || head[7:0]>3 || (replay_mode && head[15:8]!=0))reply_mem[0]<=7;
            else begin mode<=head[1:0];armed<=head[15:8]!=0;pair_reset<=1;end
            command_done<=1;state<=S_IDLE;
        end
        10:begin
            if(cmd_length==1 && (head[7:0]==0 || head[7:0]==1))begin
                replay_mode<=head[7:0]==1;virtual_tick<=0;armed<=0;
                reset_count<=4;pair_reset<=1;history_reset<=1;
                wait_cycles<=8;state<=S_RESET_WAIT;
            end else if(replay_mode && head[7:0]==2 && head[15:8]>0 && head[15:8]<=39 && cmd_length==2+13*head[15:8])begin
                entries_left<=head[13:8];rx_address<=2;byte_index<=0;state<=S_ENTRY_WAIT;
            end else if(replay_mode && head[7:0]==3 && cmd_length==5 && head[39:8]>=virtual_tick[31:0])begin
                virtual_tick<={32'b0,head[39:8]};wait_cycles<=8;state<=S_RESET_WAIT;
            end else begin reply_mem[0]<=7;command_done<=1;state<=S_IDLE;end
        end
        default:begin reply_mem[0]<=6;command_done<=1;state<=S_IDLE;end
        endcase
        S_BOUNDS:begin cal_count_limit<=history_count;cal_available<=history_count-cal_start;state<=S_PREP;end
        S_PREP:begin
            if(cal_start<oldest || cal_start>cal_count_limit)begin reply_mem[0]<=8;command_done<=1;state<=S_IDLE;end
            else begin
                if(cal_available<cal_n)cal_n<=cal_available[4:0];
                byte_index<=0;row_index<=0;state<=S_HEADER;
                reply_length<=14+32*(cal_available<cal_n ? cal_available[4:0] : cal_n);
            end
        end
        S_HEADER:begin
            reply_mem[byte_index]<=cal_header[byte_index*8+:8];
            if(byte_index==13)begin
                if(cal_n==0)begin command_done<=1;state<=S_IDLE;end
                else state<=S_ROW_REQ;
            end else byte_index<=byte_index+1'b1;
        end
        S_ROW_REQ:begin history_read_address<=cal_start[7:0]+row_index;state<=S_ROW_WAIT;end
        S_ROW_WAIT:state<=S_ROW_LATCH;
        S_ROW_LATCH:begin row_cache<=history_q;byte_index<=0;state<=S_ROW_BYTES;end
        S_ROW_BYTES:begin
            reply_mem[14+row_index*32+byte_index]<=row_cache[byte_index*8+:8];
            if(byte_index==31)begin
                if(row_index==cal_n-1)begin command_done<=1;state<=S_IDLE;end
                else begin row_index<=row_index+1'b1;state<=S_ROW_REQ;end
            end else byte_index<=byte_index+1'b1;
        end
        S_RESET_WAIT:begin
            if(wait_cycles==0)begin command_done<=1;state<=S_IDLE;end
            else wait_cycles<=wait_cycles-1'b1;
        end
        S_ENTRY_WAIT:state<=S_ENTRY_READ;
        S_ENTRY_READ:begin
            entry[byte_index*8+:8]<=rx_data;rx_address<=rx_address+1'b1;
            if(byte_index==12)state<=S_ENTRY_COMMIT;
            else byte_index<=byte_index+1'b1;
        end
        S_ENTRY_COMMIT:begin
            if(entry[31:0]<virtual_tick[31:0] || entry[39:34]!=0 || entry[33:32]==0)begin
                reply_mem[0]<=7;command_done<=1;state<=S_IDLE;
            end else begin
                virtual_tick<={32'b0,entry[31:0]};injection_flags<=entry[33:32];
                injected_pcm<=entry[55:40];injected_x<=entry[71:56];
                injected_y<=entry[87:72];injected_z<=entry[103:88];
                wait_cycles<=4;state<=S_INJECT_WAIT;
            end
        end
        S_INJECT_WAIT:begin
            if(wait_cycles==0)state<=S_INJECT;
            else wait_cycles<=wait_cycles-1'b1;
        end
        S_INJECT:begin inject_pcm<=injection_flags[0];inject_xyz<=injection_flags[1];state<=S_NEXT;end
        S_NEXT:begin
            if(entries_left==1)begin command_done<=1;state<=S_IDLE;end
            else begin entries_left<=entries_left-1'b1;byte_index<=0;state<=S_ENTRY_WAIT;end
        end
        default:state<=S_IDLE;
        endcase
    end
endmodule
