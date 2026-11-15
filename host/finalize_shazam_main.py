"""Promote the verified board app, keeping report and old software provenance."""
import json
from pathlib import Path
import shutil

from build_shazam_main import promote
from songrec_probe import digest,now,write_json


def main():
    root=Path(__file__).resolve().parent.parent
    result=json.loads((root/'state/shazam_main_verification.json').read_text(encoding='utf8'))
    candidate=json.loads((root/'state/shazam_main_candidate.json').read_text(encoding='utf8'))
    assert result['status']=='passed' and result['correct']==3 and result['total']==3
    assert result['exe_sha256']==candidate['exe_sha256'] and all(result['protected_files'].values())
    record=promote(candidate)
    output=root/'deliver/软件'
    write_json(output/'Shazam替换验证.json',result)
    notes=['# 主程序1.2.0：在线识曲切换为ShazamIO','',f'更新时间：{now()}。',
           '', '使用“开发板实时监测.exe”，进入“听歌识曲”，选择“自动”和20秒。手机外放靠近板载MIC，点录音或按原方式双击桌面唤醒。电脑麦克风不参与。无需AudioTag Key，原账户配置入口已移除。',
           '', '在线成功时来源显示“Shazam”。请求间隔至少30秒；遇429限流至少冷却60秒，并遵守更长Retry-After。冷却状态保存到本机，重启后继续。单条任务不自动重发；需要重试时退出本次识曲，再点“手动重试本次录音”。',
           '', '在线未命中或不可用仍按原规则回退本地歌单。“仅离线”、本地指纹、歌单、历史统计、收藏、抢答、板端采样及固件均保持原状。旧AudioTag历史和任务数据保留，新版不读取其Key或继续旧任务。',
           '', '新版EXE通过9项针对性检查、内置资源与依赖自检，并通过完整主程序识曲进程回放此前3份真实8kHz板端录音：',
           '', '| 原录音 | 返回歌名 | 返回歌手 | 来源 |', '|---|---|---|---|']
    for row in result['rows']:
        answer=row['result'];notes.append(f'| {row["title"]} | {answer["title"]} | {answer["artist"]} | Shazam |')
    notes += ['', '以上为已有板端录音的文件回放验证，未计为新的手机现场试次。原始WAV校验一致；每条在线成功后未运行本地匹配。离线核心源码、全部原资源字节及位流与1.1.5基线一致。新EXE不包含AudioTag客户端或凭据模块。',
              '', '原版1.1.5保存在“历史版本”目录。原报告PDF和复现实验仍对应此前封存版本，作为历史证据保留；本次软件更新、当前SHA256及验证见本目录“软件版本.json”和“Shazam替换验证.json”。',
              '', 'ShazamIO为非官方客户端，依赖Shazam在线服务，限流时界面会明确提示。',
              '', f'当前EXE SHA256：`{candidate["exe_sha256"]}`。']
    (output/'Shazam更新说明.md').write_text('\n'.join(notes)+'\n',encoding='utf8')
    doc=output/'使用说明.md'
    text=doc.read_text(encoding='utf8')
    heading='## 1.2.0在线识曲更新\n\n在线服务已切换为ShazamIO，无需API Key。在主窗口点“听歌识曲”，选择“自动”和20秒，手机外放靠近板载MIC后点“录音识曲”。原来的“仅离线”、本地歌单、收藏与抢答保持原状。\n\n在线来源显示Shazam。遇限流会等待冷却，失败后按原规则查本地歌单；旧AudioTag历史保留。验证与旧版备份位置见同目录“Shazam更新说明.md”。\n\n'
    if '## 1.2.0在线识曲更新' not in text:doc.write_text(heading+text,encoding='utf8')
    index_path=root/'deliver/交付索引.json'
    index=json.loads(index_path.read_text(encoding='utf8'))
    index['active_software']={'file':'软件/开发板实时监测.exe','app_version':'1.2.0','online_provider':'shazamio',
                              'exe_sha256':candidate['exe_sha256'],'firmware_unchanged':True,
                              'offline_unchanged':True,'verification':'软件/Shazam替换验证.json',
                              'notes':'软件/Shazam更新说明.md','previous_version_directory':record['previous_version_directory']}
    index['report_and_reproduction_scope']='原报告和复现实验保持1.1.5等历史版本证据；当前软件见active_software。'
    write_json(index_path,index)
    baseline=json.loads((root/'state/shazam_main_baseline.json').read_text(encoding='utf8'))
    for path,checksum in baseline['files'].items():
        if path.startswith('host/') or path in ('deliver/报告.pdf','release_assets/firmware/recorder_top.bit'):
            assert digest(root/path)==checksum,path
    source=output/'Shazam更新源码';source.mkdir(exist_ok=True)
    for name in ('music_shazam.py','music_worker.py','music_gui.py','music_api_wizard.py','portable_main.py','app_paths.py',
                 'pc_shazam_backend.py','songrec_probe.py','build_shazam_main.py','test_music_shazam.py','verify_shazam_main.py','finalize_shazam_main.py'):
        shutil.copy2(root/'host'/name,source/name)
    shutil.copy2(root/'requirements-runtime.txt',source/'requirements-runtime.txt')
    shutil.copy2(root/'requirements-music.txt',source/'requirements-music.txt')
    shutil.copy2(candidate['requirements_lock'],source/'requirements-locked.txt')
    checks={p.name:digest(p) for p in output.iterdir() if p.is_file() and p.name!='SHA256.json'}
    write_json(output/'SHA256.json',checks)
    assert digest(output/'开发板实时监测.exe')==candidate['exe_sha256']
    delivery={'status':'delivered','time':now(),'app_version':'1.2.0','exe':str(output/'开发板实时监测.exe'),
              'exe_sha256':candidate['exe_sha256'],'online_provider':'shazamio','unit_checks_passed':9,
              'archived_board_recordings_correct':3,'archived_board_recordings_total':3,'new_live_phone_trials':False,
              'offline_source_and_resources_unchanged':True,'firmware_unchanged':True,'historical_report_unchanged':True,
              'previous_version_directory':record['previous_version_directory'],'AudioTag_key_accessed':False,
              'GUI_check':'pending','physical_connection':'pending'}
    write_json(root/'state/shazam_main_delivery.json',delivery)
    print(json.dumps(delivery,ensure_ascii=False))


if __name__=='__main__':main()
