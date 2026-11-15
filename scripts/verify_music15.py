"""Bind 1.5 candidate, mocked host checks and existing source-exact XSim evidence.

This script does not program hardware, open UART, request an API or repeat a
physical guide. Invoke after the final candidate build and source UI smoke.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST_TESTS = (
    'test_panel_contracts.py', 'test_panel_host.py', 'test_music_shazam.py',
    'test_music_engine_cancel.py', 'test_music_cancel.py', 'test_music_board_cancel.py',
)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf8')


def bound_sources(result):
    """Reject historical evidence lacking at-run hashes or using changed files."""
    sources = result.get('sources')
    assert sources, 'Result has no at-run source hashes'
    for name, digest in sources.items():
        path = (ROOT / name).resolve()
        assert path.is_relative_to(ROOT), name
        assert sha(path) == digest, 'Changed XSim source: ' + name
    template = result.get('template_source')
    if template:
        assert sha(ROOT / template['path']) == template['sha256']


def select_result(pattern, condition):
    rejected = []
    for path in sorted((ROOT / 'runs').glob(pattern + '/result.json'), reverse=True):
        try:
            result = read(path)
            assert result.get('status') == 'passed' or result.get('passed') is True
            assert condition(result)
            bound_sources(result)
            return {'path': str(path), 'sha256': sha(path), 'result': result}
        except (AssertionError, OSError, ValueError, KeyError) as error:
            rejected.append({'path': str(path), 'reason': str(error)})
    raise AssertionError({'no_current_passed_result': pattern, 'rejected': rejected[:6]})


def candidate_binding(path):
    candidate = read(path)
    assert candidate['app_version'] == '1.5.0', 'Wait for the 1.5.0 candidate build'
    exe = Path(candidate['candidate_exe'])
    assert sha(exe) == candidate['exe_sha256']
    snapshot = Path(candidate['build_source_directory'])
    manifest = snapshot / 'source_manifest.json'
    assert sha(manifest) == candidate['source_manifest_sha256']
    for item in read(manifest):
        assert sha(ROOT / 'host' / item['path']) == item['sha256'], 'Candidate host differs: ' + item['path']
        assert sha(snapshot / 'host' / item['path']) == item['sha256']
    firmware = candidate['firmware']
    build = ROOT / 'runs' / firmware['build_run_id']
    status, inputs = read(build / 'status.json'), read(build / 'build_inputs.json')
    assert status['status'] == 'passed' and inputs['parameters']['MUSIC_MAX_SAMPLES'] == 160000
    assert inputs['build_id'] == firmware['build_id']
    assert sha(build / 'implementation/recorder_top.bit') == status['bitstream_sha256'] == firmware['bitstream_sha256']
    for item in inputs['files']:
        assert sha(ROOT / item['path']) == item['sha256'], 'Firmware source differs: ' + item['path']
    return candidate, {
        'candidate_metadata': str(path), 'candidate_metadata_sha256': sha(path),
        'host_source_manifest': str(manifest), 'host_source_manifest_sha256': sha(manifest),
        'firmware_build_inputs': str(build / 'build_inputs.json'),
        'firmware_build_inputs_sha256': sha(build / 'build_inputs.json'),
        'firmware_status': status,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, default=ROOT / 'state/shazam_main_candidate.json')
    parser.add_argument('--ui-result', type=Path, default=ROOT / 'runs/music15_ui_smoke/result.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/三敲中止数字验证.json')
    args = parser.parse_args()
    folder = ROOT / 'runs' / ('music15_digital_' + uuid.uuid4().hex[:10])
    folder.mkdir()
    try:
        candidate, binding = candidate_binding(args.candidate)
        tests = []
        for name in HOST_TESTS:
            path = ROOT / 'host' / name
            output = folder / (name + '.log')
            completed = subprocess.run([sys.executable, str(path), '-v'], cwd=ROOT,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
            output.write_bytes(completed.stdout)
            assert completed.returncode == 0, name + ': see ' + str(output)
            counts = re.findall(rb'Ran (\d+) tests? in', completed.stdout)
            assert counts, 'No unittest completion: ' + name
            tests.append({'test': name, 'status': 'passed', 'case_count': int(counts[-1]),
                          'test_sha256': sha(path), 'output': str(output), 'output_sha256': sha(output)})
        rtl = {
            'abort_and_full160000': select_result('*_test_music_abort_rtl', lambda r:
                r.get('abort_case_count') == 9 and r.get('existing_full_regression_passed') is True
                and r.get('existing_full160000_crc32') == 0x88d266ed
                and r.get('existing_prefix128000_crc32') == 0x42b6318a),
            'triple_600ms': select_result('*_test_music_triple_rtl', lambda r:
                r.get('case_count') == 11 and r.get('max_adjacent_gap_ms') == 600),
            'triple_1000ms': select_result('*_test_music_triple_rtl', lambda r:
                r.get('case_count') == 11 and r.get('max_adjacent_gap_ms') == 1000),
            'fir_and_half_capture': select_result('*_music_decimator_test', lambda r:
                r.get('bit_exact_samples') == 1024 and r['half_capture']['samples'] == 32
                and r['half_capture']['sample_rate'] == 8000 and r['half_capture']['overruns'] == 0),
            'old_double_diagnostics_600ms': select_result('*_test_music_tap', lambda r:
                'two taps never start capture' in r.get('cases', [])),
            'old_double_diagnostics_1000ms': select_result('*_music_tap_1000_boundary', lambda r:
                r.get('boundaries_ms') == [149, 150, 1000, 1001]),
            'quiet_integration': select_result('*_test_music_panel_quiet', lambda r:
                len(r.get('cases', [])) == 6 and r.get('samples') == 160000
                and r.get('pcm_crc32') == 0x88d266ed),
            'board_panel': select_result('*_test_board_panel_rtl', lambda r:
                r.get('case_count') == 21 and 'ready_triplepulse_and_words' in r.get('cases', [])),
        }
        # Generated 1000ms fixture must still derive exactly from the current
        # 600ms fixture; an old saved simulation file alone is insufficient.
        triple = (ROOT / 'tests/tb_music_triple.sv').read_text(encoding='utf8')
        triple = triple.replace("16'd600", "16'd1000").replace('boundary(600,600,1)', 'boundary(1000,1000,1)')
        triple = triple.replace('boundary(601,150,0)', 'boundary(1001,150,0)').replace('boundary(150,601,0)', 'boundary(150,1001,0)')
        derived = [ROOT / p for p in rtl['triple_1000ms']['result']['sources'] if p.endswith('tb_music_triple1000.sv')]
        assert len(derived) == 1 and derived[0].read_text(encoding='utf8') == triple
        ui = read(args.ui_result)
        assert ui.get('status') == 'passed' and ui['app_version'] == candidate['app_version']
        assert ui['checks'] and all(value is True for value in ui['checks'].values())
        ui_sources = ui['runtime_source_sha256']
        assert ui_sources, 'UI smoke must identify its actual source files'
        manifest = {item['path']: item['sha256'] for item in read(Path(candidate['build_source_directory']) / 'source_manifest.json')}
        for name, digest in ui_sources.items():
            relative = Path(name.replace('\\', '/'))
            if relative.is_absolute():
                relative = relative.relative_to(ROOT)
            assert relative.parts[0] == 'host', 'Unexpected UI source: ' + name
            assert sha(ROOT / relative) == digest == manifest[Path(*relative.parts[1:]).as_posix()]
        candidate_after, binding_after = candidate_binding(args.candidate)
        assert candidate_after == candidate and binding_after == binding, 'Candidate changed during verification'
        report = {
            'status': 'passed', 'time': datetime.now().astimezone().isoformat(),
            'app_version': candidate['app_version'], 'exe_sha256': candidate['exe_sha256'],
            'firmware': candidate['firmware'], 'kind': 'digital_and_candidate_source_Tk_not_physical',
            'hardware_used': False, 'serial_opened': False, 'network_requests': 0,
            'physical_knock_detection_measured': False, 'api_hit_rate_measured': False,
            'scope': {
                'host': '真实业务方法以 spy/mock 验证三敲等待、中止双确认、过期结果丢弃；不证明实板时序或在线命中率。',
                'rtl': 'XSim 运行真实 RTL；三敲在原检测器的已注册 tap_pulse 边界注入，原加速度检测器另用数字 XYZ 验证；不代表真人敲击结果。',
                'full_pcm': '完整160000点与128000点前缀 CRC 保持既有黄金值；1024点 FIR、半速采样与旧 double_seq 边界均通过。',
                'ui': '真实源码 Tk 窗口检查，并以源码 SHA 绑定候选打包快照；这不是冻结 EXE 截图或实体设备检查，具体步骤见 UI smoke 原始报告。',
            },
            'checks': {'host_unit_tests': True, 'source_contracts': True, 'source_exact_xsim': True,
                       'legacy_signal_and_crc_regressions': True, 'candidate_source_ui_smoke': True,
                       'candidate_host_sources_exact': True, 'firmware_inputs_exact': True},
            'binding': binding, 'host_tests': tests, 'host_case_count': sum(t['case_count'] for t in tests),
            'rtl': rtl, 'ui_smoke': {'path': str(args.ui_result), 'sha256': sha(args.ui_result), 'result': ui},
            'verifier_sha256': sha(Path(__file__)), 'result_directory': str(folder),
        }
        save(folder / 'result.json', report)
        save(args.output, report)
        print(json.dumps({'status': 'passed', 'exe_sha256': report['exe_sha256'],
                          'host_case_count': report['host_case_count'], 'result': str(folder / 'result.json')}, ensure_ascii=False))
    except Exception as error:
        save(folder / 'result.json', {'status': 'failed', 'time': datetime.now().astimezone().isoformat(),
                                    'error': str(error), 'hardware_used': False, 'network_requests': 0})
        raise


if __name__ == '__main__':
    main()
