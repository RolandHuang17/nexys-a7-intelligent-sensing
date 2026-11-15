"""Board panel contracts; fake clocks/UART replies, no Tk/serial/API/database.

These validate host decisions and packet bounds. They are not physical evidence.
"""
import struct
import queue
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from panel_protocol import Phase,PanelState,UNKNOWN_PROGRESS,send_panel
from panel_control import PanelDisplay,SwitchShortcuts,result_phase
from protocol import COMMANDS,Frame


class Clock:
    def __init__(self):self.now=100.
    def __call__(self):return self.now
    def advance(self,seconds=.201):self.now+=seconds


class Device:
    def __init__(self,replies=None,timeout=.1):
        self.serial=SimpleNamespace(timeout=timeout);self.calls=[];self.replies=list(replies or [0])
    def request(self,command,payload,event_id,timeout,retries):
        self.calls.append({'command':command,'state':PanelState.unpack(payload),
            'event_id':event_id,'timeout':timeout,'retries':retries,'serial_timeout':self.serial.timeout})
        result=self.replies.pop(0) if len(self.replies)>1 else self.replies[0]
        if isinstance(result,Exception):raise result
        return Frame(0x90,1,event_id,result if isinstance(result,bytes) else bytes([result]))


class StrictReceiver(Device):
    """Implements the RTL's SYNC/seq contract; ACK0 alone doesn't imply apply."""
    def __init__(self):
        super().__init__();self.session=None;self.last_seq=0;self.phase=Phase.NORMAL
        self.apply_count=0;self.stale_once=False;self.record_id=0
    def request(self,command,payload,event_id,timeout,retries):
        state=PanelState.unpack(payload)
        self.calls.append({'command':command,'state':state,'event_id':event_id})
        ack=0
        if self.stale_once:self.stale_once=False;ack=1
        elif state.phase==Phase.SYNC:
            if self.session is None:self.session=state.session;self.last_seq=state.display_seq
            elif self.session!=state.session or state.display_seq<self.last_seq:ack=1
            else:self.last_seq=state.display_seq
        elif self.session!=state.session or state.display_seq<self.last_seq or event_id!=self.record_id:ack=1
        elif state.display_seq!=self.last_seq:
            self.last_seq=state.display_seq;self.phase=state.phase;self.apply_count+=1
        return Frame(0x90,1,event_id,bytes([ack]))


class ProtocolTests(unittest.TestCase):
    def test_exact_little_endian_packet_and_legacy_commands(self):
        state=PanelState(Phase.READY,375,0x99aabbcc,0x11223344,0x55667788)
        self.assertEqual(state.pack(),struct.pack('<BBHIII',1,1,375,0x99aabbcc,0x11223344,0x55667788))
        self.assertEqual(PanelState.unpack(state.pack()),state)
        self.assertEqual(COMMANDS['PANEL'],16)
        self.assertEqual([COMMANDS[n] for n in ('HELLO','STATUS','CAL','SET','ARM','SNAP','LIST','READ','ACK','REPLAY','ECHO','MONITOR','PREVIEW','AUDIO','MUSIC')],list(range(1,16)))

    def test_unknown_progress_and_reject_invalid_wire_states(self):
        self.assertEqual(PanelState.unpack(PanelState().pack()).progress,UNKNOWN_PROGRESS)
        for fields in ({'version':2},{'phase':10},{'progress':1001},{'progress':-1},
                       {'session':-1},{'display_seq':2**32},{'value':2**32}):
            with self.subTest(fields=fields),self.assertRaises(ValueError):PanelState(**fields).pack()
        for data in (b'',bytes(15),bytes(17)):
            with self.assertRaises(ValueError):PanelState.unpack(data)

    def test_one_bounded_display_only_request_restores_serial_timeout(self):
        for timeout in (None,.1,.005):
            for ack in (0,1,7):
                with self.subTest(timeout=timeout,ack=ack):
                    device=Device([ack],timeout)
                    self.assertEqual(send_panel(device,PanelState(Phase.NORMAL),42),ack)
                    self.assertEqual(device.serial.timeout,timeout);self.assertEqual(len(device.calls),1)
                    call=device.calls[0]
                    self.assertEqual((call['command'],call['event_id'],call['timeout'],call['retries']),('PANEL',42,.03,0))
                    self.assertLessEqual(call['serial_timeout'],.01)
        device=Device([TimeoutError('simulated optional display timeout')])
        with self.assertRaises(TimeoutError):send_panel(device,PanelState())
        self.assertEqual(device.serial.timeout,.1);self.assertEqual(len(device.calls),1)

    def test_malformed_ack_rejected(self):
        for reply in (b'',b'\0\0',b'\2'):
            with self.subTest(reply=reply),self.assertRaises(ValueError):send_panel(Device([reply]),PanelState())


