"""Exclusive game mode on the existing UART owner; never changes thresholds."""
from capture import checked, status
from music_protocol import music_status


class GameSession:
    def __init__(self, service):
        self.service=service
        self.original=None
        self.active=False

    def emit(self,ready,**values):
        self.service.emit('game_session',ready=ready,**values)

    def control(self,action,arguments,device):
        if action not in ('game_enter','game_exit'):
            return False
        try:
            if action=='game_enter':
                self.enter(device)
            else:
                self.release(device)
        except Exception as error:
            self.service.run_record.event('game_session_failed',action=action,error=repr(error))
            self.emit(False,error=True,text=str(error))
        return True

    def enter(self,device):
        if self.active:
            self.emit(True)
            return
        service=self.service
        if service.music.enabled or service.music.current:
            raise RuntimeError('请先退出听歌识曲，再开始体感游戏。')
        if service.last and service.last['switches']&0x8000:
            raise RuntimeError('请先关闭 SW15 识曲开关，再开始体感游戏。')
        music=music_status(device)
        if music['flags']&1 or music['flags']&8 or music['state']!=0:
            raise RuntimeError('板上还有识曲任务，请先在听歌识曲页面处理并退出。')
        original=status(device)
        self.original=original
        try:
            checked(device.request('ARM',bytes((original['trigger_mode'],0))))
            readback=status(device)
            if readback['armed'] or readback['trigger_mode']!=original['trigger_mode']:
                raise RuntimeError('未能暂停自动事件记录，请重试。')
        except Exception:
            self.release(device)
            raise
        self.active=True
        service.fft_job=None
        service.run_record.event('game_session_entered',original=original)
        self.emit(True,text='体感游戏已就绪，退出游戏页后恢复原自动记录状态。')

    def release(self,device):
        original=self.original
        self.original=None
        self.active=False
        if original is None:
            self.emit(False,restored=True)
            return
        try:
            current=status(device)
            if current['build_id']!=original['build_id'] or current['ticks']<original['ticks']:
                raise RuntimeError('开发板已复位，未恢复旧会话的自动记录状态。')
            keys=('audio_threshold','accel_threshold','pair_window_ticks','threshold_id')
            if any(current[key]!=original[key] for key in keys):
                raise RuntimeError('事件配置已经变化，未用旧设置覆盖当前配置。')
            checked(device.request('ARM',bytes((original['trigger_mode'],int(original['armed'])))))
            after=status(device)
            if after['armed']!=original['armed'] or after['trigger_mode']!=original['trigger_mode']:
                raise RuntimeError('自动记录状态恢复后回读不一致。')
            self.service.run_record.event('game_session_released',restored=True,status=after)
            self.emit(False,restored=True)
        except Exception as error:
            self.service.run_record.event('game_session_released',restored=False,error=repr(error))
            self.emit(False,restored=False,text=str(error)+' 请检查监测页自动记录开关。')

    def reset(self):
        had_session=self.original is not None
        self.active=False
        self.original=None
        if had_session:
            self.emit(False,reset=True,text='开发板时间已重置，请重新准备游戏并校准。')
