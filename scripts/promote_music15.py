"""Promote the verified 1.5 candidate, preserving the complete accepted 1.4 release.

Only an explicit list of source/evidence files is installed. User data, databases,
the course report and unrelated game development never enter the copy list.
"""
import argparse,hashlib,json,shutil,zipfile
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
ORIGINAL=Path(r'D:\projects\2222wuxiaoping_codex\nexys-event-recorder')
OLD_SHA='1761968ba1ca807e7665f774438d760c69c9fdc41ab362a541095a7b158dd772'
PDF_SHA='a6df26b2fdab4db7a1778910468c26c84df32c009a13e7807ccc0e4895033494'
SOURCE=['host/app_paths.py','host/build_shazam_main.py','host/monitor_gui.py','host/monitor_service.py',
 'host/music_board.py','host/music_gui.py','host/music_protocol.py','host/music_worker.py','host/panel_control.py',
 'rtl/music_core.sv','rtl/board_panel.sv','rtl/build_id.svh',
 'host/test_panel_contracts.py','host/test_panel_host.py','host/test_music_cancel.py',
 'host/test_music_engine_cancel.py','host/test_music_board_cancel.py','host/test_music_abort_rtl.py',
 'host/test_music_triple_rtl.py','host/test_music_panel_quiet.py','host/test_board_panel_rtl.py',
 'host/test_music_decimator.py','host/test_music_tap.py','host/test_music_tap1000.py',
 'tests/tb_music.sv','tests/tb_music_half.sv','tests/tb_music_tap.sv','tests/tb_music_abort.sv',
 'tests/tb_music_triple.sv','tests/tb_music_panel_quiet.sv','tests/tb_board_panel.sv',
 'config/music_golden_frames.json','config/music_8000_golden_frames.json',
 'scripts/verify_music15.py','scripts/verify_panel_frozen.py','scripts/promote_music15.py']

def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
 p.write_bytes(json.dumps(v,ensure_ascii=False,indent=2).encode('utf8'))
def copy(source,target):
 source=Path(source).resolve();target=Path(target).resolve()
 assert source.is_file() and target.is_relative_to(ORIGINAL)
 assert not any(part.lower().endswith(('.db','.sqlite','.sqlite3','-wal','-shm')) for part in target.parts)
 assert source.read_bytes()[:16]!=b'SQLite format 3\x00'
 target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
 assert sha(source)==sha(target)

