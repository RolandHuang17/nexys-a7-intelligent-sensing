"""Concentrated, visibly guided physical collection; no detection-based rejection."""
import json,time,struct,traceback
from pathlib import Path
from audit import ROOT,Run,write_json,sha256,now
from capture import checked,status,snap,list_events,export_event
from features import configure,arm,collect_features,read_features,independent_features
from experiment import order,freeze
from guidance import Guidance
from hardware import hardware_lock
from program import find_port
from protocol import Device


def collect():
    run=Run('collect');run.snapshot('集中实体实验：10s校准、开发/冻结/留出、60s安静、LIVE')
    active=json.loads((ROOT/'state/active_device.json').read_text(encoding='utf-8'))
    write_json(run.path/'programming.json',active)
    manifest={'run_id':run.run_id,'started':now(),'source':'physical_board','programming':active,
              'sound_stimulus':'在板旁说一次“测试”，不碰桌面；外放短音未验证，改用人声',
              'sound_level':'自然说话音量；无校准声压','board_placement':'用户原照片：亚克力外壳平放木桌，未拆板',
              'trials':[],'failed_trials':[]}
    write_json(run.path/'session.json',manifest)
    guide=Guidance()

    def worker(ui):
        player=None
        def pause(seconds):
            end=time.monotonic()+seconds
            while time.monotonic()<end:
                if ui.stop.is_set():raise InterruptedError('用户停止；已完成记录均保留')
                time.sleep(min(.05,max(0,end-time.monotonic())))
        def save():write_json(run.path/'session.json',manifest)
        try:
            with hardware_lock(run),Device(find_port(),run) as device:
                checked(device.request('HELLO'))
                checked(device.request('REPLAY',b'\x00'))
                s=status(device);write_json(run.path/'status_before.json',s)
                if s['build_id']!=active['build_id']:raise ValueError('板端版本与编程记录不一致')
                if list_events(device):raise ValueError('有未导出事件；不得覆盖，先恢复导出')
                arm(device,False)
                configure(device,100,10,50,0)
                speaker=None
                speaker_path=ROOT/'state/speaker_stimulus.json'
                if speaker_path.exists() and json.loads(speaker_path.read_text(encoding='utf8')).get('passed'):
                    speaker=json.loads(speaker_path.read_text(encoding='utf8'))
                button=s['button_presses']
                ui.show('准备好后按一下 BTNU',
                        '实验约五分钟。\n敲桌面：轻敲一次。\n只有声音：'+('电脑自动播放，请不动。' if speaker else '板旁说“测试”，不碰桌。')+'\n安静：保持不动。\n等待绿色动作提示再操作。',urgent=True)
                run.event('physical_action_ready',action='按一下 BTNU 开始整轮采样，跟随窗口提示')
                while status(device)['button_presses']==button:pause(.1)
                run.event('user_started_by_btnu',counter=status(device)['button_presses'])
                if speaker:
                    from audio_stimulus import SpeakerStimulus
                    player=SpeakerStimulus(run,speaker['volume_scalar'])
                    manifest.update(sound_stimulus='电脑自动播放固定1500Hz、400ms短音；笔记本内置外放',
                                    sound_level=f'Windows音量{player.scalar*100:.0f}%；声压未标定',
                                    stimulus=player.metadata,stimulus_validation_run_id=speaker['validation_run_id'])
                    save()
                ui.show('静置校准 10 秒','请保持安静，不碰板子和桌面。')
                calibration=collect_features(device,10)
                write_json(run.path/'calibration.json',{'source':'board_live_features','rows':calibration})
                manifest['calibration_windows']=len(calibration);save()
                previous=0;development=[]
                for session in ('development','holdout'):
                    labels=order(session)
                    for index,label in enumerate(labels,1):
                        attempt=0
                        while True:
                            attempt+=1;trial_id=f'{session}_{index:02d}_{label}_a{attempt}'
                            title={'tap':'敲桌面','sound':'只有声音','quiet':'安静'}[label]
                            while time.monotonic()-previous<5:pause(.05)
                            ui.show(f'{"开发" if session=="development" else "留出"} {index}/15：准备',
                                    f'下一次：{title}。等待倒计时结束再动作。')
                            for remaining in (2,1):
                                ui.show(f'准备 {remaining}',f'下一次：{title}');pause(.65)
                            cue={}
                            def prompt(event_id,anchor):
                                previous_cue=time.monotonic()
                                ui.show('现在：'+title,{'tap':'请在 1 秒内用手指轻敲桌面一次。',
                                    'sound':'电脑自动播放短音，请保持不动。' if player else '请在板旁说一声“测试”，不碰桌面。','quiet':'继续保持安静，不动。'}[label],trial_id,True)
                                if label=='sound' and player:player.play(event_id,anchor)
                                cue.update(time=now(),monotonic=previous_cue,event_id=event_id,anchor_tick=anchor)
                                run.event('trial_cue',trial_id=trial_id,label=label,**cue)
                            trial={'trial_id':trial_id,'session':session,'label':label,'mode':'reference_snap',
                                   'source':'board_snap','threshold_id':0 if session=='development' else 1,
                                   't_audio':None,'t_accel':None,'t_confirm':None,'captured':False,
                                   'suppress_reason':None,'input_hash':None}
                            try:
                                event=snap(device,prompt);previous=cue['monotonic']
                                data=export_event(device,event,run.path/'physical'/trial_id)
                                trial.update(event_id=event['event_id'],captured=True,input_hash=data['input_hash'],
                                             directory=str((run.path/'physical'/trial_id).relative_to(ROOT)),cue=cue)
                                # The visible missed button stays available during export and the minimum interval.
                                while time.monotonic()-previous<5:pause(.05)
                                if trial_id in ui.missed:
                                    trial.update(included=False,exclusion_reason='用户在引导窗口明确标记漏做')
                                    manifest['failed_trials'].append(trial);run.event('trial_missed',**trial);save();continue
                                trial['included']=True;manifest['trials'].append(trial);save()
                                if session=='development':development.append((trial,independent_features(run.path/'physical'/trial_id)))
                                run.event('trial_completed',**trial)
                                break
                            except (TimeoutError,ValueError) as error:
                                trial.update(included=False,exclusion_reason='technical_capture_failure',error=repr(error))
                                manifest['failed_trials'].append(trial);save();raise
                    if session=='development':
                        ui.show('开发组完成，正在冻结参数','请稍候；接下来是独立留出组。')
                        from experiment import scored
                        import numpy as np
                        bg={key:float(np.percentile([r[key] for r in calibration if r[key] is not None],99)) for key in ('audio','accel')}
                        response=any(all(max(r[key] or 0 for r in scored(rows))>bg[key] for key in ('audio','accel'))
                                     for trial,rows in development if trial['label']=='tap')
                        if not response:raise RuntimeError('开发组真实敲击未取得双通道响应，保留15份原始数据并先诊断前端')
                        for stage in ('A1a','A1b'):
                            run.status(stage,'passed','真实敲击两通道均高于静置99百分位；完整WAV/XYZ及CRC已有证据',
                                       [str((run.path/'session.json').relative_to(ROOT))], '进入两种单路实板自动触发验收',
                                       bitstream_sha256=active['bitstream_sha256'],config_sha256=active['config_sha256'])
                        config=freeze(calibration,development);write_json(run.path/'frozen_config.json',config)
                        manifest['frozen_config_sha256']=sha256(run.path/'frozen_config.json');save()
                        run.event('configuration_frozen',sha256=manifest['frozen_config_sha256'],config=config)
                        configure(device,config['thresholds']['audio'],config['thresholds']['accel'],config['window_ms'],1)
                mode_tests=[]
                for mode,title,detail in ((1,'只声音自动记录','看到提示后，在板旁说一声“测试”，不碰桌面。'),
                                          (2,'只振动自动记录','看到提示后，用手指轻敲桌面一次。')):
                    if mode==1 and player:detail='电脑自动播放短音，请保持不动。'
                    ui.show('单路实板验收：'+title,'准备；'+detail);pause(2)
                    before=status(device);cursor=before['feature_count'];stream=[]
                    arm(device,True,mode)
                    pause(.12)
                    ui.show('现在：'+title,detail,urgent=True)
                    if mode==1 and player:player.play()
                    run.event('single_mode_cue',mode=mode,status=before)
                    deadline=time.monotonic()+5;events=[]
                    while time.monotonic()<deadline:
                        part=read_features(device,cursor);stream+=part;cursor+=len(part)
                        events=list_events(device)
                        if events:break
                        pause(.03)
                    arm(device,False)
                    test={'mode':mode,'source':'board_live','rows':stream,'before':before,'after':status(device),'events':[]}
                    for event in events:
                        test['events'].append(export_event(device,event,run.path/'physical'/f'mode{mode}_event{event["event_id"]}',source='board_live'))
                    mode_tests.append(test);write_json(run.path/'single_modes.json',mode_tests)
                    pause(1)
                ui.show('连续安静观察 60 秒','保持安静，不碰桌面；系统现在自动布防。')
                arm(device,True,3)
                initial=status(device);cursor=initial['feature_count'];rows=[];quiet_events=[]
                def drain(_=None):
                    nonlocal cursor
                    while True:
                        part=read_features(device,cursor);rows.extend(part);cursor+=len(part)
                        if len(part)<15:break
                while True:
                    if ui.stop.is_set():raise InterruptedError('用户停止安静观察')
                    drain();s=status(device)
                    if s['ticks']-initial['ticks']>=6000000000:break
                    for event in list_events(device):
                        quiet_events.append(export_event(device,event,run.path/'physical'/f'quiet60_event{event["event_id"]}',
                                                         source='board_live_quiet',on_block=drain))
                    pause(.06)
                arm(device,False);drain();final=status(device)
                quiet={'source':'board_live','before':initial,'after':final,'duration_s':(final['ticks']-initial['ticks'])/1e8,
                       'rows':rows,'events':quiet_events}
                write_json(run.path/'quiet60.json',quiet)
                for event in list_events(device):
                    export_event(device,event,run.path/'physical'/f'quiet60_trailing{event["event_id"]}',source='board_live_quiet')
                ui.show('最后一次：在线自动捕捉','看到“现在轻敲”再轻敲一次；本次由声振判定触发，不发 SNAP。')
                pause(2)
                live_start=status(device);arm(device,True,3)
                pause(.12)
                cursor=live_start['feature_count'];live_rows=[]
                ui.show('现在轻敲一次桌面','轻敲一次，然后等待保存。',urgent=True)
                run.event('live_tap_cue',time=now(),status=live_start)
                deadline=time.monotonic()+5;events=[]
                while time.monotonic()<deadline:
                    part=read_features(device,cursor);live_rows+=part;cursor+=len(part)
                    events=list_events(device)
                    if events:break
                    pause(.03)
                arm(device,False)
                live={'source':'board_live','before':live_start,'after':status(device),'rows':live_rows,'events':[]}
                for event in events:
                    live['events'].append(export_event(device,event,run.path/'physical'/f'LIVE_event{event["event_id"]}',source='board_live'))
                write_json(run.path/'live.json',live);write_json(run.path/'status_after.json',status(device))
                manifest['finished']=now();manifest['quiet60']='quiet60.json';manifest['live']='live.json';save()
                if not live['events']:
                    run.status('collect','failed','集中参考采样完成，最终 LIVE 未取得自动冻结事件',
                               [str((run.path/'session.json').relative_to(ROOT))], '先分析真实波形及候选，再修复或补在线试次')
                    ui.show('原始试次已保存','在线未捕获；正在保留候选与状态，随后自动诊断。')
                else:
                    run.status('collect','passed','30份独立参考试次、校准、连续安静与真实 LIVE 均已归档',
                               [str((run.path/'session.json').relative_to(ROOT))], '进行同输入板端 REPLAY 与独立参考核对',
                               bitstream_sha256=active['bitstream_sha256'],config_sha256=manifest['frozen_config_sha256'])
                    ui.show('集中采样完成','可以停止动作了；系统将自动核对数据、绘图并编译报告。')
        except BaseException as error:
            run.event('collection_stopped',error=repr(error),traceback=traceback.format_exc());save()
            run.status('collect','failed',repr(error),[str((run.path/'session.json').relative_to(ROOT))], '保留已采数据，定位故障后恢复')
            raise
        finally:
            if player:player.close()
            run.manifest()
    guide.run(worker);print('RUN_ID='+run.run_id)
    return 0

if __name__=='__main__':raise SystemExit(collect())
