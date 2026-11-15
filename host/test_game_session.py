"""UART-mode ownership, restoration, and existing music/panel compatibility."""
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from game_session import GameSession


class Sessions(unittest.TestCase):
    def setUp(self):
        self.events=[];self.messages=[];self.requests=[]
        self.service=SimpleNamespace(music=SimpleNamespace(enabled=False,current=None),last={'switches':0},
            fft_job={'old':True},run_record=SimpleNamespace(event=lambda *a,**k:self.events.append((a,k))),
            emit=lambda kind,**v:self.messages.append({'kind':kind,**v}))
        self.session=GameSession(self.service)
        self.original={'build_id':'current','ticks':100,'trigger_mode':3,'armed':True,
                       'audio_threshold':51,'accel_threshold':72,'pair_window_ticks':4000000,'threshold_id':19}
        self.disarmed={**self.original,'ticks':200,'armed':False}
        self.restored={**self.original,'ticks':300}
        def request(name,payload):
            self.requests.append((name,payload))
            return SimpleNamespace(payload=b'\x00')
        self.device=SimpleNamespace(request=request)

    def test_exact_restore_without_threshold_write_or_event_ack(self):
        with patch('game_session.music_status',return_value={'flags':0,'state':0}), \
             patch('game_session.status',side_effect=[self.original,self.disarmed,self.disarmed,self.restored]):
            self.session.enter(self.device)
            self.assertTrue(self.session.active)
            self.assertIsNone(self.service.fft_job)
            self.session.release(self.device)
        self.assertEqual(self.requests,[('ARM',b'\x03\x00'),('ARM',b'\x03\x01')])
        self.assertFalse(self.session.active)
        self.assertTrue(self.messages[-1]['restored'])

    def test_duplicate_enter_keeps_original_armed_snapshot(self):
        with patch('game_session.music_status',return_value={'flags':0,'state':0}), \
             patch('game_session.status',side_effect=[self.original,self.disarmed]):
            self.session.enter(self.device);self.session.enter(self.device)
        self.assertTrue(self.session.original['armed'])
        self.assertEqual(len(self.requests),1)

    def test_busy_music_or_sw15_refused_before_uart_mutation(self):
        for what in ('enabled','current','sw15'):
            self.service.music.enabled=what=='enabled'
            self.service.music.current={'id':'job'} if what=='current' else None
            self.service.last['switches']=0x8000 if what=='sw15' else 0
            with self.subTest(what=what),self.assertRaises(RuntimeError):
                self.session.enter(self.device)
        self.assertFalse(self.requests)

    def test_board_music_recording_or_frozen_job_refused(self):
        for value in ({'flags':1,'state':0},{'flags':8,'state':0},{'flags':0,'state':2}):
            with self.subTest(status=value),patch('game_session.music_status',return_value=value),self.assertRaises(RuntimeError):
                self.session.enter(self.device)
        self.assertFalse(self.requests)

    def test_reset_or_changed_configuration_never_restores_old_state(self):
        for current in ({**self.disarmed,'ticks':5},{**self.disarmed,'threshold_id':20}):
            self.session.original=self.original;self.session.active=True
            with self.subTest(current=current),patch('game_session.status',return_value=current):
                self.session.release(self.device)
            self.assertFalse(self.messages[-1]['restored'])
            self.assertFalse(self.session.active)
        self.assertFalse(self.requests)

    def test_failed_uart_restore_unblocks_mode_and_reports_failure(self):
        self.session.original=self.original;self.session.active=True
        with patch('game_session.status',side_effect=OSError('disconnected')):
            self.session.release(self.device)
        self.assertFalse(self.session.active)
        self.assertIsNone(self.session.original)
        self.assertFalse(self.messages[-1]['restored'])

    def test_reset_invalidates_pending_restore(self):
        self.session.original=self.original;self.session.active=True
        self.session.reset()
        self.assertIsNone(self.session.original)
        self.assertTrue(self.messages[-1]['reset'])

    def test_service_rejects_snap_arm_music_start_during_game(self):
        from monitor_service import MonitorService
        with patch('music_board.MusicBoard'):
            service=MonitorService(self.service.run_record,lambda m:self.messages.append(m))
        service.game.active=True
        for name in ('snap','arm','music_enable','music_start'):
            service.send(name)
            service.controls(self.device)
        self.assertFalse(self.requests)
        self.assertEqual(sum(m['kind']=='notice' for m in self.messages),4)
        # Existing cancellation and display queues retain their separate paths.
        service.send('music_cancel',job_id='job')
        service.send('panel_update',phase=0)
        self.assertEqual(service.cancel_commands.get_nowait(),{'job_id':'job'})
        self.assertEqual(service.panel_commands.get_nowait(),{'phase':0})

    def test_standalone_save_import_is_copy_and_never_overwrites(self):
        from tilt_game.embedded import import_standalone_save
        from tilt_game.storage import SaveStore
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'independent';dest=Path(folder)/'main'
            save=SaveStore(source)
            save.record('board',{'level':1,'won':True,'stars':3,'seconds':10,'deaths':0,'energy':3,'core':True})
            old=(source/'progress.json').read_bytes()
            self.assertTrue(import_standalone_save(dest,source))
            self.assertEqual(SaveStore(dest).unlocked('board'),2)
            self.assertEqual((source/'progress.json').read_bytes(),old)
            changed=SaveStore(dest);changed.data['settings']['sensitivity']=24;changed.commit()
            self.assertFalse(import_standalone_save(dest,source))
            self.assertEqual(SaveStore(dest).data['settings']['sensitivity'],24)


if __name__=='__main__':
    unittest.main(verbosity=2)
