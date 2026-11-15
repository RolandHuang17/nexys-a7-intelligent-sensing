"""Guarded 1.4 board-panel promotion; default preflight is strictly read-only.

--execute installs only the validated candidate bytes after all five acceptance
reports pass. It never builds, programs hardware, drives a GUI or copies a DB.
"""
import argparse
from copy import deepcopy
from datetime import datetime
import hashlib,json,os,shutil,uuid,wave,zipfile,zlib
from pathlib import Path

OLD_HASH='e4a79bad85e4c2da8eabbe4b95f21e1eaee16ea119dfa3ddafc0e175a65c8c7e'
PDF_HASH='a6df26b2fdab4db7a1778910468c26c84df32c009a13e7807ccc0e4895033494'
RUNTIME=['host/app_paths.py','host/build_shazam_main.py','host/monitor_gui.py','host/music_gui.py',
    'host/protocol.py','host/monitor_service.py','host/music_board.py','host/panel_protocol.py','host/panel_control.py']
QA=['host/test_board_panel_rtl.py','host/test_panel_host.py','host/test_panel_contracts.py','host/ui_benchmark.py',
    'host/test_music_panel_quiet.py','scripts/verify_panel_digital.py','scripts/verify_panel_frozen.py',
    'scripts/board_panel_acceptance.py','scripts/promote_panel_release.py','scripts/simple_panel_acceptance.py']
RTL=['rtl/recorder_top.sv','rtl/music_core.sv','rtl/board_panel.sv','rtl/build_id.svh','constraints/nexys_a7_100t.xdc']
FIXTURES=['tests/tb_music_panel_quiet.sv','tests/tb_board_panel.sv','tests/tb_music.sv','tests/tb_music_half.sv','tests/tb_music_tap.sv',
    'config/monitor_golden_frames.json','config/music_golden_frames.json','config/music_8000_golden_frames.json']
GATES={'frozen':'docs/板载面板冻结验证.json','digital':'docs/板载面板数字验证.json',
    'physical':'docs/板载面板实板验收.json','performance':'runs/panel_ab_01/comparison.json',
    'screenshots':'docs/板载面板截图审查.json'}
CONCURRENT_UNTOUCHED={'host/build_tilt_game.py','host/finalize_tilt_game.py','host/test_tilt_game.py',
    'host/tilt_game_main.py','host/verify_tilt_game_physical.py','host/tilt_game/input.py'}
DB_SUFFIXES=tuple(base+tail for base in ('.db','.sqlite','.sqlite3') for tail in ('','-wal','-shm','-journal'))


def require(condition,message):
    if not condition:raise ValueError(message)
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def encoded(value):return json.dumps(value,ensure_ascii=False,indent=2).encode('utf8')
def within(path,root):
    path=Path(path).resolve();root=Path(root).resolve()
    require(path.is_relative_to(root),'Path outside intended root: '+str(path));return path

def locate(name,root,package=None):
    path=Path(name)
    if not path.is_absolute():
        options=([package/path] if package else [])+[root/path]
        path=next((p for p in options if p.is_file()),options[0])
    return within(path,root)

def recording_files(row,root):
    """Validate saved physical PCM against WAV, its metadata, CRC and hashes."""
    wav=locate(row['wav'],root)
    pcm=locate(row.get('pcm',str(wav.with_name('pcm.bin'))),root)
    sidecar=locate(row.get('metadata_file',str(wav.with_name('metadata.json'))),root)
    meta=read(sidecar);reported=row.get('metadata',row)
    for key in ('record_id','samples','sample_rate','crc32','pcm_sha256','wav_sha256'):
        if key in reported:require(reported[key]==meta[key],'Recording metadata mismatch: '+key)
    raw=pcm.read_bytes();crc=zlib.crc32(raw)&0xffffffff
    require(len(raw)==meta['samples']*2,'Incomplete PCM')
    require(crc==meta['crc32'],'PCM CRC mismatch')
    require(sha(pcm)==meta['pcm_sha256'],'PCM SHA mismatch')
    require(sha(wav)==meta['wav_sha256'],'WAV SHA mismatch')
    for key,actual in [('pcm_sha256_computed',sha(pcm)),('wav_sha256_computed',sha(wav)),('pcm_crc32_computed',crc)]:
        if key in row:require(row[key]==actual,'Recording evidence mismatch: '+key)
    with wave.open(str(wav),'rb') as audio:
        require((audio.getnchannels(),audio.getsampwidth(),audio.getframerate(),audio.getnframes())==
            (1,2,meta['sample_rate'],meta['samples']),'WAV header mismatch')
        require(audio.readframes(audio.getnframes())==raw,'WAV frames differ from physical PCM')
    require(meta['sample_rate'] in (8000,16000),'Unexpected recording sample rate')
    return [wav,pcm,sidecar],meta


