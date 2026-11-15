"""Ship fingerprints and labels, without redistributing user-selected pop audio."""
import json,shutil
from pathlib import Path
from audit import ROOT,write_json,sha256,now
from app_paths import RESOURCE_ROOT
from music_store import MusicStore

def stage_seed(assets):
    store=MusicStore();source=store.folder
    if not (source/'library_manifest.json').exists():return
    dest=Path(assets)/'music_seed';dest.mkdir(exist_ok=True)
    manifest=json.loads((source/'library_manifest.json').read_text(encoding='utf8'))
    for row in manifest['tracks']:row['file']='canonical/'+row['canonical_sha256']+'.wav'
    shutil.copy2(source/'fingerprints.pklz',dest/'fingerprints.pklz')
    write_json(dest/'library_manifest.json',manifest)
    write_json(dest/'seed.json',{'songs':[{k:r[k] for k in ('id','song_id','title','artist','original_sha256','canonical_sha256','duration')} for r in store.recordings()],
        'match_profile':store.setting('match_profile'),'tap_profile':store.setting('tap_profile'),'tap_profile_scope':'原实板与桌面，换桌可重新校准','fingerprints_sha256':sha256(dest/'fingerprints.pklz'),
        'audio_files_in_seed':False,'no_credentials_history_favourites_or_online_tokens':True})

def install_seed():
    store=MusicStore();dest=store.folder;source=RESOURCE_ROOT/'music_seed'
    if store.recordings():return False
    if not (source/'seed.json').exists():return False
    seed=json.loads((source/'seed.json').read_text(encoding='utf8'));manifest=json.loads((source/'library_manifest.json').read_text(encoding='utf8'))
    if sha256(source/'fingerprints.pklz')!=seed['fingerprints_sha256']:raise ValueError('演示指纹校验失败')
    rows=[]
    with store.db() as c:
        for r in seed['songs']:
            row={**r,'file':str(dest/'canonical'/(r['canonical_sha256']+'.wav')),'created_at':now()};rows.append(row)
            c.execute('INSERT OR IGNORE INTO songs VALUES(?,?,?)',(r['song_id'],r['title'],r['artist']))
            c.execute('INSERT OR IGNORE INTO recordings VALUES(?,?,?,?,?,?,?)',tuple(row[k] for k in ('id','song_id','original_sha256','canonical_sha256','file','duration','created_at')))
    shutil.copy2(source/'fingerprints.pklz',dest/'fingerprints.pklz');manifest['tracks']=rows;write_json(dest/'library_manifest.json',manifest)
    if seed.get('match_profile'):store.set_setting('match_profile',seed['match_profile'])
    if seed.get('tap_profile'):store.set_setting('tap_profile',seed['tap_profile'])
    return True
