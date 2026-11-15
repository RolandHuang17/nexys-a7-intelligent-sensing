import json,tempfile,wave
from pathlib import Path
import numpy as np
from audit import ROOT,Run,write_json,sha256
from music_library import import_tracks,LocalMatcher,decode
from music_store import MusicStore

def main():
    r=Run('music_library_prepare');manifest=json.loads((ROOT/'music_demo/manifest.json').read_text(encoding='utf8'))
    tracks=[{**row,'file':str(ROOT/row['file'])} for row in manifest['tracks'] if row['group']=='library'];assert len(tracks)==5
    result=import_tracks(tracks);write_json(r.path/'import_result.json',result)
    repeated=import_tracks(tracks);assert all(t['status']=='duplicate' for t in repeated['tracks']);assert len(MusicStore().recordings())==5
    matcher=LocalMatcher();rows=[]
    test_dir=r.path/'digital_queries';test_dir.mkdir()
    for i,row in enumerate(MusicStore().recordings()):
        with wave.open(row['file'],'rb') as w:
            rate=w.getframerate();w.setpos(min(int(rate*30),w.getnframes()-10*rate));raw=w.readframes(10*rate)
        path=test_dir/f'query_{i:02}.wav'
        with wave.open(str(path),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(rate);w.writeframes(raw)
        evidence=matcher.match(path);assert evidence['matched'] and evidence['title']==row['title'] and evidence['artist']==row['artist'],evidence
        rows.append({'evidence_kind':'digital_crop_not_physical','expected':row['title'],'result':evidence,'sha256':sha256(path)})
    rng=np.random.default_rng(20261114);path=test_dir/'noise.wav'
    with wave.open(str(path),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes((rng.normal(0,2000,160000)).astype('<i2').tobytes())
    noise=matcher.match(path);assert not noise['matched']
    write_json(r.path/'result.json',{'import':result,'duplicate_import':repeated,'positive_digital':rows,'noise_digital':noise,
        'formal_physical_acceptance':False,'upstream_commit':'cb03ba99feafd41b8874307f0f4e808a6ce34362'})
    r.status('MUSIC2_library','passed','五首全曲建库、重复导入去重、数字裁剪与噪声基本检查通过；尚非手机外放验收',
        [str((r.path/'result.json').relative_to(ROOT))],'使用实板开发数据确定门槛，再采独立正式试次');r.manifest();print(r.run_id)
if __name__=='__main__':main()