def prepare(root,original):
    root=root.resolve();original=original.resolve()
    require(root!=original,'Candidate checkout must be isolated')
    baseline_record=read(root/'state/panel_baseline.json')
    baseline={n.replace('\\','/'):h for n,h in baseline_record['files'].items()}
    require(baseline_record['version']=='1.3.0' and len(baseline)==286,'Expected immutable 286-file 1.3 baseline')
    require(Path(baseline_record['original']).resolve()==original,'Baseline belongs to another original project')
    raw_baseline_names=set(baseline)
    concurrent={}
    for name,digest in baseline.items():
        actual=sha(within(original/name,original))
        if actual!=digest:
            require(name in CONCURRENT_UNTOUCHED and name not in RUNTIME+QA+RTL+FIXTURES,'Original changed since baseline: '+name)
            concurrent[name]=actual
    software=original/'deliver/软件';old_exe=software/'开发板实时监测.exe'
    old_version=read(software/'软件版本.json')
    require(sha(old_exe)==OLD_HASH and old_version['app_version']=='1.3.0','Expected formal 1.3.0 EXE')
    old_built=within(old_version['build_source_directory'],root/'runs')
    require(sha(old_built/'source_manifest.json')==old_version['source_manifest_sha256'],'Immutable 1.3 monitor source snapshot changed')
    for row in read(old_built/'source_manifest.json'):
        require(sha(within(old_built/'host'/row['path'],old_built/'host'))==row['sha256'],'Old monitor source bytes changed')
    require(sha(original/'deliver/报告.pdf')==PDF_HASH,'Historical PDF changed')
    candidate=read(root/'state/shazam_main_candidate.json');checksum=candidate['exe_sha256']
    exe=within(candidate['candidate_exe'],root/'.portable_build')
    require(candidate['app_version']=='1.4.0' and sha(exe)==checksum,'Invalid tested 1.4.0 candidate')
    gates={name:read(root/path) for name,path in GATES.items()}
    performance_waived=gates['performance'].get('status')=='waived_by_user'
    for name,gate in gates.items():
        if name=='performance' and performance_waived:
            require(gate.get('user_request',{}).get('source')=='user_chat' and
                    gate['user_request'].get('statement')=='别性能采样了，搞快一点，太浪费时间了',
                    'Performance waiver requires the explicit user instruction')
            require(gate.get('exe_sha256')==checksum,'Performance waiver EXE mismatch')
            continue
        require(gate.get('passed') is True or gate.get('status')=='passed','Gate has not passed: '+name)
        if 'checks' in gate:require(bool(gate['checks']) and all(v is True for v in gate['checks'].values()),'Gate checks failed: '+name)
        if name!='performance' or 'exe_sha256' in gate:require(gate.get('exe_sha256')==checksum,'Gate EXE mismatch: '+name)
    physical=gates['physical'];require(physical.get('user_visual_confirmed') is True,'Physical display requires actual user visual confirmation')
    if physical.get('kind')=='simple_panel_acceptance_v2':
        required_steps={'ready','record','finish'}
    elif physical.get('kind')=='user_confirmed_live_session':
        confirmation=physical.get('user_confirmation',{})
        require(confirmation.get('source')=='user_chat' and confirmation.get('statement')=='完成，显示正常',
                'Manual session requires the actual user visual confirmation')
        require(physical.get('guided_test_finished') is False,'Manual session must preserve interrupted guide provenance')
        required_steps={'mode_enable','recordings_complete','mode_disable'}
    else:raise ValueError('Unknown physical evidence workflow')
    require({s.get('step') for s in physical.get('steps',[])}==required_steps and
            all(s.get('passed') is True for s in physical['steps']),'Physical evidence is incomplete')
    require(read(root/'runs/panel_ab_01/B_candidate/launch.json')['exe_sha256']==checksum,'Performance EXE mismatch')
    if not performance_waived:
        measured=gates['performance']['runs'];require(len(measured)==3,'A/B/A results missing')
        require(all(r['elapsed_s']>=300 and r['warmup_s']>=30 for r in measured),'Full A/B/A duration required')
        require(all(r.get('firmware_programmed_for_case') for r in measured),'Each A/B/A case must use its own bundled firmware')
        require(measured[1]['device']['build_id']==candidate['firmware']['build_id'],'Performance firmware mismatch')
    built=within(candidate['build_source_directory'],root/'runs')
    require(sha(built/'source_manifest.json')==candidate['source_manifest_sha256'],'Tested source manifest changed')
    source_rows=read(built/'source_manifest.json')
    for row in source_rows:require(sha(within(built/'host'/row['path'],built/'host'))==row['sha256'],'Build snapshot changed: '+row['path'])
    for name in RUNTIME+[p for p in QA if p.startswith('host/')]:
        require(sha(root/name)==sha(built/name),'Source differs from tested EXE snapshot: '+name)
    # Seal every old resource and permit replacing only the firmware bitstream.
    old_assets=read(original/'release_assets/release_manifest.json')
    stage=root/'.portable_build/shazam_main_assets/release_assets';new_assets=read(stage/'release_manifest.json')
    require(sha(stage/'release_manifest.json')==candidate['resource_manifest_sha256'],'Staged manifest differs from tested EXE')
    require(new_assets['firmware']==candidate['firmware'],'Staged firmware metadata mismatch')
    for row in old_assets['resources']:
        name=row['path'];require(sha(original/'release_assets'/name)==row['sha256'],'Original resource changed: '+name)
        if name!='firmware/recorder_top.bit':require(sha(stage/name)==row['sha256'],'Non-firmware resource changed: '+name)
    old_paths={r['path'] for r in old_assets['resources']}
    for row in new_assets['resources']:
        require(row['path'] in old_paths or row['path'].startswith('licenses/shazam_runtime/'),'Unexpected new resource: '+row['path'])
        require(sha(within(stage/row['path'],stage))==row['sha256'],'Staged resource changed: '+row['path'])
    firmware=candidate['firmware'];fpga=within(root/'runs'/firmware['build_run_id'],root/'runs')
    inputs=read(fpga/'build_inputs.json');status=read(fpga/'status.json')
    require(status['status']=='passed' and inputs['parameters']['MUSIC_MAX_SAMPLES']==160000,'Passed full-size FPGA build required')
    require(inputs['build_id']==firmware['build_id'],'FPGA build ID mismatch')
    source_status=read(root/'state/build/status.json')
    require(source_status==status and status['run_id']==firmware['build_run_id'],'Source entry latest status differs from tested FPGA run')
    require(status['config_sha256']==firmware['config_sha256'],'Source entry XDC status mismatch')
    require(within(root/status['outputs'][0],fpga)==fpga/'implementation/recorder_top.bit','Source entry bitstream output path mismatch')
    require(firmware['build_run_id']!=old_version['firmware']['build_run_id'],'New firmware run must not overwrite an old run')
    formal_run=within(original/'runs'/firmware['build_run_id'],original/'runs')
    if formal_run.is_dir():
        for existing in formal_run.rglob('*'):
            if existing.is_file():
                expected=fpga/existing.relative_to(formal_run)
                require(expected.is_file() and sha(existing)==sha(expected),'Existing formal run differs; it must remain untouched: '+str(existing))
    require(sha(fpga/'implementation/recorder_top.bit')==firmware['bitstream_sha256']==sha(stage/'firmware/recorder_top.bit'),'FPGA bitstream mismatch')
    require(sha(root/'constraints/nexys_a7_100t.xdc')==firmware['config_sha256'],'XDC differs from tested firmware')
    for row in inputs['files']:
        require(sha(within(root/row['path'],root))==row['sha256'],'RTL/XDC changed after build: '+row['path'])
        require(sha(within(fpga/'input_source'/row['path'],fpga/'input_source'))==row['sha256'],'Frozen FPGA input changed')
    import psutil
    for proc in psutil.process_iter(['pid','exe']):
        try:require(not proc.info['exe'] or Path(proc.info['exe']).resolve()!=old_exe.resolve(),'Close formal 1.3 GUI before promotion: PID '+str(proc.pid))
        except (psutil.NoSuchProcess,psutil.AccessDenied):pass
    package=root/'deliver/板载面板验收';copies={}
    def add(source,relative):
        source=within(source,root);require(source.is_file(),'Missing delivery source: '+str(source))
        require(not source.name.lower().endswith(DB_SUFFIXES),'Databases may not be copied')
        with source.open('rb') as stream:require(stream.read(16)!=b'SQLite format 3\x00','Renamed databases may not be copied')
        destination=within(original/relative,original)
        require(destination!=original/'deliver/报告.pdf','PDF is immutable')
        if destination in copies:require(sha(copies[destination])==sha(source),'Conflicting destination: '+str(destination))
        copies[destination]=source
    for name in RUNTIME+QA+RTL+FIXTURES:add(root/name,name)
    # Source monitor.ps1 and program_latest use state/build plus audited runs,
    # whereas the frozen application reads its embedded release_assets.
    source_entry_files=[fpga/'status.json',fpga/'build_inputs.json',fpga/'implementation/recorder_top.bit']
    source_entry_files += [p for p in sorted((fpga/'input_source').rglob('*')) if p.is_file()]
    for path in source_entry_files:add(path,Path('runs')/fpga.name/path.relative_to(fpga))
    add(fpga/'status.json',Path('state/build/status.json'))
    for path in source_entry_files:
        destination=within(formal_run/path.relative_to(fpga),formal_run)
        require(destination in copies and sha(copies[destination])==sha(path),'Incomplete source-entry copy plan')
    source_entry={'build_run_id':fpga.name,'build_id':inputs['build_id'],'formal_run':str(formal_run),
        'status_sha256':sha(fpga/'status.json'),'build_inputs_sha256':sha(fpga/'build_inputs.json'),
        'bitstream_sha256':firmware['bitstream_sha256'],'config_sha256':firmware['config_sha256'],
        'input_source_file_count':len(source_entry_files)-3,'global_status_target':'state/build/status.json',
        'old_runs_replaced':False}
    # Retain the raw baseline plus Git archive for reproducible contract checks.
    for name in ('panel_baseline.json','panel_baseline_1.3.zip'):
        add(root/'state'/name,Path('state')/name);add(root/'state'/name,Path('deliver/板载面板验收/baseline')/name)
    for path in sorted((root/'docs').glob('板载面板*')):
        if path.is_file() and path.suffix in ('.md','.json'):add(path,path.relative_to(root));add(path,Path('deliver/板载面板验收/docs')/path.name)
    for path in sorted(package.rglob('*')):
        if path.is_file():add(path,Path('deliver/板载面板验收')/path.relative_to(package))
    screenshots=gates['screenshots'].get('screenshots',[]);require(len(screenshots)>=2,'Reviewed screenshots missing')
    for row in screenshots:
        require(isinstance(row,dict) and row.get('sha256'),'Screenshot hash required')
        image=locate(row.get('path',row.get('file')),root,package);within(image,package)
        require(sha(image)==row['sha256'],'Reviewed screenshot changed')
    recordings=physical.get('recordings') or ([physical['recording']] if 'recording' in physical else [])
    require(recordings,'Physical recording evidence missing');full_length=False
    for i,row in enumerate(recordings,1):
        files,meta=recording_files(row,root)
        full_length|=(meta['samples']==160000 and meta['sample_rate']==8000)
        for path in files:add(path,Path('deliver/板载面板验收/recordings')/f'{i:02}_{meta["record_id"]}'/path.name)
    require(full_length,'At least one complete 20-second board recording is required')
    for path in GATES.values():add(root/path,Path('deliver/板载面板验收/evidence')/Path(path).name)
    add(root/'docs/板载面板实板验收.jsonl',Path('deliver/板载面板验收/evidence/板载面板实板验收.jsonl'))
    digital=gates['digital']
    digital_roots=[within(digital['result_directory'],root/'runs')]
    for key in ('panel','quiet_integration'):
        digital_roots.append(within(root/'runs'/digital[key]['run_id'],root/'runs'))
    for run_id in digital['legacy_runs'].values():digital_roots.append(within(root/'runs'/run_id,root/'runs'))
    excluded={'xsim.dir','source_snapshots','source','input_source','snapshots','__pycache__'}
    for folder in digital_roots:
        require(folder.is_dir(),'Missing digital evidence directory')
        for path in sorted(folder.rglob('*')):
            if path.is_file() and path.suffix.lower() in ('.json','.jsonl','.log','.hex','.txt','.bin') and not any(part in excluded for part in path.relative_to(folder).parts):
                add(path,Path('deliver/板载面板验收/digital')/folder.name/path.relative_to(folder))
    ui_smoke=locate(digital.get('ui_smoke_path','runs/panel_ui_smoke_01/result.json'),root)
    add(ui_smoke,Path('deliver/板载面板验收/digital')/ui_smoke.parent.name/ui_smoke.name)
    for gate in gates.values():
        for item in gate.get('evidence_files',[]):
            path=locate(item['path'] if isinstance(item,dict) else item,root)
            if isinstance(item,dict) and 'sha256' in item:require(sha(path)==item['sha256'],'Referenced evidence changed')
            add(path,Path('deliver/板载面板验收/evidence/attached')/path.relative_to(root))
    for path in sorted((root/'runs/panel_ab_01').rglob('*')):
        if path.is_file() and path.name in {'comparison.json','result.json','launch.json','samples.jsonl','monitor.jsonl','preview.jsonl','session_summary.json'}:
            add(path,Path('deliver/板载面板验收/performance')/path.relative_to(root/'runs/panel_ab_01'))
    for path in sorted(built.rglob('*')):
        if path.is_file():add(path,Path('deliver/软件/面板更新源码')/path.relative_to(built))
    for path in sorted((fpga/'input_source').rglob('*')):
        if path.is_file():add(path,Path('deliver/软件/面板更新源码/FPGA/input_source')/path.relative_to(fpga/'input_source'))
    for path in [fpga/'build_inputs.json',fpga/'status.json']+list((fpga/'implementation').glob('*.rpt')):
        add(path,Path('deliver/软件/面板更新源码/FPGA')/path.name)
    add(candidate['requirements_lock'],Path('deliver/软件/面板更新源码/requirements-locked.txt'))
    add(candidate['requirements_lock'],Path('deliver/板载面板验收/requirements-locked.txt'))
    for row in new_assets['resources']:add(stage/row['path'],Path('release_assets')/row['path'])
    add(stage/'release_manifest.json',Path('release_assets/release_manifest.json'))
    # Include root-level baseline build scripts/documents beyond the 286 raw hashes.
    archive_source=root/'state/panel_baseline_1.3.zip'
    with zipfile.ZipFile(archive_source) as old:
        for name in old.namelist():
            if name.endswith('/') or name in baseline:continue
            path=within(original/name,original)
            if name.split('/')[0] in ('host','rtl','scripts','constraints','tests','config','docs') or '/' not in name:
                if path.is_file():
                    archived=old.read(name)
                    if archived.replace(b'\r\n',b'\n')!=path.read_bytes().replace(b'\r\n',b'\n'):
                        require(name=='.gitignore' and path not in copies,'Original baseline content changed: '+name)
                        concurrent[name]=sha(path)
                        baseline[name]=hashlib.sha256(archived).hexdigest()  # Old Git bytes, not a claimed raw-file baseline.
                    else:baseline[name]=sha(path)
    plan={'app_version':'1.4.0','exe_sha256':checksum,'candidate_exe':str(exe),'original_project':str(original),
        'archive':str(software/'历史版本/1.3.0_e4a79bad'),'firmware':firmware,'source_entry_configuration':source_entry,
        'gate_hashes':{path:sha(root/path) for path in GATES.values()},'report_pdf_sha256':PDF_HASH,
        'copy_count':len(copies),'copy_bytes':sum(p.stat().st_size for p in copies.values()),
        'original_baseline_file_count':len(baseline),'protected_raw_baseline_file_count':286-len(raw_baseline_names.intersection(concurrent)),
        'old_monitor_source_snapshot':str(old_built),'old_monitor_source_manifest_sha256':old_version['source_manifest_sha256'],
        'concurrent_preserved_files':concurrent,'baseline_manifest_sha256':sha(root/'state/panel_baseline.json'),
        'copy_hashes':{str(target.relative_to(original)):sha(source) for target,source in copies.items()}}
    return candidate,copies,plan,baseline


