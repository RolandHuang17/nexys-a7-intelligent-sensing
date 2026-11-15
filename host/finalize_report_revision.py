"""Seal a writing-only revision after rendering and inspecting every PDF page."""
import json,shutil,sys
from pathlib import Path
import pymupdf
from audit import ROOT,Run,sha256,write_json,now

def read(p):return json.loads(Path(p).read_text(encoding='utf8'))

def finalize(render_id):
    state=read(ROOT/'state/plain_language_revision.json')
    revision=Run('plain_language_revision',state['run_id']);run=Run('report_revision_acceptance')
    deliver=ROOT/'deliver';package=deliver/'复现实验'
    index=read(deliver/'交付索引.json');pdf=deliver/index.get('report_file','报告.pdf');pdf_hash=sha256(pdf);rendered=ROOT/'runs'/render_id
    visual=read(rendered/'visual_review.json');doc=pymupdf.open(pdf);pages=len(doc)
    assert visual['pdf_sha256']==pdf_hash
    assert visual['visually_reviewed_pages']==list(range(1,pages+1))
    for row in visual['reviewed_images']:
        assert sha256(rendered/row['path'])==row['sha256']
    assert any(x['kind']=='pdf_rendered' and x['sha256']==pdf_hash for x in
               [json.loads(line) for line in (rendered/'actions.jsonl').read_text(encoding='utf8').splitlines()])
    text='\n'.join(p.get_text() for p in doc)
    for phrase in ('黄玉成','2022302111419','武小平','嵌入式系统','系统功能详细分析','硬件模块框图',
                   '系统软件设计思想','核心技术要点','0.571','0.750','用来作参照的官方程序'):
        assert phrase in text,phrase
    assert '待补充' not in text
    for p in doc:
        assert all(x0>=-.5 and y0>=-.5 and x1<=p.rect.width+.5 and y1<=p.rect.height+.5
                   for x0,y0,x1,y1,*_ in p.get_text('words')),'Text outside page'
    for folder in (ROOT/'report',deliver/'报告源码'):
        log=(folder/'Experiment-template.log').read_text(errors='replace')
        assert all(s not in log for s in ('Overfull','Undefined control sequence','Missing character','undefined references'))
    assert sha256(deliver/'报告源码/Experiment-template.pdf')==pdf_hash
    for row in read(ROOT/'report/template_provenance.json')['unchanged_files']:
        assert sha256(deliver/'报告源码'/row['file'])==row['sha256']
    old_claim=read(revision.path/'previous_delivery/报告源码/generated/claim_index.json')
    claim=read(ROOT/'report/generated/claim_index.json')
    for key in ('collection_run_id','evaluation_run_id','result_sha256','frozen_config_sha256','bitstream_sha256'):
        assert claim[key]==old_claim[key],key
    assert [e['input_hash'] for e in claim['figures']]==[e['input_hash'] for e in old_claim['figures']]
    assert sha256(ROOT/'runs'/claim['evaluation_run_id']/'results.json')==claim['result_sha256']
    old_review=read(revision.path/'previous_delivery/验收记录.json')
    review={**old_review,'time':now(),'pdf_sha256':pdf_hash,'pages':pages,'render_run_id':render_id,
            'visually_reviewed_pages':visual['visually_reviewed_pages'],'detail_zoom_pages':visual['detail_zoom_pages'],
            'writing_revision':True,'previous_pdf_sha256':state['previous_pdf_sha256'],
            'revision_run_id':revision.run_id,'measurements_and_parameters_unchanged':True,
            'checks':visual['checks']+['源码及交付目录复编译','模板文件校验','实测结果、参数和图表输入哈希与上一版一致']}
    for key in ('files','reproduction_manifest_sha256','package_hash_verification'):review.pop(key,None)
    write_json(run.path/'review.json',review);write_json(deliver/'验收记录.json',review)
    evidence=['deliver/验收记录.json','deliver/交付索引.json','state/plain_language_revision.json']
    report_run=Run('report',index['report_run_id']);report_run.event('visual_review_completed',**review)
    report_run.status('report','passed',f'朴素中文改写，{pages}页逐页检查及交付目录复编译通过',evidence,'已交付',
        bitstream_sha256=claim['bitstream_sha256'],config_sha256=claim['frozen_config_sha256'],
        outputs=[pdf.relative_to(ROOT).as_posix(),'deliver/报告源码','deliver/复现实验'])
    state.update(status='passed',completed=now(),pdf_sha256=pdf_hash,pages=pages,render_run_id=render_id,
        acceptance_run_id=run.run_id,measurements_and_parameters_unchanged=True)
    write_json(ROOT/'state/plain_language_revision.json',state)
    revision.event('revision_completed',pdf_sha256=pdf_hash,pages=pages,acceptance_run_id=run.run_id,measurements_unchanged=True)
    revision.manifest();report_run.manifest()
    resume=read(ROOT/'state/resume.json');resume.update(execution_state='complete',final_acceptance_run_id=run.run_id,
        report_revision_run_id=revision.run_id,final_deliverables_complete=True,completed=now())
    write_json(ROOT/'state/resume.json',resume)
    write_json(ROOT/'state/active_checkpoint.json',{'execution_state':'complete','completed':now(),
        'delivery_index':'deliver/交付索引.json','final_acceptance_run_id':run.run_id,'report_revision_run_id':revision.run_id})
    note=(f'## 报告文字已改写（{now()}）\n\n新版报告共{pages}页。先用敲桌面的例子说明功能，解释baseline和触发等词；'
          '结果先列找到、误报和漏检次数，运行号及校验值移到附录。实测数据、阈值、位流和原始事件均未改变。'
          f'旧报告在 `runs/{revision.run_id}/previous_delivery/`。当前交付为 `deliver/{pdf.name}`，'
          '源码和复现实验包已同步。不需要重新采样。\n\n')
    p=ROOT/'docs/CONTINUE.md';p.write_text(note+p.read_text(encoding='utf8'),encoding='utf8')
    usage=(ROOT/'docs/交付说明.md').read_text(encoding='utf8')
    usage=usage.replace('25页',f'{pages}页').replace('`报告.pdf`',f'`{pdf.name}`')
    usage+='\n## 本次文字修改\n\n报告已改为较朴素的中文，新增官方参照程序与本项目功能的说明，术语先解释再使用。'
    usage+='正文先列检测次数，再介绍指标；长运行号和校验值集中到附录。实验数据、参数和结论保持不变。\n'
    (ROOT/'docs/交付说明.md').write_text(usage,encoding='utf8');(deliver/'使用说明.md').write_text(usage,encoding='utf8')
    run.status('delivery','passed',f'新版{pages}页PDF、可编译源码及复现实验包已同步',evidence,'完成')
    run.snapshot('朴素中文报告完成，保留最终脚本和状态快照')
    # Freeze package contents before hashing. The final verification receipt remains outside this snapshot.
    for name in ('host','report','docs','state'):
        for p in (ROOT/name).rglob('*'):
            if not p.is_file() or '__pycache__' in p.parts:continue
            if name=='report' and p.suffix not in ('.tex','.cls','.pdf','.png','.jpg','.eps','.json','.md','.txt'):continue
            if p.name.startswith('layout_check'):continue
            q=package/p.relative_to(ROOT);q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,q)
    for folder in (revision.path,report_run.path,run.path,rendered):
        for p in folder.rglob('*'):
            if p.is_file():
                q=package/p.relative_to(ROOT);q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,q)
    shutil.copy2(ROOT/'runs/actions.jsonl',package/'runs/actions.jsonl');write_json(package/'final_acceptance.json',review)
    hashes=[{'path':p.relative_to(package).as_posix(),'sha256':sha256(p),'bytes':p.stat().st_size}
            for p in sorted(package.rglob('*')) if p.is_file() and p.name!='SHA256.json']
    write_json(package/'SHA256.json',hashes)
    rc,_=run.command([sys.executable,package/'verify_hashes.py'],'新版复现包全部文件哈希校验',timeout=180)
    assert rc==0
    index.update(report_sha256=pdf_hash,pages=pages,visual_review=f'passed: all {pages} pages',
        final_acceptance_run_id=run.run_id,revision_run_id=revision.run_id,files=len(hashes),
        acceptance_record='验收记录.json',reproduction_manifest_sha256=sha256(package/'SHA256.json'),
        package_hash_verification='passed',data_snapshot_completed=now())
    write_json(deliver/'交付索引.json',index)
    review.update(files=len(hashes),reproduction_manifest_sha256=index['reproduction_manifest_sha256'],package_hash_verification='passed')
    write_json(deliver/'验收记录.json',review);run.manifest()
    print(json.dumps({'pages':pages,'pdf_sha256':pdf_hash,'files':len(hashes),'run_id':run.run_id},ensure_ascii=False))

if __name__=='__main__':finalize(sys.argv[1])
