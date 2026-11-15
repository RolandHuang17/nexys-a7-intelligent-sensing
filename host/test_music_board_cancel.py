"""Real protocol/workflow tests over a fake UART; no hardware, API or user DB."""
import json,queue,struct,tempfile,threading,time,unittest,wave,zlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import music_protocol
from music_board import MusicBoard,MusicCancelled
from music_store import MusicStore
from monitor_service import MonitorService
from panel_control import PanelDisplay
from panel_protocol import Phase
from protocol import Frame

class UART:
    def __init__(self):
        self.record_id=14;self.state=3;self.active=True;self.enabled=True;self.wake=True;self.game=False
        self.rate=8000;self.raw=b''.join(struct.pack('<h',i-240) for i in range(480));self.target=480
        self.calls=[];self.reads=0;self.acks=0;self.starts=0;self.abort_error=0;self.after_read=None
    def frame(self,error=0):
        p=bytearray(128);p[0]=error;p[1]=1;p[2]=self.state
        p[3]=int(self.enabled)|int(self.wake)<<1|int(self.game)<<2|int(self.active)<<3|int(self.rate==8000)<<4
        samples=len(self.raw)//2 if self.state==3 else 0
        for offset,value in ((4,self.record_id),(8,self.target),(12,samples),(16,self.rate),(20,zlib.crc32(self.raw)),(124,160000)):
            struct.pack_into('<I',p,offset,value)
        for offset,value in ((24,12500),(32,12500+max(0,samples-1)*12500),(48,0),(56,100000000)):
            struct.pack_into('<Q',p,offset,value)
        return Frame(143,event_id=self.record_id,payload=bytes(p))
    def request(self,command,payload=b'',event_id=0,**kwargs):
        self.calls.append((command,payload,event_id,kwargs))
        if command=='ARM':return Frame(133,payload=b'\0')
        if command!='MUSIC':raise AssertionError('Unexpected command: '+str(command))
        op=payload[0]
        if op==2:return self.frame()
        if op==0:
            if self.state!=0 or self.active:return self.frame(1)
            flags=payload[1];self.enabled=bool(flags&1);self.wake=bool(flags&2);self.game=bool(flags&4)
            self.rate=8000 if flags&8 else 16000;self.target=struct.unpack_from('<I',payload,4)[0]
            return self.frame()
        if op==1:self.starts+=1;raise AssertionError('Capture bypassed triple knocks')
        if op==3:
            offset,count=struct.unpack_from('<IH',payload,1)
            assert event_id==self.record_id and self.state==3
            h=bytearray(32);h[1]=1
            struct.pack_into('<IIHHII',h,4,self.record_id,offset,count,self.rate,len(self.raw)//2,zlib.crc32(self.raw))
            self.reads+=1
            if self.after_read:self.after_read(self.reads)
            return Frame(143,event_id=event_id,payload=bytes(h)+self.raw[2*offset:2*(offset+count)])
        if op==4:self.acks+=1;self.state=0;return self.frame()
        if op==5:self.state=0;self.active=False;return self.frame()
        if op==6:
            if self.abort_error:return self.frame(self.abort_error)
            if event_id!=self.record_id:return self.frame(3)
            self.state=0;self.active=False;return self.frame()
        raise AssertionError('Unknown music operation')

class BoardCancellationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.events=[];self.messages=[];self.d=UART()
        s=MonitorService.__new__(MonitorService);self.s=s
        s.run_record=SimpleNamespace(path=self.root/'session',run_id='fake-session',event=lambda kind,**data:self.events.append((kind,data)))
        s.run_record.path.mkdir();s.publish=self.messages.append;s.commands=queue.Queue();s.cancel_commands=queue.Queue();s.panel_commands=queue.Queue()
        s.last={'mode':3,'armed':False,'buttons':0};s.stop_event=threading.Event();s.epoch=1;s.fft_job=None;s.programming={'build_id':'test'}
        s.panel=PanelDisplay(s.run_record,s.emit);s.panel.disabled=True;s.poll=lambda d,force=False:None
        self.store=MusicStore(self.root/'music')
        with patch('music_board.MusicStore',return_value=self.store):self.board=MusicBoard(s)
        s.music=self.board;self.board.enabled=True;self.board.settings['seconds']=20;self.board.center_seen=0
        self.board.last=music_protocol.parse_status(self.d.frame())
    def tearDown(self):self.temp.cleanup()
    def job(self,identifier='current',stage='recording',repeat=False):
        job={'id':identifier,'record_id':self.d.record_id,'policy':'auto','game':False,'verify_repeat':repeat,
            'directory':str(self.root/'session/music'/identifier),'clock':None}
        self.board.current=job;self.board.stage=stage;self.s.panel.bind_job(job);return job
    def messages_of(self,kind):return [m for m in self.messages if m['kind']==kind]
    def cancel(self,identifier='current'):
        self.s.send('music_cancel',job_id=identifier);self.s.cancel_hook(self.d)

    def test_abort_is_addressed_and_rejection_never_looks_like_success(self):
        row=music_protocol.abort(self.d,14)
        self.assertEqual(self.d.calls[-1],('MUSIC',b'\x06',14,{'timeout':1}))
        self.assertEqual((row['state'],row['flags']&8),(0,0))
        with self.assertRaises(RuntimeError):music_protocol.abort(self.d,13)
        self.assertEqual(self.d.acks,0)

    def test_recording_cancel_drops_current_without_ack_or_history_mutation(self):
        job=self.job();self.d.state=2
        self.store.save_online('current','hash','running',details={'provider':'shazamio'})
        before=self.store.online('current');self.cancel()
        self.assertIsNone(self.board.current);self.assertEqual(self.board.cancel_waiting,'current');self.assertEqual(self.d.acks,0)
        self.assertEqual(self.store.online('current'),before);self.assertEqual(self.store.history(),[])
        self.assertFalse(self.d.wake);self.assertEqual(self.d.starts,0)
        self.assertEqual(self.messages_of('music_cancelled')[-1]['job_id'],'current')
        self.assertEqual(json.loads((Path(job['directory'])/'cancelled.json').read_text(encoding='utf8'))['stage'],'recording')

    def test_abort_error_keeps_job_and_emits_failure_not_success_or_reconnect(self):
        job=self.job();self.d.abort_error=7;self.cancel()
        self.assertIs(self.board.current,job);self.assertEqual(self.board.stage,'recording')
        self.assertEqual(self.board.cancel_waiting,'current');self.assertEqual(self.d.acks,0)
        self.assertEqual(len(self.messages_of('music_cancel_failed')),1);self.assertEqual(self.messages_of('music_cancelled'),[])
        self.assertFalse(any(k=='monitor_connection_error' for k,_ in self.events))

    def test_stale_cancel_cannot_mutate_new_job_or_its_panel(self):
        job=self.job('new');self.s.panel.update(Phase.MATCH,job_id='new');self.cancel('old')
        self.assertIs(self.board.current,job);self.assertEqual(self.d.calls,[])
        self.assertEqual((self.s.panel.job_id,self.s.panel.phase),('new',Phase.MATCH))
        self.assertTrue(self.messages_of('music_cancelled')[-1]['ignored']);self.assertIsNone(self.board.cancel_waiting)

    def test_matching_cancel_retains_saved_wav_and_committed_history(self):
        job=self.job(stage='matching');self.d.state=0
        folder=Path(job['directory']);folder.mkdir(parents=True);wav=folder/'saved.wav'
        with wave.open(str(wav),'wb') as w:w.setparams((1,2,8000,0,'NONE','not compressed'));w.writeframes(self.d.raw)
        job['metadata']={'wav':str(wav)};before=wav.read_bytes()
        self.store.record_result('previous',{'matched':False,'source':'none'},'auto',wav,'hash');history=self.store.history()
        self.cancel()
        self.assertEqual(wav.read_bytes(),before);self.assertEqual(self.store.history(),history)
        self.assertEqual(self.messages_of('music_cancelled')[-1]['saved_wav'],str(wav));self.assertEqual(self.d.acks,0)

    def transfer_cancel(self,after_poll=False,repeat=False):
        job=self.job(repeat=repeat);observed=[];real_export=music_protocol.export
        if after_poll:
            def poll(d,force=False):self.s.send('music_cancel',job_id='current');self.s.cancel_hook(d)
            self.s.poll=poll
        else:
            target=3 if repeat else 1
            self.d.after_read=lambda count:self.s.send('music_cancel',job_id='current') if count==target else None
        def export(*args,**kwargs):
            callback=kwargs['on_progress']
            def progress(n,total):
                try:callback(n,total)
                except MusicCancelled:observed.append(True);raise
            kwargs['on_progress']=progress;return real_export(*args,**kwargs)
        with patch('music_board.export',side_effect=export):self.board.step(self.d,force=True)
        self.assertEqual(observed,[True]);self.assertIsNone(self.board.current);self.assertEqual(self.board.stage,'idle')
        self.assertEqual(self.d.acks,0);self.assertEqual(self.messages_of('music_exported'),[])
        self.assertFalse(any(k=='monitor_connection_error' for k,_ in self.events))
        return job
    def test_transfer_cancel_before_poll_never_acks_exports_or_matches(self):self.transfer_cancel()
    def test_transfer_cancel_arriving_during_poll_is_checked_after_poll(self):self.transfer_cancel(after_poll=True)
    def test_repeat_cancel_keeps_first_verified_wav(self):
        self.transfer_cancel(repeat=True)
        saved=self.messages_of('music_cancelled')[-1]['saved_wav'];self.assertTrue(Path(saved).is_file())
        with wave.open(saved,'rb') as w:self.assertEqual(w.readframes(w.getnframes()),self.d.raw)

    def test_cancel_barrier_needs_correct_ready_ack_then_fresh_quiet_period(self):
        self.job();self.cancel();self.board.key_quiet_until=0
        self.assertEqual(self.s.panel.phase,Phase.HOLD)
        self.board.step(self.d,force=True,allow_export=False);self.assertFalse(self.d.wake)
        self.board.control('music_cancel_ready',{'job_id':'old'},self.d)
        self.board.step(self.d,force=True,allow_export=False);self.assertFalse(self.d.wake)
        with self.assertRaises(RuntimeError):self.board.control('music_enable',{},self.d)
        self.board.control('music_cancel_ready',{'job_id':'current'},self.d)
        self.assertIsNone(self.board.cancel_waiting);self.assertFalse(self.d.wake);self.assertEqual(self.s.panel.phase,Phase.READY)
        self.board.key_quiet_until=0;self.board.step(self.d,force=True,allow_export=False)
        self.assertTrue(self.d.wake);self.assertEqual(self.d.starts,0)

    def test_cancel_barrier_ignores_late_manual_result_and_conflicting_old_cancel(self):
        self.job();self.cancel()
        self.board.control('music_idle_result',{'result':{'job_id':'current','matched':True}},self.d)
        self.assertIsNone(self.board.result);self.assertEqual(self.s.panel.phase,Phase.HOLD)
        before=len(self.d.calls);self.cancel('old')
        self.assertEqual(self.board.cancel_waiting,'current');self.assertEqual(len(self.d.calls),before)
        self.assertTrue(self.messages_of('music_cancelled')[-1]['ignored'])

    def test_config_failure_quarantines_fresh_hardware_record_until_same_cancel_retried(self):
        self.job()
        with patch('music_board.configure',side_effect=RuntimeError('fixture: config timed out after abort')):self.cancel()
        self.assertIsNone(self.board.current);self.assertEqual(self.board.cancel_waiting,'current')
        self.assertEqual(self.messages_of('music_cancelled'),[])
        # Fault injection: the unmuted board captured a new record before CONFIG ACK.
        self.d.record_id=15;self.d.state=2;self.d.active=True
        self.board.step(self.d,force=True,allow_export=False)
        self.assertIsNone(self.board.current);self.assertEqual(self.messages_of('music_started'),[])
        before=len(self.d.calls);self.cancel('old')
        self.assertEqual(len(self.d.calls),before);self.assertEqual(self.board.cancel_waiting,'current')
        self.cancel('current')
        abort_ids=[event for command,payload,event,_ in self.d.calls if command=='MUSIC' and payload==b'\x06']
        self.assertEqual(abort_ids,[14,15]);self.assertEqual((self.d.state,self.d.active,self.d.wake),(0,False,False))
        self.assertEqual(self.messages_of('music_cancelled')[-1]['job_id'],'current')

    def test_enable_and_legacy_start_only_arm_and_cannot_bypass_knocks(self):
        self.board.enabled=False;self.d.state=0;self.d.active=False
        self.board.control('music_enable',{'seconds':20,'wake':False},self.d)
        self.board.control('music_start',{},self.d)
        self.assertTrue(self.board.settings['wake']);self.assertFalse(self.d.wake)
        self.board.key_quiet_until=0;self.board.step(self.d,force=True,allow_export=False)
        self.assertTrue(self.d.wake);self.assertEqual(self.d.starts,0);self.assertIsNone(self.board.current)
        self.assertEqual(self.messages_of('music_started'),[])

    def test_legacy_weak_knock_profile_cannot_lower_floor_and_stronger_profile_survives(self):
        self.board.enabled=False;self.d.state=0;self.d.active=False
        self.board.control('music_enable',{'seconds':20,'high':50,'low':20},self.d)
        self.assertEqual((self.board.settings['high'],self.board.settings['low']),(300,80))
        self.board.control('music_settings',{'high':50,'low':20},self.d)
        self.assertEqual((self.board.settings['high'],self.board.settings['low']),(300,80))
        self.board.control('music_settings',{'high':400,'low':120},self.d)
        self.assertEqual((self.board.settings['high'],self.board.settings['low']),(400,120))

    def test_settings_force_wake_except_cancel_quiet_and_happy_export_unchanged(self):
        self.d.state=0;self.d.active=False;self.board.wake_muted=False
        self.board.control('music_settings',{'wake':False},self.d)
        self.assertTrue(self.board.settings['wake']);self.assertTrue(self.d.wake)
        self.board.cancel_waiting='cancel';self.board.wake_muted=True
        self.board.control('music_settings',{'wake':False},self.d)
        self.assertTrue(self.board.settings['wake']);self.assertFalse(self.d.wake)
        # A non-cancelled frozen recording still follows the exact full PCM path.
        self.board.cancel_waiting=None;self.board.wake_muted=False;self.d.state=3;self.d.active=True;self.d.target=480
        job=self.job();self.board.step(self.d,force=True)
        self.assertIs(self.board.current,job);self.assertEqual(self.board.stage,'matching');self.assertEqual(self.d.acks,1)
        message=self.messages_of('music_exported')[-1];self.assertEqual(message['metadata']['crc32'],zlib.crc32(self.d.raw))
        with wave.open(message['metadata']['wav'],'rb') as w:self.assertEqual(w.readframes(w.getnframes()),self.d.raw)

if __name__=='__main__':unittest.main()
