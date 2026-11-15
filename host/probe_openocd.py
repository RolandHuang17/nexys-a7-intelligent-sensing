"""Read-only JTAG scan using the already installed RVfpga/OpenOCD driver path."""
from pathlib import Path
import shutil
from audit import ROOT, Run, sha256, write_json

PACKAGE = Path(r"C:\Users\roland\.platformio\packages\tool-openocd-riscv-chipsalliance")
run=Run("jtag_winusb_diagnostic")
run.snapshot("采用兼容已有 libwdi/WinUSB 绑定的 OpenOCD 只读 JTAG 扫描")
exe=PACKAGE / "bin" / "openocd.exe"
run.event("diagnostic_finding", finding="JTAG A 接口绑定 libwdi WinUSB (oem65.inf)，B 接口为 FTDI；Vivado/Adept 均枚举零目标",
          decision="先验证已安装 OpenOCD 的 libusb/WinUSB 路径，不修改系统驱动")
run.command([exe,"--version"],"确认课程 OpenOCD 版本")
write_json(run.path / "tool.json",{"executable":str(exe),"sha256":sha256(exe),
           "package":(PACKAGE/"package.json").read_text(encoding="utf-8")})
rc,text=run.command([exe,"-f",ROOT/"scripts/jtag_winusb.cfg","-c","init; scan_chain; shutdown"],
                    "选择唯一 USB 序列号，读取 XC7A100T JTAG IDCODE；不下载或重置 FPGA",timeout=45)
write_json(run.path / "scan_result.json",{"returncode":rc,"idcode_found":"0x03631093" in text,
           "programmed":False,"driver_modified":False})
run.manifest()
print("RUN_ID="+run.run_id)
raise SystemExit(rc)
