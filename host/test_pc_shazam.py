"""Recognition semantics, cancellation, corrupt input and worker deadline tests."""
import asyncio
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import wave

from pc_shazam_backend import Backend, ShazamClient, error_result, parse_response, retry_after_seconds, validate_clip, verified_songrec_session
from songrec_probe import digest


def fixture(path, seconds=20):
    with wave.open(str(path), 'wb') as wav:
        wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        wav.writeframes(b'\x01\x00'*(seconds*16000))


class ShazamTests(unittest.TestCase):
    def test_missing_matches_or_track_is_not_a_success(self):
        self.assertFalse(parse_response({'matches': [],'track':{'title':'Fake','subtitle':'Fake'}})['matched'])
        self.assertEqual(parse_response({'matches':[{}]})['status'],'invalid_response')
        self.assertEqual(parse_response({'matches':[{}],'track':{'title':'Song','subtitle':''}})['status'],'invalid_response')
        result=parse_response({'matches':[{}],'track':{'title':'Song','subtitle':'Artist','key':'42'}})
        self.assertTrue(result['matched'])
        self.assertEqual(result['source'],'shazamio')
        self.assertNotIn('confidence',result)

    def test_rate_limit_and_timeout_remain_distinct_from_not_found(self):
        RateLimited=type('RateLimited',(Exception,),{})
        self.assertEqual(error_result(RateLimited())['status'],'rate_limited')
        self.assertEqual(error_result(asyncio.TimeoutError())['status'],'timeout')
        self.assertEqual(error_result(ConnectionError())['status'],'network_error')

    def test_retry_after_accepts_seconds_dates_and_rejects_nonfinite_values(self):
        self.assertEqual(retry_after_seconds('120'),120)
        self.assertEqual(retry_after_seconds('Thu, 01 Jan 1970 00:02:00 GMT',wall_time=0),120)
        for value in ('nan','inf','invalid','-2'):
            self.assertEqual(retry_after_seconds(value),0)

    def test_closing_cooldown_does_not_send_a_request(self):
        client=ShazamClient(interval=0)
        client.next_allowed=time.monotonic()+60
        client.cancel_event=threading.Event()
        client.cancel_event.set()
        with tempfile.TemporaryDirectory() as temp,patch('pc_shazam_backend.subprocess.Popen') as spawn:
            result=client.recognize(Path(temp)/'clip.wav',Path(temp))
            self.assertEqual(result['status'],'cancelled')
            self.assertEqual(result['http_requests'],0)
            spawn.assert_not_called()

    def test_cancelled_capture_never_prepares_or_calls_service(self):
        class Client:
            def recognize(self,*args):
                raise AssertionError('cancelled capture must not request recognition')
        with tempfile.TemporaryDirectory() as temp:
            backend=Backend(temp,Client())
            directory,job=backend.new_trial('computer_microphone')
            fixture(directory/'original.wav',2)
            result=backend.recognize(directory,job,directory/'original.wav',{'complete':False})
            self.assertEqual(result['result']['status'],'cancelled')
            self.assertFalse((directory/'center_12s.wav').exists())
            self.assertEqual(result['result']['http_requests'],0)

    def test_import_preserves_source_and_client_receives_only_center_clip(self):
        class Client:
            calls=0
            def recognize(self,clip,directory):
                self.calls+=1
                self.assert_clip=validate_clip(clip)
                return {'matched':False,'status':'not_found','message':'fixture','source':'shazamio'}
        client=Client()
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'source.wav'
            fixture(source)
            old=digest(source)
            record=Backend(Path(temp)/'store',client).import_wav(source)
            self.assertEqual(digest(source),old)
            self.assertEqual(record['preparation']['clip_start_s'],4)
            self.assertEqual(record['preparation']['clip_duration_s'],12)
            self.assertTrue(client.assert_clip)
            self.assertEqual(client.calls,1)

    def test_short_wav_never_reaches_client(self):
        class Client:
            def recognize(self,*args):
                raise AssertionError('short input must not reach service')
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'short.wav'
            fixture(source,2)
            with self.assertRaises(ValueError):
                Backend(Path(temp)/'store',Client()).import_wav(source)

    def test_worker_deadline_kills_only_owned_worker_and_preserves_failure(self):
        class Process:
            returncode=None
            killed=False
            pid=135791
            def communicate(self,timeout=None):
                if timeout is not None:
                    raise subprocess.TimeoutExpired('owned test worker',timeout)
                return b'',b''
            def kill(self):
                self.killed=True
                self.returncode=-9
        proc=Process()
        with tempfile.TemporaryDirectory() as temp,patch('pc_shazam_backend.subprocess.Popen',return_value=proc),patch('pc_shazam_backend.subprocess.run') as kill_tree:
            result=ShazamClient(interval=0).recognize(Path(temp)/'clip.wav',Path(temp))
            self.assertTrue(proc.killed)
            self.assertEqual(result['status'],'timeout')
            self.assertTrue((Path(temp)/'recognition.json').exists())
            self.assertEqual(kill_tree.call_args.args[0],['taskkill','/PID','135791','/T','/F'])

    def test_worker_crash_cannot_reuse_a_matching_payload_as_success(self):
        class Process:
            returncode=1
            def communicate(self,timeout=None):
                return b'',b'fixture crash'
        with tempfile.TemporaryDirectory() as temp,patch('pc_shazam_backend.subprocess.Popen',return_value=Process()):
            (Path(temp)/'recognition.json').write_text(json.dumps({'matched':True,'status':'matched','title':'Fake','artist':'Fake'}))
            result=ShazamClient(interval=0).recognize(Path(temp)/'clip.wav',Path(temp))
            self.assertFalse(result['matched'])
            self.assertEqual(result['status'],'worker_error')

    def test_silence_and_invalid_clip_length(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'silence.wav'
            with wave.open(str(path),'wb') as wav:
                wav.setparams((1,2,16000,0,'NONE','not compressed'))
                wav.writeframes(b'\0'*(12*16000*2))
            self.assertFalse(validate_clip(path))
            fixture(path,20)
            with self.assertRaises(ValueError):
                validate_clip(path)

    def test_unfinished_or_changed_acceptance_cannot_trigger_replay(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'session.json'
            path.write_text(json.dumps({'rows':[]}))
            with self.assertRaises(ValueError):
                verified_songrec_session(path)
            original,clip=Path(temp)/'original.wav',Path(temp)/'clip.wav'
            fixture(original)
            fixture(clip,12)
            rows=[{'index':i,'kind':'formal_microphone','complete':True,'grade':'correct','wav':str(original),
                   'clip':str(clip),'source_sha256':'incorrect hash','clip_sha256':digest(clip)} for i in range(6)]
            path.write_text(json.dumps({'rows':rows}))
            with self.assertRaisesRegex(ValueError,'校验不一致'):
                verified_songrec_session(path)


if __name__=='__main__':
    unittest.main()
