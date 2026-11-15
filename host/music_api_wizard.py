"""A short online-only phone round; the old offline round remains archived."""
import json
import tkinter as tk
from tkinter import ttk
from audit import ROOT,Run,now,write_json
from music_shazam import same_song


class ApiAcceptanceWizard:
    def __init__(self,panel):
        self.p=panel;self.win=tk.Toplevel(panel.win);self.win.title('听歌识曲 · Shazam实板检查');self.win.geometry('860x540')
        self.title=tk.StringVar();self.instruction=tk.StringVar();self.progress=tk.StringVar()
        ttk.Label(self.win,textvariable=self.title,font=('Microsoft YaHei UI',18,'bold'),foreground='#173b5c').pack(anchor='w',padx=24,pady=(24,16))
        ttk.Label(self.win,textvariable=self.instruction,font=('Microsoft YaHei UI',12),wraplength=790,justify='left').pack(anchor='w',padx=24,pady=12)
        ttk.Label(self.win,textvariable=self.progress,font=('Microsoft YaHei UI',11),foreground='#168c82',wraplength=790).pack(anchor='w',padx=24,pady=16)
        self.button=ttk.Button(self.win,command=self.next);self.button.pack(anchor='w',padx=24,pady=18)
        ttk.Label(self.win,text='全程保持联网。每条录音只发起一次Shazam识别；本轮只检查在线识曲。',wraplength=790).pack(anchor='w',padx=24,pady=15)
        self.tasks=[{'kind':'online','title':title,'artist':artist,'position_s':position,'outside_library':True,'wake_attempted':False}
            for title,artist,position in [('Hotel California','Eagles',70),('Billie Jean','Michael Jackson',60),('We Will Rock You','Queen',30)]]
        self.results=[];self.active=None;self.attempts=[];self.mode='ready'
        saved=None
        try:
            state=json.loads((ROOT/'state/music_shazam_api_wizard.json').read_text(encoding='utf8'))
            saved=json.loads((ROOT/'runs'/state['run_id']/'checkpoint.json').read_text(encoding='utf8'))
        except (OSError,ValueError,KeyError):pass
        if saved:
            self.run=Run('music_api_physical_acceptance',state['run_id']);self.results=saved['results'];self.tasks=saved['tasks'];self.attempts=saved.get('interrupted_attempts',[])
            if saved.get('active'):
                self.attempts.append({**saved['active'],'outcome':'interrupted_not_scored','interrupted_at':now()})
        else:
            self.run=Run('music_shazam_physical_acceptance');self.run.snapshot('Shazam在线实板检查；离线功能按原状保留')
        self.win.protocol('WM_DELETE_WINDOW',self.hide);self.ready();self.win.after(150,self.tick)
    def show(self):self.win.deiconify();self.win.lift()
    def hide(self):self.save();self.win.withdraw()
    def save(self):
        row={'time':now(),'mode':self.mode,'step':len(self.results),'active':self.active,'results':self.results,'tasks':self.tasks,'interrupted_attempts':self.attempts}
        write_json(self.run.path/'checkpoint.json',row)
        write_json(ROOT/'state/music_shazam_api_wizard.json',{'run_id':self.run.run_id,'mode':self.mode,'step':len(self.results),'time':now()})
    def ready(self):
        if len(self.results)>=len(self.tasks):self.complete();return
        task=self.tasks[len(self.results)];pos=task['position_s'];self.mode='ready'
        self.title.set(f'在线实板检查 {len(self.results)+1}/{len(self.tasks)}')
        self.instruction.set(f'手机播放：{task["title"]} — {task["artist"]}\n拖到约{pos//60:02}:{pos%60:02}，手机扬声器靠近板载MIC。\n准备好后点击下面按钮，持续外放到20秒录音结束。本轮直接点按钮录音，不要求敲桌或离线测试。')
        self.progress.set('本条尚未开始；前一次未命中记录保留，新一轮单独统计。');self.button.configure(text='歌曲已播放，开始在线录音',state='normal');self.save()
    def next(self):
        if self.mode=='finished':self.hide();return
        if self.mode!='ready' or self.p.busy:return
        if not self.p.app.connected:self.progress.set('正在等待开发板连接。');return
        self.p.policy.set('自动');self.p.policy_changed();self.p.seconds.set('20');self.p.wake.set(False);self.p.verification_reads=False
        self.active={**self.tasks[len(self.results)],'trial':len(self.results)+1,'started_at':now(),'record_started':False}
        self.mode='recording';self.button.configure(state='disabled');self.run.event('api_phone_trial_started',trial=self.active['trial'])
        self.save();self.p.record()
    def receive(self,kind,message):
        if self.mode!='recording' or self.active is None:return
        if kind=='music_started':self.active.update(record_started=True,job_id=message['job']['id'])
        if kind=='music_complete':
            result=message['result'];row={**self.active,'finished_at':now(),'job':message['job'],'result':result,
                'correct':same_song(result,self.active),'online_correct':same_song(result,self.active) and result.get('source')=='shazamio'}
            self.results.append(row);write_json(self.run.path/f'trial_{row["trial"]:02}.json',row)
            self.active=None;self.ready()
    def tick(self):
        if self.mode=='recording':self.progress.set(self.p.stage.get())
        if self.win.winfo_exists():self.win.after(150,self.tick)
    def complete(self):
        hits=sum(bool(r['online_correct']) for r in self.results)
        cost_ok=all(r['result'].get('paid_service_calls')==0 and r['result'].get('cost_yuan')==0 for r in self.results)
        result={'schema':'shazam_board_v1','provider':'shazamio','run_id':self.run.run_id,'time':now(),'source':'real_board_microphone_operator_phone',
            'results':self.results,'tasks':self.tasks,'interrupted_attempts':self.attempts,'online_correct':hits,'online_total':len(self.results),
            'offline_development_closed_by_user':True,'remaining_offline_tests_cancelled_by_user':True,
            'actual_cost_yuan':0 if cost_ok else None,'target_met':hits>=2 and cost_ok}
        write_json(self.run.path/'result.json',result);write_json(ROOT/'state/music_shazam_phone_round.json',result)
        self.mode='finished';self.p.board('music_disable');self.title.set('本轮在线检查完成')
        self.instruction.set(f'Shazam正确 {hits}/{len(self.results)}；'+('未使用付费接口。' if cost_ok else '调用记录仍待核对。')+'\n原始录音、未命中和新旧版本结果均已保存。请回到对话回复“完成”。')
        self.progress.set('离线功能已按现状收尾。');self.button.configure(text='关闭检查窗口',state='normal');self.save()
        self.run.status('MUSIC6_api_phone','passed' if result['target_met'] else 'failed','实板在线目标达到且0元' if result['target_met'] else '实测结果已保留，未达到在线目标',
            [(self.run.path/'result.json').relative_to(ROOT).as_posix()],'原功能回归与报告收尾')
