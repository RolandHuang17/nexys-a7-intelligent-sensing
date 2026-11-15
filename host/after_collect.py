"""Continue authorized evaluation/report after the physical guide closes."""
import json,sys,time
from pathlib import Path
import psutil
from audit import ROOT,Run,write_json

def main(collection_id):
    run=Run('experiment_flow');collection=ROOT/'runs'/collection_id
    rows=[json.loads(x) for x in (collection/'actions.jsonl').read_text(encoding='utf8').splitlines()]
    pid=next(x['pid'] for x in rows if x['kind']=='hardware_lock_acquired')
    write_json(ROOT/'state/experiment_flow.json',{'pid':psutil.Process().pid,'run_id':run.run_id,'collection_run_id':collection_id,'state':'waiting_for_physical_collection'})
    run.event('flow_waiting',collection_run_id=collection_id,collection_pid=pid)
    while psutil.pid_exists(pid):
        resume=ROOT/'state/resume.json'
        if resume.exists() and json.loads(resume.read_text(encoding='utf8')).get('execution_state')=='user_paused':
            run.event('flow_stopped_by_user_pause');run.manifest();return 2
        time.sleep(1)
    status_path=collection/'status.json'
    state=json.loads(status_path.read_text(encoding='utf8')) if status_path.exists() else {}
    if state.get('stage')!='collect' or state.get('status')!='passed':
        run.status('experiment_flow','failed','实体采样尚未通过，保留原件并等待诊断',[str(status_path.relative_to(ROOT))], '检查集中采样记录')
        return 2
    for action in ('evaluate','report'):
        write_json(ROOT/'state/experiment_flow.json',{'pid':psutil.Process().pid,'run_id':run.run_id,'collection_run_id':collection_id,'state':action})
        argv=[sys.executable,ROOT/'host/harness.py',action]
        rc,text=run.command(argv,'集中实物操作后自动继续'+action,timeout=2400)
        if rc:
            run.status('experiment_flow','failed',action+'未通过；原始记录保留',[], '按首条错误诊断后恢复');return rc
    write_json(ROOT/'state/experiment_flow.json',{'pid':None,'run_id':run.run_id,'collection_run_id':collection_id,'state':'awaiting_visual_review_and_cover'})
    run.event('flow_generated_report_pending_review');run.manifest();return 0

if __name__=='__main__':raise SystemExit(main(sys.argv[1]))
