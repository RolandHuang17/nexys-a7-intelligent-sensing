"""Fresh real recording, testing the provider's preferred 8 kHz WAV format."""
import json,time,uuid,winsound
from audit import ROOT,Run,write_json,sha256
from hardware import hardware_lock
from protocol import Device
from program import find_port
from music_protocol import configure,start,music_status,export,finish
from music_physical_probe import prepare_playback
from music_library import decode,LocalMatcher
from music_online import AudioTagClient
from music_store import MusicStore
from music_worker import recognize_recording
from audio_stimulus import SpeakerStimulus

if __name__=='__main__':
    r=Run('music_native_online_diagnostic');manifest=json.loads((ROOT/'music_demo/manifest.json').read_text(encoding='utf8'))
    track=next(x for x in manifest['tracks'] if x['title']=='Fluffing a Duck');playback=r.path/'speaker.wav'
    prepare_playback(ROOT/track['file'],30,playback,normalize=True,duration_s=24)
    programming=json.loads((ROOT/'state/active_device.json').read_text(encoding='utf8'))
    with SpeakerStimulus(r,volume_scalar=.20),hardware_lock(r),Device(find_port(),r,audit_responses=False) as d:
        d.seq=uuid.uuid4().int&65535 # Diagnostic on the older bit while its cache fix is building.
        r.event('diagnostic_uart_sequence_seed',value=d.seq)
        prior=music_status(d);assert prior['state']==0
        if prior['flags']&8:finish(d)
        configure(d,wake=False,seconds=20);winsound.PlaySound(str(playback),winsound.SND_FILENAME|winsound.SND_ASYNC);time.sleep(.5);start(d)
        deadline=time.monotonic()+25
        while True:
            row=music_status(d)
            if row['state']==3:break
            if time.monotonic()>deadline:raise TimeoutError('capture')
            time.sleep(.15)
        winsound.PlaySound(None,0);meta=export(d,row,r.path/'original',programming=programming);finish(d);configure(d,enabled=False,wake=False)
    native=r.path/'native_8000.wav';decode(meta['wav'],native,8000)
    identifier=uuid.uuid4().hex;store=MusicStore();client=AudioTagClient(store,audit=r.event)
    result,local=recognize_recording(identifier,native,'auto',store,LocalMatcher(),online=client,metadata={'original_board':meta,'native_wav_sha256':sha256(native),'resampling_only_no_reupload_of_prior_recordings':True})
    write_json(r.path/'result.json',{'expected':track,'original_board':meta,'native_wav_sha256':sha256(native),'local':local,'result':result})
    r.event('native_format_diagnostic_completed',reason=result['reason'],matched=result['matched']);r.manifest();print(json.dumps({'run_id':r.run_id,'reason':result['reason'],'matched':result['matched'],'title':result.get('title'),'artist':result.get('artist'),'after':result.get('after')},ensure_ascii=False))
