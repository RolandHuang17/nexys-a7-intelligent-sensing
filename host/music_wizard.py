"""Operator-paced physical acceptance, resumable and explicit about evidence type."""
import json,time,random,math,wave,uuid
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox
from audit import ROOT,Run,write_json,now
from app_paths import RESOURCE_ROOT

def tap_counts(rows,high,low,min_ms=150,max_ms=600):
    """Independent timestamp-based counterpart of the board impulse/pair gate."""
    previous=None;rearmed=True;last=-10**18;pending=None;taps=[];pairs=[]
    for row in rows:
        vector=[row[k] for k in ('x','y','z')];tick=row['tick']
        if previous is None:previous=vector;continue
        delta=sum(abs(a-b) for a,b in zip(vector,previous));previous=vector
        if pending is not None and tick-pending>max_ms*100000:pending=None
        if delta<=low:rearmed=True
        if rearmed and delta>=high and tick-last>=10000000:
            rearmed=False;last=tick;taps.append(tick)
            if pending is not None and min_ms*100000<=tick-pending<=max_ms*100000:pairs.append(tick);pending=None
            elif pending is None:pending=tick
    return taps,pairs

def fit_taps(windows):
    candidates=[]
    for maximum in (600,800,1000):
        for high in (20,30,40,50,60,80,100,120,160,200,250,320,450,600):
            for ratio in (.4,.6):
                low=max(1,int(high*ratio));false=success=0;details=[]
                for window in windows:
                    taps,pairs=tap_counts(window['rows'],high,low,150,maximum)
                    details.append({'kind':window['kind'],'taps':len(taps),'pairs':len(pairs)})
                    if window['kind']=='double':success+=int(bool(pairs))
                    else:false+=len(pairs)
                candidates.append({'high':high,'low':low,'min_ms':150,'max_ms':maximum,'false':false,'success':success,'details':details})
    return candidates,min(candidates,key=lambda c:(c['false'],-c['success'],c['max_ms'],c['high'],c['low']))

