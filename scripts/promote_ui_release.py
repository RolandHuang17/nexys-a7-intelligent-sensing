"""Guarded UI 1.3.0 promotion. Default is read-only; --execute applies it.

No build, firmware programming, GUI control, database migration or Git operation
is performed here. All acceptance reports must already exist and pass.
"""
import argparse
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid
import zipfile
import zlib


OLD_HASH='447b8c154e9d726a3540d8a3a15024efc528a4e34ab666890486a0f0b25d01a0'
PDF_HASH='a6df26b2fdab4db7a1778910468c26c84df32c009a13e7807ccc0e4895033494'
SOURCE_FILES=[
    'host/monitor_gui.py','host/music_gui.py','host/app_paths.py','host/build_shazam_main.py',
    'requirements-runtime.txt','scripts/build_portable.ps1','monitor.ps1',
]
QA_FILES=[
    'host/test_ui_contracts.py','host/ui_smoke.py','host/ui_benchmark.py',
    'scripts/ui_review_scene.py','scripts/verify_ui_frozen.py','scripts/verify_ui_live_flow.py',
    'scripts/verify_ui_online_replay.py','scripts/promote_ui_release.py',
]
GATES={
    'frozen':'docs/UI冻结验证.json','online':'docs/UI在线回放验证.json',
    'live':'docs/UI实板流程验证.json','performance':'runs/ui_ab_02/comparison.json',
    'screenshots':'docs/UI截图审查.json',
}


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf8'))
def encoded(value):return json.dumps(value,ensure_ascii=False,indent=2).encode('utf8')
def within(path,root):
    path=Path(path).resolve();root=Path(root).resolve()
    if not path.is_relative_to(root):raise ValueError('Path outside intended root: '+str(path))
    return path


