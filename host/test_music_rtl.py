import os,re,sys,zlib
import numpy as np
from audit import ROOT,Run,write_json,sha256
from protocol import Frame,Decoder
from music_protocol import parse_status
from hardware import VIVADO
r=Run('test_music_rtl')
sources=[ROOT/'rtl/00_recorder_pkg.sv',ROOT/'rtl/music_decimator.sv',ROOT/'rtl/music_core.sv',ROOT/'tests/tb_music.sv']
for tool,args in [('xvlog.bat',['-sv',*sources]),('xelab.bat',['tb_music','-s','music_sim']),('xsim.bat',['music_sim','-runall'])]:
 rc,text=r.command([os.environ['COMSPEC'],'/d','/c',VIVADO.with_name(tool),*args],'长录音数字注入：'+tool,cwd=r.path,timeout=240)
 assert rc==0,tool
 if tool=='xsim.bat':
  assert 'PASS MUSIC' in text,text[-2000:]
  m=re.search(r'MUSIC_CRC ([0-9a-fA-F]+) ([0-9a-fA-F]+)',text);assert m
  raw=((np.arange(160000,dtype=np.uint32)*37)^0x9a35).astype('<i2').tobytes()
  assert int(m[1],16)==zlib.crc32(raw) and int(m[2],16)==zlib.crc32(raw[:256000])
r.status('MUSIC1_rtl','passed','160000点、跨65535/131071地址、重复读取、启动去重、忙拒绝、坏ACK与CRC通过',
         [str(r.path.relative_to(ROOT))],'综合布局布线；另做双击与按键边界测试')
frames={}
for name in ('music_status','music_read'):
 tokens=[]
 for line in (r.path/(name+'.hex')).read_text().splitlines():
  if not line.startswith('//'):tokens.extend(line.split())
 payload=bytes(int(t,16) for t in tokens);frame=Frame(143,123,1,payload);encoded=frame.encode()
 assert Decoder().feed(encoded)==[frame]
 if name=='music_status':
  status=parse_status(frame);assert status['samples']==160000 and status['state']==3 and status['crc32']==zlib.crc32(raw)
 else:assert payload[32:]==raw[65530*2:(65530+24)*2]
 frames[name]={'payload_hex':payload.hex(),'wire_hex':encoded.hex()}
write_json(ROOT/'config/music_golden_frames.json',{'source':'XSim real RTL response to host parser','run_id':r.run_id,'frames':frames})
write_json(r.path/'result.json',{'source':'digital_injection_not_physical','samples':160000,'crc32':zlib.crc32(raw),'prefix_8s_crc32':zlib.crc32(raw[:256000]),'shared_golden_frames':True});r.manifest();print(r.run_id)
