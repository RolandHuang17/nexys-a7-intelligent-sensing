"""Acquire fixed open-source tools and attributed demo music, with hashes."""
import json,shutil,sys,zipfile,urllib.request,urllib.parse,re,time
from pathlib import Path
from audit import ROOT,Run,sha256,write_json

COMMIT='cb03ba99feafd41b8874307f0f4e808a6ce34362'
TRACKS=[
 ('Carefree','Kevin MacLeod','library'),('Sneaky Snitch','Kevin MacLeod','library'),('Cipher','Kevin MacLeod','library'),
 ('Signal to Noise','Scott Buckley','library'),('Titan','Scott Buckley','library'),
 ('Fluffing a Duck','Kevin MacLeod','development_negative'),('Wallpaper','Kevin MacLeod','development_negative'),('Investigations','Kevin MacLeod','development_negative'),
 ('Monkeys Spinning Monkeys','Kevin MacLeod','holdout_negative'),('Local Forecast - Elevator','Kevin MacLeod','holdout_negative'),('Chasing Daylight','Scott Buckley','holdout_negative')]
SCOTT={'Signal to Noise':('2020/04/sb_signaltonoise.mp3','signal-to-noise'),
       'Titan':('2018/06/sb_titan.mp3','titan'),'Chasing Daylight':('2021/03/sb_chasingdaylight.mp3','chasing-daylight')}
def fetch(url,path,run,media=False):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and path.stat().st_size>100:return
    import requests
    headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36','Accept':'*/*'}
    for attempt in range(3):
        try:
            response=requests.get(url,headers=headers,timeout=(8,45));response.raise_for_status()
            data=response.content;kind=response.headers.get('Content-Type','');break
        except Exception as error:
            run.event('public_download_retry',url=url,attempt=attempt+1,error=type(error).__name__)
            if attempt==2:raise
            time.sleep(.5)
    if media and ('text/html' in kind or len(data)<10000):raise ValueError('音乐下载未返回完整音频')
    path.write_bytes(data);run.event('public_dependency_downloaded',url=url,path=path.relative_to(ROOT).as_posix(),bytes=len(data),sha256=sha256(path),content_type=kind)
def main():
    run=Run('prepare_music');up=ROOT/'upstream/music';up.mkdir(parents=True,exist_ok=True)
    archive=up/('audfprint-'+COMMIT+'.zip');fetch('https://codeload.github.com/dpwe/audfprint/zip/'+COMMIT,archive,run)
    source=up/'audfprint';source.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            rel=Path(*Path(info.filename).parts[1:])
            if not info.is_dir() and '..' not in rel.parts:
                dest=source/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(z.read(info))
    import imageio_ffmpeg
    ffmpeg=up/'ffmpeg.exe';shutil.copy2(imageio_ffmpeg.get_ffmpeg_exe(),ffmpeg)
    run.command([ffmpeg,'-version'],'记录随软件附带的FFmpeg版本与编译选项',timeout=30)
    fetch('https://ffmpeg.org/releases/ffmpeg-7.1.tar.xz',up/'ffmpeg-7.1-source.tar.xz',run)
    corpus=ROOT/'music_demo';corpus.mkdir(exist_ok=True);rows=[];failures=[]
    for title,artist,group in TRACKS:
        try:
            if artist=='Kevin MacLeod':
                name='Cipher2' if title=='Cipher' else title;url='https://incompetech.com/music/royalty-free/mp3-royaltyfree/'+urllib.parse.quote(name)+'.mp3'
                license_url='https://incompetech.com/music/royalty-free/licenses/'
            else:
                name,slug=SCOTT[title];url='https://www.scottbuckley.com.au/library/wp-content/uploads/'+name
                license_url='https://www.scottbuckley.com.au/library/'+slug+'/'
            path=corpus/group/(title+'.mp3');fetch(url,path,run,True)
            row={'title':title,'artist':artist,'group':group,'file':path.relative_to(ROOT).as_posix(),'sha256':sha256(path),
                 'source_url':url,'license_page':license_url,'license':'CC BY 4.0',
                 'credit':f'"{title}" by {artist}; Licensed under Creative Commons Attribution 4.0; https://creativecommons.org/licenses/by/4.0/ ; '+license_url}
            lp=up/'licenses'/(title+'.html')
            try:fetch(license_url,lp,run)
            except Exception as e:run.event('license_page_fetch_failed',title=title,error=type(e).__name__)
            rows.append(row);print('TRACK',title,path.stat().st_size,flush=True)
        except Exception as error:
            failure={'title':title,'error':str(error)};failures.append(failure);run.event('music_download_failed',**failure);print(failure,flush=True)
    write_json(corpus/'manifest.json',{'source':'author_official_free_attribution_download','tracks':rows,'failures':failures})
    (corpus/'署名与用途.txt').write_text('\n\n'.join(r['credit'] for r in rows)+'\n\n库外曲目不导入识曲库，用于检查误报。请将正式演示所需完整曲目复制到手机本地。',encoding='utf8')
    assets=ROOT/'release_assets/music';assets.mkdir(exist_ok=True);shutil.copytree(source,assets/'audfprint',dirs_exist_ok=True);shutil.copy2(ffmpeg,assets/'ffmpeg.exe')
    write_json(up/'provenance.json',{'audfprint_commit':COMMIT,'archive_sha256':sha256(archive),'ffmpeg_sha256':sha256(ffmpeg),
        'ffmpeg_source_sha256':sha256(up/'ffmpeg-7.1-source.tar.xz'),'tracks':rows,'failures':failures})
    run.status('MUSIC0_dependencies','passed' if not failures else 'failed',f'开源工具与{len(rows)}首作者许可示例音乐，失败{len(failures)}首',
        ['upstream/music/provenance.json','music_demo/manifest.json'],'修复失败下载或开始指纹建库');run.manifest();print(run.run_id)
if __name__=='__main__':main()
