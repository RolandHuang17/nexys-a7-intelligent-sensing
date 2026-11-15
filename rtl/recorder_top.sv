`timescale 1ns/1ps
module recorder_top #(parameter integer MUSIC_MAX_SAMPLES=160000)(
    input wire CLK100MHZ,CPU_RESETN,BTNU,M_DATA,ACL_MISO,ACL_INT1,UART_TXD_IN,
    input wire BTND,BTNL,BTNR,BTNC,input wire [15:0] SW,
    input wire TMP_INT,TMP_CT,inout wire TMP_SCL,TMP_SDA,
    output reg M_CLK=0,output wire M_LRSEL,ACL_CSN,ACL_SCLK,ACL_MOSI,UART_RXD_OUT,
    output wire [15:0] LED,
    output wire LED16_R,LED16_G,LED16_B,LED17_R,LED17_G,LED17_B,
    output wire CA,CB,CC,CD,CE,CF,CG,DP,output wire [7:0] AN
);
    `include "build_id.svh"
    localparam [31:0] BUILD_ID=`RECORDER_BUILD_ID;
    wire clk=CLK100MHZ;
    (* ASYNC_REG="TRUE" *) reg [1:0] reset_sync=2'b11,mic_sync=0;
    (* ASYNC_REG="TRUE" *) reg [1:0] button_sync=0;
    reg button_previous=0;
    reg [15:0] button_presses=0;
    reg [7:0] reset_count=0;
    wire reset=reset_count!=255;
    reg [63:0] ticks=0,pcm_count=0,xyz_total=0,last_xyz_tick=0;
    reg [31:0] clip_count=0;
    wire pcm_valid,clipped,configured,id_ok,xyz_valid;
    wire signed [15:0] pcm,x,y,z;
    wire [63:0] xyz_tick;
    wire [31:0] identity,readback,overruns,rail_count;
    wire signed [15:0] accel_temperature;
    wire accel_temperature_valid;
    wire [63:0] accel_temperature_tick;
    always @(posedge clk)begin
        reset_sync<={reset_sync[0],CPU_RESETN};mic_sync<={mic_sync[0],M_DATA};
        button_sync<={button_sync[0],BTNU};button_previous<=button_sync[1];
        if(reset)button_presses<=0;
        else if(button_sync[1]&&!button_previous)button_presses<=button_presses+1'b1;
        if(!reset_sync[1])reset_count<=0;
        else if(reset_count!=255)reset_count<=reset_count+1'b1;
        if(reset)begin ticks<=0;pcm_count<=0;xyz_total<=0;clip_count<=0;end
        else begin
            ticks<=ticks+1'b1;
            if(pcm_valid)begin pcm_count<=pcm_count+1'b1;if(clipped)clip_count<=clip_count+1'b1;end
            if(xyz_valid)begin xyz_total<=xyz_total+1'b1;last_xyz_tick<=xyz_tick;end
        end
    end
    reg [4:0] pdm_div=0;
    reg pdm_valid=0;
    assign M_LRSEL=0;
    always @(posedge clk)begin
        pdm_valid<=0;
        if(reset)begin pdm_div<=0;M_CLK<=0;end
        else if(pdm_div==24)begin
            pdm_div<=0;M_CLK<=!M_CLK;if(!M_CLK)pdm_valid<=1;
        end else pdm_div<=pdm_div+1'b1;
    end
    pdm_cic microphone(clk,reset,pdm_valid,mic_sync[1],pcm_valid,pcm,clipped);
    adxl362 accelerometer(clk,reset,ticks,ACL_MISO,ACL_INT1,ACL_CSN,ACL_SCLK,ACL_MOSI,
        configured,id_ok,xyz_valid,x,y,z,xyz_tick,identity,readback,overruns,rail_count,
        accel_temperature,accel_temperature_valid,accel_temperature_tick);
    wire [15:0] sw_raw,sw_stable;
    wire [4:0] btn_raw,btn_stable;
    wire [31:0] gpio_changes;
    wire [159:0] button_press_counts,button_release_counts;
    gpio_monitor inputs_monitor(clk,reset,SW,{BTNC,BTNR,BTNL,BTND,BTNU},
        sw_raw,btn_raw,sw_stable,btn_stable,gpio_changes,button_press_counts,button_release_counts);
    wire adt_configured,adt_valid;
    wire signed [15:0] adt_temperature;
    wire [7:0] adt_identity,adt_configuration;
    wire [63:0] adt_tick,xadc_tick;
    wire [31:0] adt_samples,adt_errors,xadc_samples;
    wire [15:0] xadc_temperature,vccint,vccaux,vccbram;
    wire [3:0] xadc_valid;
    adt7420 board_temperature(clk,reset,ticks,TMP_SCL,TMP_SDA,adt_configured,adt_valid,
        adt_temperature,adt_identity,adt_configuration,adt_tick,adt_samples,adt_errors);
    xadc_monitor chip_monitor(clk,reset,ticks,xadc_temperature,vccint,vccaux,vccbram,
        xadc_valid,xadc_tick,xadc_samples);
    (* ASYNC_REG="TRUE" *) reg [1:0] temp_pins_sync1=3,temp_pins_sync2=3;
    always @(posedge clk)begin temp_pins_sync1<={TMP_CT,TMP_INT};temp_pins_sync2<=temp_pins_sync1;end

    wire request_valid,tx_busy;
    reg request_accept=0,payload_write=0,send_start=0;
    wire [7:0] request_command,request_data;
    wire [15:0] request_seq,request_length;
    wire [31:0] request_event;
    wire [127:0] request_head;
    reg [8:0] payload_address=0;
    reg [7:0] payload_data=0,send_command=0;
    reg [15:0] send_seq=0,send_length=0;
    reg [31:0] send_event=0;
    wire [31:0] packet_crc_errors,length_errors,framing_errors;
    reg [15:0] fill_index=0;
    wire [8:0] analysis_rx_address,request_read_address;
    packet_link link(clk,reset,UART_TXD_IN,UART_RXD_OUT,request_valid,request_accept,
        request_command,request_seq,request_length,request_event,request_head,
        request_read_address,request_data,payload_write,payload_address,payload_data,
        send_start,send_command,send_seq,send_length,send_event,tx_busy,
        packet_crc_errors,length_errors,framing_errors);

    localparam IDLE=0,CLASSIFY=1,FILL=2,SEND=3,READ_REQ=4,READ_WAIT=5,ACK_WAIT=6,ENGINE_WAIT=7,READ_BOUNDS=8,MON_WAIT=9,MUSIC_WAIT=10,PANEL_WAIT=11;
    localparam RM_ERROR=0,RM_STATUS=1,RM_LIST=2,RM_SNAP=3,RM_ECHO=4,RM_ENGINE=5,RM_MONITOR=6,RM_MUSIC=7,RM_PANEL=8;
    reg [3:0] state=IDLE,response_mode=0;
    reg [7:0] command=0,error_code=0;
    reg [15:0] cmd_seq=0,command_length=0;
    reg [31:0] command_event=0,next_event=1;
    reg [127:0] head=0;
    reg selected_bank=0;
    reg [15:0] read_base=0;
    reg [8:0] read_index=0,read_length=0;
    reg [16:0] read_end=0;
    reg snap_cache_valid=0;
    reg [15:0] snap_seq=0;
    reg [31:0] snap_id=0;
    reg [63:0] snap_tick=0;
    assign request_read_address=(state==ENGINE_WAIT && command==10) ? analysis_rx_address : fill_index[8:0];
    wire analysis_done,armed,replay_mode;
    wire [15:0] analysis_length;
    wire [7:0] analysis_data;
    wire [1:0] trigger_mode;
    wire [31:0] threshold_id,audio_threshold,accel_threshold,pair_window,late_xyz;
    wire trigger_valid,audio_cross,accel_cross,joint_pair,joint_confirm,deduplicated;
    wire [63:0] result_tick,t_audio,t_accel,t_confirm,feature_count;
    wire music_done,music_enabled;wire [7:0] music_data;wire [15:0] music_length,music_leds;
    wire panel_done,panel_quiet;wire [7:0] panel_reply;
    wire [1:0] panel_music_state;wire [4:0] panel_music_progress;
    wire [31:0] panel_music_target,panel_music_count,panel_music_rate,panel_music_record;
    wire panel_music_game,panel_music_wake,panel_music_job;wire [15:0] panel_music_max_ms;
    music_core #(.MAX_SAMPLES(MUSIC_MAX_SAMPLES)) music(clk,reset,ticks,pcm_count,pcm_valid,pcm,
        xyz_valid,xyz_tick,x,y,z,btn_stable[4],state==CLASSIFY && command==15,command_length,cmd_seq,head,command_event,
        fill_index[8:0],music_data,music_done,music_length,music_enabled,music_leds,
        panel_quiet,panel_music_state,panel_music_target,panel_music_count,panel_music_rate,panel_music_record,
        panel_music_progress,panel_music_game,panel_music_wake,panel_music_job,panel_music_max_ms);
    reg [7:0] storage_reason=0;
    reg [31:0] suppressed_post=0,suppressed_not_ready=0,suppressed_dedup=0;
    analysis_engine analysis(clk,reset,ticks,pcm_valid,pcm,xyz_valid,xyz_tick,x,y,z,
        state==CLASSIFY && (command==3 || command==4 || command==5 || command==10),
        command,command_length,head,analysis_rx_address,request_data,fill_index[8:0],analysis_data,
        analysis_done,analysis_length,storage_reason,armed,trigger_mode,threshold_id,audio_threshold,
        accel_threshold,pair_window,trigger_valid,audio_cross,accel_cross,joint_pair,joint_confirm,
        deduplicated,result_tick,t_audio,t_accel,t_confirm,feature_count,late_xyz,replay_mode);
    wire [1:0] bank_ready,bank_frozen,bank_post,bank_read_valid,bank_ack_ok;
    wire [7:0] bank_data[0:1];
    wire [31:0] bank_id[0:1],bank_crc[0:1],bank_xyz_count[0:1],bank_length[0:1],bank_wraps[0:1];
    wire [63:0] bank_anchor[0:1],bank_first_index[0:1],bank_first_tick[0:1];
    wire choose_bank=!bank_ready[0];
    wire is_duplicate=snap_cache_valid && cmd_seq==snap_seq;
    wire snap_allowed=command==6 && command_length==0 && !is_duplicate && !music_enabled &&
                      (|bank_ready) && !(|bank_post) && configured;
    wire manual_capture=state==CLASSIFY && snap_allowed;
    wire auto_candidate=trigger_valid && armed && !replay_mode && !music_enabled &&
        ((trigger_mode==1 && audio_cross)||(trigger_mode==2 && accel_cross)||(trigger_mode==3 && joint_pair));
    always @*begin
        storage_reason=0;
        if(auto_candidate)begin
            if(manual_capture || (|bank_post))storage_reason=2;
            else if(!( |bank_ready) || !configured)storage_reason=3;
            else if(trigger_mode==3 && deduplicated)storage_reason=4;
            else storage_reason=1;
        end
    end
    wire auto_capture=auto_candidate && storage_reason==1;
    reg [31:0] bank_config[0:1];
    reg [7:0] bank_mode[0:1];
    reg [63:0] bank_audio_time[0:1],bank_accel_time[0:1],bank_confirm_time[0:1];
    integer capture_bank;
    always @(posedge clk)begin
        if(reset)begin
            suppressed_post<=0;suppressed_not_ready<=0;suppressed_dedup<=0;
            for(capture_bank=0;capture_bank<2;capture_bank=capture_bank+1)begin
                bank_config[capture_bank]<=0;bank_mode[capture_bank]<=0;
                bank_audio_time[capture_bank]<=64'hffffffffffffffff;
                bank_accel_time[capture_bank]<=64'hffffffffffffffff;bank_confirm_time[capture_bank]<=0;
            end
        end else begin
            if(auto_candidate)case(storage_reason)
                2:suppressed_post<=suppressed_post+1'b1;
                3:suppressed_not_ready<=suppressed_not_ready+1'b1;
                4:suppressed_dedup<=suppressed_dedup+1'b1;
            endcase
            if(manual_capture || auto_capture)begin
                bank_config[choose_bank]<=threshold_id;
                bank_mode[choose_bank]<=manual_capture ? 0 : {6'b0,trigger_mode};
                bank_audio_time[choose_bank]<=manual_capture || trigger_mode==2 ? 64'hffffffffffffffff :
                    (trigger_mode==1 ? result_tick : t_audio);
                bank_accel_time[choose_bank]<=manual_capture || trigger_mode==1 ? 64'hffffffffffffffff :
                    (trigger_mode==2 ? result_tick : t_accel);
                bank_confirm_time[choose_bank]<=manual_capture ? ticks : result_tick;
            end
        end
    end
    genvar b;
    generate for(b=0;b<2;b=b+1)begin:BANK
        record_bank memory_bank(clk,reset,ticks,pcm_valid,pcm,pcm_count,
            xyz_valid,x,y,z,xyz_tick,
            (manual_capture || auto_capture) && choose_bank==b,next_event,manual_capture ? ticks : result_tick,
            state==CLASSIFY && command==9 && command_length==8,command_event,head[31:0],head[63:32],
            state==READ_REQ && selected_bank==b,read_base+read_index,
            bank_read_valid[b],bank_data[b],bank_ready[b],bank_frozen[b],bank_post[b],bank_ack_ok[b],
            bank_id[b],bank_crc[b],bank_xyz_count[b],bank_anchor[b],bank_first_index[b],bank_first_tick[b],
            bank_length[b],bank_wraps[b]);
    end endgenerate

    reg [1023:0] status_image;
    reg [1535:0] monitor_image;
    wire monitor_done;wire [15:0] monitor_length;wire [7:0] monitor_data;
    wire [31:0] preview_total,monitor_xyz_total,audio_snapshot_id;
    monitor_core telemetry(clk,reset,ticks,pcm_valid,pcm,xyz_valid,xyz_tick,x,y,z,monitor_image,
        state==CLASSIFY && (command==12 || command==13 || command==14),command,command_length,head,command_event,
        fill_index[8:0],monitor_data,monitor_done,monitor_length,preview_total,monitor_xyz_total,audio_snapshot_id);
    reg [1567:0] list_image;
    reg [127:0] snap_image;
    reg [1023:0] status_latched=0;
    reg [1567:0] list_latched=0;
    integer i;
    always @*begin
        monitor_image=0;
        monitor_image[8+:8]=1;
        monitor_image[16+:8]={2'b0,&xadc_valid,accel_temperature_valid,adt_valid,adt_configured,id_ok,configured};
        monitor_image[32+:32]=BUILD_ID;monitor_image[64+:64]=ticks;
        monitor_image[128+:64]=pcm_count;monitor_image[192+:64]=xyz_total;
        monitor_image[256+:64]=adt_tick;monitor_image[320+:16]=adt_temperature;
        monitor_image[336+:8]=adt_identity;monitor_image[344+:8]=adt_configuration;
        monitor_image[352+:32]=adt_errors;monitor_image[384+:64]=xadc_tick;
        monitor_image[448+:16]=xadc_temperature;monitor_image[464+:16]=vccint;
        monitor_image[480+:16]=vccaux;monitor_image[496+:16]=vccbram;
        monitor_image[512+:16]=accel_temperature;monitor_image[528+:16]=sw_raw;
        monitor_image[544+:16]=sw_stable;monitor_image[560+:8]={3'b0,btn_raw};
        monitor_image[568+:8]={3'b0,btn_stable};monitor_image[576+:32]=gpio_changes;
        monitor_image[608+:160]=button_press_counts;monitor_image[768+:160]=button_release_counts;
        monitor_image[928+:8]={6'b0,temp_pins_sync2};monitor_image[936+:8]={4'b0,xadc_valid};
        monitor_image[960+:32]=xadc_samples;monitor_image[992+:32]=adt_samples;
        monitor_image[1024+:16]=x;monitor_image[1040+:16]=y;monitor_image[1056+:16]=z;
        monitor_image[1088+:32]=overruns;monitor_image[1120+:32]=rail_count;
        monitor_image[1152+:32]=clip_count;monitor_image[1184+:32]=framing_errors;
        monitor_image[1216+:32]=packet_crc_errors;monitor_image[1248+:32]=length_errors;
        monitor_image[1280+:8]={6'b0,bank_ready};monitor_image[1288+:8]={6'b0,bank_frozen};
        monitor_image[1296+:8]={6'b0,bank_post};monitor_image[1304+:8]={4'b0,replay_mode,armed,trigger_mode};
        monitor_image[1312+:32]=preview_total;monitor_image[1344+:32]=monitor_xyz_total;
        monitor_image[1376+:32]=audio_snapshot_id;monitor_image[1408+:64]=accel_temperature_tick;
        status_image=0;
        status_image[8+:8]={6'b0,bank_ready};status_image[16+:8]={6'b0,bank_frozen};
        status_image[24+:8]={6'b0,bank_post};status_image[32+:32]=100000000;
        status_image[64+:64]=ticks;status_image[128+:64]=pcm_count;status_image[192+:64]=xyz_total;
        status_image[256+:32]=identity;status_image[288+:32]=readback;
        status_image[320+:16]=x;status_image[336+:16]=y;status_image[352+:16]=z;
        status_image[368+:8]={7'b0,configured};status_image[376+:8]={7'b0,id_ok};
        status_image[384+:32]=overruns;status_image[416+:32]=rail_count;
        status_image[448+:32]=clip_count;status_image[480+:32]=framing_errors;
        status_image[512+:32]=packet_crc_errors;status_image[544+:32]=length_errors;
        status_image[576+:64]=last_xyz_tick;status_image[640+:32]=BUILD_ID;
        status_image[672+:64]=feature_count;
        status_image[736+:32]=suppressed_post;status_image[768+:32]=suppressed_not_ready;
        status_image[800+:32]=suppressed_dedup;status_image[832+:32]=late_xyz;
        status_image[864+:32]=threshold_id;status_image[896+:32]=audio_threshold;
        status_image[928+:32]=accel_threshold;status_image[960+:32]=pair_window;
        status_image[992+:8]={4'b0,replay_mode,armed,trigger_mode};
        status_image[1000+:8]={7'b0,button_sync[1]};status_image[1008+:16]=button_presses;
        list_image=0;list_image[8+:8]={6'b0,bank_frozen};
        list_image[16+:8]={6'b0,bank_ready};list_image[24+:8]={6'b0,bank_post};
        for(i=0;i<2;i=i+1)begin
            list_image[32+i*768+:32]=bank_id[i];
            list_image[64+i*768+:64]=bank_anchor[i];
            list_image[128+i*768+:64]=bank_first_index[i];
            list_image[192+i*768+:64]=bank_first_tick[i];
            list_image[256+i*768+:32]=24000;
            list_image[288+i*768+:32]=bank_xyz_count[i];
            list_image[320+i*768+:32]=bank_length[i];
            list_image[352+i*768+:32]=bank_crc[i];
            list_image[384+i*768+:32]=bank_config[i];
            list_image[416+i*768+:8]=bank_mode[i];
            list_image[448+i*768+:64]=bank_audio_time[i];
            list_image[512+i*768+:64]=bank_accel_time[i];
            list_image[576+i*768+:64]=bank_confirm_time[i];
            list_image[640+i*768+:64]=bank_anchor[i]-50000000;
            list_image[704+i*768+:64]=bank_anchor[i]+100000000;
        end
        snap_image=0;snap_image[8+:32]=snap_id;snap_image[40+:64]=snap_tick;
    end
    always @(posedge clk)begin
        request_accept<=0;payload_write<=0;send_start<=0;
        if(reset)begin state<=IDLE;next_event<=1;snap_cache_valid<=0;end
        else begin
        if(auto_capture)next_event<=next_event+1'b1;
        case(state)
        IDLE:if(request_valid && !tx_busy)begin
            request_accept<=1;command<=request_command;cmd_seq<=request_seq;
            command_event<=request_event;command_length<=request_length;head<=request_head;
            send_command<=request_command|8'h80;send_seq<=request_seq;send_event<=request_event;
            state<=CLASSIFY;fill_index<=0;error_code<=0;
        end
        CLASSIFY:begin
            status_latched<=status_image;list_latched<=list_image;
            state<=FILL;response_mode<=RM_ERROR;send_length<=1;
            case(command)
            1,2:begin response_mode<=RM_STATUS;send_length<=128;if(command==1)snap_cache_valid<=0;end
            3,4,5,10:state<=ENGINE_WAIT;
            12,13,14:state<=MON_WAIT;
            15:state<=MUSIC_WAIT;
            16:state<=PANEL_WAIT;
            6:begin
                if(command_length!=0)error_code<=7;
                else if(is_duplicate)begin response_mode<=RM_SNAP;send_length<=13;send_event<=snap_id;end
                else if(!configured)error_code<=2;
                else if(|bank_post)error_code<=1;
                else if(!( |bank_ready))error_code<=2;
                else begin
                    snap_cache_valid<=1;snap_seq<=cmd_seq;snap_id<=next_event;snap_tick<=ticks;
                    next_event<=next_event+1'b1;response_mode<=RM_SNAP;send_length<=13;send_event<=next_event;
                end
            end
            7:begin response_mode<=RM_LIST;send_length<=196;end
            8:begin
                if(command_length!=6 || head[47:32]==0 || head[47:32]>511)error_code<=7;
                else if(!((bank_frozen[0] && bank_id[0]==command_event)||(bank_frozen[1] && bank_id[1]==command_event)))error_code<=3;
                else if(head[31:16]!=0)error_code<=4;
                else begin
                    selected_bank<=!(bank_frozen[0] && bank_id[0]==command_event);
                    read_base<=head[15:0];read_length<=head[40:32];read_index<=0;
                    read_end<={1'b0,head[15:0]}+{1'b0,head[47:32]};
                    send_length<=head[47:32]+1'b1;state<=READ_BOUNDS;
                end
            end
            9:begin
                if(command_length!=8)error_code<=7;
                else state<=ACK_WAIT;
            end
            11:begin response_mode<=RM_ECHO;send_length<=command_length;if(command_length==0)state<=SEND;end
            default:error_code<=6;
            endcase
        end
        FILL:begin
            payload_write<=1;payload_address<=fill_index[8:0];
            case(response_mode)
            RM_STATUS:payload_data<=status_latched[fill_index*8+:8];
            RM_LIST:payload_data<=list_latched[fill_index*8+:8];
            RM_SNAP:payload_data<=snap_image[fill_index*8+:8];
            RM_ECHO:payload_data<=request_data;
            RM_ENGINE:payload_data<=analysis_data;
            RM_MONITOR:payload_data<=monitor_data;
            RM_MUSIC:payload_data<=music_data;
            RM_PANEL:payload_data<=panel_reply;
            default:payload_data<=error_code;
            endcase
            if(fill_index==send_length-1)state<=SEND;
            else fill_index<=fill_index+1'b1;
        end
        SEND:if(!tx_busy)begin send_start<=1;state<=IDLE;end
        READ_BOUNDS:begin
            if(read_end>{1'b0,bank_length[selected_bank][15:0]})begin error_code<=4;send_length<=1;state<=FILL;end
            else begin payload_write<=1;payload_address<=0;payload_data<=0;state<=READ_REQ;end
        end
        READ_REQ:state<=READ_WAIT;
        READ_WAIT:if(bank_read_valid[selected_bank])begin
            payload_write<=1;payload_address<=read_index+1'b1;payload_data<=bank_data[selected_bank];
            if(read_index==read_length-1)state<=SEND;
            else begin read_index<=read_index+1'b1;state<=READ_REQ;end
        end
        ACK_WAIT:begin error_code<=(|bank_ack_ok) ? 0 : 5;state<=FILL;end
        ENGINE_WAIT:if(analysis_done)begin
            response_mode<=RM_ENGINE;send_length<=analysis_length;fill_index<=0;state<=FILL;
        end
        MON_WAIT:if(monitor_done)begin
            response_mode<=RM_MONITOR;send_length<=monitor_length;fill_index<=0;state<=FILL;
        end
        MUSIC_WAIT:if(music_done)begin
            response_mode<=RM_MUSIC;send_length<=music_length;fill_index<=0;state<=FILL;
        end
        PANEL_WAIT:if(panel_done)begin
            response_mode<=RM_PANEL;send_length<=1;fill_index<=0;state<=FILL;
        end
        default:state<=IDLE;
        endcase
        end
    end
    wire [15:0] legacy_leds=music_enabled ? music_leds : {ticks[25],5'b0,|packet_crc_errors,|framing_errors,bank_post,bank_frozen,bank_ready,id_ok,configured};
    wire [2:0] panel_rgb0,panel_rgb1;wire [7:0] panel_segments;
    assign {LED16_R,LED16_G,LED16_B}=panel_rgb0;assign {LED17_R,LED17_G,LED17_B}=panel_rgb1;
    assign {DP,CG,CF,CE,CD,CC,CB,CA}=panel_segments;
    board_panel panel(.clk(clk),.reset(reset),.ticks(ticks),.switches(sw_stable),.switches_raw(sw_raw),.legacy_leds(legacy_leds),
        .pcm_valid(pcm_valid),.pcm(pcm),.temperature_raw(adt_temperature),.temperature_valid(adt_valid && adt_configured),
        .music_enabled(music_enabled),.music_state(panel_music_state),.music_target(panel_music_target),.music_count(panel_music_count),
        .music_rate(panel_music_rate),.music_record_id(panel_music_record),.music_progress(panel_music_progress),
        .music_game(panel_music_game),.music_wake(panel_music_wake),.music_job_active(panel_music_job),.music_max_ms(panel_music_max_ms),
        .command_start(state==CLASSIFY && command==16),.command_length(command_length),.command_head(head),.command_event(command_event),
        .done(panel_done),.reply_data(panel_reply),.quiet(panel_quiet),.led(LED),.rgb0(panel_rgb0),.rgb1(panel_rgb1),.segments(panel_segments),.anodes(AN));
endmodule
