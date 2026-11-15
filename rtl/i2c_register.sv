`timescale 1ns/1ps
// One register write or repeated-START register read. Both bus lines are open drain.
module i2c_register #(parameter integer QUARTER=250,TIMEOUT=2000000)(
    input wire clk,reset,start,read_operation,read_two,
    input wire [6:0] device_address,input wire [7:0] register_address,write_value,
    inout wire scl,sda,output reg busy=0,done=0,error=0,output reg [15:0] data=0
);
    reg scl_low=0,sda_low=0;
    assign scl=scl_low ? 1'b0 : 1'bz;assign sda=sda_low ? 1'b0 : 1'bz;
    (* ASYNC_REG="TRUE" *) reg [1:0] scl_sync=3,sda_sync=3;
    localparam IDLE=0,START_A=1,START_B=2,START_C=3,START_D=4,BITS=5,ACK=6,STOP_A=7,STOP_B=8,STOP_C=9;
    reg [3:0] state=0,stage=0;reg [1:0] phase=0;reg [2:0] bit_index=7;
    reg [31:0] timer=0,watchdog=0;
    reg [7:0] tx=0,rx=0,reg_addr=0,wr=0;reg [6:0] dev=0;
    reg op_read=0,two=0,receiving=0;
    wire stretching=(state==START_B || state==STOP_B || ((state==BITS || state==ACK)&&phase==1))&&!scl_sync[1];
    always @(posedge clk)begin
        scl_sync<={scl_sync[0],scl};sda_sync<={sda_sync[0],sda};done<=0;
        if(reset)begin state<=IDLE;busy<=0;scl_low<=0;sda_low<=0;timer<=0;watchdog<=0;error<=0;end
        else if(state==IDLE)begin
            scl_low<=0;sda_low<=0;
            if(start)begin
                busy<=1;error<=0;data<=0;dev<=device_address;reg_addr<=register_address;wr<=write_value;
                op_read<=read_operation;two<=read_two;stage<=0;tx<={device_address,1'b0};receiving<=0;
                state<=START_A;timer<=0;watchdog<=0;phase<=0;bit_index<=7;
            end
        end else if(watchdog==TIMEOUT-1)begin
            error<=1;done<=1;busy<=0;state<=IDLE;scl_low<=0;sda_low<=0;
        end else begin
            watchdog<=watchdog+1'b1;
            // State outputs settle for a full quarter period before the next transition.
            case(state)
                START_A:begin scl_low<=1;sda_low<=0;end
                START_B:begin scl_low<=0;sda_low<=0;end
                START_C:begin scl_low<=0;sda_low<=1;end
                START_D:begin scl_low<=1;sda_low<=1;end
                BITS:case(phase)
                    0:begin scl_low<=1;sda_low<=receiving ? 1'b0 : !tx[bit_index];end
                    1,2:begin scl_low<=0;end
                    3:begin scl_low<=1;end
                endcase
                ACK:case(phase)
                    0:begin scl_low<=1;sda_low<=receiving && stage==3 && two;end
                    1,2:begin scl_low<=0;end
                    3:begin scl_low<=1;end
                endcase
                STOP_A:begin scl_low<=1;sda_low<=1;end
                STOP_B:begin scl_low<=0;sda_low<=1;end
                STOP_C:begin scl_low<=0;sda_low<=0;end
            endcase
            if(stretching)timer<=0;
            else if(timer!=QUARTER-1)timer<=timer+1'b1;
            else begin
                timer<=0;
                case(state)
                    START_A:state<=START_B;
                    START_B:state<=START_C;
                    START_C:state<=START_D;
                    START_D:begin state<=BITS;phase<=0;bit_index<=7;end
                    BITS:begin
                        if(phase==2 && receiving)rx[bit_index]<=sda_sync[1];
                        if(phase==3)begin
                            phase<=0;
                            if(bit_index==0)state<=ACK;else bit_index<=bit_index-1'b1;
                        end else phase<=phase+1'b1;
                    end
                    ACK:begin
                        if(phase==2 && !receiving && sda_sync[1])error<=1;
                        if(phase!=3)phase<=phase+1'b1;
                        else begin
                            phase<=0;bit_index<=7;
                            if(error)state<=STOP_A;
                            else case(stage)
                                0:begin stage<=1;tx<=reg_addr;state<=BITS;end
                                1:if(op_read)begin stage<=2;tx<={dev,1'b1};state<=START_A;end
                                  else begin stage<=2;tx<=wr;state<=BITS;end
                                2:if(op_read)begin stage<=3;receiving<=1;state<=BITS;end
                                  else state<=STOP_A;
                                3:begin
                                    if(two)begin data[15:8]<=rx;stage<=4;state<=BITS;end
                                    else begin data<={8'b0,rx};state<=STOP_A;end
                                end
                                4:begin data[7:0]<=rx;state<=STOP_A;end
                            endcase
                        end
                    end
                    STOP_A:state<=STOP_B;
                    STOP_B:state<=STOP_C;
                    STOP_C:begin state<=IDLE;busy<=0;done<=1;end
                endcase
            end
        end
    end
endmodule
