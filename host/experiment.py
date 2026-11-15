"""Trial definitions and frozen configuration, independent of board detection."""
import json,math,random
from pathlib import Path
import numpy as np
from features import independent_features
from reference import Pairing

SEEDS={'development':20261113,'holdout':20261114}

def order(session):
    labels=['tap']*5+['sound']*5+['quiet']*5
    random.Random(SEEDS[session]).shuffle(labels)
    return labels

def scored(rows):
    return [r for r in rows if 50000000 < r['tick']-10004 <= 150000000]

def decisions(rows,audio_threshold,accel_threshold,window_ms):
    p=Pairing(audio_threshold,accel_threshold,window_ms*100000)
    result=[]
    for row in rows:
        trigger=p.step(row['tick'],row['audio'],row['accel'])
        if 50000000 < row['tick']-10004 <= 150000000:
            result.append({**row,**trigger})
    return result

def metrics(trials,thresholds,window_ms):
    result={}
    for mode in ('audio','accel','joint'):
        counts={'TP':0,'FP':0,'TN':0,'FN':0,'extra_triggers':0,'sound_false_trials':0,'quiet_false_trials':0}
        details=[]
        for trial,rows in trials:
            ds=decisions(rows,thresholds['audio'],thresholds['accel'],window_ms)
            hits=[r for r in ds if (r[mode+'_cross'] if mode!='joint' else r['joint'] and not r['joint']['dedup'])]
            positive=trial['label']=='tap';detected=bool(hits)
            outcome=('TP' if detected else 'FN') if positive else ('FP' if detected else 'TN')
            counts[outcome]+=1;counts['extra_triggers']+=max(0,len(hits)-1)
            if detected and not positive:counts[trial['label']+'_false_trials']+=1
            details.append({'trial_id':trial['trial_id'],'label':trial['label'],'outcome':outcome,
                            'count':len(hits),'ticks':[r['tick'] for r in hits]})
        tp,fp,fn=(counts[k] for k in ('TP','FP','FN'))
        counts.update(Precision=tp/(tp+fp) if tp+fp else None,Recall=tp/(tp+fn) if tp+fn else None,
                      F1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None,
                      precision_denominator=tp+fp,recall_denominator=tp+fn,f1_denominator=2*tp+fp+fn)
        result[mode]={'metrics':counts,'trials':details}
    return result

def freeze(calibration,trials):
    bg={key:np.array([r[key] for r in calibration if r[key] is not None]) for key in ('audio','accel')}
    thresholds={};statistics={}
    for key in ('audio','accel'):
        quiet=[r[key] for trial,rows in trials if trial['label']=='quiet' for r in scored(rows) if r[key] is not None]
        if not len(bg[key]) or not quiet:raise ValueError('No valid quiet calibration/development features')
        floor=max(1,math.ceil(float(np.percentile(quiet,99))))
        median=float(np.median(bg[key]));mad=float(np.median(np.abs(bg[key]-median)))
        thresholds[key]=math.ceil(max(median+6*mad,floor))
        statistics[key]={'median':median,'MAD':mad,'development_quiet_p99_ceiling':floor,
                         'calibration_valid_windows':len(bg[key]),'development_quiet_valid_windows':len(quiet)}
    default=metrics(trials,thresholds,50)
    problem=default['joint']['metrics']['FP'] or default['joint']['metrics']['FN']
    candidates={str(w):metrics(trials,thresholds,w) for w in ((20,50,80) if problem else (50,))}
    window=min(map(int,candidates),key=lambda w:(-(candidates[str(w)]['joint']['metrics']['F1'] or 0),w!=50,abs(w-50),w))
    return {'threshold_id':1,'thresholds':thresholds,'window_ms':window,'statistics':statistics,
            'selection_rule':'F1 descending; tie 50 ms, then distance to 50 ms, then smaller',
            'comparison_triggered_by_development_errors':bool(problem),'development_comparison':candidates,
            'initialization':'REPLAY fresh DC_Q8=0, no previous XYZ, phase 0, candidates empty; 0.5 s raw pre-roll',
            'score_window':'50,000,000 < feature_tick - 10,002 <= 150,000,000; 100 full 10 ms windows',
            'seeds':SEEDS}
