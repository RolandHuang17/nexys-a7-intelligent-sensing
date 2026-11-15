"""Seal local EXE acceptance and updated report; preserve cross-PC work as pending."""
import json,shutil,sys
from pathlib import Path
import pymupdf
from audit import ROOT,Run,write_json,sha256,now
from finalize_monitor_delivery import copy_tree,check_event

def read(p):return json.loads(Path(p).read_text(encoding='utf8'))

def main(render_id):
    run=Run('portable_delivery');deliver=ROOT/'deliver';package=deliver/'复现实验';index=read(deliver/'交付索引.json')
    a=read(ROOT/'state/portable_acceptance.json');build=read(ROOT/'state/portable_build.json');pdf=deliver/index['report_file']
    pdf_hash=sha256(pdf);render=ROOT/'runs'/render_id;visual=read(render/'visual_review.json');doc=pymupdf.open(pdf)
    assert visual['pdf_sha256']==pdf_hash and visual['visually_reviewed_pages']==list(range(1,len(doc)+1))
    for row in visual['reviewed_images']:assert sha256(render/row['path'])==row['sha256']
    assert sha256(deliver/'报告源码/Experiment-template.pdf')==pdf_hash
    text='\n'.join(p.get_text() for p in doc)
    for phrase in ('黄玉成','2022302111419','嵌入式系统','独立软件与跨电脑使用','系统功能详细分析','硬件模块框图',
                   '系统软件设计思想','核心技术要点','0.571','0.750','尚未取得'):
        assert phrase in text,phrase
    for page in doc:
        assert all(x0>=-.5 and y0>=-.5 and x1<=page.rect.width+.5 and y1<=page.rect.height+.5
                   for x0,y0,x1,y1,*_ in page.get_text('words')),'Text outside page'
    for base in (ROOT/'report',deliver/'报告源码'):
        log=(base/'Experiment-template.log').read_text(errors='replace')
        assert not any(x in log for x in ('Overfull','Missing character','undefined references','Undefined control sequence'))
    for row in read(ROOT/'report/template_provenance.json')['unchanged_files']:
        assert sha256(deliver/'报告源码'/row['file'])==row['sha256']
    exe=deliver/'软件/开发板实时监测.exe'
    assert sha256(exe)==build['exe_sha256']==a['build']['exe_sha256']
    isolation=read(ROOT/'state/portable_isolation.json');assert isolation['exe_sha256']==build['exe_sha256']
    assert isolation['self_check']['frozen'] and isolation['self_check']['resources_verified']
    assert read(ROOT/'state/P3/status.json')['status']=='passed' and a['hotplug']['recovered']
    assert a['cross_pc']['status']=='needs_user' and a['second_board']['status']=='unverified'
    assert a['hotplug']['pre_session']!=a['hotplug']['post_session']
    events=[check_event(ROOT/e['directory'],build['firmware']['bitstream_sha256']) for e in a['events']]
    hotdir=ROOT/a['hotplug']['archived_post_session']/'physical'
    events += [check_event(p.parent,build['firmware']['bitstream_sha256']) for p in hotdir.rglob('metadata.json')]
    # Verify the runtime modules have not changed since the EXE source snapshot.
    snapshots=list((ROOT/'runs'/build['run_id']/'source_snapshots').glob('*/source_manifest.json'));assert len(snapshots)==1
    manifest=read(snapshots[0]);hashes={x['path']:x['sha256'] for x in manifest}
    for name in ('app_paths.py','audit.py','device_discovery.py','portable_program.py','portable_main.py','driver_setup.py','monitor_gui.py','monitor_service.py','monitor_protocol.py','protocol.py','capture.py'):
        assert sha256(ROOT/'host'/name)==hashes['host/'+name],name
    claim=read(ROOT/'report/generated/claim_index.json');previous=read(ROOT/'runs/20261114T162835_095939_portable_upgrade/previous_delivery/报告源码/generated/claim_index.json')
    for key in ('collection_run_id','evaluation_run_id','result_sha256','frozen_config_sha256','bitstream_sha256'):
        assert claim[key]==previous[key],key
    pclaim=read(ROOT/'report/generated/portable_claim_index.json')
    assert pclaim['exe_sha256']==build['exe_sha256'] and not pclaim['cross_pc_verified']
    for row in pclaim['inputs']:assert sha256(ROOT/row['path'])==row['sha256']
    assert sha256(ROOT/pclaim['generator'])==pclaim['generator_sha256']
    for row in read(ROOT/'report/generated/monitor_figure_index.json'):
        for source in row['inputs']:assert sha256(ROOT/source['path'])==source['sha256']
    shutil.copy2(pdf,deliver/'报告.pdf')
    review={'time':now(),'pdf_sha256':pdf_hash,'pages':len(doc),'render_run_id':render_id,
        'visually_reviewed_pages':visual['visually_reviewed_pages'],'checks':visual['checks'],
        'exe':build,'local_acceptance_run_id':a['run_id'],'events':events,'hotplug':a['hotplug'],
        'cross_pc':a['cross_pc'],'second_board':a['second_board'],'native_ftdi_backend':a['native_ftdi_backend'],
        'driver_setup':a['driver_setup'],'remaining_verifications':[
            '真正换电脑及常规FTDI驱动下实板下载未验证','第二块同型号板未实测','未购买应用代码签名证书',
            '传感器外部仪表标定未完成','原声振联合触发轻敲漏检仍保留']}
    write_json(run.path/'review.json',review);write_json(deliver/'验收记录.json',review)
    software_index={**build,'local_acceptance_run_id':a['run_id'],'hotplug_verified':True,
        'single_file_isolation_verified':True,'cross_pc_verified':False,'second_board_verified':False,
        'native_ftdi_physically_verified':False,'status':'local_release_accepted_cross_pc_pending'}
    write_json(deliver/'软件/软件版本.json',software_index)
    usage=(ROOT/'docs/独立软件使用说明.md').read_text(encoding='utf8')
    (deliver/'软件/使用说明.md').write_text(usage,encoding='utf8')
    note=(f'# 独立EXE已交付，换机待验（{now()}）\n\n'
        f'软件：`deliver/软件/开发板实时监测.exe`，SHA-256 `{build["exe_sha256"]}`。'
        f'报告：`deliver/{pdf.name}`，共{len(doc)}页。源码、离线工具、原始记录、失败与修复已同步。\n\n'
        '已完成本机单文件隔离、真实板端采集、完整事件、软件内初始化、真实USB拔插与重新初始化恢复、波形和诊断导出。'
        'USB和UART目标按实际序列号关联，不绑定旧板。SRAM配置掉电丢失，不写Flash。\n\n'
        '操作者目前没有另一台电脑（原文“现在没电脑，搞不了”），因此换机、常规FTDI实板路径和第二块同型号板仍待验，不能记为通过。'
        '以后复制同一个EXE到另一台电脑，初始化、操作输入、保存事件并导出诊断ZIP，放回 `deliver/软件/换机验收/` 后补验即可。'
        '不需要重做前期30次对照或覆盖旧事件。验收入口为 `state/portable_acceptance.json`、`deliver/验收记录.json`。\n\n'
        '下文为历史节点，已完成的旧暂停指令不再执行。\n\n')
    for path in (ROOT/'docs/CONTINUE.md',ROOT.parent/'项目暂停与恢复节点.md'):
        path.write_text(note+path.read_text(encoding='utf8'),encoding='utf8')
    (ROOT/'docs/独立软件发布节点.md').write_text(note,encoding='utf8')
    (deliver/'使用说明.md').write_text('当前软件与报告见交付索引。\n\n'+usage,encoding='utf8')
    state=read(ROOT/'state/portable_upgrade.json');state.update(state='local_delivery_complete',stage='P4_cross_pc_pending',
        completed_local=now(),final_acceptance_run_id=run.run_id,report_file=pdf.name,exe_sha256=build['exe_sha256'])
    write_json(ROOT/'state/portable_upgrade.json',state)
    checkpoint={'execution_state':'needs_user','active_work':'portable_cross_pc_validation','implementation':'delivered',
        'local_board_validation':'passed','cross_pc_validation':'needs_user','cross_board_validation':'unverified',
        'reason':'用户当前没有另一台电脑','updated':now(),'delivery_index':'deliver/交付索引.json',
        'final_acceptance_run_id':run.run_id,'requires_rebuild':False,'exe_sha256':build['exe_sha256'],
        'next_action':'另一台电脑可用时按docs/独立软件使用说明.md补验，收取诊断ZIP，不重做已有实板实验'}
    write_json(ROOT/'state/resume.json',checkpoint);write_json(ROOT/'state/active_checkpoint.json',checkpoint)
    for stage in ('P5_report','P6_delivery','report','delivery'):
        run.status(stage,'passed',f'EXE本机验收及{len(doc)}页报告交付；换机换板明确待验',
            ['deliver/验收记录.json','deliver/交付索引.json'],'等待以后可用的另一台电脑补验',
            bitstream_sha256=build['firmware']['bitstream_sha256'])
    run.snapshot('独立软件发布、本机实板验收和换机待验节点最终源码快照')
    for name in ('host','scripts','tests','config','docs','state','report'):
        copy_tree(ROOT/name,package/name,lambda p:not p.name.startswith('layout_check') and
            (name!='report' or p.suffix in ('.tex','.cls','.pdf','.png','.jpg','.eps','.json','.md','.txt')))
    for name in ('README.md','requirements-portable-build.txt'):shutil.copy2(ROOT/name,package/name)
    for name in ('开发板实时监测.exe','软件版本.json','使用说明.md'):shutil.copy2(deliver/'软件'/name,package/'software'/name)
    for folder in (run.path,render,ROOT/'runs'/index['report_run_id']):
        copy_tree(folder,package/'runs'/folder.name)
    shutil.copy2(ROOT/'runs/actions.jsonl',package/'runs/actions.jsonl');write_json(package/'portable_acceptance.json',review)
    files=[{'path':p.relative_to(package).as_posix(),'bytes':p.stat().st_size,'sha256':sha256(p)}
           for p in sorted(package.rglob('*')) if p.is_file() and p.name!='SHA256.json']
    write_json(package/'SHA256.json',files)
    rc,_=run.command([sys.executable,package/'verify_hashes.py'],'最终独立软件复现包逐文件SHA-256复核',timeout=300);assert rc==0
    index.update(report_sha256=pdf_hash,pages=len(doc),canonical_report_file='报告.pdf',visual_review=f'passed: all {len(doc)} pages',
        final_acceptance_run_id=run.run_id,portable_software=software_index,files=len(files),
        reproduction_manifest_sha256=sha256(package/'SHA256.json'),package_hash_verification='passed',
        pending=['cross_pc','second_board','native_ftdi_physical'],data_snapshot_completed=now())
    write_json(deliver/'交付索引.json',index);review.update(files=len(files),package_hash_verification='passed',
        reproduction_manifest_sha256=index['reproduction_manifest_sha256'])
    write_json(deliver/'验收记录.json',review)
    run.event('portable_delivery_sealed',pdf_sha256=pdf_hash,exe_sha256=build['exe_sha256'],files=len(files),pending=index['pending']);run.manifest()
    print(json.dumps({'run_id':run.run_id,'pages':len(doc),'files':len(files),'exe_sha256':build['exe_sha256'],'pending':index['pending']},ensure_ascii=False))

if __name__=='__main__':main(sys.argv[1])
