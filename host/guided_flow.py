"""One durable parent executes the physical guide and authorized next stages."""
import json,sys,os
from audit import ROOT,Run,write_json

def main():
    run=Run('guided_experiment_flow');run.snapshot('用户重新开始：实体引导、评价、报告由同一后台流程顺序执行')
    for action,timeout in (('collect',7200),('evaluate',2400),('report',900)):
        record={'pid':os.getpid(),'run_id':run.run_id,'state':action}
        write_json(ROOT/'state/experiment_flow.json',record)
        rc,text=run.command([sys.executable,ROOT/'host/harness.py',action], '集中实体实验流程：'+action,timeout=timeout)
        state_path=ROOT/'state'/action/'status.json'
        stage=json.loads(state_path.read_text(encoding='utf8')) if state_path.exists() else {}
        if rc or (action!='report' and stage.get('status')!='passed'):
            write_json(ROOT/'state/experiment_flow.json',{**record,'state':'failed','failed_action':action,'stage_run_id':stage.get('run_id')})
            run.status('experiment_flow','failed',action+'尚未通过，保留原始数据等待诊断',[], '查看对应阶段首条失败');return rc or 2
    write_json(ROOT/'state/experiment_flow.json',{'pid':None,'run_id':run.run_id,'state':'awaiting_visual_review_and_cover'})
    run.event('report_ready_for_visual_review');run.manifest();return 0

if __name__=='__main__':raise SystemExit(main())
