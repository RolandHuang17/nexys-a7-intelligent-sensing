"""Evaluate identical physical records on the FPGA and independent host code."""
import json,csv,time,struct
from pathlib import Path
import numpy as np
from audit import ROOT,Run,write_json,sha256
from capture import checked,status,snap,export_event,list_events
from features import configure,replay,compare_reference,independent_features,load_event
from experiment import metrics,scored,decisions
from hardware import hardware_lock
from program import find_port
from protocol import Device

def evaluate(collection=None):
    if collection is None:
        state=json.loads((ROOT/'state/collect/status.json').read_text(encoding='utf8'));collection=ROOT/'runs'/state['run_id']
    collection=Path(collection);session=json.loads((collection/'session.json').read_text(encoding='utf8'))
    config=json.loads((collection/'frozen_config.json').read_text(encoding='utf8'))
    if sha256(collection/'frozen_config.json')!=session['frozen_config_sha256']:raise ValueError('冻结配置哈希不符')
    run=Run('evaluate');run.snapshot('同批真实记录：板端REPLAY与独立特征及三策略比较')
    thresholds=config['thresholds'];window=config['window_ms'];comparisons=[];groups={'development':[],'holdout':[]}
    try:
        with hardware_lock(run),Device(find_port(),run) as device:
            active=json.loads((ROOT/'state/active_device.json').read_text(encoding='utf8'))
            write_json(run.path/'programming.json',active)
            if active['bitstream_sha256']!=session['programming']['bitstream_sha256']:raise ValueError('采样后判定固件已改变，需重验LIVE')
            configure(device,thresholds['audio'],thresholds['accel'],window,1)
            for index,trial in enumerate(session['trials'],1):
                directory=ROOT/trial['directory'];meta,audio,xyz,first=load_event(directory)
                if sha256(directory/'payload.bin')!=trial['input_hash']:raise ValueError('原始样本哈希不符')
                print(f'REPLAY {index}/{len(session["trials"])} {trial["trial_id"]}',flush=True)
                raw=replay(device,directory,run.path/(trial['trial_id']+'_board.json'))
                comparison=compare_reference(raw,directory,thresholds['audio'],thresholds['accel'],window)
                reference=independent_features(directory)
                write_json(run.path/(trial['trial_id']+'_reference.json'),{'input_hash':trial['input_hash'],'rows':reference})
                groups[trial['session']].append((trial,reference))
                comparison.update(trial_id=trial['trial_id'],input_hash=trial['input_hash'],event_id=trial['event_id'])
                comparisons.append(comparison);write_json(run.path/'comparisons.json',comparisons)
            checked(device.request('REPLAY',b'\x00'))
            # A real frozen event must survive deliberately slowed export and
            # a discarded READ response while both frontends keep sampling.
            before_pressure=status(device)
            pressure_event=snap(device)
            checked(device.request('READ',struct.pack('<IH',0,480),pressure_event['event_id']))
            run.event('read_response_intentionally_discarded',event_id=pressure_event['event_id'],offset=0,bytes=480)
            slow=export_event(device,pressure_event,run.path/'physical/slow_export',source='board_pressure',ack=False,on_block=lambda offset:time.sleep(.015))
            still_frozen=next(e for e in list_events(device) if e['event_id']==pressure_event['event_id'])
            assert still_frozen['payload_crc32']==pressure_event['payload_crc32']
            repeated=export_event(device,still_frozen,run.path/'physical/recovered_export',source='board_pressure')
            after_pressure=status(device)
            assert slow['input_hash']==repeated['input_hash']
            assert after_pressure['overruns']==before_pressure['overruns']
            pressure={'source':'physical_board','discarded_read_response':True,'artificial_delay_per_read_block_s':.015,
                      'slow_export_s':slow['export_s'],'repeat_export_s':repeated['export_s'],'payload_identical':True,
                      'input_hash':slow['input_hash'],'before':before_pressure,'after':after_pressure}
            write_json(run.path/'pressure.json',pressure)
        result={g:metrics(trials,thresholds,window) for g,trials in groups.items()}
        rows=[];event_rows=[]
        for group,trials in groups.items():
            for trial,features in trials:
                for mode in ('audio','accel','joint'):
                    metric=next(t for t in result[group][mode]['trials'] if t['trial_id']==trial['trial_id'])
                    raw_meta=json.loads((ROOT/trial['directory']/'metadata.json').read_text(encoding='utf8'))
                    rows.append({**trial,'source':'board_replay_verified','captured':False,'raw_captured':trial['captured'],
                                 'raw_config_id':raw_meta['config_id'],'threshold_id':1,'mode':mode,'evaluation_source':'board_replay_and_independent_reference',
                                 'outcome':metric['outcome'],'detections':metric['count'],'extra_detections':max(0,metric['count']-1),
                                 'replay_captured':False,'replay_storage_reason':'analysis_only_no_storage',
                                 'frozen_config_sha256':session['frozen_config_sha256']})
                for row in decisions(features,thresholds['audio'],thresholds['accel'],window):
                    if not (row['audio_cross'] or row['accel_cross'] or row['joint']):continue
                    event_rows.append({'trial_id':trial['trial_id'],'session':group,'label':trial['label'],
                        'source':'board_replay_verified','original_event_id':trial['event_id'],'input_hash':trial['input_hash'],
                        'threshold_id':1,'tick_virtual':row['tick'],'audio_cross':row['audio_cross'],'accel_cross':row['accel_cross'],
                        't_audio_virtual':row['joint']['t_audio'] if row['joint'] else (row['tick'] if row['audio_cross'] else None),
                        't_accel_virtual':row['joint']['t_accel'] if row['joint'] else (row['tick'] if row['accel_cross'] else None),
                        't_confirm_virtual':row['joint']['t_confirm'] if row['joint'] else None,
                        'deduplicated':row['joint']['dedup'] if row['joint'] else False,'captured':False,'suppress_reason':'REPLAY_analysis_only'})
        for name,data in (('trial_results.csv',rows),('candidate_confirmations.csv',event_rows)):
            with (run.path/name).open('w',encoding='utf-8-sig',newline='') as f:
                if data:
                    writer=csv.DictWriter(f,fieldnames=list(data[0]));writer.writeheader();writer.writerows(data)
        result.update(collection_run_id=collection.name,config=config,board_reference_windows=sum(c['windows'] for c in comparisons),
                      comparisons=comparisons,bitstream_sha256=active['bitstream_sha256'],pressure=pressure)
        latency_path=ROOT/'state/latency_model.json'
        if latency_path.exists():
            latency=json.loads(latency_path.read_text(encoding='utf8'))
            write_json(run.path/'timestamp_delay_metadata.json',{'bitstream_sha256':active['bitstream_sha256'],
                       'raw_timestamps':'数据可用时刻，未减去滤波延迟；REPLAY为统一重置虚拟时基',
                       'latency_model':latency,'applies_to_input_hashes':[t['input_hash'] for t in session['trials']]})
        cal=json.loads((collection/'calibration.json').read_text(encoding='utf8'))['rows']
        tap_responses=[]
        for trial,rows in groups['development']:
            if trial['label']!='tap':continue
            features=scored(rows)
            tap_responses.append({'trial_id':trial['trial_id'],'max_audio':max(r['audio'] or 0 for r in features),
                                  'max_accel':max(r['accel'] or 0 for r in features), 'input_hash':trial['input_hash']})
        raw_response=any(t['max_audio']>thresholds['audio'] and t['max_accel']>thresholds['accel'] for t in tap_responses)
        result['real_tap_responses']=tap_responses
        single_modes=json.loads((collection/'single_modes.json').read_text(encoding='utf8'))
        single_valid=all(any(e['mode']==test['mode'] and e['anchor_tick']==e['t_confirm'] for e in test['events'])
                         for test in single_modes) and len(single_modes)==2
        result['single_modes_verified']=single_valid
        live=json.loads((collection/'live.json').read_text(encoding='utf8'))
        live_valid=bool(live['events'])
        for event in live['events']:
            live_valid=live_valid and event['source']=='board_live' and event['anchor_tick']==event['t_confirm']
            live_valid=live_valid and abs(event['t_audio']-event['t_accel'])<=window*100000
            live_valid=live_valid and event['window_end']-event['window_start']==150000000
        quiet=json.loads((collection/'quiet60.json').read_text(encoding='utf8'))
        result['quiet60']={'duration_s':quiet['duration_s'],'windows':len(quiet['rows']),
            'audio_candidates':sum(r['audio_cross'] for r in quiet['rows']),
            'accel_candidates':sum(r['accel_cross'] for r in quiet['rows']),
            'pairs':sum(r['joint_pair'] for r in quiet['rows']),'confirmations':sum(r['joint_confirm'] for r in quiet['rows']),
            'audio_valid':sum(r['audio'] is not None for r in quiet['rows']),
            'accel_valid':sum(r['accel'] is not None for r in quiet['rows']),
            'pcm_samples':quiet['after']['pcm_count']-quiet['before']['pcm_count'],
            'xyz_samples':quiet['after']['xyz_count']-quiet['before']['xyz_count'],
            'overrun_delta':quiet['after']['overruns']-quiet['before']['overruns']}
        result['live_verified']=live_valid
        write_json(run.path/'results.json',result)
        evidence=[str((run.path/'results.json').relative_to(ROOT)),str((collection/'session.json').relative_to(ROOT))]
        if raw_response:
            for stage in ('A1a','A1b'):
                run.status(stage,'passed','真实敲击双通道响应补齐；结合先前完整窗口、CRC、回卷和双缓冲证据',evidence,
                           '进入单路与联合实测对照',bitstream_sha256=active['bitstream_sha256'],config_sha256=session['frozen_config_sha256'])
        else:run.status('A1a','failed','真实敲击未证明双通道高于静置阈值',evidence,'定位声源、机械耦合及前端')
        run.status('A2','passed' if raw_response and single_valid else 'failed','相同真实输入逐窗板端/独立参考对照；两种单路自动记录均可追溯',
                   evidence,'核对联合与LIVE',bitstream_sha256=active['bitstream_sha256'],config_sha256=session['frozen_config_sha256'])
        passed=raw_response and single_valid and live_valid and quiet['duration_s']>=60 and len(session['trials'])==30
        run.status('A3','passed' if passed else 'failed','联合判定回放逐窗一致，真实LIVE及连续安静已核对' if passed else '尚缺真实响应或LIVE/连续安静证据',
                   evidence,'生成案例图和报告' if passed else '定位缺项并补验',bitstream_sha256=active['bitstream_sha256'],config_sha256=session['frozen_config_sha256'])
        run.status('evaluate','passed' if passed else 'failed','对照实测核对完成' if passed else '对照完成但实板准入条件尚有缺项',evidence,
                   '生成报告与复现包' if passed else '诊断缺项',bitstream_sha256=active['bitstream_sha256'],config_sha256=session['frozen_config_sha256'])
        print(json.dumps(result['holdout'],ensure_ascii=False,indent=2));return 0 if passed else 2
    except Exception as error:
        run.event('evaluation_failed',error=repr(error));run.status('evaluate','failed',repr(error),[],'从首个不一致窗口诊断并重试');raise
    finally:run.manifest();print('RUN_ID='+run.run_id)

if __name__=='__main__':
    import sys
    raise SystemExit(evaluate(sys.argv[1] if len(sys.argv)>1 else None))
