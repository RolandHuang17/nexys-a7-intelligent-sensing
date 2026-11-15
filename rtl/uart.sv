`timescale 1ns/1ps
module uart_rx #(parameter integer DIV=217)(
    input wire clk,reset,rx,
    output reg valid=0, output reg [7:0] data=0,
    output reg [31:0] framing_errors=0
);
    (* ASYNC_REG="TRUE" *) reg [1:0] sync=2'b11;
    reg [15:0] timer=0;
    reg [3:0] state=0;
    reg [7:0] shift=0;
    always @(posedge clk) begin
        sync<={sync[0],rx};valid<=0;
        if(reset) begin state<=0;timer<=0;framing_errors<=0;end
        else if(state==0) begin
            if(!sync[1]) begin state<=1;timer<=DIV/2-1;end
        end else if(timer!=0) timer<=timer-1'b1;
        else begin
            timer<=DIV-1;
            if(state==1) begin
                if(!sync[1])state<=2;else state<=0;
            end else if(state<=9) begin
                shift[state-2]<=sync[1];state<=state+1'b1;
            end else begin
                state<=0;
                if(sync[1])begin data<=shift;valid<=1;end
                else framing_errors<=framing_errors+1'b1;
            end
        end
    end
endmodule

module uart_tx #(parameter integer DIV=217)(
    input wire clk,reset,valid,input wire [7:0] data,
    output wire ready,output wire tx
);
    reg [9:0] shift=10'h3ff;
    reg [15:0] timer=0;
    reg [3:0] bits_left=0;
    assign ready=bits_left==0;
    assign tx=shift[0];
    always @(posedge clk) begin
        if(reset)begin shift<=10'h3ff;timer<=0;bits_left<=0;end
        else if(bits_left==0)begin
            if(valid)begin shift<={1'b1,data,1'b0};bits_left<=10;timer<=DIV-1;end
        end else if(timer!=0) timer<=timer-1'b1;
        else begin
            shift<={1'b1,shift[9:1]};bits_left<=bits_left-1'b1;timer<=DIV-1;
        end
    end
endmodule
