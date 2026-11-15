`timescale 1ns/1ps
// Two feature buckets allow a DATA_READY sample read by SPI after a boundary
// to update its original window. Finalization waits 100 us (>32 us SPI burst).
module feature_core #(parameter integer FRAME=1000000,DRAIN=10000)(
    input wire clk,reset,input wire [63:0] time_tick,
    input wire pcm_valid,input wire signed [15:0] pcm,
    input wire xyz_valid,input wire [63:0] xyz_tick,input wire signed [15:0] x,y,z,
    output reg feature_valid=0,output reg [63:0] feature_tick=0,
    output reg [31:0] audio_feature=0,accel_feature=0,
    output reg audio_valid=0,accel_valid=0,
    output reg [15:0] audio_n=0,xyz_n=0,output reg [31:0] late_xyz=0
);
    reg [63:0] frame_start=0;
    reg current=0,pending=0;
    reg [31:0] sums[0:1];
    reg [17:0] maxima[0:1];
    reg [15:0] counts[0:1],xyz_counts[0:1],diff_counts[0:1];
    reg signed [31:0] dc_q=0;
    reg signed [15:0] previous_x=0,previous_y=0,previous_z=0;
    reg previous_valid=0;
    reg xyz_pipe1=0,xyz_pipe2=0,xyz_bank1=0,xyz_bank2=0,xyz_new1=0,xyz_new2=0;
    reg [16:0] abs_x1=0,abs_y1=0,abs_z1=0;
    reg [17:0] motion2=0;
    reg [1:0] finish_pipeline=0;
    reg [23:0] final_sum=0;
    reg [38:0] mean_product=0;
    reg [63:0] final_tick1=0,final_tick2=0;
    reg [31:0] final_accel1=0,final_accel2=0;
    reg [15:0] final_an1=0,final_an2=0,final_xn1=0,final_xn2=0;
    reg [1:0] final_flags1=0,final_flags2=0;
    wire [31:0] elapsed=time_tick[31:0]-frame_start[31:0];
    wire boundary=elapsed>=FRAME;
    wire audio_bank=boundary ? !current : current;
    // Classify against the registered start directly. Avoid the serial
    // elapsed comparison -> start mux/add -> timestamp subtraction path.
    wire signed [31:0] xyz_offset=xyz_tick[31:0]-frame_start[31:0];
    wire xyz_next=xyz_offset>=FRAME;
    wire xyz_bank=(xyz_offset<0 || xyz_next) ? !current : current;
    wire xyz_late=xyz_offset<0 && (!pending || elapsed>=DRAIN);
    wire signed [31:0] sample_ext={{16{pcm[15]}},pcm};
    wire signed [31:0] filtered=sample_ext-(dc_q>>>8);
    wire [31:0] absolute_audio=filtered<0 ? -filtered : filtered;
    // A difference of two PCM16-width axis values needs 17 signed bits;
    // three absolute differences sum to at most 196605 (18 unsigned bits).
    wire signed [16:0] dx=$signed({x[15],x})-$signed({previous_x[15],previous_x});
    wire signed [16:0] dy=$signed({y[15],y})-$signed({previous_y[15],previous_y});
    wire signed [16:0] dz=$signed({z[15],z})-$signed({previous_z[15],previous_z});
    wire [16:0] abs_dx=dx<0 ? -dx : dx,abs_dy=dy<0 ? -dy : dy,abs_dz=dz<0 ? -dz : dz;
    wire [17:0] motion1={1'b0,abs_x1}+{1'b0,abs_y1}+{1'b0,abs_z1};
    integer i;
    always @(posedge clk)begin
        feature_valid<=0;
        finish_pipeline<={finish_pipeline[0],1'b0};
        xyz_pipe1<=xyz_valid && !xyz_late && previous_valid;
        xyz_pipe2<=xyz_pipe1;
        if(reset)begin
            frame_start<=time_tick;current<=0;pending<=0;dc_q<=0;previous_valid<=0;late_xyz<=0;
            audio_valid<=0;accel_valid<=0;
            finish_pipeline<=0;
            xyz_pipe1<=0;xyz_pipe2<=0;
            for(i=0;i<2;i=i+1)begin sums[i]<=0;maxima[i]<=0;counts[i]<=0;xyz_counts[i]<=0;diff_counts[i]<=0;end
        end else begin
            if(boundary)begin
                frame_start<=frame_start+FRAME;current<=!current;pending<=1;
                sums[!current]<=0;counts[!current]<=0;maxima[!current]<=0;
                xyz_counts[!current]<=0;diff_counts[!current]<=0;
            end
            if(pcm_valid)begin
                dc_q<=dc_q+(((sample_ext<<<8)-dc_q)>>>8);
                sums[audio_bank]<=boundary ? absolute_audio : sums[audio_bank]+absolute_audio;
                counts[audio_bank]<=boundary ? 1 : counts[audio_bank]+1'b1;
            end
            if(xyz_valid)begin
                previous_x<=x;previous_y<=y;previous_z<=z;previous_valid<=1;
                if(xyz_late)late_xyz<=late_xyz+1'b1;
                else begin
                    xyz_counts[xyz_bank]<=(boundary && xyz_next) ? 1 : xyz_counts[xyz_bank]+1'b1;
                    if(previous_valid)begin
                        diff_counts[xyz_bank]<=(boundary && xyz_next) ? 1 : diff_counts[xyz_bank]+1'b1;
                    end
                end
                abs_x1<=abs_dx;abs_y1<=abs_dy;abs_z1<=abs_dz;
                xyz_bank1<=xyz_bank;xyz_new1<=boundary && xyz_next;
            end
            if(xyz_pipe1)begin
                motion2<=motion1;xyz_bank2<=xyz_bank1;xyz_new2<=xyz_new1;
            end
            if(xyz_pipe2 && (xyz_new2 || motion2>maxima[xyz_bank2]))maxima[xyz_bank2]<=motion2;
            // Close input eligibility at DRAIN, allow two clocks for motion to
            // reach the maximum register, then perform the existing mean pipe.
            if(pending && !boundary && elapsed>=DRAIN+2)begin
                pending<=0;finish_pipeline[0]<=1;final_tick1<=frame_start+DRAIN+2;
                final_sum<=sums[!current];final_accel1<=maxima[!current];
                final_flags1<={diff_counts[!current]!=0,counts[!current]==160};
                final_an1<=counts[!current];final_xn1<=xyz_counts[!current];
            end
            if(finish_pipeline[0])begin
                // floor(sum/160)=floor(floor(sum/32)/5). For a 24-bit sum,
                // floor(n/5)=(n*838861)>>22 exactly for n=sum[23:5].
                mean_product<=final_sum[23:5]*20'd838861;
                final_tick2<=final_tick1;final_accel2<=final_accel1;
                final_flags2<=final_flags1;final_an2<=final_an1;final_xn2<=final_xn1;
            end
            if(finish_pipeline[1])begin
                feature_valid<=1;feature_tick<=final_tick2+2;
                audio_feature<=mean_product>>22;accel_feature<=final_accel2;
                audio_valid<=final_flags2[0];accel_valid<=final_flags2[1];audio_n<=final_an2;xyz_n<=final_xn2;
            end
        end
    end
endmodule
