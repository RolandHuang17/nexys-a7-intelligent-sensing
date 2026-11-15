"""Provider replacement checks; offline matcher and user metadata stay unchanged."""
import json
from pathlib import Path
import tempfile
import time
import unittest
import uuid
import wave

from music_store import MusicStore
from music_shazam import ShazamOnlineClient
from music_worker import recognize_recording


def fixture(path):
    with wave.open(str(path),'wb') as wav:
        wav.setparams((1,2,8000,0,'NONE','not compressed'))
        wav.writeframes(b'\1\0'*160000)


class Service:
    def __init__(self,status='matched'):
        self.calls=0;self.status=status;self.next_allowed=0
    def recognize(self,clip,directory):
        self.calls+=1
        with wave.open(str(clip)) as wav:
            assert wav.getframerate()==8000 and wav.getnframes()==96000
        result={'matched':self.status=='matched','status':self.status,'http_requests':1,'elapsed_s':.1}
        if result['matched']:result.update(title='Fixture Song',artist='Fixture Artist')
        return result


class Matcher:
    def __init__(self,hit=True):self.calls=0;self.hit=hit
    def match(self,wav):
        self.calls+=1
        return {'matched':self.hit,'source':'local' if self.hit else 'none','title':'Local Song','artist':'Local Artist'}


class MainProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.wav=self.root/'board.wav';fixture(self.wav);self.store=MusicStore(self.root/'store')
    def tearDown(self):self.temp.cleanup()
    def test_offline_does_not_read_audio_or_call_online_service(self):
        service=Service();client=ShazamOnlineClient(self.store,client=service)
        result=client.recognize('unused',self.root/'missing.wav','offline')
        self.assertEqual(result['reason'],'offline_only');self.assertEqual(service.calls,0)
    def test_board_8khz_clip_and_duplicate_job_are_idempotent(self):
        service=Service();client=ShazamOnlineClient(self.store,client=service)
        first=client.recognize('same-job',self.wav)
        second=client.recognize('same-job',self.wav)
        self.assertEqual(service.calls,1);self.assertEqual(first['source'],'shazamio')
        self.assertTrue(second['cached_original_task'])
        self.assertEqual(first['preprocessing']['clip_start_s'],4)
    def test_legacy_token_and_history_are_preserved_without_query(self):
        self.store.save_online('legacy','oldhash','submitted',token='SIMULATED-LEGACY-TOKEN',details={'source_wav':str(self.wav)})
        before=self.store.online('legacy');service=Service()
        result=ShazamOnlineClient(self.store,client=service).recognize('legacy',self.wav)
        self.assertEqual(result['reason'],'legacy_online_task');self.assertEqual(service.calls,0)
        self.assertEqual(self.store.online('legacy'),before)
    def test_old_AudioTag_free_account_lock_does_not_block_Shazam(self):
        self.store.set_setting('online_locked',True);service=Service()
        self.assertTrue(ShazamOnlineClient(self.store,client=service).recognize('new',self.wav)['matched'])
        self.assertEqual(service.calls,1)
    def test_modified_audio_cannot_reuse_job_identity(self):
        client=ShazamOnlineClient(self.store,client=Service());client.recognize('job',self.wav)
        with self.wav.open('ab') as f:f.write(b'changed')
        self.assertEqual(client.recognize('job',self.wav)['reason'],'job_audio_mismatch')
    def test_rate_limit_cooldown_survives_client_restart(self):
        client=ShazamOnlineClient(self.store,client=Service('rate_limited'))
        result=client.recognize('limited',self.wav)
        self.assertEqual(result['reason'],'online_rate_limited')
        self.assertGreaterEqual(self.store.setting('shazam_next_allowed_at'),time.time()+59)
        service=Service();ShazamOnlineClient(self.store,client=service).recognize('next',self.wav)
        self.assertGreaterEqual(service.next_allowed,time.monotonic()+58)
    def test_online_success_skips_local_and_is_saved_under_Shazam(self):
        matcher=Matcher();client=ShazamOnlineClient(self.store,client=Service())
        result,_=recognize_recording('online',self.wav,'auto',self.store,matcher,online=client)
        self.assertEqual(matcher.calls,0);self.assertEqual(result['source'],'shazamio')
        self.assertEqual(self.store.history()[0]['source'],'shazamio')
        self.store.favourite(result['song_id']);self.store.favourite(result['song_id'])
        self.assertEqual(len(self.store.history(favourites=True)),1)
    def test_unavailable_online_keeps_existing_local_fallback(self):
        matcher=Matcher();client=ShazamOnlineClient(self.store,client=Service('not_found'))
        result,_=recognize_recording('fallback',self.wav,'auto',self.store,matcher,online=client)
        self.assertEqual(matcher.calls,1);self.assertEqual(result['source'],'local')
        self.assertEqual(result['online_attempt']['reason'],'online_not_found')
    def test_offline_worker_uses_only_the_unchanged_local_path(self):
        class Forbidden:
            def recognize(self,*args):raise AssertionError('offline must not request online')
        matcher=Matcher();result,_=recognize_recording('offline',self.wav,'offline',self.store,matcher,online=Forbidden())
        self.assertEqual(matcher.calls,1);self.assertEqual(result['source'],'local')
        self.assertEqual(result['recognition_order'],'offline_only')


if __name__=='__main__':unittest.main()
