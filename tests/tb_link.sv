`timescale 1ns/1ps
module tb_link;
    reg clk=0,reset=1,rx=1,accept=0,wr=0,start=0;
    wire tx,req_valid,busy;
    wire [7:0] cmd,req_data;
    wire [15:0] seq,len;
    wire [31:0] event_id,crc_errors,length_errors,framing_errors;
    wire [127:0] head;
    reg [8:0] addr=0,wraddr=0;
    reg [7:0] wrdata=0,outcmd=0;
    reg [15:0] outseq=0,outlen=0;
    reg [31:0] outevent=0;
    reg [7:0] input_bytes[0:1071],expected[0:543];
    wire observed_valid;wire [7:0] observed;
    wire [31:0] monitor_errors;
    integer state=0,index=0,n,k,received=0,requests=0;
    always #5 clk=~clk;
    packet_link #(.BAUD_DIV(8)) link(clk,reset,rx,tx,req_valid,accept,cmd,seq,len,event_id,head,
        addr,req_data,wr,wraddr,wrdata,start,outcmd,outseq,outlen,outevent,busy,crc_errors,length_errors,framing_errors);
    uart_rx #(.DIV(8)) monitor(clk,reset,tx,observed_valid,observed,monitor_errors);
    always @(negedge clk)begin
        accept=0;wr=0;start=0;
        if(!reset)case(state)
        0:if(req_valid && !busy)begin
            accept=1;outcmd=cmd|8'h80;outseq=seq;outlen=len;outevent=event_id;
            requests=requests+1;addr=0;index=0;state=len==0 ? 2 : 1;
        end
        1:begin
            wr=1;wraddr=index;wrdata=req_data;
            if(index==outlen-1)state=2;
            else begin index=index+1;addr=index;end
        end
        2:if(!busy)begin start=1;state=0;end
        endcase
        if(observed_valid)begin
            if(observed!==expected[received])$fatal(1,"wire mismatch byte=%0d got=%02x expected=%02x",received,observed,expected[received]);
            received=received+1;
        end
    end
    initial begin
        $readmemh("link_input.hex",input_bytes);$readmemh("link_expected.hex",expected);
        repeat(5)@(negedge clk);reset=0;
        for(n=0;n<1072;n=n+1)begin
            rx=0;repeat(8)@(negedge clk);
            for(k=0;k<8;k=k+1)begin rx=input_bytes[n][k];repeat(8)@(negedge clk);end
            rx=1;repeat(8)@(negedge clk);
        end
        wait(received==544);repeat(30)@(negedge clk);
        if(requests!=2 || crc_errors!=1 || framing_errors!=0 || monitor_errors!=0)$fatal(1,"link counters mismatch requests=%0d crc=%0d framing=%0d monitor=%0d",requests,crc_errors,framing_errors,monitor_errors);
        $display("PASS LINK 512-byte golden frame, empty frame, bad CRC resynchronization");$finish;
    end
    initial begin #5000000;$fatal(1,"timeout");end
endmodule
