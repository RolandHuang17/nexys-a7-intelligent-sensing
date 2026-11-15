"""User-selected official public recordings for a private local fingerprint library."""
import sys,json
from audit import ROOT,Run,write_json,sha256
sys.path.insert(0,str(ROOT/'upstream/music/media_fetcher'))
import yt_dlp

if __name__=='__main__':
 r=Run('selected_music_reference');rows=[];folder=ROOT/'music_user';folder.mkdir(exist_ok=True)
 for title,video in [('Take It Easy','5igDtWadYms'),('Tequila Sunrise','le61bGcXlq0')]:
  path=folder/(title+'.m4a');url='https://www.youtube.com/watch?v='+video
  options={'format':'bestaudio[ext=m4a]/bestaudio','outtmpl':str(folder/(title+'.%(ext)s')),'noplaylist':True,'quiet':True,'no_warnings':True,'retries':0,'socket_timeout':15}
  try:
   with yt_dlp.YoutubeDL(options) as ydl:info=ydl.extract_info(url,download=True);actual=__import__('pathlib').Path(ydl.prepare_filename(info))
   row={'title':title,'artist':'Eagles','file':str(actual),'sha256':sha256(actual),'duration':info.get('duration'),'channel':info.get('channel'),
     'source_url':url,'purpose':'user_selected_private_local_fingerprint','redistribute_audio':False}
   rows.append(row);r.event('selected_official_recording_acquired',**row)
  except Exception as error:
   r.event('selected_recording_unavailable',title=title,error_type=type(error).__name__)
   rows.append({'title':title,'artist':'Eagles','source_url':url,'status':'requires_existing_user_audio_file'})
 write_json(folder/'manifest.json',{'tracks':rows,'audio_not_in_deliverable':True});write_json(r.path/'result.json',{'tracks':rows});r.manifest();print(json.dumps(rows,ensure_ascii=False))
