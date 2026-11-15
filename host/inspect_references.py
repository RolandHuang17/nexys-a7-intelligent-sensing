"""Extract primary-source text and candidate pins; no physical-board inference."""
import csv
import json
import re
from pathlib import Path
import pymupdf
from audit import ROOT, Run, sha256, write_json

run = Run("reference_inspection")
run.snapshot("提取官方图纸、候选引脚表与用户操作请求")
run.event("user_action_requested", text="请读出板上的板名、100T 和 Rev 丝印，确认板载编程 USB 已接好并打开电源开关，完成后回复丝印文字及电源灯是否亮起。",
          reason="USB 存在，但 Vivado 与 Adept 均枚举不到 JTAG；需要板级标识与上电状态")
for name in ("nexys-a7-d3-sch.pdf", "nexys-a7_rm.pdf", "adxl362.pdf"):
    path = ROOT / "upstream" / "assets" / name
    document = pymupdf.open(path)
    parts = []
    selected = []
    for i, page in enumerate(document):
        text = page.get_text()
        parts.append(f"\n--- PAGE {i + 1} ---\n{text}")
        if name == "nexys-a7-d3-sch.pdf" and any(key in text for key in ("SPK0833", "ADMP421", "ADXL362", "FT2232")):
            target = run.path / f"schematic_page_{i+1}.png"
            page.get_pixmap(matrix=pymupdf.Matrix(1.5,1.5)).save(target)
            selected.append({"page":i+1,"image":target.relative_to(ROOT).as_posix()})
    extracted = run.path / (name + ".txt")
    extracted.write_text("".join(parts),encoding="utf-8")
    run.event("reference_extracted", input=path.relative_to(ROOT).as_posix(), sha256=sha256(path),
              pages=len(document), output=extracted.relative_to(ROOT).as_posix(), selected=selected)
    print(name, "pages:",len(document), "selected:",selected)
xdc = ROOT / "upstream" / "assets" / "Nexys-A7-100T-Master.xdc"
pins = re.findall(r"PACKAGE_PIN\s+(\S+)\s+IOSTANDARD\s+(\S+)\s*}\s*\[get_ports\s*{\s*([^}]+)\s*}",xdc.read_text())
rows=[]
for pin, standard, signal in pins:
    signal=signal.strip()
    if signal in ("CLK100MHZ","M_CLK","M_DATA","M_LRSEL","BTNU","UART_TXD_IN","UART_RXD_OUT") or signal.startswith(("ACL_","LED[")):
        direction = "input" if signal in ("CLK100MHZ","M_DATA","BTNU","UART_TXD_IN","ACL_MISO") or signal.startswith("ACL_INT") else "output"
        rows.append({"signal":signal,"fpga_pin":pin,"direction_from_fpga":direction,"io_standard":standard,
                     "source":xdc.relative_to(ROOT).as_posix(),"source_sha256":sha256(xdc),
                     "physical_revision_match":"pending"})
target=ROOT / "constraints" / "candidate_pinmap.csv"
target.parent.mkdir(parents=True,exist_ok=True)
with target.open("w",encoding="utf-8-sig",newline="") as f:
    writer=csv.DictWriter(f,fieldnames=rows[0].keys());writer.writeheader();writer.writerows(rows)
write_json(run.path / "pinmap.json",rows)
run.manifest()
print("RUN_ID="+run.run_id)