def execute(root,original,candidate,copies,plan,baseline):
    """Save all rollback bytes before atomically replacing any target."""
    for name,digest in baseline.items():
        require(sha(original/name)==plan['concurrent_preserved_files'].get(name,digest),'Original changed after preflight: '+name)
    archive=within(plan['archive'],original/'deliver/软件/历史版本');archive.mkdir(parents=True,exist_ok=True)
    software=original/'deliver/软件';backup=archive/'面板升级前源码'
    def preserve(source,target,expected=None):
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():require(sha(target)==(expected or sha(source)),'Conflicting rollback archive: '+str(target))
        else:shutil.copy2(source,target)
        if expected:require(sha(target)==expected,'Rollback hash mismatch')
    with zipfile.ZipFile(root/'state/panel_baseline_1.3.zip') as saved:
        for name,digest in baseline.items():
            if name not in plan['concurrent_preserved_files']:preserve(original/name,backup/name,digest)
            else:
                current=plan['concurrent_preserved_files'][name]
                require(sha(original/name)==current,'Concurrent game source changed after preflight: '+name)
                preserve(original/name,archive/'并发游戏源码快照'/current[:12]/name,current)
                if name not in saved.namelist():continue  # Unowned game source was never in the 1.3 monitor Git archive.
                archived=saved.read(name)
                variants=[archived,archived.replace(b'\r\n',b'\n'),archived.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')]
                raw=next((data for data in variants if hashlib.sha256(data).hexdigest()==digest),None)
                if raw is None:continue  # Keep exact old Git bytes in the ZIP, never mislabel current game bytes.
                target=backup/name;target.parent.mkdir(parents=True,exist_ok=True)
                if target.exists():require(sha(target)==digest,'Conflicting raw baseline backup')
                else:target.write_bytes(raw)
    old_built=within(plan['old_monitor_source_snapshot'],root/'runs')
    require(sha(old_built/'source_manifest.json')==plan['old_monitor_source_manifest_sha256'],'Old monitor source changed after preflight')
    for row in read(old_built/'source_manifest.json'):
        require(sha(within(old_built/'host'/row['path'],old_built/'host'))==row['sha256'],'Old monitor source changed during promotion')
    for source in sorted(old_built.rglob('*')):
        if source.is_file():preserve(source,archive/'1.3监测程序构建源码'/source.relative_to(old_built))
    preserve(root/'state/panel_baseline_1.3.zip',archive/'panel_baseline_1.3.zip')
    preserve(root/'state/panel_baseline.json',archive/'panel_baseline.json')
    for name in ('开发板实时监测.exe','软件版本.json','使用说明.md'):preserve(software/name,archive/name)
    preserve(original/'release_assets/firmware/recorder_top.bit',archive/'recorder_top.bit')
    preserve(original/'release_assets/release_manifest.json',archive/'release_manifest.json')
    require(sha(archive/'开发板实时监测.exe')==OLD_HASH,'Rollback EXE mismatch')
    stamp=datetime.now().astimezone().isoformat()
    record={**candidate,'delivered_at':stamp,'delivered_exe':str(software/'开发板实时监测.exe'),
        'previous_version_directory':str(archive),'panel_acceptance_directory':'../板载面板验收'}
    index_path=original/'deliver/交付索引.json';index=read(index_path);old_index=deepcopy(index)
    history=index.setdefault('software_release_history',[]);require(isinstance(history,list),'Invalid release history')
    old_active=deepcopy(index.get('active_software',{}))
    if old_active and not any(row.get('exe_sha256')==OLD_HASH for row in history):history.append(old_active)
    index['active_software']={'file':'软件/开发板实时监测.exe','app_version':'1.4.0','exe_sha256':candidate['exe_sha256'],
        'online_provider':'shazamio','firmware_unchanged':False,'firmware':candidate['firmware'],'offline_unchanged':True,
        'verification':'板载面板验收/evidence','notes':'软件/面板更新说明.md','previous_version_directory':str(archive)}
    index['panel_delivery']={'delivered_at':stamp,'app_version':'1.4.0','exe_sha256':candidate['exe_sha256'],
        'acceptance_directory':'板载面板验收','source_directory':'软件/面板更新源码','gate_hashes':plan['gate_hashes'],
        'historical_report_unchanged':True}
    for key,value in old_index.items():
        if key not in ('active_software','software_release_history','panel_delivery'):require(index[key]==value,'Historical index changed')
    notes=('## 1.4.0 板载面板更新\n\n新增独立灯光、数码管状态显示和拨码快捷控制。'
        '日常只用 SW15：拨上进入识曲，拨下退出并恢复监测。'
        '录音和收藏使用原有电脑按钮，灯效自动跟随状态；其余开关是可选的显示调节。'
        '启动或重连时，SW15 已拨上就恢复到识曲准备状态，不会直接开始录音。'
        '任务进行中拨下 SW15，仍会等本次任务结束再退出。\n\n'
        'PANEL 只更新显示；串口数据通道、采样算法、SQLite、Shazam 和离线匹配参数保留。'
        '此版本配套新面板固件，仅由通过 100MHz 时序验证的构建生成。原报告继续归属历史实验。'
        '实板视觉确认、完整录音 CRC/WAV、数字测试、冻结资源及截图保存在“板载面板验收”。'
        +('性能采样已按用户要求停止，保留已采片段，不宣称完整性能对照通过。\n\n' if read(root/GATES['performance']).get('status')=='waived_by_user' else '完整性能对照证据也保存在该目录。\n\n')+
        '回退时使用“历史版本/1.3.0_e4a79bad”中的原 EXE、完整源码和位流；用户数据库不参与替换。\n\n'
        'EXE SHA256：'+candidate['exe_sha256']+'\n\n')
    generated={software/'软件版本.json':encoded(record),software/'面板更新说明.md':notes.encode('utf8'),
        software/'使用说明.md':(notes+(software/'使用说明.md').read_text(encoding='utf8')).encode('utf8'),
        index_path:encoded(index),original/'state/portable_build.json':encoded(record)}
    manifest_path=original/'deliver/板载面板验收/SHA256清单.json';receipt_path=original/'state/panel_release_delivery.json'
    targets=set(copies)|set(generated)|{software/'开发板实时监测.exe',manifest_path,receipt_path}
    backups={};added=set()
    for target in targets:
        within(target,original)
        if target.exists():
            saved=archive/'面板升级前文件'/target.relative_to(original);preserve(target,saved);backups[target]=saved
        else:added.add(target)
    for name,digest in baseline.items():
        require(sha(original/name)==plan['concurrent_preserved_files'].get(name,digest),'Original changed while rollback archive was prepared: '+name)
    (archive/'面板提升计划.json').write_bytes(encoded(plan));written=[]
    def install(target,source=None,data=None):
        target=within(target,original);target.parent.mkdir(parents=True,exist_ok=True)
        temporary=target.with_name(target.name+'.panel_'+uuid.uuid4().hex+'.tmp')
        try:
            if source is not None:shutil.copy2(source,temporary)
            else:temporary.write_bytes(data)
            os.replace(temporary,target);written.append(target)
        finally:
            if temporary.exists():temporary.unlink()
    try:
        for target,source in copies.items():
            expected=plan['copy_hashes'][str(target.relative_to(original))]
            require(sha(source)==expected,'Delivery source changed during promotion')
            install(target,source=source);require(sha(target)==expected,'Delivery copy mismatch')
        for target,data in generated.items():install(target,data=data)
        for name,digest in plan['gate_hashes'].items():require(sha(root/name)==digest,'Acceptance changed during promotion')
        require(sha(candidate['candidate_exe'])==candidate['exe_sha256'],'Tested EXE changed')
        install(software/'开发板实时监测.exe',source=candidate['candidate_exe'])
        require(sha(software/'开发板实时监测.exe')==candidate['exe_sha256'],'Formal EXE mismatch')
        require(sha(original/'deliver/报告.pdf')==PDF_HASH,'Historical PDF changed')
        entry=plan['source_entry_configuration'];installed=read(original/'state/build/status.json')
        require(sha(original/'state/build/status.json')==entry['status_sha256'],'Installed source entry status mismatch')
        run_dir=within(original/'runs'/installed['run_id'],original/'runs')
        require(installed['status']=='passed' and installed['run_id']==entry['build_run_id'],'Installed source entry run mismatch')
        require(sha(run_dir/'build_inputs.json')==entry['build_inputs_sha256'],'Installed source entry inputs mismatch')
        require(sha(within(original/installed['outputs'][0],run_dir))==entry['bitstream_sha256'],'Installed source entry bitstream mismatch')
        for row in read(run_dir/'build_inputs.json')['files']:
            require(sha(within(original/row['path'],original))==row['sha256'],'Installed source RTL/XDC differs from tested firmware')
            require(sha(within(run_dir/'input_source'/row['path'],run_dir/'input_source'))==row['sha256'],'Installed frozen source input mismatch')
        for name,digest in plan['concurrent_preserved_files'].items():require(sha(original/name)==digest,'Concurrent game file changed during promotion: '+name)
        acceptance=original/'deliver/板载面板验收'
        manifest=[{'path':p.relative_to(acceptance).as_posix(),'sha256':sha(p),'bytes':p.stat().st_size}
            for p in sorted(acceptance.rglob('*')) if p.is_file() and p!=manifest_path]
        install(manifest_path,data=encoded(manifest))
        result={**plan,'status':'passed','delivered_at':stamp,'backup_directory':str(archive),'user_database_touched':False,'report_unchanged':True}
        install(receipt_path,data=encoded(result));(archive/'面板提升结果.json').write_bytes(encoded(result));return result
    except Exception:
        for target in reversed(written):
            if target in backups:shutil.copy2(backups[target],target)
            elif target in added and target.exists():within(target,original).unlink()
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--execute',action='store_true')
    parser.add_argument('--original',type=Path,default=Path(r'D:\projects\2222wuxiaoping_codex\nexys-event-recorder'))
    args=parser.parse_args();root=Path(__file__).resolve().parents[1];original=args.original.resolve()
    try:candidate,copies,plan,baseline=prepare(root,original)
    except (OSError,ValueError,KeyError,TypeError) as error:
        print(json.dumps({'mode':'execute' if args.execute else 'read_only_check','ready':False,'reason':str(error)},ensure_ascii=False,indent=2));return 2
    if not args.execute:print(json.dumps({'mode':'read_only_check','ready':True,**plan},ensure_ascii=False,indent=2));return 0
    print(json.dumps(execute(root,original,candidate,copies,plan,baseline),ensure_ascii=False,indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
