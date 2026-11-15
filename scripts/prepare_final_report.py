"""Prepare the final course report from existing, immutable acceptance evidence.

This does not connect to hardware, send music, or rebuild the accepted executable.
Run with the project's .venv Python. The resulting report/final folder is portable.
"""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import csv
import hashlib
import json
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'report/final'
REPO = 'https://github.com/RolandHuang17/nexys-a7-intelligent-sensing'
TAG = 'v1.6.0'


def read(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def tex(value):
    return str(value).replace('&', r'\&').replace('_', r'\_').replace('%', r'\%').replace('#', r'\#')


def prepare():
    (OUT / 'figures').mkdir(parents=True, exist_ok=True)
    (OUT / 'data').mkdir(exist_ok=True)
    build = read('state/portable_build.json')
    assert build['app_version'] == '1.6.0'
    assert digest(ROOT/'deliver/软件/开发板实时监测.exe') == build['exe_sha256']
    source = read('deliver/软件/体感游戏更新源码/source_manifest.json')
    assert all(digest(ROOT/'host'/r['path']) == r['sha256'] for r in source)
    assert digest(ROOT/'release_assets/firmware/recorder_top.bit') == build['firmware']['bitstream_sha256']
    shutil.copy2(ROOT/'report/WHUBachelor.cls', OUT/'WHUBachelor.cls')
    shutil.copy2(ROOT/'report/figures/whulogo.pdf', OUT/'figures/whulogo.pdf')
    candidates = {
        'board.jpg': Path('C:/Users/roland/AppData/Local/Temp/codex-clipboard-21e282f7-ef8b-467f-8b43-5e485d76802c.jpg'),
        'game.png': ROOT/'deliver/体感游戏集成验收/界面预览/主程序游戏星图.png',
        'calibration.png': ROOT/'deliver/体感游戏集成验收/界面预览/主程序实板校准.png',
        'monitor.png': ROOT/'deliver/板载面板验收/screenshots/08_simple_monitor_light.png',
        'music.png': ROOT/'deliver/板载面板验收/screenshots/04_music_dark.png',
    }
    if not candidates['board.jpg'].exists():
        candidates['board.jpg'] = ROOT/'report/figures/board_original.jpg'
    image_sources=[]
    for name, path in candidates.items():
        assert path.exists(), path
        shutil.copy2(path, OUT/'figures'/name)
        image_sources.append({'file':'figures/'+name, 'source':str(path), 'sha256':digest(path)})
    evidence = {
        'game_integration': 'deliver/体感游戏集成验收/验收记录.json',
        'game_physical': 'deliver/独立小游戏/验收与测试/真人实板试玩/result.json',
        'shazam_replay': 'state/shazam_main_verification.json',
        'trigger_comparison': 'runs/20261113T233134_202541_evaluate/results.json',
        'monitor_measurements': 'report/generated/monitor_measured_values.json',
        'sample_intervals': 'report/generated/xyz_interval_statistics.json',
        'fir_design': 'config/music_decimator.json',
        'triple_abort': 'deliver/三敲与中止/三敲中止运行验证.json',
    }
    values={k:read(v) for k,v in evidence.items()}
    summary={
        'app_version':build['app_version'], 'exe_sha256':build['exe_sha256'],
        'exe_bytes':build['exe_bytes'], 'firmware':build['firmware'],
        'host_files_verified':len(source), 'repository':REPO,'tag':TAG,
        'shazam_replay':[{ 'title':r['title'], 'correct':r['correct_online'],
            'seconds':r['result']['elapsed_s'], 'wav_sha256':r['wav_sha256'] }
            for r in values['shazam_replay']['rows']],
        'holdout':{k:v['metrics'] for k,v in values['trigger_comparison']['holdout'].items()},
        'holdout_config':values['trigger_comparison']['config'],
        'reference_windows':values['trigger_comparison']['board_reference_windows'],
        'monitor_ranges':values['monitor_measurements']['sensor_ranges'],
        'game_campaign':values['game_physical']['first_campaign'],
        'game_performance':values['game_integration']['real_board_integration']['performance_with_live_board'],
        'evidence_sources':[{ 'id':k,'path':v,'sha256':digest(ROOT/v)} for k,v in evidence.items()],
        'images':image_sources,
    }
    # Preserve quantitative inputs with relative names; never copy personal databases or keys.
    write_json(OUT/'data/measured.json', summary)
    for name in ('trigger_comparison','fir_design','sample_intervals'):
        shutil.copy2(ROOT/evidence[name],OUT/'data'/(name+'.json'))
    impl=ROOT/'runs'/build['firmware']['build_run_id']/'implementation'
    for name in ('timing_summary.rpt','utilization_routed.rpt','check_timing.rpt','drc.rpt'):
        shutil.copy2(impl/name,OUT/'data'/name)
    rows=['% Generated only from recorded acceptance data.']
    rows.append(r'\newcommand{\ExeHash}{'+build['exe_sha256']+'}')
    rows.append(r'\newcommand{\BitHash}{'+build['firmware']['bitstream_sha256']+'}')
    rows.append(r'\newcommand{\BuildID}{'+build['firmware']['build_id']+'}')
    rows.append(r'\newcommand{\RepoURL}{'+REPO+'}')
    rows.append(r'\newcommand{\ReleaseURL}{'+REPO+'/releases/tag/'+TAG+'}')
    rows.append(r'\newcommand{\ExeURL}{'+REPO+'/releases/download/'+TAG+'/NexysMonitor-v1.6.0-win-x64.exe}')
    (OUT/'data/values.tex').write_text('\n'.join(rows)+'\n',encoding='utf-8')
    for filename, header, records in (
        ('shazam.csv',['song','seconds'],[(i+1,r['seconds']) for i,r in enumerate(summary['shazam_replay'])]),
        ('levels.csv',['level','seconds','stars'],[(r['level'],r['t'],r['stars']) for r in summary['game_campaign']]),
        ('resource.csv',['name','percent'],[('LUT',15118/63400*100),('FF',25096/126800*100),('BRAM',119.5/135*100),('DSP',9/240*100)]),
    ):
        with (OUT/'data'/filename).open('w',encoding='utf-8',newline='') as f:
            w=csv.writer(f);w.writerow(header);w.writerows(records)
    table=[]
    for r in summary['shazam_replay']:
        table.append(f"{tex(r['title'])} & Shazam & 正确 & {r['seconds']:.3f} "+r'\\')
    generated = [r'\newcommand{\ShazamRows}{'+'\n'+'\n'.join(table)+'\n}']
    (OUT/'data/shazam_rows.tex').write_text('\n'.join(table)+'\n',encoding='utf-8')
    table=[]
    for k,label in [('audio','声音单路'),('accel','振动单路'),('joint','声振联合')]:
        r=summary['holdout'][k]
        table.append(f"{label} & {r['TP']} & {r['FP']} & {r['FN']} & {r['Recall']*100:.0f}\\% & {r['F1']:.3f} "+r'\\')
    generated.append(r'\newcommand{\HoldoutRows}{'+'\n'+'\n'.join(table)+'\n}')
    (OUT/'data/holdout_rows.tex').write_text('\n'.join(table)+'\n',encoding='utf-8')
    table=[]
    for r in summary['game_campaign']:
        table.append(f"{r['level']} & {r['t']:.2f} & {r['stars']} & {r['deaths']} & 已通关 "+r'\\')
    generated.append(r'\newcommand{\LevelRows}{'+'\n'+'\n'.join(table)+'\n}')
    (OUT/'data/level_rows.tex').write_text('\n'.join(table)+'\n',encoding='utf-8')
    (OUT/'data/tables.tex').write_text('\n'.join(generated)+'\n',encoding='utf-8')
    # One complete, original final-version sound/vibration event, only decimated for plotting.
    event=ROOT/'deliver/体感游戏集成验收/真实完整事件'
    payloads=list(event.rglob('payload.bin'))
    if not payloads:
        event=ROOT/'runs/game_integration_live/runtime/runs/20261115T220147_953836_monitor_session/physical/e1_event2'
        payloads=[event/'payload.bin']
    import struct
    payload=payloads[0]
    audio=struct.unpack('<24000h',payload.read_bytes()[:48000])
    with (OUT/'data/event_audio.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f);w.writerow(['t','min','max'])
        for i in range(0,len(audio),80):
            w.writerow([f'{i/16000-.5:.4f}',min(audio[i:i+80]),max(audio[i:i+80])])
    meta=read(str((payload.parent/'metadata.json').relative_to(ROOT)))
    write_json(OUT/'data/event_source.json',{'payload_sha256':digest(payload),'pcm_count':24000,'metadata':meta,
        'plot_reduction':'80-sample min/max envelope; original payload retained in evidence package'})
    print(json.dumps({'prepared':str(OUT),'host_files_verified':len(source),'exe_hash_verified':True},ensure_ascii=False))


if __name__=='__main__':
    prepare()
