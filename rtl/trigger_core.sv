`timescale 1ns/1ps
module trigger_core(
    input wire clk,reset,feature_valid,input wire [63:0] feature_tick,
    input wire audio_valid,accel_valid,input wire [31:0] audio_feature,accel_feature,
    input wire [31:0] audio_threshold,accel_threshold,window_ticks,
    output reg result_valid=0,audio_cross=0,accel_cross=0,joint_pair=0,joint_confirm=0,deduplicated=0,
    output reg [63:0] t_audio=0,t_accel=0,t_confirm=0
);
    reg previous_audio_valid=0,previous_accel_valid=0;
    reg [31:0] previous_audio=0,previous_accel=0;
    reg pending_audio=0,pending_accel=0,dedup_active=0;
    reg [63:0] audio_time=0,accel_time=0,last_confirm=0;
    wire ax=audio_valid && previous_audio_valid && previous_audio<=audio_threshold && audio_feature>audio_threshold;
    wire vx=accel_valid && previous_accel_valid && previous_accel<=accel_threshold && accel_feature>accel_threshold;
    wire [31:0] audio_age=feature_tick[31:0]-audio_time[31:0];
    wire [31:0] accel_age=feature_tick[31:0]-accel_time[31:0];
    wire av=ax || (pending_audio && audio_age<=window_ticks);
    wire vv=vx || (pending_accel && accel_age<=window_ticks);
    wire [63:0] at=ax ? feature_tick : audio_time;
    wire [63:0] vt=vx ? feature_tick : accel_time;
    wire [31:0] dedup_age=feature_tick[31:0]-last_confirm[31:0];
    always @(posedge clk)begin
        result_valid<=feature_valid;audio_cross<=0;accel_cross<=0;
        joint_pair<=0;joint_confirm<=0;deduplicated<=0;
        if(reset)begin
            result_valid<=0;previous_audio_valid<=0;previous_accel_valid<=0;
            pending_audio<=0;pending_accel<=0;dedup_active<=0;
        end else if(feature_valid)begin
            if(audio_valid)begin previous_audio<=audio_feature;previous_audio_valid<=1;end
            if(accel_valid)begin previous_accel<=accel_feature;previous_accel_valid<=1;end
            if(dedup_active && dedup_age>=30000000)dedup_active<=0;
            audio_cross<=ax;accel_cross<=vx;
            pending_audio<=av;pending_accel<=vv;audio_time<=at;accel_time<=vt;
            if(av && vv)begin
                pending_audio<=0;pending_accel<=0;joint_pair<=1;
                t_audio<=at;t_accel<=vt;t_confirm<=feature_tick;
                if(dedup_active && dedup_age<30000000)deduplicated<=1;
                else begin joint_confirm<=1;dedup_active<=1;last_confirm<=feature_tick;end
            end
        end
    end
endmodule
