"""Compile, export sources, recompile in delivery, and assemble evidence package."""
import argparse,json,shutil,sys
from pathlib import Path
from audit import ROOT,Run,sha256,write_json
from report_content import generate_content,read

TEX=r'C:/texlive/2026/bin/windows/latexmk.exe'

def report(draft=False):
    music_mode=(ROOT/'config/music_selected_playlist.json').exists()
    if music_mode and not draft:
        from music_evidence import load_round
        physical=load_round()
        regression_file=ROOT/'state/music_final_regression.json'
        if not physical or not physical['complete'] or not regression_file.exists() or not read(regression_file).get('passed'):
            raise RuntimeError('听歌识曲实板轮和最终回归尚未完成；使用 --draft 编译草稿，保留既有交付。')
    monitor_mode=(ROOT/'state/monitor_evidence.json').exists()
    monitor_evidence=read(ROOT/'state/monitor_evidence.json') if monitor_mode else None
    portable_mode=(ROOT/'state/portable_acceptance.json').exists()
    if monitor_mode:
        for stage in ('M3','M4','M5','monitor_regression'):
            if read(ROOT/'state'/stage/'status.json')['status']!='passed':raise RuntimeError(stage+' 尚未通过，保留旧交付')
    state=read(ROOT/'state/evaluate/status.json')
    if state['status']!='passed':raise RuntimeError('实板及同输入评价尚未通过，只保留设计草稿')
    run=Run('report');evaluation=ROOT/'runs'/state['run_id'];run.snapshot('基于通过的实际评价生成中文图文报告和离线复现包')
    try:
        source=generate_content(evaluation)
        if monitor_mode:
            from monitor_report_content import generate_monitor
            generate_monitor(run)
        if portable_mode:
            from portable_report_content import generate_portable
            generate_portable(run)
        if (ROOT/'report/visuals/style.tex').exists():
            from report_visuals import generate_visuals
            generate_visuals(run)
        if (ROOT/'host/music_report_content.py').exists() and (ROOT/'config/music_selected_playlist.json').exists():
            from music_report_content import generate
            generate(run)
        argv=[TEX,'-xelatex','-interaction=nonstopmode','-halt-on-error','-file-line-error','Experiment-template.tex']
        rc,text=run.command(argv,'工作目录按指定命令编译WHUExperiment报告',cwd=source,timeout=240)
        if rc:raise RuntimeError('报告源目录编译失败')
        if draft:
            run.event('draft_report_compiled',pdf='report/Experiment-template.pdf',pdf_sha256=sha256(source/'Experiment-template.pdf'),
                      final_delivery_updated=False)
            return 0
        deliver=ROOT/'deliver';deliver.mkdir(exist_ok=True)
        target=deliver/'报告源码';target.mkdir(exist_ok=True)
        for p in source.rglob('*'):
            if p.is_file() and p.suffix in ('.tex','.cls','.png','.jpg','.eps','.json','.md','.txt') or (p.is_file() and p.suffix=='.pdf' and p.parent.name=='figures'):
                if p.name.startswith('layout_check'):continue
                dest=target/p.relative_to(source);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
        rc,text=run.command(argv,'在交付源码目录再次编译，验证路径和依赖完整',cwd=target,timeout=240)
        if rc:raise RuntimeError('交付目录复编译失败')
        pdf=deliver/('报告_听歌识曲版.pdf' if music_mode else ('报告_图解增强版.pdf' if (ROOT/'report/visuals/style.tex').exists() else ('报告_独立软件版.pdf' if portable_mode else ('报告_多传感器版.pdf' if monitor_mode else '报告.pdf'))))
        try:shutil.copy2(target/'Experiment-template.pdf',pdf)
        except PermissionError:
            # A reader may hold the previously delivered PDF open on Windows.
            pdf=deliver/('报告_多传感器版_修订.pdf' if monitor_mode else '报告_易读版.pdf')
            shutil.copy2(target/'Experiment-template.pdf',pdf)
            run.event('alternate_pdf_path',reason='原PDF被阅读程序占用，保留旧文件并另存新版',path=pdf.relative_to(ROOT).as_posix())
        package=deliver/'复现实验';package.mkdir(exist_ok=True)
        omitted=[]
        private_names={'music_account_attestation.json','music_credentials.json','credentials.json'}
        accepted_bits={state['bitstream_sha256']}
        if monitor_mode:accepted_bits.add(monitor_evidence['bitstream_sha256'])
        if music_mode:
            accepted_bits.add(read(ROOT/'state/build/status.json')['bitstream_sha256'])
            for result in (ROOT/'runs').glob('*_music_microphone_development/result.json'):
                bit_hash=read(result).get('programming',{}).get('bitstream_sha256')
                if bit_hash:accepted_bits.add(bit_hash)
        selected_folders=('rtl','constraints','host','scripts','tests','config','state','docs','report','upstream')+ (('release_assets',) if portable_mode else ())+(('music_demo',) if music_mode else ())
        for name in selected_folders:
            for p in (ROOT/name).rglob('*'):
                if not p.is_file() or '__pycache__' in p.parts:continue
                if p.name in private_names or p.suffix in ('.sqlite3','.sqlite3-wal','.sqlite3-shm'):omitted.append(str(p.relative_to(ROOT)));continue
                if name=='report' and p.suffix not in ('.tex','.cls','.pdf','.png','.jpg','.eps','.json','.md','.txt'):continue
                if p.name.startswith('layout_check'):continue
                if name=='upstream' and p.suffix=='.zip':
                    # Baseline bit and published archive hash remain available; include official ZIP too for offline extraction.
                    pass
                dest=package/p.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
        # Keep all command logs, source snapshots and raw inputs; omit regenerable tool caches/checkpoints.
        for p in (ROOT/'runs').rglob('*'):
            if not p.is_file():continue
            rel=p.relative_to(ROOT);parts=p.relative_to(ROOT/'runs').parts
            if p.name in private_names or any(x in parts for x in ('.Xil','xsim.dir','__pycache__','music_user','canonical')) or p.suffix in ('.dcp','.wdb','.obj','.exe','.dll','.logstr','.pb','.sqlite3','.sqlite3-wal','.sqlite3-shm'):
                omitted.append(str(rel));continue
            if p.name=='.audit.lock':continue
            # Keep the versions actually used by the original, monitor and music evidence.
            if p.suffix=='.bit' and sha256(p) not in accepted_bits:omitted.append(str(rel));continue
            dest=package/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
        for name in ('run.ps1','monitor.ps1','README.md','requirements.txt'):
            shutil.copy2(ROOT/name,package/name)
        for p in ROOT.glob('requirements-*.txt'):shutil.copy2(p,package/p.name)
        if portable_mode:
            shutil.copy2(ROOT/'requirements-portable-build.txt',package/'requirements-portable-build.txt')
            copy=package/'software';copy.mkdir(exist_ok=True)
            for name in ('开发板实时监测.exe','软件版本.json','使用说明.md'):shutil.copy2(deliver/'软件'/name,copy/name)
        shutil.copy2(ROOT.parent/'声振事件记录仪执行规划.md',package/'原始执行规划.md')
        (package/'verify_hashes.py').write_text('import hashlib,json,pathlib\nr=pathlib.Path(__file__).parent\nrows=json.loads((r/"SHA256.json").read_text(encoding="utf8"))\nfor x in rows:\n p=r/x["path"]\n assert p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()==x["sha256"],x["path"]\nprint("PASS",len(rows),"files")\n',encoding='utf8')
        write_json(package/'omitted_regenerable_files.json',{'reason':'省略可重建工具缓存、未采用位流、账号配置和含在线任务凭据的数据库；原件保留在工作区。音乐原曲不封包，指纹由release_assets/music_seed提供。原始实板试次、失败日志及源码快照保留。',
            'accepted_bitstream_sha256':sorted(accepted_bits),'files':omitted})
        hashes=[{'path':p.relative_to(package).as_posix(),'sha256':sha256(p),'bytes':p.stat().st_size}
                for p in package.rglob('*') if p.is_file() and p.name!='SHA256.json']
        write_json(package/'SHA256.json',hashes)
        rc,text=run.command([sys.executable,package/'verify_hashes.py'],'离线复现包逐文件哈希复核',timeout=180)
        if rc:raise ValueError('交付哈希不一致')
        write_json(deliver/'交付索引.json',{'report_file':pdf.name,'report_sha256':sha256(pdf),'evaluation_run_id':evaluation.name,
            'source_directory':'报告源码','reproduction_directory':'复现实验','report_run_id':run.run_id,'files':len(hashes),
            'monitor_evidence':monitor_evidence,
            'portable_acceptance_run_id':read(ROOT/'state/portable_acceptance.json')['run_id'] if portable_mode else None,
            'visual_review':'pending; render and inspect every page before final acceptance'})
        run.status('M6_compile' if monitor_mode else 'report','passed' if monitor_mode else 'needs_user',
                   'PDF及交付源码复编译完成，接下来由助手逐页核验',
                   [str((deliver/'交付索引.json').relative_to(ROOT))], '渲染逐页检查；补封面信息后最终通过',
                   bitstream_sha256=monitor_evidence['bitstream_sha256'] if monitor_mode else state['bitstream_sha256'],
                   config_sha256=monitor_evidence['config_sha256'] if monitor_mode else state['config_sha256'],outputs=[pdf.relative_to(ROOT).as_posix()])
        return 0
    except Exception as error:
        run.event('report_failed',error=repr(error));run.status('report','failed',repr(error),[],'按日志修复后只重跑报告');raise
    finally:run.manifest();print('RUN_ID='+run.run_id)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--draft',action='store_true');args=parser.parse_args()
    raise SystemExit(report(draft=args.draft))
