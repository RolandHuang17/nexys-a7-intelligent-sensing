"""Shorter, API-first physical round; prior development captures stay intact."""
import json,time,re
from pathlib import Path
from audit import ROOT,now,write_json
from music_wizard import MusicAcceptanceWizard

def same_song(result,task):
    def plain(s):return re.sub(r'[^a-z0-9]+','',s.casefold())
    # Remaster labels and article variants are retained in the actual API reply.
    title=re.split(r'\s[\[(\-]',result.get('title',''),maxsplit=1)[0]
    return bool(result.get('matched') and plain(title)==plain(task.get('title','')) and
                plain(result.get('artist','')).removeprefix('the')==plain(task.get('artist','')).removeprefix('the'))

class OnlineAcceptanceWizard(MusicAcceptanceWizard):
    requires_offline_confirmation=False
    def __init__(self,panel):
        super().__init__(panel)
        self.win.title('听歌识曲 · 在线优先实板检查')
        self.p.verification_reads=False
        if not self.tasks or self.mode in ('intro','formal_intro'):self.formal_prompt()
        self.run.event('acceptance_scope_updated',reason='用户要求API优先，离线保留为辅助板块；不再要求离线留出轮或实际断网',
                       prior_development_preserved=True,automatic_order='online_first')
        self.save()
    def configure(self,wake=True):
        self.p.policy.set('自动');self.p.policy_changed();self.p.seconds.set('20');self.p.wake.set(wake);self.p.enable()
    def formal_prompt(self):
        self.mode='formal_intro';self.title.set('前面的采样保留，接着检查在线识曲')
        self.instruction.set('保持电脑联网，不用重录开发组。接下来五首歌各录20秒，检查API优先，再做几次双击、中键收藏和干扰检查。\n每一项等你准备好再点按钮，手机声音靠近板载MIC；窗口不会自行跳过等待。')
        self.button.configure(text='准备好了，开始在线检查',state='normal')
        self.progress.set('已有五首开发录音和校准数据保留；离线正式准确率与实际断网测试不再继续。')
    def next(self):
        if not self.p.app.connected:self.progress.set('正在等待实板连接，尚未开始。');return
        if self.p.busy and self.mode!='game_reveal':self.progress.set('当前录音或匹配尚未结束，请稍候。');return
        if self.mode=='formal_intro':
            self.prepare_tasks();self.step=0;self.task_ready()
        elif self.mode=='formal_ready':self.start_task()
        elif self.mode=='formal_recording' and self.active and not self.active.get('record_started'):
            self.active.update(wake_success=False,manual_fallback=True);self.p.record();self.deadline=None
            self.progress.set('本次双击已记为未唤醒，用按钮保留这一条录音。')
        elif self.mode=='resume_ready':
            if self.tasks:self.task_ready()
            else:self.formal_prompt()
        else:super().next()
        self.save()
    def prepare_tasks(self):
        self.tasks=[{'kind':'online','title':t,'artist':a,'position_s':p,'outside_library':outside} for t,a,p,outside in [
            ('Take It Easy','Eagles',55,False),('Tequila Sunrise','Eagles',55,False),
            ('Hotel California','Eagles',70,True),('Billie Jean','Michael Jackson',60,True),('We Will Rock You','Queen',30,True)]]
        self.tasks += [{'kind':'wake','number':i+1} for i in range(5)]
        self.tasks += [{'kind':'single','number':i+1} for i in range(3)]
        self.tasks += [{'kind':'typing','seconds':30},{'kind':'music_only','seconds':30}]
        write_json(self.run.path/'online_protocol.json',{'time':now(),'tasks':self.tasks,'source':'physical_phone_playback',
            'automatic_order':'online_first','physical_disconnect':'skipped_by_user','offline_holdout':'deprioritized_by_user',
            'match_profile':self.p.store.setting('match_profile'),'tap_profile':self.p.store.setting('tap_profile'),
            'recognizer_never_receives_ground_truth':True,'prior_development_retained':True})
    def task_ready(self):
        if self.step>=len(self.tasks):
            if any(r.get('online_correct') for r in self.results) and not self.game_evidence:
                self.mode='game_intro';self.typing.delete(0,'end');self.title.set('最后试一局：人机抢歌名')
                self.instruction.set('从本地歌单五首中任选一首外放。点击开局，想到歌名就拍一下桌锁时，在下方填歌名再揭晓；机器答案保持隐藏。')
                self.progress.set('这局用本地歌单，只验证玩法和实际计时。');self.button.configure(text='音乐已在播放，开始这一局',state='normal');return
            self.complete();return
        task=self.tasks[self.step];self.mode='formal_ready';self.title.set(f'实板检查 {self.step+1}/{len(self.tasks)}')
        self.p.policy.set('自动' if task['kind']=='online' else '仅离线');self.p.policy_changed()
        self.p.seconds.set('20' if task['kind']=='online' else '8');self.p.wake.set(False);self.p.enable()
        if task['kind']=='online':
            pos=task['position_s'];self.instruction.set(f'手机播放：{task["title"]} — {task["artist"]}\n拖到约{pos//60:02}:{pos%60:02}，保持清楚的外放。点按钮后等一秒，敲两下桌面，继续播放到录音结束。')
        elif task['kind']=='wake':self.instruction.set(f'双击补充检查 {task["number"]}/5：保持上一首歌外放。点按钮后等一秒，敲两下桌面，随后停手；这条8秒录音只查本地，不上传。')
        elif task['kind']=='single':self.instruction.set(f'单敲检查 {task["number"]}/3：点按钮后等一秒，只敲一下，随后停手。')
        elif task['kind']=='typing':self.instruction.set('点按钮后连续打字30秒，可在下方输入框输入；不保存文字，只统计按键与误唤醒。')
        else:self.instruction.set('点按钮后手机外放音乐30秒，不敲桌、不碰板子，统计误唤醒。')
        self.progress.set('本条尚未开始。');self.button.configure(text='准备好了，开始这一项',state='normal');self.save()
    def start_task(self):
        self.rows=[];self.active={**self.tasks[self.step],'trial':self.step+1,'started_at':now(),
            'baseline':dict(self.p.last_status or {}),'record_started':False,'key_baseline':self.keys}
        self.run.event('online_priority_trial_started',trial=self.step+1,kind_of_trial=self.active['kind'],expected=self.tasks[self.step])
        self.mode='formal_recording';self.button.configure(state='disabled');self.p.wake.set(True);self.p.enable()
        self.deadline=time.monotonic()+(7 if self.active['kind'] in ('online','wake') else self.active.get('seconds',4))
        self.progress.set('现在按上面的提示操作。');self.save()
    def receive(self,kind,message):
        if kind=='telemetry' and self.mode=='formal_recording':self.rows.extend(message.get('xyz',[]))
        if kind=='music_started' and self.mode=='formal_recording' and self.active:
            self.active.update(record_started=True,job_id=message['job']['id'])
            if self.active['kind'] in ('online','wake'):
                self.deadline=None;self.active['wake_success']=not self.active.get('manual_fallback',False)
        if kind=='music_complete' and self.mode=='formal_recording' and self.active and self.active['kind'] in ('online','wake'):
            result=message['result'];self.active.update(result=result,job=message['job'],correct=same_song(result,self.active))
            self.active['online_correct']=bool(self.active['correct'] and result.get('source')=='audiotag')
            self.finish_task();return
        if self.mode!='formal_recording':super().receive(kind,message)
    def finish_task(self):
        row=self.active;row.update(finished_at=now(),last_status=dict(self.p.last_status or {}),keys_observed=self.keys-row['key_baseline'])
        if row['kind'] in ('single','typing','music_only'):row['false_wakes']=((row['last_status'].get('double_seq',0)-row['baseline'].get('double_seq',0))&0xffffffff)
        self.results.append(row);write_json(self.run.path/f'online_trial_{self.step+1:02}.json',row)
        if self.rows:write_json(self.run.path/f'online_trial_{self.step+1:02}_xyz.json',self.rows)
        self.active=None;self.step+=1;self.deadline=None
        song=row.get('result',{}).get('song_id')
        if row.get('correct') and song and not self.favourite_check:
            self.p.wake.set(False);self.p.enable();self.mode='favourite_wait'
            self.favourite_baseline=(self.p.last_status or {}).get('center_seq',0);self.favourite_song=song
            self.title.set('这首已识别：按中键收藏两次');self.instruction.set('对板上BTNC中键短按、松开两次，检查板端计数与收藏去重。')
            self.progress.set('等待板端中键计数。');self.button.configure(text='已经短按两次，继续',state='normal')
        else:self.task_ready()
        self.save()
    def tick(self):
        if self.deadline:
            left=max(0,self.deadline-time.monotonic());self.progress.set(f'剩余 {left:.1f} 秒')
            if left<=0:
                self.deadline=None
                if self.active and self.mode=='formal_recording':
                    if self.active['kind'] in ('online','wake') and not self.active['record_started']:
                        self.active['wake_success']=False;self.button.configure(text='双击未唤醒，用按钮保留此条录音',state='normal')
                        self.progress.set('本次双击未成功，不删除这次尝试；点按钮继续保存录音。')
                    elif self.active['kind'] in ('single','typing','music_only'):
                        if self.p.busy:self.deadline=time.monotonic()+1
                        else:self.finish_task()
        if self.win.winfo_exists():self.win.after(100,self.tick)
    def complete(self):
        online=[r for r in self.results if r['kind']=='online'];outside=[r for r in online if r['outside_library']]
        wakes=[r for r in self.results if r['kind'] in ('online','wake')]
        summary={'schema':'online_priority_v1','run_id':self.run.run_id,'time':now(),'source':'real_board_microphone_operator_phone',
            'automatic_order':'online_first','online_correct':sum(r.get('online_correct',False) for r in online),'online_total':len(online),
            'outside_online_correct':sum(r.get('online_correct',False) for r in outside),'outside_online_total':len(outside),
            'double_wake_success':sum(r.get('wake_success',False) for r in wakes),'double_wake_total':len(wakes),
            'false_wakes':{k:sum(r.get('false_wakes',0) for r in self.results if r['kind']==k) for k in ('single','typing','music_only')},
            'favourite_check':self.favourite_check,'game':self.game_evidence,'physical_disconnect_skipped_by_user':True,
            'offline_holdout':'not_run_after_user_scope_change','results':self.results,'interrupted_attempts':self.attempts}
        write_json(self.run.path/'result.json',summary);write_json(ROOT/'state/music_online_round.json',summary)
        self.p.board('music_disable');self.mode='finished';self.title.set('本轮检查完成，原始记录已保存')
        self.instruction.set(f'在线正确 {summary["online_correct"]}/{len(online)}，其中库外 {summary["outside_online_correct"]}/{len(outside)}；双击唤醒 {summary["double_wake_success"]}/{len(wakes)}。\n回到对话回复“完成”，没有做成的步骤请注明。')
        self.progress.set('没有要求断网；报告按实测列结果，不把离线开发数据写成正式准确率。');self.button.configure(text='关闭向导',state='normal')
        self.run.event('online_priority_round_finished',summary={k:v for k,v in summary.items() if k!='results'});self.save();self.run.manifest()
