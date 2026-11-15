"""Targeted SRAM configuration through native FTDI or existing WinUSB drivers."""
import json,re,time
from pathlib import Path
from app_paths import RESOURCE_ROOT
from audit import ROOT,sha256,write_json
from hardware import hardware_lock
from device_discovery import select_board

def release():
    value=json.loads((RESOURCE_ROOT/'release_manifest.json').read_text(encoding='utf8'))
    for row in value['resources']:
        p=RESOURCE_ROOT/row['path']
        if not p.is_file() or sha256(p)!=row['sha256']:raise ValueError('软件资源校验失败：'+row['path'])
    return value

def compatible_id(text):
    ids=re.findall(r'(?:IDCODE\s*=|tap/device found:)\s*(?:0x)?([0-9a-fA-F]{8})',text,re.I)
    return len(ids)==1 and (int(ids[0],16)&0x0fffffff)==0x03631093

def openocd_config(serial):
    if not re.fullmatch(r'[A-Za-z0-9_-]{3,64}',serial):raise ValueError('invalid USB serial')
    return ('adapter driver ftdi\nftdi vid_pid 0x0403 0x6010\nftdi channel 0\nftdi serial '+serial+
            '\nftdi layout_init 0x0088 0x008b\nreset_config none\ntransport select jtag\nadapter speed 1000\n'
            'jtag newtap recorder tap -irlen 6 -ignore-version -expected-id 0x03631093\npld device virtex2 recorder.tap 1\n')

def program_board(run,serial):
    board=select_board(serial);manifest=release();bit=RESOURCE_ROOT/'firmware/recorder_top.bit'
    # Raw user paths never enter Tcl: the fixed verified file is copied into the
    # programming working directory and Tcl uses a fixed relative filename.
    import shutil
    shutil.copy2(bit,run.path/'recorder_top.bit')
    cfg=run.path/'target.cfg';cfg.write_text(openocd_config(board.serial),encoding='utf8')
    native=RESOURCE_ROOT/'tools/xc3sprog/xc3sprog.exe';ocd=RESOURCE_ROOT/'tools/openocd/openocd.exe'
    cable='nexys_monitor';(run.path/'cablelist.txt').write_text(cable+' ftdi 1000000 0x0403:0x6010::0:0x88:0x8b:0x00:0x00\n')
    selected=None
    with hardware_lock(run):
        rc,out=run.command([native,'-L','-c',cable,'-s',board.serial+'A','-j'],
                           '通过常规FTDI驱动扫描所选板JTAG',cwd=run.path,timeout=20)
        if rc==0 and compatible_id(out):selected='ftd2xx'
        elif rc==0 and re.search(r'(?:IDCODE|Device ID|JTAG chain)',out,re.I):
            raise RuntimeError('JTAG目标不是受支持的XC7A100T；不下载')
        if selected is None:
            rc,out=run.command([ocd,'-f',cfg,'-c','init; shutdown'],'通过现有WinUSB扫描同一序列号JTAG',cwd=run.path,timeout=20)
            if rc or not compatible_id(out):raise RuntimeError('未找到匹配的XC7A100T下载接口：请检查驱动或其他程序占用，详见诊断日志')
            selected='winusb'
        if selected=='ftd2xx':
            rc,out=run.command([native,'-L','-c',cable,'-s',board.serial+'A','recorder_top.bit'],
                               '向所选板SRAM加载软件配套位流',cwd=run.path,timeout=120)
            if rc:raise RuntimeError('FTDI位流加载失败；保留日志，不继续采集')
        else:
            rc,out=run.command([ocd,'-f',cfg,'-c','init; pld load 0 recorder_top.bit; echo [virtex2 read_stat 0]; shutdown'],
                               '向所选板SRAM加载并读回配置状态',cwd=run.path,timeout=120)
            match=re.search(r'status register: (0x[0-9a-fA-F]+)',out);stat=int(match[1],16) if match else 0
            if rc or not(stat&(1<<14)) or stat&1:raise RuntimeError('FPGA配置状态检查失败')
    time.sleep(.5)
    result={**manifest['firmware'],'success':True,'usb_serial':board.serial,'uart_port_at_programming':board.port,
            'backend':selected,'configuration':'SRAM','programming_run_id':run.run_id,
            'verification':'JTAG target plus UART build handshake required'}
    write_json(run.path/'programming.json',result);write_json(ROOT/'state/active_device.json',result)
    run.event('targeted_sram_programmed',**result)
    return result
