`timescale 1ns/1ps
module tb_monitor_core;
    reg clk=0,reset=1;always #5 clk=~clk;
    reg [63:0] ticks=0;always @(posedge clk)ticks<=ticks+625;
    reg pv=0,xv=0;reg signed [15:0] pcm=0,x=0,y=0,z=0;reg [63:0] xt=0;
    reg [1535:0] header=0;reg start=0;reg [7:0] cmd=0;reg [15:0] len=0;
    reg [127:0] head=0;reg [31:0] event_id=0;reg [8:0] address=0;
    wire [7:0] data;wire done;wire [15:0] length;wire [31:0] ps,xs,sid;
    monitor_core dut(clk,reset,ticks,pv,pcm,xv,xt,x,y,z,header,start,cmd,len,head,event_id,address,data,done,length,ps,xs,sid);
    reg [7:0] bytes[0:511];integer i,j,base,n;
    task feed;
        input integer first,count;integer k;
        begin for(k=first;k<first+count;k=k+1)begin
            @(negedge clk);pv=1;pcm=k-1024;
            if(k%80==0)begin xv=1;xt=ticks;x=k;y=-k;z=1000;end
            repeat(1)@(negedge clk);pv=0;xv=0;repeat(8)@(negedge clk);
        end end
    endtask
    task request;
        input [7:0] c;input [15:0] l;input [127:0] h;input [31:0] e;
        begin @(negedge clk);cmd=c;len=l;head=h;event_id=e;start=1;
            @(negedge clk);start=0;wait(done);
            for(j=0;j<length;j=j+1)begin address=j;#1;bytes[j]=data;end
            @(negedge clk);
        end
    endtask
    function [31:0] u32;input integer at;begin u32={bytes[at+3],bytes[at+2],bytes[at+1],bytes[at]};end endfunction
    function signed [15:0] s16;input integer at;begin s16={bytes[at+1],bytes[at]};end endfunction
    initial begin
        header[15:8]=1;header[32+:32]=32'h12345678;
        header[16+:8]=8'h3f;header[320+:16]=16'hff80;header[336+:8]=8'hcb;header[344+:8]=8'h80;
        header[448+:16]=16'h8000;header[464+:16]=16'h5550;header[480+:16]=16'h9990;header[496+:16]=16'h5550;
        header[512+:16]=16'hf800;header[528+:16]=16'ha5a5;header[544+:16]=16'ha5a5;
        header[560+:8]=8'h15;header[568+:8]=8'h15;header[936+:8]=15;
        for(i=0;i<5;i=i+1)begin header[608+i*32+:32]=i+1;header[768+i*32+:32]=5-i;end
        repeat(5)@(negedge clk);reset=0;feed(0,4096);
        request(12,0,0,0);
        $writememh("monitor_payload.hex",bytes,0,length-1);
        if(length!=448 || u32(4)!=32'h12345678 || u32(184)!=36)$fatal(1,"monitor layout/count");
        for(i=0;i<16;i=i+1)begin
            if(s16(192+i*16+8)!=(36+i)*80 || s16(192+i*16+10)!=-(36+i)*80)$fatal(1,"XYZ circular data %d",i);
        end
        request(13,0,0,0);
        $writememh("preview_payload.hex",bytes,0,length-1);
        if(length!=280 || u32(4)!=192 || bytes[2]!=64)$fatal(1,"preview layout");
        for(i=0;i<64;i=i+1)begin
            if(s16(24+i*4)!=(192+i)*16-1024 || s16(26+i*4)!=(192+i)*16+15-1024)$fatal(1,"min/max data %d",i);
        end
        request(14,5,0,0);
        $writememh("audio_header.hex",bytes,0,length-1);
        if(bytes[0]!=0 || u32(4)!=1)$fatal(1,"audio snapshot creation");
        feed(4096,600);
        for(base=0;base<512;base=base+240)begin
            n=512-base>240 ? 240 : 512-base;
            request(14,5,{88'b0,n[15:0],base[15:0],8'd1},1);
            if(base==0)$writememh("audio_payload.hex",bytes,0,length-1);
            if(length!=32+2*n || bytes[0]!=0)$fatal(1,"snapshot read bounds");
            for(i=0;i<n;i=i+1)if(s16(32+i*2)!=3584+base+i-1024)$fatal(1,"frozen audio changed %d",base+i);
        end
        request(14,5,{88'b0,16'd240,16'd500,8'd1},1);if(bytes[0]!=7)$fatal(1,"length not rejected");
        request(14,5,{88'b0,16'd10,16'd0,8'd1},99);if(bytes[0]!=3)$fatal(1,"wrong snapshot ID");
        request(13,1,0,0);if(length!=1 || bytes[0]!=7)$fatal(1,"invalid command length");
        $display("PASS MONITOR: coherent layouts, ring wrap, min/max, frozen 512 PCM, bounds and ID checks");$finish;
    end
    initial begin #3000000;$fatal(1,"test timeout");end
endmodule
