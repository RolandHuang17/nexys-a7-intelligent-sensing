package recorder_pkg;
    function automatic [31:0] crc32_byte(input [31:0] crc,input [7:0] data);
        reg [31:0] c;
        integer i;
        begin
            c=crc^{24'b0,data};
            for(i=0;i<8;i=i+1)c=c[0] ? (c>>1)^32'hedb88320 : c>>1;
            crc32_byte=c;
        end
    endfunction
endpackage
