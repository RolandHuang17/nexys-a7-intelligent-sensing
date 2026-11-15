"""A single visible guide; the normal flow starts with the board's BTNU."""
import queue,threading,tkinter as tk


class Guidance:
    def __init__(self):
        self.messages=queue.Queue();self.stop=threading.Event();self.finished=threading.Event()
        self.missed=set();self.current_trial=None;self.error=None
        self.root=tk.Tk();self.root.title('声振实验 · 集中采样')
        self.root.geometry('900x480+100+100');self.root.attributes('-topmost',True)
        self.root.configure(bg='#f4f6f8')
        self.title=tk.Label(self.root,text='正在准备实验',font=('Microsoft YaHei',27,'bold'),bg='#f4f6f8')
        self.title.pack(pady=(32,18))
        self.detail=tk.Label(self.root,text='设备准备好后会提示按 BTNU 开始。',font=('Microsoft YaHei',20),
                             wraplength=820,justify='center',bg='#f4f6f8')
        self.detail.pack(expand=True,padx=25)
        self.note=tk.Label(self.root,text='跟随提示即可，数据会自动保存。',font=('Microsoft YaHei',13),bg='#f4f6f8',fg='#465364')
        self.note.pack(pady=10)
        buttons=tk.Frame(self.root,bg='#f4f6f8');buttons.pack(pady=18)
        self.miss=tk.Button(buttons,text='本次漏做了（保留并补采）',font=('Microsoft YaHei',12),command=self.mark_missed,state='disabled')
        self.miss.pack(side='left',padx=20)
        tk.Button(buttons,text='停止采样',font=('Microsoft YaHei',12),command=self.request_stop).pack(side='left',padx=20)
        self.root.protocol('WM_DELETE_WINDOW',self.request_stop)
        self.root.after(16,self.pump)

    def mark_missed(self):
        if self.current_trial:
            self.missed.add(self.current_trial);self.note.configure(text='已记录，原始数据保留，只补这一试次。')

    def request_stop(self):
        self.stop.set();self.title.configure(text='正在停止并保存记录')

    def show(self,title,detail,trial=None,urgent=False):
        ack=threading.Event()
        self.messages.put((title,detail,trial,ack,urgent))
        if urgent:ack.wait(.4)

    def pump(self):
        while not self.messages.empty():
            title,detail,trial,ack,urgent=self.messages.get_nowait()
            self.title.configure(text=title,fg='#126447' if urgent else '#172535');self.detail.configure(text=detail)
            self.current_trial=trial;self.miss.configure(state='normal' if trial else 'disabled')
            self.root.update_idletasks();ack.set()
        if self.finished.is_set():
            self.root.after(10000,self.root.destroy)
        else:self.root.after(16,self.pump)

    def run(self,worker):
        def execute():
            try:worker(self)
            except BaseException as error:
                self.error=error
                self.show('采样已停止，记录已保存',str(error))
            finally:self.finished.set()
        thread=threading.Thread(target=execute,daemon=True);thread.start()
        self.root.mainloop()
        thread.join(timeout=5)
        if self.error:raise self.error
