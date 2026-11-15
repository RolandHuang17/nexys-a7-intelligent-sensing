"""User-requested shutdown checkpoint; preserve incomplete raw attempts."""
import json,shutil
from pathlib import Path
from audit import ROOT,Run,write_json,now,sha256

def read(p):return json.loads(Path(p).read_text(encoding='utf8'))
def main():
    r=Run('music_shutdown_checkpoint');r.event('user_pause_requested',user_verbatim='我现在要关电脑了，先停下进度，然后保存，方便后面继续')
    paths=['state/music_wizard.json','state/music_gui.json','state/monitor_gui.json','state/music_upgrade.json','state/resume.json','state/active_checkpoint.json']
    for name in paths:
        p=ROOT/name
        if p.exists():dest=r.path/'before'/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
    ws=read(ROOT/'state/music_wizard.json');cp=ROOT/'runs'/ws['run_id']/'checkpoint.json';saved=read(cp);gui=read(ROOT/'state/music_gui.json')
    shutil.copy2(cp,r.path/'checkpoint_before_pause.json')
    interrupted=saved.get('active')
    if interrupted:
        interrupted={**interrupted,'outcome':'interrupted_by_user_shutdown_not_scored','interrupted_at':now(),
                     'last_GUI_observation':gui,'job_id':gui.get('job_id'),'record_id':gui.get('record_id'),
                     'resume_policy':'重做当前未完成试次；已完成五条不重采，冻结内容若断电则不可恢复'}
        saved.setdefault('interrupted_attempts',[]).append(interrupted)
    saved.update(active=None,mode='resume_ready',time=now(),paused_by_user=True,pause_run_id=r.run_id)
    write_json(cp,saved);write_json(ROOT/'state/music_wizard.json',{'run_id':ws['run_id'],'mode':'resume_ready','step':saved['step'],'active':None,'paused_by_user':True,'pause_run_id':r.run_id,'time':now()})
    complete=saved['results'];online=[x for x in complete if x['kind']=='online'];outside=[x for x in online if x['outside_library']]
    summary={'run_id':r.run_id,'time':now(),'execution_state':'paused_by_user','physical_acceptance_run_id':ws['run_id'],
             'monitor_session_run_id':read(ROOT/'state/monitor_gui.json')['run_id'],'resume_step_zero_based':saved['step'],
             'completed_online_trials':len(online),'online_correct':sum(bool(x.get('online_correct')) for x in online),
             'outside_online_correct':sum(bool(x.get('online_correct')) for x in outside),'outside_online_total':len(outside),
             'double_wake_completed':sum(bool(x.get('wake_success')) for x in online),'double_wake_attempts_completed':len(online),
             'favourite_check':saved.get('favourite_check'),'interrupted_attempt':interrupted,
             'actual_online_cost_yuan':0 if all(x['result'].get('zero_cost_verified') for x in online) else None,
             'exe':read(ROOT/'state/portable_build.json'),'build':read(ROOT/'state/build/status.json'),
             'API_priority_real_run':'20261114T221829_366494_music_online_priority_real','new_report_status':'58页草稿已编译与部分渲染检查；尚未覆盖最终交付PDF',
             'unfinished':['第6条双击补充试次中断，需重做该条，随后余下双击与单敲/打字/只放歌','收藏重启核验、抢歌名和最终原功能回归','最终报告重新生成、双目录编译、逐页检查和复现包封存']}
    write_json(r.path/'result.json',summary);write_json(ROOT/'state/music_pause.json',summary)
    for name in ('resume.json','active_checkpoint.json'):
        p=ROOT/'state'/name;v=read(p) if p.exists() else {};v.update(execution_state='paused_by_user',active_work='desktop_music_recognizer',
             updated=now(),pause_run_id=r.run_id,requires_rebuild=False,next_action='先读docs/听歌识曲恢复节点.md，核对现有固件和EXE，从第6条未完成试次恢复')
        write_json(p,v)
    upgrade=read(ROOT/'state/music_upgrade.json');upgrade.update(status='paused_by_user',updated=now(),pause_run_id=r.run_id,stage='MUSIC5_final_app',
        account='各次真实在线试次后stat核对零付费；余额明细见对应试次result.before/after，密钥仅在凭据管理器')
    write_json(ROOT/'state/music_upgrade.json',upgrade)
    lines=['# 听歌识曲暂停与恢复节点',f'\n保存时间：{now()}。用户要求关机，GUI和串口已停止；没有标记任务完成。',
        '\n## 已确定的要求','自动模式API优先：免费额度检查 → 单次上传 → 任务查询；在线不可用或未命中再查本地。仅离线零请求。离线只作辅助板块，不再强求离线留出准确率；用户已取消实际断网测试。预算仍为0元。',
        '\n## 文件和版本',f'- 主工程：`{ROOT}`',f'- 暂停运行：`{r.run_id}`',f'- 手机实板验收：`{ws["run_id"]}`',
        '- 最新EXE：`deliver/软件/开发板实时监测.exe`，1.1.1',f'- EXE SHA-256：`{summary["exe"]["exe_sha256"]}`',
        '- 最终固件：构建`9f3f5cbf`，运行`20261114T204236_491028_build`，位流SHA-256 `9811ed2cc6904ee33dc51339b43ce17214c59688b2558651443dcbd7f2a908fe`。100MHz WNS0.216ns，BRAM119.5/135。',
        '- 当前板为Nexys A7-100T，PB200-292 REV D；COM5是本机端口，软件按设备发现。断电后SRAM位流丢失，需要重新初始化。',
        '- Key只在Windows凭据管理器；不要读取打印密钥、不要再次要求用户提供Key、不要把凭据配置打包。',
        '\n## 本轮已保存的实际结果','|曲目|双击|最终来源|识别歌名|在线正确|','|---|---|---|---|---|']
    for x in online:
        result=x['result'];lines.append('|'+ '|'.join([x['title'],'成功' if x.get('wake_success') else '未唤醒，已按钮补录',result.get('source','none'),result.get('title','未匹配'),'是' if x.get('online_correct') else '否'])+'|')
    lines += [f'\n在线正确{summary["online_correct"]}/{len(online)}，其中库外{summary["outside_online_correct"]}/{len(outside)}；所有已完成试次费用后置核验为0元。开发成绩不计入该表。',
        f'中键收藏：{json.dumps(summary["favourite_check"],ensure_ascii=False)}',
        '\n此前已保存：5首手机10秒开发录音均160000点、CRC和重复完整读回一致；同组离线调参5/5，3库外+2环境输入无误报，未做独立留出。九条早期10秒录音的8/10秒同输入导出均值14.608/18.252秒。双击开发选择50/20、150—1000ms；11原始校准窗保留。',
        '\n## 中断点和下次顺序','1. 当前第6项（补充双击1/5）已经开始8秒录音，关机请求到来时仅传输到66240/128000点；本条明确记为中断，不算通过。原始串口文件和中断元数据保留。断电会丢失尚在SRAM中的冻结录音。',
        '2. `checkpoint.json`已改为`resume_ready`、`step=5`、`active=null`，原active完整备份在本次暂停运行。不要重置前5条结果、11个校准窗或5首开发采样。',
        '3. 先检查进程和COM设备，再启动相同EXE；若板断电，用软件“初始化此板”加载9f3f5cbf固件。已有免费凭据继续使用。',
        '4. 下一次执行前修正旧基类resume提示中“仍需确认断网”的残留文字；实际OnlineAcceptanceWizard不要求断网。若修改宿主源码，需要重建EXE再续验，并记录新哈希；本次EXE本身无需因关机重建。',
        '5. 打开“听歌识曲→实板验收向导”，续做第6项及余下双击、3次单敲、30秒打字、30秒仅放音乐。随后抢歌名（主流程满足后）、收藏重启持久化、退出识曲后的实时监测/1.5秒完整事件与回放回归。',
        '6. 不再要求实际断网或完整离线留出轮；第二台电脑、第二块板和原生FTDI实测仍待条件，不要再要求用户现在去做。',
        '\n## 报告及交付仍待完成','- 最新识曲草稿：`report/Experiment-template.pdf`，58页；新章约10幅图，源码`host/music_report_content.py`，最后渲染`20261114T222739_891935_pdf_render`，尚需用最终手机结果更新。',
        '- `deliver/报告.pdf`和`deliver/报告源码`、`deliver/复现实验`目前还是旧正式封存，不能当成已包含识曲的新交付。旧件保存在主升级运行before中。',
        '- 报告应保持朴素语言，写明API主用、离线备用、真实未命中和0元账户核验。不能将本地回退算在线成功，也不能把模拟算实板。',
        '- 生成器已更新API流程，但尚未接收本轮最终result.json；需增加每条在线表/耗时与余额数据、最终回归、收藏/抢答证据。',
        '- 老report.py封包只保留旧bit，不能直接用：需增加本轮实测的6daf…和9811…位流、完整音乐原始录音/命令/失败、离线依赖和哈希。Eagles完整原曲music_user和canonical音频不进入交付，只交付指纹。',
        '- 最终按指定latexmk命令在源码和deliver/报告源码分别编译，逐页渲染检查后更新PDF、实测表、演示步骤和复现哈希。旧实验章尾有2行孤立页，可通过压缩问题说明段落修正，不改数据。',
        '\n## 恢复命令', '```powershell', '$env:NEXYS_MONITOR_DATA="D:\\projects\\2222wuxiaoping_codex\\nexys-event-recorder"',
        'Start-Process -FilePath ".\\deliver\\软件\\开发板实时监测.exe" -WindowStyle Hidden',
        '.\\.venv\\Scripts\\python.exe host\\monitor_control.py music_wizard','```',
        '\n先核对state/music_pause.json与对应manifest；所有实测数据原件均在runs目录。']
    note='\n'.join(lines)+'\n'
    (ROOT/'docs/听歌识曲恢复节点.md').write_text(note,encoding='utf8')
    for p in (ROOT/'docs/CONTINUE.md',ROOT.parent/'项目暂停与恢复节点.md'):
        old=p.read_text(encoding='utf8') if p.exists() else ''
        p.write_text(note+'\n---\n以下为历史节点：\n'+old,encoding='utf8')
    r.snapshot('用户关机暂停：保存已有五条在线实板结果、部分读回、模式改动及恢复说明，不新开实验')
    r.event('shutdown_checkpoint_saved',run_id_of_acceptance=ws['run_id'],resume_step=saved['step'],completed_online=len(online),
            online_correct=summary['online_correct'],outside_correct=summary['outside_online_correct'],interrupted_record_id=gui.get('record_id'))
    r.manifest();print(json.dumps({k:summary[k] for k in ('run_id','completed_online_trials','online_correct','outside_online_correct','actual_online_cost_yuan','resume_step_zero_based')},ensure_ascii=False))
if __name__=='__main__':main()