def prepare(root,original):
    root=root.resolve();original=original.resolve()
    if root==original:raise ValueError('UI checkout and original project must differ')
    candidate=read(root/'state/shazam_main_candidate.json');checksum=candidate['exe_sha256']
    exe=within(candidate['candidate_exe'],root/'.portable_build')
    assert candidate['app_version']=='1.3.0' and sha(exe)==checksum
    gates={name:read(root/path) for name,path in GATES.items()}
    for name,gate in gates.items():
        assert gate.get('passed') is True or gate.get('status')=='passed','Gate failed: '+name
        if 'checks' in gate:assert all(v is True for v in gate['checks'].values()),name
        if name in ('frozen','online','screenshots'):
            assert gate['exe_sha256']==checksum,'Gate EXE mismatch: '+name
        elif name=='live':assert gate['exe_sha256']==checksum,name
        elif 'exe_sha256' in gate:assert gate['exe_sha256']==checksum,name
    assert gates['online']['correct']==3 and gates['online']['total']==3
    assert gates['frozen']['all_original_resource_bytes_verified_in_EXE'] is True
    assert sha(exe)==read(root/'runs/ui_ab_02/B_candidate/launch.json')['exe_sha256']
    screenshot_rows=gates['screenshots'].get('screenshots',[])
    assert isinstance(screenshot_rows,list) and len(screenshot_rows)>=6,'Reviewed screenshots missing'
    package=root/'deliver/UI重构验收'
    for row in screenshot_rows:
        name=row if isinstance(row,str) else row.get('path',row.get('file'))
        assert name,'Screenshot entry requires path/file'
        image=Path(name)
        if not image.is_absolute():
            options=[package/image,root/image]
            image=next((p for p in options if p.is_file()),options[0])
        image=within(image,package);assert image.is_file()
        if isinstance(row,dict) and 'sha256' in row:assert sha(image)==row['sha256']
    baseline={name.replace('\\','/'):value for name,value in read(root/'state/ui_baseline_hashes.json').items()}
    # Root-level launcher/dependency/build scripts were not in the initial
    # host/rtl/resource hash list; their original Git archive binds them too.
    with zipfile.ZipFile(root/'state/ui_baseline_1.2.zip') as saved:
        for name in SOURCE_FILES:
            if name in baseline:continue  # Raw pre-migration hashes are authoritative.
            archived=saved.read(name);actual=(original/name).read_bytes()
            # Git archives can normalize CRLF. Check content against that saved
            # baseline, then preserve the exact original bytes for rollback.
            assert archived.replace(b'\r\n',b'\n')==actual.replace(b'\r\n',b'\n'),'Original content changed: '+name
            baseline[name]=hashlib.sha256(actual).hexdigest()
    mismatches=[name for name,expected in baseline.items()
        if not (original/name).is_file() or sha(original/name)!=expected]
    assert not mismatches,'Original files changed since baseline: '+str(mismatches)
    resources=read(original/'release_assets/release_manifest.json')
    for row in resources['resources']:
        assert sha(original/'release_assets'/row['path'])==row['sha256'],row['path']
    assert sha(original/'deliver/报告.pdf')==PDF_HASH
    software=original/'deliver/软件';old_exe=software/'开发板实时监测.exe'
    assert sha(old_exe)==OLD_HASH,'Formal EXE is no longer the expected 1.2.0'
    old_version=read(software/'软件版本.json');assert old_version['app_version']=='1.2.0'
    import psutil
    for process in psutil.process_iter(['pid','exe']):
        try:
            if process.info['exe'] and Path(process.info['exe']).resolve()==old_exe.resolve():
                raise RuntimeError('Close the formal 1.2.0 GUI before promotion (PID '+str(process.pid)+')')
        except (psutil.AccessDenied,psutil.NoSuchProcess):pass
    runtime=SOURCE_FILES+[p.relative_to(root).as_posix() for p in sorted((root/'host/ui').rglob('*.py'))]
    built=within(candidate['build_source_directory'],root/'runs')
    assert sha(built/'source_manifest.json')==candidate['source_manifest_sha256']
    for name in runtime:
        assert (root/name).is_file(),name
        if name.startswith('host/'):assert sha(root/name)==sha(built/name),'Runtime differs from tested build: '+name
    copies={}
    def add(source,relative):
        source=Path(source);assert source.is_file(),source
        destination=within(original/relative,original)
        assert destination!=original/'deliver/报告.pdf'
        if destination in copies:assert sha(copies[destination])==sha(source),destination
        copies[destination]=source
    for name in runtime+QA_FILES:add(root/name,name)
    for path in sorted((root/'docs').glob('UI*')):
        if path.is_file() and path.suffix in ('.md','.json'):add(path,path.relative_to(root))
    acceptance=Path('deliver/UI重构验收')
    for path in sorted(package.rglob('*')):
        if path.is_file():add(path,acceptance/path.relative_to(package))
    wheel=package/'wheels/ttkbootstrap-2.2.7-py3-none-any.whl'
    assert wheel.is_file(),'Pinned ttkbootstrap wheel missing'
    add(wheel,Path('upstream/ui/wheels')/wheel.name)
    for name,path in GATES.items():add(root/path,acceptance/'evidence'/Path(path).name)
    for path in sorted((root/'docs').glob('UI*')):
        if path.is_file() and path.suffix in ('.md','.json'):add(path,acceptance/'docs'/path.name)
    for path in sorted((root/'runs/ui_ab_02').rglob('*')):
        if path.is_file() and path.name in {'comparison.json','result.json','launch.json','samples.jsonl',
                'monitor.jsonl','preview.jsonl','session_summary.json'}:
            add(path,acceptance/'performance/ui_ab_02'/path.relative_to(root/'runs/ui_ab_02'))
    for path in sorted(built.rglob('*')):
        if path.is_file():add(path,Path('deliver/软件/UI更新源码')/path.relative_to(built))
    add(candidate['requirements_lock'],Path('deliver/软件/UI更新源码/requirements-locked.txt'))
    add(candidate['requirements_lock'],acceptance/'requirements-locked.txt')
    add(candidate['requirements_lock'],Path('upstream/ui/requirements-locked.txt'))
    add(original/'release_assets/release_manifest.json',acceptance/'original_resource_manifest.json')
    for row in gates['online']['rows']:
        wav=within(row['original_wav'],original/'runs');assert sha(wav)==row['wav_sha256']
        add(wav,acceptance/'archived_board_replay'/(row['wav_sha256'][:12]+'.wav'))
    live=gates['live']['recording'];wav=within(live['wav'],root/'runs')
    assert sha(wav)==live['wav_sha256_computed']
    add(wav,acceptance/'live_board_flow/audio.wav')
    pcm=within(wav.parent/'pcm.bin',root/'runs')
    assert sha(pcm)==live['pcm_sha256_computed']
    assert zlib.crc32(pcm.read_bytes())&0xffffffff==live['pcm_crc32_computed']
    add(pcm,acceptance/'live_board_flow/pcm.bin')
    sidecar=within(wav.parent/'metadata.json',root/'runs')
    recorded=read(sidecar)
    for name in ('record_id','samples','sample_rate','crc32','pcm_sha256','wav_sha256'):
        assert recorded[name]==live['metadata'][name],name
    add(sidecar,acceptance/'live_board_flow/metadata.json')
    read_metadata=within(wav.parent.parent/'metadata.json',root/'runs')
    if read_metadata.is_file():add(read_metadata,acceptance/'live_board_flow/read_metadata.json')
    replay_folder=within(gates['online']['data_root'],root/'runs').parent
    for name in ('result.json','worker_messages.jsonl','worker.stderr.txt'):
        add(replay_folder/name,acceptance/'online_worker'/name)
    gate_hashes={path:sha(root/path) for path in GATES.values()}
    plan={'app_version':'1.3.0','exe_sha256':checksum,'candidate_exe':str(exe),
        'original_project':str(original),'archive':str(software/'历史版本/1.2.0_447b8c15'),
        'gate_hashes':gate_hashes,'source_whitelist':runtime+QA_FILES,
        'copy_count':len(copies),'copy_bytes':sum(p.stat().st_size for p in copies.values()),
        'report_pdf_sha256':PDF_HASH,'original_baseline_file_count':len(baseline)}
    return candidate,gates,copies,plan,baseline


