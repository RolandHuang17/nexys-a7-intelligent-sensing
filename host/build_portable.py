"""Build a self-contained Windows application with immutable, hashed resources."""
import json,shutil,sys,subprocess
from pathlib import Path
from audit import ROOT,Run,write_json,sha256,now
from app_paths import APP_VERSION

def build_legacy_assets():
    r=Run('build_portable');state=json.loads((ROOT/'state/build/status.json').read_text(encoding='utf8'))
    assert state['status']=='passed';fw_inputs=json.loads((ROOT/'runs'/state['run_id']/'build_inputs.json').read_text(encoding='utf8'))
    bit=ROOT/state['outputs'][0];assert sha256(bit)==state['bitstream_sha256']
    for x in fw_inputs['files']:assert sha256(ROOT/x['path'])==x['sha256']
    assets=ROOT/'release_assets';assets.mkdir(exist_ok=True)
    # Full local demo recordings are bundled; none are fetched at runtime.
    demo=assets/'music_demo';demo.mkdir(exist_ok=True)
    music_manifest=json.loads((ROOT/'music_demo/manifest.json').read_text(encoding='utf8'))
    for row in music_manifest['tracks']:
        src=ROOT/row['file'];dst=assets/row['file'];dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
    shutil.copy2(ROOT/'music_demo/manifest.json',demo/'manifest.json')
    shutil.copy2(ROOT/'music_demo/署名与用途.txt',demo/'署名与用途.txt')
    from music_store import MusicStore
    profile=MusicStore().setting('match_profile')
    if profile:write_json(assets/'music/default_match_profile.json',profile)
    from music_seed import stage_seed
    stage_seed(assets)
    if (ROOT/'config/music_selected_playlist.json').exists():shutil.copy2(ROOT/'config/music_selected_playlist.json',assets/'music/selected_playlist.json')
    (assets/'firmware').mkdir(exist_ok=True);shutil.copy2(bit,assets/'firmware/recorder_top.bit')
    for folder,source in [('tools/xc3sprog',ROOT/'upstream/portable/xc3sprog'),('tools/openocd',ROOT/'upstream/tools/openocd/bin'),
                           ('driver',ROOT/'upstream/portable/driver_setup')]:
        dest=assets/folder;dest.mkdir(parents=True,exist_ok=True)
        for p in source.iterdir():
            if p.is_file():shutil.copy2(p,dest/p.name)
    notices=assets/'licenses';notices.mkdir(exist_ok=True)
    shutil.copy2(ROOT/'upstream/portable/ftdi/ftd2xx.h',notices/'FTDI_original_license_and_header.txt')
    shutil.copy2(ROOT/'upstream/portable/source'/('xc3sprog-'+json.loads((ROOT/'upstream/portable/provenance.json').read_text())['xc3sprog_commit'])/'COPYING',notices/'xc3sprog_GPL.txt')
    (notices/'NOTICE.txt').write_text('NexysMonitor uses Python, Tk/Tcl, NumPy, Matplotlib, Pillow, pyserial, PyInstaller, xc3sprog (GPL-2.0-or-later), OpenOCD (GPL-2.0-or-later), libFTDI (LGPL) and libusb (LGPL). FTDI driver files remain unmodified, for use with FTDI devices only. Corresponding source archives, patches and build instructions are distributed with the reproduction package.\n',encoding='utf8')
    # Include full installed Python distribution license metadata where available.
    import importlib.metadata
    for name in ('numpy','matplotlib','pillow','pyserial','pyinstaller','scipy','requests','mutagen','psutil','docopt','joblib','imageio-ffmpeg'):
        dist=importlib.metadata.distribution(name)
        for f in dist.files or []:
            if any(t in str(f).lower() for t in ('license','copying','notice')) and dist.locate_file(f).is_file():
                target=notices/name/Path(f).name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dist.locate_file(f),target)
    shutil.copy2(ROOT/'upstream/music/audfprint/LICENSE',notices/'audfprint_MIT.txt')
    (notices/'music_and_ffmpeg.txt').write_text('Demo recordings retain author attribution in music_demo/署名与用途.txt. FFmpeg 7.1 binary from imageio-ffmpeg, GPL build; corresponding ffmpeg-7.1-source.tar.xz and upstream project archive are included in the reproduction package. No AudioTag key or local account configuration is bundled.\n',encoding='utf8')
    firmware={'build_run_id':state['run_id'],'build_id':fw_inputs['build_id'],'bitstream_sha256':state['bitstream_sha256'],
              'config_sha256':state['config_sha256'],'board_model':'Nexys A7-100T','target_part':'xc7a100tcsg324-1','protocol_version':1}
    rows=[{'path':p.relative_to(assets).as_posix(),'sha256':sha256(p),'bytes':p.stat().st_size}
          for p in sorted(assets.rglob('*')) if p.is_file() and p.name!='release_manifest.json']
    write_json(assets/'release_manifest.json',{'app_version':APP_VERSION,'built':now(),'run_id':r.run_id,'firmware':firmware,
        'resources':rows,'target_os':'Windows 10/11 x64','driver_version':'2.12.36.20',
        'driver_setup_sha256':sha256(assets/'driver/CDM2123620_Setup.exe'),'default_trigger_parameters_are_not_cross_board_calibrated':True})
    r.snapshot('独立EXE全部运行源码与固定版本资源清单')
    out=ROOT/'deliver/软件';out.mkdir(exist_ok=True)
    argv=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onefile','--windowed','--name','开发板实时监测',
          '--paths',ROOT/'host','--add-data',str(assets)+';release_assets','--distpath',out,
          '--workpath',ROOT/'.portable_build/pyinstaller','--specpath',ROOT/'scripts',
          '--hidden-import','matplotlib.backends.backend_tkagg','--paths',ROOT/'upstream/music/audfprint',
          '--hidden-import','audfprint_analyze','--hidden-import','audfprint_match','--hidden-import','hash_table',
          '--hidden-import','audio_read','--hidden-import','stft','--hidden-import','psutil','--hidden-import','scipy.io',
          '--exclude-module','librosa','--exclude-module','pymupdf',
          '--exclude-module','PyQt5','--exclude-module','PyQt6','--exclude-module','PySide2','--exclude-module','PySide6',
          '--exclude-module','pycaw','--exclude-module','comtypes','--exclude-module','pytest','--exclude-module','IPython',
          ROOT/'host/portable_main.py']
    rc,_=r.command(argv,'PyInstaller固定版本构建Windows单文件EXE',timeout=600);assert rc==0
    exe=out/'开发板实时监测.exe';record={'run_id':r.run_id,'app_version':APP_VERSION,'exe_sha256':sha256(exe),
        'exe_bytes':exe.stat().st_size,'firmware':firmware,'resource_manifest_sha256':sha256(assets/'release_manifest.json')}
    write_json(out/'软件版本.json',record);write_json(ROOT/'state/portable_build.json',record)
    r.event('single_exe_built',**record);r.manifest();print(json.dumps(record,ensure_ascii=False))

def build():
    from build_shazam_main import build as current_build
    return current_build()

if __name__=='__main__':build()
