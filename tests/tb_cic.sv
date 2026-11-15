`timescale 1ns/1ps
module tb_cic;
    reg clk=0,reset=1,bit_valid=0,pdm_bit=0;
    wire valid,clipped;
    wire signed [15:0] pcm;
    reg [0:0] bits[0:49999];
    reg [15:0] expected[0:399];
    integer n=0, outputs=0;
    always #5 clk=~clk;
    pdm_cic dut(clk,reset,bit_valid,pdm_bit,valid,pcm,clipped);
    initial begin
        $readmemh("pdm_bits.hex",bits);
        $readmemh("pcm_expected.hex",expected);
        repeat(4) @(negedge clk);reset=0;
        for(n=0;n<50000;n=n+1) begin
            pdm_bit=bits[n];bit_valid=1;
            @(negedge clk);bit_valid=0;
            repeat(2) @(negedge clk);
        end
        repeat(5) @(negedge clk);
        if(outputs!=400)$fatal(1,"output count %0d",outputs);
        $display("PASS CIC 50000 PDM bits / 400 bit-exact PCM samples");
        $finish;
    end
    always @(negedge clk) if(valid && !reset) begin
        if(pcm!==expected[outputs])$fatal(1,"PCM mismatch index=%0d actual=%0d expected=%0d",outputs,pcm,$signed(expected[outputs]));
        outputs=outputs+1;
    end
    initial begin #5000000;$fatal(1,"timeout");end
endmodule
