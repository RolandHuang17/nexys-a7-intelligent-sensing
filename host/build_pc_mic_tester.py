"""Build the additional PC microphone tester without board firmware or tools."""
import sys,json,shutil
from pathlib import Path
from audit import ROOT,Run,sha256,write_json,now
from pc_mic_backend import PC_MIC_VERSION


def main():
    run=Run('build_pc_mic_tester');run.snapshot('新增独立电脑麦克风API对照，不改开发板EXE、位流和原正式封存')
    output=ROOT/'deliver/电脑麦克风API测试';output.mkdir(exist_ok=True)
    args=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onefile','--windowed',
        '--name','电脑麦克风API测试','--paths',ROOT/'host','--distpath',output,
        '--workpath',ROOT/'.portable_build/pc_mic','--specpath',ROOT/'scripts',
        '--exclude-module','matplotlib','--exclude-module','pandas','--exclude-module','pytest',
        '--exclude-module','IPython','--exclude-module','PyQt5','--exclude-module','PyQt6',
        '--exclude-module','PySide6','--exclude-module','serial','--exclude-module','music_library',
        '--exclude-module','music_board','--exclude-module','monitor_gui','--exclude-module','portable_program',
        ROOT/'host/pc_mic_tester.py']
    code,_=run.command(args,'隔离环境构建无开发板资源的电脑麦克风单EXE',timeout=600);assert code==0
    exe=output/'电脑麦克风API测试.exe'
    modules=['pc_mic_tester.py','pc_mic_capture.py','pc_mic_backend.py','music_online.py','music_upload.py','music_credentials.py','music_store.py']
    record={'run_id':run.run_id,'version':PC_MIC_VERSION,'built':now(),'exe_sha256':sha256(exe),'exe_bytes':exe.stat().st_size,
        'source_modules':[{'path':'host/'+name,'sha256':sha256(ROOT/'host'/name)} for name in modules],
        'board_firmware_or_JTAG_tools_bundled':False,'API_key_bundled':False,'API':'existing local Windows credential, free only',
        'default_input':'Windows microphone, 16000 Hz mono PCM16','default_seconds':20,'upload':'same board-side host preparation, 8000 Hz mono PCM16'}
    write_json(output/'软件版本.json',record);write_json(run.path/'result.json',record)
    source=output/'源码';source.mkdir(exist_ok=True)
    for name in modules+['app_paths.py','audit.py']:shutil.copy2(ROOT/'host'/name,source/name)
    shutil.copy2(ROOT/'host/build_pc_mic_tester.py',source/'build_pc_mic_tester.py')
    run.manifest();print(json.dumps(record,ensure_ascii=False))


if __name__=='__main__':main()
