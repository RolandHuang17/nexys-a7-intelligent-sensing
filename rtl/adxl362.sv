`timescale 1ns/1ps
module adxl362(
    input wire clk,reset,input wire [63:0] ticks,
    input wire miso,int1,output wire cs_n,sclk,mosi,
    output reg configured=0,id_ok=0,xyz_valid=0,
    output reg signed [15:0] x=0,y=0,z=0,
    output reg [63:0] xyz_tick=0,
    output reg [31:0] identity=0,readback=0,overruns=0,rail_count=0,
    output reg signed [15:0] temperature=0,output reg temperature_valid=0,
    output reg [63:0] temperature_tick=0
);
    reg start=0;
    reg [79:0] command=0;
    reg [3:0] bytes=0;
    wire busy,done;
    wire [79:0] received;
    spi_master spi(clk,reset,start,command,bytes,miso,cs_n,sclk,mosi,busy,done,received);
    (* ASYNC_REG="TRUE" *) reg [1:0] irq_sync=0;
    reg irq_previous=0;
    reg [4:0] state=0;
    reg [31:0] wait_count=0;
    reg pending=0;
    reg [63:0] pending_tick=0;
    wire irq_rise=irq_sync[1]&&!irq_previous;
    wire signed [15:0] next_x={{4{received[35]}},received[35:32],received[47:40]};
    wire signed [15:0] next_y={{4{received[19]}},received[19:16],received[31:24]};
    wire signed [15:0] next_z={{4{received[3]}},received[3:0],received[15:8]};
    always @(posedge clk)begin
        irq_sync<={irq_sync[0],int1};irq_previous<=irq_sync[1];start<=0;xyz_valid<=0;
        if(reset)begin
            state<=0;wait_count<=0;configured<=0;id_ok<=0;pending<=0;overruns<=0;
            identity<=0;readback<=0;rail_count<=0;temperature_valid<=0;
        end else begin
            if(configured && irq_rise)begin
                if(pending || state!=14)overruns<=overruns+1'b1;
                else begin pending<=1;pending_tick<=ticks;end
            end
            case(state)
            0:if(wait_count==1000000)begin wait_count<=0;state<=1;end else wait_count<=wait_count+1'b1;
            1:begin command<={24'h0a1f52,56'b0};bytes<=3;start<=1;state<=2;end
            2:if(done)begin wait_count<=0;state<=3;end
            3:if(wait_count==1000000)state<=4;else wait_count<=wait_count+1'b1;
            4:begin command<={16'h0b00,64'b0};bytes<=6;start<=1;state<=5;end
            5:if(done)begin
                identity<=received[31:0];id_ok<=received[31:8]==24'had1df2;
                state<=received[31:8]==24'had1df2 ? 6 : 20;
            end
            6:begin command<={24'h0a2c04,56'b0};bytes<=3;start<=1;state<=7;end
            7:if(done)state<=8;
            8:begin command<={24'h0a2a01,56'b0};bytes<=3;start<=1;state<=9;end
            9:if(done)state<=10;
            10:begin command<={24'h0a2d02,56'b0};bytes<=3;start<=1;state<=11;end
            11:if(done)state<=12;
            12:begin command<={16'h0b2a,64'b0};bytes<=6;start<=1;state<=13;end
            13:if(done)begin
                readback<=received[31:0];configured<=received[31:0]==32'h01000402;
                state<=received[31:0]==32'h01000402 ? 14 : 20;
            end
            14:if(pending)begin
                command<={16'h0b0e,64'b0};bytes<=8;start<=1;state<=15;
                xyz_tick<=pending_tick;pending<=0;
            end
            15:if(done)begin
                x<=next_x;y<=next_y;z<=next_z;xyz_valid<=1;state<=16;
                if(next_x==2047 || next_x==-2048 || next_y==2047 || next_y==-2048 || next_z==2047 || next_z==-2048)
                    rail_count<=rail_count+1'b1;
            end
            16:begin command<={16'h0b14,64'b0};bytes<=4;start<=1;state<=17;end
            17:if(done)begin
                temperature<={{4{received[3]}},received[3:0],received[15:8]};
                temperature_valid<=1;temperature_tick<=ticks;state<=14;
            end
            20:begin configured<=0;end
            default:state<=0;
            endcase
        end
    end
endmodule
