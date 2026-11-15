"""Chinese music workspace inside the existing monitor application."""
import datetime as dt,json,time,uuid,wave,winsound
from pathlib import Path
import tkinter as tk
from tkinter import filedialog,messagebox,simpledialog
import ttkbootstrap as ttk
from audit import ROOT,now,write_json,sha256,TZ
from music_store import MusicStore
from music_worker import MusicEngine
from music_library import metadata
from panel_protocol import Phase

NAVY='#173b5c';TEAL='#168c82';BLUE='#2868aa';BG='#f3f6fa';MUTED='#60758a'
class _WrapRow(ttk.Frame):
    """Wrap a compact action row at the available page width."""
    def __init__(self,parent):
        super().__init__(parent)
        self.bind('<Configure>',self._queue)
        self._pending=None
        self.bind('<Destroy>',self._cancel,add='+')
    def _queue(self,event=None):
        if self._pending is None:self._pending=self.after_idle(self._layout)
    def _cancel(self,event=None):
        if event.widget is self and self._pending is not None:
            self.after_cancel(self._pending);self._pending=None
    def _layout(self):
        self._pending=None
        width=max(1,self.winfo_width());x=y=0;row_height=0
        for child in self.winfo_children():
            w=child.winfo_reqwidth();h=child.winfo_reqheight()
            if x and x+w>width:y+=row_height+6;x=0;row_height=0
            child.place(x=x,y=y,width=w,height=h)
            x+=w+8;row_height=max(row_height,h)
        self.configure(height=y+row_height)

class _ScrollablePage(ttk.Frame):
    """Keep audio actions reachable at the main window's minimum size."""
    def __init__(self,parent):
        super().__init__(parent)
        self.canvas=tk.Canvas(self,highlightthickness=0)
        scroll=ttk.Scrollbar(self,orient='vertical',command=self.canvas.yview)
        scroll.pack(side='right',fill='y');self.canvas.pack(side='left',fill='both',expand=True)
        self.canvas.configure(yscrollcommand=scroll.set)
        self.body=ttk.Frame(self.canvas,padding=(16,12))
        self.item=self.canvas.create_window((0,0),window=self.body,anchor='nw')
        self.canvas.bind('<Configure>',self._fit)
        self.body.bind('<Configure>',self._region)
        self.bind('<<ThemeChanged>>',self._theme,add='+')
        self.winfo_toplevel().bind('<MouseWheel>',self._wheel,add='+')
        self._theme()
    def _fit(self,event=None):
        self.canvas.itemconfigure(self.item,width=max(1,self.canvas.winfo_width()))
        self._region()
    def _region(self,event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))
    def _theme(self,event=None):
        self.canvas.configure(background=ttk.Style().lookup('TFrame','background'))
    def _wheel(self,event):
        if not self.winfo_ismapped() or not str(event.widget).startswith(str(self)):return
        if event.widget.winfo_class() in ('Treeview','TCombobox'):return
        if self.body.winfo_reqheight()>self.canvas.winfo_height():self.canvas.yview_scroll(-int(event.delta/120),'units')

def _table(parent,columns):
    holder=ttk.Frame(parent);holder.pack(fill='both',expand=True,pady=10)
    holder.columnconfigure(0,weight=1);holder.rowconfigure(0,weight=1)
    tree=ttk.Treeview(holder,columns=columns,show='headings',height=10)
    vertical=ttk.Scrollbar(holder,orient='vertical',command=tree.yview)
    horizontal=ttk.Scrollbar(holder,orient='horizontal',command=tree.xview)
    tree.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
    tree.grid(row=0,column=0,sticky='nsew');vertical.grid(row=0,column=1,sticky='ns');horizontal.grid(row=1,column=0,sticky='ew')
    return tree

