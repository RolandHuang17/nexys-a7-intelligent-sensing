`timescale 1ns/1ps
// Three 24-bit modulo integrators/combs, R=125. Valid input is PDM +/-1.
// PCM scaling: round_away(raw * 281475 / 2^24), saturate to signed PCM16.
module pdm_cic (
    input wire clk, reset, bit_valid, pdm_bit,
    output reg pcm_valid = 0,
    output reg signed [15:0] pcm = 0,
    output reg clipped = 0
);
    reg signed [23:0] i1=0,i2=0,i3=0,d1=0,d2=0,d3=0;
    reg [6:0] phase=0;
    wire signed [23:0] n1=i1+(pdm_bit ? 24'sd1 : -24'sd1);
    wire signed [23:0] n2=i2+i1;
    wire signed [23:0] n3=i3+i2;
    reg signed [23:0] decimated=0,c1=0,c2=0,c3=0;
    reg dec_valid=0,c1_valid=0,c2_valid=0,c3_valid=0;
    reg signed [43:0] product=0;
    reg scale_valid=0;
    // Arithmetic floor plus a one-bit correction gives symmetric nearest
    // rounding, ties away from zero, without a 44-bit abs/add/negate chain.
    wire round_up=product[43] ? product[23:0]>24'h800000 : product[23:0]>=24'h800000;
    wire signed [19:0] scaled=$signed(product[43:24])+$signed({19'b0,round_up});
    always @(posedge clk) begin
        pcm_valid<=scale_valid;
        scale_valid<=0;
        dec_valid<=0;c1_valid<=dec_valid;c2_valid<=c1_valid;c3_valid<=c2_valid;
        clipped<=0;
        if (reset) begin
            i1<=0;i2<=0;i3<=0;d1<=0;d2<=0;d3<=0;phase<=0;
            product<=0;scale_valid<=0;pcm_valid<=0;pcm<=0;
            dec_valid<=0;c1_valid<=0;c2_valid<=0;c3_valid<=0;
        end else begin
            if (bit_valid) begin
                i1<=n1;i2<=n2;i3<=n3;
                if (phase==124) begin
                    phase<=0;decimated<=n3;dec_valid<=1;
                end else phase<=phase+1'b1;
            end
            if(dec_valid)begin c1<=decimated-d1;d1<=decimated;end
            if(c1_valid)begin c2<=c1-d2;d2<=c1;end
            if(c2_valid)begin c3<=c2-d3;d3<=c2;end
            if(c3_valid)begin product<=c3*20'sd281475;scale_valid<=1;end
            if (scale_valid) begin
                if (scaled>32767) begin pcm<=32767;clipped<=1;end
                else if (scaled < -32768) begin pcm<=-32768;clipped<=1;end
                else pcm<=scaled[15:0];
            end
        end
    end
endmodule
