"""Compare fixed microphone high-pass filters using development recordings."""
import json,wave,hashlib
from pathlib import Path
import numpy as np
from scipy.signal import butter,sosfiltfilt
from audit import ROOT,Run,write_json,sha256
from music_library import LocalMatcher

if __name__=='__main__':
    r=Run('music_match_diagnostic');matcher=LocalMatcher();rows=[]
    base=ROOT/'runs/20261114T192820_860705_music_microphone_development'
    for clip in sorted(base.glob('clip_*')):
        source=clip/'first/audio.wav'
        if not source.exists():continue
        with wave.open(str(source),'rb') as w:a=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').astype(float);rate=w.getframerate()
        results=[]
        for cutoff in (0,80,150,250):
            processed=a if cutoff==0 else sosfiltfilt(butter(4,cutoff,fs=rate,btype='highpass',output='sos'),a)
            path=r.path/(clip.name+f'_HP{cutoff}.wav')
            with wave.open(str(path),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(rate);w.writeframes(np.clip(np.rint(processed),-32768,32767).astype('<i2').tobytes())
            evidence=matcher.evidence(path);results.append({'cutoff_hz':cutoff,'wav_sha256':sha256(path),'evidence':evidence})
        rows.append({'clip':clip.name,'input_wav_sha256':sha256(source),'filters':results})
        print(json.dumps({'clip':clip.name,'results':[{'cutoff':x['cutoff_hz'],'top':x['evidence']['candidates'][:1]} for x in results]},ensure_ascii=False),flush=True)
    write_json(r.path/'result.json',{'source':'same_physical_development_WAV_filter_comparison_not_holdout','rows':rows});r.manifest();print(r.run_id)
