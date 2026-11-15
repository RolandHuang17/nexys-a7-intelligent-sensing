import os
from audit import ROOT,Run,write_json,sha256
from hardware import VIVADO
r=Run('test_music_tap')
sources=[ROOT/'rtl/00_recorder_pkg.sv',ROOT/'rtl/music_decimator.sv',ROOT/'rtl/music_core.sv',ROOT/'tests/tb_music_tap.sv']
for tool,args in [('xvlog.bat',['-sv',*sources]),
                  ('xelab.bat',['tb_music_tap','-s','tap_sim']),('xsim.bat',['tap_sim','-runall'])]:
 rc,text=r.command([os.environ['COMSPEC'],'/d','/c',VIVADO.with_name(tool),*args],'双击与中键数字边界：'+tool,cwd=r.path,timeout=120);assert rc==0
 if tool=='xsim.bat':assert 'PASS MUSIC TAP' in text
write_json(r.path/'result.json',{'source':'digital_injection_not_physical','cases':['double_seq 149ms rejected','double_seq 150ms accepted','double_seq 600ms accepted','double_seq 601ms rejected','two taps never start capture','centre press edges'],'passed':True,'sources':{str(p.relative_to(ROOT)):sha256(p) for p in sources}})
r.manifest();print(r.run_id)
