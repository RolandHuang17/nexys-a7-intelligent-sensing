import os
from audit import ROOT,Run,write_json,sha256
from hardware import VIVADO

if __name__=='__main__':
 r=Run('music_tap_1000_boundary');text=(ROOT/'tests/tb_music_tap.sv').read_text()
 text=text.replace('head[127:112]=600','head[127:112]=1000').replace('pair_case(600,1)','pair_case(1000,1)').replace('pair_case(601,0)','pair_case(1001,0)').replace('149/150/600/601ms','149/150/1000/1001ms')
 source=r.path/'tb_music_tap1000.sv';source.write_text(text)
 sources=[ROOT/'rtl/00_recorder_pkg.sv',ROOT/'rtl/music_decimator.sv',ROOT/'rtl/music_core.sv',source]
 for tool,args in [('xvlog.bat',['-sv',*sources]),('xelab.bat',['tb_music_tap','-s','tap1000']),('xsim.bat',['tap1000','-runall'])]:
  rc,out=r.command([os.environ['COMSPEC'],'/d','/c',VIVADO.with_name(tool),*args],'实际选定1秒窗口边界检查：'+tool,cwd=r.path,timeout=100);assert rc==0
  if tool=='xsim.bat':assert 'PASS MUSIC TAP 149/150/1000/1001ms' in out and 'Fatal:' not in out
 write_json(r.path/'result.json',{'source':'digital_not_physical','boundaries_ms':[149,150,1000,1001],'passed':True,'sources':{str(p.relative_to(ROOT)):sha256(p) for p in sources},'template_source':{'path':'tests/tb_music_tap.sv','sha256':sha256(ROOT/'tests/tb_music_tap.sv')}});r.manifest();print(r.run_id)
