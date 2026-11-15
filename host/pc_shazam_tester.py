"""Standalone ShazamIO desktop entry; no board or AudioTag credentials."""
import argparse
import json
import os
from pathlib import Path
import queue
import sys
import threading
import winsound

from pc_shazam_backend import (Backend, VERSION, SHAZAMIO_VERSION, CORE_VERSION,
                               data_root, replay_session, versions, worker)
from songrec_probe import write_json


class App:
    def __init__(self, backend):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk, self.backend = tk, ttk, backend
        self.queue, self.stop = queue.Queue(), threading.Event()
        self.cancel_wait = threading.Event()
        backend.client.cancel_event = self.cancel_wait
        backend.client.on_wait = lambda seconds: self.queue.put(('stage', {'message': f'遵守服务请求间隔，约 {seconds:.0f} 秒后开始识别……'}))
        self.busy, self.closing, self.last, self.devices = False, False, None, []
        self.root = tk.Tk()
        self.root.title('电脑麦克风 · ShazamIO 识曲测试')
        self.root.geometry(f'{min(1060,self.root.winfo_screenwidth()-60)}x{min(780,self.root.winfo_screenheight()-80)}')
        self.root.minsize(810, 590)
        self.device = tk.StringVar()
        self.seconds = tk.StringVar(value='20')
        self.status = tk.StringVar(value='选择电脑麦克风，手机外放歌曲后开始录音。')
        self.song = tk.StringVar(value='等待识别歌曲')
        self.artist = tk.StringVar(value='Shazam 在线识曲')
        self.level = tk.StringVar(value='输入电平：等待录音')
        self.detail = tk.StringVar(value='原录音和识别片段都会保留，可以分别试听。')
        self.validation = tk.StringVar(value='')
        self.progress = tk.DoubleVar(value=0)
        header = tk.Frame(self.root, bg='#173b5c')
        header.pack(fill='x')
        tk.Label(header, text='电脑麦克风 · Shazam 识曲', font=('Microsoft YaHei UI', 21, 'bold'),
                 fg='white', bg='#173b5c').pack(side='left', padx=20, pady=18)
        tk.Label(header, text='独立测试  v'+VERSION, fg='#c8dce9', bg='#173b5c').pack(side='right', padx=20)
        outer = ttk.Frame(self.root)
        outer.pack(fill='both', expand=True)
        canvas = tk.Canvas(outer, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        frame = ttk.Frame(canvas, padding=18)
        window = canvas.create_window((0, 0), window=frame, anchor='nw')
        frame.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(window, width=e.width))
        self.root.bind_all('<MouseWheel>', lambda e: canvas.yview_scroll(-int(e.delta/120), 'units'))
        inputs = ttk.Frame(frame)
        inputs.pack(fill='x')
        ttk.Label(inputs, text='电脑麦克风').pack(side='left')
        self.devices_box = ttk.Combobox(inputs, textvariable=self.device, state='readonly', width=43)
        self.devices_box.pack(side='left', padx=8)
        self.refresh_button = ttk.Button(inputs, text='刷新设备', command=self.refresh_devices)
        self.refresh_button.pack(side='left')
        ttk.Label(inputs, text='录音长度').pack(side='left', padx=(14, 5))
        self.duration_box = ttk.Combobox(inputs, textvariable=self.seconds, values=('20','30'), state='readonly', width=4)
        self.duration_box.pack(side='left')
        ttk.Label(inputs, text='秒').pack(side='left', padx=4)
        ttk.Label(frame, text='建议选择普通麦克风，让手机音乐清楚地传到麦克风。录满后自动识别。',
                  foreground='#536d82', wraplength=950).pack(anchor='w', pady=(10, 12))
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x')
        self.start_button = ttk.Button(buttons, text='开始录音并识曲', command=self.start)
        self.start_button.pack(side='left')
        self.stop_button = ttk.Button(buttons, text='停止录音，不识别', command=self.stop.set, state='disabled')
        self.stop_button.pack(side='left', padx=8)
        self.retry_button = ttk.Button(buttons, text='重新识别这段录音', command=self.retry, state='disabled')
        self.retry_button.pack(side='left')
        self.import_button = ttk.Button(buttons, text='导入 WAV 对照', command=self.import_wav)
        self.import_button.pack(side='right')
        ttk.Progressbar(frame, variable=self.progress, maximum=100).pack(fill='x', pady=(18, 5))
        ttk.Label(frame, textvariable=self.level).pack(anchor='w')
        ttk.Label(frame, textvariable=self.status, font=('Microsoft YaHei UI', 12, 'bold'),
                  foreground='#0a7c75', wraplength=980).pack(anchor='w', pady=16)
        card = ttk.LabelFrame(frame, text='本次识别', padding=18)
        card.pack(fill='both', expand=True)
        ttk.Label(card, textvariable=self.song, font=('Microsoft YaHei UI', 25, 'bold'), wraplength=940).pack(anchor='w', pady=(4, 8))
        ttk.Label(card, textvariable=self.artist, font=('Microsoft YaHei UI', 17), wraplength=940).pack(anchor='w', pady=(0, 14))
        self.fields = ttk.Treeview(card, columns=('field','value'), show='headings', height=7)
        self.fields.heading('field', text='项目')
        self.fields.heading('value', text='记录')
        self.fields.column('field', width=150, minwidth=100)
        self.fields.column('value', width=740, minwidth=300)
        self.fields.pack(fill='both', expand=True)
        ttk.Label(frame, textvariable=self.detail, wraplength=980, foreground='#536d82').pack(anchor='w', pady=12)
        bottom = ttk.Frame(frame)
        bottom.pack(fill='x')
        self.raw_button = ttk.Button(bottom, text='试听原录音', command=lambda: self.play('wav'))
        self.raw_button.pack(side='left')
        self.clip_button = ttk.Button(bottom, text='试听识别片段', command=lambda: self.play('clip'))
        self.clip_button.pack(side='left', padx=8)
        self.response_button = ttk.Button(bottom, text='查看服务原始返回', command=self.open_response)
        self.response_button.pack(side='left')
        ttk.Button(bottom, text='打开记录目录', command=lambda: os.startfile(str(backend.root))).pack(side='right')
        ttk.Label(frame, textvariable=self.validation, foreground='#173b5c', wraplength=980).pack(anchor='w', pady=(16, 0))
        self.refresh_devices()
        self.restore()
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.after(80, self.drain)

    def refresh_devices(self):
        from pc_mic_capture import input_devices
        try:
            self.devices = input_devices()
            self.devices_box.configure(values=[d['label'] for d in self.devices])
            if self.device.get() not in [d['label'] for d in self.devices] and self.devices:
                self.device.set(next((d['label'] for d in self.devices if not d['loopback_name']
                                      and 'noise' not in d['name'].casefold()), self.devices[0]['label']))
            if not self.devices:
                self.status.set('没有检测到麦克风，请连接后刷新。')
        except Exception as error:
            self.status.set(str(error))

    def restore(self):
        latest = self.backend.root/'latest.json'
        if latest.exists():
            try:
                record = json.loads(latest.read_text(encoding='utf8'))
                if 'result' in record:
                    self.show(record)
            except (OSError, ValueError, KeyError):
                self.status.set('上一条记录未能恢复，可以开始新的录音。')
        check = self.backend.root/'validation_result.json'
        if check.exists():
            result = json.loads(check.read_text(encoding='utf8'))
            if result.get('status') in ('passed','failed'):
                self.validation.set(f'已保存录音验证：ShazamIO {result["correct"]}/{result["total"]} 正确，'
                                    f'{result["wrong"]} 次误认；使用与 SongRec 相同的六份电脑录音片段。')

    def background(self, work):
        if self.busy:
            return
        self.busy = True
        for button in (self.start_button, self.refresh_button, self.retry_button, self.import_button,
                       self.raw_button, self.clip_button, self.response_button):
            button.configure(state='disabled')
        self.devices_box.configure(state='disabled')
        self.duration_box.configure(state='disabled')
        def run():
            try:
                work()
            except Exception as error:
                write_json(self.backend.root/'last_error.json', {'type': type(error).__name__, 'message': str(error)})
                self.queue.put(('error', {'message': str(error)}))
            finally:
                self.queue.put(('idle', {}))
        threading.Thread(target=run, daemon=True).start()

    def start(self):
        from pc_mic_capture import record
        device = next((d for d in self.devices if d['label']==self.device.get()), None)
        if device is None or self.busy:
            return
        winsound.PlaySound(None, 0)
        self.stop.clear()
        self.progress.set(0)
        seconds = int(self.seconds.get())
        self.status.set('正在录制电脑麦克风，请保持音乐外放……')
        self.song.set('正在听音乐')
        self.artist.set('录满后开始识别')
        self.fields.delete(*self.fields.get_children())
        self.stop_button.configure(state='normal')
        def work():
            directory, job = self.backend.new_trial('computer_microphone')
            def progress(frames, total, level):
                self.queue.put(('progress', {'frames': frames, 'total': total, 'level': level, 'seconds': seconds}))
            meta = record(device['id'], seconds, directory/'original.wav', stop=self.stop, progress=progress)
            meta['device'] = device
            self.queue.put(('stage', {'message': '录音完成，正在识别……' if meta['complete'] else '录音已停止，未请求识别。'}))
            result = self.backend.recognize(directory, job, directory/'original.wav', meta)
            self.queue.put(('result', {'record': result}))
        self.background(work)

    def import_wav(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(parent=self.root, title='12至60秒、8/16kHz单声道PCM16 WAV',
                                          filetypes=[('PCM WAV','*.wav')])
        if path:
            winsound.PlaySound(None, 0)
            self.status.set('正在识别导入的 WAV 文件……')
            self.background(lambda: self.queue.put(('result', {'record': self.backend.import_wav(path)})))

    def retry(self):
        if self.busy or not self.last or self.last.get('result',{}).get('status')=='cancelled':
            return
        path = self.last.get('wav')
        if not path or not Path(path).is_file():
            self.status.set('原录音不存在，请重新录音。')
            return
        winsound.PlaySound(None, 0)
        self.status.set('正在重新识别已保存的录音……')
        self.background(lambda: self.queue.put(('result', {'record': self.backend.import_wav(path, source='user_requested_retry')})))

    def show(self, record):
        self.last = record
        result = record['result']
        if result.get('matched'):
            self.song.set(result['title'])
            self.artist.set(result['artist'])
            self.status.set('识别完成，已保存原录音、片段和服务返回。')
        else:
            self.song.set('本次未识出歌曲')
            self.artist.set(result.get('message','识别未完成'))
            self.status.set(result.get('message','识别未完成'))
        sources = {'computer_microphone':'本次电脑麦克风录音', 'imported_WAV_reference':'导入的 WAV 文件',
                   'replay_of_real_PC_microphone':'已保存电脑录音的验证回放', 'user_requested_retry':'已保存录音的手动重试'}
        prep = record.get('preparation', {})
        fields = [('识别来源','Shazam / ShazamIO '+SHAZAMIO_VERSION),
                  ('声音来源', sources.get(record['source'], record['source'])),
                  ('服务状态',result.get('status','—')), ('曲目 ID',result.get('track_key','—')),
                  ('原录音长度',str(prep.get('source_duration_s',record.get('metadata',{}).get('duration_s','—') if record.get('metadata') else '—'))+' 秒'),
                  ('识别片段',f'从 {prep["clip_start_s"]:g} 秒起，连续 12 秒' if prep else '未生成'),
                  ('本次识别用时',f'{result["elapsed_s"]:.2f} 秒' if 'elapsed_s' in result else '未请求识别')]
        self.fields.delete(*self.fields.get_children())
        for key, value in fields:
            self.fields.insert('', 'end', values=(key,value))
        self.detail.set('原录音和实际识别片段均已保留；此处展示服务实际返回的歌名与歌手。')
        if not self.busy:
            self.retry_button.configure(state='disabled' if result.get('status')=='cancelled' else 'normal')

    def play(self, key):
        if not self.busy and self.last:
            path = self.last.get(key)
            if path and Path(path).is_file():
                winsound.PlaySound(str(path), winsound.SND_FILENAME|winsound.SND_ASYNC)

    def open_response(self):
        if self.last and not self.busy:
            path = Path(self.last['directory'])/'service_response.json'
            if path.exists():
                os.startfile(str(path))
            else:
                self.status.set('本次没有有效服务返回，诊断信息已保存在记录目录。')

    def drain(self):
        while True:
            try:
                kind, value = self.queue.get_nowait()
            except queue.Empty:
                break
            if kind=='progress':
                self.progress.set(value['frames']/value['total']*100)
                self.level.set(f'已录 {value["frames"]/16000:.1f}/{value["seconds"]} 秒；'
                               f'RMS {value["level"]["rms_dbfs"]:.1f} dBFS；峰值 {value["level"]["peak_dbfs"]:.1f} dBFS')
            elif kind=='stage':
                self.stop_button.configure(state='disabled')
                self.status.set(value['message'])
            elif kind=='result':
                self.show(value['record'])
            elif kind=='error':
                self.status.set(value['message'])
                self.song.set('本次未完成识别')
                self.artist.set('')
                self.fields.delete(*self.fields.get_children())
                self.last = None
            elif kind=='idle':
                self.busy = False
                for button in (self.start_button, self.refresh_button, self.import_button,
                               self.raw_button, self.clip_button, self.response_button):
                    button.configure(state='normal')
                self.retry_button.configure(state='normal' if self.last and self.last.get('result',{}).get('status')!='cancelled' else 'disabled')
                self.stop_button.configure(state='disabled')
                self.devices_box.configure(state='readonly')
                self.duration_box.configure(state='readonly')
        if self.closing and not self.busy:
            self.root.destroy()
            return
        self.root.after(80,self.drain)

    def close(self):
        winsound.PlaySound(None,0)
        if self.busy:
            self.closing = True
            self.stop.set()
            self.cancel_wait.set()
            self.status.set('正在停止录音或等待当前识别结束，保存后关闭。')
        else:
            self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--internal-shazam', nargs=2, type=Path, metavar=('CLIP','OUTPUT'))
    parser.add_argument('--self-check', action='store_true')
    parser.add_argument('--probe-seconds', type=float)
    parser.add_argument('--device', type=int, default=0)
    parser.add_argument('--recognize-wav', type=Path)
    parser.add_argument('--replay-session', type=Path)
    args = parser.parse_args()
    if args.internal_shazam:
        worker(*args.internal_shazam)
        return
    folder = (args.data_dir or data_root()).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    if args.self_check:
        import shazamio, shazamio_core
        from pc_mic_capture import input_devices
        stack = versions()
        assert stack['shazamio']==SHAZAMIO_VERSION and stack['shazamio-core']==CORE_VERSION
        result = {'app_version': VERSION, 'frozen': bool(getattr(sys,'frozen',False)), 'versions': stack,
                  'devices': input_devices(), 'data_directory': str(folder),
                  'forbidden_imports': [name for name in ('serial','music_board','music_online','music_credentials','monitor_gui') if name in sys.modules]}
        assert not result['forbidden_imports']
        write_json(folder/'self_check.json', result)
        print(json.dumps(result,ensure_ascii=False))
        return
    if args.probe_seconds:
        from pc_mic_capture import record
        result = record(args.device,args.probe_seconds,folder/'capture_probe.wav')
        write_json(folder/'capture_probe.json',result)
        print(json.dumps(result,ensure_ascii=False))
        return
    if args.replay_session:
        report = replay_session(Backend(folder),args.replay_session)
        print(json.dumps({'report': str(folder/'validation_result.json'), 'status':report['status'],
                          'correct':report['correct'],'total':6,'wrong':report['wrong']},ensure_ascii=False))
        return
    if args.recognize_wav:
        record = Backend(folder).import_wav(args.recognize_wav)
        print(json.dumps(record['result'],ensure_ascii=False))
        return
    import msvcrt
    lock = (folder/'application.lock').open('a+b')
    if lock.seek(0,2)==0:
        lock.write(b'0')
        lock.flush()
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:
        from tkinter import messagebox
        messagebox.showinfo('测试程序已运行','请切换到已打开的 ShazamIO 电脑识曲窗口。')
        lock.close()
        return
    try:
        App(Backend(folder)).root.mainloop()
    finally:
        lock.close()


if __name__=='__main__':
    main()
