`timescale 1ns/1ps
module adt7420(
    input wire clk,reset,input wire [63:0] ticks,inout wire scl,sda,
    output reg configured=0,valid=0,output reg signed [15:0] temperature=0,
    output reg [7:0] identity=0,configuration=0,output reg [63:0] sample_tick=0,
    output reg [31:0] samples=0,errors=0
);
    reg start=0,rd=1,two=0;reg [7:0] address=0,value=0;
    wire busy,done,error;wire [15:0] data;
    i2c_register bus(clk,reset,start,rd,two,7'h4b,address,value,scl,sda,busy,done,error,data);
    reg [3:0] state=0;reg [31:0] wait_count=0;
    always @(posedge clk)begin
        start<=0;
        if(reset)begin state<=0;wait_count<=0;configured<=0;valid<=0;samples<=0;errors<=0;end
        else if(done && error)begin errors<=errors+1'b1;configured<=0;state<=8;wait_count<=0;end
        else case(state)
            0:if(wait_count==1000000)begin wait_count<=0;state<=1;end else wait_count<=wait_count+1'b1;
            1:begin rd<=1;two<=0;address<=8'h0b;start<=1;state<=2;end
            2:if(done)begin
                identity<=data[7:0];state<=data[7:3]==5'b11001 ? 3 : 8;wait_count<=0;
                if(data[7:3]!=5'b11001)errors<=errors+1'b1;
            end
            3:begin rd<=0;address<=3;value<=8'h80;start<=1;state<=4;end
            4:if(done)begin rd<=1;two<=0;address<=3;start<=1;state<=5;end
            5:if(done)begin
                configuration<=data[7:0];configured<=data[7:0]==8'h80;
                state<=data[7:0]==8'h80 ? 6 : 8;wait_count<=0;
                if(data[7:0]!=8'h80)errors<=errors+1'b1;
            end
            6:if(wait_count==30000000)begin rd<=1;two<=1;address<=0;start<=1;wait_count<=0;state<=7;end
              else wait_count<=wait_count+1'b1;
            7:if(done)begin temperature<=data;sample_tick<=ticks;samples<=samples+1'b1;valid<=1;state<=6;end
            8:if(wait_count==100000000)begin wait_count<=0;state<=1;end else wait_count<=wait_count+1'b1;
        endcase
    end
endmodule
