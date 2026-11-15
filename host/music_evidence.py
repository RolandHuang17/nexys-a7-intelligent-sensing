"""Read completed physical music trials without scoring an interrupted attempt."""
import datetime as dt,json
from pathlib import Path
from audit import ROOT,sha256


def summarize(saved,run_id,complete=False):
    rows=saved.get('results',[])
    online=[r for r in rows if r.get('kind')=='online']
    outside=[r for r in online if r.get('outside_library')]
    wakes=[r for r in rows if r.get('kind') in ('online','wake') and r.get('wake_attempted',True)]
    def correct(row):
        return bool(row.get('online_correct') and row.get('result',{}).get('source')=='audiotag')
    return {**saved,'schema':'online_priority_v1','run_id':run_id,'complete':complete,
        'online_correct':sum(correct(r) for r in online),'online_total':len(online),
        'outside_online_correct':sum(correct(r) for r in outside),'outside_online_total':len(outside),
        'double_wake_success':sum(bool(r.get('wake_success')) for r in wakes),'double_wake_total':len(wakes),
        'false_wakes':{k:sum(r.get('false_wakes',0) for r in rows if r.get('kind')==k)
                       for k in ('single','typing','music_only')},
        'false_wake_exposure':{k:{'trials':sum(r.get('kind')==k for r in rows),
            'seconds':sum(r.get('seconds',0) for r in rows if r.get('kind')==k)}
            for k in ('single','typing','music_only')},
        'game':saved.get('game') or saved.get('game_evidence')}


def load_round(root=ROOT):
    root=Path(root);state=root/'state/music_api_wizard.json'
    if not state.exists():state=root/'state/music_wizard.json'
    if not state.exists():return None
    run_id=json.loads(state.read_text(encoding='utf8'))['run_id'];folder=root/'runs'/run_id
    final=folder/'result.json';checkpoint=folder/'checkpoint.json'
    path=final if final.exists() else checkpoint
    if not path.exists():return None
    saved=json.loads(path.read_text(encoding='utf8'))
    if saved.get('schema') not in ('online_priority_v1','api_focus_v1') and not any(t.get('kind')=='online' for t in saved.get('tasks',[])):return None
    result=summarize(saved,run_id,complete=path==final)
    result['evidence']={'path':path.relative_to(root).as_posix(),'sha256':sha256(path)}
    return result


def online_rows(round):
    output=[]
    for row in round['results']:
        if row.get('kind')!='online':continue
        result=row.get('result',{});job=row.get('job',{});meta=job.get('metadata',{})
        before=result.get('before') or {};after=result.get('after') or {}
        start=(job.get('clock') or {}).get('start_host_estimate_ns')
        end=result.get('match_finished_monotonic_ns')
        duration=(end-start)/1e9 if start is not None and end is not None else None
        operator_s=None
        if row.get('started_at') and row.get('finished_at'):
            operator_s=(dt.datetime.fromisoformat(row['finished_at'])-dt.datetime.fromisoformat(row['started_at'])).total_seconds()
        output.append({'trial':row['trial'],'expected_title':row.get('title',''),'expected_artist':row.get('artist',''),
            'source':result.get('source','none'),'recognized_title':result.get('title','未匹配'),
            'online_reason':result.get('online_attempt',result).get('reason'),
            'online_correct':bool(row.get('online_correct') and result.get('source')=='audiotag'),
            'outside_library':bool(row.get('outside_library')),'wake_success':bool(row.get('wake_success')),
            'recording_s':meta.get('duration_s'),'export_s':meta.get('export_s'),
            'record_to_result_s':duration,'operator_trial_s':operator_s,
            'free_seconds_before':before.get('identification_free_sec_remainder'),
            'free_seconds_after':after.get('identification_free_sec_remainder'),
            'cost_yuan':result.get('cost_yuan'),'zero_cost_verified':bool(result.get('zero_cost_verified')),
            'paid_balance_before':before.get('current_credit_balance'),'paid_balance_after':after.get('current_credit_balance'),
            'credits_spent_before':before.get('credits_spent'),'credits_spent_after':after.get('credits_spent'),
            'wav_sha256':meta.get('wav_sha256'),'job_id':job.get('id')})
    return output
