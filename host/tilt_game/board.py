"""Game-specific lifecycle around the existing, unchanged serial owner."""
import time


def make_service(run, publish, serial=None):
    from monitor_service import MonitorService
    from capture import status, checked
    from music_protocol import music_status

    class GameMonitorService(MonitorService):
        def emit(self, kind, **values):
            if kind == 'status' and not values.get('connected'):
                detail=values.get('text','')
                if any(s in detail for s in ('PermissionError','拒绝访问','locking','Access is denied')):
                    values['text']='开发板被其他程序占用。请先关闭实时监测主程序，再连接游戏。'
            values['received_at']=time.perf_counter()
            super().emit(kind,**values)

        def session(self, device):
            original=status(device)
            music=music_status(device)
            if music['flags'] & 1 or music['state'] != 0 or music['flags'] & 8:
                raise RuntimeError('板上识曲尚未退出或还有未导出的录音；请先在主程序中处理并退出识曲。')
            # ARM changes only armed/mode. SET is deliberately never issued.
            checked(device.request('ARM',bytes((original['trigger_mode'],0))))
            self.emit('game_session',ready=True,original_armed=original['armed'])
            self.run_record.event('game_trigger_suspended',original=original)
            try:
                # Reuse the real MONITOR/PREVIEW decoders, cursors and logging.
                # No event bank is acknowledged or overwritten by the game.
                while not self.stop_event.is_set():
                    if self.seconds and time.perf_counter()-self.start_time >= self.seconds:
                        break
                    self.poll(device)
                    self.stop_event.wait(max(0,.04-(time.perf_counter()-self.last_poll)))
            finally:
                try:
                    current=status(device)
                    keys=('audio_threshold','accel_threshold','pair_window_ticks','threshold_id')
                    if current['build_id'] != original['build_id'] or current['ticks'] < original['ticks']:
                        raise RuntimeError('板子已复位，未恢复旧会话的触发状态')
                    if any(current[k] != original[k] for k in keys):
                        raise RuntimeError('触发配置已改变，未用旧会话覆盖当前配置')
                    checked(device.request('ARM',bytes((original['trigger_mode'],int(original['armed'])))))
                    after=status(device)
                    restored=after['armed']==original['armed'] and after['trigger_mode']==original['trigger_mode']
                    if not restored:
                        raise RuntimeError('触发状态回读不一致')
                    self.run_record.event('game_trigger_restored',passed=True,status=after)
                    self.emit('game_session',ready=False,restored=True)
                except Exception as error:
                    self.run_record.event('game_trigger_restored',passed=False,error=repr(error))
                    self.emit('game_session',ready=False,restored=False,
                              text='未能恢复触发状态：'+str(error)+'。请回主程序检查自动记录开关。')

    return GameMonitorService(run,publish,serial=serial)
