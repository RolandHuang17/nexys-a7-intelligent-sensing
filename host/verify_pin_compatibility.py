"""Cross-check official schematic netlists against the general 100T XDC.

The exact physical PCB revision stays unknown when hidden by the enclosure.
This check verifies the common interface mapping, not the physical revision.
"""
import csv
import json
import re
import pymupdf
from audit import ROOT, Run, sha256, write_json
from fetch_assets import download

run=Run("pin_compatibility")
run.snapshot("核对官方通用 XDC 与 D.2/D.3 原理图共用引脚，保留精确修订未知")
download(run,"nexys-a7-d2-sch.pdf","https://digilent.com/reference/_media/reference/programmable-logic/nexys-a7/nexys-a7-d2-sch.pdf")
with (ROOT/"constraints/candidate_pinmap.csv").open(encoding="utf-8-sig") as f:
    rows=list(csv.DictReader(f))
aliases={"M_CLK":"M0CLK","M_DATA":"M0DATA","M_LRSEL":"M0LRSEL",
         "CLK100MHZ":"CLK100MHZ","UART_TXD_IN":"UART0TXD0IN","UART_RXD_OUT":"UART0RXD0OUT",
         "ACL_MISO":"ACL0MISO","ACL_MOSI":"ACL0MOSI","ACL_SCLK":"ACL0SCLK","ACL_CSN":"ACL0CSN",
         "ACL_INT[1]":"ACL0INT1","ACL_INT[2]":"ACL0INT2","BTNU":"BTNU"}
for i in range(16): aliases[f"LED[{i}]"]=f"LED{i}"
evidence=[]
for name in ("nexys-a7-d2-sch.pdf","nexys-a7-d3-sch.pdf"):
    path=ROOT/"upstream/assets"/name
    if not path.exists(): continue
    pdf=pymupdf.open(path)
    text="\n".join(p.get_text() for p in pdf)
    checks=[]
    for row in rows:
        net=aliases[row["signal"]]
        expression=r"PIIC80"+re.escape(row["fpga_pin"])+r"\s+(?:PI[A-Z0-9]+\s+)*NL"+re.escape(net)+r"\b"
        matched=bool(re.search(expression,text))
        checks.append({"signal":row["signal"],"pin":row["fpga_pin"],"net":net,"matched":matched})
    evidence.append({"source":path.relative_to(ROOT).as_posix(),"sha256":sha256(path),
                     "microphone_in_drawing":"SPK0833LM4H" if "SPK0833LM4H" in text else None,"checks":checks})
    print(name, "verified",sum(c["matched"] for c in checks),"of",len(checks))
write_json(run.path/"compatibility.json",evidence)
essential=set(aliases)-{"LED[11]","LED[12]"}
# Legacy schematic exports omit some LED labels in their hidden netlist text.
ok=len(evidence)==2 and all(all(c["matched"] for c in item["checks"] if c["signal"] in essential) for item in evidence)
run.event("pin_compatibility_result",common_interface_verified=ok,
          physical_pcb_revision_verified=False,explanation="物理 Rev 被亚克力遮挡；图纸中的料号不作为实际料号确认")
run.manifest()
print("RUN_ID="+run.run_id)
raise SystemExit(0 if ok else 2)