def promote(execute=False):
 baseline=read(ROOT/'state/music15_baseline.json');candidate=read(ROOT/'state/shazam_main_candidate.json')
 software=ORIGINAL/'deliver/软件';old=software/'开发板实时监测.exe';exe=Path(candidate['candidate_exe'])
 assert candidate['app_version']=='1.5.0' and sha(exe)==candidate['exe_sha256']
 assert sha(old)==OLD_SHA and read(software/'软件版本.json')['app_version']=='1.4.0'
 assert sha(ORIGINAL/'deliver/报告.pdf')==PDF_SHA
 assert sha(baseline['source_archive'])==baseline['archive_sha256']
 for name in SOURCE:
  assert (ROOT/name).is_file(),name
  if name in baseline['files']:assert sha(ORIGINAL/name)==baseline['files'][name],'Formal owned file changed: '+name
 for name in ['三敲中止数字验证.json','三敲中止冻结验证.json','三敲中止运行验证.json']:
  gate=read(ROOT/'docs'/name)
  assert gate['status']=='passed' and gate['exe_sha256']==candidate['exe_sha256'],name
 frozen=Path(candidate['build_source_directory'])
 assert sha(frozen/'source_manifest.json')==candidate['source_manifest_sha256']
 for item in read(frozen/'source_manifest.json'):assert sha(ROOT/'host'/item['path'])==item['sha256'],item['path']
 fw_run=ROOT/'runs'/candidate['firmware']['build_run_id']
 assert read(fw_run/'status.json')['status']=='passed'
 for item in read(fw_run/'build_inputs.json')['files']:assert sha(ROOT/item['path'])==item['sha256'],item['path']
 assert sha(fw_run/'implementation/recorder_top.bit')==candidate['firmware']['bitstream_sha256']
 assets=ROOT/'.portable_build/shazam_main_assets/release_assets';manifest=read(assets/'release_manifest.json')
 assert manifest['firmware']==candidate['firmware'] and manifest['app_version']=='1.5.0'
 for item in manifest['resources']:assert sha(assets/item['path'])==item['sha256'],item['path']
 previous_assets=read(ORIGINAL/'release_assets/release_manifest.json')
 for item in previous_assets['resources']:
  if item['path']!='firmware/recorder_top.bit':assert sha(assets/item['path'])==item['sha256'],item['path']
 record={'status':'preflight_passed','time':datetime.now().astimezone().isoformat(),'app_version':'1.5.0',
  'exe_sha256':sha(exe),'firmware':candidate['firmware'],'previous_exe_sha256':OLD_SHA,
  'installed_sources':SOURCE,'database_files_copied':0,'historical_pdf_sha256':PDF_SHA,
  'human_physical_knocks':read(ROOT/'docs/三敲中止运行验证.json').get('human_physical_knocks','not_claimed'),
  'performance_sampling':'omitted_at_user_request'}
 if not execute:return record
 archive=software/'历史版本/1.4.0_1761968b';archive.mkdir(parents=True,exist_ok=True)
 for name in ['开发板实时监测.exe','软件版本.json','使用说明.md']:
  p=software/name
  if p.exists():
   if (archive/name).exists():assert sha(archive/name)==sha(p)
   else:copy(p,archive/name)
 for name in ['firmware/recorder_top.bit','release_manifest.json']:
  copy(ORIGINAL/'release_assets'/name,archive/'release_assets'/name)
 copy(baseline['source_archive'],archive/'source_1.4.zip')
 copy(ROOT/'state/music15_baseline.json',archive/'baseline.json')
 for name in SOURCE:copy(ROOT/name,ORIGINAL/name)
 for p in fw_run.rglob('*'):
  # Enough to reproduce and program; large intermediate synthesis databases stay in the audited checkout.
  if p.is_file() and (p.is_relative_to(fw_run/'input_source') or p.suffix in {'.json','.jsonl','.rpt','.bit','.bin','.tcl'}):
   copy(p,ORIGINAL/'runs'/fw_run.name/p.relative_to(fw_run))
 copy(fw_run/'status.json',ORIGINAL/'state/build/status.json')
 for item in manifest['resources']:copy(assets/item['path'],ORIGINAL/'release_assets'/item['path'])
 copy(assets/'release_manifest.json',ORIGINAL/'release_assets/release_manifest.json')
 evidence=ORIGINAL/'deliver/三敲与中止'
 for p in (ROOT/'docs/music15').rglob('*'):
  if p.is_file():copy(p,evidence/p.relative_to(ROOT/'docs/music15'))
 for name in ['三敲中止数字验证.json','三敲中止冻结验证.json','三敲中止运行验证.json']:
  copy(ROOT/'docs'/name,evidence/name)
 copy(exe,old)
 deployed={**candidate,'deployed_exe':str(old),'previous_version_directory':str(archive)}
 save(software/'软件版本.json',deployed);save(ORIGINAL/'state/portable_build.json',deployed)
 copy(ROOT/'docs/music15/使用说明.md',software/'使用说明.md')
 assert sha(ORIGINAL/'deliver/报告.pdf')==PDF_SHA
 record.update(status='deployed',previous_version_directory=str(archive),deployed_exe=str(old))
 save(evidence/'交付记录.json',record);save(ROOT/'state/music15_deployment.json',record)
 return record

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true')
 print(json.dumps(promote(p.parse_args().execute),ensure_ascii=False,indent=2))
