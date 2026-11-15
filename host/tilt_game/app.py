"""Embeddable game panel; all hardware work stays outside the Tk event loop."""
from collections import deque
from datetime import datetime, timedelta, timezone
import ctypes
import json
import math
from pathlib import Path
import time
import tkinter as tk
from tkinter import ttk, messagebox
import uuid

from . import TITLE, VERSION
from .audio import SoundBank
from .engine import Control, Game
from .input import TiltInput
from .levels import LEVELS
from .render import Renderer, BG, PANEL, TEXT, MUTED, CYAN, GOLD
from .storage import SaveStore


class Journal:
    def __init__(self,directory,mode):
        stamp=datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%dT%H%M%S_%f')
        self.path=Path(directory)/'sessions'/(stamp+'_'+mode+'_'+uuid.uuid4().hex[:4])
        self.path.mkdir(parents=True,exist_ok=True)
        self.events=(self.path/'events.jsonl').open('a',encoding='utf8')
        self.inputs=(self.path/'controls.jsonl').open('a',encoding='utf8')
        self.write('session_start',game_version=VERSION,source=mode,
                   physical_verification='pending' if mode=='board' else 'not_applicable')

    def write(self,kind,**values):
        self.events.write(json.dumps({'kind':kind,'host_monotonic':time.perf_counter(),**values},ensure_ascii=False)+'\n')
        self.events.flush()

    def input(self,**values):
        self.inputs.write(json.dumps(values,ensure_ascii=False)+'\n')

    def close(self,**metrics):
        self.write('session_end',metrics=metrics)
        self.events.close()
        self.inputs.close()
        (self.path/'metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf8')


def configure_styles(root):
    style=ttk.Style(root)
    style.configure('Tilt.TFrame',background=BG)
    style.configure('Tilt.TLabel',background=BG,foreground=TEXT,font=('Microsoft YaHei UI',10))
    style.configure('Tilt.Muted.TLabel',background=BG,foreground=MUTED,font=('Microsoft YaHei UI',9))
    style.configure('Tilt.TButton',background='#203b54',foreground=TEXT,bordercolor='#35566d',
                    padding=(12,9),font=('Microsoft YaHei UI',10),focuscolor=CYAN)
    style.map('Tilt.TButton',background=[('active','#315a72'),('disabled','#18283d')],
              foreground=[('disabled','#71849e')],bordercolor=[('focus',CYAN)])
    style.configure('Tilt.Primary.TButton',background=CYAN,foreground='#082632',bordercolor=CYAN,
                    padding=(20,10),font=('Microsoft YaHei UI',10,'bold'),focuscolor='#ffffff')
    style.map('Tilt.Primary.TButton',background=[('active','#a0f6ef'),('disabled','#294657')],
              foreground=[('disabled','#91a6b5')],bordercolor=[('focus','#ffffff')])
    style.configure('Tilt.TCombobox',padding=(7,5),font=('Microsoft YaHei UI',9),
                    fieldbackground='#15283f',background='#203b54',foreground=TEXT,
                    arrowcolor=CYAN,bordercolor='#35566d',lightcolor='#35566d',darkcolor='#35566d')
    style.map('Tilt.TCombobox',fieldbackground=[('readonly','#15283f')],
              foreground=[('readonly',TEXT)],selectbackground=[('readonly','#25465d')])


