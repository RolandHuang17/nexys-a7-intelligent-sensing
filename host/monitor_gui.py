"""Chinese live dashboard. All plots require real board packets; no demo data path."""
import argparse,collections,json,math,os,queue,time,tkinter as tk
from tkinter import messagebox,filedialog
import ttkbootstrap as ttk
from pathlib import Path
import numpy as np
from audit import ROOT,Run,write_json,now
from monitor_service import MonitorService
from monitor_protocol import BUTTONS
from app_paths import PORTABLE,APP_VERSION,RESOURCE_ROOT
from device_discovery import candidates,select_board
from ttkbootstrap import App
from ui.theme import ThemeManager,ThemedCanvas
from panel_control import SwitchShortcuts

BG='#edf2f7';INK='#183047';MUTED='#60758a';BLUE='#2868aa';TEAL='#168c82';ORANGE='#cc852d';RED='#bc5356'

class FlowBar(ttk.Frame):
    """Wrap controls rather than clipping them on smaller teaching laptops."""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.pending=False;self.bind('<Configure>',self.schedule)
        self.after_idle(self.layout)
    def schedule(self,event=None):
        if not self.pending:self.pending=True;self.after_idle(self.layout)
    def layout(self):
        self.pending=False;width=max(300,self.winfo_width()-20);x=y=0;line=0
        for child in self.winfo_children():
            w,h=child.winfo_reqwidth()+6,child.winfo_reqheight()+4
            if x and x+w>width:x=0;y+=line;line=0
            if child.winfo_manager()=='pack':child.pack_forget()
            child.place(x=x,y=y+2);x+=w;line=max(line,h)
        self.configure(height=y+line+4)

class Plot(ttk.LabelFrame):
    def __init__(self,parent,title):
        super().__init__(parent,text=title,padding=5)
        self.canvas=ThemedCanvas(self,bg='white',highlightthickness=0,height=110)
        self.canvas.pack(fill='both',expand=True)
    def draw(self,series,xlim,ylim,unit='',note='',max_gap=None):
        c=self.canvas;c.delete('all');w=max(150,c.winfo_width());h=max(100,c.winfo_height())
        left,right,top,bottom=48,w-12,23,h-25
        dx=max(xlim[1]-xlim[0],1e-9);dy=max(ylim[1]-ylim[0],1e-9)
        px=lambda v:left+(v-xlim[0])/dx*(right-left)
        py=lambda v:bottom-(v-ylim[0])/dy*(bottom-top)
        for f in (0,.25,.5,.75,1):
            y=top+(bottom-top)*f;c.create_line(left,y,right,y,fill='#e6edf3')
            v=ylim[1]-f*dy;c.create_text(left-6,y,text=f'{v:.2f}' if abs(v)<10 else f'{v:.0f}',anchor='e',fill=MUTED,font=('Microsoft YaHei UI',8))
        for f in (0,.25,.5,.75,1):
            x=left+(right-left)*f;c.create_line(x,top,x,bottom,fill='#f0f4f8')
            c.create_text(x,bottom+13,text=f'{xlim[0]+dx*f:g}',fill=MUTED,font=('Microsoft YaHei UI',8))
        c.create_text(left,7,text=unit,anchor='w',fill=MUTED,font=('Microsoft YaHei UI',8))
        legend=right
        for name,xs,ys,color in reversed(series):
            if name:
                c.create_text(legend,7,text=name,anchor='e',fill=color,font=('Microsoft YaHei UI',8));legend-=max(50,len(name)*9+12)
            points=[];previous_x=None
            def flush():
                if len(points)>=4:c.create_line(*points,fill=color,width=1.3)
                elif len(points)==2:c.create_oval(points[0]-2,points[1]-2,points[0]+2,points[1]+2,fill=color,outline='')
            for x,y in zip(xs,ys):
                if not(xlim[0]<=x<=xlim[1]) or not math.isfinite(float(y)):
                    flush();points=[];previous_x=None;continue
                if max_gap and previous_x is not None and x-previous_x>max_gap:flush();points=[]
                points.extend((px(x),max(top,min(bottom,py(y)))))
                previous_x=x
            flush()
        if not any(len(s[1]) for s in series):
            c.create_text((left+right)/2,(top+bottom)/2,text='等待开发板数据',fill=MUTED,font=('Microsoft YaHei UI',11))
        if note:c.create_text(left+5,top+10,text=note,anchor='w',fill=MUTED,font=('Microsoft YaHei UI',8))