class ShortcutTests(unittest.TestCase):
    def test_first_on_enters_once_first_off_does_nothing(self):
        shortcuts=SwitchShortcuts()
        self.assertEqual(shortcuts.update(0xffff),['enter'])
        self.assertEqual(shortcuts.update(0xffff),[])
        shortcuts.reset();self.assertEqual(shortcuts.update(0x7fff),[])
        self.assertEqual(shortcuts.update(0x7fff),[])

    def test_sw15_rise_enters_fall_exits_once(self):
        shortcuts=SwitchShortcuts();shortcuts.update(0)
        for mask,expected in ((0x8000,['enter']),(0x8000,[]),(0xffff,[]),
                              (0x7fff,['exit']),(0x7fff,[]),(0x8000,['enter']),
                              (0x8000,[]),(0,['exit']),(0,[])):
            with self.subTest(mask=hex(mask)):self.assertEqual(shortcuts.update(mask),expected)

    def test_reconnect_follows_current_on_once_without_record_or_favourite(self):
        shortcuts=SwitchShortcuts();self.assertEqual(shortcuts.update(0x8000),['enter'])
        shortcuts.reset();self.assertEqual(shortcuts.update(0xf000),['enter'])
        self.assertEqual(shortcuts.update(0xf000),[])
        shortcuts.reset();self.assertEqual(shortcuts.update(0x7000),[])

    def test_all_other_fifteen_switches_never_dispatch_business(self):
        shortcuts=SwitchShortcuts();shortcuts.update(0)
        for bit in range(15):self.assertEqual(shortcuts.update(1<<bit),[])
        self.assertEqual(shortcuts.update(0x8000),['enter'])
        for bit in range(15):self.assertEqual(shortcuts.update(0x8000|(1<<bit)),[])
        self.assertEqual(shortcuts.update(0xffff),[])


class DisplayTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.events=[];self.messages=[]
        self.music=SimpleNamespace(enabled=True,current=None,last=None)
        run=SimpleNamespace(event=lambda kind,**data:self.events.append((kind,data)))
        self.panel=PanelDisplay(run,lambda kind,**data:self.messages.append((kind,data)),self.clock)
        self.device=Device()
    def sync(self):
        self.panel.poll(self.device);self.clock.advance();self.panel.poll(self.device)

    def test_sync_then_rate_limit_and_duplicate_sequence_heartbeat(self):
        self.sync();self.assertEqual([c['state'].phase for c in self.device.calls],[Phase.SYNC,Phase.NORMAL])
        self.panel.update(Phase.READY);self.clock.advance(.1);self.panel.poll(self.device)
        self.assertEqual(len(self.device.calls),2)
        self.clock.advance(.101);self.panel.poll(self.device)
        state=self.device.calls[-1]['state'];self.assertEqual(state.phase,Phase.READY)
        self.clock.advance(.5);self.panel.poll(self.device);self.assertEqual(len(self.device.calls),3)
        self.clock.advance(.501);self.panel.poll(self.device)
        self.assertEqual(self.device.calls[-1]['state'].display_seq,state.display_seq)
        self.assertEqual(self.device.calls[-1]['state'].session,state.session)

    def test_stale_task_or_record_never_overwrites_current_display(self):
        self.panel.bind_job({'id':'current','record_id':12})
        before=(self.panel.phase,self.panel.progress,self.panel.value)
        self.assertFalse(self.panel.update(Phase.PASS,job_id='older',record_id=12))
        self.assertFalse(self.panel.update(Phase.PASS,job_id='current',record_id=11))
        self.assertEqual((self.panel.phase,self.panel.progress,self.panel.value),before)
        self.assertTrue(self.panel.update(Phase.MATCH,job_id='current',record_id=12))
        self.panel.on_music_message('music_progress',{'job':{'id':'older'},'current':100,'total':100},self.music)
        self.assertEqual(self.panel.phase,Phase.MATCH)
        self.panel.on_music_message('music_complete',{'job':{'id':'older','game':False},'result':{'matched':True}},self.music)
        self.assertEqual(self.panel.phase,Phase.MATCH)

    def test_three_optional_failures_disable_only_display_until_reconnect(self):
        for failure in (TimeoutError('display unavailable'),7):
            with self.subTest(failure=failure):
                self.setUp();self.device=Device([failure])
                for _ in range(3):self.panel.poll(self.device);self.clock.advance()
                self.assertTrue(self.panel.disabled);self.assertEqual(self.panel.failures,3)
                self.panel.poll(self.device);self.assertEqual(len(self.device.calls),3)
                self.panel.reconnected();self.assertFalse(self.panel.disabled)
                self.assertEqual(self.panel.phase,Phase.NORMAL);self.assertIsNone(self.panel.job_id)

    def test_stale_ack_recovers_with_sync(self):
        self.sync();self.device.replies=[1]
        self.panel.update(Phase.READY);self.clock.advance();self.panel.poll(self.device)
        self.assertFalse(self.panel.synced)
        self.clock.advance();self.device.replies=[0];self.panel.poll(self.device)
        self.assertEqual(self.device.calls[-1]['state'].phase,Phase.SYNC)

    def test_strict_receiver_applies_after_sync_and_resync_without_expiry(self):
        self.device=StrictReceiver();self.panel.update(Phase.READY);self.sync()
        self.assertEqual(self.device.phase,Phase.READY)
        applied=self.device.apply_count
        self.clock.advance(1.001);self.panel.poll(self.device)
        self.assertEqual(self.device.apply_count,applied)
        self.device.stale_once=True;self.panel.update(Phase.MATCH)
        self.clock.advance();self.panel.poll(self.device);self.assertFalse(self.panel.synced)
        self.clock.advance();self.panel.poll(self.device)
        self.clock.advance();self.panel.poll(self.device)
        self.assertEqual(self.device.phase,Phase.MATCH)
        self.assertTrue(self.panel.synced);self.assertEqual(self.device.apply_count,applied+1)

    def test_transfer_permille_and_matching_elapsed_timer(self):
        self.panel.bind_job({'id':'job','record_id':1})
        self.panel.on_music_message('music_progress',{'job':{'id':'job'},'current':3,'total':8},self.music)
        self.assertEqual((self.panel.phase,self.panel.progress),(Phase.TRANSFER,375))
        self.panel.on_music_message('music_exported',{'job':{'id':'job'}},self.music)
        self.sync();self.clock.advance(2.001);self.panel.poll(self.device)
        self.assertEqual(self.panel.phase,Phase.MATCH);self.assertGreaterEqual(self.panel.value,2000)

    def test_game_stays_neutral_until_current_round_revealed(self):
        job={'id':'round-now','record_id':31,'game':True};self.panel.bind_job(job)
        self.panel.on_music_message('music_game_ready',{'job':job,'result':{'matched':True}},self.music)
        self.assertEqual((self.panel.phase,self.panel.value),(Phase.GAME_READY,0))
        self.panel.on_music_message('music_complete',{'job':job,'result':{'matched':True}},self.music)
        self.assertEqual((self.panel.phase,self.panel.value),(Phase.GAME_READY,0))
        self.panel.on_music_message('music_game_revealed',{'record':{'round_id':'stale',
            'machine_result':{'matched':True},'machine_s':1.5}},self.music)
        self.assertEqual((self.panel.phase,self.panel.value),(Phase.GAME_READY,0))
        self.panel.on_music_message('music_game_revealed',{'record':{'round_id':'round-now',
            'machine_result':{'matched':True},'machine_s':1.5}},self.music)
        self.assertEqual((self.panel.phase,self.panel.value),(Phase.PASS,1500))

    def test_result_error_and_miss_are_distinct(self):
        self.assertEqual(result_phase({'matched':True}),Phase.PASS)
        self.assertEqual(result_phase({'matched':False,'reason':'online_not_found'}),Phase.MISS)
        for reason in ('online_timeout','online_rate_limited','worker_error'):
            self.assertEqual(result_phase({'matched':False,'reason':reason}),Phase.ERROR)

    def test_finished_job_late_progress_cannot_return_to_matching(self):
        job={'id':'finished','record_id':10,'game':False};self.panel.bind_job(job)
        self.panel.on_music_message('music_complete',{'job':job,'result':{'matched':True}},self.music)
        self.assertEqual(self.panel.phase,Phase.PASS)
        self.panel.on_music_message('music_progress',{'job':job,'current':10,'total':10},self.music)
        self.assertEqual(self.panel.phase,Phase.PASS)
        self.panel.on_music_message('music_exported',{'job':job},self.music)
        self.assertEqual(self.panel.phase,Phase.PASS)

    def test_hold_countdown_stays_hold_and_late_matching_after_exit_is_ignored(self):
        self.panel.bind_job({'id':'job','record_id':9})
        self.panel.update(Phase.HOLD,job_id='job',value=5000);self.sync()
        self.clock.advance(2.001);self.panel.poll(self.device)
        self.assertEqual(self.panel.phase,Phase.HOLD);self.assertLess(self.panel.value,4000)
        self.clock.advance(5);self.panel.poll(self.device)
        self.assertEqual((self.panel.phase,self.panel.value),(Phase.HOLD,0))
        self.music.enabled=False
        self.panel.on_music_message('music_complete',{'job':{'id':'job','game':False},'result':{'matched':True}},self.music)
        self.assertEqual(self.panel.phase,Phase.NORMAL)
        for phase in (Phase.MATCH,Phase.HOLD,Phase.TRANSFER):
            self.assertFalse(self.panel.update(phase,job_id='job',value=1000))
        self.assertEqual(self.panel.phase,Phase.NORMAL)

    def test_stale_manual_bind_cannot_replace_active_board_job(self):
        from monitor_service import MonitorService
        service=MonitorService.__new__(MonitorService)
        service.panel_commands=queue.Queue();service.commands=queue.Queue();service.cancel_commands=queue.Queue()
        service.panel=self.panel;service.run_record=SimpleNamespace(event=lambda *a,**kw:None)
        service.music=SimpleNamespace(current={'id':'board-current','record_id':44})
        self.panel.bind_job({'id':'board-current','record_id':44});self.panel.disabled=True
        service.send('panel_update',phase=Phase.MATCH,job_id='manual-stale',bind_job={'id':'manual-stale','record_id':0})
        service.send('music_start',foo='business FIFO unchanged')
        service.panel_hook(None)
        self.assertEqual((self.panel.job_id,self.panel.record_id,self.panel.phase),('board-current',44,Phase.READY))
        self.assertEqual(service.commands.get_nowait(),('music_start',{'foo':'business FIFO unchanged'}))
        service.send('panel_update',phase=Phase.MATCH,job_id='board-current',bind_job={'id':'board-current','record_id':999})
        service.panel_hook(None)
        self.assertEqual((self.panel.job_id,self.panel.record_id,self.panel.phase),('board-current',44,Phase.MATCH))

    def test_explicit_favourite_retriggers_new_sequence_but_heartbeat_does_not(self):
        self.sync()
        self.panel.on_music_message('music_favourite',{},self.music)
        self.clock.advance();self.panel.poll(self.device);first=self.device.calls[-1]['state']
        self.assertEqual(first.phase,Phase.FAVORITE)
        self.clock.advance(.7)
        self.panel.on_music_message('music_favourite',{},self.music);self.panel.poll(self.device)
        second=self.device.calls[-1]['state']
        self.assertEqual(second.phase,Phase.FAVORITE);self.assertGreater(second.display_seq,first.display_seq)
        self.clock.advance(1.001);self.panel.poll(self.device)
        self.assertEqual(self.device.calls[-1]['state'].display_seq,second.display_seq)

    def test_real_poll_cpu_reset_refreshes_record_context_without_uart_reconnect(self):
        from monitor_service import MonitorService
        from monitor_protocol import SequenceCursor
        class PollDevice(StrictReceiver):
            def request(self,command,payload=b'',event_id=0,timeout=3,retries=2):
                if command in ('MONITOR','PREVIEW'):return Frame(0x8c,payload=b'')
                return super().request(command,payload,event_id,timeout,retries)
        service=MonitorService.__new__(MonitorService);events=[]
        service.panel_commands=queue.Queue();service.commands=queue.Queue();service.cancel_commands=queue.Queue();service.panel=self.panel
        service.run_record=SimpleNamespace(event=lambda *a,**kw:None)
        service.music=SimpleNamespace(current={'id':'lost-after-reset','record_id':14},stage='matching',last=None)
        service.last={'tick':100};service.epoch=0;service.identity={'usb_serial':'same-board'}
        service.stats={'resets':0,'polls':0,'switches_seen_high':0,'switches_seen_low':0,
            'buttons_pressed_mask':0,'buttons_released_mask':0}
        service.xyz_cursor=SequenceCursor();service.audio_cursor=SequenceCursor()
        service.press_base=None;service.release_base=None;service.poll_intervals=[];service.last_poll=0
        service.last_flush=service.last_stats=time.monotonic();service.streams={}
        service.log=lambda *a,**kw:None;service.emit=lambda kind,**data:events.append((kind,data))
        self.panel.bind_job({'id':'lost-after-reset','record_id':14});self.panel.synced=True
        receiver=PollDevice();row={'tick':10,'xyz_records':[],'switches':0,'presses':[0]*5,'releases':[0]*5}
        preview={'points':[],'first_seq':0,'last_bin_end_tick':10}
        with patch('monitor_service.monitor_packet',return_value=row),patch('monitor_service.preview_packet',return_value=preview),\
             patch('music_protocol.music_status',return_value={'record_id':0,'flags':0}):
            service.poll(receiver,force=True)
        self.assertTrue(any(k=='reset' for k,v in events));self.assertEqual(service.stats['resets'],1)
        self.assertEqual(self.panel.record_id,0);self.assertIsNone(self.panel.job_id)
        service.send('panel_update',phase=Phase.MATCH,job_id='lost-after-reset',
            bind_job={'id':'lost-after-reset','record_id':14})
        attempts=len(receiver.calls)
        service.panel_hook(receiver)
        self.assertIsNone(self.panel.job_id);self.assertEqual(self.panel.record_id,0)
        self.assertEqual(len(receiver.calls),attempts,'Reset bypassed the200ms optional request deadline')
        self.clock.advance();self.panel.poll(receiver)
        self.assertEqual(receiver.calls[-1]['state'].phase,Phase.SYNC)
        self.clock.advance();self.panel.poll(receiver)
        self.assertTrue(self.panel.synced);self.assertEqual(receiver.phase,Phase.NORMAL)
        self.assertEqual(receiver.calls[-1]['state'].phase,Phase.NORMAL)
        self.assertEqual(receiver.apply_count,1)
        self.assertEqual(receiver.calls[-1]['event_id'],0)


