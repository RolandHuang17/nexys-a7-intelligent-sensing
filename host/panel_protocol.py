"""Display-only PANEL command; never changes acquisition or music state."""
from dataclasses import dataclass
from enum import IntEnum
import struct

PAYLOAD=struct.Struct('<BBHIII')
UNKNOWN_PROGRESS=0xffff
class Phase(IntEnum):
    NORMAL=0
    READY=1
    TRANSFER=2
    MATCH=3
    PASS=4
    MISS=5
    ERROR=6
    HOLD=7
    GAME_READY=8
    FAVORITE=9
    SYNC=0xfe

@dataclass(frozen=True)
class PanelState:
    phase:int=Phase.NORMAL
    progress:int=UNKNOWN_PROGRESS
    value:int=0
    session:int=0
    display_seq:int=0
    version:int=1
    def pack(self):
        if self.version!=1 or self.phase not in Phase._value2member_map_:raise ValueError('Invalid PANEL version/phase')
        if self.progress!=UNKNOWN_PROGRESS and not 0<=self.progress<=1000:raise ValueError('Invalid PANEL progress')
        if any(not 0<=n<=0xffffffff for n in (self.value,self.session,self.display_seq)):raise ValueError('Invalid PANEL counter')
        return PAYLOAD.pack(self.version,self.phase,self.progress,self.value,self.session,self.display_seq)
    @classmethod
    def unpack(cls,payload):
        if len(payload)!=PAYLOAD.size:raise ValueError('PANEL payload must be 16 bytes')
        version,phase,progress,value,session,seq=PAYLOAD.unpack(payload)
        state=cls(phase,progress,value,session,seq,version);state.pack();return state

def send_panel(device,state,event_id=0):
    """Bound an optional display attempt to 30ms and restore serial settings."""
    previous=device.serial.timeout
    try:
        device.serial.timeout=min(.01,previous) if previous is not None else .01
        reply=device.request('PANEL',state.pack(),event_id=int(event_id)&0xffffffff,timeout=.03,retries=0)
    finally:device.serial.timeout=previous
    if len(reply.payload)!=1 or reply.payload[0] not in (0,1,7):raise ValueError('Invalid PANEL acknowledgment')
    return reply.payload[0]
