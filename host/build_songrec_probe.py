"""Package only the standalone SongRec comparison tool, never board delivery."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

from songrec_probe import VERSION, SONGREC_VERSION, digest, now, write_json


def main():
    project = Path(__file__).resolve().parent.parent
    output = project / 'deliver/SongRec电脑麦克风对照'
    output.mkdir(parents=True, exist_ok=True)
    upstream = project / 'upstream/songrec/0.8.2'
    protected = ['deliver/软件/开发板实时监测.exe', 'deliver/报告.pdf', 'deliver/交付索引.json',
                 'release_assets/firmware/recorder_top.bit', 'deliver/电脑麦克风API测试/电脑麦克风API测试.exe']
    baseline_path = project / 'state/songrec_deployment_baseline.json'
    if not baseline_path.exists():
        write_json(baseline_path, {p: digest(project/p) for p in protected})
    baseline = json.loads(baseline_path.read_text(encoding='utf8'))
    args = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--windowed',
            '--name', '开始六项测试', '--paths', str(project/'host'), '--distpath', str(output),
            '--workpath', str(project/'.portable_build/songrec_probe'), '--specpath', str(project/'scripts'),
            '--exclude-module', 'matplotlib', '--exclude-module', 'scipy', '--exclude-module', 'pandas',
            '--exclude-module', 'pytest', '--exclude-module', 'IPython', '--exclude-module', 'serial',
            '--exclude-module', 'music_online', '--exclude-module', 'music_credentials',
            '--exclude-module', 'music_board', '--exclude-module', 'monitor_gui',
            str(project/'host/songrec_probe.py')]
    subprocess.run(args, check=True, cwd=project)
    shutil.copytree(upstream/'app', output/'SongRec', dirs_exist_ok=True)
    shutil.copy2(upstream/'LICENSE', output/'SongRec/LICENSE')
    shutil.copy2(upstream/'SongRec-0.8.2-source.zip', output/'SongRec/SongRec-0.8.2-source.zip')
    source = output/'源码'
    source.mkdir(exist_ok=True)
    for name in ('songrec_probe.py', 'songrec_probe_gui.py', 'pc_mic_capture.py', 'test_songrec_probe.py', 'build_songrec_probe.py'):
        shutil.copy2(project/'host'/name, source/name)
    provenance = {'project': 'https://github.com/marin-m/SongRec', 'version': SONGREC_VERSION,
                  'download_url': 'https://github.com/marin-m/SongRec/releases/download/0.8.2/SongRec-0.8.2-standalone.exe',
                  'archive_sha256': digest(upstream/'SongRec-0.8.2-standalone.exe'),
                  'source_archive_sha256': digest(upstream/'SongRec-0.8.2-source.zip'),
                  'native_exe_sha256': digest(output/'SongRec/songrec.exe'), 'license': 'GPL-3.0',
                  'source_at_version': 'https://github.com/marin-m/SongRec/tree/0.8.2',
                  'distribution': 'official standalone archive unpacked without changing native binaries'}
    write_json(output/'SongRec/来源与许可.json', provenance)
    manifest = {'app_version': VERSION, 'built_at': now(), 'songrec': provenance,
                'API_key_bundled': False, 'board_tools_bundled': False,
                'data_directory': '%LOCALAPPDATA%/SongRecMicTest', 'stage': 'SongRec_validation_before_ShazamIO',
                'gate': {'samples': 6, 'minimum_correct': 5, 'maximum_wrong': 0},
                'original_delivery_unchanged': all(digest(project/p) == h for p,h in baseline.items())}
    assert manifest['original_delivery_unchanged']
    write_json(output/'软件版本.json', manifest)
    files = {str(p.relative_to(output)).replace('\\', '/'): digest(p) for p in output.rglob('*')
             if p.is_file() and p.name != 'SHA256.json'}
    write_json(output/'SHA256.json', files)
    print(json.dumps({'output': str(output), 'exe_sha256': digest(output/'开始六项测试.exe'),
                      'files': len(files), 'protected_files_unchanged': True}, ensure_ascii=False))


if __name__ == '__main__':
    main()
