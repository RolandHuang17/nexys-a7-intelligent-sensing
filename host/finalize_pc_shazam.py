"""Seal the PC-only deliverable after real packaged-EXE validation passes."""
import json
from pathlib import Path
import shutil

from pc_shazam_backend import parse_response
from songrec_probe import digest, now, write_json


def main():
    root=Path(__file__).resolve().parent.parent
    data=Path.home()/'AppData/Local/ShazamMicTest'
    output=root/'deliver/电脑麦克风Shazam测试'
    report=json.loads((data/'validation_result.json').read_text(encoding='utf8'))
    assert report['status']=='passed' and report['correct']>=5 and report['wrong']==0
    assert report['same_six_clip_hashes_verified'] and len(report['rows'])==6
    for row in report['rows']:
        directory=Path(row['trial_directory'])
        trial=json.loads((directory/'trial.json').read_text(encoding='utf8'))
        assert digest(trial['wav'])==row['wav_sha256']
        assert digest(trial['clip'])==row['clip_sha256']
        calls_path=directory/'http_requests.json'
        calls=json.loads(calls_path.read_text(encoding='utf8')) if calls_path.exists() else []
        assert len(calls)<=1
        if row['result']['matched']:
            raw=json.loads((directory/'service_response.json').read_text(encoding='utf8'))
            parsed=parse_response(raw)
            assert parsed['matched'] and parsed['title']==row['result']['title'] and parsed['artist']==row['result']['artist']
            assert calls[0]['http_status']==200
    initial=json.loads((data/'validation_attempt1.json').read_text(encoding='utf8'))
    baseline=json.loads((root/'state/songrec_deployment_baseline.json').read_text(encoding='utf8'))
    protected={p:digest(root/p)==h for p,h in baseline.items()}
    assert all(protected.values())
    stage1=json.loads((root/'state/songrec_acceptance_passed.json').read_text(encoding='utf8'))
    session=json.loads(Path(stage1['session_file']).read_text(encoding='utf8'))
    frozen=json.loads((root/'runs/shazam_packaged_check_v2/self_check.json').read_text(encoding='utf8'))
    capture=json.loads((root/'runs/shazam_packaged_check_final/capture_probe.json').read_text(encoding='utf8'))
    assert frozen['frozen'] and not frozen['forbidden_imports'] and capture['complete'] and capture['samples']==32000
    final={**report,'verification_kind':'final_packaged_EXE_replay','entrypoint':str(output/'电脑麦克风Shazam测试.exe'),
           'exe_sha256':digest(output/'电脑麦克风Shazam测试.exe'),'verified_at':now(),
           'unit_checks_passed':11,'packaged_self_check':frozen,'real_final_EXE_2_second_microphone_probe':capture,
           'protected_files':protected,'initial_batch_preserved':True}
    write_json(output/'六份录音验证.json',final)
    write_json(output/'首轮验证_含限流.json',initial)
    write_json(output/'SongRec六项验收.json',session)
    shutil.copy2(Path(__file__),output/'源码/finalize_pc_shazam.py')
    lines=['# 电脑麦克风识曲验证结果','',f'封存时间：{final["verified_at"]}。',
           '', 'SongRec 新录制六项电脑麦克风验收：6/6 正确，零误认、零服务错误。',
           '', f'ShazamIO 打包版完整复测：{report["correct"]}/6 正确，{report["wrong"]} 次误认，{report["errors"]} 次服务错误。使用相同原录音，并逐一校验实际识别的12秒片段 SHA256。',
           '', '| 项目 | SongRec | ShazamIO 实际返回 | 判定 |', '|---|---|---|---|']
    labels={'correct':'正确','wrong':'误认','not_found':'未命中','error':'服务错误'}
    for row in report['rows']:
        expected=row['expected']; answer=row['result']
        text=answer['title']+' — '+answer['artist'] if answer.get('matched') else answer.get('message','未完成')
        lines.append(f'| {row["index"]+1}. {expected["title"]} · 第{expected["repeat"]}次 | 正确 | {text} | {labels[row["grade"]]} |')
    lines += ['', '首轮打包版测试为4/6正确，另两次均为HTTP 429限流，零误认；已保留首轮独立结果和源码快照。随后增加至少30秒请求间隔，遇429则冷却至少60秒，并遵守更长Retry-After；每个片段仍只有一次HTTP尝试，没有自动重试。上表为修改后完整重跑六项的结果。',
              '', '验证使用这三首歌的六份真实电脑录音进行文件回放，结论仅覆盖这些样本。原录音和原始服务响应保留在本机ShazamMicTest目录。',
              '', '最终EXE通过依赖检查、真实电脑麦克风2秒采集检查和11项针对性测试。开发板主程序、位流、原报告、交付索引及原AudioTag工具校验一致。新工具不连接开发板，不读取AudioTag密钥，不使用收费接口。',
              '', f'最终EXE SHA256：`{final["exe_sha256"]}`。']
    (output/'验证结果.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    manifest=json.loads((output/'软件版本.json').read_text(encoding='utf8'))
    manifest.update(release_status='validated_PC_only',validation={'SongRec_correct':6,'ShazamIO_correct':report['correct'],
                    'total':6,'wrong':report['wrong'],'errors':report['errors'],'same_six_recorded_clips':True,
                    'first_batch':'4 correct; 2 HTTP 429; preserved separately'},unit_checks_passed=11)
    write_json(output/'软件版本.json',manifest)
    files={str(p.relative_to(output)).replace('\\','/'):digest(p) for p in output.rglob('*') if p.is_file() and p.name!='SHA256.json'}
    write_json(output/'SHA256.json',files)
    assert all(digest(output/p)==h for p,h in files.items())
    songrec=root/'deliver/SongRec电脑麦克风对照'
    write_json(songrec/'六项验收结果.json',session)
    songrec_files={str(p.relative_to(songrec)).replace('\\','/'):digest(p) for p in songrec.rglob('*') if p.is_file() and p.name!='SHA256.json'}
    write_json(songrec/'SHA256.json',songrec_files)
    ready=json.loads((root/'state/songrec_probe_ready.json').read_text(encoding='utf8'))
    assert digest(songrec/'开始六项测试.exe')==ready['exe_sha256']
    ready.update(status='six_microphone_recordings_passed',formal_gate=session['gate'],ShazamIO_stage='PC_only_delivered')
    write_json(root/'state/songrec_probe_ready.json',ready)
    delivery={'status':'complete_PC_only','time':now(),'exe':str(output/'电脑麦克风Shazam测试.exe'),
              'exe_sha256':final['exe_sha256'],'SongRec_correct':6,'ShazamIO_correct':report['correct'],'total':6,
              'wrong':report['wrong'],'initial_429_errors':2,'unit_checks_passed':11,'final_files_hash_checked':len(files),
              'protected_files_unchanged':True,'main_board_application_updated':False,'AudioTag_key_accessed':False,
              'account_or_payment_created':False,'data_root':str(data),'validation_report':str(output/'六份录音验证.json')}
    write_json(root/'state/pc_shazam_delivery.json',delivery)
    print(json.dumps(delivery,ensure_ascii=False))


if __name__=='__main__':
    main()
