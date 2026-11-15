"""Read genuine new sensor channels and test old event export on the same bitstream."""
import argparse,json,struct,time
import numpy as np
from audit import ROOT,Run,write_json
from hardware import hardware_lock
from program import program_latest,find_port
from protocol import Device
from capture import status,snap,export_event
from monitor_protocol import monitor_packet,preview_packet,begin_audio,read_audio,SequenceCursor

def probe(program=True,duration=20,event=True):
    run=Run('monitor_board_probe');run.snapshot('新增通道首次实板读取及保留声振记录回归')
    programming=program_latest(run) if program else json.loads((ROOT/'state/active_device.json').read_text(encoding='utf8'))
    rows=[];previews=[];periods=[];xc=SequenceCursor();ac=SequenceCursor()
    with hardware_lock(run),Device(find_port(),run,audit_responses=False) as d:
        start=time.monotonic();previous=start
        while time.monotonic()-start<duration:
            tick=time.monotonic();periods.append(tick-previous);previous=tick
            row=monitor_packet(d.request('MONITOR'));preview=preview_packet(d.request('PREVIEW'))
            assert row['build_id']==programming['build_id']
            xc.accept(row['xyz_records']);ac.accept(preview['points']);rows.append(row);previews.append(preview)
            time.sleep(max(0,.04-(time.monotonic()-tick)))
        write_json(run.path/'monitor_rows.json',rows);write_json(run.path/'preview_rows.json',previews)
        last=rows[-1]
        assert last['adxl_configured'] and last['adxl_id_ok'] and last['adxl_temperature_valid']
        assert last['adt_configured'] and last['adt_valid'] and last['adt_identity']&0xf8==0xc8 and last['adt_configuration']==128,last
        assert last['adt_errors']==0 and last['xadc_valid_mask']==15,last
        assert -40<last['adt_c']<125 and -40<last['die_c']<125,last
        for name,lo,hi in [('vccint_v',.9,1.1),('vccaux_v',1.6,2.0),('vccbram_v',.9,1.1)]:assert lo<last[name]<hi,(name,last)
        assert all(b['tick']>a['tick'] for a,b in zip(rows,rows[1:]))
        meta=begin_audio(d);pcm=[]
        for offset in range(0,512,240):pcm.extend(read_audio(d,meta['snapshot_id'],offset,min(240,512-offset))['pcm'].tolist())
        assert len(pcm)==512
        write_json(run.path/'audio_snapshot.json',{**{k:v for k,v in meta.items() if k!='pcm'},'pcm':pcm})
        before=status(d);event_result=None
        if event:
            capture=snap(d)
            event_result=export_event(d,capture,run.path/'physical/manual',on_block=lambda offset:monitor_packet(d.request('MONITOR')) if offset%4800==0 else None)
            assert event_result['pcm_count']==24000 and event_result['xyz_count']>200
        after=status(d)
        assert after['overruns']==before['overruns'] and after['uart_framing']==before['uart_framing']
        result={'source':'physical_board','programming':programming,'duration_s':time.monotonic()-start,'rows':len(rows),
            'poll_median_s':float(np.median(periods[1:])),'poll_p99_s':float(np.percentile(periods[1:],99)),
            'preview_missing_bins':ac.missing,'xyz_missing_preview_samples':xc.missing,'last':last,
            'before':before,'after':after,'event':event_result,'crc_errors':d.decoder.crc_errors}
        write_json(run.path/'result.json',result)
        run.status('M3','passed','新增器件身份/配置、三路电压和温度均有真实回读，原事件CRC与WAV导出通过',
            [(run.path/'result.json').relative_to(ROOT).as_posix()],'完善实时界面并集中进行开关、按键及敲击操作',
            bitstream_sha256=programming['bitstream_sha256'],config_sha256=programming['config_sha256'])
    run.manifest();print('RUN_ID='+run.run_id)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--no-program',action='store_true');p.add_argument('--seconds',type=float,default=20);p.add_argument('--no-event',action='store_true');a=p.parse_args()
    probe(not a.no_program,a.seconds,not a.no_event)
