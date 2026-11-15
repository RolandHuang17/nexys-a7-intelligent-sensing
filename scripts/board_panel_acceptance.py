"""One consolidated physical panel round; observes an existing GUI only.

Default prepares instructions. --run opens the guide after root has programmed
and launched the explicitly selected build. Optional --restart-owned-gui reopens
the verified EXE after it exits, with the same profile and serial selection.
No direct UART, GUI control inbox, API, firmware tool or generated data is used.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import wave
import zlib

STEPS=[
 ('normal','普通监测与数码管数据页',
  '先把 SW15、14、13、12 和 SW0 拨下。保持板子上电，不要按 PROG/RESET。\n'
  '依次切换 SW5:4 的 00、01、10、11：左两位应为 Id、tC、Au、uP，右侧分别为记录编号、板载温度、相对 PCM 幅度、开机秒数。声音幅度不是分贝，温度未做外部标定。'),
 ('effects','灯效、亮度、速度与方向',
  'SW11:10 依次选 00 呼吸、01 彗星、10 对称波、11 原灯映射。\n'
  'SW9:8 的 00/01/10/11 为 25/50/75/100% 亮度；SW7:6 为正常/半速/1.5倍/2倍；SW3 镜像。\n'
  'SW1 开启普通监测的声音响应，SW2 每5秒切换数据页。观察后把 SW11:0 全拨下（SW0 必须为0）。'),
 ('blackout','全灭与采样隔离',
  '先点“开始本项”，把 SW0 拨上至少2秒：16颗 LED、两组 RGB、8位数码管应全部熄灭。\n'
  '这时电脑波形和板端时钟仍继续刷新。观察后把 SW0 拨下，显示恢复。'),
 ('baseline','总开关开启时不重放高电平动作',
  '先把 SW15 拨下，再把 SW14、13、12 全拨上；最后才把 SW15 拨上。\n'
  '保持四个高位开关全高至少2秒。首次开启只建立基线，不应自动进入或启动录音，也不应自动收藏。此项结束先保持四个开关全高。'),
 ('reconnect','重开软件／重连不重放开关动作',
  '保持 SW15、14、13、12 全高，关闭主监测程序，等至少3秒：依赖电脑的字段应显示 PCOFF，板端温度／相对声音／时钟页仍可看。\n'
  '回到本窗口点“已关闭主程序，重新打开测试版”，等待重新连接。\n'
  '本引导窗口保持打开；不要给开发板断电，不要按 PROG/RESET。重新连接后的第一帧只建立基线，不应因高位开关仍高而新录音或收藏。'),
 ('ready','SW14 进入准备状态',
  '保持 SW15 高，先把 SW14、13、12 拨下，稍等，再只把 SW14 拨上。\n'
  '主程序应进入识曲并就绪；双击唤醒开启时显示 tAP tAP / rEAdy、中间四灯双闪，关闭时只显示 rEAdy、四灯稳定。RGB 蓝／紫。确认主程序为“自动”、20秒；不要点录音。'),
 ('record','唯一一首20秒手机录音与结果',
  '手机持续播放 Hotel California（或本次约定歌曲）的原唱片段，扬声器靠近板载 MIC；准备好后把 SW13 从低拨高。\n'
  '应看到 rEC 剩余时间 → SEnd 实际传输百分比 → FInd 在线匹配用时 → PASS / noSonG / Err。未知进度不能假装前进；录音 RGB 橙色，完成条最后一格呼吸。\n'
  '录音中可把 SW0 拨高约2秒再拨低：显示熄灭，录音仍应完整完成。等电脑任务结束后再确认本项；无需另外录一首。'),
 ('favourite','结果一致与 SW12 收藏',
  '核对板上 PASS / noSonG / Err 与电脑本轮实际结果一致。若匹配到歌曲，把 SW12 从低拨高，应显示 FAV、中间四灯绿色约600ms，收藏中应出现该曲；保持高电平不应反复触发。\n'
  '若本轮未匹配，不重复录音：点“未做／异常”，注明“未命中，收藏条件未满足”；该项会如实保留为未验证。'),
 ('exit','关闭总开关不退出；SW14 明确退出',
  '先把 SW13 拨低，再把 SW15 拨低：识曲仍保持启用。此时把 SW13 从低拨高，不能新录音。\n'
  '然后把 SW15 拨高（只重新建立基线），最后把 SW14 拨低，程序才按原规则退出识曲、恢复监测。\n'
  '最后把 SW15、14、13、12 全拨低。'),
]


def load(path):
    for attempt in range(3):
        try:return json.loads(path.read_text(encoding='utf8'))
        except (OSError,ValueError):
            if attempt<2:time.sleep(.025)
    return {}
def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8');temporary.replace(path)
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def last_row(path):
    try:
        with path.open('rb') as stream:
            stream.seek(0,2);stream.seek(max(0,stream.tell()-65536))
            for line in reversed(stream.read().splitlines()):
                try:return json.loads(line)
                except ValueError:continue
    except OSError:pass
    return {}


def snapshot(root):
    gui=load(root/'state/monitor_gui.json');run=gui.get('run_id','')
    if run and (Path(run).name!=run):raise ValueError('Unsafe run id')
    return {'at':datetime.now().astimezone().isoformat(),'gui':gui,
        'music':load(root/'state/music_gui.json'),'panel':load(root/'state/panel_display.json'),
        'telemetry':last_row(root/'runs'/run/'monitor.jsonl') if run else {}}


def validate_recording(root,music):
    wav=Path(music.get('wav') or '').resolve()
    if not wav.is_relative_to(root) or not wav.is_file():raise ValueError('本轮完整 WAV 尚未保存')
    metadata=load(wav.parent/'metadata.json');pcm=wav.parent/'pcm.bin'
    job_metadata_path=wav.parents[2]/'metadata.json';job_metadata=load(job_metadata_path)
    if job_metadata.get('job_id')!=music.get('job_id') or job_metadata.get('record_id')!=music.get('record_id'):
        raise ValueError('WAV 外层任务编号与当前本轮任务不一致')
    with wave.open(str(wav),'rb') as audio:
        info=(audio.getframerate(),audio.getnchannels(),audio.getsampwidth(),audio.getnframes())
    if info!=(8000,1,2,160000):raise ValueError('本轮不是完整20秒/8kHz/160000点录音：'+str(info))
    raw=pcm.read_bytes();crc=zlib.crc32(raw)&0xffffffff
    if len(raw)!=320000 or sha(pcm)!=metadata.get('pcm_sha256') or sha(wav)!=metadata.get('wav_sha256') or crc!=metadata.get('crc32'):
        raise ValueError('本轮完整 PCM/WAV CRC 或哈希不符')
    if metadata.get('record_id')!=music.get('record_id') or job_metadata.get('wav_sha256')!=sha(wav) or job_metadata.get('pcm_sha256')!=sha(pcm):
        raise ValueError('WAV/PCM 与当前任务元数据校验不一致')
    if metadata['last_tick']-metadata['first_tick']!=159999*12500:raise ValueError('录音时间连续性不符')
    return {'wav':str(wav),'pcm':str(pcm),'metadata':metadata,'job_metadata':job_metadata,
        'job_metadata_path':str(job_metadata_path),'bound_job_id':job_metadata['job_id'],'crc32':crc,
        'wav_sha256':sha(wav),'pcm_sha256':sha(pcm),'samples':160000,'sample_rate':8000}


def run_guide(args,report):
    import ttkbootstrap as ttk
    import tkinter as tk
    from tkinter import messagebox,simpledialog
    initial=snapshot(args.data_root)
    if not initial['gui'].get('connected'):raise RuntimeError('先由主任务启动并连接指定主程序，再打开引导')
    if args.expected_build_id and initial['telemetry'].get('build_id')!=args.expected_build_id:
        raise RuntimeError('开发板版本与期望不符；引导不会下载固件')
    if not initial['panel'].get('synced') or initial['panel'].get('disabled'):
        raise RuntimeError('指定主程序的板载显示尚未同步')
    import psutil
    process_exe=Path(psutil.Process(initial['gui']['pid']).exe())
    report.update(status='running',initial=initial,observed_gui_exe=str(process_exe),observed_gui_exe_sha256=sha(process_exe),
        exe_sha256=sha(process_exe),user_visual_confirmed=False,passed=False,guide_gui_restarts=[])
    if args.restart_owned_gui and process_exe.name.lower().startswith('python'):
        raise RuntimeError('精确重开只支持冻结测试EXE；请由主任务先启动冻结版')
    if args.expected_exe_sha256 and report['observed_gui_exe_sha256']!=args.expected_exe_sha256:
        raise RuntimeError('指定主程序 EXE 哈希不符')
    window=ttk.App(title='板载面板 · 一轮实板检查',theme='bootstrap-light',high_dpi=False)
    window.geometry('940x760');window.minsize(760,600)
    holder=ttk.Frame(window,padding=22);holder.pack(fill='both',expand=True)
    title=tk.StringVar();text=tk.StringVar();live=tk.StringVar();progress=tk.StringVar()
    ttk.Label(holder,text='板载 LED / RGB / 八位数码管',font=('Microsoft YaHei UI',20,'bold')).pack(anchor='w')
    ttk.Label(holder,text='本窗口观察并记录；可选重开按钮只重开同一测试版和数据目录。',wraplength=840).pack(anchor='w',pady=(6,18))
    ttk.Label(holder,textvariable=progress,font=('Microsoft YaHei UI',10)).pack(anchor='w')
    ttk.Label(holder,textvariable=title,font=('Microsoft YaHei UI',15,'bold')).pack(anchor='w',pady=(8,12))
    instruction=ttk.Label(holder,textvariable=text,wraplength=840,justify='left',font=('Microsoft YaHei UI',12));instruction.pack(fill='x',anchor='w')
    ttk.Separator(holder).pack(fill='x',pady=18)
    ttk.Label(holder,textvariable=live,wraplength=840,justify='left').pack(fill='x')
    buttons=ttk.Frame(holder);buttons.pack(side='bottom',fill='x',pady=(18,0))
    reopen=ttk.Button(holder,text='已关闭主程序，重新打开测试版')
    reopen.pack(side='bottom',anchor='w',pady=(12,0))
    index=0;active=None;seen={};current=initial
    def persist():save(args.output,report)
    def event(kind,**fields):
        with args.output.with_suffix('.jsonl').open('a',encoding='utf8') as stream:
            stream.write(json.dumps({'at':datetime.now().astimezone().isoformat(),'kind':kind,**fields},ensure_ascii=False)+'\n')
    def show():
        progress.set(f'{index+1} / {len(STEPS)}');title.set(STEPS[index][1]);text.set(STEPS[index][2])
        start.configure(state='normal');yes.configure(state='disabled');no.configure(state='disabled')
        reopen.configure(state='normal' if args.restart_owned_gui and STEPS[index][0]=='reconnect' else 'disabled')
    def begin():
        nonlocal active,seen
        active=snapshot(args.data_root);seen={'busy':False,'master_off_enabled':False,'disabled_record_rise':False,'last_mask':None,'phases':[]}
        event('step_started',step=STEPS[index][0],snapshot=active)
        start.configure(state='disabled');yes.configure(state='normal');no.configure(state='normal')
    def restart():
        if not args.restart_owned_gui or STEPS[index][0]!='reconnect' or active is None:
            messagebox.showinfo('尚未开始本项','请先点“开始本项观察”，再关闭主程序。',parent=window);return
        try:
            old_pid=active['gui'].get('pid');latest=snapshot(args.data_root)['gui'];current_pid=latest.get('pid')
            if old_pid and psutil.pid_exists(old_pid):raise RuntimeError('原主程序尚未完全退出，请先关闭并稍等。')
            if current_pid and psutil.pid_exists(current_pid):raise RuntimeError('指定数据目录已有主程序，请勿重复启动。')
            if sha(process_exe)!=report['exe_sha256']:raise RuntimeError('测试EXE已改变，不能重开另一份二进制。')
            import os,subprocess
            command=[str(process_exe)]
            if args.serial:command+=['--serial',args.serial]
            environment={**os.environ,'NEXYS_MONITOR_DATA':str(args.data_root),'NEXYS_PORTABLE_RUNTIME':'1'}
            process=subprocess.Popen(command,env=environment,cwd=process_exe.parent,
                creationflags=subprocess.CREATE_NO_WINDOW)
            entry={'pid':process.pid,'exe_sha256':report['exe_sha256'],'command':command,
                'data_root':str(args.data_root),'program_firmware':False,'at':datetime.now().astimezone().isoformat()}
            report['guide_gui_restarts'].append(entry);event('same_profile_gui_restarted',**entry);persist()
            reopen.configure(state='disabled')
        except Exception as error:messagebox.showinfo('未重开主程序',str(error),parent=window)
    reopen.configure(command=restart)
    def problems():
        key=STEPS[index][0];gui=current['gui'];music=current['music'];row=current['telemetry'];mask=row.get('switches',0)
        errors=[]
        if not gui.get('connected') or (gui.get('last_receive_age_s') or 0)>1.5:errors.append('主程序尚无新鲜实板数据')
        if args.expected_build_id and row.get('build_id')!=args.expected_build_id:errors.append('板端版本不符')
        if key=='blackout' and (gui.get('last_board_tick') or 0)<=(active['gui'].get('last_board_tick') or 0)+100000000:errors.append('尚未观察到至少1秒板端采样继续')
        if key=='baseline' and (mask&0xf000!=0xf000 or music.get('busy') or music.get('job_id')!=active['music'].get('job_id')):errors.append('高位开关基线或未自动录音条件不符')
        if key=='reconnect' and (gui.get('run_id')==active['gui'].get('run_id') or mask&0xf000!=0xf000 or music.get('busy')):errors.append('尚未观察到高位保持时新主程序会话且不录音')
        if key=='ready':
            status=music.get('status') or {}
            if not music.get('enabled') or music.get('busy'):errors.append('识曲尚未进入空闲准备状态')
            if music.get('policy')!='auto' or status.get('target_samples')!=160000 or status.get('sample_rate')!=8000:
                errors.append('请在主程序选择“自动”、20秒，并等待配置为160000点/8kHz')
        if key=='record':
            if not seen['busy'] or music.get('busy') or music.get('job_id')==active['music'].get('job_id'):errors.append('尚未观察到本轮新录音启动并结束')
            else:
                try:report['recording']=validate_recording(args.data_root,music)
                except Exception as error:errors.append(str(error))
        if key=='favourite':
            result=music.get('result') or {};song=result.get('song_id')
            if not result.get('matched') or not song:errors.append('本轮未命中，收藏条件未满足；请如实记未验证')
            else:
                try:
                    with sqlite3.connect('file:'+(args.data_root/'music/music.sqlite3').as_posix()+'?mode=ro',uri=True) as db:
                        present=db.execute('SELECT COUNT(*) FROM favourites WHERE song_id=?',(song,)).fetchone()[0]
                    if not present or 9 not in seen['phases']:errors.append('尚未同时观察到 FA 状态和该曲收藏记录')
                except Exception as error:errors.append('收藏只读核对失败：'+type(error).__name__)
        if key=='exit' and (not seen['master_off_enabled'] or not seen['disabled_record_rise'] or music.get('enabled') or music.get('busy')):errors.append('请完成总开关关闭仍启用、禁用快捷录音不生效和SW14显式退出三步')
        return errors
    def finish(passed):
        nonlocal index,active
        if active is None:return
        observation='肉眼观察符合本项描述'
        if passed:
            errors=problems()
            if errors:messagebox.showinfo('本项还未完成','\n'.join(errors),parent=window);return
        else:
            observation=simpledialog.askstring('记录实际情况','请注明未做、没看清或异常现象：',parent=window)
            if observation is None:return
        item={'step':STEPS[index][0],'title':STEPS[index][1],'passed':passed,
            'visual_confirmation_by_user':passed,'observation':observation,'before':active,'after':current,'observed':seen}
        report['steps'].append(item);event('step_completed',**item);active=None;index+=1
        if index==len(STEPS):
            passed_all=all(x['passed'] and x['visual_confirmation_by_user'] for x in report['steps'])
            report.update(status='passed' if passed_all else 'completed_with_limitations',passed=passed_all,
                user_visual_confirmed=passed_all,completed_at=datetime.now().astimezone().isoformat(),
                validated_recordings=int('recording' in report),new_live_phone_recordings=int('recording' in report),
                game_physical_test=False);persist()
            title.set('本轮检查完成');text.set('记录已保存。请回到 Codex 回复“完成”；未做成的项已保留说明。')
            progress.set(f'{len(STEPS)} / {len(STEPS)}');start.configure(state='disabled');yes.configure(state='disabled');no.configure(state='disabled')
        else:persist();show()
    def poll():
        nonlocal current
        current=snapshot(args.data_root);music=current['music'];panel=current['panel'];mask=current['telemetry'].get('switches',0)
        if active is not None:
            seen['busy']|=bool(music.get('busy'))
            seen['master_off_enabled']|=bool(not mask&0x8000 and music.get('enabled') and not music.get('busy'))
            old=seen['last_mask']
            if old is not None and not mask&0x8000 and mask&0x2000 and not old&0x2000 and music.get('job_id')==active['music'].get('job_id'):seen['disabled_record_rise']=True
            seen['last_mask']=mask
            phase=(panel.get('last_applied') or {}).get('phase')
            if phase is not None and phase not in seen['phases']:seen['phases'].append(phase)
        live.set(f"实板连接：{current['gui'].get('connected')}  · 开关 0x{mask:04X}\n"
            f"识曲启用：{music.get('enabled')}  忙：{music.get('busy')}  当前任务：{music.get('job_id') or '—'}\n"
            f"显示同步：{panel.get('synced')}  最近确认阶段：{(panel.get('last_applied') or {}).get('phase_name','—')}")
        window.after(250,poll)
    def close():
        if report.get('status')=='running':report.update(status='interrupted',closed_at=datetime.now().astimezone().isoformat());persist()
        window.destroy()
    start=ttk.Button(buttons,text='开始本项观察',command=begin);start.pack(side='left')
    yes=ttk.Button(buttons,text='看到了预期现象，下一项',command=lambda:finish(True));yes.pack(side='left',padx=10)
    no=ttk.Button(buttons,text='未做／异常，记录后继续',command=lambda:finish(False));no.pack(side='right')
    holder.bind('<Configure>',lambda e:instruction.configure(wraplength=max(500,e.width-20)))
    window.protocol('WM_DELETE_WINDOW',close);persist();show();poll();window.mainloop()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--expected-build-id');parser.add_argument('--expected-exe-sha256')
    parser.add_argument('--serial');parser.add_argument('--restart-owned-gui',action='store_true')
    parser.add_argument('--run',action='store_true');args=parser.parse_args()
    args.data_root=args.data_root.resolve();args.output=args.output.resolve()
    report={'status':'prepared_not_run','data_root':str(args.data_root),'steps':[],
        'user_visual_confirmed':False,'passed':False,'planned_phone_recordings':1,'new_live_phone_recordings':0,
        'expected_build_id':args.expected_build_id,'expected_exe_sha256':args.expected_exe_sha256,
        'guide_serial_opens':0,'guide_control_requests':0,'guide_network_requests':0,'firmware_programmed_by_guide':False,
        'planned_steps':[{'id':key,'title':title,'instructions':text} for key,title,text in STEPS]}
    if args.run:run_guide(args,report)
    else:save(args.output,report);print('Prepared only; add --run after the selected board build and GUI are ready.')


if __name__=='__main__':main()
