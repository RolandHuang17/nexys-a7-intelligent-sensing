"""Accept a visual-only revision after full-page inspection; preserve hardware evidence."""
import json,re,shutil,sys
from pathlib import Path
import pymupdf
from audit import ROOT,Run,sha256,write_json,now
from finalize_monitor_delivery import copy_tree

def read(p):return json.loads(Path(p).read_text(encoding='utf8'))
def main(render_id):
    run=Run('visual_delivery');deliver=ROOT/'deliver';package=deliver/'复现实验'
    revision=read(ROOT/'state/visual_revision.json');work=ROOT/'runs'/revision['run_id'];before=work/'before'
    scope=read(work/'scope.json');index=read(deliver/'交付索引.json');pdf=deliver/index['report_file'];pdf_hash=sha256(pdf)
    old_review=read(before/'deliver/验收记录.json');old_index=read(before/'deliver/交付索引.json')
    render=ROOT/'runs'/render_id;visual=read(render/'visual_review.json');doc=pymupdf.open(pdf)
    assert visual['pdf_sha256']==pdf_hash and visual['visually_reviewed_pages']==list(range(1,len(doc)+1))
    for row in visual['reviewed_images']:assert sha256(render/row['path'])==row['sha256']
    assert sha256(deliver/'报告源码/Experiment-template.pdf')==pdf_hash
    for base in (ROOT/'report',deliver/'报告源码'):
        log=(base/'Experiment-template.log').read_text(errors='replace')
        assert not any(s in log for s in ('Overfull','Missing character','undefined references','Undefined control sequence'))
    for row in read(ROOT/'report/template_provenance.json')['unchanged_files']:
        assert sha256(deliver/'报告源码'/row['file'])==row['sha256']
    # Inputs, conclusions and runtime artifacts must survive this visual revision unchanged.
    claim=read(ROOT/'report/generated/claim_index.json');old_claim=read(before/'report/generated/claim_index.json')
    for key in ('collection_run_id','evaluation_run_id','result_sha256','frozen_config_sha256','bitstream_sha256'):
        assert claim[key]==old_claim[key],key
    for new,old in zip(claim['figures'],old_claim['figures']):
        for key in old:
            if key!='script_sha256':assert new[key]==old[key],key
    for file in ('monitor_implementation_values.json','monitor_measured_values.json','portable_claim_index.json'):
        assert read(ROOT/'report/generated'/file)==read(before/'report/generated'/file),file
    for file in ('board_original.jpg','monitor_dashboard.png','portable_dashboard.png'):
        assert sha256(ROOT/'report/figures'/file)==sha256(before/'report/figures'/file)
    assert sha256(deliver/'软件/开发板实时监测.exe')==scope['exe_sha256']
    a=read(ROOT/'state/portable_acceptance.json');assert a==read(before/'state/portable_acceptance.json')
    assert a['cross_pc']['status']=='needs_user' and a['second_board']['status']=='unverified'
    vindex=read(ROOT/'report/generated/visual_figure_index.json');assert len(vindex['figures'])==26
    assert sha256(ROOT/vindex['generator'])==vindex['generator_sha256']
    assert sha256(ROOT/vindex['shared_style'])==vindex['shared_style_sha256']
    for row in vindex['figures']:
        assert sha256(ROOT/row['tikz_source'])==row['tikz_sha256']
        for source in row['inputs']:assert sha256(ROOT/source['path'])==source['sha256'],source['path']
    exports=read(deliver/'插图/插图索引.json');assert exports['shared_style_sha256']==vindex['shared_style_sha256']
    for row in exports['figures']:
        for item in row['exports']:assert sha256(deliver/'插图'/item['file'])==item['sha256']
    for filename in ('figure_index.json','monitor_figure_index.json'):
        for row in read(ROOT/'report/generated'/filename):
            for source in row.get('inputs',[]):assert sha256(ROOT/source['path'])==source['sha256']
    count=len(re.findall(r'\\@writefile\{lof\}\{\\contentsline \{figure\}',(ROOT/'report/Experiment-template.aux').read_text(encoding='utf8')))
    assert count>=35,count
    for page in doc:
        assert all(-.5<=x0<x1<=page.rect.width+.5 and -.5<=y0<y1<=page.rect.height+.5 for x0,y0,x1,y1,*_ in page.get_text('words'))
    shutil.copy2(pdf,deliver/'报告.pdf')
    review={**old_review,'time':now(),'pdf_sha256':pdf_hash,'pages':len(doc),'render_run_id':render_id,
        'visually_reviewed_pages':visual['visually_reviewed_pages'],'checks':visual['checks'],
        'visual_revision':{'run_id':revision['run_id'],'final_run_id':run.run_id,'figures':count,'tikz_figures':26,
            'measurements_unchanged':True,'exe_unchanged':True,'previous_report_sha256':scope['baseline_pdf_sha256']}}
    write_json(deliver/'验收记录.json',review)
    state={**revision,'status':'passed','completed':now(),'final_run_id':run.run_id,'report':pdf.relative_to(ROOT).as_posix(),
        'pdf_sha256':pdf_hash,'pages':len(doc),'total_figures':count,'tikz_figures':26,'render_run_id':render_id,
        'scope':'仅图片、绘图样式与排版；数据、算法、固件与EXE保持不变'}
    write_json(ROOT/'state/visual_revision.json',state)
    note=(f'# 报告图片已加强（{now()}）\n\n新版：`deliver/{pdf.name}`，{len(doc)}页、{count}幅图，其中26幅TikZ矢量图。'
          '结构图、接口时序、状态、线程分工、实物导览和统计图已更新，实测数据、触发算法、位流与EXE未改。'
          '原报告及源码保存在本次visual_upgrade运行的before目录。\n\n'
          '交付源码可重新编译，`deliver/插图/`提供独立PDF与PNG。实测图输入哈希、图稿来源及操作记录均保留。'
          '换电脑、第二块板和原生FTDI实板路径仍待验证；用户暂时没有第二台电脑，不重复要求操作。\n\n')
    for p in (ROOT/'docs/CONTINUE.md',ROOT.parent/'项目暂停与恢复节点.md'):
        p.write_text(note+p.read_text(encoding='utf8'),encoding='utf8')
    (ROOT/'docs/报告图解修订节点.md').write_text(note,encoding='utf8')
    for name in ('resume.json','active_checkpoint.json'):
        checkpoint=read(ROOT/'state'/name);checkpoint.update(updated=now(),visual_revision=state,report_file=pdf.name)
        assert checkpoint['execution_state']=='needs_user' and checkpoint['requires_rebuild'] is False
        write_json(ROOT/'state'/name,checkpoint)
    run.status('report_visuals','passed',f'{len(doc)}页及{count}幅图逐页审阅通过；原测量与EXE保持不变',
               ['deliver/验收记录.json','report/generated/visual_figure_index.json'],'跨电脑等待验项目保持原状态')
    run.snapshot('图解增强定稿：保留TikZ、绘图样式、来源清单、修改差异和交付节点')
    for name in ('host','docs','state','report'):
        copy_tree(ROOT/name,package/name,lambda p:name!='report' or p.suffix in ('.tex','.cls','.pdf','.png','.jpg','.eps','.json','.md','.txt'))
    copy_tree(deliver/'插图',package/'报告插图')
    # Gallery source was generated after the report build; include it in recompilable sources too.
    shutil.copy2(ROOT/'report/Diagram-gallery.tex',deliver/'报告源码/Diagram-gallery.tex')
    for folder in (run.path,render,work,ROOT/'runs'/index['report_run_id']):copy_tree(folder,package/'runs'/folder.name)
    for folder in (ROOT/'runs').glob('*_diagram_gallery'):
        copy_tree(folder,package/'runs'/folder.name)
    shutil.copy2(ROOT/'runs/actions.jsonl',package/'runs/actions.jsonl')
    write_json(package/'visual_delivery_acceptance.json',review)
    write_json(package/'report_plot_style_provenance.json',{'file':'host/plot_style.py','sha256':sha256(ROOT/'host/plot_style.py'),
        'purpose':'只改变颜色、字体、网格和子图编号，不改变数据与坐标范围'})
    files=[{'path':p.relative_to(package).as_posix(),'bytes':p.stat().st_size,'sha256':sha256(p)} for p in sorted(package.rglob('*')) if p.is_file() and p.name!='SHA256.json']
    write_json(package/'SHA256.json',files)
    rc,_=run.command([sys.executable,package/'verify_hashes.py'],'最终图解增强复现实验包逐文件SHA-256核对',timeout=300);assert rc==0
    index.update(report_sha256=pdf_hash,pages=len(doc),canonical_report_file='报告.pdf',visual_review=f'passed: all {len(doc)} pages',
        final_acceptance_run_id=run.run_id,portable_software=old_index['portable_software'],pending=old_index['pending'],
        figures=count,tikz_figures=26,figure_exports='插图',visual_revision_run_id=revision['run_id'],files=len(files),
        reproduction_manifest_sha256=sha256(package/'SHA256.json'),package_hash_verification='passed',data_snapshot_completed=now())
    write_json(deliver/'交付索引.json',index)
    review.update(files=len(files),package_hash_verification='passed',reproduction_manifest_sha256=index['reproduction_manifest_sha256']);write_json(deliver/'验收记录.json',review)
    run.event('visual_delivery_sealed',pdf_sha256=pdf_hash,figures=count,pages=len(doc),pending=index['pending']);run.manifest()
    print(json.dumps({'run_id':run.run_id,'pages':len(doc),'figures':count,'files':len(files),'pdf_sha256':pdf_hash},ensure_ascii=False))
if __name__=='__main__':main(sys.argv[1])
