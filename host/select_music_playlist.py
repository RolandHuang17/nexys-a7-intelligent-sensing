"""Activate the three available demo tracks and the two user-selected Eagles songs."""
import json,shutil
from audit import ROOT,Run,write_json
from music_store import MusicStore
from music_library import import_tracks

if __name__=='__main__':
 r=Run('music_playlist_revision');store=MusicStore();selected=json.loads((ROOT/'music_user/manifest.json').read_text(encoding='utf8'))['tracks']
 assert len(selected)==2 and all('file' in t for t in selected)
 archive=r.path/'previous_library';archive.mkdir()
 for name in ('music.sqlite3','music.sqlite3-wal','music.sqlite3-shm','library_manifest.json','fingerprints.pklz'):
  p=store.folder/name
  if p.exists():shutil.copy2(p,archive/name)
 with store.db() as c:
  for row in store.recordings():
   if row['artist']=='Scott Buckley':c.execute('DELETE FROM recordings WHERE id=?',(row['id'],))
 # Move the prior index instead of deleting it; force a clean five-track index.
 for name in ('library_manifest.json','fingerprints.pklz'):
  p=store.folder/name
  if p.exists():p.rename(archive/('old_'+name))
 result=import_tracks(selected);assert len(store.recordings())==5
 playlist={'tracks':store.recordings(),'selected_by_user':['Take It Easy','Tequila Sunrise'],'source_manifest':'music_user/manifest.json',
   'pop_audio_distributed':False,'formal_outside_tracks':[{'title':'Hotel California','artist':'Eagles'},{'title':'Billie Jean','artist':'Michael Jackson'},{'title':'We Will Rock You','artist':'Queen'}]}
 write_json(ROOT/'config/music_selected_playlist.json',playlist);write_json(r.path/'result.json',{'import':result,'playlist':playlist});r.manifest();print(r.run_id)
