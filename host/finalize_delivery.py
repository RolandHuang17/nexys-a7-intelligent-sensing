"""Seal a visually reviewed PDF and its reproducibility evidence without new measurements."""
import json,shutil,sys
from pathlib import Path
import pymupdf
from audit import ROOT,Run,sha256,write_json,now

def read(p):return json.loads(Path(p).read_text(encoding='utf8'))

def finalize(render_id):
    deliver=ROOT/'deliver';package=deliver/'复现实验';run=Run('final_acceptance')
    index=read(deliver/'交付索引.json');pdf=deliver/'报告.pdf';pdf_hash=sha256(pdf)
    rendered=ROOT/'runs'/render_id
    log=[json.loads(x) for x in (rendered/'actions.jsonl').read_text(encoding='utf8').splitlines()]
    assert any(x['kind']=='pdf_rendered' and x['sha256']==pdf_hash for x in log),'Review must apply to the final PDF bytes'
    doc=pymupdf.open(pdf);assert len(doc)==25
    text='\n'.join(p.get_text() for p in doc)
    for phrase in ('黄玉成','2022302111419','武小平','嵌入式系统','系统功能详细分析','硬件模块框图','系统软件设计思想','核心技术要点','0.571','0.750'):
        assert phrase in text,phrase
    assert '待补充' not in text
    for page in doc:
        assert all(x0>=-.5 and y0>=-.5 and x1<=page.rect.width+.5 and y1<=page.rect.height+.5
                   for x0,y0,x1,y1,*_ in page.get_text('words')),'text beyond page boundary'
    compile_log=(ROOT/'report/Experiment-template.log').read_text(errors='replace')
    assert all(s not in compile_log for s in ('Overfull','Undefined control sequence','Missing character','undefined references'))
    assert pdf_hash==sha256(deliver/'报告源码/Experiment-template.pdf')
    provenance=read(ROOT/'report/template_provenance.json')
    for row in provenance['unchanged_files']:
        assert sha256(deliver/'报告源码'/row['file'])==row['sha256']
    for name in ('doctor','A0','A1a','A1b','A2','A3','build','collect','evaluate','pressure'):
        assert read(ROOT/'state'/name/'status.json')['status']=='passed',name
    result=read(ROOT/'runs'/index['evaluation_run_id']/'results.json')
    assert result['board_reference_windows']==4500 and result['live_verified'] and result['single_modes_verified']
    audit_run='20261113T234758_039461_independent_acceptance_audit'
    independent=read(ROOT/'runs'/audit_run/'audit.json');assert independent['physical_events_crc_and_wav_verified']==33
    review={'time':now(),'pdf_sha256':pdf_hash,'pages':25,'render_run_id':render_id,
            'visually_reviewed_pages':list(range(1,26)),'detail_zoom_pages':[1,7,14,17,19],
            'checks':['中文封面及校徽','目录页码及交叉引用','硬件接口图标签和引脚表','LIVE与弱响应/纯声图及来源哈希',
                      '留出混淆矩阵和分母','真实在线与60秒计数','布线100MHz/五路输出约束','无超行、缺字、未定义引用、页面外文字'],
            'independent_data_audit_run_id':audit_run,'physical_events_verified':33,
            'collection_run_id':result['collection_run_id'],'evaluation_run_id':index['evaluation_run_id'],
            'bitstream_sha256':result['bitstream_sha256'],'holdout':{k:v['metrics'] for k,v in result['holdout'].items()},
            'quiet60':result['quiet60'],'limitations':['麦克风实物物料与装配子修订尚未辨认','加速度绝对尺度未标定',
            '未测声压/精确物理延迟及示波器引脚时序','样本小且联合召回低，泛化性能待验证','官方回放未做耳机试听']}
    write_json(deliver/'验收记录.json',review);write_json(run.path/'review.json',review)
    report_run=Run('report',index['report_run_id'])
    report_run.event('visual_review_completed',**review)
    evidence=['deliver/验收记录.json','deliver/交付索引.json']
    report_run.status('report','passed','指定WHUExperiment中文25页报告，交付目录复编译与逐页核验通过',evidence,'已交付',
                      bitstream_sha256=result['bitstream_sha256'],config_sha256=read(ROOT/'state/evaluate/status.json')['config_sha256'],
                      outputs=['deliver/报告.pdf','deliver/报告源码','deliver/复现实验'])
    run.status('E','passed','同批4500窗板端/独立参考、33份原始事件校验、静置与LIVE及协议压力证据齐全',evidence,'已交付')
    run.status('experiment_flow','passed','自动报告首次排版错误已修复，最终报告与复现包验收通过',evidence,'已交付')
    write_json(ROOT/'state/experiment_flow.json',{'pid':None,'state':'complete','final_acceptance_run_id':run.run_id})
    resume=read(ROOT/'state/resume.json');resume.update(execution_state='complete',completed=now(),requires_rebuild=False,
        formal_collection_started=True,final_deliverables_complete=True,final_acceptance_run_id=run.run_id,delivery_index='deliver/交付索引.json')
    write_json(ROOT/'state/resume.json',resume)
    write_json(ROOT/'state/active_checkpoint.json',{'execution_state':'complete','completed':now(),'delivery_index':'deliver/交付索引.json','final_acceptance_run_id':run.run_id})
    completed=('## 最终节点：已完成并交付\n\n详见 `deliver/交付索引.json` 与 `deliver/验收记录.json`。25页中文报告、可重编源码和离线复现包已验证。'
       '真实采样232625会话30试次及3个自动事件；板端4500窗一致；联合留出TP2/FP0/FN3、F1=0.571，振动F1=0.750；'
       '60.154秒无联合确认。最终位流34918c...，构建b247b381、100MHz WNS0.173ns。不得据此声称联合策略最优。'
       '已有工作无需重跑；新增场景或阈值改进另建开发/独立留出与LIVE运行。\n\n')
    p=ROOT/'docs/CONTINUE.md';p.write_text(completed+p.read_text(encoding='utf8'),encoding='utf8')
    summary='''# 交付与复现说明

报告已按指定WHUExperiment模板交付，封面为计算机科学与技术/黄玉成/2022302111419/武小平/嵌入式系统。
原工作区交付目录：`D:\\projects\\2222wuxiaoping_codex\\nexys-event-recorder\\deliver`。

- 报告：`报告.pdf`，25页；可编译源码：`报告源码/Experiment-template.tex`。
- 实验：`复现实验/`，含源码、位流、原始数据、失败日志、源码快照、离线wheel和OpenOCD。
- 中文复现步骤见实验包内 `docs/复现说明.md`，文件核对运行 `python verify_hashes.py`。
- 30个对照试次、33份实体事件的CRC/WAV均已验证，4500窗板端回放与独立参考一致。
- 联合留出：TP2、FP0、TN10、FN3，Precision1.000、Recall0.400、F1=0.571；振动单路F1=0.750。
- 连续安静60.154秒：联合确认0；LIVE真实自动事件38可播放并对齐，声振上穿相差10ms。
- 真实记录 `runs/20261113T232625_950296_collect/physical/`；LIVE录音为 `LIVE_event38/audio.wav`。

报告完整展开功能可行性、硬件模块与接口、软件框架流程、核心技术，并保留弱响应、漏检及失败修复。
未验证项：实际麦克风物料/装配子修订、加速度绝对标定、声压/精确物理时延/示波器电气验收，以及跨场景泛化；官方基线没有耳机试听证据。
内部布线100MHz WNS0.173ns/TNS0，五路串行输出20ns传播约束均真正生效；测量位流34918c849baa72bff90249738707d6a996f298667e79a0cd2a36da6533e41ec1。

重新编译报告：在报告源码目录运行 `latexmk -xelatex -interaction=nonstopmode -halt-on-error -file-line-error Experiment-template.tex`。
报告源码/校徽/图片均已包含；环境需预装TeX Live 2026和中文字体。硬件重建需Vivado 2026.1；Python依赖可用 `scripts/bootstrap.ps1` 离线安装。
最终SHA256清单只覆盖本次封存的文件快照；封存后的校验命令回执在交付根目录的验收记录和索引中，避免校验日志自引用。
'''
    (ROOT/'docs/交付说明.md').write_text(summary,encoding='utf8')
    (deliver/'使用说明.md').write_text(summary,encoding='utf8')
    run.snapshot('最终实板与报告验收节点，封面信息齐全，逐页核验和独立计数核对完成')
    # Update closure evidence in the immutable delivery snapshot.
    for folder in ('host','scripts','docs','state','config'):
        for p in (ROOT/folder).rglob('*'):
            if not p.is_file() or '__pycache__' in p.parts:continue
            q=package/p.relative_to(ROOT);q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,q)
    for folder in (run.path,report_run.path,ROOT/'runs'/audit_run,rendered):
        for p in folder.rglob('*'):
            if p.is_file():
                q=package/p.relative_to(ROOT);q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,q)
    shutil.copy2(ROOT/'runs/actions.jsonl',package/'runs/actions.jsonl')
    (package/'docs/交付说明.md').write_text(summary,encoding='utf8')
    write_json(package/'final_acceptance.json',review)
    hashes=[{'path':p.relative_to(package).as_posix(),'sha256':sha256(p),'bytes':p.stat().st_size}
            for p in sorted(package.rglob('*')) if p.is_file() and p.name!='SHA256.json']
    write_json(package/'SHA256.json',hashes)
    rc,output=run.command([sys.executable,package/'verify_hashes.py'],'封存后复现包全部文件SHA-256复核',timeout=180)
    assert rc==0,'delivery hash verification failed'
    index.update(report_sha256=pdf_hash,visual_review='passed: all 25 pages',acceptance_record='验收记录.json',
                 final_acceptance_run_id=run.run_id,files=len(hashes),reproduction_manifest_sha256=sha256(package/'SHA256.json'),
                 package_hash_verification='passed',data_snapshot_completed=now())
    write_json(deliver/'交付索引.json',index)
    review.update(reproduction_manifest_sha256=index['reproduction_manifest_sha256'],package_hash_verification='passed',files=len(hashes))
    write_json(deliver/'验收记录.json',review)
    run.status('delivery','passed','最终PDF/源码复编译、25页逐页检查、全部复现文件哈希通过',evidence,'完成')
    run.manifest();print(json.dumps({'acceptance_run_id':run.run_id,'pdf_sha256':pdf_hash,'pages':25,'files':len(hashes)},ensure_ascii=False))

if __name__=='__main__':finalize(sys.argv[1])
