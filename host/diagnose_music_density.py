"""Evaluate denser reference fingerprints on recorded development data only."""
import json,gc,contextlib,io,shutil,sqlite3
from audit import ROOT,Run,write_json,sha256
from music_store import MusicStore
from music_library import upstream,LocalMatcher

if __name__=='__main__':
    r=Run('music_density_diagnostic');base=ROOT/'music';records=MusicStore().recordings();analyze,_,htmod=upstream();summary=[]
    clips=list((ROOT/'runs/20261114T192820_860705_music_microphone_development').glob('clip_*/result.json'))
    for density in (40,80):
        folder=r.path/('density'+str(density));folder.mkdir();store=MusicStore(folder)
        with sqlite3.connect(base/'music.sqlite3') as src,sqlite3.connect(store.path) as dst:src.backup(dst)
        analyzer=analyze.Analyzer();analyzer.density=density;analyzer.shifts=1;ht=htmod.HashTable(hashbits=20,depth=100);fingerprints=[]
        with contextlib.redirect_stdout(io.StringIO()):
            for row in records:
                hashes=analyzer.wavfile2hashes(row['file']);ht.store(row['id'],hashes);fingerprints.append({'id':row['id'],'hashes':len(hashes),'wav_sha256':sha256(row['file'])})
            ht.save(str(folder/'fingerprints.pklz'))
        manifest=json.loads((base/'library_manifest.json').read_text(encoding='utf8'));manifest.update(density=density,generation=sha256(folder/'fingerprints.pklz'),fingerprints=fingerprints)
        write_json(folder/'library_manifest.json',manifest);del ht;gc.collect();matcher=LocalMatcher(folder);results=[]
        for clip in clips:
            data=json.loads(clip.read_text(encoding='utf8'));path=data['metadata']['wav'];result={'trial':data['trial'],'track':data['track']}
            for seconds,key in ((8,'evidence8'),(10,'evidence10')):
                query=__import__('pathlib').Path(path).parent.parent/'first8.wav' if seconds==8 else path
                result[key]=matcher.evidence(query)
            results.append(result)
        write_json(folder/'development_evidence.json',results);summary.append({'density':density,'directory':str(folder),'results':results})
        print(json.dumps({'density':density,'results':[{'trial':x['trial'],'title':x['track']['title'],'top':x['evidence10']['candidates'][:1]} for x in results]},ensure_ascii=False),flush=True)
        del matcher;gc.collect()
    write_json(r.path/'result.json',{'source':'development_only','rows':summary});r.manifest();print(r.run_id)
