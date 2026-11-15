"""Discover FT2232 channel B; never bind application operation to a lab board."""
from dataclasses import asdict,dataclass
import re

@dataclass(frozen=True)
class BoardCandidate:
    serial:str
    port:str
    description:str=''
    location:str=''
    def record(self):return asdict(self)
    @property
    def label(self):return f'{self.serial}  ·  {self.port}'

def candidates(ports=None):
    if ports is None:
        from serial.tools.list_ports import comports
        ports=comports()
    result={}
    for p in ports:
        if (p.vid,p.pid)!=(0x0403,0x6010):continue
        raw=p.serial_number or '';hw=p.hwid or ''
        # FTDI VCP includes the interface suffix in the serial (A is JTAG, B UART).
        if not re.fullmatch(r'[A-Za-z0-9_-]{3,64}B',raw):continue
        serial=raw[:-1]
        candidate=BoardCandidate(serial,p.device,p.description or '',getattr(p,'location','') or '')
        if serial in result:raise RuntimeError('同一USB序列号出现多个UART，不能唯一关联板子')
        result[serial]=candidate
    return sorted(result.values(),key=lambda x:(x.serial,x.port))

def select_board(serial=None,ports=None):
    found=candidates(ports)
    if serial:found=[x for x in found if x.serial==serial]
    if not found:raise RuntimeError('未找到开发板UART：请连接PROG/UART、上电，并检查USB驱动')
    if len(found)!=1:raise RuntimeError('检测到多块板，请在设备列表中选择一块')
    return found[0]