class MusicPanel:
    def __init__(self,dashboard):
        self.app=dashboard
        from music_seed import install_seed
        install_seed();self.store=MusicStore()
        self.dialog_owner=dashboard.root
        self.win=ttk.Frame(dashboard.audio_page);self.win.pack(fill='both',expand=True)
        self.engine=MusicEngine(lambda m:self.app.messages.put({'kind':'music_worker','payload':m}))
        self.enabled=False;self.busy=False;self.importing=False;self.job=None;self.result=None;self.wav=None;self.last_status=None;self.pending={};self.game_ready=None
        self.cancelled_jobs=set();self.cancel_request=None;self.active_retry_id=None;self.worker_unavailable=False
        profile=self.store.setting('match_profile',{'seconds':10})
        self.policy=tk.StringVar(value={'auto':'自动','offline':'仅离线'}.get(self.store.setting('policy','auto'),'自动'))
        self.seconds=tk.StringVar(value=str(20 if self.policy.get()=='自动' else profile.get('seconds',10)));self.wake=tk.BooleanVar(value=True)
        self.status=tk.StringVar(value='先进入识曲，播放音乐后连续敲桌三下开始录音。');self.source=tk.StringVar(value='本次来源：—')
        self.title=tk.StringVar(value='让开发板听一首歌');self.artist=tk.StringVar(value='电脑不使用自己的麦克风，声音来自板载麦克风。')
        self.details=tk.StringVar(value='完整录音校验通过后，才会开始匹配。');self.stage=tk.StringVar(value='等待开始');self.policy_text=tk.StringVar(value='当前设置：'+self.policy.get())
        self.make_widgets();self.refresh_library();self.refresh_history();self.save_state()
        self.app.theme_manager.register(self.win)
        self.app.theme_manager.listeners.append(self._theme_wave)
    def make_widgets(self):
        header=ttk.Frame(self.win,padding=(20,14,20,8));header.pack(fill='x')
        ttk.Label(header,text='听歌识曲',font=('Microsoft YaHei UI',20,'bold')).pack(side='left')
        ttk.Label(header,text='板载麦克风 · Shazam 在线优先',style='Muted.TLabel').pack(side='right')
        book=ttk.Notebook(self.win);self.book=book
        pages=[_ScrollablePage(book) for _ in range(4)]
        listen,library,history,game=[page.body for page in pages]
        for page,title in zip(pages,('录音识曲','本地歌单','历史与收藏','人机抢歌名')):book.add(page,text='  '+title+'  ')
        self._wrapped_labels=[]
        def wrapped(parent,**kw):
            label=ttk.Label(parent,wraplength=720,justify='left',**kw);self._wrapped_labels.append(label);return label
        row=_WrapRow(listen);row.pack(fill='x')
        ttk.Label(row,text='识别方式').pack(side='left');choice=ttk.Combobox(row,textvariable=self.policy,values=('自动','仅离线'),state='readonly',width=10);choice.pack(side='left',padx=8);choice.bind('<<ComboboxSelected>>',self.policy_changed)
        ttk.Label(row,text='录音长度').pack(side='left',padx=(14,3));duration=ttk.Combobox(row,textvariable=self.seconds,values=('8','10','20'),state='readonly',width=5);duration.pack(side='left');duration.bind('<<ComboboxSelected>>',self.settings_changed);ttk.Label(row,text='秒').pack(side='left',padx=4)
        ttk.Label(row,text='就绪后连续敲桌三下才录音').pack(side='left',padx=18)
        wrapped(listen,text='自动：优先使用 Shazam 在线识曲，在线不可用或未命中时再查本地歌单；仅离线：全程在本机识别。',style='Muted.TLabel').pack(anchor='w',pady=(10,3))
        wrapped(listen,text='模式切换从下一次识曲生效；当前任务不会因此重复上传。切换页面后，录音和识别继续进行。',style='Muted.TLabel').pack(anchor='w')
        buttons=_WrapRow(self.win);buttons.pack(fill='x',padx=20,pady=(6,8))
        ttk.Button(buttons,text='进入识曲（敲三下）',command=self.record).pack(side='left',padx=(0,8))
        self.cancel_button=ttk.Button(buttons,text='中止本次识曲',command=self.cancel,state='disabled');self.cancel_button.pack(side='left',padx=4)
        ttk.Button(buttons,text='退出识曲，恢复监测',command=self.hide).pack(side='left',padx=4)
        card=ttk.Frame(listen,style='Card.TFrame',padding=20);card.pack(fill='both',expand=True,pady=6)
        wrapped(card,textvariable=self.title,style='Card.TLabel',font=('Microsoft YaHei UI',22,'bold')).pack(anchor='w',pady=(0,8))
        wrapped(card,textvariable=self.artist,style='Card.TLabel',font=('Microsoft YaHei UI',13)).pack(anchor='w',pady=(0,8))
        wrapped(card,textvariable=self.source,style='Card.TLabel').pack(anchor='w',pady=3)
        wrapped(card,textvariable=self.policy_text,style='Card.TLabel').pack(anchor='w',pady=3)
        wrapped(card,textvariable=self.details,style='Card.TLabel').pack(anchor='w',pady=8)
        self.wave=tk.Canvas(card,height=75,highlightthickness=0);self.wave.pack(fill='x',pady=(5,0))
        wrapped(listen,textvariable=self.stage,font=('Microsoft YaHei UI',11,'bold')).pack(anchor='w',pady=(12,5))
        self.progress=ttk.Progressbar(listen,maximum=100,mode='determinate');self.progress.pack(fill='x')
        tail=_WrapRow(listen);tail.pack(fill='x',pady=12)
        ttk.Button(tail,text='播放本次录音',command=self.play).pack(side='left',padx=4);ttk.Button(tail,text='收藏当前歌曲（中键）',command=self.favourite).pack(side='left',padx=4)
        ttk.Button(tail,text='手动重试本次录音',command=self.retry).pack(side='left',padx=4);ttk.Button(tail,text='在线服务说明',command=self.online_help).pack(side='left',padx=4)
        self.verify_button=ttk.Button(tail,text='检查识曲组件',command=self.verify);self.verify_button.pack(side='left',padx=4)
        status=ttk.Frame(self.win,padding=(20,8));status.pack(side='bottom',fill='x')
        wrapped(status,textvariable=self.status,style='Muted.TLabel').pack(fill='x')
        book.pack(fill='both',expand=True,padx=16,pady=(4,8))
        # Existing local-library operations and SQL-backed history are retained.
        wrapped(library,text='导入完整音乐文件，录音外放到任意有音乐内容的位置都可尝试匹配。',font=('Microsoft YaHei UI',12,'bold')).pack(anchor='w',pady=10)
        bar=_WrapRow(library);bar.pack(fill='x',pady=10)
        ttk.Button(bar,text='导入本地歌单',command=self.import_files).pack(side='left',padx=4);ttk.Button(bar,text='加载演示歌单',command=self.import_demo).pack(side='left',padx=4)
        ttk.Button(bar,text='刷新',command=self.refresh_library).pack(side='left',padx=4);ttk.Button(bar,text='查看音乐署名',command=self.credits).pack(side='left',padx=4)
        self.library_tree=_table(library,('title','artist','duration'))
        for key,title,width in [('title','歌名',340),('artist','歌手 / 作者',220),('duration','全曲时长 / 秒',130)]:self.library_tree.heading(key,text=title);self.library_tree.column(key,width=width,minwidth=70)
        wrapped(library,text='同一内容重复导入会复用原记录。库外验收曲目请保留在手机上，不要导入。',style='Muted.TLabel').pack(anchor='w',pady=10)
        filters=_WrapRow(history);filters.pack(fill='x')
        self.query=tk.StringVar();self.history_source=tk.StringVar(value='全部来源');self.only_favourites=tk.BooleanVar(value=False)
        self.start_date=tk.StringVar();self.end_date=tk.StringVar()
        ttk.Label(filters,text='歌曲或歌手').pack(side='left');ttk.Entry(filters,textvariable=self.query,width=22).pack(side='left',padx=5)
        ttk.Combobox(filters,textvariable=self.history_source,values=('全部来源','本地歌单','Shazam','AudioTag（历史）'),state='readonly',width=16).pack(side='left',padx=5)
        ttk.Checkbutton(filters,text='只看收藏',variable=self.only_favourites).pack(side='left',padx=8);ttk.Button(filters,text='查询',command=self.refresh_history).pack(side='left',padx=5)
        times=_WrapRow(history);times.pack(fill='x',pady=9)
        ttk.Label(times,text='时间从').pack(side='left');ttk.Entry(times,textvariable=self.start_date,width=24).pack(side='left',padx=5)
        ttk.Label(times,text='至').pack(side='left');ttk.Entry(times,textvariable=self.end_date,width=24).pack(side='left',padx=5)
        ttk.Button(times,text='昨晚重复听了哪首',command=self.last_night).pack(side='left',padx=8);ttk.Button(times,text='清空时间',command=self.clear_dates).pack(side='left')
        self.history_tree=_table(history,('time','title','artist','source','favourite'))
        for key,title,width in [('time','真实识别时间',210),('title','歌名 / 结果',230),('artist','歌手 / 作者',170),('source','来源',100),('favourite','收藏',70)]:self.history_tree.heading(key,text=title);self.history_tree.column(key,width=width,minwidth=60)
        self.stats=tk.StringVar();wrapped(history,textvariable=self.stats).pack(fill='x',pady=10)
        wrapped(history,text='这里的查询和收藏完全在本机运行。未配置本地模型时，保留普通筛选和时间查询。',style='Muted.TLabel').pack(anchor='w')
        wrapped(game,text='连续敲桌三下开始，再拍桌锁定你的抢答时间。',font=('Microsoft YaHei UI',16,'bold')).pack(anchor='w',pady=18)
        wrapped(game,text='使用本地歌单；开局计时包括机器的录音、传输和实际匹配。',style='Muted.TLabel').pack(anchor='w')
        self.game_status=tk.StringVar(value='请先让出题者从歌单中随机外放一首歌。');self.game_answer=tk.StringVar();self.game_text=tk.StringVar(value='答案尚未揭晓')
        ttk.Button(game,text='进入抢答（敲三下）',command=self.start_game).pack(anchor='w',pady=20)
        wrapped(game,textvariable=self.game_status,font=('Microsoft YaHei UI',13)).pack(anchor='w',pady=14)
        ttk.Label(game,text='拍桌后填写你想到的歌名：').pack(anchor='w');ttk.Entry(game,textvariable=self.game_answer,width=65).pack(fill='x',pady=10)
        ttk.Button(game,text='锁定答案并揭晓',command=self.reveal).pack(anchor='w',pady=16)
        wrapped(game,textvariable=self.game_text,font=('Microsoft YaHei UI',16,'bold')).pack(anchor='w',pady=15)
        wrapped(game,text='揭晓后由出题者核对双方答案；时间接近时结合记录中的误差判断。',style='Muted.TLabel').pack(anchor='w',pady=10)
        self.win.bind('<Configure>',self._fit_labels,add='+')
        self.win.bind('<<ThemeChanged>>',self._theme_wave,add='+')
        self._theme_wave()

    def _fit_labels(self,event=None):
        width=max(240,self.win.winfo_width()-104)
        if width==getattr(self,'_wrap_width',None):return
        self._wrap_width=width
        for label in self._wrapped_labels:label.configure(wraplength=width)

    def _theme_wave(self,event=None):
        style=ttk.Style()
        self.wave.configure(background=style.lookup('Card.TFrame','background') or style.lookup('TFrame','background'))
        self.wave.itemconfigure('audio-wave',fill=self.app.theme_manager.palette['blue'])

    def show(self):
        self.app.show_page('audio');self.refresh_history()

    def hide(self):
        if self.enabled:self.board('music_disable')
        self.app.show_page('monitor')

    def board(self,action,**values):self.app.action(action,**values)
    def mode(self):return 'offline' if self.policy.get()=='仅离线' else 'auto'
    def policy_changed(self,event=None):
        self.store.set_setting('policy',self.mode());self.policy_text.set('下次采用：'+self.policy.get());self.board('music_policy',policy=self.mode())
        self.verify_button.configure(state='disabled' if self.mode()=='offline' else 'normal')
        if self.mode()=='auto' and int(self.seconds.get())<20:self.seconds.set('20');self.settings_changed()
    def settings_changed(self,event=None):
        if self.mode()=='auto' and int(self.seconds.get())!=20:
            self.seconds.set('20');self.status.set('在线录音使用完整20秒；请让手机持续外放到录音结束。')
        self.board('music_settings',seconds=int(self.seconds.get()),wake=True)
    def enable(self,game=False):
        if self.worker_unavailable:self.status.set('识曲进程未能恢复，请重启软件；普通监测仍可使用。');return False
        if self.importing:self.status.set('正在更新歌单，请等待建库完成。');return False
        if self.busy:self.status.set('请等待本次识曲结束，或点“中止本次识曲”。');return False
        tap=self.store.setting('tap_profile',{'high':80,'low':32})
        self.board('music_enable',seconds=int(self.seconds.get()),wake=True,game=game,policy='offline' if game else self.mode(),verify_repeat=getattr(self,'verification_reads',False),**tap)
        return True
    def record(self):
        if self.busy:self.status.set('本次任务尚未结束，不会重复启动。');return
        if self.enable(game=False):self.status.set('正在进入识曲；等提示就绪后，播放音乐并连续敲桌三下开始录音。')
    def sync_cancel_button(self):
        request=self.cancel_request
        allowed=self.busy and (request is None or request.get('board_failed',False))
        self.cancel_button.configure(state='normal' if allowed else 'disabled')
    def cancel(self):
        request=self.cancel_request
        if request is not None:
            if request.get('board_failed'):
                request['board_failed']=False;self.status.set('正在重试中止，请稍候…')
                self.board('music_cancel',job_id=request['id']);self.sync_cancel_button();self.save_state()
            return
        if not self.busy:return
        identifier=self.active_retry_id or (self.job or {}).get('id')
        if not identifier:self.status.set('尚未取得当前任务编号，请稍后重试中止。');return
        self.cancelled_jobs.add(identifier)
        self.cancel_request={'id':identifier,'board_ack':False,'worker_ack':False,'worker_ok':True,'board_failed':False}
        self.result=None;self.game_ready=None
        self.status.set('正在中止本次识曲…');self.stage.set('正在中止')
        if self.job and self.job.get('game'):self.game_text.set('正在中止本局…')
        self.sync_cancel_button();self.save_state()
        self.board('music_cancel',job_id=identifier)
        self.engine.cancel(identifier)
    def finish_cancel(self):
        request=self.cancel_request
        if not request or not request['board_ack'] or not request['worker_ack']:return
        identifier=request['id']
        applies=self.active_retry_id==identifier or (self.job or {}).get('id')==identifier or self.job is None
        self.pending.pop(identifier,None)
        if not request['worker_ok']:
            self.worker_unavailable=True;self.board('music_disable')
        else:self.board('music_cancel_ready',job_id=identifier)
        if applies:
            game=bool(self.job and self.job.get('game'))
            self.busy=False;self.job=None;self.active_retry_id=None;self.result=None;self.game_ready=None
            self.enabled=request.get('enabled',self.enabled);self.progress['value']=0
            self.title.set('本次识曲已中止' if request['worker_ok'] else '中止状态需要确认');self.artist.set('完整录音已保留，可播放或手动重试。' if self.wav else '未产生完整录音；已有文件保留。')
            self.source.set('本次来源：已中止')
            if game:self.game_text.set('本局已中止，未揭晓答案。');self.game_status.set('本局已中止。')
            if request['worker_ok']:
                self.stage.set('已中止');self.status.set('本次已中止；连续敲桌三下可重新录音。' if self.enabled else '本次已中止；再次进入后，连续敲桌三下才会录音。')
            else:
                self.stage.set('中止未完全确认');self.status.set(request.get('worker_message') or '识曲进程未能恢复，请重启软件；普通监测仍可使用。')
            self.refresh_history()
        self.cancel_request=None;self.sync_cancel_button();self.save_state()
    def play(self):
        if self.wav and Path(self.wav).exists():
            from music_library import normalize_query
            playback=Path(self.wav).with_name('listening_copy.wav');processing=normalize_query(self.wav,playback)
            self.app.run.event('music_recording_played',**processing)
            winsound.PlaySound(str(playback),winsound.SND_FILENAME|winsound.SND_ASYNC)
        else:self.status.set('尚无完整录音；请先录音并等待校验通过。')
    def favourite(self):
        if self.result and self.result.get('matched') and not (self.job and self.job.get('game') and not self.game_ready):
            song=self.result.get('song_id') or self.store.put_song(self.result['title'],self.result['artist']);self.store.favourite(song);self.status.set('已收藏；同一首只保留一份。');self.refresh_history();self.project_panel(Phase.FAVORITE,identifier=self.result.get('job_id'))
        else:self.status.set('当前尚无可以收藏的确定结果。')
    def online_help(self):
        messagebox.showinfo('Shazam在线识曲','当前在线服务为ShazamIO，无需API Key。\n自动模式先在线识别，未命中或不可用时仍回退本地歌单。\n请求间隔至少30秒；限流后冷却至少60秒，可稍后手动重试。\n旧AudioTag历史记录保留，新版不再查询旧任务。',parent=self.dialog_owner)
    def verify(self):
        if self.mode()=='offline':self.status.set('仅离线模式无需在线组件检查。');return
        identifier=self.engine.submit('verify',mode='auto');self.pending[identifier]='verify';self.status.set('正在检查ShazamIO识曲组件，本次不发送音频。')
    def import_files(self):
        paths=filedialog.askopenfilenames(parent=self.dialog_owner,title='选择已有的完整音乐文件',filetypes=[('音乐','*.wav *.mp3 *.flac *.m4a *.ogg *.aac *.wma')])
        tracks=[]
        for path in paths:
            labels=metadata(path)
            if not labels['artist']:
                artist=simpledialog.askstring('补充歌手 / 作者',Path(path).name+'\n请输入真实歌手或作者：',parent=self.dialog_owner)
                if not artist:continue
                labels['artist']=artist
            tracks.append({'file':path,**labels})
        if tracks:self.submit_import(tracks)
    def import_demo(self):
        from music_seed import install_seed
        if install_seed():self.refresh_library();self.status.set('五首演示指纹已载入，包含两首Eagles流行歌。');return
        if len(self.store.recordings())>=5:self.status.set('演示歌单已在本机；现有歌单保留。');self.refresh_library();return
        from app_paths import RESOURCE_ROOT
        manifest=ROOT/'music_demo/manifest.json'
        if not manifest.exists():manifest=RESOURCE_ROOT/'music_demo/manifest.json'
        if not manifest.exists():self.status.set('请从交付的听歌识曲示例包导入五首入库歌曲。');return
        data=json.loads(manifest.read_text(encoding='utf8'));base=ROOT if (ROOT/'music_demo').exists() else RESOURCE_ROOT
        tracks=[{'file':str(base/r['file']),'title':r['title'],'artist':r['artist']} for r in data['tracks'] if r['group']=='library']
        self.submit_import(tracks)
    def submit_import(self,tracks):
        if self.busy or self.enabled:self.status.set('请先退出识曲，再导入或更新歌单；监测曲线继续运行。');return
        self.importing=True;identifier=self.engine.submit('import',tracks=tracks);self.pending[identifier]='import';self.status.set('正在为完整音乐建立本地指纹，请稍候…')
    def refresh_library(self):
        self.library_tree.delete(*self.library_tree.get_children())
        for row in self.store.recordings():self.library_tree.insert('', 'end',values=(row['title'],row['artist'],f'{row["duration"]:.1f}'))
    def refresh_history(self):
        filters={'text':self.query.get(),'source':{'本地歌单':'local','Shazam':'shazamio','AudioTag（历史）':'audiotag'}.get(self.history_source.get(),''),
            'start':self.start_date.get(),'end':self.end_date.get(),'favourites':self.only_favourites.get()}
        rows=self.store.history(**filters);self.history_tree.delete(*self.history_tree.get_children())
        for row in rows:self.history_tree.insert('', 'end',values=(row['created_at'],row['title'] or '未匹配',row['artist'] or '—',{'local':'本地歌单','shazamio':'Shazam','audiotag':'AudioTag（历史）'}.get(row['source'],'—'),'★' if row['favourited_at'] else ''))
        groups=self.store.statistics(**filters);self.stats.set('共'+str(len(rows))+'次记录；'+ '　'.join(g['title']+' '+str(g['count'])+'次' for g in groups[:8]))
    def last_night(self):
        today=dt.datetime.now(TZ).date();start=dt.datetime.combine(today-dt.timedelta(days=1),dt.time(18),TZ);end=dt.datetime.combine(today,dt.time(6),TZ)
        self.start_date.set(start.isoformat());self.end_date.set(end.isoformat());self.refresh_history()
        groups=[g for g in self.store.statistics(start=start.isoformat(),end=end.isoformat()) if g['count']>=2]
        self.stats.set('昨晚18:00至今天06:00：'+ ('；'.join(g['title']+' '+str(g['count'])+'次，时间 '+', '.join(g['times']) for g in groups) or '没有重复识别的歌曲。'))
    def clear_dates(self):self.start_date.set('');self.end_date.set('');self.refresh_history()
    def credits(self):
        from app_paths import RESOURCE_ROOT
        path=ROOT/'music_demo/署名与用途.txt'
        if not path.exists():path=RESOURCE_ROOT/'music_demo/署名与用途.txt'
        if path.exists():
            import os
            os.startfile(str(path))
    def retry(self):
        if self.worker_unavailable:self.status.set('识曲进程未能恢复，请重启软件。');return
        if self.busy or not self.wav:self.status.set('请先取得完整录音，并等待当前任务结束。');return
        if self.enabled:self.status.set('请先点“退出识曲，恢复监测”，再手动重试保存的录音。');return
        identifier=uuid.uuid4().hex;self.pending[identifier]='retry';self.busy=True;self.active_retry_id=identifier;self.sync_cancel_button()
        self.engine.submit('match',id=identifier,wav=self.wav,mode=self.mode(),metadata={'manual_retry':True});self.stage.set('③ 正在匹配（手动重试）')
        self.project_panel(Phase.MATCH,identifier=identifier,bind=True)
    def start_game(self):
        if self.busy:self.status.set('请等待当前任务结束。');return
        self.game_answer.set('');self.game_text.set('答案尚未揭晓');self.game_ready=None
        if self.enable(game=True):self.game_status.set('正在进入抢答；等提示就绪后，播放音乐并连续敲桌三下开始。')
    def reveal(self):
        if not self.game_ready:self.game_status.set('机器尚未获得结果，请继续等待。');return
        self.board('music_game_reveal',answer=self.game_answer.get().strip())
    def open_acceptance(self):
        from music_api_wizard import ApiAcceptanceWizard
        if not hasattr(self,'wizard'):self.wizard=ApiAcceptanceWizard(self)
        else:self.wizard.show()
        self.app.theme_manager.register(self.wizard.win)
    def project_panel(self,phase,*,identifier=None,bind=False,value=0):
        worker=getattr(self.app,'worker',None)
        if worker is None or not worker.is_alive():return
        job=self.job or {};identifier=identifier or job.get('id')
        values={'phase':int(phase),'job_id':identifier,'value':int(value)}
        if bind:values['bind_job']={'id':identifier,'record_id':job.get('record_id',0)}
        self.board('panel_update',**values)

    def receive(self,kind,message):
        request=self.cancel_request
        if kind=='music_worker' and message['payload'].get('action')=='cancelled':
            ack=message['payload']
            if request and ack.get('id')==request['id']:
                request['worker_ack']=True;request['worker_ok']=bool(ack.get('ok'));request['worker_message']=ack.get('message');self.finish_cancel()
            return
        if kind=='music_cancelled' and request:
            if message.get('job_id')==request['id']:
                request['board_ack']=True;request['board_failed']=False;request['enabled']=message['enabled']
                owns_current=self.active_retry_id==request['id'] or (self.job or {}).get('id')==request['id'] or self.job is None
                if message.get('saved_wav') and owns_current:self.wav=message['saved_wav']
                self.finish_cancel()
            return
        if kind=='music_cancel_failed':
            if request and message.get('job_id')==request['id']:
                request['board_failed']=True;self.status.set(message['text']);self.stage.set('中止尚未确认')
                self.sync_cancel_button();self.save_state()
            return
        if kind=='music_worker':
            worker_message=message['payload']
            if worker_message.get('id') in self.cancelled_jobs or (request and worker_message.get('action')=='worker_exit'):return
        else:
            message_id=message.get('job_id') or (message.get('job') or {}).get('id') or (message.get('record') or {}).get('round_id')
            if message_id in self.cancelled_jobs:return
        if kind=='music_worker':
            m=message['payload'];action=m.get('action');identifier=m.get('id')
            if action in ('match','match_progress') and identifier!=(self.job or {}).get('id') and self.pending.get(identifier)!='retry':return
            if action=='match_progress':
                text=m['message'];self.stage.set(text)
                waiting=text.startswith('遵守服务请求间隔')
                import re
                wait=re.search(r'约(\d+)秒',text) if waiting else None
                self.project_panel(Phase.HOLD if waiting else Phase.MATCH,identifier=identifier,value=int(wait.group(1))*1000 if wait else 0)
                return
            if not m.get('ok'):
                if action in ('match','worker_exit'):self.project_panel(Phase.ERROR,identifier=identifier,value=1)
                self.status.set(m.get('message','识曲未完成，录音已保留。'));self.importing=False;self.busy=False
                if action=='match' and self.job:
                    self.board('music_result',result={'matched':False,'source':'none','reason':'worker_error','job_id':self.job['id'],
                        'wav_sha256':self.job.get('metadata',{}).get('wav_sha256'),'match_finished_monotonic_ns':time.perf_counter_ns()})
                self.active_retry_id=None;self.sync_cancel_button();self.save_state();return
            result=m['result']
            if action=='import':
                self.importing=False;self.refresh_library();self.status.set('歌单更新完成：'+str(result['total'])+'首；重复文件已跳过。')
            elif action=='verify':
                self.status.set(result.get('message','识曲组件检查未完成'))
            elif action=='match':
                if self.pending.pop(identifier,None)=='retry':self.busy=False;self.active_retry_id=None;self.display_result(result);self.board('music_idle_result',result=result)
                elif self.job and identifier==self.job['id']:
                    self.board('music_result',result=result)
                    if not self.job['game']:self.display_result(result)
            elif action=='calibrate':self.status.set('开发组参数已保存。' if result['accepted'] else '开发组仍未达标，请按向导调整外放位置。')
        elif kind=='music_mode':self.enabled=message['enabled'];self.status.set(message['text'])
        elif kind=='music_policy':self.policy_text.set('下次：'+{'auto':'自动','offline':'仅离线'}[message['policy']]+('；本次：'+{'auto':'自动','offline':'仅离线'}[message['current_policy']] if message.get('current_policy') else ''))
        elif kind=='music_started':
            self.active_retry_id=None
            self.job=message['job'];self.busy=True;self.result=None;self.game_ready=None;self.wav=None;self.title.set('正在听，请保持音乐外放');self.artist.set('板载麦克风正在连续录音');self.source.set('本次来源：等待匹配')
            self.policy_text.set('本次采用：'+{'auto':'自动','offline':'仅离线'}[self.job['policy']]);self.details.set('原始声音采满后冻结，传输校验通过才会识别。');self.progress['value']=0;self.stage.set('① 正在录音');self.wave.delete('all')
        elif kind=='music_status':
            row=message['status'];self.last_status=row
            if row['state'] in (1,2):self.progress['value']=100*row['samples']/max(1,row['target_samples']);self.stage.set(f'① 正在录音  {row["samples"]}/{row["target_samples"]} 点')
            if self.job and self.job['game'] and row['human_tick']:
                self.game_status.set(f'已拍桌锁定：{(row["human_tick"]-row["start_tick"])/1e8:.3f} 秒。现在可以填写答案，机器继续工作。')
        elif kind=='music_progress':self.progress['value']=message['current']/max(1,message['total'])*100;self.stage.set(f'② 正在传输  {message["current"]}/{message["total"]} 点')
        elif kind=='music_exported':
            self.job=message['job'];meta=message['metadata'];self.wav=meta['wav'];self.stage.set('③ 正在匹配');self.progress['value']=100
            self.details.set(f'{meta["duration_s"]:.1f}秒，{meta["sample_rate"]}Hz，{meta["samples"]}点完整WAV；CRC通过，传输 {meta["export_s"]:.2f}秒。');self.draw_wave()
            self.engine.submit('match',id=self.job['id'],wav=self.wav,mode=self.job['policy'],game=self.job['game'],metadata=meta)
        elif kind=='music_game_ready':
            self.game_ready=message;self.game_status.set('机器已经取得结果。拍桌锁时并填写你的答案后，可以揭晓。')
        elif kind=='music_game_revealed':
            r=message['record'];m=r['machine_result'];human='尚未拍桌' if r['human_s'] is None else f'{r["human_s"]:.3f} 秒'
            self.game_text.set('机器：'+(m.get('title','未匹配'))+' / '+m.get('artist','—')+f'\n机器用时 {r["machine_s"]:.3f} 秒；人类用时 '+human+f'\n计时不确定度约 ±{r["clock_uncertainty_s"]:.3f} 秒。请出题者核对答案。')
            self.display_result(m)
        elif kind=='music_complete':self.busy=False;self.result=message['result'];self.stage.set('识曲结束 · 可以继续下一次');self.refresh_history()
        elif kind=='music_cancelled':self.busy=False;self.job=None;self.status.set(message['text'])
        elif kind in ('music_notice','music_favourite'):self.status.set(message['text']);self.refresh_history()
        if hasattr(self,'wizard'):self.wizard.receive(kind,message)
        self.sync_cancel_button()
        self.save_state()
    def display_result(self,result):
        self.result=result
        if result.get('matched'):
            self.title.set(result['title']);self.artist.set(result['artist']);self.source.set('本次来源：'+{'local':'本地歌单','shazamio':'Shazam','audiotag':'AudioTag（历史）'}.get(result['source'],result['source']));self.status.set('识别完成，按板上中键即可收藏。')
        else:
            self.title.set('这次没有确定歌名');self.artist.set(result.get('message','未在本地歌单找到'));self.source.set('本次来源：未匹配')
            self.status.set('完整录音仍保存在本机；未确定的候选不自动收藏，也不计为识别成功。')
        attempt=result.get('online_attempt',result)
        if attempt.get('provider')=='shazamio':
            self.details.set(self.details.get().split('\n在线：')[0]+'\n在线：Shazam'+
                ('；识别用时 '+f'{attempt["online_elapsed_s"]:.2f}'+' 秒' if attempt.get('online_elapsed_s') is not None else ''))
        self.stage.set('识曲完成');self.refresh_history()
    def draw_wave(self):
        import numpy as np
        if not self.wav:return
        with wave.open(self.wav,'rb') as w:a=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').astype(float)
        self.wave.delete('all');width=max(600,self.wave.winfo_width());height=max(60,self.wave.winfo_height())
        a-=np.mean(a);peak=max(1,float(np.max(np.abs(a))));stride=max(1,len(a)//width)
        points=[]
        for i in range(0,len(a),stride):points.extend((i/max(1,len(a)-1)*width,height/2-a[i]/peak*height*.42))
        if len(points)>=4:self.wave.create_line(*points,fill=BLUE,width=1,tags='audio-wave');self._theme_wave()
    def save_state(self):
        write_json(ROOT/'state/music_gui.json',{'time':now(),'enabled':self.enabled,'busy':self.busy,'policy':self.mode(),
            'job_id':self.job['id'] if self.job else None,'record_id':self.job['record_id'] if self.job else None,
            'stage':self.stage.get(),'wav':self.wav,'status':self.last_status,
            'cancel_pending':self.cancel_request,'worker_unavailable':self.worker_unavailable,
            'result':self.result if not (self.job and self.job.get('game') and not self.game_ready) else None})
