import json,tempfile,wave
from pathlib import Path
from unittest.mock import patch
from audit import ROOT,Run,write_json
from music_seed import stage_seed,install_seed
from music_store import MusicStore
from music_library import import_tracks,LocalMatcher

if __name__=='__main__':
 r=Run('music_seed_test')
 with tempfile.TemporaryDirectory() as tmp:
  base=Path(tmp);assets=base/'assets';assets.mkdir();stage_seed(assets);target=base/'user/music'
  with patch('music_seed.RESOURCE_ROOT',assets),patch('music_seed.MusicStore',lambda:MusicStore(target)):
   assert install_seed();assert not install_seed()
  store=MusicStore(target);assert len(store.recordings())==5 and not any(Path(t['file']).exists() for t in store.recordings())
  assert not list((assets/'music_seed').glob('*.wav'))
  extra=import_tracks([{'file':str(ROOT/'music_demo/development_negative/Fluffing a Duck.mp3'),'title':'Fluffing a Duck','artist':'Kevin MacLeod'}],target)
  assert extra['total']==6
  original=next(t for t in MusicStore().recordings() if t['title']=='Take It Easy');query=base/'query.wav'
  with wave.open(original['file'],'rb') as w:rate=w.getframerate();w.setpos(60*rate);raw=w.readframes(10*rate)
  with wave.open(str(query),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(rate);w.writeframes(raw)
  result=LocalMatcher(target).match(query);assert result['matched'] and result['title']=='Take It Easy' and result['artist']=='Eagles'
  write_json(r.path/'result.json',{'source':'digital_reference_not_physical','no_full_pop_recording_in_seed':True,'seed_tracks':5,'incremental_import_total':6,'old_track_still_matches':True,'result':result})
 r.manifest();print(r.run_id)
