import os,random
from audit import ROOT,Run,write_json
from hardware import VIVADO
from protocol import Frame,Decoder
run=Run("digital_protocol");run.snapshot("UART 512 B 黄金帧、空帧、坏 CRC 后重新同步验证")
good=Frame(11,0x1234,0x11223344,bytes(range(256))*2)
wire=good.encode();bad=bytearray(wire);bad[-1]^=1
empty=Frame(1,0x1235,0)
input_bytes=wire+bad+empty.encode()
expected=Frame(139,good.seq,good.event_id,good.payload).encode()+Frame(129,empty.seq).encode()
(run.path/"link_input.hex").write_text("\n".join(f"{b:02x}" for b in input_bytes)+"\n")
(run.path/"link_expected.hex").write_text("\n".join(f"{b:02x}" for b in expected)+"\n")
(run.path/"golden_request.bin").write_bytes(wire);(run.path/"golden_response.bin").write_bytes(expected[:528])
decoder=Decoder();decoded=[];rng=random.Random(20261113);offset=0
data=b"noise\xa5"+input_bytes
while offset<len(data):
    size=rng.randrange(1,41);decoded+=decoder.feed(data[offset:offset+size]);offset+=size
assert decoded==[good,empty] and decoder.crc_errors==1
for tool,args in (("xvlog.bat",["-sv",ROOT/"rtl/00_recorder_pkg.sv",ROOT/"rtl/uart.sv",ROOT/"rtl/packet_link.sv",ROOT/"tests/tb_link.sv"]),
                  ("xelab.bat",["tb_link","-s","link_sim"]),("xsim.bat",["link_sim","-runall"])):
    rc,text=run.command([os.environ["COMSPEC"],"/d","/c",VIVADO.with_name(tool),*args],tool,cwd=run.path,timeout=90)
    if rc:raise RuntimeError(tool)
assert "PASS LINK" in text
write_json(run.path/"result.json",{"source":"digital_injection","golden_payload_bytes":512,"rtl_and_host_wire_equal":True,"bad_crc_rejected":True})
run.manifest();print("RUN_ID="+run.run_id)
