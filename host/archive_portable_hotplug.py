"""Complete the real hotplug check and preserve the separate pre/post sessions."""
import json,os,shutil,time,zlib,wave
from pathlib import Path
from audit import ROOT,Run,write_json,sha256,now
import monitor_control

def read(p):return json.loads(Path(p).read_text(encoding='utf8'))

def main():
    data=Path(os.environ['LOCALAPPDATA'])/'NexysMonitor';monitor_control.ROOT=data
    current=read(data/'state/monitor_gui.json');new=current['run_id'];old='20261114T170519_481384_monitor_session'
    assert new!=old and current['connected'];summary=read(data/'runs'/new/'session_summary.json')
    assert summary['exported_events'];assert summary['last']['build_id']=='f4e259e1'
    monitor_control.control('close')
    for _ in range(40):
        if read(data/'state/monitor_gui.json')['state']=='closed':break
        time.sleep(.25)
    assert read(data/'state/monitor_gui.json')['state']=='closed'
    h=read(ROOT/'state/portable_hotplug_result.json');run=Run('portable_hotplug',h['run_id'])
    a=read(ROOT/'state/portable_acceptance.json');accept=Run('portable_acceptance',a['run_id'])
    for name in (old,new,'20261114T170816_794816_app_program'):
        source=data/'runs'/name;target=accept.path/'runtime_records'/name
        shutil.copytree(source,target,dirs_exist_ok=True)
    saved=[]
    for m in (data/'runs'/new/'physical').rglob('metadata.json'):
        meta=read(m);p=m.parent/'payload.bin';assert sha256(p)==meta['input_hash']
        assert zlib.crc32(p.read_bytes())==meta['payload_crc32']
        saved.append({'event_id':meta['event_id'],'input_hash':meta['input_hash'],'pcm_count':meta['pcm_count'],'xyz_count':meta['xyz_count']})
    assert saved
    shutil.copy2(data/'pause_final_verified.json',run.path/'pause_verified.json')
    h.update(recovered=True,pre_session=old,post_session=new,programming_run_id='20261114T170816_794816_app_program',
             post_events=saved,exe_sha256=a['build']['exe_sha256'],completed=now(),
             archived_post_session=(accept.path/'runtime_records'/new).relative_to(ROOT).as_posix())
    write_json(run.path/'result.json',h);write_json(ROOT/'state/portable_hotplug_result.json',h)
    a['hotplug']=h;write_json(ROOT/'state/portable_acceptance.json',a);write_json(accept.path/'result.json',a)
    run.event('hotplug_recovery_passed',**h);run.status('P_hotplug','passed','真实USB消失及重插已观察，EXE初始化后恢复并导出完整事件',
        [(run.path/'result.json').relative_to(ROOT).as_posix()],'完成报告')
    accept.event('hotplug_evidence_added',hotplug_run_id=run.run_id,pre_session=old,post_session=new);accept.manifest()
    print(json.dumps(h,ensure_ascii=False))

if __name__=='__main__':main()
