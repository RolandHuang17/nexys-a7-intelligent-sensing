"""Lifecycle contract checks using fake UART, never physical-board evidence."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace


class BoardLifecycle(unittest.TestCase):
    def service(self,*,armed=True,music=False,fail_poll=False,reset=False):
        from tilt_game.board import make_service
        original={'armed':armed,'trigger_mode':3,'build_id':'test','ticks':100,
                  'audio_threshold':13,'accel_threshold':39,'pair_window_ticks':5000000,'threshold_id':7}
        current={**original,'ticks':10 if reset else 200,'armed':False}
        after={**original,'ticks':300}
        events=[]
        published=[]
        commands=[]
        run=SimpleNamespace(event=lambda *a,**k:events.append((a,k)))
        device=SimpleNamespace(request=lambda name,payload:commands.append((name,payload)) or SimpleNamespace(payload=b'\x00'))
        with patch('music_board.MusicBoard'), patch('capture.status',side_effect=[original,current,after]), \
             patch('music_protocol.music_status',return_value={'flags':int(music),'state':0}):
            service=make_service(run,published.append)
            if fail_poll:
                service.poll=lambda d: (_ for _ in ()).throw(RuntimeError('test transport failure'))
            else:
                service.stop_event.set()
            if fail_poll or music:
                with self.assertRaises(RuntimeError):
                    service.session(device)
            else:
                service.session(device)
        return commands,events,published

    def test_restores_armed_state_without_set_or_ack(self):
        commands,events,_=self.service()
        self.assertEqual(commands,[('ARM',b'\x03\x00'),('ARM',b'\x03\x01')])
        self.assertTrue(events[-1][1]['passed'])

    def test_unarmed_stays_unarmed(self):
        commands,_,_=self.service(armed=False)
        self.assertEqual(commands[-1],('ARM',b'\x03\x00'))

    def test_transport_failure_still_attempts_restore(self):
        commands,events,_=self.service(fail_poll=True)
        self.assertEqual(commands[-1],('ARM',b'\x03\x01'))
        self.assertTrue(events[-1][1]['passed'])

    def test_music_in_progress_refused_before_mutation(self):
        commands,_,_=self.service(music=True)
        self.assertEqual(commands,[])

    def test_reset_never_restores_old_session(self):
        commands,events,published=self.service(reset=True)
        self.assertEqual(commands,[('ARM',b'\x03\x00')])
        self.assertFalse(events[-1][1]['passed'])
        self.assertFalse(published[-1]['restored'])


if __name__=='__main__':
    unittest.main(verbosity=2)
