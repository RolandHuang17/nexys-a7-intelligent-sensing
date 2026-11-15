"""Dashboard composition. Device commands stay on the existing controller."""
import os
import tkinter as tk
import ttkbootstrap as ttk
from audit import ROOT
from app_paths import APP_VERSION
from .theme import ThemedCanvas

def build_dashboard(app,FlowBar,Plot):
    root=app.root
    header=ttk.Frame(root,padding=(20,14));header.pack(fill='x')
    ttk.Label(header,text='NEXYS  /  声振监测',font=('Microsoft YaHei UI',17,'bold')).pack(side='left')
    app.dot=tk.Label(header,text='● 未连接',font=('Microsoft YaHei UI',10),bg='#edf2f7',fg='#e1b56e')
    app.dot.pack(side='left',padx=24)
    app.music_progress=tk.StringVar(value='')
    ttk.Label(header,textvariable=app.music_progress,style='Muted.TLabel').pack(side='left',padx=8)
    app.theme_choice=tk.StringVar(value=app.theme_manager.choice)
    themes=ttk.Combobox(header,textvariable=app.theme_choice,values=('跟随系统','浅色','深色'),width=9,state='readonly')
    themes.pack(side='right');themes.bind('<<ComboboxSelected>>',lambda e:app.theme_manager.set(app.theme_choice.get()))
    ttk.Label(header,text='主题',style='Muted.TLabel').pack(side='right',padx=8)
    device=FlowBar(root,padding=(20,0,20,10));device.pack(fill='x')
    ttk.Label(device,text='设备').pack(side='left',padx=(0,8))
    app.device_box=ttk.Combobox(device,textvariable=app.device_label,state='readonly',width=29)
    app.device_box.pack(side='left');app.device_box.bind('<<ComboboxSelected>>',app.choose_device)
    for text,command in [('刷新',app.refresh_devices),('连接 / 重连',app.connect),('初始化此板',app.download),('驱动准备',app.open_driver_setup)]:
        ttk.Button(device,text=text,command=command).pack(side='left',padx=3)
    ttk.Checkbutton(device,text='确认板型为 Nexys A7-100T',variable=app.board_confirmed).pack(side='left',padx=8)
    footer=ttk.Frame(root,padding=(20,8));footer.pack(side='bottom',fill='x')
    app.status_label=ttk.Label(footer,textvariable=app.status,style='Muted.TLabel',wraplength=1200);app.status_label.pack(anchor='w')
    app.notice_label=ttk.Label(footer,textvariable=app.notice,style='Muted.TLabel',wraplength=1200);app.notice_label.pack(anchor='w',pady=(3,0))
    footer.bind('<Configure>',lambda e:[w.configure(wraplength=max(400,e.width-40)) for w in (app.status_label,app.notice_label)])
    shell=ttk.Frame(root);shell.pack(fill='both',expand=True)
    sidebar=ttk.Frame(shell,width=158,padding=(12,16));sidebar.pack(side='left',fill='y');sidebar.pack_propagate(False)
    ttk.Label(sidebar,text='工作空间',style='Muted.TLabel').pack(anchor='w',padx=8,pady=(0,14))
    app.nav_buttons={}
    for key,title in [('monitor','实时监测'),('events','事件记录'),('audio','听歌识曲'),('game','体感游戏')]:
        button=ttk.Button(sidebar,text=title,style='Nav.TButton',command=lambda k=key:app.show_page(k))
        button.pack(fill='x',pady=4);app.nav_buttons[key]=button
    ttk.Label(sidebar,text='NEXYS A7\nv'+APP_VERSION,style='Muted.TLabel',justify='left').pack(side='bottom',anchor='w',padx=8,pady=4)
    body=ttk.Frame(shell,padding=(8,10,20,0));body.pack(side='left',fill='both',expand=True)
    body.rowconfigure(0,weight=1);body.columnconfigure(0,weight=1)
    app.pages={key:ttk.Frame(body) for key in ('monitor','events','audio','game')}
    for page in app.pages.values():page.grid(row=0,column=0,sticky='nsew')
    app.audio_page=app.pages['audio'];monitor_host=app.pages['monitor']
    viewport=ThemedCanvas(monitor_host,bg='#edf2f7',highlightthickness=0)
    scrollbar=ttk.Scrollbar(monitor_host,orient='vertical',command=viewport.yview)
    viewport.configure(yscrollcommand=scrollbar.set);scrollbar.pack(side='right',fill='y');viewport.pack(side='left',fill='both',expand=True)
    monitor=ttk.Frame(viewport);window=viewport.create_window((0,0),window=monitor,anchor='nw')
    app.monitor_scroll=viewport
    def fit(event=None):
        viewport.itemconfigure(window,width=max(300,viewport.winfo_width()),height=max(monitor.winfo_reqheight(),viewport.winfo_height()))
        viewport.configure(scrollregion=viewport.bbox('all'))
    viewport.bind('<Configure>',fit);monitor.bind('<Configure>',fit)
    ttk.Label(monitor,text='实时监测',style='Title.TLabel').pack(anchor='w')
    ttk.Label(monitor,text='传感器状态与连续波形 · 数据来自当前开发板',style='Muted.TLabel').pack(anchor='w',pady=(3,12))
    controls=ttk.LabelFrame(monitor,text='采集与触发',padding=8);controls.pack(fill='x',pady=(0,12))
    toolbar=FlowBar(controls);toolbar.pack(fill='x')
    app.pause_button=ttk.Button(toolbar,text='暂停画面',command=app.pause);app.pause_button.pack(side='left',padx=3)
    ttk.Button(toolbar,text='抓取 1.5 秒',command=lambda:app.action('snap')).pack(side='left',padx=3)
    ttk.Label(toolbar,text='自动记录').pack(side='left',padx=(12,5))
    ttk.Combobox(toolbar,textvariable=app.mode,values=('声振联合','仅声音','仅振动'),state='readonly',width=8).pack(side='left')
    for name,var,width in [('声阈值',app.a_threshold,5),('振阈值',app.v_threshold,5),('间隔ms',app.pair_window,4)]:
        ttk.Label(toolbar,text=name).pack(side='left',padx=(8,2));ttk.Entry(toolbar,textvariable=var,width=width).pack(side='left')
    ttk.Button(toolbar,text='应用并启用',command=app.arm).pack(side='left',padx=5)
    ttk.Button(toolbar,text='停止自动',command=lambda:app.action('arm',enabled=False,mode=app.mode_number())).pack(side='left')
    ttk.Button(toolbar,text='实板检查',command=app.open_guide).pack(side='left',padx=5)
    cards=ttk.Frame(monitor);cards.pack(fill='x',pady=(0,10));app.card_values={};card_frames=[]
    for key,title in [('board','板载温度'),('die','FPGA 芯片温度'),('int','核心电压'),('aux','辅助电压'),('bram','存储电压'),('acc_temp','ADXL 温度原始值')]:
        card=ttk.Frame(cards,style='Card.TFrame',padding=(14,10));card_frames.append(card)
        ttk.Label(card,text=title,style='CardMuted.TLabel').pack(anchor='w')
        var=tk.StringVar(value='—');app.card_values[key]=var
        ttk.Label(card,textvariable=var,style='CardValue.TLabel').pack(anchor='w',pady=(4,0))
    card_cols=[0]
    def layout_cards(event):
        count=6 if event.width>=1140 else 3
        if card_cols[0]==count:return
        card_cols[0]=count
        for i in range(6):cards.columnconfigure(i,weight=1 if i<count else 0,uniform='cards' if i<count else '')
        for i,card in enumerate(card_frames):card.grid(row=i//count,column=i%count,sticky='nsew',padx=(0,8 if i%count<count-1 else 0),pady=(0,6))
        root.after_idle(fit)
    cards.bind('<Configure>',layout_cards)
    grid=ttk.Frame(monitor);grid.pack(fill='both',expand=True)
    plots=ttk.Frame(grid);plots.pack(fill='both',expand=True)
    def wheel(event):
        if app.active_page!='monitor':return
        node=event.widget
        while node is not None:
            if node==viewport:viewport.yview_scroll(-int(event.delta/120),'units');return 'break'
            node=getattr(node,'master',None)
    root.bind_all('<MouseWheel>',wheel,add='+')
    for c in range(2):plots.columnconfigure(c,weight=1,uniform='panel')
    for r in range(3):plots.rowconfigure(r,weight=1,uniform='panel',minsize=190)
    app.plots={}
    for key,title,r,c in [('audio','声音预览 · 16点一组，显示时去直流',0,0),('fft','频谱 · 512点原速声音快照',0,1),('xyz','三轴加速度 · 标称换算，未绝对标定',1,0),('temp','温度趋势 · 板载 / 芯片',1,1),('voltage','FPGA 内部供电电压',2,0)]:
        plot=Plot(plots,title);plot.grid(row=r,column=c,sticky='nsew',padx=(0,8),pady=(0,8));app.plots[key]=plot
    io=ttk.LabelFrame(plots,text='开关、方向按键和静态倾斜参考',padding=6);io.grid(row=2,column=1,sticky='nsew',padx=(0,8),pady=(0,8))
    app.io_canvas=ThemedCanvas(io,bg='white',height=110,highlightthickness=0);app.io_canvas.pack(fill='both',expand=True)
    plot_panels=list(app.plots.values())+[io];plot_columns=[0]
    def layout_plots(event):
        count=2 if event.width>=1000 else 1
        if count==plot_columns[0]:return
        plot_columns[0]=count
        for c in range(2):plots.columnconfigure(c,weight=1 if c<count else 0,uniform='panel' if c<count else '')
        for r in range(6):plots.rowconfigure(r,weight=1 if r<6//count else 0,minsize=190 if r<6//count else 0)
        for i,panel in enumerate(plot_panels):panel.grid(row=i//count,column=i%count,sticky='nsew',padx=(0,8),pady=(0,8))
        root.after_idle(fit)
    plots.bind('<Configure>',layout_plots)
    events=app.pages['events']
    ttk.Label(events,text='事件记录',style='Title.TLabel').pack(anchor='w')
    ttk.Label(events,text='完整事件与历史记录 · 双击播放录音',style='Muted.TLabel').pack(anchor='w',pady=(3,16))
    actions=FlowBar(events);actions.pack(fill='x',pady=(0,12))
    for text,command in [('查看波形',app.view_event),('播放录音',app.play),('导出选中事件',app.export_selected),('打开数据目录',lambda:os.startfile(str(ROOT/'runs'))),('导出本次诊断包',app.export_diagnostics)]:
        ttk.Button(actions,text=text,command=command).pack(side='left',padx=3)
    table=ttk.Frame(events);table.pack(fill='both',expand=True);table.columnconfigure(0,weight=1);table.rowconfigure(0,weight=1)
    app.events=ttk.Treeview(table,columns=('id','mode','time','result','folder'),show='headings',height=12)
    for col,title,size in [('id','事件',65),('mode','保存方式',110),('time','板端参考时刻 / s',160),('result','校验结果 / 设备',260),('folder','保存目录',500)]:
        app.events.heading(col,text=title);app.events.column(col,width=size,minwidth=60,stretch=col=='folder')
    app.events.grid(row=0,column=0,sticky='nsew');app.events.bind('<Double-1>',app.play)
    vs=ttk.Scrollbar(table,orient='vertical',command=app.events.yview);vs.grid(row=0,column=1,sticky='ns')
    hs=ttk.Scrollbar(table,orient='horizontal',command=app.events.xview);hs.grid(row=1,column=0,sticky='ew')
    app.events.configure(yscrollcommand=vs.set,xscrollcommand=hs.set)
    app.active_page='monitor';app.show_page('monitor');app.theme_manager.set(app.theme_manager.choice,persist=False)
