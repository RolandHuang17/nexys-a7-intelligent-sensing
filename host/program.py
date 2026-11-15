import json,re
from audit import ROOT,sha256,write_json
from hardware import openocd


def program_latest(run):
    state=json.loads((ROOT/"state/build/status.json").read_text(encoding="utf-8"))
    if state["status"]!="passed":raise RuntimeError("Latest implementation has not passed")
    if sha256(ROOT/'constraints/nexys_a7_100t.xdc')!=state['config_sha256']:
        raise RuntimeError('当前XDC与已验收构建不同，必须先重建')
    bit=ROOT/state["outputs"][0]
    if sha256(bit)!=state["bitstream_sha256"]:raise ValueError("bitstream provenance mismatch")
    build_inputs=json.loads((ROOT/'runs'/state['run_id']/'build_inputs.json').read_text(encoding='utf8'))
    for item in build_inputs['files']:
        if sha256(ROOT/item['path'])!=item['sha256']:raise RuntimeError('当前RTL与通过构建不同，等待重建完成')
    rc,text=openocd(run,f"init; pld load 0 {{{bit.as_posix()}}}; echo [virtex2 read_stat 0]; shutdown",
                    "下载已通过时序检查的改进位流到 SRAM，并读回配置状态",timeout=120)
    match=re.search(r"status register: (0x[0-9a-fA-F]+)",text)
    stat=int(match[1],16) if match else None
    success=rc==0 and stat is not None and bool(stat&(1<<14)) and not bool(stat&1)
    result={"success":success,"status":None if stat is None else f"{stat:08x}",
            "bitstream_sha256":sha256(bit),"build_run_id":state["run_id"],"build_id":build_inputs["build_id"],
            "config_sha256":state["config_sha256"],"configuration":"SRAM"}
    write_json(run.path/"programming.json",result)
    if not success:raise RuntimeError("FPGA configuration status did not pass")
    write_json(ROOT/'state/active_device.json',{**result,'programming_run_id':run.run_id})
    return result


def find_port(expected_serial="210292B7F4F8"):
    from serial.tools import list_ports
    ports=list(list_ports.comports())
    matches=[p for p in ports if p.vid==0x0403 and p.pid==0x6010 and
             expected_serial in (p.serial_number or "")]
    if len(matches)!=1:raise RuntimeError("Unique matching UART not found: "+repr([(p.device,p.hwid) for p in ports]))
    return matches[0].device
