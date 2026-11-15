"""Fresh board-microphone API development checks with automatic laptop playback."""
import json,time,uuid,winsound
from pathlib import Path
from audit import ROOT,Run,write_json
from hardware import hardware_lock
from protocol import Device
from device_discovery import select_board
from capture import status
from music_protocol import configure,start,music_status,export,finish
from music_store import MusicStore
from music_online import AudioTagClient
from music_physical_probe import prepare_playback
from audio_stimulus import SpeakerStimulus
from music_online_wizard import same_song


def main():
    r=Run('music_api_capture_development');r.snapshot('仅API在线链路改进：自动播放后由板载麦克风重新连续录音；不使用数字原曲作为上传输入')
    store=MusicStore();known={x['title']:x for x in store.recordings()};rows=[]
    programming=json.loads((ROOT/'state/active_device.json').read_text(encoding='utf8'));board=select_board()
    for title,position in [('Take It Easy',90),('Tequila Sunrise',80),('Carefree',50)]:
        track=known[title];clip=r.path/f'clip_{len(rows)+1:02}';clip.mkdir();playback=clip/'speaker.wav'
        prepare_playback(Path(track['file']),position,playback,normalize=True,duration_s=24)
        with SpeakerStimulus(r,volume_scalar=.30),hardware_lock(r),Device(board.port,r,audit_responses=False) as d:
            assert status(d)['build_id']==programming['build_id']
            prior=music_status(d);assert prior['state']==0
            if prior['flags']&8:finish(d)
            configure(d,enabled=True,wake=False,seconds=20,max_ms=1000)
            winsound.PlaySound(str(playback),winsound.SND_FILENAME|winsound.SND_ASYNC);time.sleep(.5);start(d)
            deadline=time.monotonic()+25
            while True:
                row=music_status(d)
                if row['state']==3:break
                if time.monotonic()>deadline:raise TimeoutError('连续录音未冻结')
                time.sleep(.15)
            winsound.PlaySound(None,0);meta=export(d,row,clip/'board',programming=programming);finish(d);configure(d,enabled=False,wake=False,seconds=20)
        actions=[]
        def audit(kind,**fields):
            r.event(kind,**fields)
            if kind=='audiotag_request':actions.append(fields['action'])
        result=AudioTagClient(store,audit=audit).recognize(uuid.uuid4().hex,meta['wav'])
        expected={'title':title,'artist':track['artist']};correct=same_song(result,expected) and result.get('source')=='audiotag'
        trial={'expected':expected,'source':'fresh_real_board_microphone_laptop_playback_development','metadata':meta,'result':result,
            'correct':correct,'API_actions':actions,'one_upload':actions.count('identify')<=1,'not_phone_acceptance':True}
        rows.append(trial);write_json(clip/'result.json',trial);r.manifest()
        print(json.dumps({'trial':len(rows),'expected':title,'correct':correct,'reason':result.get('reason'),'recognized_title':result.get('title'),
            'cost_yuan':result.get('cost_yuan'),'zero_cost_verified':result.get('zero_cost_verified'),'API_actions':actions},ensure_ascii=False),flush=True)
    result={'run_id':r.run_id,'source':'fresh_real_board_microphone_laptop_playback_development','trials':rows,
        'correct':sum(x['correct'] for x in rows),'total':len(rows),'actual_cost_yuan':0 if all(x['result'].get('zero_cost_verified') and x['result'].get('cost_yuan')==0 for x in rows) else None}
    write_json(r.path/'result.json',result);write_json(ROOT/'state/music_api_capture_development.json',result);r.manifest();print(r.run_id)


if __name__=='__main__':main()
