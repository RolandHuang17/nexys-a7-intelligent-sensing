import os,re,struct,zlib,argparse
from audit import ROOT,Run,write_json
from hardware import VIVADO

parser=argparse.ArgumentParser();parser.add_argument('--base',type=lambda s:int(s,0),default=0);parser.add_argument('--lag',type=int,default=0)
args=parser.parse_args()
run=Run("digital_bank")
run.snapshot("BRAM 回卷、前后窗、CRC 与幂等释放边界仿真")
tb=(ROOT/'tests/tb_bank.sv').read_text().replace('BASE=0, LAG=0',f'BASE=64\'d{args.base}, LAG=64\'d{args.lag}')
(run.path/'tb_bank.sv').write_text(tb)
sources=sorted((ROOT/"rtl").glob("*.sv"))+[run.path/'tb_bank.sv']
for name,argv in (("xvlog.bat",["-sv","-i",ROOT/"rtl",*sources]),
                  ("xelab.bat",["tb_bank","-s","bank_sim"]),
                  ("xsim.bat",["bank_sim","-runall"])):
    rc,text=run.command([os.environ["COMSPEC"],"/d","/c",VIVADO.with_name(name),*argv],name,cwd=run.path,timeout=120)
    if rc!=0:raise RuntimeError(name+" failed")
if "PASS BANK" not in text:raise RuntimeError("simulation did not pass")
meta=re.search(r"BANK_META (\d+) (\d+) (\d+) (\d+) (\d+) (\d+) ([0-9a-fA-F]+)",text)
event_id,anchor,first_index,first_tick,nxyz,length=map(int,meta.groups()[:6]);crc=int(meta[7],16)
payload=(run.path/"bank_payload.bin").read_bytes()
assert len(payload)==length and zlib.crc32(payload)==crc
assert struct.unpack("<24h",payload[:48])==tuple(range(first_index,first_index+24))
xyz=[struct.unpack_from("<Ihhh",payload,i) for i in range(48,len(payload),10)]
assert len(xyz)==nxyz
for relative,x,y,z in xyz:
    actual_tick=anchor-48+relative
    stimulus_tick=actual_tick-args.base
    assert 0<=relative<144 and stimulus_tick%30==0 and (x,y,z)==(stimulus_tick,-stimulus_tick,1000)
assert anchor-48<=first_tick<anchor-48+6
write_json(run.path/"independent_check.json",{"source":"digital_injection","event_id":event_id,"anchor":anchor,
           "first_index":first_index,"first_tick":first_tick,"xyz_count":nxyz,"bytes":length,"base_tick":args.base,"anchor_lag":args.lag,
           "board_style_crc":f"{crc:08x}","python_zlib_crc":f"{zlib.crc32(payload):08x}","passed":True})
run.manifest();print("RUN_ID="+run.run_id)
