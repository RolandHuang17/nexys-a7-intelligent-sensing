"""Fixed, logged laptop-speaker stimulus with restoration of Windows settings."""
import time,wave,winsound
import numpy as np
from audit import ROOT,sha256

class SpeakerStimulus:
    def __init__(self,run,volume_scalar=.30,duration_s=.4):
        import comtypes
        from pycaw.pycaw import AudioUtilities
        comtypes.CoInitialize();self.comtypes=comtypes;self.utilities=AudioUtilities;self.run=run
        self.endpoint=AudioUtilities.GetSpeakers();self.volume=self.endpoint.EndpointVolume
        self.original_mute=bool(self.volume.GetMute());self.original_volume=self.volume.GetMasterVolumeLevelScalar()
        self.closed=False;self.scalar=volume_scalar;self.frequency=1500;self.duration=float(duration_s)
        if not .1<=self.duration<=3:raise ValueError('测试短音长度必须为0.1至3秒')
        self.path=run.path/f'stimulus_1500Hz_{round(self.duration*1000)}ms.wav'
        t=np.arange(round(self.duration*16000))/16000;envelope=np.minimum(1,np.minimum(t/.01,(self.duration-t)/.01))
        pcm=(16000*np.sin(2*np.pi*self.frequency*t)*envelope).astype('<i2')
        with wave.open(str(self.path),'wb') as f:
            f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(pcm.tobytes())
        self.metadata={'stimulus_kind':'computer_tone','speaker_kind_user_reported':'laptop_builtin_speakers',
            'endpoint_name':self.endpoint.FriendlyName,'endpoint_id':self.endpoint.id,
            'volume_scalar':volume_scalar,'frequency_hz':self.frequency,'duration_s':self.duration,
            'wav_sha256':sha256(self.path),'original_mute':self.original_mute,'original_volume_scalar':self.original_volume,
            'speaker_position':'未精确量测；电脑与板子按用户当前桌面摆放','sound_pressure':'未标定'}
        run.event('speaker_stimulus_prepared',**self.metadata)
        try:
            self.volume.SetMasterVolumeLevelScalar(volume_scalar,None);self.volume.SetMute(0,None)
        except BaseException:
            self.close();raise

    def play(self,event_id=None,anchor=None):
        if self.utilities.GetSpeakers().id!=self.endpoint.id:raise RuntimeError('默认播放端点改变，停止并保留试次')
        winsound.PlaySound(str(self.path),winsound.SND_FILENAME|winsound.SND_ASYNC)
        self.run.event('speaker_stimulus_play_requested',event_id=event_id,anchor_tick=anchor,
                       monotonic=time.monotonic(),wav_sha256=self.metadata['wav_sha256'],endpoint_id=self.endpoint.id)

    def close(self):
        if self.closed:return
        try:
            winsound.PlaySound(None,0)
            self.volume.SetMasterVolumeLevelScalar(self.original_volume,None);self.volume.SetMute(int(self.original_mute),None)
            self.run.event('speaker_settings_restored',muted=bool(self.volume.GetMute()),volume_scalar=self.volume.GetMasterVolumeLevelScalar())
        finally:self.closed=True;self.comtypes.CoUninitialize()

    def __enter__(self):return self
    def __exit__(self,*args):self.close()
