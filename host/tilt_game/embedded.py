"""Host adapter. The accepted game mechanics and standalone executable stay intact."""
import json
import os
from pathlib import Path
import time
import tkinter as tk
from tkinter import ttk

from .app import GamePanel, configure_styles
from .storage import SaveStore
from .render import BG, CYAN, GOLD


def import_standalone_save(destination,source=None):
    destination=Path(destination)
    source=Path(source) if source is not None else Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData/Local')))/'NexysGravityVoyager/game'
    if (destination/'progress.json').exists() or not (source/'progress.json').exists():
        return False
    previous=SaveStore(source)
    if previous.warning:
        return False
    imported=SaveStore(destination)
    imported.data=json.loads(json.dumps(previous.data))
    imported.commit()
    return True


class EmbeddedGamePanel(GamePanel):
    def __init__(self,host,save_dir,*,migrate=True):
        self.host=host
        self.lease_ready=False
        self.requested=False
        self.pending=None
        self._wrapping=False
        imported=import_standalone_save(save_dir) if migrate else False
        super().__init__(host.pages['game'],'board',save_dir,
                         on_connect=lambda serial=None:host.connect(),
                         on_disconnect=self.release)
        self.pack(fill='both',expand=True)
        self.active=False
        host.theme_manager.listeners.append(self.theme_changed)
        if imported:
            self.status.set('已保留独立版通关进度。设备使用上方主程序连接，直接开始即可。')
        else:
            self.status.set('设备使用上方主程序连接，点击开始航行后进行握持校准。')

    def _build(self):
        super()._build()
        # The host and game scene already provide titles; keep room for the map.
        self.source_label.master.pack_forget()
        tools=self.device_box.master
        for child in tools.winfo_children()[1:]:
            child.pack_forget()
        ttk.Label(tools,text='使用上方设备连接 · 按住板载中键刹车',style='Tilt.Muted.TLabel').pack(side='left',padx=14)
        footer=self.primary.master
        self._footer_buttons=list(footer.winfo_children())
        for child in self._footer_buttons:
            child.pack_forget()
        footer.bind('<Configure>',lambda e:self._schedule_wrap(),add='+')
        self.after_idle(self._wrap)

    def _schedule_wrap(self):
        if not self._wrapping:
            self._wrapping=True
            self.after_idle(self._wrap)

    def _wrap(self):
        self._wrapping=False
        if self.closed:
            return
        footer=self.primary.master
        available=max(260,footer.winfo_width()-48)
        x=y=line=0
        for button in self._footer_buttons:
            width,height=button.winfo_reqwidth()+6,button.winfo_reqheight()+4
            if x and x+width>available:
                x=0;y+=line;line=0
            button.place(x=24+x,y=8+y,width=width-6,height=height-4)
            x+=width;line=max(line,height)
        footer.configure(height=y+line+16)

    def theme_changed(self):
        if not self.closed:
            configure_styles(self.host.root)
            # ttkbootstrap also restyles native Tk widgets outside ThemeManager.
            self.canvas.configure(bg=BG)
            self.source_label.configure(bg=BG,fg=CYAN if self.mode=='board' else GOLD)

    def request(self,action):
        self.pending=action
        if not self.host.worker or not self.host.worker.is_alive():
            self.status.set('请先用上方“连接 / 重连”连接开发板，或切换键盘练习。')
            self.host.connect()
            return
        if not self.host.connected:
            self.status.set('正在等待主程序连接开发板…')
            return
        if not self.requested:
            self.requested=True
            self.status.set('正在准备体感游戏…')
            self.host.action('game_enter')

    def release(self):
        self.pending=None
        if self.lease_ready or self.requested:
            self.host.action('game_exit')
        self.lease_ready=False
        self.requested=False

    def activate(self):
        self.active=True

    def deactivate(self):
        self.pause('已离开游戏页面，返回后点击继续。')
        if self.state=='calibration':
            self.tilt.invalidate('返回游戏后请重新校准。')
            if self.game:
                self.state='paused'
                self.pause_reason='校准已暂停，返回后点击继续。'
            else:
                self.home()
        self.active=False
        self.pressed.clear()
        self.release()

    def primary_action(self):
        if self.mode=='board' and not self.lease_ready:
            self.request(('primary',None))
            return
        super().primary_action()

    def start_level(self,index):
        if self.mode=='board' and not self.lease_ready:
            self.request(('level',index))
            return
        super().start_level(index)

    def calibrate(self):
        if self.mode=='board' and not self.lease_ready:
            self.request(('calibrate',None))
            return
        super().calibrate()

    def feed(self,message):
        if self.closed:
            return
        kind=message['kind']
        super().feed(message)
        if kind=='status' and message.get('connected') and self.pending and self.active:
            self.request(self.pending)
        elif kind in ('reset','stopped') or kind=='status' and not message.get('connected'):
            self.lease_ready=False
            self.requested=False
        elif kind=='game_session':
            self.requested=False
            self.lease_ready=bool(message.get('ready'))
            if self.lease_ready and self.active:
                pending,self.pending=self.pending,None
                if pending:
                    action,index=pending
                    if action=='primary':super().primary_action()
                    elif action=='level':super().start_level(index)
                    elif action=='calibrate':super().calibrate()
            elif not self.lease_ready:
                if self.state=='playing':
                    self.pause(message.get('text','体感游戏暂时退出，点击继续后重新准备。'))
                if message.get('error'):
                    self.pending=None
                    self.status.set(message.get('text','游戏未能就绪，请重试。'))

    def help(self):
        self.pause('查看玩法后，点击继续即可返回航行。')
        from tkinter import messagebox
        messagebox.showinfo('体感游戏 · 重力迷航',
            '轻轻倾斜开发板控制小球，按住五向按键正中的 BTNC 刹车。\n'
            '先收集较大的通行核心，再进入圆形终点；三枚小能量用于挑战额外星级。\n\n'
            '压板上慢下来停留片刻即可开门；激光熄灭后再通过；冰面上更容易滑动。\n'
            '跌落后从检查点继续，收集物保留，不限重试次数。\n\n'
            '键盘练习：方向键移动，空格刹车。P / Esc 暂停，R 重试。\n'
            '游戏使用主程序已连接的设备。先关闭 SW15 并退出识曲，再开始实板游戏。\n'
            '离开游戏页会暂停并恢复原自动记录；回到游戏页后手动继续。',parent=self.host.root)

    def close(self):
        self.release()
        if self.theme_changed in self.host.theme_manager.listeners:
            self.host.theme_manager.listeners.remove(self.theme_changed)
        super().close()