class GamePanel(ttk.Frame):
    """feed(message), activate(), pause(), close() form the future host contract."""
    def __init__(self,parent,input_source,save_dir,*,on_connect=None,on_disconnect=None,on_initialize=None,preview=False):
        configure_styles(parent)
        super().__init__(parent,style='Tilt.TFrame')
        self._ui_preserve=True
        self._timer_resolution=False
        try:
            self._timer_resolution=ctypes.windll.winmm.timeBeginPeriod(1)==0
        except (AttributeError,OSError):
            pass
        self.mode=input_source
        self.save_dir=Path(save_dir)
        self.store=SaveStore(self.save_dir)
        self.journal=Journal(self.save_dir,self.mode)
        self.preview=preview
        self.tilt=TiltInput()
        self.tilt.sensitivity=self.store.data['settings']['sensitivity']
        self.sounds=SoundBank(self.save_dir/'sound_cache')
        try:
            self.sounds.prepare()
        except OSError:
            pass
        self.on_connect=on_connect
        self.on_disconnect=on_disconnect
        self.on_initialize=on_initialize
        self.game=None
        self.state='map'
        self.active=True
        self.closed=False
        self.selected=0
        self.pressed=set()
        self.pending_start=False
        self.return_to_game=False
        self.cal_phase=None
        self.pause_reason=''
        self.notice=''
        self.notice_until=0
        self.last_frame=time.perf_counter()
        self.scene_ready_until=0.
        self.last_input_log=self.last_metrics_dump=0.
        self.frame_times=deque(maxlen=7200)
        self.draw_times=deque(maxlen=7200)
        self.delivery_delays=deque(maxlen=7200)
        self.last_pending_delivery=None
        self.rendered_frames=0
        self.last_control=Control()
        self._resize_id=None
        self._frame_id=None
        self.devices={}
        self.connecting=False
        self.status=tk.StringVar(value=self.store.warning or '选择星区，开始一段新的航行。')
        self.mode_var=tk.StringVar(value='开发板倾斜' if self.mode=='board' else '键盘练习')
        self.device_var=tk.StringVar(value='自动选择开发板')
        self._build()
        self.renderer=Renderer(self.canvas)
        self.renderer.effects=self.store.data['settings']['effects']
        self.canvas.bind('<Configure>',self._resize)
        self.canvas.bind('<Button-1>',self._click)
        self.canvas.bind('<Double-Button-1>',self._double_click)
        self._key_press_binding=self.winfo_toplevel().bind('<KeyPress>',self._key_press,add='+')
        self._key_release_binding=self.winfo_toplevel().bind('<KeyRelease>',self._key_release,add='+')
        self._focus_binding=self.winfo_toplevel().bind('<FocusOut>',self._focus_out,add='+')
        self._unmap_binding=self.winfo_toplevel().bind('<Unmap>',self._unmap,add='+')
        self.after_idle(self._draw)
        self._frame_id=self.after(16,self._frame)

    def _build(self):
        header=ttk.Frame(self,style='Tilt.TFrame',padding=(24,13,24,8))
        header.pack(fill='x')
        ttk.Label(header,text='重力迷航',style='Tilt.TLabel',font=('Microsoft YaHei UI',14,'bold')).pack(side='left')
        ttk.Label(header,text='GRAVITY VOYAGER  /  '+VERSION,style='Tilt.Muted.TLabel').pack(side='left',padx=18)
        self.source_label=tk.Label(header,text='●  实板模式',bg=BG,fg=CYAN,font=('Microsoft YaHei UI',10))
        self.source_label.pack(side='right')
        tools=ttk.Frame(self,style='Tilt.TFrame',padding=(24,0,24,8))
        tools.pack(fill='x')
        source=ttk.Combobox(tools,textvariable=self.mode_var,values=('开发板倾斜','键盘练习'),width=12,state='readonly',style='Tilt.TCombobox')
        source.pack(side='left')
        source.bind('<<ComboboxSelected>>',self._change_mode)
        self.device_box=ttk.Combobox(tools,textvariable=self.device_var,width=30,state='readonly',style='Tilt.TCombobox')
        self.device_box.pack(side='left',padx=(12,6))
        for label,command in (('刷新设备',self.refresh_devices),('连接',self.connect),('断开',self.disconnect),('初始化板子',self.initialize)):
            ttk.Button(tools,text=label,command=command,style='Tilt.TButton',padding=(10,5)).pack(side='left',padx=3)
        self.canvas=tk.Canvas(self,bg=BG,highlightthickness=0,takefocus=True)
        self.canvas.pack(fill='both',expand=True)
        footer=ttk.Frame(self,style='Tilt.TFrame',padding=(24,10,24,6))
        footer.pack(fill='x')
        self.primary=ttk.Button(footer,text='开始航行',command=self.primary_action,style='Tilt.Primary.TButton',width=15)
        self.primary.pack(side='left',padx=(0,12))
        self.pause_button=ttk.Button(footer,text='暂停',command=lambda:self.pause('航行已暂停，可以随时继续。'),style='Tilt.TButton')
        self.pause_button.pack(side='left',padx=3)
        self.retry_button=ttk.Button(footer,text='重试本关',command=self.retry,style='Tilt.TButton')
        self.retry_button.pack(side='left',padx=3)
        ttk.Button(footer,text='返回星图',command=self.home,style='Tilt.TButton').pack(side='left',padx=3)
        ttk.Button(footer,text='握持校准',command=self.calibrate,style='Tilt.TButton').pack(side='left',padx=3)
        ttk.Button(footer,text='设置',command=self.settings,style='Tilt.TButton').pack(side='right',padx=3)
        ttk.Button(footer,text='玩法',command=self.help,style='Tilt.TButton').pack(side='right',padx=3)
        self.status_label=ttk.Label(self,textvariable=self.status,style='Tilt.Muted.TLabel',padding=(25,3,25,10),wraplength=1100)
        self.status_label.pack(fill='x')
        self._buttons()

    def _buttons(self):
        labels={'map':'开始航行','playing':'正在航行','paused':'继续航行','won':'下一星区','calibration':'正在校准'}
        self.primary.configure(text=labels.get(self.state,'开始航行'),state='disabled' if self.state in ('playing','calibration') else 'normal')
        if self.state=='won' and self.game and self.game.level.number==8:
            self.primary.configure(text='返回星图')
        self.pause_button.configure(state='normal' if self.state=='playing' else 'disabled')
        self.retry_button.configure(state='normal' if self.game and self.state in ('playing','paused','won') else 'disabled')
        self.source_label.configure(text='●  实板模式' if self.mode=='board' else '◆  键盘练习 · 成绩独立',fg=CYAN if self.mode=='board' else GOLD)

    def _resize(self,event):
        self.status_label.configure(wraplength=max(500,event.width-50))
        if self._resize_id:
            self.after_cancel(self._resize_id)
        self._resize_id=self.after(100,self._resized)

    def _resized(self):
        self._resize_id=None
        if not self.closed:
            self._draw()

    def _draw(self):
        if self.closed or self.canvas.winfo_width()<100:
            return
        if self.state=='map':
            self.renderer.map(self.store,self.mode,self.selected)
        elif self.state=='calibration':
            self.renderer.calibration(self.tilt)
            self.cal_phase=self.tilt.phase
        elif self.game:
            self.renderer.game(self.game,self.mode)
            self.renderer.update(self.game,self.last_control,self.notice)
            if self.state=='paused':
                self.renderer.overlay('暂泊一下',self.pause_reason)
            elif self.state=='won':
                final=self.game.level.number==8
                body=f'{self.game.elapsed:.1f} 秒  ·  能量 {len(self.game.collected)} / 3  ·  失误 {self.game.deaths} 次'
                if final:
                    body+='\n八个星区已经点亮。还可以回去挑战更多三星。'
                self.renderer.overlay('星核已点亮' if final else '航道已点亮',body,
                                      stars=self.game.stars,kicker='VOYAGE COMPLETE' if final else 'SECTOR COMPLETE')
        self._buttons()
        # Building a cached scene is an intentional transition, not gameplay time.
        if self.state=='playing':
            self.last_frame=time.perf_counter()
            # Give queued board telemetry one dispatch turn after scene creation.
            self.scene_ready_until=self.last_frame+.35
            self.last_pending_delivery=None

    def _click(self,event):
        self.canvas.focus_set()
        if self.state!='map':
            return
        for x,y,right,bottom,index,unlocked in self.renderer.card_hits:
            if x<=event.x<=right and y<=event.y<=bottom:
                if unlocked:
                    self.selected=index
                    self.status.set(f'{LEVELS[index].name}：'+LEVELS[index].hint)
                    self._draw()
                else:
                    self.status.set('先通过前一星区，即可解锁这里。键盘练习可以体验所有关卡。')
                return

    def _double_click(self,event):
        if self.state!='map':
            return
        for x,y,right,bottom,index,unlocked in self.renderer.card_hits:
            if x<=event.x<=right and y<=event.y<=bottom and unlocked:
                self.selected=index
                self.primary_action()
                return

    def _key_press(self,event):
        if not self.active or self.closed or isinstance(event.widget,(tk.Entry,ttk.Entry,ttk.Combobox)):
            return
        key=event.keysym.lower()
        repeated=key in self.pressed
        self.pressed.add(key)
        if repeated:
            return
        if key in ('escape','p'):
            if self.state=='playing':
                self.pause('航行已暂停，可以随时继续。')
            elif self.state=='paused':
                self.primary_action()
        elif key=='r' and self.state in ('playing','paused','won'):
            self.retry()
        elif key=='return' and not isinstance(event.widget,ttk.Button):
            self.primary_action()
        elif self.state=='map' and key in ('left','right','up','down'):
            delta={'left':-1,'right':1,'up':-4,'down':4}[key]
            self.selected=max(0,min(self.store.unlocked(self.mode)-1,self.selected+delta))
            self._draw()

    def _key_release(self,event):
        self.pressed.discard(event.keysym.lower())

    def _focus_out(self,event):
        self.after(100,self._check_focus)

    def _check_focus(self):
        if self.closed:
            return
        try:
            focused=self.winfo_toplevel().focus_displayof()
        except tk.TclError:
            focused=None
        if focused is None:
            self.pressed.clear()
            if self.state=='playing':
                self.pause('窗口暂时离开前台，航行已暂停。回来后点击继续。')

    def _unmap(self,event):
        if event.widget==self.winfo_toplevel():
            self.pause('窗口已最小化，航行已暂停。')

    def refresh_devices(self):
        try:
            from device_discovery import candidates
            found=candidates()
            self.devices={b.label:b.serial for b in found}
            self.device_box.configure(values=('自动选择开发板',*self.devices))
            if self.device_var.get() not in self.devices and self.device_var.get()!='自动选择开发板':
                self.device_var.set('自动选择开发板')
            self.status.set(f'发现 {len(found)} 块开发板。连接游戏前请先关闭实时监测主程序。')
        except Exception as error:
            self.status.set('设备检查未完成：'+str(error))

    def connect(self):
        if self.on_connect:
            self.connecting=True
            self.status.set('正在连接开发板；如果端口被占用，请先关闭实时监测主程序。')
            self.on_connect(self.devices.get(self.device_var.get()))
        else:
            self.status.set('请通过宿主程序连接开发板。')

    def disconnect(self):
        self.pause('开发板已断开。重新连接并校准后可继续。')
        self.connecting=False
        if self.on_disconnect:
            self.on_disconnect()

    def initialize(self):
        self.pause('准备初始化开发板，航行已暂停。')
        if self.on_initialize:
            self.on_initialize(self.devices.get(self.device_var.get()))

    def _change_mode(self,event=None):
        mode='board' if self.mode_var.get()=='开发板倾斜' else 'keyboard'
        if mode==self.mode:
            return
        self.pressed.clear()
        self.journal.write('mode_changed',previous=self.mode,current=mode)
        self.mode=mode
        self.pending_start=False
        self.home()
        self.selected=min(self.selected,self.store.unlocked(mode)-1)
        self.status.set('键盘练习不计入实板成绩。方向键移动，空格刹车。' if mode=='keyboard' else '实板模式：开始前请连接并完成握持校准。')
        if mode=='keyboard' and self.on_disconnect:
            self.on_disconnect()
        self._draw()

    def primary_action(self):
        if self.state=='map':
            if self.mode=='board' and (not self.tilt.ready or not self.tilt.fresh(time.perf_counter())):
                self.pending_start=True
                self.calibrate()
            else:
                self.start_level(self.selected)
        elif self.state=='paused':
            if self.mode=='board' and (not self.tilt.ready or not self.tilt.fresh(time.perf_counter())):
                self.return_to_game=True
                self.calibrate()
                return
            self.game.paused=False
            self.game.vx=self.game.vy=0.
            self.game.accumulator=0.
            self.state='playing'
            self.pressed.clear()
            self.last_frame=time.perf_counter()
            self.journal.write('resume',level=self.game.level.number)
            self._draw()
            self.canvas.focus_set()
        elif self.state=='won':
            if self.game.level.number==8:
                self.home()
            else:
                self.selected=self.game.level.number
                self.start_level(self.selected)

    def start_level(self,index):
        if not 0<=index<self.store.unlocked(self.mode):
            return
        if self.mode=='board' and (not self.tilt.ready or not self.tilt.fresh(time.perf_counter())):
            self.selected=index
            self.pending_start=True
            self.calibrate()
            return
        self.selected=index
        self.game=Game(LEVELS[index])
        self.state='playing'
        self.pressed.clear()
        self.pending_start=False
        self.last_frame=time.perf_counter()
        self.last_control=Control()
        self.status.set('轻倾板子移动，按住中键刹车。P / Esc 暂停。' if self.mode=='board' else '方向键移动 · 空格刹车 · P / Esc 暂停 · R 重试')
        self.journal.write('level_start',level=index+1,source=self.mode,preview=self.preview)
        self._draw()
        self.canvas.focus_set()

    def retry(self):
        if self.game:
            self.journal.write('restart',level=self.game.level.number)
            self.start_level(self.game.level.number-1)

    def home(self):
        if self.game and self.state in ('playing','paused','calibration'):
            self.journal.write('level_abandoned',**self.game.result(),source=self.mode)
        self.state='map'
        self.game=None
        self.pending_start=self.return_to_game=False
        self.pressed.clear()
        self._draw()

    def activate(self):
        self.active=True

    def pause(self,reason='航行已暂停。'):
        if self.closed or self.state!='playing':
            return
        self.state='paused'
        self.game.paused=True
        self.pressed.clear()
        self.pause_reason=reason
        self.journal.write('pause',reason=reason,level=self.game.level.number)
        self._draw()

    def calibrate(self):
        if self.mode!='board':
            self.status.set('键盘练习不需要校准。切换到开发板倾斜后即可校准。')
            return
        if self.state=='playing':
            self.pause('重新校准后可继续。')
            self.return_to_game=True
        elif self.state=='paused':
            self.return_to_game=True
        self.state='calibration'
        if self.tilt.fresh(time.perf_counter()):
            self.tilt.begin()
        else:
            self.tilt.invalidate('等待开发板的新三轴数据。连接成功后会自动开始校准。')
            if not self.connecting and not self.tilt.connected:
                self.connect()
        self._draw()
        self._buttons()

    def feed(self,message):
        if self.closed:
            return
        now=time.perf_counter()
        self.tilt.feed(message,message.get('received_at',now))
        kind=message['kind']
        if kind=='status':
            self.connecting=not message.get('connected',False)
            self.status.set(message.get('text',''))
            if not message.get('connected') and self.state=='playing' and self.mode=='board':
                self.pause('开发板连接中断。重连、校准后再继续，不会扣除机会。')
        elif kind=='identity':
            self.journal.write('board_identity',**message['device'])
        elif kind=='data':
            if message.get('xyz'):
                self.last_pending_delivery=message.get('received_at',now)
            if self.state=='calibration' and self.tilt.phase=='idle' and self.tilt.fresh(now):
                self.tilt.begin()
                self._draw()
        elif kind in ('notice','game_session') and message.get('text'):
            self.status.set(message['text'])

    def _frame(self):
        if self.closed:
            return
        began=time.perf_counter()
        dt=began-self.last_frame
        self.last_frame=began
        if self.active and self.state=='playing':
            if dt>.25:
                self.pause('画面曾短暂停顿，航行已暂停，点击继续即可。')
            elif self.mode=='board' and not self.tilt.fresh(began) and began<self.scene_ready_until:
                pass  # Waiting for the first fresh frame; neither clock nor ball advances.
            elif self.mode=='board' and (not self.tilt.ready or not self.tilt.fresh(began)):
                self.pause('三轴数据暂时中断，已暂停计时。数据恢复后点击继续。')
            else:
                if self.mode=='keyboard':
                    control=Control(float('right' in self.pressed)-float('left' in self.pressed),
                                    float('down' in self.pressed)-float('up' in self.pressed),'space' in self.pressed)
                else:
                    control=self.tilt.control(began)
                self.last_control=control
                self.game.advance(dt,control)
                self.frame_times.append(dt)
                for event in self.game.drain_events():
                    self.journal.write('game_event',source=self.mode,level=self.game.level.number,event=event)
                    self._event(event,began)
                if began-self.last_input_log>=.05:
                    self.last_input_log=began
                    self.journal.input(host_monotonic=began,game_seconds=self.game.elapsed,source=self.mode,
                                       level=self.game.level.number,control=control.__dict__,
                                       xyz=self.tilt.raw if self.mode=='board' else None,
                                       seq=self.tilt.last_seq if self.mode=='board' else None,
                                       ball=[self.game.x,self.game.y,self.game.vx,self.game.vy])
                if self.state=='playing':
                    self.renderer.update(self.game,control,self.notice if began<self.notice_until else '')
                    self.rendered_frames += 1
        elif self.state=='calibration':
            if self.tilt.phase!=self.cal_phase:
                if self.tilt.ready:
                    for event in self.tilt.events:
                        self.journal.write('calibration',details=event)
                    self.tilt.events.clear()
                    if self.return_to_game and self.game:
                        self.state='paused'
                        self.return_to_game=False
                        self.pause_reason='校准完成。点击继续，重新出发。'
                        self._draw()
                    elif self.pending_start:
                        self.start_level(self.selected)
                    else:
                        self.home()
                        self.status.set('握持校准完成，可以开始航行。')
                else:
                    self._draw()
            else:
                self.renderer.update_calibration(self.tilt)
        ended=time.perf_counter()
        if self.state=='playing':
            self.draw_times.append(ended-began)
            if self.last_pending_delivery is not None:
                self.delivery_delays.append(max(0,ended-self.last_pending_delivery))
                self.last_pending_delivery=None
        if began-self.last_metrics_dump>2:
            self.last_metrics_dump=began
            self.dump_state()
        self._frame_id=self.after(max(1,round((1/60-(ended-began))*1000)),self._frame)

    def _event(self,event,now):
        kind=event['kind']
        notices={'energy':'能量 +1','core':'通行核心已获得，终点已开启',
                 'checkpoint':'检查点已点亮','gate_open':'能量门已开启',
                 'death':'调整一下，从检查点再来','locked':'先收集金色通行核心，再进入终点'}
        if kind in notices:
            self.notice=notices[kind]
            self.notice_until=now+2.4
        if self.store.data['settings']['sound']:
            self.sounds.play(kind)
        if kind=='win':
            self.state='won'
            if not self.preview:
                try:
                    self.store.record(self.mode,self.game.result())
                except OSError as error:
                    self.status.set('本关已通过，但进度未能保存：'+str(error))
                    self.journal.write('save_failed',error=repr(error),result=self.game.result())
            self._draw()

    def settings(self):
        self.pause('设置调整后，点击继续即可返回航行。')
        win=tk.Toplevel(self)
        win.title('航行设置')
        win.configure(bg=BG)
        win.transient(self.winfo_toplevel())
        win.resizable(False,False)
        box=ttk.Frame(win,style='Tilt.TFrame',padding=24)
        box.pack(fill='both',expand=True)
        ttk.Label(box,text='航行设置',style='Tilt.TLabel',font=('Microsoft YaHei UI',16,'bold')).pack(anchor='w',pady=(0,20))
        ttk.Label(box,text='倾斜灵敏度（达到最大推力所需角度）',style='Tilt.TLabel').pack(anchor='w')
        sensitivity=tk.StringVar(value={12:'灵敏 · 12°',18:'标准 · 18°',24:'稳健 · 24°'}[self.store.data['settings']['sensitivity']])
        combo=ttk.Combobox(box,textvariable=sensitivity,values=('灵敏 · 12°','标准 · 18°','稳健 · 24°'),state='readonly',width=30)
        combo.pack(anchor='w',pady=(8,18))
        effects=tk.BooleanVar(value=self.store.data['settings']['effects'])
        sound=tk.BooleanVar(value=self.store.data['settings']['sound'])
        tk.Checkbutton(box,text='显示球体尾迹',variable=effects,bg=BG,fg=TEXT,selectcolor=PANEL,activebackground=BG,activeforeground=TEXT).pack(anchor='w',pady=4)
        tk.Checkbutton(box,text='播放收集与通关音效',variable=sound,bg=BG,fg=TEXT,selectcolor=PANEL,activebackground=BG,activeforeground=TEXT).pack(anchor='w',pady=4)
        ttk.Label(box,text='关闭尾迹可减少画面运动；机关节奏保持一致。',style='Tilt.Muted.TLabel').pack(anchor='w',pady=(14,20))
        def save():
            self.store.data['settings']={'sensitivity':{'灵敏 · 12°':12,'标准 · 18°':18,'稳健 · 24°':24}[sensitivity.get()],
                                         'effects':effects.get(),'sound':sound.get()}
            try:
                self.store.commit()
                self.tilt.sensitivity=self.store.data['settings']['sensitivity']
                self.renderer.effects=effects.get()
                win.destroy()
            except OSError as error:
                messagebox.showerror('设置未保存',str(error),parent=win)
        ttk.Button(box,text='保存设置',style='Tilt.Primary.TButton',command=save).pack(anchor='e')
        win.grab_set()
        combo.focus_set()

    def help(self):
        self.pause('查看玩法后，点击继续即可返回航行。')
        messagebox.showinfo('重力迷航 · 航行指南',
            '目标：收集金色通行核心，进入圆形终点。菱形小能量决定额外星级。\n\n'
            '开发板：轻轻倾斜移动，按住中间按键刹车。初次使用跟随握持校准。\n'
            '键盘：方向键移动，空格刹车。P / Esc 暂停，R 重试本关。\n\n'
            '一星：到达终点。二星：再收齐三枚能量。\n'
            '三星：收齐能量、零失误，并达到本关时间目标。\n\n'
            '金色压板：慢下来并停留片刻开门。\n'
            '红色激光：等待熄灭后通过；金色预警代表即将亮起。\n'
            '蓝紫色冰面：惯性更大，可用刹车减速。\n'
            '失误后回到最近检查点，已收集物保留，不限次数。\n\n'
            '独立版连接前，请先关闭实时监测主程序。\n'
            '实板与键盘记录分别保存；键盘练习可体验全部八关。',parent=self.winfo_toplevel())

    def metrics(self):
        def percentile(values,fraction):
            values=sorted(values)
            if not values:
                return None
            return values[min(len(values)-1,int((len(values)-1)*fraction))]
        return {'source':self.mode,'preview':self.preview,'rendered_frames':self.rendered_frames,
                'fps':len(self.frame_times)/sum(self.frame_times) if self.frame_times else None,
                'frame_p95_ms':None if not self.frame_times else percentile(self.frame_times,.95)*1000,
                'update_p95_ms':None if not self.draw_times else percentile(self.draw_times,.95)*1000,
                'receive_to_canvas_submit_p95_ms':None if not self.delivery_delays else percentile(self.delivery_delays,.95)*1000,
                'delivery_measurement':'host decoder publish to Canvas update; excludes sensor and display hardware latency',
                'xyz_received':self.tilt.received,'xyz_missing':self.tilt.missing,
                'board_serial':self.tilt.serial,'state':self.state,'result':self.game.result() if self.game else None}

    def dump_state(self):
        try:
            value={**self.metrics(),'session_directory':str(self.journal.path),'game_version':VERSION,
                   'tilt_phase':self.tilt.phase,'connected':self.tilt.connected,
                   'status':self.status.get(),'updated':time.time()}
            target=self.save_dir/'runtime_state.json'
            tmp=target.with_suffix('.tmp')
            tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
            tmp.replace(target)
        except OSError:
            pass

    def close(self):
        if self.closed:
            return
        self.closed=True
        self.state='closed'
        self.pressed.clear()
        if self._frame_id:
            self.after_cancel(self._frame_id)
        if self._resize_id:
            self.after_cancel(self._resize_id)
        root=self.winfo_toplevel()
        for sequence,binding in (('<KeyPress>',self._key_press_binding),('<KeyRelease>',self._key_release_binding),
                                 ('<FocusOut>',self._focus_binding),('<Unmap>',self._unmap_binding)):
            root.unbind(sequence,binding)
        self.dump_state()
        self.journal.close(**self.metrics())
        if self._timer_resolution:
            ctypes.windll.winmm.timeEndPeriod(1)
            self._timer_resolution=False
