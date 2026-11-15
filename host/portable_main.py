"""Single-file application entry point, including its isolated programmer worker."""
import argparse,json,os,sys,traceback
from app_paths import DATA_ROOT,RESOURCE_ROOT,APP_VERSION,PORTABLE

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--internal-program');p.add_argument('--self-check',action='store_true')
    p.add_argument('--diagnose',action='store_true');p.add_argument('--no-connect',action='store_true')
    p.add_argument('--program',action='store_true');p.add_argument('--serial');p.add_argument('--test-seconds',type=float)
    p.add_argument('--internal-music-worker',action='store_true')
    p.add_argument('--internal-shazam',nargs=2)
    a=p.parse_args();DATA_ROOT.mkdir(parents=True,exist_ok=True)
    if a.internal_shazam:
        from pc_shazam_backend import worker
        worker(*a.internal_shazam);return
    from audit import Run,write_json
    if a.internal_music_worker:
        from music_worker import serve
        serve();return
    if a.internal_program:
        from portable_program import program_board
        r=Run('app_program')
        try:program_board(r,a.internal_program)
        finally:r.manifest()
        return
    if a.self_check or a.diagnose:
        from portable_program import release
        from device_discovery import candidates
        r=Run('app_self_check');m=release()
        import tkinter,numpy,serial,matplotlib.backends.backend_tkagg
        record={'app_version':APP_VERSION,'frozen':bool(getattr(sys,'frozen',False)),
            'resources_verified':True,'firmware':m['firmware'],'data_directory':str(DATA_ROOT),
            'resource_directory':str(RESOURCE_ROOT),'devices':[b.record() for b in candidates()]}
        from music_shazam import ShazamOnlineClient
        online=ShazamOnlineClient().verify();assert online['ok']
        record.update(online_provider='shazamio',online_components=online['versions'])
        write_json(DATA_ROOT/'self_check.json',record);r.event('self_check_passed',**record);r.manifest();print(json.dumps(record,ensure_ascii=False));return
    # A second GUI must not compete for the same UART or the control inbox.
    import msvcrt
    lock=(DATA_ROOT/'application.lock').open('a+b');lock.write(b'0');lock.flush();lock.seek(0)
    try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:
        import tkinter.messagebox
        tkinter.messagebox.showinfo('软件已经运行','已有实时监测窗口正在运行，请切换到原窗口。');return
    from monitor_gui import Dashboard
    app=Dashboard(a.program,not a.no_connect,serial=a.serial)
    if a.test_seconds:app.root.after(int(a.test_seconds*1000),app.close)
    try:app.root.mainloop()
    finally:lock.close()

if __name__=='__main__':
    try:main()
    except Exception:
        DATA_ROOT.mkdir(parents=True,exist_ok=True);error=traceback.format_exc()
        (DATA_ROOT/'startup_error.log').write_text(error,encoding='utf8')
        if not any(x in sys.argv for x in ('--internal-program','--internal-music-worker','--internal-shazam','--self-check','--diagnose')):
            import tkinter.messagebox
            tkinter.messagebox.showerror('软件启动未完成','诊断文件已保存到：'+str(DATA_ROOT/'startup_error.log')+'\n'+error[-900:])
        raise
