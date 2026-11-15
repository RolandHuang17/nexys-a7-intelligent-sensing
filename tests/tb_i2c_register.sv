`timescale 1ns/1ps
module tb_i2c_register;
    reg clk=0,reset=1,start=0,rd=1,two=0;always #5 clk=~clk;
    reg [7:0] regaddr=0,wr=0;tri1 scl,sda;
    reg slave_low=0,stretch=0;
    assign sda=slave_low ? 1'b0 : 1'bz;assign scl=stretch ? 1'b0 : 1'bz;
    wire busy,done,error;wire [15:0] result;
    i2c_register #(.QUARTER(8),.TIMEOUT(10000)) dut(clk,reset,start,rd,two,7'h4b,regaddr,wr,scl,sda,busy,done,error,result);
    task start_condition;begin
        @(negedge sda);while(scl!==1'b1)@(negedge sda);
    end endtask
    task stop_condition;begin
        @(posedge sda);while(scl!==1'b1)@(posedge sda);
    end endtask
    task receive;
        input [7:0] expected;input acknowledge,clock_stretch;
        reg [7:0] v;integer j;
        begin
            for(j=7;j>=0;j=j-1)begin @(posedge scl);v[j]=sda;end
            if(v!==expected)$fatal(1,"I2C byte got %h expected %h",v,expected);
            @(negedge scl);slave_low=acknowledge;
            if(clock_stretch)begin stretch=1;repeat(30)@(negedge clk);stretch=0;end
            @(posedge scl);@(negedge scl);slave_low=0;
        end
    endtask
    task transmit;
        input [7:0] value;input expected_ack;integer j;
        begin
            for(j=7;j>=0;j=j-1)begin slave_low=!value[j];@(posedge scl);@(negedge scl);end
            slave_low=0;@(posedge scl);
            if(sda!==!expected_ack)$fatal(1,"master ACK/NACK mismatch");
            @(negedge scl);
        end
    endtask
    task request;
        input read_flag,two_flag;input [7:0] register_value,write_byte;
        begin @(negedge clk);rd=read_flag;two=two_flag;regaddr=register_value;wr=write_byte;start=1;
            @(negedge clk);start=0;wait(done);@(negedge clk);end
    endtask
    initial begin
        repeat(6)@(negedge clk);reset=0;
        fork
            begin start_condition;receive(8'h96,1,0);receive(8'h0b,1,1);
                start_condition;receive(8'h97,1,0);transmit(8'hcb,0);stop_condition;end
            request(1,0,8'h0b,0);
        join
        if(error || result!=16'h00cb)$fatal(1,"identity read");
        fork
            begin start_condition;receive(8'h96,1,0);receive(8'h03,1,0);receive(8'h80,1,0);stop_condition;end
            request(0,0,3,8'h80);
        join
        if(error)$fatal(1,"configuration write");
        fork
            begin start_condition;receive(8'h96,1,0);receive(0,1,0);start_condition;
                receive(8'h97,1,0);transmit(8'h0c,1);transmit(8'h80,0);stop_condition;end
            request(1,1,0,0);
        join
        if(error || result!=16'h0c80)$fatal(1,"positive temperature");
        fork
            begin start_condition;receive(8'h96,1,0);receive(0,1,0);start_condition;
                receive(8'h97,1,0);transmit(8'hff,1);transmit(8'h80,0);stop_condition;end
            request(1,1,0,0);
        join
        if(error || $signed(result)!=-128)$fatal(1,"negative temperature");
        fork
            begin start_condition;receive(8'h96,0,0);stop_condition;end
            request(1,0,8'h0b,0);
        join
        if(!error)$fatal(1,"NACK not rejected");
        @(negedge clk);stretch=1;
        request(1,0,8'h0b,0);
        if(!error)$fatal(1,"stuck clock not rejected");
        stretch=0;
        $display("PASS I2C: ID/config, repeated START, positive/negative data, ACK/NACK, clock stretch, timeout");$finish;
    end
    initial begin #2000000;$fatal(1,"test timeout");end
endmodule
