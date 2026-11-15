import os
from audit import ROOT,Run,write_json
from hardware import VIVADO
from reference import Pairing
run=Run('digital_triggers');run.snapshot('双向配对、严格上穿、无效窗口、去重和低32位进位边界')
cases=[]
for delta in (4000000,4900000,5000000,5100000,6000000):
    for first in ('audio','accel'):
        cases.append([(0,0,0),(1000000,20 if first=='audio' else 0,20 if first=='accel' else 0),
                      (1000000+delta,20 if first=='accel' else 0,20 if first=='audio' else 0)])
cases += [[(0,0,0),(1000000,10,10),(2000000,20,20)],
          [(0,0,0),(1000000,20,20),(2000000,0,0),(3000000,20,20),(30000000,0,0),(31000000,20,20)],
          [(0,0,0),(1000000,20,None),(2000000,0,None),(3000000,0,20)],
          [(2**32-2000000,0,0),(2**32-1000000,20,0),(2**32+4000000,0,20)]]
lines=['`timescale 1ns/1ps','module tb_trigger;reg clk=0,reset=1,fv=0,av=0,vv=0;reg[63:0]t=0;reg[31:0]a=0,v=0;',
       'wire rv,ax,vx,pair,confirm,dd;wire[63:0]ta,tv,tc;always #5 clk=~clk;',
       "trigger_core dut(clk,reset,fv,t,av,vv,a,v,32'd10,32'd10,32'd5000000,rv,ax,vx,pair,confirm,dd,ta,tv,tc);",
       'initial begin']
golden=[];index=0
for case in cases:
    lines+=['reset=1;fv=0;repeat(3)@(negedge clk);reset=0;']
    reference=Pairing(10,10)
    for tick,a,v in case:
        result=reference.step(tick,a,v);joint=result['joint']
        flags=[int(result['audio_cross']),int(result['accel_cross']),int(joint is not None),
               int(joint is not None and not joint['dedup']),int(joint is not None and joint['dedup'])]
        index+=1
        lines += [f"t=64'd{tick};a=32'd{a or 0};v=32'd{v or 0};av={int(a is not None)};vv={int(v is not None)};fv=1;@(negedge clk);fv=0;",
                  f"if(!rv || {{ax,vx,pair,confirm,dd}}!==5'b{''.join(map(str,flags))})$fatal(1,\"trigger vector {index}\");"]
        if joint:
            lines += [f"if(ta!=64'd{joint['t_audio']} || tv!=64'd{joint['t_accel']} || tc!=64'd{joint['t_confirm']})$fatal(1,\"time vector {index}\");"]
        lines += ['repeat(2)@(negedge clk);']
        golden.append({'tick':tick,'audio':a,'accel':v,'expected':result})
lines += [f'$display("PASS TRIGGERS {index} vectors");$finish;end endmodule']
bench=run.path/'tb_trigger.sv';bench.write_text('\n'.join(lines),encoding='utf-8')
write_json(run.path/'golden.json',golden)
for name,args in (('xvlog.bat',['-sv',ROOT/'rtl/trigger_core.sv',bench]),
                  ('xelab.bat',['tb_trigger','-s','trigger_sim']),('xsim.bat',['trigger_sim','-runall'])):
    rc,text=run.command([os.environ['COMSPEC'],'/d','/c',VIVADO.with_name(name),*args],name,cwd=run.path,timeout=90)
    if rc:raise RuntimeError(name)
assert 'PASS TRIGGERS' in text
run.event('digital_result',source='digital_candidate_interface',vectors=index,passed=True,physical_validation=False)
run.manifest();print('RUN_ID='+run.run_id)
