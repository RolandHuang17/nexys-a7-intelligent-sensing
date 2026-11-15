"""Meaningful digital checks, explicitly distinct from board evidence."""
import os
import random
from pathlib import Path
from audit import ROOT,Run,write_json
from hardware import VIVADO
from reference import cic_reference,Pairing

run=Run("digital_numeric")
run.snapshot("CIC 定点 RTL 与独立 Python 数值参考")
rng=random.Random(20261113)
bits=[1]*12500+[0]*12500+[i%2 for i in range(12500)]+[rng.randrange(2) for _ in range(12500)]
expected=cic_reference(bits)
(run.path/"pdm_bits.hex").write_text("\n".join(str(x) for x in bits)+"\n")
(run.path/"pcm_expected.hex").write_text("\n".join(f"{x&65535:04x}" for x in expected)+"\n")
write_json(run.path/"vectors.json",{"source":"digital_injection","seed":20261113,"segments":["ones","zeros","alternating","random"],"samples":len(expected),"pcm":expected})
commands=[("xvlog.bat",["-sv",ROOT/"rtl/pdm_cic.sv",ROOT/"tests/tb_cic.sv"]),
          ("xelab.bat",["tb_cic","-s","cic_sim"]), ("xsim.bat",["cic_sim","-runall"])]
success=True
for tool,args in commands:
    rc,text=run.command([os.environ["COMSPEC"],"/d","/c",VIVADO.with_name(tool),*args],
                        f"XSim CIC {tool}",cwd=run.path,timeout=120)
    if rc!=0 or (tool=="xsim.bat" and "PASS CIC" not in text):success=False;break
checks=[]
for delta in (4_000_000,4_900_000,5_000_000,5_100_000,6_000_000):
    for first in ("audio","accel"):
        p=Pairing(10,10);p.step(0,0,0)
        p.step(1_000_000,20 if first=="audio" else 0,20 if first=="accel" else 0)
        out=p.step(1_000_000+delta,20 if first=="accel" else 0,20 if first=="audio" else 0)
        observed=out["joint"] is not None
        assert observed==(delta<=5_000_000)
        checks.append({"layer":"candidate_interface_reference","first":first,"delta_ticks":delta,"paired":observed})
p=Pairing(10,10);p.step(0,0,0);assert not p.step(1_000_000,10,10)["audio_cross"]
write_json(run.path/"reference_boundaries.json",checks)
run.event("digital_result",cic_rtl_bit_exact=success,reference_boundary_cases=len(checks),source="digital_injection",board_validation=False)
run.manifest()
print("RUN_ID="+run.run_id)
raise SystemExit(0 if success else 2)
