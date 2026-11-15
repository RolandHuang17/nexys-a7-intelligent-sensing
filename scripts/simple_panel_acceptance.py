"""Three-step panel observation using the existing GUI's record action.

Default only prepares the plan. --run observes the selected running GUI and,
after the user's record button click, sends ONE existing music_record control.
No UART, firmware programming, new recognition implementation or fake data.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import time
import uuid

from board_panel_acceptance import load,save,sha,snapshot,validate_recording

KIND='simple_panel_acceptance_v2'


def run(args,report):
    import ttkbootstrap as ttk
    import tkinter as tk
    from tkinter import messagebox,simpledialog
    import psutil
    initial=snapshot(args.data_root);gui=initial['gui']
    if not gui.get('connected') or gui.get('last_receive_age_s') is None or gui['last_receive_age_s']>1.5:
        raise RuntimeError('请由Codex先连接指定测试主程序')
    if initial['telemetry'].get('build_id')!=args.expected_build_id:raise RuntimeError('板端版本不符')
    executable=Path(psutil.Process(gui['pid']).exe());checksum=sha(executable)
    if checksum!=args.expected_exe_sha256:raise RuntimeError('实际主程序EXE哈希不符')
    if not initial['panel'].get('synced') or initial['panel'].get('disabled'):raise RuntimeError('板载显示尚未同步')
    report.update(status='running',exe_sha256=checksum,initial=initial,
        observed_gui_exe=str(executable),run_id=gui['run_id'])
    window=ttk.App(title='板载显示 · 简单测试',theme='bootstrap-light',high_dpi=False)
    window.geometry('820x520');window.minsize(700,430)
    body=ttk.Frame(window,padding=26);body.pack(fill='both',expand=True)
    heading=tk.StringVar();instructions=tk.StringVar();status=tk.StringVar(value='等待准备')
    ttk.Label(body,text='只做一首歌，三步完成',font=('Microsoft YaHei UI',21,'bold')).pack(anchor='w')
    ttk.Label(body,textvariable=heading,font=('Microsoft YaHei UI',15,'bold')).pack(anchor='w',pady=(20,12))
    label=ttk.Label(body,textvariable=instructions,font=('Microsoft YaHei UI',12),wraplength=750,justify='left')
    label.pack(fill='x',anchor='w')
    ttk.Separator(body).pack(fill='x',pady=22)
    ttk.Label(body,textvariable=status,wraplength=750,justify='left').pack(fill='x')
    controls=ttk.Frame(body);controls.pack(side='bottom',fill='x',pady=(20,0))
    stage='ready';current=initial;before_record=None;request_id=None;request_at=None;active_job=None
    busy_seen=False;last_phase=None;last_business_stage=None;record_validated=False
    def persist():save(args.output,report)
    def event(kind,**values):
        with args.output.with_suffix('.jsonl').open('a',encoding='utf8') as stream:
            stream.write(json.dumps({'at':datetime.now().astimezone().isoformat(),'kind':kind,**values},ensure_ascii=False)+'\n')
    def fresh():
        gui=current['gui']
        if gui.get('run_id')!=report['run_id']:raise ValueError('主程序会话已改变，请交给Codex处理')
        if not gui.get('connected') or gui.get('last_receive_age_s') is None or gui['last_receive_age_s']>1.5:raise ValueError('主程序暂未收到新数据，请稍等')
        if current['telemetry'].get('build_id')!=args.expected_build_id:raise ValueError('开发板版本已改变')
    def ready_check():
        fresh();music=current['music'];status_row=music.get('status') or {}
        if not current['telemetry'].get('switches',0)&0x8000 or not music.get('enabled'):raise ValueError('请把板上SW15拨上，稍等识曲就绪')
        if music.get('busy'):raise ValueError('当前任务还没结束，请稍等')
        if music.get('policy')!='auto' or status_row.get('target_samples')!=160000 or status_row.get('sample_rate')!=8000:
            raise ValueError('主程序请选择“自动”和“20秒”，然后稍等就绪')
    def show_ready():
        heading.set('1 / 3　打开识曲开关')
        instructions.set('把板上 SW15 拨上。看到 rEAdy 或 tAP 后，点下面按钮。\n其他开关都不用动。')
        primary.configure(text='准备好了，下一步',state='normal')
    def proceed():
        nonlocal stage,before_record,request_id,request_at
        try:
            if stage=='ready':
                ready_check();report['steps'].append({'step':'ready','passed':True,'snapshot':current})
                event('ready_confirmed_by_user',snapshot=current);stage='phone';persist()
                heading.set('2 / 3　播放音乐，开始录音')
                instructions.set('手机播放你要测试的歌，扬声器靠近板载 MIC。\n音乐播放后点下面按钮，录满20秒；接着会自动发送并识曲。')
                primary.configure(text='音乐已播放，开始20秒录音')
            elif stage=='phone':
                ready_check();before_record=current;request_id=uuid.uuid4().hex;request_at=time.monotonic()
                command={'id':request_id,'target_run_id':report['run_id'],'action':'music_record','arguments':{}}
                save(args.data_root/'state/monitor_control.json',command)
                report['guide_control_requests']=1;report['record_request']=command;report['before_record']=before_record
                event('existing_GUI_music_record_requested',request=command,snapshot=current)
                stage='recording';persist();primary.configure(text='正在录音和识曲…',state='disabled')
                instructions.set('请持续播放满20秒。观察板上录音、发送和识曲显示；完成后会提示你关掉SW15。')
            elif stage=='finish':
                fresh();music=current['music'];mask=current['telemetry'].get('switches',0)
                if mask&0x8000 or music.get('enabled') or music.get('busy'):raise ValueError('请把 SW15 拨下，等待恢复普通监测后再点完成')
                if not record_validated:raise ValueError('本轮完整录音尚未校验')
                report['steps'].append({'step':'finish','passed':True,'visual_confirmation_by_user':True,'snapshot':current})
                report.update(status='passed',passed=True,user_visual_confirmed=True,new_live_phone_recordings=1,
                    completed_at=datetime.now().astimezone().isoformat(),checks={
                        'sw15_entered_ready':True,'one_existing_GUI_record_request':report['guide_control_requests']==1,
                        'new_bound_20s_8k_crc':True,'sw15_off_restored_monitoring':True,'user_visual_confirmation':True})
                event('user_confirmed_display_and_finished',snapshot=current);persist();stage='done'
                heading.set('测试完成');instructions.set('记录已保存。回到 Codex 回复“完成”即可。')
                primary.configure(text='已完成',state='disabled');problem.configure(state='disabled')
        except Exception as error:
            event('observer_or_readiness_issue',message=str(error),snapshot=current)
            messagebox.showinfo('稍等一下',str(error),parent=window)
    def note_problem():
        nonlocal stage
        text=simpledialog.askstring('记录问题','哪里不正常？简单说一下即可。',parent=window)
        if text is None:return
        report.update(status='completed_with_limitations',passed=False,user_visual_confirmed=False,
            observation=text,new_live_phone_recordings=int(record_validated),completed_at=datetime.now().astimezone().isoformat())
        event('user_reported_problem',observation=text,snapshot=current);persist();stage='done'
        heading.set('问题已记录');instructions.set('请回到 Codex 回复“完成”，我会根据记录处理。')
        primary.configure(state='disabled');problem.configure(state='disabled')
    def poll():
        nonlocal current,active_job,busy_seen,last_phase,last_business_stage,stage,record_validated
        current=snapshot(args.data_root);music=current['music'];panel=current['panel'];state=music.get('status') or {}
        phase=(panel.get('last_applied') or {}).get('phase')
        if phase!=last_phase:
            event('observed_PANEL_ack_phase',phase=(panel.get('last_applied') or {}),snapshot=current);last_phase=phase
        if stage=='recording':
            if current['gui'].get('run_id')!=report['run_id']:
                status.set('主程序会话已改变，先别重复录音；请记录问题。')
            else:
                if music.get('busy') and music.get('job_id') and music.get('job_id')!=before_record['music'].get('job_id'):
                    if active_job is None:
                        active_job=music['job_id'];report['active_job_id']=active_job
                        event('actual_new_recording_started',snapshot=current);persist()
                    if music['job_id']==active_job:busy_seen=True
                if busy_seen and not music.get('busy') and music.get('job_id')==active_job and music.get('wav'):
                    try:
                        result=music.get('result') or {}
                        if result.get('job_id')!=active_job:raise ValueError('等待当前录音的识曲结果')
                        recording=validate_recording(args.data_root,music)
                        report.update(recording=recording,result=result,new_live_phone_recordings=1)
                        report['steps'].append({'step':'record','passed':True,'snapshot':current})
                        event('actual_recording_completed_and_verified',recording=recording,result=result,snapshot=current)
                        record_validated=True;stage='finish';persist()
                        heading.set('3 / 3　关掉开关，确认显示')
                        instructions.set('板上应显示与电脑一致的结果。\n把 SW15 拨下，恢复普通监测后，确认本轮灯光和数字显示正常。')
                        primary.configure(text='显示正常，完成',state='normal')
                    except Exception as error:
                        status.set(str(error))
                if stage=='recording':
                    if state.get('state') in (1,2):
                        status.set(f"正在录音：{min(20,state.get('samples',0)/8000):.1f} / 20 秒")
                        observed='recording'
                    elif panel.get('desired_phase')==2:
                        value=panel.get('progress',65535)
                        status.set('正在发送录音'+(f'：{value/10:.1f}%' if value!=65535 else ''))
                        observed='transfer'
                    elif busy_seen:status.set('正在识曲，请稍候');observed='matching'
                    else:
                        status.set('等待主程序开始录音，请勿重复点击' if time.monotonic()-request_at<8 else '主程序尚未开始本轮录音，请记录问题')
                        observed='waiting_start'
                    if observed!=last_business_stage:
                        event('observed_business_stage',stage=observed,snapshot=current);last_business_stage=observed
            ack=load(args.data_root/'state/monitor_control_result.json')
            if ack.get('id')==request_id and not report.get('record_request_ack'):
                report['record_request_ack']=ack;event('GUI_control_acknowledged',ack=ack);persist()
        elif stage=='finish':
            result=report.get('result') or {}
            status.set(('识别结果：'+result.get('title','') if result.get('matched') else '本次没有确定歌名，录音已完整保存。')+'\n最后只需把 SW15 拨下。')
        elif stage in ('ready','phone'):
            status.set('SW15：'+('已打开' if current['telemetry'].get('switches',0)&0x8000 else '关闭')+'　·　'+('识曲已就绪' if music.get('enabled') and not music.get('busy') else '等待就绪'))
        window.after(250,poll)
    def close():
        if report.get('status')=='running':
            report.update(status='interrupted',passed=False,user_visual_confirmed=False,new_live_phone_recordings=int(record_validated));persist()
        window.destroy()
    primary=ttk.Button(controls,command=proceed);primary.pack(side='left')
    problem=ttk.Button(controls,text='有异常，记录问题',command=note_problem);problem.pack(side='right')
    body.bind('<Configure>',lambda e:label.configure(wraplength=max(580,e.width-12)))
    window.protocol('WM_DELETE_WINDOW',close);persist();show_ready();poll();window.mainloop()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root',required=True,type=Path)
    parser.add_argument('--output',type=Path,default=Path('docs/板载面板实板验收.json'))
    parser.add_argument('--expected-build-id',required=True);parser.add_argument('--expected-exe-sha256',required=True)
    parser.add_argument('--run',action='store_true');args=parser.parse_args()
    args.data_root=args.data_root.resolve();args.output=args.output.resolve()
    report={'kind':KIND,'status':'prepared_not_run','passed':False,'user_visual_confirmed':False,
        'data_root':str(args.data_root),'expected_build_id':args.expected_build_id,
        'expected_exe_sha256':args.expected_exe_sha256,'steps':[],'guide_control_requests':0,
        'guide_serial_opens':0,'guide_network_requests':0,'firmware_programmed_by_guide':False,
        'planned_phone_recordings':1,'new_live_phone_recordings':0,'game_physical_test':False,
        'simple_steps':['SW15打开，准备','手机放歌，点开始20秒录音','SW15关闭，确认显示正常']}
    if args.run:run(args,report)
    else:save(args.output,report);print('Prepared only: SW15 ON -> one GUI recording -> SW15 OFF and confirm.')


if __name__=='__main__':main()
