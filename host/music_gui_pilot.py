"""Exercise the actual EXE button workflow with a recorded physical microphone input."""
import json,time,wave,winsound,zlib
from pathlib import Path
from audit import ROOT,Run,write_json,sha256
from monitor_control import control
from music_physical_probe import prepare_playback
from audio_stimulus import SpeakerStimulus

if __name__=='__main__':
 r=Run('music_exe_gui_pilot');track=ROOT/'music_user/Take It Easy.m4a';playback=r.path/'speaker_input.wav'
 prep=prepare_playback(track,60,playback,normalize=True,duration_s=24)
 control('music');control('music_policy',{'policy':'仅离线'});time.sleep(.3)
 old=json.loads((ROOT/'state/music_gui.json').read_text(encoding='utf8')).get('job_id')
 with SpeakerStimulus(r,volume_scalar=.20):
  r.event('music_playback_requested',title='Take It Easy',artist='Eagles',source='official_public_reference',offset_s=60,playback=prep)
  winsound.PlaySound(str(playback),winsound.SND_FILENAME|winsound.SND_ASYNC);time.sleep(.5);control('music_record')
  deadline=time.monotonic()+80
  while time.monotonic()<deadline:
   row=json.loads((ROOT/'state/music_gui.json').read_text(encoding='utf8'))
   if row.get('job_id')!=old and row.get('result') and not row['busy']:break
   time.sleep(.2)
  else:raise TimeoutError('EXE录音识曲未结束')
  winsound.PlaySound(None,0)
 wav=Path(row['wav']);meta=json.loads((wav.parent/'metadata.json').read_text(encoding='utf8'));raw=(wav.parent/'pcm.bin').read_bytes()
 assert meta['samples']==160000 and meta['sample_rate']==8000 and meta['duration_s']==20 and zlib.crc32(raw)==meta['crc32']
 assert meta['last_tick']-meta['first_tick']==159999*12500
 result={'source':'actual_EXE_GUI_and_board_microphone','exe':json.loads((ROOT/'state/portable_build.json').read_text(encoding='utf8')),
  'expected':{'title':'Take It Easy','artist':'Eagles'},'metadata':meta,'display_result':row['result'],'AudioTag_requests':0,
  'matched_correctly':row['result'].get('title')=='Take It Easy' and row['result'].get('artist')=='Eagles'}
 write_json(r.path/'result.json',result);r.status('MUSIC5_gui','passed' if result['matched_correctly'] else 'in_progress',
  '实际EXE按钮到实板20秒完整WAV和离线结果链路' if result['matched_correctly'] else '实际EXE完整录音已校验；本次外放仍未可靠命中，继续手机近距离开发校准',
  [str((r.path/'result.json').relative_to(ROOT))],'集中手机、双击、收藏与游戏验收');r.manifest();print(json.dumps({'run_id':r.run_id,'matched_correctly':result['matched_correctly'],'result':row['result']},ensure_ascii=False))