def execute(root,original,candidate,gates,copies,plan,baseline):
    archive=within(plan['archive'],original/'deliver/软件/历史版本')
    archive.mkdir(parents=True,exist_ok=True)
    software=original/'deliver/软件';source_backup=archive/'UI升级前源码'
    # Preserve a complete baseline so AST and resource fences remain reusable.
    for name in baseline:
        target=source_backup/name;target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():assert sha(target)==baseline[name],target
        else:shutil.copy2(original/name,target)
        assert sha(target)==baseline[name],target
    # The initial source hash list excluded pycache, but the sealed manifest
    # deliberately includes several audfprint .pyc resources. Keep those too.
    resource_manifest=read(original/'release_assets/release_manifest.json')
    for row in resource_manifest['resources']:
        name=Path('release_assets')/row['path'];target=source_backup/name
        target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():shutil.copy2(original/name,target)
        assert sha(target)==row['sha256'],target
    for name in ('开发板实时监测.exe','软件版本.json','使用说明.md'):
        source=software/name;target=archive/name
        if source.exists():
            if target.exists():assert sha(target)==sha(source),target
            else:shutil.copy2(source,target)
    assert sha(archive/'开发板实时监测.exe')==OLD_HASH
    now=datetime.now().astimezone().isoformat()
    record={**candidate,'delivered_at':now,'delivered_exe':str(software/'开发板实时监测.exe'),
        'previous_version_directory':str(archive),'ui_acceptance_directory':'../UI重构验收',
        'ui_verification':{'frozen':'UI冻结验证.json','online':'UI在线回放验证.json',
            'live':'UI实板流程验证.json','screenshots':'UI截图审查.json','performance':'comparison.json'}}
    index_path=original/'deliver/交付索引.json';index=read(index_path);before=deepcopy(index)
    history=index.setdefault('software_release_history',[]);assert isinstance(history,list)
    old_active=deepcopy(index.get('active_software',{}))
    if old_active and not any(r.get('exe_sha256')==OLD_HASH for r in history):history.append(old_active)
    index['active_software']={'file':'软件/开发板实时监测.exe','app_version':'1.3.0',
        'online_provider':'shazamio','exe_sha256':candidate['exe_sha256'],'firmware_unchanged':True,
        'offline_unchanged':True,'verification':'UI重构验收/evidence',
        'notes':'软件/UI更新说明.md','previous_version_directory':str(archive)}
    index['ui_delivery']={'delivered_at':now,'app_version':'1.3.0','exe_sha256':candidate['exe_sha256'],
        'acceptance_directory':'UI重构验收','source_directory':'软件/UI更新源码',
        'historical_report_unchanged':True,'gate_hashes':plan['gate_hashes']}
    for key,value in before.items():
        if key not in ('active_software','ui_delivery','software_release_history'):assert index[key]==value,key
    notes=('## 1.3.0 界面更新\n\n实时监测、事件记录和听歌识曲已统一到主窗口。'
        '主题入口支持跟随系统、浅色和深色；小窗口整页滚动，窄屏图表自动单列。'
        '录音和识别期间切换页面、切换主题会继续当前任务，显式“退出识曲”沿用原退出行为。'
        '串口、采样、算法、SQLite、Shazam 和离线功能保持原状。\n\n'
        '本机实板流程、截图复查、冻结资源及 A/B/A 性能验收均已通过。'
        '三首历史实板录音经同一冻结程序回放识别3/3，属于历史录音回归，不是新一轮手机录音准确率测量。'
        '证据在“UI重构验收”，精确构建源码与依赖锁在“UI更新源码”；原报告保留原实验归属。\n\n'
        'EXE SHA256：'+candidate['exe_sha256']+'\n\n')
    original_readme=(software/'使用说明.md').read_text(encoding='utf8')
    generated={software/'软件版本.json':encoded(record),software/'UI更新说明.md':notes.encode('utf8'),
        software/'使用说明.md':(notes+original_readme).encode('utf8'),index_path:encoded(index),
        original/'state/portable_build.json':encoded(record)}
    # Snapshot all overwritten destinations before the first replacement.
    targets=set(copies)|set(generated)|{software/'开发板实时监测.exe',
        original/'deliver/UI重构验收/SHA256清单.json',original/'state/ui_release_delivery.json'}
    backup_map={};added=[]
    for target in sorted(targets):
        within(target,original)
        if target.exists():
            dest=(source_backup if target.is_relative_to(original/'host') or target.is_relative_to(original/'scripts')
                or target in (original/'requirements-runtime.txt',original/'monitor.ps1') else archive/'UI升级前文件')/target.relative_to(original)
            dest.parent.mkdir(parents=True,exist_ok=True)
            if dest.exists():assert sha(dest)==sha(target),dest
            else:shutil.copy2(target,dest)
            backup_map[target]=dest
        else:added.append(target)
    (archive/'UI提升计划.json').write_bytes(encoded(plan))
    written=[]
    def install(target,source=None,data=None):
        target=within(target,original);target.parent.mkdir(parents=True,exist_ok=True)
        temporary=target.with_name(target.name+'.ui_'+uuid.uuid4().hex+'.tmp')
        try:
            if source is not None:shutil.copy2(source,temporary)
            else:temporary.write_bytes(data)
            os.replace(temporary,target);written.append(target)
        finally:
            if temporary.exists():temporary.unlink()
    try:
        for target,source in copies.items():install(target,source=source)
        for target,data in generated.items():install(target,data=data)
        for name,checksum in plan['gate_hashes'].items():assert sha(root/name)==checksum,'Acceptance changed during promotion'
        assert sha(candidate['candidate_exe'])==candidate['exe_sha256']
        install(software/'开发板实时监测.exe',source=candidate['candidate_exe'])
        assert sha(software/'开发板实时监测.exe')==candidate['exe_sha256']
        assert sha(original/'deliver/报告.pdf')==PDF_HASH
        for target,source in copies.items():assert sha(target)==sha(source),target
        acceptance=original/'deliver/UI重构验收'
        manifest=[{'path':p.relative_to(acceptance).as_posix(),'sha256':sha(p),'bytes':p.stat().st_size}
            for p in sorted(acceptance.rglob('*')) if p.is_file() and p.name!='SHA256清单.json']
        install(acceptance/'SHA256清单.json',data=encoded(manifest))
        delivery={**plan,'status':'passed','delivered_at':now,'backup_directory':str(archive),
            'verified_copy_count':len(copies),'user_database_touched':False,'report_unchanged':True}
        install(original/'state/ui_release_delivery.json',data=encoded(delivery))
        (archive/'UI提升结果.json').write_bytes(encoded(delivery))
        return delivery
    except Exception:
        # Restore only files touched by this invocation; backups are never removed.
        for target in reversed(written):
            if target in backup_map:shutil.copy2(backup_map[target],target)
            elif target in added and target.exists():within(target,original).unlink()
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--original',type=Path,default=Path(r'D:\projects\2222wuxiaoping_codex\nexys-event-recorder'))
    args=parser.parse_args();root=Path(__file__).resolve().parents[1];original=args.original.resolve()
    candidate,gates,copies,plan,baseline=prepare(root,original)
    if not args.execute:print(json.dumps({'mode':'read_only_check','ready':True,**plan},ensure_ascii=False,indent=2));return
    result=execute(root,original,candidate,gates,copies,plan,baseline)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
