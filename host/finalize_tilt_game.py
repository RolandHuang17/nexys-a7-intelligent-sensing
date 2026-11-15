"""Collect independent deliverables and prove the existing main release unchanged."""
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy_file(source,target):
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(source,target)


def main():
    output=ROOT/'deliver/独立小游戏'
    evidence=output/'验收与测试'
    evidence.mkdir(parents=True,exist_ok=True)
    baseline_dir=ROOT/'runs/20261115T174523_tilt_game_baseline'
    baseline=json.loads((baseline_dir/'baseline.json').read_text(encoding='utf8'))
    changed=[row['path'] for row in baseline['files'] if not (ROOT/row['path']).exists() or digest(ROOT/row['path'])!=row['sha256']]
    assert not changed,'Existing main software changed: '+repr(changed)
    protection={'passed':True,'baseline_directory':str(baseline_dir),'protected_file_count':len(baseline['files']),
                'changed_files':changed,'main_app_version':'1.3.0',
                'main_exe_sha256':digest(ROOT/'deliver/软件/开发板实时监测.exe'),
                'firmware_sha256':digest(ROOT/'release_assets/firmware/recorder_top.bit')}
    (evidence/'主程序与固件保持原样.json').write_text(json.dumps(protection,ensure_ascii=False,indent=2),encoding='utf8')
    copy_file(ROOT/'runs/tilt_game_unit_tests.txt',evidence/'行为测试23项.txt')
    for folder,label in (('tilt_game_campaign_validation','八关数字输入复验'),('tilt_game_ui_validation','界面与性能'),
                         ('tilt_game_physical_connection','真实开发板连接')):
        src=ROOT/'runs'/folder
        target=evidence/label
        target.mkdir(parents=True,exist_ok=True)
        for path in src.glob('*.json'):
            copy_file(path,target/path.name)
    physical=json.loads((ROOT/'runs/tilt_game_physical_connection/result.json').read_text(encoding='utf8'))
    physical_run=Path(physical['run_directory'])
    for name in ('uart_rx.bin','uart_tx.bin','monitor.jsonl','actions.jsonl','session_summary.json','run.json'):
        copy_file(physical_run/name,evidence/'真实开发板连接/原始记录'/name)
    source=output/'源码'
    host=source/'host'
    shared=('app_paths.py','audit.py','capture.py','device_discovery.py','hardware.py','monitor_protocol.py',
            'monitor_service.py','music_board.py','music_protocol.py','music_store.py','portable_program.py',
            'program.py','protocol.py')
    for path in [*(ROOT/'host').glob('*tilt_game*.py'),*(ROOT/'host/tilt_game').glob('*.py')]:
        copy_file(path,source/path.relative_to(ROOT))
    for name in shared:
        copy_file(ROOT/'host'/name,host/name)
    # Small immutable firmware/programmer resources are sufficient for this app.
    assets=ROOT/'.portable_build/tilt_game_assets/release_assets'
    for path in assets.rglob('*'):
        if path.is_file():
            copy_file(path,source/'release_assets'/path.relative_to(assets))
    copy_file(ROOT/'docs/重力迷航开发与接入说明.md',output/'开发与接入说明.md')
    (source/'requirements-game.txt').write_text('numpy==1.26.4\nPillow==12.0.0\npyserial==3.5\nPyInstaller==6.22.3\n',encoding='utf8')
    (source/'README.md').write_text('源码运行：安装 Python 3.12 x64 和 requirements-game.txt，运行 python host/tilt_game_main.py。\n键盘练习加 --keyboard。正式运行直接双击上一级重力迷航.exe，无需 Python。\n共享串口模块为原程序的未修改副本。测试报告与数字回放输入在上一级验收与测试目录。\n重新打包可运行 python -m PyInstaller --onefile --windowed --paths host --add-data "release_assets;release_assets" --name 重力迷航 host/tilt_game_main.py。\n不执行主程序集成或晋升脚本。\n',encoding='utf8')
    campaign=json.loads((ROOT/'runs/tilt_game_campaign_validation/summary.json').read_text(encoding='utf8'))
    ui=json.loads((ROOT/'runs/tilt_game_ui_validation/result.json').read_text(encoding='utf8'))
    package=json.loads((output/'版本与校验.json').read_text(encoding='utf8'))
    human_path=evidence/'真人实板试玩/result.json'
    human=json.loads(human_path.read_text(encoding='utf8')) if human_path.exists() else None
    human_matches=bool(human and human.get('exe_sha256')==digest(output/'重力迷航.exe'))
    decision_path=ROOT/'state/tilt_game_handover.json'
    decision=json.loads(decision_path.read_text(encoding='utf8')) if decision_path.exists() else {}
    deferred=decision.get('status')=='standalone_accepted_integration_deferred_by_user'
    integration='deferred_by_user_keep_standalone' if deferred else 'not_started_waiting_for_user_playtest_approval'
    package['physical_acceptance']='passed_on_this_board' if human_matches else 'pending'
    package['user_playtest_approval']='approved' if human_matches else 'pending'
    package['integration']=integration
    (output/'版本与校验.json').write_text(json.dumps(package,ensure_ascii=False,indent=2),encoding='utf8')
    check=ROOT/'runs/tilt_game_packaged_check/self_check.json'
    packaged=json.loads(check.read_text(encoding='utf8')) if check.exists() else None
    if packaged:
        copy_file(check,evidence/'打包EXE自检.json')
    record={'time':datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds'),
            'game_version':package['game_version'],'exe_sha256':digest(output/'重力迷航.exe'),
            'independent_release':True,'unit_tests_passed':23,'campaign':campaign,
            'ui':ui,'real_board_connection':physical,'main_unchanged':protection,
            'packaged_self_check':packaged,'user_playtest_approval':'approved' if human_matches else 'pending',
            'physical_four_direction_calibration':'passed' if human_matches and human['four_directions_passed'] else 'pending',
            'physical_center_brake':'passed' if human_matches and human['physical_center_brake_passed'] else 'pending',
            'physical_eight_level_playthrough':'passed' if human_matches and human['physical_eight_level_playthrough_passed'] else 'pending',
            'human_playtest':human if human_matches else None,'integration':integration,
            'latest_user_instruction':decision.get('latest_user_instruction')}
    (output/'验收记录.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
    rows=[{'path':p.relative_to(output).as_posix(),'sha256':digest(p),'bytes':p.stat().st_size}
          for p in sorted(output.rglob('*')) if p.is_file() and p.name!='SHA256清单.json']
    (output/'SHA256清单.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'directory':str(output),'files':len(rows),'main_files_unchanged':len(baseline['files']),
                      'exe_sha256':record['exe_sha256'],'user_playtest_approval':record['user_playtest_approval'],
                      'integration':integration},ensure_ascii=False))


if __name__=='__main__':
    main()
