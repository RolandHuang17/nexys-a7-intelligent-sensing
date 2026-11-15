"""Bind digital regression evidence to the exact 1.4 candidate; no hardware/API."""
import hashlib,json,subprocess,sys,uuid
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def read(path):return json.loads(Path(path).read_text(encoding='utf8'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')

def main():
    candidate=read(ROOT/'state/shazam_main_candidate.json');exe=Path(candidate['candidate_exe'])
    assert candidate['app_version']=='1.4.0' and sha(exe)==candidate['exe_sha256']
    folder=ROOT/'runs'/('panel_digital_'+uuid.uuid4().hex[:10]);folder.mkdir()
    tests=[]
    for name in ('test_panel_contracts.py','test_panel_host.py','test_music_shazam.py'):
        path=ROOT/'host'/name
        result=subprocess.run([sys.executable,str(path),'-v'],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        (folder/(name+'.log')).write_bytes(result.stdout)
        assert result.returncode==0,name
        tests.append({'test':name,'status':'passed','test_sha256':sha(path),'output':str(folder/(name+'.log'))})
    panel=read(ROOT/'state/board_panel_rtl.json');assert panel['status']=='passed'
    for name,digest in panel['sources'].items():assert sha(ROOT/name)==digest,name
    quiet=read(ROOT/'state/music_panel_quiet.json');assert quiet['status']=='passed'
    for name,digest in quiet['sources'].items():assert sha(ROOT/name)==digest,name
    old_runs={
        'full_pcm_crc':'20261115T182922_178793_test_music_rtl',
        'fir':'20261115T182939_261054_music_decimator_test',
        'tap':'20261115T183058_378383_test_music_tap',
        'tap_1000':'20261115T183122_945840_music_tap_1000_boundary',
        'monitor':'20261115T183031_167163_digital_monitor',
    }
    results={k:read(ROOT/'runs'/v/'result.json') for k,v in old_runs.items()}
    assert results['full_pcm_crc']['samples']==160000 and results['full_pcm_crc']['shared_golden_frames']
    assert results['fir']['passed'] and results['fir']['bit_exact_samples']==1024
    assert results['tap']['passed'] and results['tap_1000']['passed']
    assert set(results['monitor']['passed'])=={'gpio_monitor','i2c_register','monitor_core'}
    snapshot=Path(candidate['build_source_directory'])
    for item in read(snapshot/'source_manifest.json'):
        assert sha(ROOT/'host'/item['path'])==item['sha256'],'Host source differs from candidate: '+item['path']
    inputs=read(ROOT/'runs'/candidate['firmware']['build_run_id']/'build_inputs.json')
    for item in inputs['files']:assert sha(ROOT/item['path'])==item['sha256']
    ui_path=ROOT/'runs/panel_simple_ui_smoke_02/result.json'
    ui=read(ui_path);assert all(ui['checks'].values())
    report={'status':'passed','time':datetime.now().astimezone().isoformat(),
        'exe_sha256':sha(exe),'app_version':'1.4.0','firmware_build_id':candidate['firmware']['build_id'],
        'kind':'digital_and_source_contracts_not_physical','hardware_used':False,'network_requests':0,
        'checks':{'host_unit_tests':True,'source_contracts':True,'panel_xsim':True,'legacy_rtl_regressions':True,
                  'ui_smoke':True,'candidate_host_sources_exact':True,'firmware_inputs_exact':True},
        'host_tests':tests,'panel':panel,'quiet_integration':quiet,'legacy_results':results,'legacy_runs':old_runs,
        'ui_smoke':ui,'ui_smoke_path':str(ui_path),'result_directory':str(folder)}
    for path in (folder/'result.json',ROOT/'docs/板载面板数字验证.json'):save(path,report)
    print(json.dumps({'status':'passed','exe_sha256':report['exe_sha256'],'result':str(folder/'result.json')},ensure_ascii=False))

if __name__=='__main__':main()
