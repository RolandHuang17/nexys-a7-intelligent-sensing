import os,json,re,zlib
import numpy as np
from audit import ROOT,Run,write_json,sha256
from hardware import VIVADO
from music_protocol import parse_status
from protocol import Frame

if __name__=='__main__':
 r=Run('music_decimator_test');config=json.loads((ROOT/'config/music_decimator.json').read_text(encoding='utf8'))
 rng=np.random.default_rng(20261114);a=rng.integers(-32768,32768,2048,dtype=np.int32);a[:64]=1000;a[64:128]=np.tile([-32768,32767],32)
 (r.path/'fir_input.hex').write_text('\n'.join(f'{int(x)&65535:04x}' for x in a),encoding='ascii')
 sources=[ROOT/'rtl/00_recorder_pkg.sv',ROOT/'rtl/music_decimator.sv',ROOT/'rtl/music_core.sv',ROOT/'tests/tb_music_decimator.sv',ROOT/'tests/tb_music_half.sv']
 rc,_=r.command([os.environ['COMSPEC'],'/d','/c',VIVADO.with_name('xvlog.bat'),'-sv',*sources],'编译定点低通和完整8kHz捕获契约',cwd=r.path);assert rc==0
 for name in ('music_decimator','music_half'):
  for tool,args in [('xelab.bat',['tb_'+name,'-s',name]),('xsim.bat',[name,'-runall'])]:
   rc,text=r.command([os.environ['COMSPEC'],'/d','/c',VIVADO.with_name(tool),*args],'8kHz数字检查 '+name,cwd=r.path,timeout=120);assert rc==0
   if tool=='xsim.bat':assert 'PASS MUSIC' in text and 'Fatal:' not in text
 out=np.loadtxt(r.path/'fir_output.txt',dtype=np.int64);sums=np.convolve(a.astype(np.int64),np.array(config['coefficients_q15'],dtype=np.int64))[:len(a)]
 expected=np.clip((sums+np.where(sums<0,16383,16384))>>15,-32768,32767)
 assert np.array_equal(out[:,0],np.arange(0,2048,2)) and np.array_equal(out[:,1],expected[::2])
 tokens=[]
 for line in (r.path/'music_half_status.hex').read_text().splitlines():
  if not line.startswith('//'):tokens.extend(line.split())
 payload=bytes(int(x,16) for x in tokens);row=parse_status(Frame(143,1,1,payload))
 assert row['sample_rate']==8000 and row['samples']==32 and row['crc32']==zlib.crc32(np.full(32,1000,dtype='<i2').tobytes())
 assert abs(config['gain_1k_dB'])<.1 and config['gain_6k_dB'] < -50
 write_json(ROOT/'config/music_8000_golden_frames.json',{'run_id':r.run_id,'payload_hex':payload.hex(),'source':'RTL FIR and music core digital integration'})
 write_json(r.path/'result.json',{'source':'digital_not_physical','bit_exact_samples':1024,'lowpass':config,'half_capture':row,'passed':True,'sources':{str(p.relative_to(ROOT)):sha256(p) for p in sources}});r.manifest();print(r.run_id)
