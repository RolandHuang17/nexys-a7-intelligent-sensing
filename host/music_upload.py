"""Prepare the whole board recording for AudioTag without a knock setting its gain."""
import math,wave
from pathlib import Path
import numpy as np
from scipy.signal import resample_poly
from audit import sha256


def prepare_upload(source,destination):
    source=Path(source);destination=Path(destination)
    with wave.open(str(source),'rb') as w:
        if w.getnchannels()!=1 or w.getsampwidth()!=2:raise ValueError('在线识曲需要单声道PCM16')
        rate=w.getframerate();raw=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').astype(float)
    if not len(raw) or rate not in (8000,16000):raise ValueError('录音为空或采样率不受支持')
    dc=float(raw.mean());audio=raw-dc
    if rate!=8000:
        divisor=math.gcd(rate,8000);audio=resample_poly(audio,8000//divisor,rate//divisor)
    # Only brief impulses above this whole-recording percentile can limit.
    # The original samples and duration remain in the archived source WAV.
    rms=float(np.sqrt(np.mean(audio**2)));robust_peak=float(np.quantile(np.abs(audio),.995))
    gain=min(32768*10**(-18/20)/max(1.,rms),.9*32767/max(1.,robust_peak))
    amplified=np.rint(audio*gain);limited=int(np.count_nonzero((amplified>32767)|(amplified<-32768)))
    pcm=np.clip(amplified,-32768,32767).astype('<i2')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with wave.open(str(destination),'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(8000);w.writeframes(pcm.tobytes())
    return {'method':'whole_recording_RMS_and_robust_peak_v3','source_samples':len(raw),'source_sample_rate':rate,
        'samples':len(pcm),'sample_rate':8000,'duration_s':len(pcm)/8000,'dc_counts':dc,'gain':gain,
        'robust_peak_percentile':99.5,'target_rms_dbfs':-18,'robust_peak_counts':robust_peak,'limited_samples':limited,
        'limited_fraction':limited/len(pcm),'input_ac_rms_counts':float(np.sqrt(np.mean(audio**2))),
        'upload_rms_dbfs':float(20*np.log10(max(1e-12,float(np.sqrt(np.mean(pcm.astype(float)**2))))/32768)),
        'source_sha256':sha256(source),'upload_sha256':sha256(destination),'cropped':False,'whole_recording':True}
