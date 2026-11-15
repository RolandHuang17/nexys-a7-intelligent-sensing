from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

from audit import ROOT, Run, write_json, sha256
from hardware import hardware_server, vivado, VIVADO, openocd


def doctor(args):
    run = Run("doctor")
    run.snapshot("工具和板型准入诊断版本")
    rc, output = run.command(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                             "-File", ROOT / "scripts" / "inventory.ps1"],
                            "枚举 USB、UART、Adept 驱动及工具；排除蓝牙", timeout=90)
    inventory = json.loads(output.lstrip("\ufeff")) if rc == 0 else {}
    write_json(run.path / "inventory.json", inventory)
    run.command([str(VIVADO), "-version"] if sys.platform != "win32" else
                ["cmd.exe", "/d", "/c", str(VIVADO), "-version"], "确认 Vivado 实际版本")
    with hardware_server(run) as url:
        rc, text = vivado(run, "enumerate.tcl", [url], "非编程 JTAG/器件枚举")
    scan_rc, scan = openocd(run, "init; scan_chain; shutdown", "兼容 WinUSB 的唯一序列号 JTAG 只读扫描")
    found = re.findall(r"tap/device found: (0x[0-9a-fA-F]+)", scan)
    jtag_ok = scan_rc == 0 and len(found) == 1 and int(found[0],16) & 0x0fffffff == 0x03631093
    profile_path = ROOT / "config" / "board_profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8")) if profile_path.exists() else {}
    profile.update({"observed_usb": inventory.get("devices", []),
                    "jtag_targets": re.findall(r"^TARGET:(.+)$", text, re.M),
                    "jtag_devices": re.findall(r"^DEVICE:(.+)$", text, re.M),
                    "openocd_idcodes": found, "jtag_unique_verified": jtag_ok,
                    "enumeration_run_id": run.run_id,
                    "board_name": profile.get("board_name"), "pcb_revision": profile.get("pcb_revision"),
                    "physical_verified": profile.get("physical_verified", False),
                    "pins_verified": profile.get("pins_verified", False)})
    write_json(profile_path, profile)
    evidence = [(run.path / "inventory.json").relative_to(ROOT).as_posix(),
                profile_path.relative_to(ROOT).as_posix()]
    passed = jtag_ok and profile["physical_verified"] and profile["pins_verified"]
    run.status("doctor", "passed" if passed else "failed", "板名/100T、唯一 USB-JTAG/UART 与共用关键引脚准入通过；PCB 精确 Rev 和实际麦克风料号仍未验证" if passed else
               "尚缺板级确认或唯一 JTAG 目标；详见原始枚举和硬件服务日志", evidence,
               "核对 Adept/WinUSB 链路；实物丝印确认后复测")
    print("RUN_ID=" + run.run_id)
    return 0 if passed else 2


def baseline(args):
    if args.observation:
        state=json.loads((ROOT/"state/A0/status.json").read_text(encoding="utf-8"))
        run=Run("baseline",state["run_id"])
        run.event("user_observation",verbatim=args.observation,
                  led_sequence_observed=args.led_sequence_observed,heard_playback=args.heard_playback)
        write_json(run.path/"functional_observation.json",{"verbatim":args.observation,
                   "led_sequence_observed":args.led_sequence_observed,"heard_playback":args.heard_playback})
        if not args.led_sequence_observed:
            run.status("A0","needs_user","观察尚未证明完整录放状态序列",state["evidence"],"诊断 BTNU 与 LED 行为")
            return 2
        if not (run.path/"programming.json").exists():
            raise RuntimeError("No associated programming evidence")
        run.status("A0","passed","官方位流编程与用户观察到的完整录放 LED 序列均有证据",
                   state["evidence"]+[str((run.path/"functional_observation.json").relative_to(ROOT))],
                   "进入 A1a 前端自检",bitstream_sha256=state["bitstream_sha256"],
                   upstream_revision="100T/OOB/2025.1-1")
        return 0
    doctor_state=json.loads((ROOT/"state/doctor/status.json").read_text(encoding="utf-8"))
    if doctor_state["status"]!="passed":
        raise RuntimeError("Board/tool admission has not passed")
    run=Run("baseline")
    run.snapshot("官方固定版本 SRAM 编程入口")
    bit=ROOT/"upstream/baseline/Nexys4DdrUserDemo.bit"
    archive=ROOT/"upstream/assets/Nexys-A7-100T-OOB-hw.xpr.zip"
    bh=sha256(bit); ah=sha256(archive)
    assert bh=="5a92da8b2852ecac5fe0bc7340f1e9f9c9d94b0f27c3b8187749ef915ba50c69"
    assert ah=="77672b7708bd676d5dd0c979bafebd70fa1d1b4a09aff34dbe20f464247bca13"
    rc,text=openocd(run,f"init; pld load 0 {{{bit.as_posix()}}}; virtex2 read_stat 0; shutdown",
                    "将校验后的官方位流写入 FPGA SRAM 并读取配置状态",timeout=120)
    record={"returncode":rc,"bitstream":str(bit.relative_to(ROOT)),"bitstream_sha256":bh,
            "archive_sha256":ah,"usb_serial":"210292B7F4F8","transport":"OpenOCD FTDI WinUSB",
            "configuration":"SRAM","functional_observation":"pending"}
    write_json(run.path/"programming.json",record)
    run.status("A0","needs_user" if rc==0 else "failed",
               "官方 SRAM 编程命令成功；待 BTNU 功能观察" if rc==0 else "官方 SRAM 编程失败",
               [(run.path/"programming.json").relative_to(ROOT).as_posix()],
               "按一次 BTNU 并报告 LED 从逐渐亮起到逐渐熄灭的完整变化" if rc==0 else "诊断编程日志后重试",
               bitstream_sha256=bh,upstream_revision="100T/OOB/2025.1-1")
    print("RUN_ID="+run.run_id)
    return rc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("doctor", "baseline", "build", "selftest", "collect", "evaluate", "report"))
    parser.add_argument("--observation")
    parser.add_argument("--led-sequence-observed",action="store_true")
    parser.add_argument("--heard-playback",action="store_true")
    args, remaining = parser.parse_known_args()
    if args.action == "doctor":
        return doctor(args)
    if args.action == "baseline":
        return baseline(args)
    if args.action == "build":
        from build_logic import build
        return build()
    if args.action == "selftest":
        from selftest import selftest
        return selftest()
    if args.action == "collect":
        from collect import collect
        return collect()
    if args.action == "evaluate":
        from evaluate import evaluate
        return evaluate()
    if args.action == "report":
        from report import report
        return report()
    parser.error(f"{args.action} 的实现尚未完成；不得将此入口视为阶段通过")


if __name__ == "__main__":
    sys.exit(main())
