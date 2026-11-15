"""Promote the exact verified 1.6 candidate, preserving 1.5 and the standalone game."""
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf8'))
def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')


def main():
    candidate=read(ROOT/'state/shazam_main_candidate.json')
    frozen=read(ROOT/'state/game_frozen_check.json')
    live=read(ROOT/'runs/game_integration_live/result.json')
    ui=read(ROOT/'runs/game_embedding_ui/result.json')
    state=read(ROOT/'state/game_integration.json')
    baseline=Path(state['baseline'])
    previous=read(baseline/'baseline.json')
    exe=Path(candidate['candidate_exe'])
    assert candidate['app_version']=='1.6.0' and frozen['passed'] and live['passed'] and ui['passed']
    assert sha(exe)==candidate['exe_sha256']==frozen['candidate_exe_sha256']
    assert candidate['firmware']==previous['formal_version']['firmware']
    assert candidate['panel_protocol_version']==1
    assert 'Ran 100 tests' in (ROOT/'runs/game_integration_tests.txt').read_text(encoding='utf8')
    import psutil
    formal=ROOT/'deliver/软件/开发板实时监测.exe'
    for process in psutil.process_iter(['exe']):
        try:
            if process.info['exe'] and Path(process.info['exe']).resolve()==formal.resolve():
                raise RuntimeError('正式窗口仍在运行，请先正常关闭后发布。')
        except (psutil.AccessDenied,psutil.NoSuchProcess):pass
    assert sha(formal)==previous['formal_version']['exe_sha256'],'Formal app changed during implementation'
    allowed={'host/monitor_gui.py','host/monitor_service.py','host/ui/dashboard.py','host/app_paths.py','host/build_shazam_main.py'}
    for row in previous['files']:
        if row['path'].startswith('deliver/') or row['path'] in allowed:continue
        assert sha(ROOT/row['path'])==row['sha256'],row['path']
    build_source=Path(candidate['build_source_directory'])
    runtime=['monitor_gui.py','monitor_service.py','app_paths.py','game_session.py','ui/dashboard.py',
             *[p.relative_to(ROOT/'host').as_posix() for p in (ROOT/'host/tilt_game').glob('*.py')]]
    for relative in runtime:
        assert sha(ROOT/'host'/relative)==sha(build_source/'host'/relative),relative
    standalone=ROOT/'deliver/独立小游戏/重力迷航.exe'
    standalone_hash=sha(standalone)
    evidence=ROOT/'deliver/体感游戏集成验收'
    evidence.mkdir(parents=True,exist_ok=True)
    frozen_ui=read(ROOT/'state/game_frozen_ui.json')
    assert frozen_ui['passed'] and frozen_ui['exe_sha256']==candidate['exe_sha256']
    for source,name in (
            (ROOT/'runs/game_integration_tests.txt','自动测试100项.txt'),
            (ROOT/'runs/game_integration_live/result.json','实板流程.json'),
            (ROOT/'runs/game_embedding_ui/result.json','页面切换与布局.json'),
            (Path(frozen['directory'])/'result.json','EXE资源与隔离自检.json'),
            (ROOT/'state/game_frozen_ui.json','EXE界面复核.json')):
        shutil.copy2(source,evidence/name)
    event=Path(live['full_event']['directory'])
    shutil.copytree(event,evidence/'真实完整事件',dirs_exist_ok=True)
    shutil.copy2(ROOT/'release_assets/release_manifest.json',evidence/'原资源清单.json')
    human=ROOT/'deliver/独立小游戏/验收与测试/真人实板试玩/result.json'
    shutil.copy2(human,evidence/'原独立版八关真人实板验收.json')
    source_output=ROOT/'deliver/软件/体感游戏更新源码'
    shutil.copytree(build_source,source_output,dirs_exist_ok=True)
    shutil.copy2(candidate['requirements_lock'],source_output/'requirements-locked.txt')
    qa=evidence/'验证脚本';qa.mkdir(exist_ok=True)
    for name in ('test_game_session.py','test_game_integration_contracts.py','verify_game_embedding.py',
                 'verify_game_integration_live.py','verify_game_frozen.py','publish_game_integration.py'):
        shutil.copy2(ROOT/'host'/name,qa/name)
    candidate.update(game_integration=True,game_version='0.1.0',panel_protocol_version=1,
                     game_acceptance_directory='deliver/体感游戏集成验收',
                     standalone_game_preserved_sha256=standalone_hash)
    from build_shazam_main import promote
    promoted=promote(candidate)
    backup=Path(promoted['previous_version_directory'])
    shutil.copytree(baseline/'source/host',backup/'游戏接入前源码/host',dirs_exist_ok=True)
    old_usage=(baseline/'formal/使用说明.md').read_text(encoding='utf-8-sig')
    addition=('\n\n# 1.6.0：体感游戏\n\n'
              '左侧新增“体感游戏”，内含已完成真人实板验收的八关《重力迷航》。'
              '游戏共用上方已连接的开发板，不另开串口。开始实板游戏前，关闭 SW15 并退出听歌识曲；'
              '进入后暂停自动事件记录，离开游戏页或退出软件时恢复原开关和参数。\n\n'
              '自然握稳后按向导完成校准，轻倾移动，按住五向按键正中的 BTNC 刹车。'
              '也可选择键盘练习，方向键移动、空格刹车。离开页面或窗口失焦时暂停，返回后手动继续。\n\n'
              '第一次打开会复制已有独立版通关进度；两边后续分别保存。独立版 EXE 及其历史验收包保留原样。'
              '当前主程序继续使用 1.5.0 的 ec0351f8 固件，合并没有重新烧写开发板。\n\n'
              '代码与验证见“体感游戏更新源码”和上一级“体感游戏集成验收”。旧 1.5.0 EXE 与源码已备份到历史版本。\n')
    (ROOT/'deliver/软件/使用说明.md').write_text(old_usage+addition,encoding='utf8')
    result={'status':'passed','app_version':'1.6.0','exe_sha256':sha(formal),
            'previous_version':'1.5.0','previous_version_backup':str(backup),
            'firmware_unchanged':True,'firmware':candidate['firmware'],'automatic_tests':100,
            'source_ui':ui,'real_board_integration':live,'frozen':frozen,'frozen_ui':frozen_ui,
            'standalone_preserved':sha(standalone)==standalone_hash,'standalone_exe_sha256':standalone_hash,
            'original_game_mechanics_changed':False,'physical_eight_level_acceptance_source':str(human),
            'latest_user_instruction':'现在合并吧',
            'time':datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')}
    assert result['standalone_preserved']
    write(evidence/'验收记录.json',result)
    index=read(ROOT/'deliver/交付索引.json')
    index['active_software']={**index.get('active_software',{}),'file':'软件/开发板实时监测.exe',
        'app_version':'1.6.0','exe_sha256':result['exe_sha256'],'firmware_unchanged':True,
        'verification':'体感游戏集成验收','game_integration':True,'notes':'软件/使用说明.md',
        'previous_version_directory':str(backup)}
    index['game_integration']={k:result[k] for k in ('app_version','exe_sha256','firmware_unchanged','automatic_tests','standalone_preserved','time')}
    write(ROOT/'deliver/交付索引.json',index)
    state.update(status='complete',result='deliver/体感游戏集成验收/验收记录.json',exe_sha256=result['exe_sha256'])
    write(ROOT/'state/game_integration.json',state)
    write(ROOT/'state/tilt_game_handover.json',{'status':'integrated_into_main','latest_user_instruction':'现在合并吧',
        'main_app_version':'1.6.0','main_exe':'deliver/软件/开发板实时监测.exe','main_exe_sha256':result['exe_sha256'],
        'standalone_game_preserved':True,'acceptance':'deliver/体感游戏集成验收/验收记录.json','time':result['time']})
    files=[{'path':p.relative_to(evidence).as_posix(),'sha256':sha(p),'bytes':p.stat().st_size}
           for p in sorted(evidence.rglob('*')) if p.is_file() and p.name!='SHA256清单.json']
    write(evidence/'SHA256清单.json',files)
    print(json.dumps({k:result[k] for k in ('status','app_version','exe_sha256','previous_version_backup','standalone_preserved')},ensure_ascii=False))


if __name__=='__main__':main()
