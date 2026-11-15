`timescale 1ns/1ps
module tb_bank;
    parameter [63:0] BASE=0, LAG=0;
    reg clk=0,reset=1,capture=0,ack=0,read_en=0;
    reg [63:0] ticks=0,pcm_index=0;
    wire [63:0] relative_tick=ticks-BASE;
    wire pcm_valid=relative_tick%6==0;
    wire xyz_valid=relative_tick%30==0;
    wire signed [15:0] pcm=pcm_index[15:0],x=relative_tick[15:0],y=-$signed(relative_tick[15:0]),z=1000;
    reg [31:0] ack_crc=0,ack_len=0,offset=0;
    wire read_valid,ready,frozen,post_active,ack_ok;
    wire [7:0] data;
    wire [31:0] id,crc,nxyz,length,wraps;
    wire [63:0] anchor,first_index,first_tick;
    integer f,i;
    always @(posedge clk)begin
        #1;
        if(!reset && post_active!==(bank.state==1 && (ticks[31:0]-anchor[31:0])<96))
            $fatal(1,"registered busy boundary changed");
    end
    always #5 clk=~clk;
    always @(posedge clk)if(reset)begin ticks<=BASE;pcm_index<=0;end
        else begin ticks<=ticks+1;if(pcm_valid)pcm_index<=pcm_index+1;end
    record_bank #(.PRE_SAMPLES(8),.POST_SAMPLES(16),.XYZ_DEPTH(8),
        .PRE_TICKS(48),.POST_TICKS(96),.PCM_PERIOD(6),.DRAIN_TICKS(6)) bank(
        clk,reset,ticks,pcm_valid,pcm,pcm_index,xyz_valid,x,y,z,ticks,
        capture,32'd123,ticks-LAG,ack,32'd123,ack_len,ack_crc,read_en,offset,
        read_valid,data,ready,frozen,post_active,ack_ok,id,crc,nxyz,anchor,first_index,first_tick,length,wraps);
    initial begin
        repeat(4)@(negedge clk);reset=0;
        wait(relative_tick==20);@(negedge clk);capture=1;@(negedge clk);capture=0;
        if(id!=0)$fatal(1,"captured before prehistory ready");
        wait(relative_tick==200);@(negedge clk);capture=1;@(negedge clk);capture=0;
        wait(frozen);@(negedge clk);
        $display("BANK_META %0d %0d %0d %0d %0d %0d %08x",id,anchor,first_index,first_tick,nxyz,length,crc);
        if(wraps==0)$fatal(1,"wrap was not exercised");
        f=$fopen("bank_payload.bin","wb");
        for(i=0;i<length;i=i+1)begin
            offset=i;read_en=1;@(negedge clk);read_en=0;
            wait(read_valid);@(negedge clk);$fwrite(f,"%c",data);@(negedge clk);
        end
        $fclose(f);
        ack_len=length;ack_crc=crc^1;ack=1;@(negedge clk);ack=0;
        if(!frozen || ack_ok)$fatal(1,"bad CRC released bank");
        ack_crc=crc;ack=1;@(negedge clk);ack=0;
        if(frozen || !ack_ok)$fatal(1,"valid ACK did not release");
        @(negedge clk);ack=1;@(negedge clk);ack=0;
        if(!ack_ok)$fatal(1,"duplicate ACK not idempotent");
        if(ready)$fatal(1,"released bank immediately ready");
        wait(ready);$display("PASS BANK prehistory/wrap/freeze/CRC/bad ACK/duplicate ACK/rearm");$finish;
    end
    initial begin #1000000;$fatal(1,"timeout");end
endmodule
