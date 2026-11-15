"""Six labelled, independent PC recordings; SongRec is an external process."""
import json
import os
from pathlib import Path
import queue
import threading
import winsound

from songrec_probe import SCHEDULE, VERSION, write_json

LABELS = {'correct': '正确', 'wrong': '误认', 'not_found': '未命中', 'error': '服务错误'}


class App:
    def __init__(self, session):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk, self.session = tk, ttk, session
        self.queue = queue.Queue()
        self.stop = threading.Event()
        self.busy, self.closing, self.last = False, False, None
        self.devices = []
        self.root = tk.Tk()
        self.root.title('SongRec · 电脑麦克风六项对照')
        self.root.geometry(f'{min(1080, self.root.winfo_screenwidth()-60)}x{min(820, self.root.winfo_screenheight()-80)}')
        self.root.minsize(800, 590)
        self.root.configure(bg='#edf3f7')
        self.device = tk.StringVar()
        self.instruction = tk.StringVar()
        self.position = tk.StringVar()
        self.status = tk.StringVar(value='手机外放音乐，准备好后开始录音。每项录满 20 秒。')
        self.level = tk.StringVar(value='输入电平：等待录音')
        self.result = tk.StringVar(value='识别结果将显示在这里')
        self.gate = tk.StringVar()
        self.progress = tk.DoubleVar(value=0)
        header = tk.Frame(self.root, bg='#173b5c')
        header.pack(fill='x')
        tk.Label(header, text='SongRec · 电脑麦克风对照', bg='#173b5c', fg='white',
                 font=('Microsoft YaHei UI', 21, 'bold')).pack(side='left', padx=20, pady=18)
        tk.Label(header, text='六项验收  v'+VERSION, bg='#173b5c', fg='#c8dce9').pack(side='right', padx=20)
        outer = ttk.Frame(self.root)
        outer.pack(fill='both', expand=True)
        canvas = tk.Canvas(outer, highlightthickness=0, bg='#edf3f7')
        bar = ttk.Scrollbar(outer, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        frame = ttk.Frame(canvas, padding=18)
        window = canvas.create_window((0, 0), window=frame, anchor='nw')
        frame.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(window, width=e.width))
        self.root.bind_all('<MouseWheel>', lambda e: canvas.yview_scroll(-int(e.delta/120), 'units')
                           if e.widget.winfo_class() != 'Treeview' else None)
        controls = ttk.Frame(frame)
        controls.pack(fill='x')
        ttk.Label(controls, text='电脑麦克风').pack(side='left')
        self.device_box = ttk.Combobox(controls, textvariable=self.device, state='readonly', width=47)
        self.device_box.pack(side='left', padx=8)
        self.refresh_button = ttk.Button(controls, text='刷新设备', command=self.refresh_devices)
        self.refresh_button.pack(side='left')
        ttk.Label(frame, text='建议选择普通麦克风；手机保持相同距离和音量，使用原唱录音室版本。',
                  foreground='#536d82', wraplength=950).pack(anchor='w', pady=(8, 12))
        card = ttk.LabelFrame(frame, text='当前步骤', padding=15)
        card.pack(fill='x')
        ttk.Label(card, textvariable=self.instruction, font=('Microsoft YaHei UI', 18, 'bold'),
                  wraplength=940).pack(anchor='w')
        ttk.Label(card, textvariable=self.position, font=('Microsoft YaHei UI', 12),
                  wraplength=940).pack(anchor='w', pady=(8, 12))
        buttons = ttk.Frame(card)
        buttons.pack(fill='x')
        self.start_button = ttk.Button(buttons, text='准备好了，录制本项 20 秒', command=self.start)
        self.start_button.pack(side='left')
        self.stop_button = ttk.Button(buttons, text='停止录音，不识别', command=self.stop.set, state='disabled')
        self.stop_button.pack(side='left', padx=10)
        self.new_button = ttk.Button(buttons, text='开始新一轮', command=self.new_round)
        self.new_button.pack(side='right')
        ttk.Progressbar(card, variable=self.progress, maximum=100).pack(fill='x', pady=(14, 5))
        ttk.Label(card, textvariable=self.level).pack(anchor='w')
        ttk.Label(frame, textvariable=self.status, foreground='#0a7c75', wraplength=980,
                  font=('Microsoft YaHei UI', 11, 'bold')).pack(anchor='w', pady=12)
        ttk.Label(frame, textvariable=self.result, font=('Microsoft YaHei UI', 16, 'bold'),
                  wraplength=980).pack(anchor='w', pady=(0, 10))
        self.table = ttk.Treeview(frame, columns=('step', 'expected', 'actual', 'grade'), show='headings', height=6)
        for key, text, width in [('step', '步骤', 65), ('expected', '本项播放', 300),
                                 ('actual', '服务实际返回', 370), ('grade', '判定', 85)]:
            self.table.heading(key, text=text)
            self.table.column(key, width=width, minwidth=55)
        self.table.pack(fill='x')
        ttk.Label(frame, textvariable=self.gate, font=('Microsoft YaHei UI', 12, 'bold'),
                  foreground='#173b5c', wraplength=980).pack(anchor='w', pady=12)
        bottom = ttk.Frame(frame)
        bottom.pack(fill='x')
        self.play_raw = ttk.Button(bottom, text='试听原始录音', command=lambda: self.play('wav'))
        self.play_raw.pack(side='left')
        self.play_clip = ttk.Button(bottom, text='试听识别片段', command=lambda: self.play('clip'))
        self.play_clip.pack(side='left', padx=8)
        self.import_button = ttk.Button(bottom, text='WAV 文件辅助对照', command=self.import_wav)
        self.import_button.pack(side='left')
        ttk.Button(bottom, text='打开记录目录', command=lambda: os.startfile(str(session.root))).pack(side='right')
        ttk.Label(frame, text='通过标准：六项至少五项正确，且没有误认。文件对照不计入六项成绩。\n'
                  '原始 20 秒录音完整保留，识别使用居中 12 秒；未命中和网络错误都会如实记录。',
                  wraplength=980, foreground='#536d82').pack(anchor='w', pady=(12, 0))
        self.refresh_devices()
        self.refresh_results()
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.after(80, self.drain)

    def refresh_devices(self):
        from pc_mic_capture import input_devices
        try:
            self.devices = input_devices()
            self.device_box.configure(values=[d['label'] for d in self.devices])
            if self.device.get() not in [d['label'] for d in self.devices] and self.devices:
                self.device.set(next((d['label'] for d in self.devices if not d['loopback_name']
                                      and 'noise' not in d['name'].casefold()), self.devices[0]['label']))
            if not self.devices:
                self.status.set('没有检测到电脑麦克风，请连接后刷新。')
        except Exception as error:
            self.status.set(str(error))

    def refresh_results(self):
        self.table.delete(*self.table.get_children())
        rows = self.session.state['rows']
        for i, item in enumerate(SCHEDULE):
            row = rows[i] if i < len(rows) else None
            reply = row['result'] if row else {}
            actual = reply['title']+' — '+reply['artist'] if reply.get('matched') else reply.get('message', '等待录音')
            self.table.insert('', 'end', values=(f'{i+1}/6', f'{item["title"]} · 第{item["repeat"]}次',
                                                 actual, LABELS[row['grade']] if row else '待测'))
        gate = self.session.state['gate']
        self.gate.set(f'已完成 {gate["attempted"]}/6；正确 {gate["correct"]}；误认 {gate["wrong"]}；'
                      f'未命中 {gate["not_found"]}；服务错误 {gate["errors"]}')
        if len(rows) < 6:
            current = SCHEDULE[len(rows)]
            self.instruction.set(f'{len(rows)+1}/6   {current["title"]}  —  {current["artist"]}')
            pos = current['position_s']
            self.position.set(f'第 {current["repeat"]} 次：请把歌曲调到 {pos//60:02d}:{pos%60:02d}，开始外放后点击录音。')
        else:
            passed = gate['status'] == 'passed'
            self.instruction.set('本轮检查完成 · '+('达到接入门槛' if passed else '尚未达到接入门槛'))
            self.position.set('结果与六份录音已保存。请回到 Codex 回复“完成”。')
            self.status.set('六项至少五项正确且零误认，具备进入 ShazamIO 验证的条件。' if passed else
                            '本轮结果尚未通过；保留全部结果，先分析原因，不自动进入接入阶段。')
        self.start_button.configure(state='disabled' if self.busy or len(rows) == 6 else 'normal')
        if rows and self.last is None:
            self.last = rows[-1]

    def set_busy(self, value):
        self.busy = value
        for button in (self.start_button, self.new_button, self.import_button, self.refresh_button, self.play_raw, self.play_clip):
            button.configure(state='disabled' if value else 'normal')
        self.device_box.configure(state='disabled' if value else 'readonly')
        if not value:
            self.stop_button.configure(state='disabled')
            self.refresh_results()

    def background(self, work):
        if self.busy:
            return
        self.set_busy(True)
        def run():
            try:
                work()
            except Exception as error:
                write_json(self.session.root/'last_error.json', {'error_type': type(error).__name__, 'message': str(error)})
                self.queue.put(('error', {'message': str(error)}))
            finally:
                self.queue.put(('idle', {}))
        threading.Thread(target=run, daemon=True).start()

    def start(self):
        from pc_mic_capture import record
        device = next((d for d in self.devices if d['label'] == self.device.get()), None)
        if self.busy or device is None:
            return
        winsound.PlaySound(None, 0)
        self.stop.clear()
        self.progress.set(0)
        self.status.set('正在录制电脑麦克风，请保持音乐外放……')
        self.result.set('正在录音，尚未识别')
        self.stop_button.configure(state='normal')
        def work():
            index, directory = self.session.new_capture()
            def progress(frames, total, level):
                self.queue.put(('progress', {'frames': frames, 'total': total, 'level': level}))
            metadata = record(device['id'], 20, directory/'original.wav', stop=self.stop, progress=progress)
            self.queue.put(('stage', {'text': '录音完成，正在通过 SongRec 查询 Shazam……' if metadata['complete'] else '已停止，未调用识别服务。'}))
            row = self.session.finish_capture(index, directory, metadata, device)
            self.queue.put(('row', {'row': row, 'wav': str(directory/'original.wav')}))
        self.background(work)

    def new_round(self):
        from tkinter import messagebox
        if not messagebox.askyesno('开始新一轮', '保留已有录音和结果，另开一轮六项检查？', parent=self.root):
            return
        self.session.new()
        self.last = None
        self.progress.set(0)
        self.result.set('新一轮尚未录音')
        self.status.set('旧记录已保留，请按步骤准备第一首歌。')
        self.refresh_results()

    def import_wav(self):
        from tkinter import filedialog
        filename = filedialog.askopenfilename(parent=self.root, title='辅助对照：12至60秒、8/16kHz单声道PCM16 WAV',
                                               filetypes=[('PCM WAV', '*.wav')])
        if filename:
            self.status.set('正在识别文件；文件对照不计入六项成绩。')
            def work():
                row = self.session.auxiliary(Path(filename))
                self.queue.put(('aux', {'row': row}))
            self.background(work)

    def show_reply(self, row):
        reply = row['result']
        self.result.set(reply['title']+' — '+reply['artist'] if reply.get('matched') else reply['message'])

    def play(self, key):
        if self.busy or not self.last:
            return
        path = self.last.get(key)
        if path and Path(path).is_file():
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)

    def drain(self):
        while True:
            try:
                kind, data = self.queue.get_nowait()
            except queue.Empty:
                break
            if kind == 'progress':
                self.progress.set(data['frames']/data['total']*100)
                self.level.set(f'已录 {data["frames"]/16000:.1f}/20 秒；RMS {data["level"]["rms_dbfs"]:.1f} dBFS；'
                               f'峰值 {data["level"]["peak_dbfs"]:.1f} dBFS')
            elif kind == 'stage':
                self.stop_button.configure(state='disabled')
                self.status.set(data['text'])
            elif kind == 'row':
                if data['row']:
                    self.last = data['row']
                    self.show_reply(self.last)
                    self.status.set('本项已保存。请准备下一项歌曲或播放位置，再点录音。')
                else:
                    self.last = {'wav': data['wav']}
                    self.status.set('录音已停止，部分录音已保存，本项未计入成绩。')
            elif kind == 'aux':
                self.last = {'wav': data['row']['original'], 'clip': data['row']['clip']}
                self.show_reply(data['row'])
                self.status.set('辅助对照已保存，不计入六项成绩。')
            elif kind == 'error':
                self.status.set(data['message'])
            elif kind == 'idle':
                self.set_busy(False)
        if self.closing and not self.busy:
            self.root.destroy()
            return
        self.root.after(80, self.drain)

    def close(self):
        winsound.PlaySound(None, 0)
        if self.busy:
            self.closing = True
            self.stop.set()
            self.status.set('正在停止录音或等待本次请求结束，保存后关闭。')
        else:
            self.root.destroy()
