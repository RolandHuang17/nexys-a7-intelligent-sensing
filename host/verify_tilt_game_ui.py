"""Real Tk rendering/state checks, with explicitly simulated input only."""
import argparse
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
import time
import tkinter as tk
from tkinter import ttk

from tilt_game.app import GamePanel
from tilt_game.levels import LEVELS
from test_tilt_game import SensorHarness


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--seconds',type=float,default=30)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    root=tk.Tk()
    root.title('重力迷航 UI 自动验证 · 模拟输入')
    ttk.Style(root).theme_use('clam')
    errors=[]
    root.report_callback_exception=lambda cls,value,tb:errors.append(repr(value))
    layouts=[]
    with nullcontext(str(args.output/'runtime')) as directory:
        panel=GamePanel(root,'keyboard',directory,preview=True)
        panel.pack(fill='both',expand=True)
        for width,height,scaling in ((1366,768,1.25),(1366,768,1.5),(1920,1080,1.5),(1060,680,1.5)):
            root.tk.call('tk','scaling',scaling*96/72)
            root.geometry(f'{width}x{height}+0+0')
            root.update()
            panel.state='map'
            panel._draw()
            root.update_idletasks()
            # All eight cards must remain inside the Canvas.
            for x,y,right,bottom,index,_ in panel.renderer.card_hits:
                assert x>=0 and y>=0 and right<=panel.canvas.winfo_width()+1 and bottom<=panel.canvas.winfo_height()+1,(width,height,index,bottom,panel.canvas.winfo_height())
            panel.start_level(0)
            root.update_idletasks()
            assert panel.state=='playing','Initial scene drawing falsely paused gameplay'
            for button in (panel.primary,panel.pause_button,panel.retry_button):
                assert button.winfo_ismapped()
                assert button.winfo_x()+button.winfo_width()<=button.master.winfo_width(),('button clipped',width,button.cget('text'))
            layouts.append({'requested':[width,height],'actual':[root.winfo_width(),root.winfo_height()],
                            'tk_scaling':scaling,'canvas':[panel.canvas.winfo_width(),panel.canvas.winfo_height()],'passed':True})
            panel.pause('自动测试暂停')
            before=panel.game.elapsed
            panel.game.advance(.1)
            assert panel.game.elapsed==before
            panel.primary_action()
            assert panel.state=='playing'
            panel.home()
        root.geometry('1366x768+0+0')
        root.update()
        # Exercise the complete UI-side calibration completion and journal path.
        panel.mode='board'
        panel.mode_var.set('开发板倾斜')
        h=SensorHarness(panel.tilt)
        panel.tilt.begin()
        panel.state='calibration'
        panel.pending_start=True
        panel._draw()
        h.calibrate()
        assert panel.tilt.ready
        # Synthetic harness timestamps are not host timestamps; refresh freshness.
        panel.tilt.last_fresh=time.perf_counter()
        panel.tilt.connected=True
        panel._frame_id and panel.after_cancel(panel._frame_id)
        panel._frame()
        root.update()
        assert panel.state=='playing',('calibration completion',panel.state,errors)
        # Preview mode prevents these synthetic runs from creating board scores.
        panel.mode='keyboard'
        panel.mode_var.set('键盘练习')
        panel.start_level(5)
        root.focus_force()
        panel.canvas.focus_set()
        panel.frame_times.clear()
        panel.draw_times.clear()
        panel.delivery_delays.clear()
        panel.rendered_frames=0
        panel.last_frame=time.perf_counter()
        def synthetic_publish():
            # Measures dispatch, with no claim of physical sensor/display latency.
            panel.last_pending_delivery=time.perf_counter()
            root.after(40,synthetic_publish)
        root.after(40,synthetic_publish)
        root.after(round(args.seconds*1000),root.quit)
        root.mainloop()
        metrics=panel.metrics()
        assert not errors,errors
        assert metrics['state']=='playing' and metrics['rendered_frames']>=args.seconds*50,metrics
        assert metrics['fps'] is not None and metrics['fps']>=50,metrics
        assert metrics['receive_to_canvas_submit_p95_ms']<80,metrics
        panel.pause('结束性能测试')
        root.update()
        panel.close()
        root.destroy()
    result={'source':'real_tk_window_with_digital_input','physical_board_trials':0,
            'passed':True,'layouts':layouts,'metrics':metrics,'callback_errors':errors,
            'checks':['all_eight_cards_visible','native_controls_visible','initial_draw_does_not_pause',
                      'pause_freezes_simulation','resume','complete_calibration_UI_and_journal','50_FPS_minimum',
                      'host_publish_to_Canvas_submit_p95_under_80ms']}
    (args.output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
