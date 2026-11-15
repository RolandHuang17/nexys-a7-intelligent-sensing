"""Select gates using development evidence only; holdout files are not read."""
import itertools,json,statistics
from audit import ROOT,Run,write_json,sha256
from music_store import MusicStore
from music_library import decide,LocalMatcher

def main(data_path=None):
    r=Run('music_profile_selection')
    state=json.loads((ROOT/'state/music_development.json').read_text(encoding='utf8')) if data_path is None else {'run_id':__import__('pathlib').Path(data_path).parent.name}
    source=ROOT/'runs'/state['run_id']/'result.json' if data_path is None else __import__('pathlib').Path(data_path)
    data=json.loads(source.read_text(encoding='utf8'));trials=data['trials']
    assert len([t for t in trials if t['track']['expected']])>=5
    assert len([t for t in trials if not t['track']['expected']])>=4
    choices=[];matcher=LocalMatcher();density_evidence={}
    for t in trials:
        wav=__import__('pathlib').Path(t['metadata']['wav']);prefix=__import__('pathlib').Path(t['prefix_wav']) if t.get('prefix_wav') else wav.parent.parent/'first8.wav'
        for density in (10,20,40,80):
            for seconds,path in ((8,prefix),(10,wav)):
                density_evidence[(t['trial'],density,seconds)]=matcher.evidence(path,density)
    write_json(r.path/'density_evidence.json',[{'trial':i,'query_density':d,'seconds':s,'evidence':v} for (i,d,s),v in density_evidence.items()])
    for seconds in (8,10):
        for hashes,span,ratio,density in itertools.product((8,12,16,24,32),(1.,1.5,2.),(1.5,2.,3.),(10,20,40,80)):
            profile={'min_hashes':hashes,'min_span_s':span,'min_ratio':ratio,'seconds':seconds,'query_density':density}
            tp=fp=0;scored=[]
            for t in trials:
                result=decide(density_evidence[(t['trial'],density,seconds)],profile);expected=t['track'];correct=result.get('title')==expected.get('title') and result.get('artist')==expected.get('artist')
                tp+=int(expected['expected'] and result['matched'] and correct)
                fp+=int(result['matched'] and (not expected['expected'] or not correct))
                scored.append({'trial':t['trial'],'expected':expected['title'],'matched':result['matched'],'reported':result.get('title'),'correct':correct})
            choices.append({'profile':profile,'tp':tp,'fp':fp,'scored':scored})
    winners={s:min([c for c in choices if c['profile']['seconds']==s],key=lambda c:(c['fp'],-c['tp'],-c['profile']['min_hashes'],-c['profile']['min_span_s'],-c['profile']['min_ratio'])) for s in (8,10)}
    n=sum(t['track']['expected'] for t in trials)
    # Ties retain 10 s for more musical context and the service's 10--30 s advice.
    choose8=winners[8]['fp']==0 and winners[8]['tp']/n>=.8 and winners[8]['tp']>winners[10]['tp']
    selected=winners[8 if choose8 else 10]
    accepted=selected['fp']==0 and selected['tp']/n>=.8
    profile={**selected['profile'],'status':'frozen_before_holdout' if accepted else 'development_needs_improvement',
        'development_run_id':state['run_id'],'selection_run_id':r.run_id,'source_sha256':sha256(source),'holdout_used':False}
    benchmark=trials
    if not any(t['transfer8_s'] is not None for t in benchmark):
        try:
            bs=json.loads((ROOT/'state/MUSIC3_recording/status.json').read_text(encoding='utf8'))
            benchmark=json.loads((ROOT/'runs'/bs['run_id']/'result.json').read_text(encoding='utf8'))['trials']
        except (OSError,ValueError,KeyError):pass
    summary={'profile':profile,'accepted':accepted,'winners':winners,'grid':choices,'duration_tie_rule':'同分保留10秒，提供更多上下文且符合官方10至30秒建议',
        'same_input_prefix8_vs_full10':True,'resource_note':'8秒与10秒运行在同一160000点固件时，分配BRAM相同；另有128000点独立构建用于容量比较',
        'transfer8_mean_s':statistics.mean(t['transfer8_s'] for t in benchmark if t['transfer8_s'] is not None) if any(t['transfer8_s'] is not None for t in benchmark) else None,'transfer10_mean_s':statistics.mean(t['metadata']['export_s'] for t in benchmark)}
    write_json(r.path/'result.json',summary)
    if accepted:
        MusicStore().set_setting('match_profile',profile)
        from app_paths import PORTABLE
        if not PORTABLE:write_json(ROOT/'release_assets/music/default_match_profile.json',profile)
    r.status('MUSIC3_profile','passed' if accepted else 'failed','开发集已冻结参数' if accepted else '开发集命中不足，保留数据并诊断后重采',
        [str((r.path/'result.json').relative_to(ROOT))],'进入正式手机试次' if accepted else '改善信噪比或前处理；不得用留出集调参')
    print(json.dumps({k:summary[k] for k in ('profile','accepted','transfer8_mean_s','transfer10_mean_s')},ensure_ascii=False))
    return {'profile':profile,'accepted':accepted,'selection_run_id':r.run_id,'positive_correct':selected['tp'],'negative_false_matches':selected['fp']}
if __name__=='__main__':main()
