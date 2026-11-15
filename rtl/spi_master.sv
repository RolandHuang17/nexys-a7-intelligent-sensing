`timescale 1ns/1ps
// Mode 0, 2 MHz at 100 MHz; MSB first; tx_data is left aligned.
module spi_master #(parameter integer HALF_DIV=25)(
    input wire clk,reset,start,input wire [79:0] tx_data,input wire [3:0] byte_count,
    input wire miso,output reg cs_n=1,sclk=0,mosi=0,
    output reg busy=0,done=0,output reg [79:0] rx_data=0
);
    reg [79:0] shift=0;
    reg [6:0] remaining=0;
    reg [7:0] divider=0;
    (* ASYNC_REG="TRUE" *) reg [1:0] sync=0;
    always @(posedge clk) begin
        sync<={sync[0],miso};done<=0;
        if(reset)begin cs_n<=1;sclk<=0;mosi<=0;busy<=0;divider<=0;end
        else if(!busy)begin
            if(start)begin
                busy<=1;cs_n<=0;sclk<=0;mosi<=tx_data[79];shift<=tx_data;
                rx_data<=0;remaining<={byte_count,3'b000};divider<=HALF_DIV-1;
            end
        end else if(divider!=0)divider<=divider-1'b1;
        else begin
            divider<=HALF_DIV-1;sclk<=!sclk;
            if(!sclk) rx_data<={rx_data[78:0],sync[1]};
            else if(remaining==1)begin
                busy<=0;done<=1;cs_n<=1;sclk<=0;mosi<=0;
            end else begin
                remaining<=remaining-1'b1;shift<={shift[78:0],1'b0};mosi<=shift[78];
            end
        end
    end
endmodule
