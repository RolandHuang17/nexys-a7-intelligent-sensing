"""Bounded serial-owner display publisher and edge-only switch shortcuts."""
import time,secrets
from panel_protocol import Phase,PanelState,UNKNOWN_PROGRESS,send_panel

class SwitchShortcuts:
    """SW15 arms music mode; a fresh triple knock starts recording."""
    def __init__(self):self.reset()
    def reset(self):self.previous=None
    def update(self,switches):
        switches=int(switches)&0xffff;previous=self.previous;self.previous=switches
        enabled=bool(switches&0x8000)
        if previous is None:return ['enter'] if enabled else []
        if enabled==bool(previous&0x8000):return []
        return ['enter'] if enabled else ['exit']


def result_phase(result):
    if result.get('matched'):return Phase.PASS
    reason=str(result.get('reason',''))
    errors=('error','timeout','rate_limit','cooldown','unavailable','missing','network','failed')
    return Phase.ERROR if any(word in reason for word in errors) else Phase.MISS

class PanelDisplay:
    MIN_INTERVAL=.2
    HEARTBEAT=1.0
    def __init__(self,run,emit,clock=time.monotonic,state_path=None):
        self.run=run;self.emit=emit;self.clock=clock;self.state_path=state_path;self.last_applied=None;self.reconnected()
    def reconnected(self):
        self.session=secrets.randbits(32) or 1;self.sequence=1;self.synced=False;self.disabled=False
        self.failures=0;self.next_send=getattr(self,'next_send',0.);self.last_sent=-float('inf');self.dirty=True
        self.phase=Phase.NORMAL;self.progress=UNKNOWN_PROGRESS;self.value=0
        self.record_id=0;self.job_id=None;self.match_started=None;self.last_status=None;self.finished=False;self.last_applied=None;self.hold_until=None
    def _advance_sequence(self):
        self.sequence=(self.sequence+1)&0xffffffff
        if not self.sequence:self.sequence=1;self.synced=False
    def _notice(self,text):
        if text!=self.last_status:self.last_status=text;self.emit('panel_status',text=text)
    def bind_job(self,job):
        self.job_id=job['id'];self.record_id=int(job['record_id'])&0xffffffff
        self.phase=Phase.READY;self.progress=UNKNOWN_PROGRESS;self.value=0;self.match_started=None;self.dirty=True;self.finished=False;self.hold_until=None
        self._advance_sequence()
    def update(self,phase,*,record_id=None,job_id=None,progress=UNKNOWN_PROGRESS,value=0):
        phase=Phase(phase)
        if phase==Phase.SYNC:raise ValueError('SYNC is owned by the serial display publisher')
        if job_id is not None and job_id!=self.job_id:return False
        if record_id is not None and int(record_id)!=self.record_id:return False
        if job_id is not None and phase in (Phase.MATCH,Phase.HOLD,Phase.TRANSFER) and self.finished:return False
        PanelState(phase,int(progress),int(value)).pack()
        state=(phase,int(progress),int(value))
        if state!=(self.phase,self.progress,self.value):
            self.phase,self.progress,self.value=state;self.dirty=True;self._advance_sequence()
            self.hold_until=self.clock()+self.value/1000 if phase==Phase.HOLD else None
        elif phase==Phase.FAVORITE:
            self.dirty=True;self._advance_sequence()  # A new explicit favourite needs a new acknowledgment.
        if phase==Phase.MATCH and self.match_started is None:self.match_started=self.clock()
        elif phase not in (Phase.MATCH,Phase.HOLD):self.match_started=None
        return True
    def on_music_message(self,kind,data,music):
        job=data.get('job')
        if kind=='music_started':self.bind_job(job)
        elif kind=='music_mode':
            if not music.current:
                self.update(Phase.READY if data['enabled'] else Phase.NORMAL)
                if music.last:self.record_id=int(music.last['record_id'])
        elif kind=='music_progress':
            if not job or job.get('id')!=self.job_id:return
            total=max(1,int(data['total']));self.update(Phase.TRANSFER,job_id=job['id'],progress=min(1000,int(data['current'])*1000//total))
        elif kind=='music_exported':
            if job and job.get('id')==self.job_id:self.update(Phase.MATCH,job_id=job['id'])
        elif kind=='music_game_ready':
            if self.update(Phase.GAME_READY,job_id=job['id']):self.finished=True
        elif kind=='music_game_revealed':
            record=data['record']
            if record.get('round_id')!=self.job_id:return
            result=record['machine_result'];self.update(result_phase(result),value=1 if result_phase(result)==Phase.ERROR else max(0,int(data['record']['machine_s']*1000)))
        elif kind=='music_complete':
            if not job or job['id']!=self.job_id:return
            self.finished=True
            if not music.enabled:self.update(Phase.NORMAL)
            elif job and job['id']==self.job_id and not job.get('game'):
                result=data['result'];phase=result_phase(result)
                value=1 if phase==Phase.ERROR else max(0,int(float(result.get('online_elapsed_s') or 0)*1000))
                self.update(phase,job_id=job['id'],value=value)
        elif kind=='music_favourite':self.update(Phase.FAVORITE)
        elif kind=='music_cancelled':
            if data.get('job_id') is not None and data['job_id']!=self.job_id:return
            self.finished=True
            self.update((Phase.HOLD if music.enabled else Phase.NORMAL) if data.get('reason')=='user_cancelled' else Phase.ERROR,
                value=0 if data.get('reason')=='user_cancelled' else 1)
        elif kind=='music_cancel_ready':
            if data.get('job_id')!=self.job_id:return
            self.update(Phase.READY if music.enabled else Phase.NORMAL)
    def snapshot(self):
        return {'session':self.session,'display_seq':self.sequence,'record_id':self.record_id,'job_id':self.job_id,
            'desired_phase':int(self.phase),'desired_phase_name':self.phase.name,'progress':self.progress,'value':self.value,
            'synced':self.synced,'disabled':self.disabled,'consecutive_failures':self.failures,'last_applied':self.last_applied}
    def _checkpoint(self):
        if self.state_path is not None:
            from audit import write_json,now
            try:write_json(self.state_path,{'time':now(),**self.snapshot()})
            except OSError:pass
    def poll(self,device):
        if self.disabled:return
        current=self.clock()
        if current<self.next_send:return
        if self.synced and self.phase==Phase.HOLD and self.hold_until is not None:
            remaining=min(0xffffffff,max(0,int((self.hold_until-current)*1000)))
            if remaining//1000!=self.value//1000:self.value=remaining;self.dirty=True;self._advance_sequence()
        if self.synced and self.phase==Phase.MATCH and self.match_started is not None:
            elapsed=min(0xffffffff,max(0,int((current-self.match_started)*1000)))
            if elapsed//1000!=self.value//1000:self.value=elapsed;self.dirty=True;self._advance_sequence()
        if self.synced and not self.dirty and current-self.last_sent<self.HEARTBEAT:return
        if not self.synced:
            state=PanelState(Phase.SYNC,session=self.session,display_seq=self.sequence)
        else:
            state=PanelState(self.phase,self.progress,self.value,self.session,self.sequence)
        self.next_send=current+self.MIN_INTERVAL;self.last_sent=current
        try:
            ack=send_panel(device,state,self.record_id)
            if ack==7:raise ValueError('PANEL payload rejected')
            self.failures=0
            if ack==0:
                if not self.synced:self.synced=True;self.dirty=True;self._advance_sequence()
                else:
                    self.dirty=False;self.last_applied={'phase':int(state.phase),'phase_name':Phase(state.phase).name,
                        'progress':state.progress,'value':state.value,'record_id':self.record_id,
                        'session':state.session,'display_seq':state.display_seq,'host_monotonic':current}
                self._notice('板端显示已连接')
            else:
                self.synced=False;self.dirty=True;self._notice('板端显示等待会话同步')
        except Exception as error:
            self.failures+=1
            self.run.event('panel_display_failed',attempt=self.failures,error=repr(error))
            if self.failures>=3:
                self.disabled=True;self._notice('板端显示暂不可用，监测继续；重连后重试')

        self._checkpoint()
