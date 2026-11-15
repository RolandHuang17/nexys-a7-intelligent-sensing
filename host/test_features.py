import os,re,argparse
from audit import ROOT,Run,write_json
from hardware import VIVADO
from reference import feature_reference
parser=argparse.ArgumentParser();parser.add_argument('--extreme',action='store_true');options=parser.parse_args()
run=Run('digital_features');run.snapshot('独立验证跨窗 SPI 迟到、无 XYZ 窗口无效、最小有符号音频值与三轴极值')
tb=(ROOT/'tests/tb_features.sv').read_text()
if options.extreme:tb=tb.replace('x=(xyz_tick/40)*7,y=-$signed((xyz_tick/40)*3),z=1000',"x=(xyz_tick/40)%2 ? 32767 : -32768,y=x,z=x")
(run.path/'tb_features.sv').write_text(tb)
for name,args in (('xvlog.bat',['-sv',ROOT/'rtl/feature_core.sv',run.path/'tb_features.sv']),
                  ('xelab.bat',['tb_features','-s','feature_sim']),('xsim.bat',['feature_sim','-runall'])):
    rc,text=run.command([os.environ['COMSPEC'],'/d','/c',VIVADO.with_name(name),*args],name,cwd=run.path,timeout=90)
    if rc:raise RuntimeError(name)
assert 'PASS FEATURES' in text
actual=[tuple(map(int,m)) for m in re.findall(r'FEATURE (\d+) (\d+) (\d+) (\d+) (\d+) (\d+) (\d+)',text)]
pcm=[-32768 if t==20 else (t%64-32)*100 for t in range(480)]
xyz=[(t,t//40*7,-t//40*3,1000) for t in range(0,480,40) if not 160<=t<320]
if options.extreme:xyz=[(t,*([32767 if t//40%2 else -32768]*3)) for t in range(0,480,40) if not 160<=t<320]
expected=feature_reference(pcm,xyz,0,pcm_period=1,end_tick=480,frame_ticks=160,available_delay=14)
for row,ref in zip(actual,expected):
    ft,a,v,av,vv,an,xn=row
    assert (ft,a if av else None,v if vv else None,an,xn)==(ref['tick'],ref['audio'],ref['accel'],ref['audio_n'],ref['xyz_n']),(row,ref)
assert len(actual)==len(expected)==3
write_json(run.path/'comparison.json',{'source':'digital_injection','actual':actual,'reference':expected,'passed':True})
run.manifest();print('RUN_ID='+run.run_id)