class Dashboard:
    def __init__(self,program=False,auto_connect=True,guide=False,serial=None):
        self.root=App(title='开发板实时监测 · Nexys A7',theme='bootstrap-light',high_dpi=False)
        self.theme_manager=ThemeManager(self.root,ROOT/'state/ui_preferences.json')
        width=min(1460,self.root.winfo_screenwidth()-60);height=min(960,self.root.winfo_screenheight()-80)
        self.root.geometry(f'{width}x{height}');self.root.minsize(min(960,self.root.winfo_screenwidth()-60),min(600,self.root.winfo_screenheight()-80))
        self.root.after(20,lambda:self.root.state('zoomed'))
        self.run=Run('monitor_session');self.run.snapshot('真实开发板中文实时界面及参数、日志版本')
        try:self.settings=json.loads((ROOT/'state/app_settings.json').read_text(encoding='utf8'))
        except (OSError,ValueError):self.settings={}
        self.selected_serial=serial or self.settings.get('preferred_serial');self.device_options={};self.device_identity=None
        self.device_label=tk.StringVar();self.board_confirmed=tk.BooleanVar(value=False);self.switch_pending=False;self.confirm_display_serial=None
        self.messages=queue.Queue();self.worker=None;self.program=program;self.connected=False;self.paused=False
        self.last_row=None;self.last_receive=0;self.last_state_save=0;self.last_draw=0;self.closing=False
        self.audio=collections.deque(maxlen=5000);self.xyz=collections.deque(maxlen=1800);self.temps=collections.deque(maxlen=4000)
        self.volts=collections.deque(maxlen=4000);self.freq=None;self.event_paths={};self.render_count=0
        self.status=tk.StringVar(value='尚未连接');self.notice=tk.StringVar(value='数据将自动留存在本次运行目录。')
        self.mode=tk.StringVar(value='声振联合');self.a_threshold=tk.StringVar(value='13');self.v_threshold=tk.StringVar(value='39');self.pair_window=tk.StringVar(value='50')
        self.panel_shortcuts=SwitchShortcuts();self.panel_link_text='显示同步中'
        self.board_control_status=tk.StringVar(value='识曲开关 SW15：关 · 显示同步中')
        self.game_panel=None
        self.music_panel=None;self.make_widgets();self.root.protocol('WM_DELETE_WINDOW',self.close)
        self.root.after(50,self.tick)
        if auto_connect:self.root.after(300,self.connect)
        self.guide=None
        self.last_control=None
        self.load_history()
        self.refresh_devices();self.root.after(2000,self.scan_devices)
        if guide:self.root.after(1200,self.open_guide)

    def make_widgets(self):
        from ui.dashboard import build_dashboard
        build_dashboard(self,FlowBar,Plot)
        ttk.Label(self.device_box.master,textvariable=self.board_control_status,style='Muted.TLabel').pack(side='left',padx=8)

    def show_page(self,key):
        if key=='game' and self.game_panel is None:
            self.open_game();return
        if key=='audio' and self.music_panel is None:
            self.open_music();return
        if getattr(self,'active_page',None)=='game' and key!='game':self.game_panel.deactivate()
        self.active_page=key;self.pages[key].tkraise()
        if key=='game':self.game_panel.activate()
        for name,button in self.nav_buttons.items():
            button.configure(style='Active.Nav.TButton' if name==key else 'Nav.TButton')

    def open_game(self):
        if self.game_panel is None:
            from tilt_game.embedded import EmbeddedGamePanel
            self.game_panel=EmbeddedGamePanel(self,ROOT/'game')
            if self.device_identity:self.game_panel.feed({'kind':'identity','device':self.device_identity})
            self.game_panel.feed({'kind':'status','connected':self.connected,'text':'点击开始航行，准备游戏并校准。'})
        self.show_page('game')

    def open_music(self):
        if self.music_panel is None:
            from music_gui import MusicPanel
            self.music_panel=MusicPanel(self)
            self.theme_manager.set(self.theme_manager.choice,persist=False)
            self.music_panel.stage.trace_add('write',self.update_music_progress)
            self.music_panel.status.trace_add('write',lambda *a:self.root.after_idle(self.update_music_progress))
        self.show_page('audio')
        self.music_panel.refresh_history()
        self.update_music_progress()

    def update_music_progress(self,*args):
        if self.music_panel:self.music_progress.set('识曲 · '+(self.music_panel.stage.get() if self.music_panel.busy else '就绪'))

    def handle_panel_shortcuts(self,row):
        previous=self.panel_shortcuts.previous
        actions=self.panel_shortcuts.update(row['switches'])
        if previous is None or row['switches']&0x8000 and not previous&0x8000:
            self.run.event('panel_mode_position',switches=row['switches'],board_tick=row.get('tick'))
        enabled=bool(row['switches']&0x8000)
        self.board_control_status.set('识曲开关 SW15：'+('开' if enabled else '关')+' · '+self.panel_link_text)
        if not actions:return
        self.open_music();panel=self.music_panel;action=actions[0]
        self.run.event('panel_shortcut',action=action,switches=row['switches'],board_tick=row.get('tick'),
            accepted=action=='exit' or not(panel.busy or panel.importing),busy=panel.busy)
        if action=='exit':
            # Existing music_disable owns its busy-task exit_pending policy.
            self.action('music_disable');self.show_page('monitor')
        elif panel.busy or panel.importing:
            self.notice.set('板控操作已忽略：请等待当前任务结束。')
        elif action=='enter':
            if not panel.enabled:panel.enable()

    def mode_number(self):return {'仅声音':1,'仅振动':2,'声振联合':3}[self.mode.get()]
    def action(self,name,**values):
        if not self.worker or not self.worker.is_alive():self.notice.set('请先连接开发板。');return
        self.worker.send(name,**values)
    def arm(self):
        try:values={'audio':int(self.a_threshold.get()),'accel':int(self.v_threshold.get()),'window':int(self.pair_window.get())}
        except ValueError:self.notice.set('阈值和间隔需要填写整数。');return
        self.action('arm',enabled=True,mode=self.mode_number(),**values)
    def connect(self):
        if self.worker and self.worker.is_alive():self.notice.set('采集线程正在连接或运行，请查看连接状态。');return
        if self.worker is not None:
            previous=self.run.run_id;self.run.event('gui_connection_ended');self.run.manifest()
            self.run=Run('monitor_session');self.run.snapshot('重连或初始化后的独立采集会话')
            self.run.event('gui_connection_started',previous_session=previous);self.clear_live()
        self.run.event('gui_connect',program=self.program)
        self.worker=MonitorService(self.run,self.messages.put,program=self.program,serial=self.selected_serial);self.program=False;self.worker.start()
    def download(self):
        if PORTABLE or (RESOURCE_ROOT/'release_manifest.json').exists():
            try:board=select_board(self.selected_serial)
            except Exception as error:self.notice.set(str(error));return
            if not self.board_confirmed.get():
                self.notice.set('请先核对板面为Nexys A7-100T并勾选板型确认；USB芯片型号本身不能确认整块板型。');return
            self.selected_serial=board.serial
            if not messagebox.askokcancel('初始化所选开发板',f'设备：{board.serial} / {board.port}\n将临时加载配套程序到SRAM，清空板内未导出的记录。\n不写Flash，断电后需要再次初始化。',parent=self.root):return
            confirmed=self.settings.setdefault('confirmed_serials',[])
            if board.serial not in confirmed:confirmed.append(board.serial)
            self.save_settings()
        if self.worker and self.worker.is_alive():
            self.notice.set('正在停止当前连接，随后下载固件；板上尚未导出的记录会被清除。')
            self.worker.stop_event.set();self.root.after(150,self.download_when_stopped)
        else:self.program=True;self.connect()
    def save_settings(self):
        self.settings['preferred_serial']=self.selected_serial;write_json(ROOT/'state/app_settings.json',self.settings)
    def refresh_devices(self):
        try:found=candidates()
        except Exception as error:self.notice.set(str(error));return
        self.device_options={b.label:b for b in found};self.device_box['values']=list(self.device_options)
        chosen=next((b for b in found if b.serial==self.selected_serial),None)
        if chosen is None and len(found)==1:chosen=found[0]
        if chosen:
            changed=self.selected_serial is not None and chosen.serial!=self.selected_serial
            self.selected_serial=chosen.serial;self.device_label.set(chosen.label)
            if self.confirm_display_serial!=chosen.serial:
                self.board_confirmed.set(chosen.serial in self.settings.get('confirmed_serials',[]));self.confirm_display_serial=chosen.serial
            if changed:self.switch_device()
        else:
            self.device_label.set('请选择设备' if found else '等待PROG/UART连接和上电')
    def scan_devices(self):
        if self.closing:return
        self.refresh_devices();self.root.after(2000,self.scan_devices)
    def choose_device(self,event=None):
        board=self.device_options.get(self.device_label.get())
        if not board:return
        self.selected_serial=board.serial;self.confirm_display_serial=board.serial;self.board_confirmed.set(board.serial in self.settings.get('confirmed_serials',[]))
        self.save_settings();self.switch_device()
    def switch_device(self):
        if self.switch_pending:return
        self.switch_pending=True
        if self.worker:self.worker.stop_event.set()
        def stopped():
            if self.worker and self.worker.is_alive():self.root.after(100,stopped);return
            self.clear_live();self.switch_pending=False;self.connect()
        stopped()
    def clear_live(self):
        self.audio.clear();self.xyz.clear();self.temps.clear();self.volts.clear();self.freq=None;self.last_row=None;self.last_receive=0
        for value in self.card_values.values():value.set('—')
    def open_driver_setup(self):
        win=tk.Toplevel(self.root);win.title('首次使用 · USB驱动准备');win.geometry('640x350')
        text=('若已经能连接，无需安装。\n\n使用板上的PROG/UART接口，打开电源。常规FTDI驱动与已有WinUSB均可使用，软件按实际情况选择下载方式。\n\n下面按钮启动FTDI原版签名安装器，仅安装器请求管理员权限。取消安装后仍可返回软件。不会调用Zadig替换现有驱动。\n\n初始化前请确认板型为Nexys A7-100T。')
        ttk.Label(win,text=text,wraplength=590,justify='left').pack(padx=22,pady=20,fill='x')
        def install():
            import threading
            def work():
                try:
                    from driver_setup import install
                    self.messages.put({'kind':'notice','text':install(self.run)})
                except Exception as error:self.messages.put({'kind':'notice','text':'驱动安装未完成：'+str(error)})
            threading.Thread(target=work,daemon=True).start()
        ttk.Button(win,text='启动官方FTDI驱动安装器',command=install).pack(pady=5)
    def export_selected(self):
        selected=self.events.selection()
        if not selected:self.notice.set('请先在表格选择一条完整事件。');return
        target=filedialog.askdirectory(parent=self.root,initialdir=self.settings.get('export_directory',str(Path.home())),title='选择事件导出目录')
        if not target:return
        import shutil
        source=self.event_paths[selected[0]];name=source.parent.parent.name+'_'+source.name;dest=Path(target)/name
        if dest.exists():self.notice.set('该导出目录已存在，保留原文件；请选择其他位置。');return
        try:
            from audit import sha256
            meta=json.loads((source/'metadata.json').read_text(encoding='utf8'))
            if sha256(source/'payload.bin')!=meta['input_hash']:raise ValueError('原始数据校验失败')
            shutil.copytree(source,dest);self.settings['export_directory']=target;self.save_settings()
            self.run.event('user_event_exported',source=str(source),destination=str(dest),input_hash=meta['input_hash'])
            self.notice.set('完整事件已导出到：'+str(dest))
        except Exception as error:self.notice.set('导出未完成：'+str(error))
    def export_diagnostics(self):
        target=filedialog.asksaveasfilename(parent=self.root,initialdir=self.settings.get('export_directory',str(Path.home())),
            initialfile=self.run.run_id+'_诊断.zip',defaultextension='.zip',filetypes=[('诊断包','*.zip')],title='保存本次实板诊断包')
        if not target:return
        if self.worker:self.worker.stop_event.set()
        def stopped():
            if self.worker and self.worker.is_alive():self.root.after(100,stopped);return
            import zipfile,platform
            from audit import sha256
            self.run.event('diagnostic_export_started',destination=target)
            paths=[p for p in self.run.path.rglob('*') if p.is_file() and p.name!='manifest.json']
            summary={'app_version':APP_VERSION,'session':self.run.run_id,'device':self.device_identity,
                'windows':platform.platform(),'architecture':platform.machine(),
                'files':[{'path':str(p.relative_to(self.run.path)).replace('\\','/'),'sha256':sha256(p)} for p in paths]}
            with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
                for p in paths:z.write(p,str(p.relative_to(self.run.path)))
                z.writestr('diagnostic_index.json',json.dumps(summary,ensure_ascii=False,indent=2))
            self.run.event('diagnostic_export_completed',file_sha256=sha256(target),destination=target)
            self.notice.set('本次采集已停止，诊断包已保存：'+target+'；可点连接继续采集。')
        stopped()
    def download_when_stopped(self):
        if self.worker and self.worker.is_alive():self.root.after(150,self.download_when_stopped)
        else:self.program=True;self.connect()
    def pause(self):
        self.paused=not self.paused;self.pause_button.configure(text='继续画面' if self.paused else '暂停画面')
        self.run.event('gui_view_paused',paused=self.paused)
        self.notice.set('画面暂停，后台采集和文件记录继续。' if self.paused else '画面已恢复。')
    def play(self,event=None):
        selected=self.events.selection()
        if selected:
            import winsound
            path=self.event_paths[selected[0]]/'audio.wav';winsound.PlaySound(str(path),winsound.SND_FILENAME|winsound.SND_ASYNC)
            self.run.event('gui_playback',file=str(path));self.notice.set('正在播放：'+str(path))

    def load_history(self):
        paths=sorted((ROOT/'runs').glob('*_monitor_session/physical/*/metadata.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:20]
        for p in reversed(paths):
            try:self.accept({'kind':'event','event':json.loads(p.read_text(encoding='utf8')),'directory':str(p.parent),'historical':True})
            except (ValueError,KeyError,OSError):continue
        if paths:self.notice.set(f'已载入 {len(paths)} 条历史事件；实时曲线仍等待新的板端数据。')

    def view_event(self):
        selected=self.events.selection()
        if not selected:self.notice.set('请先选择一条已保存事件。');return
        path=self.event_paths[selected[0]]
        try:
            from audit import sha256
            from features import load_event
            meta,audio,xyz,first=load_event(path)
            if sha256(path/'payload.bin')!=meta['input_hash']:raise ValueError('原始数据校验不符')
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            import matplotlib
            matplotlib.rcParams.update({'font.family':'Microsoft YaHei','axes.unicode_minus':False})
            win=tk.Toplevel(self.root);win.title(f'事件 {meta["event_id"]} · 已保存原始波形');win.geometry('980x720')
            fig=Figure(figsize=(8,5.5),layout='constrained');ax=fig.subplots(2,1,sharex=True)
            ax[0].plot((first+np.arange(len(audio))*6250-50000000)/1e8,audio,linewidth=.7,color=BLUE)
            ax[0].set_ylabel('原始声音 / PCM计数');a=np.asarray(xyz)
            for i,name,color in [(1,'X',BLUE),(2,'Y',ORANGE),(3,'Z',TEAL)]:ax[1].plot((a[:,0]-50000000)/1e8,a[:,i],label=name,color=color,linewidth=.8)
            ax[1].set_ylabel('三轴 / 标称mg');ax[1].set_xlabel('距保存参考时刻 / s');ax[1].legend(ncol=3)
            for p in ax:p.axvline(0,color=MUTED,linestyle='--');p.grid(alpha=.2)
            fig.suptitle(f'事件 {meta["event_id"]}：原始录音 {len(audio)} 点，XYZ {len(xyz)} 组')
            canvas=FigureCanvasTkAgg(fig,master=win);canvas.draw();self.theme_manager.preserve(canvas.get_tk_widget());canvas.get_tk_widget().pack(fill='both',expand=True)
            ttk.Label(win,text=str(path),wraplength=900).pack(fill='x',padx=10,pady=5)
            self.run.event('gui_event_viewed',directory=path.relative_to(ROOT).as_posix(),input_hash=meta['input_hash'])
        except Exception as error:messagebox.showerror('无法打开事件',str(error),parent=self.root)

    def control_request(self):
        path=ROOT/'state/monitor_control.json'
        if not path.exists():return
        try:
            request=json.loads(path.read_text(encoding='utf8'))
            if request.get('target_run_id')!=self.run.run_id or request.get('id')==self.last_control:return
            self.last_control=request['id'];action=request['action'];args=request.get('arguments',{})
            self.run.event('local_control_request',request=request)
            if action=='show':self.root.deiconify();self.root.state('zoomed');self.root.lift()
            elif action=='dismiss_guide':
                if self.guide and self.guide['window'].winfo_exists():self.guide['window'].destroy()
            elif action=='guide':self.open_guide()
            elif action=='music':self.open_music()
            elif action.startswith('music_'):
                self.open_music()
                if action=='music_record':self.music_panel.record()
                elif action=='music_cancel':self.music_panel.cancel()
                elif action=='music_verify':self.music_panel.verify()
                elif action=='music_demo':self.music_panel.import_demo()
                elif action=='music_game':self.music_panel.start_game()
                elif action=='music_reveal':self.music_panel.game_answer.set(args.get('answer',''));self.music_panel.reveal()
                elif action=='music_policy':self.music_panel.policy.set(args['policy']);self.music_panel.policy_changed()
                elif action=='music_favourite':self.music_panel.favourite()
                elif action=='music_wizard':self.music_panel.open_acceptance()
                else:self.action(action,**args)
            elif action=='ui_page':self.show_page(args['page'])
            elif action=='ui_theme':
                self.theme_choice.set(args['theme']);self.theme_manager.set(args['theme'])
            elif action=='pause':self.pause()
            elif action=='snap':self.action('snap')
            elif action=='arm':self.action('arm',**args)
            elif action=='mark':self.action('mark',**args)
            elif action=='resize':
                width=max(960,min(3000,int(args['width'])));height=max(600,min(2000,int(args['height'])))
                self.root.state('normal');self.root.geometry(f'{width}x{height}')
            elif action!='close':raise ValueError('不支持的本机控制命令')
            write_json(ROOT/'state/monitor_control_result.json',{'id':request['id'],'run_id':self.run.run_id,'accepted':True,'time':now()})
            if action=='close':self.close()
        except (OSError,ValueError,KeyError) as error:self.notice.set('本机控制请求未完成：'+str(error))

    def open_guide(self):
        if self.guide and self.guide['window'].winfo_exists():self.guide['window'].lift();return
        win=tk.Toplevel(self.root);win.title('实板检查 · 按提示操作');win.geometry('760x430')
        win.configure(bg='white');win.transient(self.root)
        title=tk.StringVar(value='等待有效板端数据');instruction=tk.StringVar(value='连接后将显示操作步骤。');progress=tk.StringVar(value='')
        tk.Label(win,text='集中完成开关、按键和敲击检查',font=('Microsoft YaHei UI',17,'bold'),fg=INK,bg='white').pack(anchor='w',padx=24,pady=(20,12))
        tk.Label(win,textvariable=title,font=('Microsoft YaHei UI',14,'bold'),fg=BLUE,bg='white').pack(anchor='w',padx=24,pady=8)
        tk.Label(win,textvariable=instruction,font=('Microsoft YaHei UI',13),fg=INK,bg='white',wraplength=700,justify='left').pack(anchor='w',padx=24,pady=12)
        tk.Label(win,textvariable=progress,font=('Microsoft YaHei UI',12),fg=TEAL,bg='white',wraplength=700,justify='left').pack(anchor='w',padx=24,pady=10)
        tk.Label(win,text='不需要按 PROG 或 CPU RESET，也不用拔线。数据会自动保存。',font=('Microsoft YaHei UI',10),fg=MUTED,bg='white').pack(side='bottom',pady=15)
        self.guide={'window':win,'title':title,'instruction':instruction,'progress':progress,'stage':-1,
            'high':0,'low':0,'press':0,'release':0,'max_tilt_change':0,'returned':0,'events':[], 'started':now()}
        self.action('arm',enabled=False,mode=3)
        self.run.event('physical_guide_opened',steps=['16开关双状态','5方向按键按下和释放','轻微倾斜后放平','真实联合自动敲击'])

    def guide_update(self,row):
        g=self.guide
        if not g or not g['window'].winfo_exists() or g['stage']==4:return
        stage=g['stage']
        if stage==-1:
            g.update(stage=0,press_base=row['presses'],release_base=row['releases'],first_tick=row['tick'])
            g['title'].set('1 / 4　拨码开关')
            g['instruction'].set('先把16个开关全拨下，再从最右侧 SW0 开始逐个拨上，最后全部拨回下方；每拨一个稍停一下。')
        elif stage==0:
            g['high']|=row['switches'];g['low']|=(~row['switches'])&65535
            g['progress'].set(f'已看到高电平 {g["high"].bit_count()}/16，低电平 {g["low"].bit_count()}/16；当前 0x{row["switches"]:04X}')
            if g['high']==65535 and g['low']==65535 and row['switches']==0:
                g['stage']=1;g['title'].set('2 / 4　方向按键')
                g['instruction'].set('依次按上、下、左、右、中各一次，每次按住约半秒、松开后再按下一个。')
                self.run.event('physical_switches_verified',high_mask=g['high'],low_mask=g['low'],tick=row['tick'])
        elif stage==1:
            for i in range(5):
                if row['presses'][i]>g['press_base'][i]:g['press']|=1<<i
                if row['releases'][i]>g['release_base'][i]:g['release']|=1<<i
            names=('上','下','左','右','中');g['progress'].set('　'.join(name+(' ✓' if (g['press']&g['release'])&(1<<i) else ' 待操作') for i,name in enumerate(names)))
            if g['press']==31 and g['release']==31:
                g['stage']=2;g['baseline_xyz']=row['xyz_latest'];g['title'].set('3 / 4　倾斜后放平')
                g['instruction'].set('轻轻抬起板子一边约10°，停一秒，再放回原来的平放位置；不用拔线。')
                self.run.event('physical_buttons_verified',press_mask=31,release_mask=31,tick=row['tick'],presses=row['presses'],releases=row['releases'])
        elif stage==2:
            change=float(np.linalg.norm(np.asarray(row['xyz_latest'])-np.asarray(g['baseline_xyz'])))
            g['max_tilt_change']=max(g['max_tilt_change'],change)
            if g['max_tilt_change']>120 and change<70:g['returned']+=1
            else:g['returned']=0
            g['progress'].set(f'三轴变化最大值 {g["max_tilt_change"]:.0f} 计数；'+('正在确认已放平…' if g['returned'] else '等待倾斜并放回'))
            if g['returned']>=8:
                g['stage']=3;g['tap_start_tick']=row['tick'];g['title'].set('4 / 4　自动记录真实敲击')
                g['instruction'].set('板子保持平放，等两秒后敲桌面三次，每次间隔约三秒；不按任何按键。请等显示“检查完成”。')
                self.action('arm',enabled=True,mode=3,audio=13,accel=39,window=50)
                self.run.event('physical_tilt_verified',maximum_change_counts=g['max_tilt_change'],tick=row['tick'])
        elif stage==3:
            g['progress'].set('正在等待联合触发并导出完整事件；如果尚未成功，可以稍用力再敲一次。')
        write_json(self.run.path/'physical_guide.json',{k:v for k,v in g.items() if k not in ('window','title','instruction','progress')})

    def accept(self,message):
        kind=message['kind']
        if getattr(self,'game_panel',None):self.game_panel.feed(message)
        if kind.startswith('music_'):
            if self.music_panel:self.music_panel.receive(kind,message)
            return
        if kind=='panel_status':
            self.panel_link_text=message['text'].replace('板端显示','显示')
            row=self.last_row
            self.board_control_status.set('识曲开关 SW15：'+('开' if row and row['switches']&0x8000 else '关')+' · '+self.panel_link_text)
            return
        if kind=='identity':
            if self.device_identity!=message['device']:self.clear_live();self.panel_shortcuts.reset()
            self.device_identity=message['device']
        elif kind=='status':
            self.panel_shortcuts.reset()
            self.connected=message['connected'];self.status.set(message['text'])
        elif kind in ('notice','stopped'):self.notice.set(message['text'])
        elif kind=='reset':
            self.panel_shortcuts.reset();self.clear_live()
            self.notice.set('已开始新的板端时间段；旧记录仍在文件中。')
        elif kind=='data':
            self.last_row=message['row'];self.last_receive=time.monotonic()
            self.audio.extend(message['audio']);self.xyz.extend(message['xyz'])
            r=self.last_row;t=r['tick']/1e8
            self.temps.append((t,r['adt_c'],r['die_c']));self.volts.append((t,r['vccint_v'],r['vccaux_v'],r['vccbram_v']))
            self.missing=(message['missing_audio'],message['missing_xyz'])
            self.handle_panel_shortcuts(self.last_row)
            self.guide_update(self.last_row)
            if self.music_panel and hasattr(self.music_panel,'wizard'):self.music_panel.wizard.receive('telemetry',message)
        elif kind=='spectrum':self.freq=message
        elif kind=='event':
            e=message['event'];mode={0:'手动',1:'声音自动',2:'振动自动',3:'联合自动'}.get(e['mode'],str(e['mode']))
            if message.get('historical'):mode='历史 / '+mode
            serial=e.get('programming',{}).get('usb_serial','旧实验记录')
            item=self.events.insert('',0,values=(e['event_id'],mode,f'{e["anchor_tick"]/1e8:.3f}', 'CRC通过 · '+serial,message['directory']))
            self.event_paths[item]=Path(message['directory']);self.notice.set(f'事件 {e["event_id"]} 已保存：24000声音点，{e["xyz_count"]}组XYZ。')
            if self.guide and self.guide['stage']==3 and e['mode']==3 and e['anchor_tick']>self.guide['tap_start_tick']+150000000:
                g=self.guide;g['events'].append({'event_id':e['event_id'],'input_hash':e['input_hash'],'directory':message['directory']})
                g['stage']=4;g['title'].set('检查完成');g['instruction'].set('全部开关和方向按键已经读到，倾斜响应和真实敲击自动记录已保存。请回到对话回复“完成”。')
                g['progress'].set(f'事件 {e["event_id"]}：24000点录音、{e["xyz_count"]}组振动，校验通过。')
                self.run.event('physical_guide_completed',event_id=e['event_id'],input_hash=e['input_hash'],tick=e['anchor_tick'])
                write_json(self.run.path/'physical_guide.json',{k:v for k,v in g.items() if k not in ('window','title','instruction','progress')})

    def draw(self):
        row=self.last_row;stale=row is None or time.monotonic()-self.last_receive>1.5
        self.dot.configure(text='● 数据陈旧 / 未连接' if stale else '● 实板在线',fg=self.theme_manager.resolve('#e1b56e' if stale else '#77dfc6'))
        if not row:
            for p in self.plots.values():p.draw([],(-1,0),(-1,1))
            self.draw_io(None);return
        current=row['tick']/1e8
        def value(key,digits,unit,valid=True):
            v=row.get(key);return '—' if stale or v is None or not valid else f'{v:.{digits}f} {unit}'
        adt_fresh=row['adt_valid'] and row['tick']-row['adt_tick']<150000000
        adc_fresh=row['xadc_valid_mask']==15 and row['tick']-row['xadc_tick']<100000000
        for name,key,digits,unit,valid in [('board','adt_c',2,'°C',adt_fresh),('die','die_c',2,'°C',adc_fresh),
            ('int','vccint_v',3,'V',adc_fresh),('aux','vccaux_v',3,'V',adc_fresh),('bram','vccbram_v',3,'V',adc_fresh)]:
            self.card_values[name].set(value(key,digits,unit,valid))
        self.card_values['acc_temp'].set(str(row['adxl_temperature_raw'])+' 计数' if row['adxl_temperature_valid'] and not stale else '—')
        a=[p for p in self.audio if p['tick']/1e8>current-3];ax=[p['tick']/1e8-current for p in a]
        center=float(np.median([(p['low']+p['high'])/2 for p in a])) if a else 0
        amp=max(100,max((max(abs(p['low']-center),abs(p['high']-center)) for p in a),default=100)*1.1)
        self.plots['audio'].draw([('最小值',ax,[p['low']-center for p in a],BLUE),('最大值',ax,[p['high']-center for p in a],TEAL)],(-3,0),(-amp,amp),'PCM相对计数 · 距当前 / s',note='数据已过旧' if stale else '',max_gap=.0015)
        if self.freq:
            f=self.freq;age=current-f['first_tick']/1e8
            self.plots['fft'].draw([('',[x/1000 for x in f['hz']],f['dbfs'],BLUE)],(0,8),(-100,0),'dBFS · 频率 / kHz',note=f'本帧主峰 {f["peak"]:.1f} Hz · 快照距今 {age:.1f}s')
        else:self.plots['fft'].draw([],(0,8),(-100,0),'dBFS · 频率 / kHz')
        xyz=[p for p in self.xyz if p['tick']/1e8>current-5];xs=[p['tick']/1e8-current for p in xyz]
        extent=max(1100,max((max(abs(p[k]) for k in ('x','y','z')) for p in xyz),default=1100)*1.1)
        self.plots['xyz'].draw([(k.upper(),xs,[p[k] for p in xyz],color) for k,color in [('x',BLUE),('y',ORANGE),('z',TEAL)]],(-5,0),(-extent,extent),'标称mg · 距当前 / s',max_gap=.0075)
        temps=[p for p in self.temps if p[0]>current-120]
        tv=[v for p in temps for v in p[1:] if v is not None]
        limits=(min(tv)-1,max(tv)+1) if tv else (0,60)
        self.plots['temp'].draw([(name,[p[0]-current for p in temps],[p[i] if p[i] is not None else float('nan') for p in temps],color)
            for i,name,color in [(1,'板载温度',TEAL),(2,'芯片温度',RED)]],(-120,0),limits,'°C · 距当前 / s')
        volts=[p for p in self.volts if p[0]>current-120]
        self.plots['voltage'].draw([(name,[p[0]-current for p in volts],[p[i] if p[i] is not None else float('nan') for p in volts],color)
            for i,name,color in [(1,'核心',BLUE),(2,'辅助',ORANGE),(3,'存储',TEAL)]],(-120,0),(0,2.2),'V · 距当前 / s')
        self.draw_io(row if not stale else None)
        if not stale:
            mode={1:'声音',2:'振动',3:'联合'}.get(row['mode'],'未知')
            self.status.set(f'设备 {(self.device_identity or {}).get("usb_serial", "—")} · 程序 {row["build_id"]} · 板端 {current:.2f}s · 自动记录：{mode if row["armed"] else "未启用"} · '
                f'前端漏读 {row["overruns"]} · 包校验错误 {row["packet_crc_errors"]} · 预览缺口：声音 {self.missing[0]} / XYZ {self.missing[1]}')
        self.render_count+=1

    def draw_io(self,row):
        c=self.io_canvas;c.delete('all');w=max(300,c.winfo_width());h=max(100,c.winfo_height())
        c.create_text(8,8,text='拨码开关（左15 → 右0）',anchor='nw',fill=MUTED,font=('Microsoft YaHei UI',9))
        cell=(w-24)/16
        for i in range(16):
            bit=15-i;x=12+i*cell;on=bool(row and row['switches']&(1<<bit));fill=TEAL if on else '#e7edf3'
            c.create_rectangle(x,30,x+cell-4,51,fill=fill,outline='')
            c.create_text(x+(cell-4)/2,62,text=str(bit),fill=MUTED,font=('Microsoft YaHei UI',8))
        sw='—' if not row else f'0x{row["switches"]:04X}'
        c.create_text(w-9,10,text=sw,anchor='ne',fill=BLUE,font=('Consolas',10,'bold'))
        y=max(85,h-38);positions={i:(31+48*i,y) for i in range(5)}
        for i,(x,yy) in positions.items():
            on=bool(row and row['buttons']&(1<<i));c.create_rectangle(x-18,yy-10,x+18,yy+10,fill=BLUE if on else '#e7edf3',outline='')
            count=row['presses'][i] if row else '—'
            c.create_text(x,yy,text=f'{BUTTONS[i][-1]}:{count}',fill='white' if on else INK,font=('Consolas',9,'bold'))
        counts='—' if not row else ' / '.join(str(x) for x in row['presses'])
        c.create_text(265,y-8,text='按键：上 / 下 / 左 / 右 / 中',anchor='nw',fill=MUTED,font=('Microsoft YaHei UI',8))
        if row:
            x,yv,z=row['xyz_latest'];norm=math.sqrt(x*x+yv*yv+z*z)
            tilt_x=math.degrees(math.atan2(x,math.sqrt(yv*yv+z*z))) if norm else 0
            tilt_y=math.degrees(math.atan2(yv,math.sqrt(x*x+z*z))) if norm else 0
            c.create_text(12,min(h-10,y+22),text=f'静态倾斜参考 X {tilt_x:.1f}° / Y {tilt_y:.1f}° · 合加速度 {norm/1000:.3f}g',anchor='w',fill=MUTED,font=('Microsoft YaHei UI',8))

    def tick(self):
        self.control_request()
        if self.closing:return
        for _ in range(100):
            try:self.accept(self.messages.get_nowait())
            except queue.Empty:break
        stale=self.last_row is None or time.monotonic()-self.last_receive>1.5
        self.dot.configure(text='● 数据陈旧 / 未连接' if stale else '● 实板在线',fg=self.theme_manager.resolve('#e1b56e' if stale else '#77dfc6'))
        if not self.paused and getattr(self,'active_page',None)!='game':self.draw()
        t=time.monotonic()
        if t-self.last_state_save>1:
            self.last_state_save=t
            write_json(ROOT/'state/monitor_gui.json',{'pid':os.getpid(),'run_id':self.run.run_id,'connected':self.connected,
                'last_receive_age_s':t-self.last_receive if self.last_receive else None,'last_board_tick':self.last_row['tick'] if self.last_row else None,
                'render_count':self.render_count,'paused':self.paused,'state':'closing' if self.closing else 'running','time':now()})
        self.root.after(50,self.tick)

    def close(self):
        self.closing=True
        if self.game_panel:self.game_panel.close()
        if self.music_panel:self.music_panel.engine.close()
        if self.worker:self.worker.stop_event.set()
        self.finish_close()
    def finish_close(self):
        if self.worker and self.worker.is_alive():self.root.after(100,self.finish_close);return
        self.run.event('gui_closed',render_count=self.render_count)
        write_json(ROOT/'state/monitor_gui.json',{'pid':None,'run_id':self.run.run_id,'state':'closed','time':now()})
        self.run.manifest();self.root.destroy()

def main():
    p=argparse.ArgumentParser();p.add_argument('--program',action='store_true');p.add_argument('--no-connect',action='store_true');p.add_argument('--guide',action='store_true');a=p.parse_args()
    app=Dashboard(a.program,not a.no_connect,a.guide);app.root.mainloop()

if __name__=='__main__':main()
