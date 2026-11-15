"""Seal the music implementation and its limitations after PDF visual review."""
import json,shutil,sys
from pathlib import Path
import pymupdf
from audit import ROOT,Run,now,sha256,write_json
from music_evidence import load_round


def read(path):return json.loads(Path(path).read_text(encoding='utf8'))


def main(render_id):
    run=Run('music_delivery');deliver=ROOT/'deliver';package=deliver/'复现实验'
    index=read(deliver/'交付索引.json');pdf=deliver/index['report_file'];review=read(ROOT/'runs'/render_id/'visual_review.json')
    physical=load_round();build=read(ROOT/'state/portable_build.json');regression=read(ROOT/'state/music_final_regression.json')
    assert physical['complete'] and physical['online_total']==3
    assert all(r['result'].get('zero_cost_verified') and r['result'].get('cost_yuan')==0 for r in physical['results'])
    assert regression['passed'] and regression['bitstream_sha256']==build['firmware']['bitstream_sha256']
    assert sha256(deliver/'软件/开发板实时监测.exe')==build['exe_sha256']
    assert read(ROOT/'state/portable_isolation.json')['exe_sha256']==build['exe_sha256']
    doc=pymupdf.open(pdf);assert review['pdf_sha256']==sha256(pdf) and review['visually_reviewed_pages']==list(range(1,len(doc)+1))
    for row in review['reviewed_images']:assert sha256(ROOT/'runs'/render_id/row['path'])==row['sha256']
    assert sha256(deliver/'报告源码/Experiment-template.pdf')==sha256(pdf)
    for folder in (ROOT/'report',deliver/'报告源码'):
        log=(folder/'Experiment-template.log').read_text(errors='replace')
        assert not any(s in log for s in ('Overfull','Missing character','undefined references','Undefined control sequence'))
    for name in ('报告.pdf','交付索引.json','验收记录.json'):
        path=deliver/name
        if path.exists():
            target=run.path/'before'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
    variant=pdf.name;shutil.copy2(pdf,deliver/'报告.pdf')
    result={'run_id':run.run_id,'time':now(),'implementation_status':'delivered_with_limitations',
        'app':build,'phone_run_id':physical['run_id'],'phone_online_correct':physical['online_correct'],'phone_online_total':physical['online_total'],
        'online_accuracy_target_met':physical.get('target_met',False),'actual_cost_yuan':0,
        'offline_scope':'closed_by_user_keep_existing_feature','legacy_regression':regression,'render_run_id':render_id,
        'favourite_restart':read(ROOT/'state/music_favourite_restart.json'),
        'report_sha256':sha256(pdf),'report_pages':len(doc),'pending_external':['cross_pc','second_board','native_ftdi_physical'],
        'limitations':['最新手机实板轮0/3确定命中，Billie Jean仅低置信度候选；API准确率未达目标','不以数字参考或候选展示改记实板识别成功']}
    write_json(run.path/'result.json',result);write_json(deliver/'验收记录_听歌识曲.json',result);write_json(ROOT/'state/music_delivery.json',result)
    old=read(deliver/'验收记录.json');write_json(deliver/'验收记录.json',{'latest_music':result,'previous_acceptance':old})
    for name in ('resume','active_checkpoint','music_upgrade','music_handover'):
        path=ROOT/'state'/f'{name}.json'
        value=read(path) if path.exists() else {}
        value.update(execution_state='implementation_delivered_with_limitations',music_delivery_run_id=run.run_id,
            next_action='日常使用1.1.5；API命中率不足保留为限制，离线不再开发，不要求当前换机补验',updated=now())
        if name in ('music_upgrade','music_handover'):value['status']='delivered_with_limitations'
        write_json(path,value)
    note=('# 听歌识曲API版本已交付（'+now()+'）\n\n软件'+build['app_version']+'，报告'+str(len(doc))+'页。'+
        '本轮手机确定命中0/3，Billie Jean返回低置信度候选，费用均核验0元；不宣称准确率达标。离线功能按现状收尾，不再补测。'+
        '当前交付以deliver/交付索引.json和deliver/验收记录_听歌识曲.json为准。\n\n'+
        '旧版手机1/5、笔记本开发0/3、全部未命中及中断记录均保留。后续外部换机、第二块板、原生FTDI仍待条件，不要求现在操作。\n\n---\n以下为历史恢复记录：\n\n')
    for path in (ROOT/'docs/听歌识曲恢复节点.md',ROOT/'docs/CONTINUE.md',ROOT.parent/'项目暂停与恢复节点.md'):
        path.write_text(note+path.read_text(encoding='utf8'),encoding='utf8')
    # Refresh the final state and documentation; account configuration stays local.
    private={'music_account_attestation.json','music_credentials.json','credentials.json'}
    for name in ('state','docs'):
        for path in (ROOT/name).rglob('*'):
            if not path.is_file() or path.name in private:continue
            target=package/path.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
    for name in ('README.md',):shutil.copy2(ROOT/name,package/name)
    if (deliver/'API实测摘要.md').exists():shutil.copy2(deliver/'API实测摘要.md',package/'API实测摘要.md')
    shutil.copy2(Path(__file__),package/'host/finalize_music_delivery.py')
    shutil.copytree(ROOT/'runs'/render_id,package/'runs'/render_id,dirs_exist_ok=True)
    target=package/'runs'/run.run_id;target.mkdir(parents=True,exist_ok=True)
    shutil.copy2(run.path/'result.json',target/'result.json')
    for name in private:assert not list(package.rglob(name)),name
    assert not list(package.rglob('*.sqlite3'))
    rows=[{'path':p.relative_to(package).as_posix(),'sha256':sha256(p),'bytes':p.stat().st_size}
        for p in sorted(package.rglob('*')) if p.is_file() and p.name!='SHA256.json']
    write_json(package/'SHA256.json',rows)
    for row in rows:assert sha256(package/row['path'])==row['sha256']
    index.update(report_file='报告.pdf',report_variant_file=variant,report_sha256=sha256(pdf),music_delivery=result,
        visual_review='passed',files=len(rows),package_manifest_sha256=sha256(package/'SHA256.json'))
    write_json(deliver/'交付索引.json',index)
    run.status('MUSIC7_delivery','passed','软件、双目录编译、逐页复核和复现哈希完成；API准确率未达目标已明确写入',
        ['deliver/交付索引.json','deliver/验收记录_听歌识曲.json'],'保留限制；离线开发关闭')
    print(run.run_id,'FILES',len(rows),'PHONE',physical['online_correct'],physical['online_total'])


if __name__=='__main__':main(sys.argv[1])
