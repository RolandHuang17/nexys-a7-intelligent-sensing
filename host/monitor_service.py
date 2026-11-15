"""Single-owner serial worker shared by the GUI and physical acceptance checks."""
import json,queue,struct,threading,time,traceback,sys
from contextlib import ExitStack
import numpy as np
from audit import ROOT,write_json,now
from hardware import hardware_lock
from program import find_port,program_latest
from protocol import Device
from capture import status,checked,list_events,export_event
from monitor_protocol import monitor_packet,preview_packet,begin_audio,read_audio,spectrum,SequenceCursor
from app_paths import PORTABLE,RESOURCE_ROOT,app_command
from device_discovery import select_board

class MonitorService(threading.Thread):
    def __init__(self,run,publish,*,program=False,seconds=None,serial=None):
        super().__init__(name='board-monitor',daemon=True)
        self.run_record=run;self.publish=publish;self.program=program;self.seconds=seconds
        self.stop_event=threading.Event();self.commands=queue.Queue();self.cancel_commands=queue.Queue();self.last=None;self.epoch=0
        self.xyz_cursor=SequenceCursor();self.audio_cursor=SequenceCursor()
        self.stats={'source':'physical_board','polls':0,'resets':0,'switches_seen_high':0,'switches_seen_low':0,
                    'buttons_pressed_mask':0,'buttons_released_mask':0,'exported_events':[],'connection_errors':[]}
        self.poll_intervals=[];self.last_poll=0;self.last_stats=0;self.last_flush=0
        self.start_time=time.monotonic();self.programming=None;self.streams={};self.press_base=None;self.release_base=None
        self.next_fft=0;self.fft_job=None;self.exporting=False
        self.config_id=1;self.trigger_settings=None
        self.selected_serial=serial;self.identity=None
        from music_board import MusicBoard
        from panel_control import PanelDisplay
        self.panel_commands=queue.Queue();self.panel=PanelDisplay(run,self.emit,state_path=ROOT/'state/panel_display.json')
        self.music=MusicBoard(self)
        from game_session import GameSession
        self.game=GameSession(self)

    def send(self,action,**values):
        if action=='music_cancel':self.cancel_commands.put(values)
        elif action=='panel_update':self.panel_commands.put(values)
        else:self.commands.put((action,values))
    def cancel_hook(self,d):
        # Export owns UART synchronously, so cancellation has its own small queue
        # which is also serviced between PCM blocks on this same owner thread.
        for _ in range(16):
            try:values=self.cancel_commands.get_nowait()
            except queue.Empty:break
            try:self.music.cancel(d,values['job_id'])
            except Exception as error:
                self.run_record.event('music_cancel_failed',job_id=values.get('job_id'),error=repr(error))
                self.emit('music_cancel_failed',job_id=values.get('job_id'),text='中止未完成：'+str(error))
    def panel_hook(self,d):
        # A separate display queue keeps export-time projection updates bounded;
        # business commands retain their original FIFO and non-reentrant owner.
        for _ in range(100):
            try:values=self.panel_commands.get_nowait()
            except queue.Empty:break
            try:
                job=values.pop('bind_job',None)
                if job is not None:
                    current=self.music.current
                    if current is not None and (job['id']!=current['id'] or current.get('record_id')!=self.panel.record_id):continue
                    job={**job,'record_id':self.panel.record_id}
                    self.panel.bind_job(job)
                self.panel.update(**values)
            except (ValueError,TypeError,KeyError) as error:self.run_record.event('panel_projection_ignored',error=repr(error))
        self.panel.poll(d)
    def reset_panel(self,d):
        # A board reset can leave UART open while record_id goes back to zero.
        # Refresh display context only; the original music recovery remains at reconnect.
        from music_protocol import music_status
        from panel_protocol import Phase
        self.panel.reconnected()
        try:
            row=music_status(d);self.music.last=row;self.panel.record_id=row['record_id']
            job=self.music.current
            if job and job['record_id']==row['record_id'] and row['flags']&8:
                self.panel.bind_job(job)
                if self.music.stage=='matching':self.panel.update(Phase.MATCH,job_id=job['id'])
                elif self.music.stage=='transferring':self.panel.update(Phase.TRANSFER,job_id=job['id'])
                elif self.music.stage=='result' and job.get('game'):self.panel.update(Phase.GAME_READY,job_id=job['id'])
        except Exception as error:
            self.panel.disabled=True
            self.run_record.event('panel_context_refresh_failed',error=repr(error))
            self.emit('panel_status',text='板端显示暂不可用，监测继续；重连后重试')

    def emit(self,kind,**values):
        if kind=='data':values['received_at']=time.perf_counter()
        self.publish({'kind':kind,**values})
    def log(self,name,value):
        if name not in self.streams:self.streams[name]=(self.run_record.path/name).open('a',encoding='utf8')
        self.streams[name].write(json.dumps(value,ensure_ascii=False,separators=(',',':'))+'\n')

    def run(self):
        run=self.run_record
        try:
            while not self.stop_event.is_set():
                if self.seconds and time.monotonic()-self.start_time>=self.seconds:break
                try:
                    board=select_board(self.selected_serial)
                    if self.selected_serial is None:self.selected_serial=board.serial
                    if self.program:
                        self.emit('status',text='正在下载已通过时序检查的固件…',connected=False)
                        rc,_=run.command(app_command('--internal-program',board.serial) if PORTABLE else
                            [sys.executable,ROOT/'host/program_monitor.py'],
                            '独立进程下载位流并等待USB链路稳定',timeout=150)
                        if rc:raise RuntimeError('位流下载未完成，见编程日志')
                        self.programming=json.loads((ROOT/'state/active_device.json').read_text(encoding='utf8'));self.program=False
                    port=board.port
                    with hardware_lock(run),Device(port,run,audit_responses=False) as d:
                        hello=status(d)
                        if PORTABLE:
                            from portable_program import release
                            fw=release()['firmware'];build_id=fw['build_id'];build={'run_id':fw['build_run_id'],**fw}
                        else:
                            build=json.loads((ROOT/'state/build/status.json').read_text(encoding='utf8'))
                            build_id=json.loads((ROOT/'runs'/build['run_id']/'build_inputs.json').read_text(encoding='utf8'))['build_id']
                        if hello['build_id']!=build_id:
                            raise RuntimeError('板上程序与软件不匹配，请确认板型后点“初始化此板”')
                        identity={'usb_serial':board.serial,'port':port,'build_id':build_id}
                        if identity!=self.identity:
                            self.epoch+=1;self.last=None;self.xyz_cursor=SequenceCursor();self.audio_cursor=SequenceCursor()
                            self.emit('reset',epoch=self.epoch);self.identity=identity
                        if self.programming is None:
                            self.programming={'build_run_id':build['run_id'],'build_id':build_id,
                                'bitstream_sha256':build['bitstream_sha256'],'config_sha256':build['config_sha256']}
                        self.programming={**self.programming,'usb_serial':board.serial,'uart_port':port}
                        run.event('monitor_connected',port=port,device=identity,programming=self.programming)
                        self.stats['device']=identity;self.emit('identity',device=identity)
                        self.trigger_settings={k:hello[k] for k in ('audio_threshold','accel_threshold','pair_window_ticks','threshold_id')}
                        self.config_id=max(self.config_id,hello['threshold_id'])
                        self.emit('status',text=f'已连接 {port} · 程序 {build_id} · 所有数据来自实板',connected=True)
                        self.fft_job=None;self.last_poll=0;self.next_fft=0
                        self.reset_panel(d)
                        self.music.reconnected(d)
                        try:self.session(d)
                        finally:self.game.release(d)
                except Exception as error:
                    record={'time':now(),'error':repr(error)};self.stats['connection_errors'].append(record)
                    run.event('monitor_connection_error',**record);self.log('errors.jsonl',{**record,'traceback':traceback.format_exc()})
                    self.emit('status',text='连接中断或设备未就绪：'+str(error),connected=False)
                    self.stop_event.wait(2)
        finally:
            self.summary()
            for f in self.streams.values():f.flush();f.close()
            self.emit('stopped',text='采集已停止；原始包和记录已保存')
            run.event('monitor_stopped',elapsed_s=time.monotonic()-self.start_time,stats=self.stats)
            run.manifest()

    def poll(self,d,force=False):
        self.cancel_hook(d)
        self.panel_hook(d)
        if not force and time.monotonic()-self.last_poll<.04:return
        started=time.monotonic()
        row=monitor_packet(d.request('MONITOR',timeout=1));preview=preview_packet(d.request('PREVIEW',timeout=1))
        if self.last and row['tick']<self.last['tick']:
            self.epoch+=1;self.stats['resets']+=1;self.xyz_cursor=SequenceCursor();self.audio_cursor=SequenceCursor()
            self.press_base=None;self.release_base=None
            self.run_record.event('board_reset_observed',new_tick=row['tick'],previous_tick=self.last['tick'],epoch=self.epoch)
            self.emit('reset',epoch=self.epoch)
            if getattr(self,'game',None):self.game.reset()
            self.reset_panel(d)
        fresh_xyz=self.xyz_cursor.accept(row['xyz_records']);fresh_audio=self.audio_cursor.accept(preview['points'])
        if self.last_poll:self.poll_intervals.append(started-self.last_poll)
        self.last_poll=started;self.last=row;self.stats['polls']+=1
        self.stats['switches_seen_high']|=row['switches'];self.stats['switches_seen_low']|=(~row['switches'])&65535
        if self.press_base is None:self.press_base=row['presses'];self.release_base=row['releases']
        for i in range(5):
            if row['presses'][i]>self.press_base[i]:self.stats['buttons_pressed_mask']|=1<<i
            if row['releases'][i]>self.release_base[i]:self.stats['buttons_released_mask']|=1<<i
        self.log('monitor.jsonl',{'host_time':now(),'host_monotonic':started,'epoch':self.epoch,'device':self.identity,**row})
        self.log('preview.jsonl',{'host_time':now(),'epoch':self.epoch,'first_seq':preview['first_seq'],
            'last_bin_end_tick':preview['last_bin_end_tick'],'points':[[p['seq'],p['tick'],p['low'],p['high']] for p in fresh_audio]})
        self.emit('data',row=row,audio=fresh_audio,xyz=fresh_xyz,epoch=self.epoch,
            missing_audio=self.audio_cursor.missing,missing_xyz=self.xyz_cursor.missing)
        if started-self.last_flush>=1:
            for f in self.streams.values():f.flush()
            self.last_flush=started
        if started-self.last_stats>=1:
            self.last_stats=started
            self.run_record.event('telemetry_progress',polls=self.stats['polls'],board_tick=row['tick'],epoch=self.epoch,
                preview_missing_bins=self.audio_cursor.missing,xyz_missing_preview_samples=self.xyz_cursor.missing,
                uart_crc_errors=d.decoder.crc_errors,retries=d.retries)
            self.summary()

    def summary(self):
        value={**self.stats,'programming':self.programming,'epoch':self.epoch,'last':self.last,
            'preview_missing_bins':self.audio_cursor.missing,'xyz_missing_preview_samples':self.xyz_cursor.missing,
            'duration_s':time.monotonic()-self.start_time,'poll_intervals_s':{
                'median':float(np.median(self.poll_intervals)) if self.poll_intervals else None,
                'p99':float(np.percentile(self.poll_intervals,99)) if self.poll_intervals else None}}
        write_json(self.run_record.path/'session_summary.json',value)

    def controls(self,d):
        try:action,args=self.commands.get_nowait()
        except queue.Empty:return
        self.run_record.event('monitor_action',action=action,parameters=args,board_tick=self.last['tick'] if self.last else None)
        try:
            game=getattr(self,'game',None)
            if game and game.control(action,args,d):return
            if game and game.active and (action in ('snap','arm') or action in ('music_enable','music_start')):
                raise RuntimeError('请先离开体感游戏页面，再操作事件记录或听歌识曲。')
            if self.music.enabled and action in ('snap','arm'):raise RuntimeError('请先退出识曲，再使用1.5秒事件和原自动触发。')
            if self.music.control(action,args,d):pass
            elif action=='snap':
                p=checked(d.request('SNAP',retries=0));identifier,anchor=struct.unpack_from('<IQ',p,1)
                self.emit('notice',text=f'事件 {identifier} 正在记录后一秒…')
                self.run_record.event('snap_anchor',event_id=identifier,anchor_tick=anchor)
            elif action=='arm':
                mode=int(args.get('mode',3));enabled=bool(args.get('enabled',True))
                if enabled:
                    audio=int(args.get('audio',13));accel=int(args.get('accel',39));window=int(args.get('window',50))
                    if min(audio,accel,window)<1 or window>80:raise ValueError('阈值必须大于零，配对间隔为1至80毫秒')
                    checked(d.request('ARM',bytes((mode,0))))
                    self.config_id+=1
                    checked(d.request('SET',struct.pack('<IIII',audio,accel,window*100000,self.config_id)))
                    self.trigger_settings={'audio_threshold':audio,'accel_threshold':accel,'pair_window_ticks':window*100000,'threshold_id':self.config_id}
                checked(d.request('ARM',bytes((mode,int(enabled)))))
                self.emit('notice',text='自动记录已启用' if enabled else '自动记录已暂停')
            elif action=='mark':
                self.log('observations.jsonl',{'time':now(),'tick':self.last['tick'] if self.last else None,**args})
                self.emit('notice',text='已保存操作标记：'+str(args.get('text','')))
        except Exception as error:
            self.run_record.event('monitor_action_failed',action=action,error=repr(error))
            self.emit('notice',text='操作未完成：'+str(error))

    def fft_step(self,d):
        now_mono=time.monotonic()
        if self.fft_job is None:
            if now_mono<self.next_fft:return
            meta=begin_audio(d);self.fft_job={'meta':meta,'pcm':[]};return
        job=self.fft_job;offset=len(job['pcm']);meta=job['meta']
        chunk=read_audio(d,meta['snapshot_id'],offset,min(240,512-offset));job['pcm'].extend(chunk['pcm'].tolist())
        if len(job['pcm'])==512:
            values=np.asarray(job['pcm'],dtype='<i2');hz,dbfs,peak=spectrum(values)
            target=self.run_record.path/'audio_snapshots';target.mkdir(exist_ok=True)
            filename=f'e{self.epoch}_snapshot_{meta["snapshot_id"]:08}.npz'
            np.savez_compressed(target/filename,pcm=values,first_tick=meta['first_tick'],first_index=meta['first_index'],sample_rate=16000)
            self.log('spectra.jsonl',{'epoch':self.epoch,'snapshot_id':meta['snapshot_id'],'first_tick':meta['first_tick'],
                'first_index':meta['first_index'],'dominant_hz':peak,'file':'audio_snapshots/'+filename})
            self.emit('spectrum',hz=hz.tolist(),dbfs=dbfs.tolist(),peak=peak,first_tick=meta['first_tick'])
            self.fft_job=None;self.next_fft=now_mono+1

    def session(self,d):
        next_list=0
        while not self.stop_event.is_set():
            if self.seconds and time.monotonic()-self.start_time>=self.seconds:break
            self.poll(d);self.music.step(d);self.controls(d)
            if not self.game.active and not self.music.enabled and time.monotonic()>=next_list:
                events=list_events(d);next_list=time.monotonic()+.5
                if events:
                    event=events[0];self.exporting=True;self.fft_job=None
                    self.emit('notice',text=f'正在导出事件 {event["event_id"]}，曲线继续更新…')
                    def during_export(offset):
                        if self.stop_event.is_set():raise InterruptedError('界面关闭，冻结事件保留在板上')
                        self.poll(d)
                    directory=self.run_record.path/'physical'/f'e{self.epoch}_event{event["event_id"]}'
                    # Failed attempts retain their directory and UART bytes; retries get a distinct path.
                    attempt=0;target=directory
                    while target.exists():attempt+=1;target=directory.with_name(directory.name+f'_retry{attempt}')
                    saved=export_event(d,event,target,source='board_live' if event['mode'] else 'board_snap',on_block=during_export)
                    saved.update(programming=self.programming,monitor_run_id=self.run_record.run_id,epoch=self.epoch,trigger_settings=self.trigger_settings)
                    write_json(target/'metadata.json',saved)
                    self.stats['exported_events'].append({'event_id':saved['event_id'],'mode':saved['mode'],
                        'input_hash':saved['input_hash'],'directory':target.relative_to(ROOT).as_posix()})
                    self.emit('event',event=saved,directory=str(target));self.exporting=False;next_list=time.monotonic()+.3
            if not self.game.active and not self.stop_event.is_set() and self.music.stage not in ('recording','transferring'):self.fft_step(d)
            self.stop_event.wait(max(0,.04-(time.monotonic()-self.last_poll)))
        try:self.music.disable(d)
        except Exception:pass
