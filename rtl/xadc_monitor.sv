`timescale 1ns/1ps
module xadc_monitor(
    input wire clk,reset,input wire [63:0] ticks,
    output reg [15:0] temperature=0,vccint=0,vccaux=0,vccbram=0,
    output reg [3:0] valid=0,output reg [63:0] sample_tick=0,
    output reg [31:0] samples=0
);
    wire [15:0] data;wire ready,eoc;wire [4:0] channel;
    reg enable=0;reg [6:0] address=0;
    // UG480 continuous sequencer, internal channels only, average 16 conversions.
    // DCLK=100MHz, ADC clock=12.5MHz. Alarms are implemented in the host UI.
    XADC #(.INIT_40(16'h9000),.INIT_41(16'h2ff0),.INIT_42(16'h0800),
        .INIT_48(16'h4701),.INIT_49(16'h0000),.INIT_4A(16'h4700),
        .INIT_4B(16'h0000),.INIT_4C(16'h0000),.INIT_4D(16'h0000),
        .INIT_4E(16'h0000),.INIT_4F(16'h0000),.SIM_DEVICE("7SERIES")) adc(
        .DCLK(clk),.RESET(reset),.DADDR(address),.DEN(enable),.DI(16'b0),.DWE(1'b0),
        .DO(data),.DRDY(ready),.EOC(eoc),.CHANNEL(channel),.EOS(),.ALM(),.OT(),
        .BUSY(),.JTAGBUSY(),.JTAGLOCKED(),.JTAGMODIFIED(),.MUXADDR(),
        .CONVST(1'b0),.CONVSTCLK(1'b0),.VP(1'b0),.VN(1'b0),.VAUXP(16'b0),.VAUXN(16'b0));
    always @(posedge clk)begin
        enable<=eoc;
        if(eoc)address<={2'b0,channel};
        if(reset)begin valid<=0;samples<=0;enable<=0;end
        else if(ready)case(address)
            0:begin temperature<=data;valid[0]<=1;end
            1:begin vccint<=data;valid[1]<=1;end
            2:begin vccaux<=data;valid[2]<=1;end
            6:begin vccbram<=data;valid[3]<=1;sample_tick<=ticks;samples<=samples+1'b1;end
        endcase
    end
endmodule