class Value:
    def __init__(self):self.value=''
    def set(self,value):self.value=value


class DashboardShortcutTests(unittest.TestCase):
    def setUp(self):
        from monitor_gui import Dashboard
        self.app=Dashboard.__new__(Dashboard);self.calls=[];self.audit=[]
        self.app.panel_shortcuts=SwitchShortcuts();self.app.panel_link_text='test display'
        self.app.board_control_status=Value();self.app.notice=Value();self.app.status=Value()
        self.app.last_row=None;self.app.device_identity={'serial':'board'}
        self.app.run=SimpleNamespace(event=lambda kind,**data:self.audit.append((kind,data)))
        self.app.open_music=lambda:self.calls.append('open')
        self.app.action=lambda name,**values:self.calls.append(name)
        self.app.show_page=lambda page:self.calls.append('page:'+page)
        self.app.clear_live=lambda:self.calls.append('clear')
        self.app.music_panel=SimpleNamespace(enabled=False,busy=False,importing=False,
            record=lambda:self.calls.append('record'),enable=lambda:self.calls.append('enable'),
            favourite=lambda:self.calls.append('favourite'))
    def row(self,mask):self.app.handle_panel_shortcuts({'switches':mask,'tick':12345})

    def test_existing_enter_exit_callbacks_reused_without_automatic_recording(self):
        self.row(0x8000);self.assertEqual(self.calls,['open','enable'])
        self.row(0xffff);self.row(0x8001)
        self.assertEqual(self.calls,['open','enable'])
        self.row(0x7fff);self.assertEqual(self.calls[-3:],['open','music_disable','page:monitor'])
        dispatched=[v['action'] for k,v in self.audit if k=='panel_shortcut']
        self.assertEqual(dispatched,['enter','exit'])
        self.assertNotIn('record',self.calls);self.assertNotIn('favourite',self.calls)

    def test_busy_or_importing_ignores_enter_but_exit_uses_original_pending_policy(self):
        for flag in ('busy','importing'):
            with self.subTest(flag=flag):
                self.setUp();setattr(self.app.music_panel,flag,True)
                self.row(0x8000);self.row(0xffff)
                self.assertEqual(self.calls,['open'])
                self.row(0x7fff)
                self.assertEqual(self.calls[-3:],['open','music_disable','page:monitor'])
                audits=[v for k,v in self.audit if k=='panel_shortcut']
                self.assertEqual([v['accepted'] for v in audits],[False,True])
                self.assertNotIn('record',self.calls);self.assertNotIn('favourite',self.calls)

    def test_same_identity_reconnect_and_reset_follow_on_once(self):
        self.row(0x8000);self.calls.clear()
        self.app.accept({'kind':'status','connected':False,'text':'disconnected'})
        self.app.accept({'kind':'identity','device':{'serial':'board'}})
        self.app.accept({'kind':'status','connected':True,'text':'connected'})
        self.row(0xf000);self.row(0xffff)
        self.assertEqual(self.calls,['open','enable'])
        self.app.accept({'kind':'reset'});self.row(0xf000);self.row(0xffff)
        self.assertEqual(self.calls,['open','enable','clear','open','enable'])
        self.assertNotIn('record',self.calls);self.assertNotIn('favourite',self.calls)


if __name__=='__main__':unittest.main(verbosity=2)
