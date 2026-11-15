"""Real microphone development; no online requests and no formal phone trials."""
import argparse,json,time,threading,wave,zlib,shutil
from pathlib import Path
import numpy as np
import winsound
from audit import ROOT,Run,write_json,sha256,now
from hardware import hardware_lock
from program import program_latest,find_port
from protocol import Device
from capture import status,checked
from music_protocol import configure,start,music_status,export,acknowledge,finish
from music_library import decode,LocalMatcher,decide
from audio_stimulus import SpeakerStimulus

def prepare_playback(source,position,path,normalize=False,duration_s=14):
    canonical=path.with_name(path.stem+'_full.wav');decode(source,canonical,16000)
    with wave.open(str(canonical),'rb') as w:
        w.setpos(min(w.getnframes()-1,int(position*16000)));raw=w.readframes(round(duration_s*16000))
    a=np.frombuffer(raw,dtype='<i2').astype(float);gain=1.
    if normalize:
        gain=min(.90*32767/max(1,float(np.max(np.abs(a)))),.20*32767/max(1,float(np.std(a))))
        raw=np.clip(np.rint(a*gain),-32768,32767).astype('<i2').tobytes()
    with wave.open(str(path),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(raw)
    canonical.unlink()
    return {'gain':gain,'normalized':normalize,'input_ac_rms':float(np.std(a)),'output_wav_sha256':sha256(path)}

def main():
    p=argparse.ArgumentParser();p.add_argument('--program',action='store_true');p.add_argument('--quick',action='store_true');p.add_argument('--resume');p.add_argument('--volume',type=float,default=.30)
    p.add_argument('--normalize',action='store_true');p.add_argument('--fast-quality',action='store_true');args=p.parse_args()
    r=Run('music_microphone_development',args.resume);r.snapshot('真实板载麦克风完整采集、重复读回、8/10秒同输入和开发集门槛')
    programming=program_latest(r) if args.program else json.loads((ROOT/'state/active_device.json').read_text(encoding='utf8'))
    manifest=json.loads((ROOT/'music_demo/manifest.json').read_text(encoding='utf8'));tracks=manifest['tracks']
    chosen=[{**x,'position_s':30,'expected':True} for x in tracks if x['group']=='library']
    if not args.quick:chosen += [{**x,'position_s':30,'expected':False} for x in tracks if x['group']=='development_negative'] + [{'title':'安静','artist':'','expected':False,'kind':'quiet'}]
    rows=[];matcher=LocalMatcher()
    with SpeakerStimulus(r,volume_scalar=args.volume) as speaker,hardware_lock(r),Device(find_port(),r,audit_responses=False) as d:
        hello=status(d);assert hello['build_id']==programming['build_id']
        checked(d.request('ARM',bytes((3,0))))
        old=music_status(d)
        if old['state']!=0 and not args.resume:raise RuntimeError('板上已有未完成录音，请先在界面恢复')
        if old['state']==0 and old['flags']&8:finish(d)
        if old['state']==0:configure(d,wake=False,seconds=10)
        for i,track in enumerate(chosen):
            original=r.path/f'clip_{i+1:02}'
            if (original/'result.json').exists():rows.append(json.loads((original/'result.json').read_text(encoding='utf8')));continue
            directory=original
            if directory.exists():directory=directory/('retry_'+str(time.time_ns()))
            directory.mkdir(parents=True);playback=None
            prior=music_status(d);recovering=prior['state'] in (1,2,3)
            playback_meta=None
            if 'file' in track and not recovering:
                playback=directory/'speaker_input.wav';playback_meta=prepare_playback(ROOT/track['file'],track['position_s'],playback,args.normalize)
                if speaker.volume.GetMute():raise RuntimeError('播放端点被静音，停止并保留当前进度')
                winsound.PlaySound(str(playback),winsound.SND_FILENAME|winsound.SND_ASYNC)
                time.sleep(.5)
            initial=prior if recovering else start(d)
            r.event('physical_music_recording_resumed' if recovering else 'physical_music_recording_started',trial=i+1,track=track,record_id=initial['record_id'],sound_source='laptop_external_speakers' if 'file' in track else 'room_quiet',playback=playback_meta,volume_scalar=speaker.volume.GetMasterVolumeLevelScalar())
            deadline=time.monotonic()+15
            while True:
                row=music_status(d)
                if row['state']==3:break
                if time.monotonic()>deadline:raise TimeoutError('板端长录音未冻结')
                time.sleep(.15)
            winsound.PlaySound(None,0)
            metadata=export(d,row,directory/'first',ack=False,programming=programming)
            repeated=metadata if args.fast_quality else export(d,row,directory/'repeat',ack=False,programming=programming)
            assert metadata['pcm_sha256']==repeated['pcm_sha256']
            raw=(directory/'first/pcm.bin').read_bytes();assert zlib.crc32(raw[:256000])==row['prefix_crc32']
            cropped=directory/'first8.wav'
            with wave.open(str(cropped),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(raw[:256000])
            # Actual transfer timing for the 8-second prefix of the same frozen recording.
            from music_protocol import read_samples
            t0=time.monotonic();prefix=bytearray()
            if not args.fast_quality:
                for offset in range(0,128000,240):prefix.extend(read_samples(d,row,offset,min(240,128000-offset)))
                transfer8=time.monotonic()-t0;assert bytes(prefix)==raw[:256000]
            else:transfer8=None
            acknowledge(d,row);finish(d)
            ev8=matcher.evidence(cropped);ev10=matcher.evidence(directory/'first/audio.wav')
            values=np.frombuffer(raw,dtype='<i2').astype(float)
            result={'trial':i+1,'track':track,'metadata':metadata,'repeat_metadata':None if args.fast_quality else repeated,'repeat_equal':None if args.fast_quality else True,
                'prefix_crc32':row['prefix_crc32'],'transfer8_s':transfer8,'evidence8':ev8,'evidence10':ev10,
                'rms_ac':float(np.std(values)),'peak':float(np.max(np.abs(values))),'evidence_kind':'physical_board_development_laptop_speaker_not_formal_phone'}
            write_json(directory/'result.json',result);write_json(original/'result.json',result);rows.append(result)
            print(json.dumps({'trial':i+1,'title':track['title'],'samples':row['samples'],'crc32':f'{row["crc32"]:08x}',
                'rms_ac':result['rms_ac'],'transfer10_s':metadata['export_s'],'transfer8_s':transfer8,'top8':ev8['candidates'][:1],'top10':ev10['candidates'][:1]},ensure_ascii=False),flush=True)
        configure(d,enabled=False,wake=False)
    write_json(r.path/'result.json',{'source':'real_board_mic_laptop_speaker','programming':programming,'trials':rows,'formal_phone_acceptance':False})
    write_json(ROOT/'state/music_development.json',{'run_id':r.run_id,'trials':len(rows),'programming':programming})
    r.status('MUSIC3_quality' if args.fast_quality else 'MUSIC3_recording','passed' if len(rows)>=5 else 'in_progress','完整录音校验通过；重复读回状态逐条列出，开发集不替代正式外放验收',[str((r.path/'result.json').relative_to(ROOT))],'冻结离线参数后进入手机与双击正式验收');r.manifest();print('RUN_ID='+r.run_id)
if __name__=='__main__':main()
