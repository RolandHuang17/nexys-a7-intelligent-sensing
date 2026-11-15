import math,os,random,struct
from audit import ROOT,Run,write_json
from hardware import VIVADO
from reference import feature_reference,Pairing
run=Run('digital_replay_engine');run.snapshot('完整 REPLAY 原始采样时间轴与共享特征/判定链路的独立对照')
pcm=[round(2000*math.sin(2*math.pi*1500*i/16000)) if 65000000<=1234+i*6250<67500000 else (i%7-3) for i in range(24000)]
rng=random.Random(20261113)
xyz=[]
for t in range(250000,150000000,500000):
    xyz.append((t+rng.randrange(-100,101),128 if 66000000<=t<67000000 else 0,0,1000))
events=[(1234+i*6250,1,value,0,0,0) for i,value in enumerate(pcm)]
events += [(t,2,0,x,y,z) for t,x,y,z in xyz]
events.sort(key=lambda e:e[0])
stream=b''.join(struct.pack('<IBhhhh',*e) for e in events)
(run.path/'replay_input.hex').write_text('\n'.join(f'{b:02x}' for b in stream)+'\n')
bench=r'''`timescale 1ns/1ps
module tb_engine;
reg clk=0,reset=1,start=0;reg[63:0]ticks=0;reg[7:0]cmd=0;reg[15:0]len=0;reg[127:0]head=0;
reg[7:0]rx_mem[0:511],stream[0:BYTE_COUNT-1];wire[8:0]rx_addr;wire[7:0]rx_data=rx_mem[rx_addr];
reg[8:0]reply_addr=0;wire[7:0]reply_data;wire done;wire[15:0]reply_len;
wire armed,replay,rv,ax,vx,pair,confirm,dd;wire[1:0]mode;wire[31:0]cfg,ath,vth,win,late;
wire[63:0]rt,ta,tv,tc,hcount;integer i,j,n,offset,f,cursor;
always #5 clk=~clk;always @(posedge clk)if(reset)ticks<=0;else ticks<=ticks+1;
analysis_engine dut(clk,reset,ticks,1'b0,16'sd0,1'b0,64'b0,16'sd0,16'sd0,16'sd0,
start,cmd,len,head,rx_addr,rx_data,reply_addr,reply_data,done,reply_len,8'b0,
armed,mode,cfg,ath,vth,win,rv,ax,vx,pair,confirm,dd,rt,ta,tv,tc,hcount,late,replay);
task transact(input[7:0]c,input[15:0]l,input[127:0]h);
begin @(negedge clk);cmd=c;len=l;head=h;start=1;@(negedge clk);start=0;wait(done);@(negedge clk);
reply_addr=0;#1;if(reply_data!=0)$fatal(1,"engine command error c=%0d code=%0d",c,reply_data);end endtask
initial begin
$readmemh("replay_input.hex",stream);repeat(5)@(negedge clk);reset=0;
transact(4,16,{32'd1234,32'd5000000,32'd5,32'd50});transact(10,1,128'd1);
offset=0;
while(offset<BYTE_COUNT)begin
n=(BYTE_COUNT-offset)/13;if(n>39)n=39;
for(i=0;i<n*13;i=i+1)rx_mem[i+2]=stream[offset+i];
transact(10,2+n*13,(n<<8)|2);offset=offset+n*13;
end
transact(10,5,{88'b0,32'd150010004,8'd3});
if(hcount!=150 || late!=0)$fatal(1,"history count=%0d late=%0d",hcount,late);
f=$fopen("engine_history.bin","wb");
for(cursor=0;cursor<150;cursor=cursor+15)begin
transact(3,9,{56'b0,8'd15,64'(cursor)});
if(reply_len!=494)$fatal(1,"CAL length %0d",reply_len);
for(j=14;j<494;j=j+1)begin @(negedge clk);reply_addr=j;#1;$fwrite(f,"%c",reply_data);end
end
$fclose(f);$display("PASS REPLAY ENGINE 24000 PCM plus actual-timestamp XYZ");$finish;
end
initial begin #30000000;$fatal(1,"engine timeout");end
endmodule
'''.replace('BYTE_COUNT',str(len(stream)))
(run.path/'tb_engine.sv').write_text(bench)
for name,args in (('xvlog.bat',['-sv',ROOT/'rtl/feature_core.sv',ROOT/'rtl/trigger_core.sv',ROOT/'rtl/analysis_engine.sv',run.path/'tb_engine.sv']),
                  ('xelab.bat',['tb_engine','-s','engine_sim']),('xsim.bat',['engine_sim','-runall'])):
    rc,text=run.command([os.environ['COMSPEC'],'/d','/c',VIVADO.with_name(name),*args],name,cwd=run.path,timeout=120)
    if rc:raise RuntimeError(name)
assert 'PASS REPLAY ENGINE' in text
raw=(run.path/'engine_history.bin').read_bytes();assert len(raw)==150*32
rows=[struct.unpack_from('<QIIHHBBHII',raw,i) for i in range(0,len(raw),32)]
expected=feature_reference(pcm,xyz,1234,end_tick=150000000)
pairing=Pairing(50,5);comparisons=[]
for row,ref in zip(rows,expected):
    tick,a,v,an,xn,flags,reason,cfg,agea,agev=row
    assert (tick,a if flags&1 else None,v if flags&2 else None,an,xn)==(ref['tick'],ref['audio'],ref['accel'],ref['audio_n'],ref['xyz_n']),(row,ref)
    gold=pairing.step(tick,ref['audio'],ref['accel']);joint=gold['joint']
    assert bool(flags&4)==gold['audio_cross'] and bool(flags&8)==gold['accel_cross']
    assert bool(flags&16)==(joint is not None)
    assert bool(flags&32)==(joint is not None and not joint['dedup'])
    assert bool(flags&64)==(joint is not None and joint['dedup'])
    if joint:assert (tick-agea,tick-agev,tick)==(joint['t_audio'],joint['t_accel'],joint['t_confirm'])
    assert cfg==1234 and reason==0
    comparisons.append({'reference':ref,'rtl':row,'trigger_reference':gold})
write_json(run.path/'comparison.json',{'source':'digital_injection','windows':150,'rows':comparisons,'passed':True})
run.event('digital_result',source='digital_injection',windows=150,pcm_samples=24000,xyz_samples=len(xyz),passed=True)
run.manifest();print('RUN_ID='+run.run_id)
