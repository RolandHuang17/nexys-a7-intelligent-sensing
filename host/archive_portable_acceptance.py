"""Archive actual EXE session evidence and keep unavailable cross-PC tests pending."""
import json,os,shutil,sys,wave,zlib,zipfile
from pathlib import Path
from audit import ROOT,Run,write_json,sha256,now

def read(p):return json.loads(Path(p).read_text(encoding='utf8'))

def main():
    run=Run('portable_acceptance');build=read(ROOT/'state/portable_build.json')
    data=Path(os.environ['LOCALAPPDATA'])/'NexysMonitor';gui=read(data/'state/monitor_gui.json')
    assert gui['state']=='closed';session=data/'runs'/gui['run_id']
    assert sha256(session/'release_manifest.json')==build['resource_manifest_sha256']
    summary=read(session/'session_summary.json');assert summary['polls']>100 and summary['last']['build_id']==build['firmware']['build_id']
    assert summary['last']['adxl_id_ok'] and summary['last']['adt_identity']==203 and summary['last']['adt_configuration']==128
    assert summary['last']['xadc_valid_mask']==15
    target=run.path/'runtime_records';target.mkdir()
    for folder in (data/'runs').iterdir():
        if folder.is_dir() and folder.name>='20261114T164000':shutil.copytree(folder,target/folder.name)
    events=[]
    for p in (target/gui['run_id']/'physical').rglob('metadata.json'):
        m=read(p);b=(p.parent/'payload.bin').read_bytes()
        assert sha256(p.parent/'payload.bin')==m['input_hash'] and zlib.crc32(b)==m['payload_crc32']
        assert len(b)==48000+10*m['xyz_count'] and m['pcm_count']==24000
        with wave.open(str(p.parent/'audio.wav'),'rb') as w:
            assert w.getframerate()==16000 and w.getnframes()==24000 and w.readframes(24000)==b[:48000]
        assert m['programming']['bitstream_sha256']==build['firmware']['bitstream_sha256']
        assert m['programming']['usb_serial']==summary['device']['usb_serial']
        events.append({'event_id':m['event_id'],'pcm_count':m['pcm_count'],'xyz_count':m['xyz_count'],
                       'input_hash':m['input_hash'],'directory':p.parent.relative_to(ROOT).as_posix()})
    assert events
    ui=read(ROOT/'state/portable_ui_review.json');ui_run=Run('portable_ui_review',ui['run_id'])
    for filename in ('portable_dashboard_final.png','small_window_scroll.png','portable_event_view.png'):
        assert (ui_run.path/filename).is_file()
    diag=ui_run.path/'本机EXE实板诊断.zip';assert diag.is_file()
    import hashlib
    with zipfile.ZipFile(diag) as z:
        d=read_index=json.loads(z.read('diagnostic_index.json'))
        assert d['session']==gui['run_id']
        for row in d['files']:assert hashlib.sha256(z.read(row['path'])).hexdigest()==row['sha256']
    isolation=read(ROOT/'state/portable_isolation.json');assert isolation['exe_sha256']==build['exe_sha256']
    review={'time':now(),'exe_sha256':build['exe_sha256'],'gui_session':gui['run_id'],'ui_run_id':ui_run.run_id,
        'checks':['实际EXE实时数据来自板端','完整事件CRC与WAV一致','EXE内原始波形窗口通过',
                  '1280x720控件换行和图表滚动通过','GUI独立子进程SRAM初始化和重新连接通过',
                  '诊断导出ZIP逐文件哈希通过'],
        'screenshot':(ui_run.path/'portable_dashboard_final.png').relative_to(ROOT).as_posix(),
        'screenshot_sha256':sha256(ui_run.path/'portable_dashboard_final.png'),
        'diagnostic_zip':diag.relative_to(ROOT).as_posix(),'diagnostic_zip_sha256':sha256(diag)}
    write_json(ui_run.path/'review.json',review);ui_run.event('portable_ui_acceptance',**review);ui_run.manifest()
    result={'source':'physical_board_and_packaged_executable','run_id':run.run_id,'build':build,
        'gui_session':gui['run_id'],'archived_session':(target/gui['run_id']).relative_to(ROOT).as_posix(),
        'isolation_run_id':isolation['run_id'],'ui_review':review,'events':events,
        'summary':summary,'cross_pc':{'status':'needs_user','verbatim':'现在没电脑，搞不了','observed':now(),
            'reason':'另一台电脑目前不可用，未进行真正换机验收'},
        'second_board':{'status':'unverified','reason':'没有第二块Nexys A7-100T'},
        'native_ftdi_backend':{'status':'built_not_physically_verified','reason':'本机A接口使用WinUSB，未替换可用驱动'},
        'driver_setup':{'status':'signature_verified_not_installed','version':'2.12.36.20',
            'signer':'Future Technology Devices International Ltd','reason':'现有驱动可用，无需安装'},
        'programming_runs':['20261114T164205_403029_app_program','20261114T164627_654088_app_program']}
    write_json(run.path/'result.json',result);write_json(ROOT/'state/portable_acceptance.json',result)
    run.event('portable_local_acceptance_passed',exe_sha256=build['exe_sha256'],gui_session=gui['run_id'],
              events=events,cross_pc_status='needs_user',second_board_status='unverified')
    run.status('P3','passed','单文件EXE本机隔离运行、实板采集、事件完整性及GUI初始化通过',
        [(run.path/'result.json').relative_to(ROOT).as_posix()],'更新报告与发布包',
        bitstream_sha256=build['firmware']['bitstream_sha256'])
    run.status('P4_cross_pc','needs_user','用户当前没有另一台电脑，换机与常规FTDI实板路径待验证',
        [(run.path/'result.json').relative_to(ROOT).as_posix()],'以后只需复制EXE做换机验收，不必重做已有实验')
    run.manifest();print(run.run_id)

if __name__=='__main__':main()