class MusicAcceptanceWizard:
    requires_offline_confirmation=True
    def __init__(self,panel):
        self.p=panel;self.win=tk.Toplevel(panel.win);self.win.title('听歌识曲 · 集中实板验收');self.win.geometry('870x610');self.win.minsize(820,560)
        resume=None
        try:
            state=json.loads((ROOT/'state/music_wizard.json').read_text(encoding='utf8'))
            prior=ROOT/'runs'/state['run_id']/'checkpoint.json'
            saved=json.loads(prior.read_text(encoding='utf8'))
            if saved['mode']!='finished':resume=saved;self.run=Run('music_physical_acceptance',state['run_id'])
        except (OSError,ValueError,KeyError):pass
        if resume is None:
            self.run=Run('music_physical_acceptance');self.run.snapshot('集中手机外放、双击、中键和负样本验收；等待操作者准备')
        self.title=tk.StringVar(value='准备手机外放，按提示逐条操作');self.instruction=tk.StringVar(value='先准备对话中列出的五首原版音乐，用手机搜索或播放已有文件即可。\n本向导先校准双击，再采开发组并冻结参数，最后做正式验收。每一步等你点按钮才开始。');self.progress=tk.StringVar(value='尚未开始；没有把等待时间算作试次。')
        ttk.Label(self.win,textvariable=self.title,font=('Microsoft YaHei UI',18,'bold'),foreground='#173b5c').pack(anchor='w',padx=26,pady=(25,14))
        ttk.Label(self.win,textvariable=self.instruction,font=('Microsoft YaHei UI',12),wraplength=800,justify='left').pack(anchor='w',padx=26,pady=12)
        ttk.Label(self.win,textvariable=self.progress,font=('Microsoft YaHei UI',12,'bold'),foreground='#168c82',wraplength=800).pack(anchor='w',padx=26,pady=15)
        self.button=ttk.Button(self.win,text='我已准备好，开始双击校准',command=self.next);self.button.pack(anchor='w',padx=26,pady=16)
        try:self.skip_disconnect=json.loads((ROOT/'state/music_operator_preferences.json').read_text(encoding='utf8')).get('skip_physical_disconnect',False)
        except (OSError,ValueError):self.skip_disconnect=False
        self.offline=tk.BooleanVar(value=False)
        if not self.requires_offline_confirmation:ttk.Label(self.win,text='本轮保持联网，按各条提示检查在线识曲或仅离线功能。').pack(anchor='w',padx=26,pady=10)
        elif self.skip_disconnect:ttk.Label(self.win,text='本次保持电脑联网；实际断网测试按用户要求标为未做，各条模式见上方提示。').pack(anchor='w',padx=26,pady=10)
        else:ttk.Checkbutton(self.win,text='正式离线阶段：我已让电脑断网（本软件仍会强制仅离线）',variable=self.offline).pack(anchor='w',padx=26,pady=10)
        self.typing=ttk.Entry(self.win,width=85);self.typing.pack(anchor='w',padx=26,pady=8);self.typing.bind('<KeyPress>',self.keypress)
        ttk.Label(self.win,text=' typing阶段可在这里随意打字；只记按键次数，不保存输入文字。',foreground='#60758a').pack(anchor='w',padx=26)
        self.mode='intro';self.rows=[];self.calibration=[];self.cal_windows=[];self.results=[];self.step=-1;self.deadline=None;self.active=None;self.next_task=None;self.keys=0
        self.favourite_check=None;self.game_evidence=None;self.tasks=[];self.cal_step=0;self.attempts=[];self.dev_tasks=[];self.dev_results=[];self.dev_step=0;self.dev_attempt=1
        if resume:
            self.results=resume['results'];self.cal_windows=resume['calibration_windows'];self.step=resume['step'];self.cal_step=resume.get('cal_step',len(self.cal_windows));self.tasks=resume.get('tasks',[])
            self.favourite_check=resume.get('favourite_check');self.attempts=resume.get('interrupted_attempts',[])
            self.game_evidence=resume.get('game_evidence')
            self.dev_tasks=resume.get('dev_tasks',[]);self.dev_results=resume.get('dev_results',[]);self.dev_step=resume.get('dev_step',0);self.dev_attempt=resume.get('dev_attempt',1)
            if resume.get('active'):
                self.attempts.append({**resume['active'],'interrupted_at':now(),'outcome':'interrupted_not_counted_as_success'})
                self.run.event('operator_trial_interrupted',trial=resume['active'].get('trial'),job_id=resume['active'].get('job_id'))
            self.resume_mode=resume['mode'];self.mode='resume_ready'
            self.title.set('发现上次检查记录，可以接着做')
            self.instruction.set('已完成的试次和校准保留。中断的试次单独保留，不计成功，重新准备后再采。'+
                ('正式离线试次仍需确认电脑断网。' if self.requires_offline_confirmation and not self.skip_disconnect else '保持电脑联网，继续上次未完成的步骤。'))
            self.button.configure(text='恢复上次进度')
            if self.resume_mode=='formal_intro' and self.p.store.setting('match_profile',{}).get('status')=='frozen_before_holdout':self.formal_prompt()
        self.win.protocol('WM_DELETE_WINDOW',self.hide);self.save();self.win.after(100,self.tick)
    def show(self):self.win.deiconify();self.win.lift()
    def hide(self):self.save();self.win.withdraw()
    def keypress(self,event):self.keys+=1
    def save(self):
        write_json(self.run.path/'checkpoint.json',{'time':now(),'mode':self.mode,'step':self.step,'active':self.active,'results':self.results,
            'calibration_windows':self.cal_windows,'operator_offline_confirmation':self.offline.get(),'keys':self.keys,'title':self.title.get(),
            'cal_step':self.cal_step,'tasks':self.tasks,'favourite_check':self.favourite_check,'game_evidence':self.game_evidence,'interrupted_attempts':self.attempts,
            'dev_tasks':self.dev_tasks,'dev_results':self.dev_results,'dev_step':self.dev_step,'dev_attempt':self.dev_attempt,'physical_disconnect_skipped_by_user':self.skip_disconnect})
        write_json(ROOT/'state/music_wizard.json',{'run_id':self.run.run_id,'mode':self.mode,'step':self.step,'active':self.active,'time':now()})
    def configure(self,wake=True):
        self.p.policy.set('仅离线');self.p.policy_changed();self.p.wake.set(wake);self.p.enable()
    def formal_prompt(self):
        self.mode='formal_intro';self.title.set('前面的数据已保存，直接继续正式验收')
        if self.skip_disconnect:
            self.instruction.set('不用重录刚才五段，也不用断网。正式任务仍固定为“仅离线”，不向AudioTag发请求。\n接下来五首歌曲各用两个新位置，并检查双击、中键和干扰。每条都等你准备好后点按钮。')
            self.button.configure(text='保持联网，开始仅离线正式试次',state='normal')
        else:
            self.instruction.set('正式任务固定为“仅离线”。请断开电脑网络，手机继续播放已有音乐，勾选断网确认后开始。')
            self.button.configure(text='已断网，开始正式试次',state='normal')
        self.progress.set('歌单与门槛已冻结，正式位置避开开发采样片段。')
    def next(self):
        if not self.p.app.connected:self.progress.set('请先等待主窗口连接实板；未开始试次。');return
        if self.p.busy and self.mode!='game_reveal':self.progress.set('当前录音还未结束，请稍候。');return
        if self.mode=='resume_ready':
            if self.tasks:
                if not self.offline.get() and not self.skip_disconnect:self.progress.set('恢复正式试次前，请先勾选断网确认。');return
                self.configure(wake=True);self.task_ready()
            elif self.dev_tasks:self.configure(wake=False);self.dev_ready()
            elif self.cal_step<=10:self.configure(wake=False);self.cal_ready()
            else:
                self.mode='development_intro';self.title.set('双击校准已完成，准备手机开发采样');self.instruction.set('先用手机录五首入库歌曲和开发负样本；随后冻结参数再正式验收。');self.button.configure(text='准备开发组采样')
        elif self.mode=='intro':
            self.configure(wake=False);self.mode='calibration';self.cal_step=0;self.cal_ready()
        elif self.mode=='calibration_ready':self.cal_start()
        elif self.mode in ('development_intro','development_failed'):
            self.prepare_development();self.configure(wake=False);self.dev_ready()
        elif self.mode=='development_ready':
            self.mode='development_recording';self.button.configure(state='disabled');self.p.record();self.progress.set('正在录开发数据，请继续外放；这条不计正式成绩。')
        elif self.mode=='formal_intro':
            if not self.offline.get() and not self.skip_disconnect:self.progress.set('请先确认电脑已断网，再开始正式离线试次。');return
            self.prepare_tasks();self.configure(wake=True);self.mode='formal_ready';self.step=0;self.task_ready()
        elif self.mode=='formal_ready':self.start_task()
        elif self.mode=='formal_recording' and self.active and self.active['kind']=='positive' and not self.active.get('record_started'):
            self.active['wake_success']=False;self.active['manual_fallback']=True;self.p.record();self.progress.set('双击未唤醒已记为失败，现在用按钮保存本次歌曲。')
        elif self.mode=='favourite_wait':
            count=((self.p.last_status or {}).get('center_seq',0)-self.favourite_baseline)&0xffffffff
            if count<2:self.progress.set(f'板端记录到{count}次中键按下，请短按并松开两次。');return
            with self.p.store.db() as c:copies=c.execute('SELECT count(*) FROM favourites WHERE song_id=?',(self.favourite_song,)).fetchone()[0]
            if copies!=1:self.progress.set('收藏写入尚未完成，请稍候。');return
            self.favourite_check={'source':'physical_BTNC','center_seq_before':self.favourite_baseline,'center_seq_after':self.p.last_status['center_seq'],
                'presses':count,'song_id':self.favourite_song,'favourite_rows':copies,'time':now()}
            write_json(self.run.path/'physical_favourite.json',self.favourite_check);self.task_ready()
        elif self.mode=='game_intro':
            self.mode='game_running';self.p.seconds.set(str(self.p.store.setting('match_profile')['seconds']));self.p.start_game();self.button.configure(state='disabled')
            self.title.set('最后一局：想到歌名就拍桌');self.instruction.set('机器继续录音。请拍一下桌面锁定人的时间，在下方输入你猜的歌名；机器答案暂时隐藏。')
        elif self.mode=='game_reveal':
            if not (self.p.last_status or {}).get('human_tick'):self.progress.set('还没有记录到拍桌，请拍一下并等状态更新。');return
            answer=self.typing.get().strip()
            if not answer:self.progress.set('请在下方填写你猜的歌名，再揭晓。');return
            self.p.game_answer.set(answer);self.mode='game_revealing';self.p.reveal();self.button.configure(state='disabled')
        elif self.mode=='finished':self.win.withdraw()
        self.save()
    def cal_ready(self):
        self.mode='calibration_ready';self.rows=[]
        if self.cal_step==0:
            self.title.set('校准 1/11：只放歌，先不敲桌');self.instruction.set('让手机外放音乐，板子保持平放，30秒内不碰桌面；准备后点下面按钮。')
        elif self.cal_step<=5:
            self.title.set(f'校准 {self.cal_step+1}/11：只敲一下');self.instruction.set('点按钮后等一秒，只敲桌面一下，然后停手；不要敲成两下。')
        else:
            self.title.set(f'校准 {self.cal_step+1}/11：敲两下');self.instruction.set('点按钮后等一秒，敲桌两下，中间约0.2至1秒，再停手。')
        self.button.configure(text='准备好了，开始这一项',state='normal');self.progress.set('此阶段用来确定阈值，不计入正式十次成绩。')
    def cal_start(self):
        self.mode='calibration_running';self.rows=[];self.deadline=time.monotonic()+(30 if self.cal_step==0 else 5);self.button.configure(state='disabled')
        self.run.event('calibration_window_started',step=self.cal_step,kind='music_only' if self.cal_step==0 else 'single' if self.cal_step<=5 else 'double')
    def finish_calibration(self):
        row={'step':self.cal_step,'kind':'music_only' if self.cal_step==0 else 'single' if self.cal_step<=5 else 'double','rows':self.rows}
        self.cal_windows.append(row);write_json(self.run.path/f'calibration_{self.cal_step:02}.json',row)
        self.cal_step+=1
        if self.cal_step<=10:self.cal_ready();return
        candidates,best=fit_taps(self.cal_windows)
        self.p.store.set_setting('tap_profile',{k:best[k] for k in ('high','low','min_ms','max_ms')})
        write_json(self.run.path/'tap_selection.json',{'candidates':candidates,'chosen':best,'window_ms':[best['min_ms'],best['max_ms']],'refractory_ms':100,'frozen_before_formal':True})
        self.p.board('music_disable');self.mode='development_intro';self.title.set('双击参数已保存，先采手机开发组')
        self.instruction.set(f'双击开发校准：成功 {best["success"]}/5，误唤醒 {best["false"]} 次。\n下一步五首入库曲目各录一段，再录说话和安静；开发用库外数据由程序复用。手机放在麦克风附近约15厘米，保持能清楚听见的音量。\n这些数据只用来选参数，正式位置会重新随机选择。')
        self.button.configure(text='准备手机开发组采样',state='normal');self.progress.set('所有开发和失败数据保留，正式组尚未开始。')
    def music_manifest(self):
        path=ROOT/'music_demo/manifest.json'
        if not path.exists():path=RESOURCE_ROOT/'music_demo/manifest.json'
        return json.loads(path.read_text(encoding='utf8'))
    def prepare_development(self):
        self.p.seconds.set('10')
        if self.dev_results:
            write_json(self.run.path/f'development_attempt_{self.dev_attempt:02}.json',{'trials':self.dev_results,'outcome':'retained_before_retry'})
            self.dev_attempt+=1
        self.dev_results=[];self.dev_step=0
        # Reuse the archived development negatives so the operator only needs
        # the five requested songs, speech and quiet in this stage.
        baseline=[]
        try:
            state=json.loads((ROOT/'state/MUSIC3_recording/status.json').read_text(encoding='utf8'))
            prior=json.loads((ROOT/'runs'/state['run_id']/'result.json').read_text(encoding='utf8'))
            baseline=[t for t in prior['trials'] if t['track'].get('group')=='development_negative']
        except (OSError,ValueError,KeyError):pass
        if baseline:
            for t in baseline:
                wav=Path(t['metadata']['wav']);self.dev_results.append({**t,'trial':len(self.dev_results)+1,'prefix_wav':str(wav.parent.parent/'first8.wav'),'reused_archived_development_negative':True})
        else:
            from music_library import decode
            from audit import sha256
            for track in self.music_manifest()['tracks']:
                if track['group']!='development_negative':continue
                base=ROOT if (ROOT/track['file']).exists() else RESOURCE_ROOT
                full=self.run.path/(track['title']+'_full.wav');decode(base/track['file'],full,16000)
                wav=self.run.path/(track['title']+'_digital_negative.wav');prefix=wav.with_name(wav.stem+'_8s.wav')
                with wave.open(str(full),'rb') as w:w.setpos(30*16000);raw=w.readframes(160000)
                for path,pcm in ((wav,raw),(prefix,raw[:256000])):
                    with wave.open(str(path),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(pcm)
                self.dev_results.append({'trial':len(self.dev_results)+1,'track':{**track,'expected':False},'metadata':{'wav':str(wav),'wav_sha256':sha256(wav),'export_s':0,'source':'digital_development_negative_not_physical'},'prefix_wav':str(prefix),'transfer8_s':None})
        self.dev_tasks=[{'title':r['title'],'artist':r['artist'],'expected':True,'position_s':30} for r in self.p.store.recordings()]
        self.dev_tasks += [{'title':'环境语音','artist':'','expected':False,'description':'正常说话，不播放音乐'}, {'title':'环境安静','artist':'','expected':False,'description':'保持安静，不播放音乐'}]
    def dev_ready(self):
        if self.dev_step>=len(self.dev_tasks):
            data=self.run.path/f'development_attempt_{self.dev_attempt:02}.json';write_json(data,{'trials':self.dev_results,'source':'board_microphone_phone_development'})
            self.mode='development_calibrating';self.title.set('开发组已采齐，正在选择门槛');self.instruction.set('现在可以暂停播放。程序比较同一段录音的前8秒与完整10秒，并用库外和噪声一起检查，达到要求后才冻结参数。')
            self.button.configure(state='disabled');self.p.engine.submit('calibrate',id=uuid.uuid4().hex,data=str(data));self.save();return
        task=self.dev_tasks[self.dev_step];self.mode='development_ready';self.title.set(f'手机开发采样 {self.dev_step+1}/{len(self.dev_tasks)}')
        self.p.verification_reads=bool(task['expected']);self.p.enable()
        self.instruction.set((f'手机播放：{task["title"]} — {task["artist"]}\n拖到00:30开始外放；手机在板载麦克风附近约15厘米，保持清楚的音量。点按钮后无需敲桌，系统手动录音。' if 'position_s' in task else task['description']+'。点按钮后开始10秒录音。'))
        self.button.configure(text='声音已准备好，录这一条开发数据',state='normal');self.progress.set('本条未开始；不用着急，每一条都等你点击。');self.save()
    def prepare_tasks(self):
        records=self.p.store.recordings();rng=random.Random(20261114);tasks=[]
        for r in records:
            upper=max(10,int(r['duration'])-15)
            available=[s for s in range(5,upper+1) if s+10<=30 or s>=40]
            p1=rng.choice(available);p2=rng.choice([s for s in available if abs(s-p1)>=20])
            for pos in (p1,p2):tasks.append({'kind':'positive','title':r['title'],'artist':r['artist'],'position_s':pos})
        rng.shuffle(tasks)
        tasks += [{'kind':'single','number':i+1} for i in range(10)]
        tasks += [{'kind':'typing','seconds':60},{'kind':'music_only','seconds':60}]
        manifest_path=ROOT/'music_demo/manifest.json'
        if not manifest_path.exists():manifest_path=RESOURCE_ROOT/'music_demo/manifest.json'
        manifest=json.loads(manifest_path.read_text(encoding='utf8'))
        selection=ROOT/'config/music_selected_playlist.json'
        if not selection.exists():selection=RESOURCE_ROOT/'music/selected_playlist.json'
        outside=json.loads(selection.read_text(encoding='utf8'))['formal_outside_tracks'] if selection.exists() else [r for r in manifest['tracks'] if r['group']=='holdout_negative']
        tasks += [{**{k:r[k] for k in ('title','artist')},'kind':'outside','position_s':30} for r in outside]
        tasks += [{'kind':'noise','description':'在板子附近正常说话，不播放音乐'},{'kind':'noise','description':'在桌上正常敲键盘，不播放音乐'}]
        self.tasks=tasks;write_json(self.run.path/'frozen_protocol.json',{'tasks':tasks,'match_profile':self.p.store.setting('match_profile'),
            'tap_profile':self.p.store.setting('tap_profile'),'library_manifest':json.loads((ROOT/'music/library_manifest.json').read_text(encoding='utf8')),
            'operator_offline_confirmation':self.offline.get(),'physical_disconnect_skipped_by_user':self.skip_disconnect,'recognizer_never_receives_ground_truth':True,'no_overlap_with_development_segment_30_to_40s':True})
    def task_ready(self):
        if self.step>=len(self.tasks):
            positives=[r for r in self.results if r.get('kind')=='positive'];negatives=[r for r in self.results if r.get('kind') in ('outside','noise')]
            passed=sum(bool(r.get('correct')) for r in positives)>=8 and sum(bool(r.get('wake_success')) for r in positives)>=9 and not any(r.get('result',{}).get('matched') for r in negatives)
            if passed and not self.game_evidence:
                self.mode='game_intro';self.typing.delete(0,'end');self.title.set('主流程已达标，最后试一局抢歌名')
                self.instruction.set('请从五首歌中自己随机选一首，从中间外放。点按钮开局，想到歌名就拍一下桌，随后在下方填写答案并揭晓。这个输入是你的抢答答案，揭晓时会保存。')
                self.progress.set('机器的答案在揭晓前保持隐藏；这局只验证玩法和实际计时。');self.button.configure(text='音乐已在播放，开始这一局',state='normal');return
            self.complete();return
        task=self.tasks[self.step];self.title.set(f'正式试次 {self.step+1}/{len(self.tasks)}')
        self.p.wake.set(False);self.p.seconds.set('20' if task['kind']=='outside' else str(self.p.store.setting('match_profile')['seconds']));self.p.enable()
        if task['kind'] in ('positive','outside'):
            pos=task['position_s'];self.instruction.set(f'手机播放：{task["title"]} — {task["artist"]}\n拖到约 {pos//60:02}:{pos%60:02} 开始外放。'+ ('点按钮后敲两下桌面，等本次识曲结束。' if task['kind']=='positive' else '点按钮后系统手动录音；请不要敲桌。'))
        elif task['kind']=='single':self.instruction.set(f'单敲检查 {task["number"]}/10：点按钮，等一秒后只敲一下，随后停手。')
        elif task['kind']=='typing':self.instruction.set('连续打字60秒，不放歌、不敲桌；可在下方输入框随意输入，内容不会保存。')
        elif task['kind']=='music_only':self.instruction.set('手机持续外放一首歌60秒，不敲桌、不碰开发板；只统计误唤醒。')
        else:self.instruction.set(task['description']+'；点按钮后系统手动录音。')
        self.mode='formal_ready';self.button.configure(text='准备好了，开始本试次',state='normal');self.progress.set('本试次未开始。')
    def start_task(self):
        self.rows=[];self.active={**self.tasks[self.step],'trial':self.step+1,'started_at':now(),'baseline':dict(self.p.last_status or {}),'record_started':False,'key_baseline':self.keys}
        self.run.event('formal_trial_started',trial=self.step+1,kind_of_trial=self.active['kind'],expected=self.tasks[self.step])
        self.mode='formal_recording';self.button.configure(state='disabled')
        self.p.wake.set(self.active['kind'] not in ('outside','noise'));self.p.enable()
        if self.active['kind']=='positive':self.deadline=time.monotonic()+6;self.progress.set('现在敲两下桌面；若未唤醒，稍后可用按钮保留这条歌曲试次。')
        elif self.active['kind'] in ('outside','noise'):self.p.record();self.deadline=None
        else:self.deadline=time.monotonic()+(self.active.get('seconds') or 4);self.progress.set('检查正在进行，请按上述动作操作。')
        self.save()
    def receive(self,kind,message):
        if kind=='music_game_ready' and self.mode=='game_running':
            self.mode='game_reveal';self.title.set('机器已经取得结果，答案还没揭晓');self.instruction.set('先拍桌锁时，并在下方填写你猜的歌名，再点按钮一起揭晓。不会用歌单中的预设时间代替机器实际完成时间。')
            self.button.configure(text='锁定我的答案并揭晓',state='normal');self.save();return
        if kind=='music_complete' and self.mode=='game_revealing':
            self.game_evidence=message['job']['game_result'];write_json(self.run.path/'physical_game.json',self.game_evidence);self.complete();return
        if kind=='music_worker' and message.get('payload',{}).get('action')=='calibrate' and self.mode=='development_calibrating':
            response=message['payload'];result=response.get('result',{})
            if response.get('ok') and result.get('accepted'):
                self.p.verification_reads=False;self.p.seconds.set(str(result['profile']['seconds']));self.p.board('music_disable');self.mode='formal_intro'
                self.formal_prompt()
            else:
                self.mode='development_failed';self.title.set('开发组还没达标，数据已保留');self.instruction.set('请把手机扬声器靠近板载MIC、让音量足够清楚；不敲开发板。准备后重采开发组，上一轮仍保留，不会算作正式通过。');self.button.configure(text='调整好了，重采开发组',state='normal')
            self.save();return
        if kind=='music_complete' and self.mode=='development_recording':
            job=message['job'];metadata=job['metadata'];wav=Path(metadata['wav']);prefix=wav.with_name('development_first8.wav')
            with wave.open(str(wav),'rb') as w:raw=w.readframes(128000)
            with wave.open(str(prefix),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(raw)
            row={'trial':len(self.dev_results)+1,'track':self.dev_tasks[self.dev_step],'metadata':metadata,'prefix_wav':str(prefix),'transfer8_s':None,'source':'physical_phone_development','initial_result':message['result']}
            self.dev_results.append(row);self.run.event('phone_development_recorded',trial=self.dev_step+1,job_id=job['id'],wav_sha256=metadata['wav_sha256']);self.dev_step+=1;self.dev_ready();return
        if kind=='telemetry' and self.mode in ('calibration_running','formal_recording'):
            for row in message.get('xyz',[]):self.rows.append(row)
        if kind=='music_started' and self.mode=='formal_recording' and self.active:
            self.active['record_started']=True;self.active['job_id']=message['job']['id']
            if self.active['kind'] in ('positive','outside','noise'):self.deadline=None
            if self.active['kind']=='positive' and not self.active.get('manual_fallback'):self.active['wake_success']=True
        if kind=='music_complete' and self.mode=='formal_recording' and self.active and self.active['kind'] in ('positive','outside','noise'):
            result=message['result'];self.active['result']=result;self.active['job']=message['job']
            self.active['correct']=bool(result.get('matched') and result.get('title')==self.active.get('title') and result.get('artist')==self.active.get('artist')) if self.active['kind']=='positive' else not result.get('matched')
            self.finish_task()
    def finish_task(self):
        self.active['finished_at']=now();self.active['last_status']=dict(self.p.last_status or {});self.active['keys_observed']=self.keys-self.active['key_baseline']
        if self.active['kind'] in ('single','typing','music_only'):
            self.active['false_wakes']=max(0,self.active['last_status'].get('double_seq',0)-self.active['baseline'].get('double_seq',0))
        self.results.append(self.active);write_json(self.run.path/f'trial_{self.step+1:02}.json',self.active)
        if self.rows:write_json(self.run.path/f'trial_{self.step+1:02}_xyz.json',self.rows)
        needs_favourite=self.active['kind']=='positive' and self.active.get('correct') and not self.favourite_check
        song=self.active.get('result',{}).get('song_id');self.active=None;self.step+=1;self.deadline=None
        if needs_favourite:
            self.p.wake.set(False);self.p.enable()
            self.mode='favourite_wait';self.favourite_baseline=(self.p.last_status or {})['center_seq'];self.favourite_song=song
            self.title.set('中键收藏检查：短按两次');self.instruction.set('这首歌已经识别成功。请对板上中键BTNC短按并松开两次，检查收藏是否仍只有一份。')
            self.progress.set('等待板端中键计数。');self.button.configure(text='已按两次，继续下一项',state='normal')
        else:self.task_ready()
        self.save()
    def tick(self):
        if self.deadline:
            left=max(0,self.deadline-time.monotonic());self.progress.set(f'剩余 {left:.1f} 秒')
            if left<=0:
                self.deadline=None
                if self.mode=='calibration_running':self.finish_calibration()
                elif self.mode=='formal_recording' and self.active:
                    if self.active['kind']=='positive' and not self.active['record_started']:
                        self.button.configure(text='双击未唤醒，改用按钮保存此试次',state='normal');self.progress.set('本次双击未成功；不删除试次，点击按钮继续录音。')
                    elif self.active['kind'] in ('single','typing','music_only'):
                        if self.p.busy:self.deadline=time.monotonic()+1
                        else:self.finish_task()
        if self.win.winfo_exists():self.win.after(100,self.tick)
    def complete(self):
        positives=[r for r in self.results if r.get('kind')=='positive'];neg=[r for r in self.results if r.get('kind') in ('outside','noise')]
        summary={'source':'physical_board_with_operator_phone_playback','run_id':self.run.run_id,'recorded_trials':len(self.results),
            'positive_correct':sum(bool(r.get('correct')) for r in positives),'positive_total':len(positives),
            'double_wake_success':sum(bool(r.get('wake_success')) for r in positives),'double_wake_total':len(positives),
            'negative_false_matches':sum(bool(r.get('result',{}).get('matched')) for r in neg),'negative_total':len(neg),
            'false_wakes':{k:sum(r.get('false_wakes',0) for r in self.results if r.get('kind')==k) for k in ('single','typing','music_only')},
            'offline_confirmation':self.offline.get(),'physical_disconnect_skipped_by_user':self.skip_disconnect,'online_physical':'pending_separate_reuse_of_outside_recordings',
            'favourite_check':self.favourite_check,'game':self.game_evidence,'interrupted_attempts':self.attempts,'results':self.results}
        write_json(self.run.path/'result.json',summary);self.mode='finished';self.title.set('本轮检查完成，原始数据已保留')
        self.instruction.set(f'离线正确 {summary["positive_correct"]}/{len(positives)}；双击成功 {summary["double_wake_success"]}/{len(positives)}；库外与噪声误报 {summary["negative_false_matches"]}/{len(neg)}。\n'+('本轮按要求保持联网，物理断网测试未做。' if self.skip_disconnect else '现在可以恢复电脑网络。')+'回到对话回复“完成”；未做成的动作请注明。')
        self.button.configure(text='关闭向导',state='normal');self.progress.set('在线识曲将复用三条真实库外录音，单独核验免费额度，不重复要求放歌。')
        self.run.event('operator_round_finished',summary={k:v for k,v in summary.items() if k!='results'});self.run.manifest();self.save()
