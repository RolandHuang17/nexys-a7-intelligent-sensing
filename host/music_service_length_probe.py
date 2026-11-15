"""Public digital reference only, to diagnose the live API's duration rejection."""
import json,wave,uuid
from audit import ROOT,Run,write_json,sha256
from music_library import decode,LocalMatcher
from music_store import MusicStore
from music_online import AudioTagClient
from music_worker import recognize_recording

if __name__=='__main__':
    r=Run('music_service_duration_diagnostic');source=ROOT/'music_demo/development_negative/Investigations.mp3'
    full=r.path/'full.wav';decode(source,full,16000)
    with wave.open(str(full),'rb') as w:w.setpos(30*16000);raw=w.readframes(20*16000)
    wav=r.path/'digital_20_seconds.wav'
    with wave.open(str(wav),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(raw)
    store=MusicStore();identifier=uuid.uuid4().hex
    result,local=recognize_recording(identifier,wav,'auto',store,LocalMatcher(),online=AudioTagClient(store,audit=r.event),metadata={'evidence_kind':'digital_public_reference_not_board','purpose':'diagnose duration only; not part of physical accuracy'})
    write_json(r.path/'result.json',{'source':'digital_public_reference_not_board','seconds':20,'wav_sha256':sha256(wav),'local':local,'result':result})
    r.manifest();print(json.dumps({'run_id':r.run_id,'reason':result['reason'],'service_error':result.get('service_error'),'matched':result['matched'],'title':result.get('title'),'artist':result.get('artist'),'after':result.get('after')},ensure_ascii=False))
