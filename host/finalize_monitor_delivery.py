"""Seal the monitor extension after physical checks and human PDF inspection.

Verification receipts stay outside the frozen package to avoid self-reference.
No measurements or firmware are generated or changed here.
"""
import csv
import json
from pathlib import Path
import shutil
import sys
import wave
import zlib

import pymupdf
from audit import ROOT, Run, now, sha256, write_json


def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def check_event(directory, bit_hash=None):
    directory=Path(directory)
    m=read(directory/'metadata.json'); payload=(directory/'payload.bin').read_bytes()
    assert len(payload)==m['payload_length']==48000+10*m['xyz_count']
    assert zlib.crc32(payload)==m['payload_crc32']
    assert sha256(directory/'payload.bin')==m['input_hash']
    with wave.open(str(directory/'audio.wav'),'rb') as w:
        assert (w.getnchannels(),w.getsampwidth(),w.getframerate(),w.getnframes())==(1,2,16000,24000)
        assert w.readframes(24000)==payload[:48000]
    with (directory/'xyz.csv').open(encoding='utf8') as f:
        rows=list(csv.DictReader(f))
    assert len(rows)==m['xyz_count']
    if bit_hash:
        assert m['programming']['bitstream_sha256']==bit_hash
    return {'directory':directory.relative_to(ROOT).as_posix(),'event_id':m['event_id'],
            'input_hash':m['input_hash'],'pcm_count':m['pcm_count'],'xyz_count':m['xyz_count'],
            'crc32':m['payload_crc32'],'mode':m['mode']}


def copy_tree(source, target, predicate=lambda p: True):
    for p in source.rglob('*'):
        if p.is_file() and '__pycache__' not in p.parts and predicate(p):
            q=target/p.relative_to(source);q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,q)


