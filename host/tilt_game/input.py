"""Relative three-axis tilt, sample freshness, and guided orientation calibration."""
from collections import deque
import math
import statistics
from .engine import Control


def angles(xyz):
    x,y,z=xyz
    return (math.degrees(math.atan2(x,math.hypot(y,z))),
            math.degrees(math.atan2(y,math.hypot(x,z))))


class TiltInput:
    STALE_SECONDS=.250

    def __init__(self):
        self.serial=None
        self.epoch=None
        self.connected=False
        self.last_seq=None
        self.last_tick=None
        self.last_fresh=None
        self.raw=None
        self.filtered=None
        self.brake=False
        self.phase='idle'
        self.neutral=None
        self.gravity=None
        self.mapping=[]
        self.samples=deque()
        self.hold_since=None
        self.progress=0.
        self.sensitivity=18
        self.reason='请连接开发板，然后进行握持校准。'
        self.received=0
        self.missing=0
        self.events=[]

    @property
    def ready(self):
        return self.phase == 'ready'

    def fresh(self, now):
        return self.connected and self.last_fresh is not None and 0 <= now-self.last_fresh <= self.STALE_SECONDS

    def invalidate(self, reason):
        self.phase='idle'
        self.neutral=None
        self.gravity=None
        self.mapping=[]
        self.samples.clear()
        self.hold_since=None
        self.progress=0
        self.brake=False
        self.reason=reason

    def begin(self):
        self.invalidate('自然握住板子，正面朝上，保持静止约 2 秒。')
        self.phase='neutral'

    def feed(self, message, received_at):
        kind=message['kind']
        if kind == 'identity':
            serial=message['device']['usb_serial']
            if serial != self.serial:
                self.serial=serial
                self.invalidate('已连接开发板，请先校准自然握持姿势。')
            return
        if kind == 'status':
            self.connected=bool(message.get('connected'))
            if not self.connected:
                self.last_fresh=None
                self.invalidate('连接已中断，重连后需要重新校准。')
            return
        if kind in ('reset','stopped'):
            self.last_seq=self.last_tick=None
            self.last_fresh=None
            self.raw=self.filtered=None
            self.epoch=message.get('epoch')
            self.invalidate('板端时间已重置，请重新校准。')
            if kind == 'stopped':
                self.connected=False
            return
        if kind != 'data':
            return
        if self.epoch is not None and self.epoch != message.get('epoch',self.epoch):
            self.last_seq=self.last_tick=None
            self.filtered=None
            self.last_fresh=None
            self.invalidate('检测到新板端时间，请重新校准。')
        self.epoch=message.get('epoch',self.epoch)
        row=message['row']
        if not row.get('adxl_configured',False) or not row.get('adxl_id_ok',False):
            self.last_fresh=None
            self.brake=False
            self.reason='三轴传感器未就绪，请检查初始化。'
            return
        records=message.get('xyz',())
        for sample in records:
            seq=sample['seq']
            delta=None if self.last_seq is None else (seq-self.last_seq)&0xffffffff
            if delta is not None and (delta==0 or delta>=0x80000000):
                continue
            tick=sample['tick']
            if self.last_tick is not None and tick <= self.last_tick:
                continue
            xyz=tuple(float(sample[k]) for k in ('x','y','z'))
            if not all(math.isfinite(v) for v in xyz):
                continue
            norm=math.sqrt(sum(v*v for v in xyz))
            if norm < 100:
                continue
            dt=.0053 if self.last_tick is None else min(.1,(tick-self.last_tick)/1e8)
            self.last_seq=seq
            self.last_tick=tick
            self.received += 1
            self.missing += max(0,(delta or 1)-1)
            age=max(0,(row['tick']-tick)/1e8)
            if age > self.STALE_SECONDS:
                continue
            if self.gravity and not .60*self.gravity < norm < 1.5*self.gravity:
                continue
            a=1-math.exp(-dt/.055)
            self.raw=xyz
            self.filtered=xyz if self.filtered is None else tuple(p+(v-p)*a for p,v in zip(self.filtered,xyz))
            self.last_fresh=received_at-age
            self._calibrate(tick/1e8,xyz)
        self.brake=bool(row.get('buttons',0)&16) if self.fresh(received_at) else False

    def _calibrate(self, t, xyz):
        if self.phase == 'neutral':
            self.samples.append((t,xyz))
            while self.samples and t-self.samples[0][0] > 2.12:
                self.samples.popleft()
            elapsed=t-self.samples[0][0]
            self.progress=min(1,elapsed/2)
            if elapsed < 2 or len(self.samples)<100:
                return
            axes=list(zip(*(v for _,v in self.samples)))
            mean=tuple(statistics.mean(a) for a in axes)
            gravity=math.sqrt(sum(v*v for v in mean))
            # The existing Nexys board reads about -750 on Z when face-up.
            # Mounting sign is learned by the guided axis mapping, not assumed.
            if abs(mean[2]) < gravity*.55:
                self.reason='请让板子正面朝上，再保持静止。'
                return
            if max(statistics.pstdev(a) for a in axes)>gravity*.025:
                self.reason='板子还在晃动，请自然握稳约 2 秒。'
                return
            self.neutral=angles(mean)
            self.gravity=gravity
            self.phase='right'
            self.progress=0
            self.hold_since=None
            self.reason='向你希望小球右移的方向轻倾，保持片刻。'
        elif self.phase in ('right','forward'):
            now_angles=angles(self.filtered)
            delta=[v-p for v,p in zip(now_angles,self.neutral)]
            axis=max(range(2),key=lambda i:abs(delta[i])) if self.phase=='right' else 1-self.mapping[0][0]
            if abs(delta[axis]) < 6 or (self.phase=='forward' and abs(delta[axis])<abs(delta[1-axis])*.7):
                self.hold_since=None
                self.progress=0
                return
            if self.hold_since is None:
                self.hold_since=t
            self.progress=min(1,(t-self.hold_since)/.35)
            if self.progress < 1:
                return
            self.mapping.append((axis,1 if delta[axis]>0 else -1))
            self.hold_since=None
            self.progress=0
            if self.phase=='right':
                self.phase='forward'
                self.reason='回到自然姿势，再向前轻倾，让小球向屏幕上方移动。'
            else:
                self.phase='return'
                self.reason='回到刚才的自然握持姿势，即将就绪。'
        elif self.phase=='return':
            delta=[v-p for v,p in zip(angles(self.filtered),self.neutral)]
            if max(abs(v) for v in delta)>3:
                self.hold_since=None
                return
            if self.hold_since is None:
                self.hold_since=t
            self.progress=min(1,(t-self.hold_since)/.4)
            if self.progress>=1:
                self.phase='ready'
                self.reason='校准完成。轻轻倾斜移动，按住中键刹车。'
                self.events.append({'kind':'calibrated','serial':self.serial,
                                    'neutral':self.neutral,'mapping':list(self.mapping),
                                    'gravity_raw':self.gravity})

    def control(self, now):
        if not self.ready or not self.fresh(now):
            return Control()
        delta=[v-p for v,p in zip(angles(self.filtered),self.neutral)]
        result=[]
        for axis,sign in self.mapping:
            value=delta[axis]*sign
            value=math.copysign(max(0,abs(value)-1.2)/max(1,self.sensitivity-1.2),value)
            result.append(max(-1,min(1,value)))
        return Control(result[0],-result[1],self.brake)
