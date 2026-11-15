"""Audfprint adapter: full local recordings, conservative evidence gates."""
import contextlib,hashlib,io,json,os,shutil,subprocess,sys,tempfile,time,uuid,wave
from pathlib import Path
import numpy as np
import scipy.signal
from audit import ROOT,sha256,write_json
from app_paths import RESOURCE_ROOT
from music_store import MusicStore

PROFILE={'min_hashes':12,'min_span_s':1.5,'min_ratio':2.0,'seconds':10,'status':'development_not_frozen'}

def normalize_query(source,destination):
    """Keep the entire recording; remove microphone DC and avoid resampling tiny integers."""
    with wave.open(str(source),'rb') as w:
        if w.getnchannels()!=1 or w.getsampwidth()!=2:raise ValueError('识曲录音需要单声道PCM16')
        rate=w.getframerate();a=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').astype(float)
    if not len(a):raise ValueError('录音为空')
    offset=float(np.mean(a));a-=offset;peak=float(np.max(np.abs(a)));gain=.9*32767/max(1.,peak)
    with wave.open(str(destination),'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(rate);w.writeframes(np.rint(a*gain).astype('<i2').tobytes())
    return {'method':'whole_recording_DC_remove_peak_normalize_v1','samples':len(a),'sample_rate':rate,'dc_counts':offset,'gain':gain,
        'source_sha256':sha256(source),'normalized_sha256':sha256(destination),'cropped':False}
def tools():
    assets=RESOURCE_ROOT/'music'
    if not (assets/'audfprint').exists():assets=Path(__file__).resolve().parents[1]/'upstream/music'
    return assets
def upstream():
    p=str(tools()/'audfprint')
    if p not in sys.path:sys.path.insert(0,p)
    import audfprint_analyze,audfprint_match,hash_table,audio_read
    audio_read.HAVE_FFMPEG=False
    return audfprint_analyze,audfprint_match,hash_table
def decode(source,dest,rate=11025):
    source=Path(source);dest=Path(dest);dest.parent.mkdir(parents=True,exist_ok=True)
    if not source.is_file():raise ValueError('请选择已有的本机音乐文件')
    if source.suffix.lower() not in ('.wav','.mp3','.flac','.m4a','.ogg','.aac','.wma'):raise ValueError('请选择本机音乐文件')
    p=subprocess.run([str(tools()/'ffmpeg.exe'),'-v','error','-nostdin','-y','-protocol_whitelist','file,pipe','-i',str(source),'-vn','-map_metadata','-1','-ac','1','-ar',str(rate),'-c:a','pcm_s16le',str(dest)],
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,timeout=120)
    if p.returncode:raise ValueError('音乐文件无法解码，原文件已保留')
    with wave.open(str(dest),'rb') as w:
        assert w.getnchannels()==1 and w.getsampwidth()==2 and w.getframerate()==rate
        raw=w.readframes(w.getnframes());duration=w.getnframes()/rate
    return hashlib.sha256(raw).hexdigest(),duration
def metadata(path):
    title=Path(path).stem;artist=''
    try:
        import mutagen
        data=mutagen.File(path,easy=True)
        if data:title=str(data.get('title',[title])[0]);artist=str(data.get('artist',[''])[0])
    except Exception:pass
    return {'title':title,'artist':artist}
def import_tracks(tracks,folder=None):
    store=MusicStore(folder);base=store.folder;canonical=base/'canonical';canonical.mkdir(exist_ok=True)
    before=store.recordings();known={r['canonical_sha256']:r for r in before};added=[];results=[]
    for track in tracks:
        source=Path(track['file']);labels={**metadata(source),**track};title=labels['title'].strip();artist=labels['artist'].strip()
        if not title or not artist:results.append({'file':str(source),'status':'needs_metadata','title':title,'artist':artist});continue
        temporary=canonical/(uuid.uuid4().hex+'.wav');pcm_hash,duration=decode(source,temporary)
        if pcm_hash in known:
            existing=Path(known[pcm_hash]['file'])
            if not existing.exists():existing.parent.mkdir(parents=True,exist_ok=True);os.replace(temporary,existing)
            else:temporary.unlink()
            results.append({'file':str(source),'status':'duplicate','id':known[pcm_hash]['id']});continue
        sid=store.put_song(title,artist)
        similar=[r for r in before if r['song_id']==sid and abs(r['duration']-duration)<2]
        if similar and not labels.get('allow_variant',False):
            temporary.unlink();results.append({'file':str(source),'status':'confirm_variant','title':title,'artist':artist});continue
        identifier=pcm_hash;dest=canonical/(identifier+'.wav');os.replace(temporary,dest)
        row={'id':identifier,'song_id':sid,'original_sha256':sha256(source),'canonical_sha256':pcm_hash,'file':str(dest),'duration':duration,
             'title':title,'artist':artist}
        added.append(row);known[pcm_hash]=row;results.append({'file':str(source),'status':'added','id':identifier})
    if not added:return {'tracks':results,'total':len(before),'rebuilt':False}
    analyze,_,htmod=upstream();analyzer=analyze.Analyzer();analyzer.shifts=1
    all_rows=before+added;old_manifest=base/'library_manifest.json';old_index=base/'fingerprints.pklz';fingerprints=[]
    with contextlib.redirect_stdout(io.StringIO()):
        if before and old_manifest.exists() and old_index.exists():
            previous=json.loads(old_manifest.read_text(encoding='utf8'))
            if sha256(old_index)!=previous['generation']:raise ValueError('本地指纹库校验失败，请保留文件后重新导入')
            ht=htmod.HashTable(str(old_index));fingerprints=previous['fingerprints'];to_hash=added
        else:ht=htmod.HashTable(hashbits=20,depth=100);to_hash=all_rows
        for row in to_hash:
            hashes=analyzer.wavfile2hashes(row['file']);ht.store(row['id'],hashes)
            fingerprints.append({'id':row['id'],'hashes':len(hashes),'wav_sha256':sha256(row['file'])})
        tmp=base/'fingerprints.tmp.pklz';ht.save(str(tmp));os.replace(tmp,base/'fingerprints.pklz')
    from audit import now
    with store.db() as c:
        for row in added:c.execute('INSERT OR IGNORE INTO recordings VALUES(?,?,?,?,?,?,?)',
            tuple(row[k] for k in ('id','song_id','original_sha256','canonical_sha256','file','duration'))+(now(),))
    generation=sha256(base/'fingerprints.pklz')
    write_json(base/'library_manifest.json',{'fingerprinter':'audfprint','upstream_commit':'cb03ba99feafd41b8874307f0f4e808a6ce34362',
        'generation':generation,'fingerprints':fingerprints,'tracks':store.recordings(),'sample_rate':11025,'density':20,'hashbits':20,'depth':100})
    default_profile=RESOURCE_ROOT/'music/default_match_profile.json'
    if store.setting('match_profile') is None and default_profile.exists():
        store.set_setting('match_profile',json.loads(default_profile.read_text(encoding='utf8')))
    return {'tracks':results,'total':len(all_rows),'rebuilt':True,'generation':generation}

class LocalMatcher:
    def __init__(self,folder=None):self.store=MusicStore(folder);self.ht=None;self.generation=None
    def evidence(self,wav,query_density=20):
        started=time.perf_counter();base=self.store.folder;manifest=base/'library_manifest.json'
        if not manifest.exists():return {'candidates':[],'reason':'empty_library','elapsed_s':time.perf_counter()-started}
        data=json.loads(manifest.read_text(encoding='utf8'));analyze,match,htmod=upstream()
        if self.generation!=data['generation']:
            with contextlib.redirect_stdout(io.StringIO()):self.ht=htmod.HashTable(str(base/'fingerprints.pklz'))
            self.generation=data['generation']
        analyzer=analyze.Analyzer();analyzer.shifts=4;analyzer.density=query_density
        matcher=match.Matcher();matcher.exact_count=True;matcher.find_time_range=True;matcher.threshcount=3;matcher.search_depth=100
        with tempfile.TemporaryDirectory(prefix='nexys-query-') as temp:
            levelled=Path(temp)/'levelled.wav';preprocess=normalize_query(wav,levelled)
            normalized=Path(temp)/'query.wav';decode(levelled,normalized);hashes=analyzer.wavfile2hashes(str(normalized))
            if len(hashes)==0:rows=[]
            else:rows=matcher.match_hashes(self.ht,hashes)
        trackmap={r['id']:r for r in data['tracks']};candidates=[];seen=set()
        for row in rows:
            name=self.ht.names[int(row[0])]
            if name in seen:continue
            seen.add(name);track=trackmap[name]
            candidates.append({'recording_id':name,'song_id':track['song_id'],'title':track['title'],'artist':track['artist'],
                'aligned_hashes':int(row[1]),'offset_s':float(row[2])*256/11025,'span_s':float(row[6]-row[5])*256/11025,
                'raw_hashes':int(row[3])})
        return {'candidates':candidates[:10],'query_hashes':len(hashes),'query_density':query_density,'preprocess':preprocess,'generation':self.generation,'elapsed_s':time.perf_counter()-started}
    def match(self,wav,profile=None):
        profile=profile or self.store.setting('match_profile',PROFILE);evidence=self.evidence(wav,profile.get('query_density',20))
        return decide(evidence,profile)

def decide(evidence,profile):
    candidates=evidence['candidates'];best=candidates[0] if candidates else None
    ratio=best['aligned_hashes']/max(1,candidates[1]['aligned_hashes']) if len(candidates)>1 else float(best['aligned_hashes']) if best else 0
    accepted=bool(best and best['aligned_hashes']>=profile['min_hashes'] and best['span_s']>=profile['min_span_s'] and ratio>=profile['min_ratio'])
    return {**evidence,'matched':accepted,'source':'local' if accepted else 'none','reason':'matched' if accepted else 'insufficient_evidence',
        'ratio':ratio,'profile':profile,**({k:best[k] for k in ('title','artist','song_id')} if accepted else {})}
