import json
import numpy as np
from audit import ROOT,Run,write_json
from audio_stimulus import SpeakerStimulus
from hardware import hardware_lock
from protocol import Device
from program import find_port
from capture import snap,export_event,checked,status
from features import load_event,arm

def verify():
    run=Run('speaker_validation');run.snapshot('已确认笔记本外放：固定30%音量短音与静置实板对照')
    active=json.loads((ROOT/'state/active_device.json').read_text(encoding='utf8'));write_json(run.path/'programming.json',active)
    with hardware_lock(run),Device(find_port(),run) as device:
        checked(device.request('HELLO'));arm(device,False)
        before=status(device);assert before['build_id']==active['build_id']
        quiet=export_event(device,snap(device),run.path/'physical/quiet')
        with SpeakerStimulus(run) as player:
            tone=export_event(device,snap(device,player.play),run.path/'physical/computer_tone')
            stimulus=player.metadata
        _,pcm,_,first=load_event(run.path/'physical/computer_tone');t=(first+np.arange(len(pcm))*6250-50000000)/1e8
        def statistics(mask):
            x=pcm[mask].astype(float);x-=np.mean(x);spectrum=np.abs(np.fft.rfft(x*np.hanning(len(x))))**2
            freq=np.fft.rfftfreq(len(x),1/16000);band=(freq>=1475)&(freq<=1525)
            return {'std':float(x.std()),'tone_band_power':float(np.sum(spectrum[band])/len(x)**2),
                    'dominant_hz':float(freq[np.argmax(spectrum)])}
        pre=statistics((t>=-.45)&(t<-.05));post=statistics((t>=.03)&(t<.63))
        ratio=post['tone_band_power']/max(pre['tone_band_power'],1e-12)
        passed=ratio>=10 and post['std']>=1.5*max(pre['std'],1)
        result={'passed':bool(passed),'quiet':quiet,'tone':tone,'pre':pre,'post':post,'tone_band_ratio':ratio,
                'criterion':'1500±25Hz功率为前段至少10倍，后段标准差至少1.5倍','stimulus':stimulus}
        write_json(run.path/'result.json',result)
        if passed:write_json(ROOT/'state/speaker_stimulus.json',{'validation_run_id':run.run_id,**stimulus,'passed':True})
    run.status('speaker_validation','passed' if passed else 'failed','固定外放短音拾取验证通过' if passed else '尚未证明固定外放短音被稳定拾取',
               [str((run.path/'result.json').relative_to(ROOT))],'使用固定短音集中采样' if passed else '诊断输出路由和声源位置后重试')
    run.manifest();print(json.dumps({'passed':bool(passed),'pre':pre,'post':post,'ratio':ratio},ensure_ascii=False));print('RUN_ID='+run.run_id)
    return 0 if passed else 2

if __name__=='__main__':raise SystemExit(verify())
