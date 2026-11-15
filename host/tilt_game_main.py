"""Independent launcher. Never promotes or modifies the teacher's main app."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import traceback


def main():
    parser=argparse.ArgumentParser(description='重力迷航 · 独立体感闯关游戏')
    parser.add_argument('--keyboard',action='store_true')
    parser.add_argument('--data-dir',type=Path)
    parser.add_argument('--test-seconds',type=float)
    parser.add_argument('--self-check',action='store_true')
    parser.add_argument('--internal-program')
    parser.add_argument('--review-scene',choices=('map','game','pause','win','calibration'))
    parser.add_argument('--level',type=int,default=1,choices=range(1,9))
    args=parser.parse_args()
    data=args.data_dir or Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData/Local')))/'NexysGravityVoyager'
    data.mkdir(parents=True,exist_ok=True)
    # These variables apply to this independent process only, before shared imports.
    os.environ['NEXYS_MONITOR_DATA']=str(data)
    os.environ['NEXYS_PORTABLE_RUNTIME']='1'
    from audit import Run
    if args.internal_program:
        from portable_program import program_board
        run=Run('tilt_game_program')
        try:
            program_board(run,args.internal_program)
        finally:
            run.manifest()
        return
    if args.self_check:
        from tilt_game import VERSION
        from tilt_game.levels import LEVELS
        from app_paths import RESOURCE_ROOT
        from portable_program import release
        import tkinter, PIL, serial, numpy
        manifest=release()
        value={'game_version':VERSION,'levels':len(LEVELS),'resources_verified':True,
               'firmware':manifest['firmware'],'data_directory':str(data),
               'resource_directory':str(RESOURCE_ROOT),'frozen':bool(getattr(sys,'frozen',False))}
        (data/'self_check.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps(value,ensure_ascii=False))
        return
    import msvcrt
    lock=(data/'game.lock').open('a+b')
    if lock.tell()==0:
        lock.write(b'0')
        lock.flush()
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:
        import tkinter.messagebox
        tkinter.messagebox.showinfo('游戏已经运行','已有《重力迷航》窗口，请切换到原窗口。')
        lock.close()
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError,OSError):
        pass
    import tkinter as tk
    from tkinter import ttk, messagebox
    from tilt_game.app import GamePanel
    from tilt_game import TITLE, VERSION
    root=tk.Tk()
    root.title(TITLE+' · 独立试玩版 '+VERSION)
    root.configure(bg='#080f23')
    from PIL import ImageTk
    from tilt_game.render import icon_image
    root._game_icon=ImageTk.PhotoImage(icon_image(64),master=root)
    root.iconphoto(True,root._game_icon)
    ttk.Style(root).theme_use('clam')
    width=min(1400,root.winfo_screenwidth()-70)
    height=min(900,root.winfo_screenheight()-70)
    root.geometry(f'{width}x{height}+30+25')
    root.minsize(min(1060,width),min(680,height))
    inbox=queue.Queue()
    worker=None
    board_run=None
    closing=False
    programming=False
    def connect(serial=None):
        nonlocal worker,board_run
        if programming:
            panel.status.set('正在初始化板子，请稍候。')
            return
        if worker and worker.is_alive():
            panel.status.set('连接线程正在运行。切换板子前请先断开。')
            return
        from tilt_game.board import make_service
        board_run=Run('tilt_game_board')
        board_run.event('game_board_connect',selected_serial=serial)
        worker=make_service(board_run,inbox.put,serial)
        worker.start()
    def disconnect():
        if worker:
            worker.stop_event.set()
    def initialize(serial=None):
        nonlocal programming
        if programming:
            return
        from device_discovery import select_board
        try:
            board=select_board(serial)
        except Exception as error:
            panel.status.set(str(error))
            return
        if not messagebox.askokcancel('初始化 Nexys A7-100T',
            '请确认板子型号为 Nexys A7-100T。\n\n'
            f'设备：{board.serial} / {board.port}\n'
            '即将加载配套程序，会清空板上尚未导出的录音和采样。\n'
            '不会写入永久存储；断电后需要再次初始化。',parent=root):
            return
        programming=True
        disconnect()
        def wait_for_worker():
            if worker and worker.is_alive():
                root.after(100,wait_for_worker)
                return
            panel.status.set('正在初始化开发板，请稍候。')
            def program():
                try:
                    # Refuse to reprogram a board whose UART another app owns.
                    import serial as serial_module
                    with serial_module.Serial(board.port,460800,timeout=.1):
                        pass
                    argv=[sys.executable,'--internal-program',board.serial] if getattr(sys,'frozen',False) else [sys.executable,str(Path(__file__).resolve()),'--internal-program',board.serial]
                    argv += ['--data-dir',str(data)]
                    result=subprocess.run(argv,capture_output=True,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
                    if result.returncode:
                        raise RuntimeError(result.stderr.decode('utf8',errors='replace')[-700:] or '初始化失败，请查看运行日志')
                    inbox.put({'kind':'program_done','serial':board.serial})
                except Exception as error:
                    inbox.put({'kind':'program_error','text':'初始化未完成：'+str(error)})
            threading.Thread(target=program,name='game-programmer',daemon=True).start()
        wait_for_worker()
    panel=GamePanel(root,'keyboard' if args.keyboard else 'board',data/'game',
                    on_connect=connect,on_disconnect=disconnect,on_initialize=initialize,
                    preview=bool(args.review_scene))
    panel.pack(fill='both',expand=True)
    def pump():
        nonlocal programming
        # A pending programming worker must still deliver its completion when
        # the user closes the window; otherwise finish() would wait forever.
        if closing and not programming:
            return
        for _ in range(200):
            try:
                message=inbox.get_nowait()
            except queue.Empty:
                break
            if message['kind']=='program_done':
                programming=False
                panel.status.set('初始化完成，正在重新连接。')
                if not closing:
                    connect(message['serial'])
            elif message['kind']=='program_error':
                programming=False
                panel.status.set(message['text'])
            else:
                panel.feed(message)
        root.after(8,pump)
    def close():
        nonlocal closing
        if closing:
            return
        closing=True
        disconnect()
        panel.pause('游戏正在退出。')
        panel.status.set('正在恢复开发板原触发状态并保存记录…')
        def finish():
            if programming or (worker and worker.is_alive()):
                root.after(100,finish)
                return
            panel.close()
            if board_run:
                board_run.manifest()
            root.destroy()
        finish()
    root.protocol('WM_DELETE_WINDOW',close)
    def review():
        from tilt_game.engine import Game
        from tilt_game.levels import LEVELS
        panel.mode='keyboard'
        panel.mode_var.set('键盘练习')
        panel.selected=args.level-1
        if args.review_scene in ('game','pause','win'):
            panel.game=Game(LEVELS[args.level-1])
            panel.state='playing'
            if args.review_scene=='pause':
                panel.game.paused=True
                panel.state='paused'
                panel.pause_reason='航行已暂停。调整好姿势，准备再次出发。'
            elif args.review_scene=='win':
                panel.game.has_core=True
                panel.game.collected={0,1,2}
                panel.game.won=True
                panel.game.elapsed=42.3
                panel.state='won'
        elif args.review_scene=='calibration':
            panel.mode='board'
            panel.mode_var.set('开发板倾斜')
            panel.tilt.begin()
            panel.state='calibration'
        panel._draw()
        panel.status.set('界面预览 · 不计入任何实板或练习成绩')
    root.after(100,panel.refresh_devices)
    root.after(150,root.deiconify)
    root.after(8,pump)
    if args.review_scene:
        root.after(250,review)
    if args.test_seconds:
        root.after(int(args.test_seconds*1000),close)
    try:
        root.mainloop()
    finally:
        if not panel.closed:
            panel.close()
        lock.close()


if __name__=='__main__':
    try:
        main()
    except Exception:
        error=traceback.format_exc()
        data=Path(os.environ.get('NEXYS_MONITOR_DATA',str(Path.home())))
        data.mkdir(parents=True,exist_ok=True)
        (data/'startup_error.log').write_text(error,encoding='utf8')
        if not any(flag in sys.argv for flag in ('--self-check','--internal-program')):
            import tkinter.messagebox
            tkinter.messagebox.showerror('游戏启动未完成','诊断记录：'+str(data/'startup_error.log')+'\n'+error[-800:])
        raise
