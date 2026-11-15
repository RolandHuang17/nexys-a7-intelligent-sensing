"""Standalone PC microphone test entry point; never imports the board application."""
import argparse,json,os,sys,threading,queue,wave,winsound
from pathlib import Path


def bootstrap_data(folder=None):
    default=Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData/Local'))/'AudioTagMicTest'
    folder=Path(folder or os.environ.get('AUDIOTAG_PC_MIC_DATA',default)).resolve();folder.mkdir(parents=True,exist_ok=True)
    os.environ['NEXYS_MONITOR_DATA']=str(folder);os.environ['NEXYS_PORTABLE_RUNTIME']='1'
    return folder


class App:
    def __init__(self,folder):
        import tkinter as tk
        from tkinter import ttk
        from pc_mic_backend import Backend,PC_MIC_VERSION
        self.tk=tk;self.ttk=ttk;self.folder=folder;self.queue=queue.Queue();self.busy=False;self.closing=False
        self.stop=threading.Event();self.record=None;self.devices=[];self.root=tk.Tk();self.root.title('电脑麦克风 · AudioTag API对照测试')
        width=min(1060,self.root.winfo_screenwidth()-60);height=min(780,self.root.winfo_screenheight()-80)
        self.root.geometry(f'{width}x{height}');self.root.minsize(840,600)
        self.backend=Backend(lambda kind,**data:self.queue.put((kind,data)))
        self.device=tk.StringVar();self.seconds=tk.StringVar(value='20');self.status=tk.StringVar(value='选择电脑麦克风，手机外放歌曲后开始。')
        self.song=tk.StringVar(value='电脑麦克风 → AudioTag');self.service=tk.StringVar(value='尚未录音；不连接开发板，也不查本地歌单。')
        self.stats=tk.StringVar(value='沿用当前Windows用户已保存的AudioTag凭据，上传前核对免费额度。')
        self.level=tk.StringVar(value='输入电平：等待录音');self.progress=tk.DoubleVar(value=0)
        header=tk.Frame(self.root,bg='#173b5c');header.pack(fill='x')
        tk.Label(header,text='电脑麦克风 · API对照',font=('Microsoft YaHei UI',21,'bold'),fg='white',bg='#173b5c').pack(side='left',padx=20,pady=16)
        tk.Label(header,text='独立程序  v'+PC_MIC_VERSION,fg='#c3dbe9',bg='#173b5c').pack(side='right',padx=20)
        container=ttk.Frame(self.root);container.pack(fill='both',expand=True)
        viewport=tk.Canvas(container,highlightthickness=0);scroll=ttk.Scrollbar(container,orient='vertical',command=viewport.yview)
        viewport.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');viewport.pack(side='left',fill='both',expand=True)
        frame=ttk.Frame(viewport,padding=14);window=viewport.create_window((0,0),window=frame,anchor='nw')
        frame.bind('<Configure>',lambda e:viewport.configure(scrollregion=viewport.bbox('all')))
        viewport.bind('<Configure>',lambda e:viewport.itemconfigure(window,width=e.width))
        self.root.bind_all('<MouseWheel>',lambda e:viewport.yview_scroll(-int(e.delta/120),'units') if e.widget.winfo_class()!='Treeview' else None)
        inputs=ttk.Frame(frame);inputs.pack(fill='x')
        ttk.Label(inputs,text='声音输入').pack(side='left')
        self.devices_box=ttk.Combobox(inputs,textvariable=self.device,state='readonly',width=46);self.devices_box.pack(side='left',padx=8)
        ttk.Button(inputs,text='刷新设备',command=self.refresh_devices).pack(side='left')
        ttk.Label(inputs,text='录音长度').pack(side='left',padx=(16,5))
        ttk.Combobox(inputs,textvariable=self.seconds,values=('20','30'),state='readonly',width=5).pack(side='left');ttk.Label(inputs,text='秒').pack(side='left',padx=4)
        ttk.Label(frame,text='录满后只向AudioTag上传一次；免费额度不足或无法核验时不上传。请选能清楚录到手机外放的麦克风。',wraplength=990,foreground='#60758a').pack(anchor='w',pady=(12,8))
        buttons=ttk.Frame(frame);buttons.pack(fill='x',pady=6)
        self.start_button=ttk.Button(buttons,text='开始录音并调用API',command=self.start);self.start_button.pack(side='left',padx=(0,8))
        self.stop_button=ttk.Button(buttons,text='停止录音，不上传',command=self.stop.set,state='disabled');self.stop_button.pack(side='left',padx=4)
        self.verify_button=ttk.Button(buttons,text='检查免费账户',command=self.verify);self.verify_button.pack(side='left',padx=4)
        self.resume_button=ttk.Button(buttons,text='继续查询原任务',command=self.resume,state='disabled');self.resume_button.pack(side='left',padx=4)
        self.import_button=ttk.Button(buttons,text='干净WAV对照',command=self.import_wav);self.import_button.pack(side='right')
        ttk.Progressbar(frame,variable=self.progress,maximum=100).pack(fill='x',pady=(14,5))
        ttk.Label(frame,textvariable=self.level,foreground='#60758a').pack(anchor='w')
        ttk.Label(frame,textvariable=self.status,font=('Microsoft YaHei UI',12,'bold'),foreground='#168c82',wraplength=990).pack(anchor='w',pady=14)
        card=ttk.LabelFrame(frame,text='服务实际返回与软件判断',padding=14);card.pack(fill='both',expand=True)
        ttk.Label(card,textvariable=self.song,font=('Microsoft YaHei UI',20,'bold'),wraplength=950).pack(anchor='w',pady=4)
        ttk.Label(card,textvariable=self.service,wraplength=950).pack(anchor='w',pady=8)
        columns=('title','artist','confidence');self.candidates=ttk.Treeview(card,columns=columns,show='headings',height=7)
        for key,title,width in [('title','API返回的候选歌名',360),('artist','歌手',300),('confidence','服务置信度',130)]:
            self.candidates.heading(key,text=title);self.candidates.column(key,width=width,minwidth=80)
        self.candidates.pack(fill='both',expand=True,pady=8)
        ttk.Label(frame,textvariable=self.stats,wraplength=990).pack(anchor='w',pady=10)
        bottom=ttk.Frame(frame);bottom.pack(fill='x')
        ttk.Button(bottom,text='试听原录音',command=lambda:self.play(False)).pack(side='left',padx=(0,8))
        ttk.Button(bottom,text='试听实际上传副本',command=lambda:self.play(True)).pack(side='left')
        ttk.Button(bottom,text='打开记录目录',command=lambda:os.startfile(str(folder))).pack(side='right')
        ttk.Label(frame,text='对比时尽量使用同一首、同一播放位置和相同音量。双方都失败仍不能直接归因于API，可再用干净WAV对照。',wraplength=990,foreground='#60758a').pack(anchor='w',pady=(12,0))
        self.refresh_devices();self.restore();self.root.protocol('WM_DELETE_WINDOW',self.close);self.root.after(80,self.drain)
    def refresh_devices(self):
        if self.busy:return
        from pc_mic_capture import input_devices
        try:
            self.devices=input_devices();labels=[d['label'] for d in self.devices];self.devices_box.configure(values=labels)
            if self.device.get() not in labels and labels:self.device.set(next((d['label'] for d in self.devices if not d['loopback_name']),labels[0]))
            if not labels:self.status.set('未检测到电脑录音设备，请接好麦克风后刷新。')
        except Exception as error:self.status.set(str(error))
    def run_background(self,function):
        if self.busy:return
        self.busy=True
        for button in (self.start_button,self.verify_button,self.import_button,self.resume_button):button.configure(state='disabled')
        def work():
            try:function()
            except Exception as error:self.queue.put(('error',{'message':str(error)}))
            finally:self.queue.put(('idle',{}))
        threading.Thread(target=work,daemon=True).start()
    def start(self):
        if self.busy:return
        device=next((d for d in self.devices if d['label']==self.device.get()),None)
        if device is None:self.status.set('请先选择可用的电脑麦克风。');return
        self.stop.clear();seconds=int(self.seconds.get());self.progress.set(0);self.candidates.delete(*self.candidates.get_children())
        self.song.set('正在听电脑麦克风');self.service.set('请持续外放，录满后才调用API。');self.stop_button.configure(state='normal')
        def work():
            from pc_mic_capture import record
            from audit import write_json,sha256
            run,job=self.backend.new_trial();path=run.path/'computer_microphone_original.wav'
            run.event('pc_microphone_recording_started',device=device,seconds=seconds)
            try:
                metadata=record(device['id'],seconds,path,stop=self.stop,progress=lambda n,total,level:self.queue.put(('capture_progress',{'samples':n,'total':total,'level':level})))
            except Exception as error:
                write_json(run.path/'capture_failure.json',{'error_type':type(error).__name__,'message':str(error),'API_uploads':0,'source':'computer_microphone'})
                run.manifest();raise
            metadata.update(input_device=device,wav_sha256=sha256(path));write_json(run.path/'recording.json',metadata)
            job.update(wav=str(path),metadata=metadata)
            if not metadata['complete']:
                job.update(status='cancelled_not_uploaded');write_json(run.path/'trial.json',job);run.manifest()
                self.queue.put(('cancelled',{'record':job}));return
            self.queue.put(('stage',{'text':'录音完整，开始免费额度检查与API识别'}))
            self.queue.put(('result',{'record':self.backend.recognize(run,job,path,metadata)}))
        self.run_background(work)
    def verify(self):self.run_background(lambda:self.queue.put(('verified',{'result':self.backend.verify()})))
    def resume(self):
        pending=self.backend.pending()
        if not pending:self.status.set('没有可续查的在线任务。');return
        item=pending[0]
        if not item['wav'] or not Path(item['wav']).is_file():self.status.set('原录音文件不存在，未提交任何请求。');return
        def work():
            from audit import Run,write_json
            run=Run('pc_mic_resume_query');job={'id':item['job_id'],'run_id':run.run_id,'directory':str(run.path),'source':'resumed_original_PC_task'}
            self.queue.put(('result',{'record':self.backend.recognize(run,job,item['wav'])}))
        self.run_background(work)
    def import_wav(self):
        if self.busy:return
        from tkinter import filedialog
        from pc_mic_backend import validate_wav
        filename=filedialog.askopenfilename(parent=self.root,title='选择15至60秒、8/16kHz单声道PCM16 WAV',filetypes=[('PCM WAV','*.wav')])
        if not filename:return
        try:metadata=validate_wav(filename)
        except Exception as error:self.status.set(str(error));return
        def work():
            import shutil
            run,job=self.backend.new_trial('clean_WAV_reference_not_microphone');copy=run.path/'reference_original.wav';shutil.copy2(filename,copy)
            self.queue.put(('result',{'record':self.backend.recognize(run,job,copy,metadata)}))
        self.run_background(work)
    def show_result(self,record):
        self.record=record;result=record['result'];state=record.get('service_status')
        labels={'found':'服务返回found（有候选）','not found':'服务返回not found（未命中）','wait':'服务仍在处理'}
        self.service.set(labels.get(state,'服务状态：'+result.get('message',result.get('reason','未完成')))+'；软件判断：'+('确定匹配' if result.get('matched') else result.get('message',result.get('reason','未确定'))))
        self.song.set(result['title']+' — '+result['artist'] if result.get('matched') else ('API返回候选，尚未确定' if record.get('candidates') else '本次未识出歌曲'))
        self.candidates.delete(*self.candidates.get_children())
        for candidate in record.get('candidates',[])[:30]:self.candidates.insert('','end',values=(candidate['title'],candidate['artist'],str(candidate['confidence'])+'%'))
        before=result.get('before') or {};after=result.get('after') or {}
        fees='0元，已后置核验' if result.get('zero_cost_verified') else '费用核验尚未完成'
        self.stats.set('免费秒数 '+str(before.get('identification_free_sec_remainder','—'))+' → '+str(after.get('identification_free_sec_remainder','—'))+'；'+fees+'；本次API阶段 '+f'{record.get("recognition_wall_s",0):.2f}'+'秒；上传 '+str(record.get('API_actions_this_call',[]).count('identify'))+'次。')
        self.status.set('结果和脱敏后的服务原始返回已保存，可试听原录音与上传副本。')
    def restore(self):
        path=self.folder/'latest.json'
        if path.exists():
            try:self.show_result(json.loads(path.read_text(encoding='utf8')))
            except (OSError,ValueError,KeyError):pass
        self.resume_button.configure(state='normal' if self.backend.pending() else 'disabled')
    def play(self,upload):
        if self.busy:self.status.set('请等待当前录音和识别结束再试听，避免录到电脑回放声。');return
        if not self.record:return
        path=self.record.get('wav')
        if upload:
            previous=self.backend.store.online(self.record['id'])
            path=json.loads(previous['details']).get('upload_wav') if previous else None
        if path and Path(path).is_file():winsound.PlaySound(str(path),winsound.SND_FILENAME|winsound.SND_ASYNC)
        else:self.status.set('当前没有可试听的完整文件。')
    def drain(self):
        while True:
            try:kind,data=self.queue.get_nowait()
            except queue.Empty:break
            if kind=='stage':self.status.set(data['text'])
            elif kind=='capture_progress':
                self.progress.set(100*data['samples']/data['total']);level=data['level'];self.level.set(f'已录 {data["samples"]/16000:.2f} 秒；输入RMS {level["rms_dbfs"]:.1f} dBFS；峰值 {level["peak_dbfs"]:.1f} dBFS')
            elif kind=='result':self.show_result(data['record'])
            elif kind=='cancelled':self.record=data['record'];self.status.set('录音已停止，部分录音已保存，没有上传到API。')
            elif kind=='verified':
                value=data['result'];stats=value.get('stats') or {};self.status.set(value.get('message','账户核验未完成'))
                self.stats.set('免费剩余 '+str(stats.get('identification_free_sec_remainder','—'))+' 秒；付费积分 '+str(stats.get('current_credit_balance','—'))+'。此次仅检查账户，不上传。')
            elif kind=='error':self.status.set(data['message'])
            elif kind=='idle':
                self.busy=False;self.stop_button.configure(state='disabled')
                for button in (self.start_button,self.verify_button,self.import_button):button.configure(state='normal')
                self.resume_button.configure(state='normal' if self.backend.pending() else 'disabled')
        if self.closing and not self.busy:self.root.destroy();return
        self.root.after(80,self.drain)
    def close(self):
        winsound.PlaySound(None,0)
        if self.busy:self.closing=True;self.stop.set();self.status.set('正在停止录音或等待当前请求返回，保存后自动关闭。')
        else:self.root.destroy()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--data-dir');parser.add_argument('--self-check',action='store_true');parser.add_argument('--probe-seconds',type=float);parser.add_argument('--device',type=int,default=0)
    args=parser.parse_args();folder=bootstrap_data(args.data_dir)
    from audit import Run,write_json
    from pc_mic_capture import input_devices,record
    from pc_mic_backend import PC_MIC_VERSION,reuse_account_confirmation
    reuse_account_confirmation()
    if args.self_check:
        r=Run('pc_mic_self_check');result={'app_version':PC_MIC_VERSION,'frozen':bool(getattr(sys,'frozen',False)),
            'input_devices':input_devices(),'data_directory':str(folder),'board_modules_imported':[x for x in ('serial','protocol','music_board','monitor_service') if x in sys.modules]}
        assert not result['board_modules_imported'];write_json(folder/'self_check.json',result);write_json(r.path/'result.json',result);r.manifest();return
    if args.probe_seconds:
        r=Run('pc_mic_capture_probe');result=record(args.device,args.probe_seconds,r.path/'probe.wav');write_json(r.path/'result.json',result);r.manifest();return
    import msvcrt
    lock=(folder/'application.lock').open('a+b');lock.write(b'0');lock.flush();lock.seek(0)
    try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:
        import tkinter.messagebox as messagebox
        messagebox.showinfo('测试程序已运行','请切换到已打开的“电脑麦克风 · AudioTag API对照测试”窗口。');return
    try:App(folder).root.mainloop()
    finally:lock.close()


if __name__=='__main__':
    try:main()
    except Exception:
        import traceback
        folder=Path(os.environ.get('NEXYS_MONITOR_DATA',Path.home()));folder.mkdir(parents=True,exist_ok=True)
        (folder/'startup_error.log').write_text(traceback.format_exc(),encoding='utf8');raise
