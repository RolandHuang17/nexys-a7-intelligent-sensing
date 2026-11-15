"""Independent CIC impulse kernel and measured fabric-valid pipeline latency."""
import os,re,json
import numpy as np
from audit import ROOT,Run,write_json,sha256
from hardware import VIVADO

run=Run('digital_latency');run.snapshot('单测电子通路延迟：2MHz有效使能、CIC差分脉冲响应及PCM有效流水')
tb=r'''`timescale 1ns/1ps
module tb_latency;
reg clk=0,reset=1,bit_valid=0,bit0=0; wire va,vb;wire signed[15:0] pa,pb;wire ca,cb;
integer cycle=0,inputs=0,last_dec=0,outputs=0,n=0;
always #5 clk=~clk;
always @(posedge clk)begin
cycle<=cycle+1;
if(!reset&&bit_valid)begin
 inputs<=inputs+1;if(inputs%125==124)last_dec<=cycle+1;
end
end
pdm_cic baseline(clk,reset,bit_valid,1'b0,va,pa,ca);
pdm_cic impulse(clk,reset,bit_valid,bit0,vb,pb,cb);
always @(negedge clk)if(va&&!reset)begin
 if(!vb || cycle-last_dec!=5)$fatal(1,"valid latency mismatch");
 $display("LATENCY %0d %0d %0d %0d",outputs,cycle-last_dec,$signed(baseline.c3),$signed(impulse.c3));outputs=outputs+1;
end
initial begin
repeat(5)@(negedge clk);reset=0;
for(n=0;n<1500;n=n+1)begin bit0=(n==500);bit_valid=1;@(negedge clk);bit_valid=0;repeat(49)@(negedge clk);end
repeat(8)@(negedge clk);if(outputs!=12)$fatal(1,"count");$display("PASS LATENCY");$finish;end
endmodule'''
(run.path/'tb_latency.sv').write_text(tb)
for name,args in (('xvlog.bat',['-sv',ROOT/'rtl/pdm_cic.sv',run.path/'tb_latency.sv']),
                  ('xelab.bat',['tb_latency','-s','latency_sim']),('xsim.bat',['latency_sim','-runall'])):
    rc,text=run.command([os.environ['COMSPEC'],'/d','/c',VIVADO.with_name(name),*args],name,cwd=run.path,timeout=120)
    if rc:raise RuntimeError(name)
assert 'PASS LATENCY' in text
rows=[tuple(map(int,m)) for m in re.findall(r'LATENCY (\d+) (\d+) (-?\d+) (-?\d+)',text)]
kernel=np.convolve(np.convolve(np.ones(125,dtype=np.int64),np.ones(125,dtype=np.int64)),np.ones(125,dtype=np.int64))
for index,delay,baseline,impulse in rows:
    position=124+125*index-500-2
    expected=2*int(kernel[position]) if 0<=position<len(kernel) else 0
    assert impulse-baseline==expected,(index,impulse-baseline,expected)
model={'source':'digital_injection_and_analytic_model','input_bit_rate_hz':2000000,
       'ideal_cic_kernel_samples':len(kernel),'ideal_cic_center_input_periods':186,'ideal_cic_group_delay_us':93,
       'registered_integrator_extra_input_periods':2,'integrator_extra_delay_us':1,
       'decimation_strobe_to_pcm_valid_fabric_clocks':5,'fabric_clock_hz':100000000,'pcm_valid_pipeline_ns':50,
       'feature_available_delay_ticks':10004,'timestamps_compensated':False,
       'excluded_delays':'外部麦克风/传感器物理与内部滤波；输入同步及顶层消费打拍另列，未测物理传播延迟',
       'raw_impulse_rows':rows,'kernel_reference':'three length-125 rectangular kernels convolved; RTL integrators add two input periods',
       'rtl_sha256':sha256(ROOT/'rtl/pdm_cic.sv'),'passed':True}
write_json(run.path/'latency_model.json',model);write_json(ROOT/'state/latency_model.json',{'run_id':run.run_id,**model})
run.manifest();print('RUN_ID='+run.run_id)
