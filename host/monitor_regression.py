"""Automated physical sound, legacy protocol and shared-engine checks on the new bitstream."""
import json,struct,time,wave
import numpy as np
from audit import ROOT,Run,write_json
from hardware import hardware_lock
from protocol import Device,Frame
from program import find_port
from capture import checked,status,list_events,export_event
from audio_stimulus import SpeakerStimulus
from monitor_protocol import monitor_packet,preview_packet,begin_audio,read_audio,spectrum
from features import configure,replay,compare_reference

def regression():
    run=Run('monitor_regression');run.snapshot('新位流真实声音快照、原协议与原判定引擎回归，不重用旧位流结论')
    programming=json.loads((ROOT/'state/active_device.json').read_text(encoding='utf8'))
    with hardware_lock(run),Device(find_port(),run,audit_responses=False) as d,SpeakerStimulus(run,duration_s=1.2) as sound:
        before=status(d);assert before['build_id']==programming['build_id']
        checked(d.request('ARM',bytes((3,0))))
        recovered=[]
        for e in list_events(d):recovered.append(export_event(d,e,run.path/'physical'/f'recovered_event{e["event_id"]}'))
        deadline=time.monotonic()+3
        while not status(d)['ready_mask']:
            assert time.monotonic()<deadline;time.sleep(.05)
        p=checked(d.request('SNAP'));event_id,anchor=struct.unpack_from('<IQ',p,1)
        run.event('snap_anchor',event_id=event_id,anchor_tick=anchor);sound.play(event_id,anchor)
        time.sleep(.5)
        meta=begin_audio(d);pcm=[]
        for offset in range(0,512,240):pcm.extend(read_audio(d,meta['snapshot_id'],offset,min(240,512-offset))['pcm'].tolist())
        hz,dbfs,peak=spectrum(pcm)
        np.savez_compressed(run.path/'tone_snapshot.npz',pcm=np.asarray(pcm,dtype='<i2'),hz=hz,dbfs=dbfs,
            first_tick=meta['first_tick'],first_index=meta['first_index'],sample_rate=16000)
        write_json(run.path/'tone_snapshot_result.json',{'peak_hz':peak,'max_dbfs':float(max(dbfs)),
            'snapshot_first_tick':meta['first_tick'],'anchor_tick':anchor,'pcm':pcm})
        assert abs(peak-1500)<=31.25,(peak,max(dbfs))
        telemetry=[]
        while True:
            telemetry.append(monitor_packet(d.request('MONITOR')))
            available=list_events(d)
            target=next((e for e in available if e['event_id']==event_id),None)
            if target:break
            time.sleep(.03)
        tone=export_event(d,target,run.path/'physical/tone',on_block=lambda offset:preview_packet(d.request('PREVIEW')) if offset%4800==0 else None)
        assert d.request('ECHO',bytes(range(256))*2).payload==bytes(range(256))*2
        crc_before=status(d)['packet_crc_errors']
        bad=bytearray(Frame(11,60001,0,b'monitor CRC fault injection').encode());bad[-1]^=1
        d.tx.write(bad);d.tx.flush();d.serial.write(bad);time.sleep(.06)
        assert status(d)['packet_crc_errors']==crc_before+1
        configure(d,13,39,50,991)
        comparison=[]
        physical=json.loads((ROOT/'runs/20261114T014800_033039_monitor_session/session_summary.json').read_text(encoding='utf8'))
        for directory in [run.path/'physical/tone',ROOT/physical['exported_events'][0]['directory']]:
            rows=replay(d,directory,run.path/(directory.name+'_board.json'))
            result=compare_reference(rows,directory,13,39,50);comparison.append({**result,'input_directory':directory.relative_to(ROOT).as_posix()})
        checked(d.request('REPLAY',b'\x00'));configure(d,13,39,50,2);checked(d.request('ARM',bytes((3,0))))
        after=status(d)
        assert after['overruns']==before['overruns'] and after['uart_framing']==before['uart_framing']
        result={'source':'physical_board','programming':programming,'stimulus':sound.metadata,
            'snapshot_peak_hz':peak,'snapshot_samples':512,'snapshot_first_tick':meta['first_tick'],
            'tone_event':tone,'recovered':recovered,'replay_comparisons':comparison,
            'board_reference_windows':sum(x['windows'] for x in comparison),'echo_512_passed':True,
            'bad_crc_injected_and_rejected':True,'before':before,'after':after,'host_decoder_crc_errors':d.decoder.crc_errors}
        write_json(run.path/'result.json',result);write_json(run.path/'telemetry.json',telemetry)
        run.status('monitor_regression','passed','1500Hz真实短音快照、512B回环、坏CRC拒绝及两条真实输入逐窗板端参考一致',
            [(run.path/'result.json').relative_to(ROOT).as_posix()],'完成界面历史查看和报告',
            bitstream_sha256=programming['bitstream_sha256'],config_sha256=programming['config_sha256'])
    run.manifest();print('RUN_ID='+run.run_id)

if __name__=='__main__':regression()
