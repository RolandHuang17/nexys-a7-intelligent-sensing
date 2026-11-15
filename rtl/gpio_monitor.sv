`timescale 1ns/1ps
module gpio_monitor #(parameter integer MS_CYCLES=100000,DEBOUNCE_MS=20)(
    input wire clk,reset,input wire [15:0] switches,input wire [4:0] buttons,
    output wire [15:0] raw_switches,output wire [4:0] raw_buttons,
    output reg [15:0] stable_switches=0,output reg [4:0] stable_buttons=0,
    output reg [31:0] changes=0,
    output wire [159:0] presses,releases
);
    (* ASYNC_REG="TRUE" *) reg [20:0] sync1=0,sync2=0;
    reg [31:0] divider=0;
    reg [7:0] count[0:20];
    reg [31:0] press_count[0:4],release_count[0:4];
    wire [20:0] stable={stable_buttons,stable_switches};
    assign raw_switches=sync2[15:0];assign raw_buttons=sync2[20:16];
    genvar b;
    generate for(b=0;b<5;b=b+1)begin:COUNTS
        assign presses[b*32+:32]=press_count[b];assign releases[b*32+:32]=release_count[b];
    end endgenerate
    integer i;
    reg [5:0] changed;
    always @(posedge clk)begin
        sync1<={buttons,switches};sync2<=sync1;
        if(reset)begin
            divider<=0;stable_switches<=0;stable_buttons<=0;changes<=0;
            for(i=0;i<21;i=i+1)count[i]<=0;
            for(i=0;i<5;i=i+1)begin press_count[i]<=0;release_count[i]<=0;end
        end else if(divider==MS_CYCLES-1)begin
            divider<=0;changed=0;
            for(i=0;i<21;i=i+1)begin
                if(sync2[i]==stable[i])count[i]<=0;
                else if(count[i]==DEBOUNCE_MS-1)begin
                    count[i]<=0;changed=changed+1'b1;
                    if(i<16)stable_switches[i]<=sync2[i];
                    else begin
                        stable_buttons[i-16]<=sync2[i];
                        if(sync2[i])press_count[i-16]<=press_count[i-16]+1'b1;
                        else release_count[i-16]<=release_count[i-16]+1'b1;
                    end
                end else count[i]<=count[i]+1'b1;
            end
            changes<=changes+changed;
        end else divider<=divider+1'b1;
    end
endmodule
