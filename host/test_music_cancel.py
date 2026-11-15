"""GUI cancellation/triple-entry decisions with spies: no Tk root/UART/API/SQL."""
from types import SimpleNamespace
import unittest
from music_gui import MusicPanel


class Value:
    def __init__(self,value=''):self.value=value
    def get(self):return self.value
    def set(self,value):self.value=value
class Widget(dict):
    def configure(self,**values):self.update(values)
    def delete(self,*args):pass
class Engine:
    def __init__(self):self.cancelled=[];self.submissions=[]
    def cancel(self,identifier):self.cancelled.append(identifier)
    def submit(self,*args,**values):self.submissions.append((args,values))


class GuiCancelTests(unittest.TestCase):
    def setUp(self):
        self.panel=MusicPanel.__new__(MusicPanel);self.calls=[];self.saved=0;self.refreshed=0
        p=self.panel;p.app=SimpleNamespace(action=lambda name,**values:self.calls.append((name,values)),worker=None)
        p.enabled=True;p.busy=True;p.importing=False;p.job={'id':'current','record_id':9,'game':False,'policy':'auto'}
        p.pending={};p.result=None;p.game_ready=None;p.wav=None;p.last_status=None
        p.cancelled_jobs=set();p.cancel_request=None;p.active_retry_id=None;p.worker_unavailable=False
        p.engine=Engine();p.store=SimpleNamespace(setting=lambda *a,**kw:{'high':80,'low':32})
        p.cancel_button=Widget(state='normal');p.progress=Widget(value=30);p.wave=Widget()
        for name in ('title','artist','source','status','stage','details','policy_text','game_text','game_status','game_answer'):
            setattr(p,name,Value())
        p.seconds=Value('20');p.policy=Value('自动');p.wake=Value(False)
        p.save_state=lambda:self.save();p.refresh_history=lambda:self.refresh();p.draw_wave=lambda:None
    def save(self):self.saved+=1
    def refresh(self):self.refreshed+=1
    def worker_ack(self,identifier='current',ok=True,**extra):
        self.panel.receive('music_worker',{'payload':{'id':identifier,'action':'cancelled','ok':ok,'worker_restarted':ok,**extra}})
    def board_ack(self,identifier='current',**values):
        self.panel.receive('music_cancelled',{'job_id':identifier,'reason':'user_cancelled','text':'中止完成','enabled':True,**values})

    def test_record_transfer_match_wait_both_acks_and_preserve_complete_wav(self):
        for phase in ('record','transfer','match'):
            with self.subTest(phase=phase):
                self.setUp();p=self.panel;p.stage.set(phase);p.wav='verified-complete.wav' if phase=='match' else None
                before=p.wav;p.cancel();p.cancel()
                self.assertEqual(p.engine.cancelled,['current'])
                self.assertEqual(self.calls,[('music_cancel',{'job_id':'current'})])
                self.assertTrue(p.busy);self.assertEqual(p.cancel_button['state'],'disabled')
                self.board_ack();self.assertTrue(p.busy)
                self.assertNotIn('music_cancel_ready',[name for name,_ in self.calls])
                self.worker_ack();self.assertFalse(p.busy);self.assertIsNone(p.cancel_request)
                self.assertEqual(p.wav,before);self.assertEqual(self.calls[-1],('music_cancel_ready',{'job_id':'current'}))
                self.assertEqual(p.cancel_button['state'],'disabled')

    def test_worker_ack_first_still_waits_for_board(self):
        self.panel.cancel();self.worker_ack();self.assertTrue(self.panel.busy)
        self.assertNotIn('music_cancel_ready',[name for name,_ in self.calls])
        self.board_ack();self.assertFalse(self.panel.busy)

    def test_manual_retry_cancels_retry_identity_not_previous_board_job(self):
        p=self.panel;p.active_retry_id='retry';p.pending={'retry':'retry'};p.wav='original-complete.wav'
        p.cancel();self.assertEqual(p.engine.cancelled,['retry']);self.assertEqual(self.calls[0][1]['job_id'],'retry')
        self.worker_ack('retry');self.board_ack('retry')
        self.assertFalse(p.busy);self.assertEqual(p.wav,'original-complete.wav');self.assertNotIn('retry',p.pending)

    def test_cancelled_late_events_never_submit_display_or_finish_old_job(self):
        p=self.panel;p.cancel();stage=p.stage.get()
        late=[('music_worker',{'payload':{'id':'current','action':'match_progress','ok':True,'message':'late'}}),
            ('music_worker',{'payload':{'id':'current','action':'match','ok':True,'result':{'matched':True}}}),
            ('music_worker',{'payload':{'id':'current','action':'match','ok':False,'message':'late error'}}),
            ('music_worker',{'payload':{'action':'worker_exit','ok':False,'message':'old exit'}}),
            ('music_exported',{'job':dict(p.job),'metadata':{}}),
            ('music_progress',{'job':dict(p.job),'current':100,'total':100}),
            ('music_complete',{'job':dict(p.job),'result':{'matched':True}}),
            ('music_started',{'job':dict(p.job)}),
            ('music_game_ready',{'job':dict(p.job),'result':{'matched':True}}),
            ('music_game_revealed',{'record':{'round_id':'current'}}),
            ('music_status',{'job_id':'current','status':{}})]
        for kind,message in late:p.receive(kind,message)
        self.assertTrue(p.busy);self.assertEqual(p.stage.get(),stage);self.assertEqual(p.engine.submissions,[])
        self.assertEqual([n for n,_ in self.calls],['music_cancel'])
        self.board_ack();self.worker_ack();finished=p.stage.get()
        for kind,message in late:
            if kind=='music_worker' and message['payload'].get('action')=='worker_exit':continue
            p.receive(kind,message)
        self.assertFalse(p.busy);self.assertEqual(p.stage.get(),finished);self.assertIsNone(p.result)

    def test_late_cancel_ack_cannot_clear_new_job(self):
        p=self.panel;p.cancel()
        new={'id':'new','record_id':10,'game':False,'policy':'auto'}
        p.receive('music_started',{'job':new});self.board_ack(saved_wav='old-cancelled.wav');self.worker_ack()
        self.assertTrue(p.busy);self.assertEqual(p.job['id'],'new')
        self.assertIsNone(p.wav)
        self.board_ack();self.worker_ack();self.assertEqual(p.job['id'],'new')

    def test_failed_board_ack_keeps_busy_and_retry_only_resends_board_cancel(self):
        p=self.panel;p.cancel();self.worker_ack()
        p.receive('music_cancel_failed',{'job_id':'current','text':'板端停止尚未确认'})
        self.assertTrue(p.busy);self.assertEqual(p.cancel_button['state'],'normal')
        p.cancel();self.assertEqual(p.engine.cancelled,['current'])
        self.assertEqual([n for n,_ in self.calls],['music_cancel','music_cancel'])
        self.assertTrue(p.busy);self.board_ack();self.assertFalse(p.busy)

    def test_worker_restart_failure_never_rearms_or_claims_ready(self):
        p=self.panel;p.cancel();self.board_ack();self.worker_ack(ok=False)
        self.assertTrue(p.worker_unavailable);self.assertFalse(p.busy)
        self.assertNotIn('music_cancel_ready',[n for n,_ in self.calls]);self.assertEqual(self.calls[-1][0],'music_disable')
        self.assertIn('未能恢复',p.status.get());before=len(self.calls);p.record();p.start_game()
        self.assertEqual(len(self.calls),before)

    def test_verified_first_wav_returned_by_board_ack_is_retained(self):
        p=self.panel;p.cancel();self.board_ack(saved_wav='verified-first-read.wav');self.worker_ack()
        self.assertEqual(p.wav,'verified-first-read.wav');self.assertIn('完整录音已保留',p.artist.get())

    def test_worker_stop_unconfirmed_preserves_authoritative_error_and_blocks_ready(self):
        p=self.panel;p.cancel();self.board_ack();message='未能确认识曲进程已停止，请关闭软件后重试。'
        self.worker_ack(ok=False,message=message)
        self.assertEqual(p.status.get(),message);self.assertIn('需要确认',p.title.get())
        self.assertTrue(p.worker_unavailable);self.assertNotIn('music_cancel_ready',[n for n,_ in self.calls])

    def test_game_cancel_clears_hidden_answer_without_reveal(self):
        p=self.panel;p.job['game']=True;p.game_ready={'secret':'answer'};p.result={'title':'secret'}
        p.cancel();self.assertIsNone(p.game_ready);self.assertIsNone(p.result)
        self.worker_ack();self.board_ack();self.assertIn('未揭晓',p.game_text.get())

    def test_idle_cancel_and_wrong_identity_acks_do_nothing(self):
        p=self.panel;p.busy=False;p.sync_cancel_button();p.cancel()
        self.assertEqual(self.calls,[]);self.assertEqual(p.engine.cancelled,[])
        p.busy=True;p.cancel();self.board_ack('wrong');self.worker_ack('wrong')
        self.assertTrue(p.busy);self.assertFalse(p.cancel_request['board_ack']);self.assertFalse(p.cancel_request['worker_ack'])

    def test_non_cancelled_completion_retains_original_behavior(self):
        p=self.panel;result={'matched':False,'source':'none','job_id':'current'}
        p.receive('music_complete',{'job':dict(p.job),'result':result})
        self.assertFalse(p.busy);self.assertEqual(p.result,result);self.assertEqual(p.engine.cancelled,[])
        self.assertEqual(p.cancel_button['state'],'disabled')

    def test_normal_and_game_entry_only_arm_and_always_require_triple_knock(self):
        p=self.panel;p.busy=False;p.record()
        self.assertEqual([n for n,_ in self.calls],['music_enable']);self.assertTrue(self.calls[0][1]['wake'])
        self.assertFalse(self.calls[0][1]['game']);self.assertIn('就绪后',p.status.get())
        self.calls.clear();p.start_game()
        self.assertEqual([n for n,_ in self.calls],['music_enable']);self.assertTrue(self.calls[0][1]['wake'])
        self.assertTrue(self.calls[0][1]['game']);self.assertEqual(self.calls[0][1]['policy'],'offline')
        self.assertNotIn('music_start',[n for n,_ in self.calls])

    def test_settings_cannot_disable_triple_gate_or_start_recording(self):
        p=self.panel;p.wake.set(False);p.settings_changed()
        self.assertEqual(self.calls[0],('music_settings',{'seconds':20,'wake':True}))
        self.assertNotIn('music_start',[n for n,_ in self.calls])


if __name__=='__main__':unittest.main(verbosity=2)
