`timescale 1ns/1ps
module packet_link #(parameter integer BAUD_DIV=217)(
    input wire clk,reset,uart_rx_i,output wire uart_tx_o,
    output reg request_valid=0,input wire request_accept,
    output reg [7:0] request_command=0,
    output reg [15:0] request_seq=0,request_length=0,
    output reg [31:0] request_event=0,
    output reg [127:0] request_head=0,
    input wire [8:0] request_address,output wire [7:0] request_data,
    input wire payload_write,input wire [8:0] payload_address,input wire [7:0] payload_data,
    input wire send_start,input wire [7:0] send_command,input wire [15:0] send_seq,send_length,
    input wire [31:0] send_event,output wire tx_busy,
    output reg [31:0] crc_errors=0,length_errors=0,
    output wire [31:0] framing_errors
);
    import recorder_pkg::*;
    wire byte_valid;wire [7:0] rx_byte;
    uart_rx #(.DIV(BAUD_DIV)) receiver(clk,reset,uart_rx_i,byte_valid,rx_byte,framing_errors);
    reg [7:0] rx_mem[0:511],tx_mem[0:511];
    assign request_data=rx_mem[request_address];
    reg [2:0] rx_state=0;
    reg [9:0] rx_index=0;
    reg [31:0] rx_crc=32'hffffffff,rx_check=0;
    reg [7:0] rx_version=0;
    always @(posedge clk)begin
        if(payload_write)tx_mem[payload_address]<=payload_data;
        if(request_accept)request_valid<=0;
        if(reset)begin rx_state<=0;request_valid<=0;crc_errors<=0;length_errors<=0;end
        else if(byte_valid)begin
            case(rx_state)
            0:if(rx_byte==8'ha5)rx_state<=1;
            1:begin
                if(rx_byte==8'h5a)begin rx_state<=2;rx_index<=0;rx_crc<=32'hffffffff;request_head<=0;end
                else rx_state<=rx_byte==8'ha5 ? 1 : 0;
            end
            2:begin
                rx_crc<=crc32_byte(rx_crc,rx_byte);rx_index<=rx_index+1'b1;
                case(rx_index)
                0:rx_version<=rx_byte;
                1:request_command<=rx_byte;
                2:request_seq[7:0]<=rx_byte;
                3:request_seq[15:8]<=rx_byte;
                4:request_event[7:0]<=rx_byte;
                5:request_event[15:8]<=rx_byte;
                6:request_event[23:16]<=rx_byte;
                7:request_event[31:24]<=rx_byte;
                8:request_length[7:0]<=rx_byte;
                9:begin
                    request_length[15:8]<=rx_byte;rx_index<=0;
                    if({rx_byte,request_length[7:0]}>512 || rx_version!=1)begin
                        rx_state<=0;length_errors<=length_errors+1'b1;
                    end else rx_state<={rx_byte,request_length[7:0]}==0 ? 4 : 3;
                end
                endcase
            end
            3:begin
                rx_mem[rx_index[8:0]]<=rx_byte;
                if(rx_index<16)request_head[rx_index*8+:8]<=rx_byte;
                rx_crc<=crc32_byte(rx_crc,rx_byte);rx_index<=rx_index+1'b1;
                if(rx_index==request_length-1)begin rx_state<=4;rx_index<=0;end
            end
            4:begin
                rx_check[rx_index*8+:8]<=rx_byte;rx_index<=rx_index+1'b1;
                if(rx_index==3)begin
                    if({rx_byte,rx_check[23:0]}==~rx_crc)request_valid<=1;
                    else crc_errors<=crc_errors+1'b1;
                    rx_state<=0;
                end
            end
            default:rx_state<=0;
            endcase
        end
    end
    reg active=0;
    reg [9:0] tx_index=0;
    reg [7:0] command=0;
    reg [15:0] seq=0,length=0;
    reg [31:0] event_number=0,tx_crc=32'hffffffff;
    reg [7:0] tx_byte;
    wire uart_ready;
    assign tx_busy=active || !uart_ready;
    wire [31:0] final_crc=~tx_crc;
    always @*begin
        case(tx_index)
        0:tx_byte=8'ha5;1:tx_byte=8'h5a;2:tx_byte=1;3:tx_byte=command;
        4:tx_byte=seq[7:0];5:tx_byte=seq[15:8];
        6:tx_byte=event_number[7:0];7:tx_byte=event_number[15:8];
        8:tx_byte=event_number[23:16];9:tx_byte=event_number[31:24];
        10:tx_byte=length[7:0];11:tx_byte=length[15:8];
        default:begin
            if(tx_index<12+length)tx_byte=tx_mem[tx_index-12];
            else tx_byte=final_crc[(tx_index-12-length)*8+:8];
        end
        endcase
    end
    uart_tx #(.DIV(BAUD_DIV)) transmitter(clk,reset,active,tx_byte,uart_ready,uart_tx_o);
    always @(posedge clk)begin
        if(reset)begin active<=0;tx_index<=0;end
        else if(send_start && !tx_busy)begin
            active<=1;tx_index<=0;command<=send_command;seq<=send_seq;
            length<=send_length;event_number<=send_event;tx_crc<=32'hffffffff;
        end else if(active && uart_ready)begin
            if(tx_index>=2 && tx_index<12+length)tx_crc<=crc32_byte(tx_crc,tx_byte);
            if(tx_index==15+length)active<=0;
            else tx_index<=tx_index+1'b1;
        end
    end
endmodule
