"""Independent integer reference. No recorded samples are synthesized here."""
from __future__ import annotations
from dataclasses import dataclass

TICKS_PER_SECOND=100_000_000
FRAME_TICKS=1_000_000


def signed(value,bits):
    return ((int(value)+(1<<(bits-1))) & ((1<<bits)-1))-(1<<(bits-1))


def cic_reference(bits):
    """Definition using previous integrator values and modulo comb differences."""
    integrators=[0,0,0]; delays=[0,0,0]; output=[]
    for index,bit in enumerate(bits):
        old=integrators[:]
        integrators=[signed(old[0]+(1 if bit else -1),24),
                     signed(old[1]+old[0],24), signed(old[2]+old[1],24)]
        if (index+1)%125: continue
        value=integrators[2]
        for stage in range(3):
            before=value;value=signed(value-delays[stage],24);delays[stage]=before
        product=value*281475
        scaled=(abs(product)+(1<<23))>>24
        if product<0: scaled=-scaled
        output.append(max(-32768,min(32767,scaled)))
    return output


@dataclass
class Pairing:
    audio_threshold:int
    accel_threshold:int
    window_ticks:int=5_000_000
    dedup_ticks:int=30_000_000
    prev_audio:int|None=None
    prev_accel:int|None=None
    pending_audio:int|None=None
    pending_accel:int|None=None
    last_joint:int|None=None

    def step(self,t,audio,accel):
        audio_cross=audio is not None and self.prev_audio is not None and self.prev_audio<=self.audio_threshold<audio
        accel_cross=accel is not None and self.prev_accel is not None and self.prev_accel<=self.accel_threshold<accel
        if audio is not None:self.prev_audio=audio
        if accel is not None:self.prev_accel=accel
        for key in ("pending_audio","pending_accel"):
            value=getattr(self,key)
            if value is not None and t-value>self.window_ticks:setattr(self,key,None)
        if audio_cross:self.pending_audio=t
        if accel_cross:self.pending_accel=t
        joint=None
        if self.pending_audio is not None and self.pending_accel is not None:
            if abs(self.pending_audio-self.pending_accel)<=self.window_ticks:
                joint={"t_audio":self.pending_audio,"t_accel":self.pending_accel,
                       "t_confirm":max(self.pending_audio,self.pending_accel)}
                self.pending_audio=None;self.pending_accel=None
                joint["dedup"]=self.last_joint is not None and joint["t_confirm"]-self.last_joint<self.dedup_ticks
                if not joint["dedup"]:self.last_joint=joint["t_confirm"]
        return {"audio_cross":audio_cross,"accel_cross":accel_cross,"joint":joint}


def feature_reference(pcm,xyz,first_pcm_tick,pcm_period=6250,origin=0,end_tick=None,frame_ticks=FRAME_TICKS,available_delay=10004):
    """Fresh Q8 DC state; half-open common 10 ms windows; XYZ uses actual times."""
    records=[]
    dc=0;last_xyz=None; xyz_index=0
    if end_tick is None:end_tick=first_pcm_tick+len(pcm)*pcm_period
    first_frame=origin//frame_ticks
    windows={i:{"sum":0,"n":0,"vmax":None,"xyz_n":0} for i in range(first_frame,(end_tick+frame_ticks-1)//frame_ticks)}
    for i,value in enumerate(pcm):
        t=first_pcm_tick+i*pcm_period
        if not origin<=t<end_tick:continue
        x=int(value);filtered=x-(dc>>8);dc+=((x<<8)-dc)>>8
        w=windows[t//frame_ticks];w["sum"]+=abs(filtered);w["n"]+=1
    for t,x,y,z in xyz:
        t=int(t)
        if not origin<=t<end_tick:continue
        w=windows[t//frame_ticks];w["xyz_n"]+=1
        if last_xyz is not None:
            motion=sum(abs(v-p) for v,p in zip((x,y,z),last_xyz))
            w["vmax"]=max(w["vmax"] or 0,motion)
        last_xyz=(int(x),int(y),int(z))
    for i,w in sorted(windows.items()):
        records.append({"tick":(i+1)*frame_ticks+available_delay,"window_end":(i+1)*frame_ticks,"audio":w["sum"]//160 if w["n"]==160 else None,
                        "accel":w["vmax"],"audio_n":w["n"],"xyz_n":w["xyz_n"]})
    return records
