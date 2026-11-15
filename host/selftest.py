import json,struct,time,wave,winsound,zlib
import numpy as np
from audit import ROOT,Run,write_json,sha256
from capture import status,list_events,snap,export_event,checked
from hardware import hardware_lock
from program import program_latest,find_port
from protocol import Device,Frame


def stimulus(run):
    rate=16000;t=np.arange(int(.4*rate))/rate
    fade=np.minimum(1,np.minimum(t/.01,(.4-t)/.01))
    audio=(16000*np.sin(2*np.pi*1500*t)*fade).astype('<i2')
    path=run.path/'stimulus_1500Hz.wav'
    with wave.open(str(path),'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(rate);wav.writeframes(audio.tobytes())
    run.event('stimulus_prepared',file=path.relative_to(ROOT).as_posix(),sha256=sha256(path),
              frequency_hz=1500,duration_s=.4,endpoint='Windows default output',volume='current setting; not changed')
    def play(event_id,anchor):
        winsound.PlaySound(str(path),winsound.SND_FILENAME|winsound.SND_ASYNC)
        run.event('stimulus_play_requested',event_id=event_id,anchor_tick=anchor)
    return play


def selftest():
    run=Run('selftest');run.snapshot('A1 实板自检：静置、电脑短音、双缓冲、错误 ACK、断线恢复')
    try:
        programmed=program_latest(run)
        time.sleep(2)
        port=find_port();play=stimulus(run)
        with hardware_lock(run):
            with Device(port,run) as device:
                hello=device.request('HELLO');checked(hello)
                first_status=status(device);write_json(run.path/'status_before.json',first_status)
                assert first_status['build_id']==programmed['build_id']
                assert first_status['configured'] and first_status['id_ok'],first_status
                golden=bytes(range(256))*2
                assert device.request('ECHO',golden).payload==golden
                run.event('board_echo_passed',bytes=512,source='board_uart')
                quiet=snap(device)
                duplicate=device.request('READ',struct.pack('<IH',0,480),quiet['event_id'])
                assert duplicate.payload==device.request('READ',struct.pack('<IH',0,480),quiet['event_id']).payload
                bad=device.request('ACK',struct.pack('<II',quiet['payload_length'],quiet['payload_crc32']^1),quiet['event_id'])
                assert bad.payload==b'\x05'
                assert next(e for e in list_events(device) if e['event_id']==quiet['event_id'])['payload_crc32']==quiet['payload_crc32']
                second=[]
                def during_export(offset):
                    if offset==4800 and not second:second.append(snap(device,play))
                quiet_data=export_event(device,quiet,run.path/'physical/quiet',ack=False,on_block=during_export)
                assert len(list_events(device))==2
                rejected=device.request('SNAP',retries=0)
                assert rejected.payload==b'\x02'
                write_json(run.path/'both_frozen.json',list_events(device))
                run.event('pressure_cases_passed',cases=['duplicate block','wrong ACK CRC rejected','second capture during export','both banks frozen; third SNAP rejected'])
            # Reconnect without reprogramming or power cycling: frozen event must survive.
            with Device(port,run) as device:
                recovered=list_events(device)
                quiet_again=next(e for e in recovered if e['event_id']==quiet['event_id'])
                replayed=export_event(device,quiet_again,run.path/'physical/quiet_after_reconnect')
                assert replayed['input_hash']==quiet_data['input_hash']
                assert checked(device.request('ACK',struct.pack('<II',quiet_again['payload_length'],quiet_again['payload_crc32']),quiet_again['event_id']))==b'\x00'
                tone=next(e for e in list_events(device) if e['event_id']==second[0]['event_id'])
                tone_data=export_event(device,tone,run.path/'physical/computer_tone')
                final_status=status(device);write_json(run.path/'status_after.json',final_status)
                assert final_status['overruns']==first_status['overruns']
                assert final_status['xyz_count']>first_status['xyz_count'] and final_status['pcm_count']>first_status['pcm_count']
        results={'quiet':quiet_data,'computer_tone':tone_data,'before':first_status,'after':final_status,
                 'programming':programmed,'microphone_response_ratio':tone_data['audio_rms']/max(quiet_data['audio_rms'],1)}
        write_json(run.path/'results.json',results)
        assert 500<quiet_data['gravity_mg']<1500,quiet_data
        assert tone_data['audio_peak']>0 and quiet_data['xyz_count']>200
        assert quiet_data['audio_std']>1 and quiet_data['audio_saturated_samples']<240
        evidence=[(run.path/'results.json').relative_to(ROOT).as_posix()]
        run.status('A1a','needs_user','真实 PCM/XYZ、自检回读、重力和时间戳检查通过；尚待真实敲击响应',evidence,
                   '集中采样首个开发组敲击补齐验收；期间准备后续数字逻辑',bitstream_sha256=programmed['bitstream_sha256'],config_sha256=programmed['config_sha256'])
        run.status('A1b','needs_user','完整窗口、整事件 CRC、双缓冲及断线恢复检查通过；待 A1a 敲击响应后正式通过',evidence,
                   '关联集中采样首个真实敲击的双通道记录',bitstream_sha256=programmed['bitstream_sha256'],config_sha256=programmed['config_sha256'])
        print(json.dumps(results,ensure_ascii=False,indent=2))
        return 0
    except Exception as error:
        run.event('selftest_failed',error=repr(error))
        run.status('A1a','failed',repr(error),[], '检查完整串口包、状态及编程日志后修复重试')
        raise
    finally:
        run.manifest();print('RUN_ID='+run.run_id)


if __name__=='__main__':raise SystemExit(selftest())