def finalize(render_id):
    run=Run('monitor_delivery_acceptance')
    deliver=ROOT/'deliver';package=deliver/'复现实验'
    index=read(deliver/'交付索引.json');evidence=read(ROOT/'state/monitor_evidence.json')
    pdf=deliver/index['report_file'];pdf_hash=sha256(pdf);rendered=ROOT/'runs'/render_id
    visual=read(rendered/'visual_review.json');doc=pymupdf.open(pdf);pages=len(doc)
    run.event('acceptance_started',pdf_sha256=pdf_hash,render_run_id=render_id)
    assert visual['pdf_sha256']==pdf_hash
    assert visual['visually_reviewed_pages']==list(range(1,pages+1))
    assert len(visual['reviewed_images'])==pages
    for row in visual['reviewed_images']:
        assert sha256(rendered/row['path'])==row['sha256']
    assert any(x['kind']=='pdf_rendered' and x['sha256']==pdf_hash for x in
               [json.loads(s) for s in (rendered/'actions.jsonl').read_text(encoding='utf8').splitlines()])
    text='\n'.join(p.get_text() for p in doc)
    for phrase in ('黄玉成','2022302111419','武小平','嵌入式系统','系统功能详细分析','硬件模块框图',
                   '系统软件设计思想','核心技术要点','0.571','0.750','f4e259e1','b247b381','ADT7420','XADC'):
        assert phrase in text,phrase
    assert '待补充' not in text
    for page in doc:
        assert all(x0>=-.5 and y0>=-.5 and x1<=page.rect.width+.5 and y1<=page.rect.height+.5
                   for x0,y0,x1,y1,*_ in page.get_text('words')),'Text outside page'
    for folder in (ROOT/'report',deliver/'报告源码'):
        log=(folder/'Experiment-template.log').read_text(errors='replace')
        assert all(s not in log for s in ('Overfull','Undefined control sequence','Missing character','undefined references'))
    assert sha256(deliver/'报告源码/Experiment-template.pdf')==pdf_hash
    for row in read(ROOT/'report/template_provenance.json')['unchanged_files']:
        assert sha256(deliver/'报告源码'/row['file'])==row['sha256']
    for stage in ('M0','M1','M2','M3','M4','M5','monitor_regression','M6_compile'):
        assert read(ROOT/'state'/stage/'status.json')['status']=='passed',stage
    build=ROOT/'runs'/evidence['build_run_id'];inputs=read(build/'build_inputs.json')
    assert sha256(build/'implementation/recorder_top.bit')==evidence['bitstream_sha256']
    for row in inputs['files']:
        assert sha256(ROOT/row['path'])==row['sha256'],row['path']
    probe=read(ROOT/'runs'/evidence['probe_run_id']/'result.json')
    regression=read(ROOT/'runs'/evidence['regression_run_id']/'result.json')
    for result in (probe,regression):
        assert result['programming']['bitstream_sha256']==evidence['bitstream_sha256']
        assert result['programming']['config_sha256']==evidence['config_sha256']
    assert regression['snapshot_peak_hz']==1500 and regression['board_reference_windows']==300
    assert regression['echo_512_passed'] and regression['bad_crc_injected_and_rejected']
    physical=ROOT/'runs'/evidence['physical_gui_session'];guide=read(physical/'physical_guide.json')
    assert guide['stage']==4 and guide['high']==guide['low']==65535 and guide['press']==guide['release']==31
    measured=read(ROOT/'report/generated/monitor_measured_values.json')
    assert measured['summary']['last']['overruns']==0
    events=[check_event(ROOT/e['directory'],evidence['bitstream_sha256'])
            for e in measured['summary']['exported_events']]
    assert len(events)==2 and all(e['mode']==3 for e in events)
    # Also check the final GUI's manual export and the independent tone capture.
    extra=[]
    for base in (ROOT/'runs'/evidence['final_gui_session']/'physical',ROOT/'runs'/evidence['regression_run_id']/'physical'):
        for p in base.rglob('metadata.json'):
            extra.append(check_event(p.parent))
    assert any(e['mode']==0 for e in extra)
    for figure in read(ROOT/'report/generated/monitor_figure_index.json'):
        for p in figure['inputs']:assert sha256(ROOT/p['path'])==p['sha256']
        if 'script' in figure:assert sha256(ROOT/figure['script'])==figure['script_sha256']
    claim=read(ROOT/'report/generated/claim_index.json')
    old_claim=read(ROOT/'runs/20261114T002057_834973_plain_language_revision/previous_delivery/报告源码/generated/claim_index.json')
    for key in ('collection_run_id','evaluation_run_id','result_sha256','frozen_config_sha256','bitstream_sha256'):
        assert claim[key]==old_claim[key],key
    assert [r['input_hash'] for r in claim['figures']]==[r['input_hash'] for r in old_claim['figures']]
    assert sha256(ROOT/'runs'/claim['evaluation_run_id']/'results.json')==claim['result_sha256']
    assert read(ROOT/'state/monitor_gui.json')['state']=='closed','Close acquisition before freezing package'
    before=run.path/'previous_checkpoints';before.mkdir()
    for p in (ROOT/'state/resume.json',ROOT/'state/active_checkpoint.json',ROOT/'docs/CONTINUE.md',
              ROOT.parent/'项目暂停与恢复节点.md'):
        shutil.copy2(p,before/p.name)
    review={'time':now(),'pdf_sha256':pdf_hash,'pages':pages,'render_run_id':render_id,
            'visually_reviewed_pages':visual['visually_reviewed_pages'],'detail_zoom_pages':visual['detail_zoom_pages'],
            'checks':visual['checks']+['交付目录重新编译通过','WHU模板与校徽版本校验通过','当前RTL与实测位流构建输入一致',
                '全部普通开关、方向按键、倾斜及自动事件检查通过','新事件CRC、WAV及输入SHA校验通过',
                '新板端300窗与独立参考一致','原版三策略结果及图表输入未改变'],
            'monitor_evidence':evidence,'new_joint_events':events,'additional_exports':extra,
            'digital_run_id':read(ROOT/'state/M1/status.json')['run_id'],
            'historical_trigger_metrics_bitstream_sha256':claim['bitstream_sha256'],
            'remaining_verifications':evidence['limitations']+['麦克风实际物料及D.2/D.3装配子修订未辨认',
                '官方基线未进行耳机试听','倾角、加速度和物理时延未作外部仪表标定','原联合触发轻敲漏检仍待改进']}
    write_json(run.path/'review.json',review);write_json(deliver/'验收记录.json',review)
    report_run=Run('report',index['report_run_id']);report_run.event('monitor_visual_acceptance',**review);report_run.manifest()
    # The old report.pdf may be open in a reader. Keep a clear current filename regardless.
    canonical=deliver/'报告.pdf'
    try:
        if canonical.exists() and sha256(canonical)!=pdf_hash:
            shutil.copy2(canonical,run.path/'previous_report.pdf')
        shutil.copy2(pdf,canonical)
        index['canonical_report_file']='报告.pdf'
        run.event('canonical_pdf_updated',sha256=pdf_hash)
    except PermissionError:
        run.event('canonical_pdf_locked',current_report=pdf.name,reason='阅读器占用旧文件，使用明确的新版本文件名')
    usage=(f'# 交付与使用说明\n\n当前报告：`{pdf.name}`，共 {pages} 页。封面为计算机科学与技术 / 黄玉成 / 2022302111419 / 武小平 / 嵌入式系统。\n\n'
        '## 打开实时界面\n\n在工程目录运行 `.\\monitor.ps1`；重新上电后用 `.\\monitor.ps1 -Program` 下载到 SRAM。'
        '下载会清空板内未导出的临时事件。普通连接保留它们。详细操作见 `docs/实时监测使用说明.md`。\n\n'
        '声音和频谱、XYZ、板载与芯片温度、三路内部电压、ADXL362温度原始值、16开关、5方向按键均已接入。'
        '原有手动与三种自动触发、事件录音、波形查看继续可用。\n\n'
        '## 实板验收\n\n全部16开关两种状态、5按键按下释放和倾斜响应已检查。新增两段联合自动事件均为24000点声音、279组XYZ，CRC、WAV与SHA核对通过。'
        '1500 Hz短音实测主峰1500 Hz，新版本300窗板端回放与独立参考一致。100 MHz布局布线WNS0.045 ns，TNS0。\n\n'
        '旧版30试次和4500窗对照保留原位流归属；联合F1=0.571，振动单路F1=0.750。新增监测界面没有据此宣称触发准确率提升。\n\n'
        '## 文件与复现\n\n- `报告源码/Experiment-template.tex`：可重新编译的WHUExperiment工程。\n'
        '- `复现实验/`：RTL、位流、宿主程序、原始数据、失败记录、版本快照、离线Python依赖和重建说明。\n'
        '- `交付索引.json`、`验收记录.json`：实测来源、当前版本和最终哈希。\n\n'
        '在报告源码目录运行 `latexmk -xelatex -interaction=nonstopmode -halt-on-error -file-line-error Experiment-template.tex`。'
        '环境需TeX Live 2026和中文字体。硬件重建需Vivado 2026.1。实验包中用 `scripts/bootstrap.ps1` 安装离线Python依赖，'
        '用 `python verify_hashes.py` 校验封存快照。详见包内 `docs/复现说明.md`。\n\n'
        '## 目前的限制\n\n预览存在缺口，不能当作连续无损录音；完整事件另行存储并校验。温度、电压、倾角和声压尚未作外部仪表标定。'
        'ADXL362内部温度只显示原始值。板载温度与芯片温度不等同精确室温。原联合触发对轻敲的漏检仍待改进，'
        '新版本没有重新采集独立留出组。麦克风物料和装配子修订仍未辨认，官方基线没有耳机试听证据。\n\n'
        '旧版PDF保留为历史。封存后再次打开界面会产生新的运行目录，不改变本次报告和实验包。校验回执位于封存快照外，避免日志自引用。\n')
    (ROOT/'docs/交付说明.md').write_text(usage,encoding='utf8');(deliver/'使用说明.md').write_text(usage,encoding='utf8')
    checkpoint=(f'# 最新节点：实时监测扩展已验收（{now()}）\n\n'
        f'当前交付为 `deliver/{pdf.name}`（{pages}页）、`deliver/报告源码/`、`deliver/复现实验/`。'
        f'最终验收运行：`{run.run_id}`。详见 `deliver/交付索引.json` 和 `deliver/验收记录.json`。\n\n'
        '已有实板验证和采样不需要重做。普通使用运行 `.\\monitor.ps1`；断电后用 `.\\monitor.ps1 -Program`。'
        f'当前实测构建 `{inputs["build_id"]}`、位流 `{evidence["bitstream_sha256"]}`。'
        '预览缺口和未标定项目已写入报告。以后新增采样另建运行目录，保留封存包。\n\n'
        '下文为历史记录；其中旧的暂停和待执行指令已经完成，不作为当前恢复任务。\n\n')
    for p in (ROOT/'docs/CONTINUE.md',ROOT.parent/'项目暂停与恢复节点.md'):
        p.write_text(checkpoint+p.read_text(encoding='utf8'),encoding='utf8')
    upgrade=read(ROOT/'state/monitor_upgrade.json')
    upgrade.update(state='complete',stage='complete',completed=now(),pages=pages,report_file=pdf.name,
                   digital_run_id=review['digital_run_id'],final_acceptance_run_id=run.run_id)
    write_json(ROOT/'state/monitor_upgrade.json',upgrade)
    write_json(ROOT/'state/resume.json',{'execution_state':'complete','completed':now(),'active_work':None,
        'final_deliverables_complete':True,'delivery_index':'deliver/交付索引.json','final_acceptance_run_id':run.run_id,
        'validated_build_run_id':evidence['build_run_id'],'last_programming':regression['programming'],
        'current_xdc_sha256':evidence['config_sha256'],'requires_rebuild':False,
        'next_action':'日常使用monitor.ps1；断电后monitor.ps1 -Program。新增实验另建运行目录。',
        'historical_checkpoint':str((before/'resume.json').relative_to(ROOT))})
    write_json(ROOT/'state/active_checkpoint.json',{'execution_state':'complete','completed':now(),
        'delivery_index':'deliver/交付索引.json','final_acceptance_run_id':run.run_id,'monitor_evidence':evidence})
    for stage in ('M6','report','delivery'):
        run.status(stage,'passed',f'多传感器扩展实板验收、{pages}页图文报告复编译与逐页检查通过',
            ['deliver/验收记录.json','deliver/交付索引.json'], '完成；新操作另建运行目录',
            bitstream_sha256=evidence['bitstream_sha256'],config_sha256=evidence['config_sha256'])
    run.snapshot('封存多传感器扩展最终源码、说明、协议、黄金帧和恢复节点')
    # Copy changed sources, states and new evidence after the report assembler's snapshot.
    for name in ('host','scripts','tests','config','docs','state','report'):
        copy_tree(ROOT/name,package/name,lambda p: not p.name.startswith('layout_check') and
            (name!='report' or p.suffix in ('.tex','.cls','.pdf','.png','.jpg','.eps','.json','.md','.txt')))
    for name in ('README.md','monitor.ps1','run.ps1','requirements.txt'):
        shutil.copy2(ROOT/name,package/name)
    for folder in (run.path,report_run.path,rendered,ROOT/'runs'/review['digital_run_id']):
        copy_tree(folder,package/'runs'/folder.name,lambda p:not any(x in p.parts for x in ('.Xil','xsim.dir'))
                  and p.suffix not in ('.dcp','.wdb','.obj','.exe','.dll','.logstr','.pb'))
    shutil.copy2(ROOT/'runs/actions.jsonl',package/'runs/actions.jsonl')
    shutil.copy2(ROOT.parent/'项目暂停与恢复节点.md',package/'最新节点及历史暂停记录.md')
    write_json(package/'final_monitor_acceptance.json',review)
    hashes=[{'path':p.relative_to(package).as_posix(),'sha256':sha256(p),'bytes':p.stat().st_size}
            for p in sorted(package.rglob('*')) if p.is_file() and p.name!='SHA256.json']
    write_json(package/'SHA256.json',hashes)
    rc,_=run.command([sys.executable,package/'verify_hashes.py'],'最终多传感器复现包逐文件SHA-256复核',timeout=240)
    assert rc==0,'Final package integrity verification failed'
    index.update(pages=pages,report_sha256=pdf_hash,visual_review=f'passed: all {pages} pages',
        final_acceptance_run_id=run.run_id,render_run_id=render_id,files=len(hashes),
        acceptance_record='验收记录.json',reproduction_manifest_sha256=sha256(package/'SHA256.json'),
        package_hash_verification='passed',data_snapshot_completed=now())
    write_json(deliver/'交付索引.json',index)
    review.update(files=len(hashes),reproduction_manifest_sha256=index['reproduction_manifest_sha256'],package_hash_verification='passed')
    write_json(deliver/'验收记录.json',review)
    run.event('final_delivery_sealed',pdf_sha256=pdf_hash,pages=pages,files=len(hashes),
              reproduction_manifest_sha256=index['reproduction_manifest_sha256'])
    run.manifest()
    print(json.dumps({'pages':pages,'pdf_sha256':pdf_hash,'files':len(hashes),'run_id':run.run_id},ensure_ascii=False))


if __name__=='__main__':finalize(sys.argv[1])
