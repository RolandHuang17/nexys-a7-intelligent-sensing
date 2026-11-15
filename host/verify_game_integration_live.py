"""Real board and actual Dashboard integration; never synthesizes a physical win."""
import json
import os
from pathlib import Path
import threading
import time
import wave


def main():
    root=Path(__file__).resolve().parents[1]
    output=root/'runs/game_integration_live'
    output.mkdir(parents=True,exist_ok=True)
    os.environ['NEXYS_MONITOR_DATA']=str(output/'runtime')
    os.environ['NEXYS_PORTABLE_RUNTIME']='1'
    from monitor_gui import Dashboard
    from audit import sha256
    import tkinter as tk
    app=Dashboard()
    app.root.title('游戏接入实板回归 · 测试窗口')
    errors=[]
    app.root.report_callback_exception=lambda cls,value,tb:errors.append(repr(value))
    result={'source':'real_board_and_actual_Dashboard','physical_game_campaign_repeated':False,
            'firmware_programmed':False,'online_requests':0}

    def wait(predicate,seconds=12):
        deadline=time.perf_counter()+seconds
        while not predicate():
            app.root.update()
            if time.perf_counter()>deadline:
                raise AssertionError('Timed out: '+str({'notice':app.notice.get(),'connected':app.connected,'errors':errors}))
            time.sleep(.002)
        app.root.update_idletasks()

    try:
        wait(lambda:app.connected and app.last_row is not None)
        assert not app.last_row['switches']&0x8000,'Please turn SW15 off before testing the game'
        worker=app.worker
        identity=dict(app.device_identity)
        original=dict(worker.trigger_settings)
        mode,armed=app.last_row['mode'],app.last_row['armed']
        app.show_page('game')
        panel=app.game_panel
        panel.preview=True  # No test scenario can write a board/practice score.
        panel.primary_action()
        wait(lambda:worker.game.active and panel.lease_ready)
        wait(lambda:panel.tilt.phase=='right',seconds=8)
        result['real_neutral_calibration_stage']=panel.tilt.phase
        result['xyz_from_shared_worker']=panel.tilt.received
        assert sum(t.name=='board-monitor' for t in threading.enumerate())==1
        app.show_page('monitor')
        wait(lambda:not worker.game.active and app.last_row['armed']==armed and app.last_row['mode']==mode)
        def released():
            rows=[json.loads(line) for line in (app.run.path/'actions.jsonl').read_text(encoding='utf8').splitlines()]
            return any(row['kind']=='game_session_released' for row in rows)
        wait(released)
        assert worker.trigger_settings==original
        actions=[json.loads(line) for line in (app.run.path/'actions.jsonl').read_text(encoding='utf8').splitlines()]
        restored=next(row for row in reversed(actions) if row['kind']=='game_session_released')
        assert restored['restored']
        for key,value in original.items():
            assert restored['status'][key]==value,key
        result['exact_trigger_configuration_restore']=True
        app.open_music()
        app.action('music_enable',seconds=8,wake=True,policy='offline')
        wait(lambda:worker.music.enabled)
        app.show_page('game')
        panel.primary_action()
        wait(lambda:panel.pending is None and not panel.requested)
        assert not panel.lease_ready and not worker.game.active and worker.music.enabled
        assert '请先退出' in panel.status.get(),panel.status.get()
        result['music_mode_blocks_real_game_entry']=True
        app.open_music()
        app.action('music_disable')
        wait(lambda:not worker.music.enabled)
        app.show_page('monitor')
        previous=set(app.event_paths)
        app.action('snap')
        wait(lambda:bool(set(app.event_paths)-previous),seconds=12)
        item=next(iter(set(app.event_paths)-previous))
        event=app.event_paths[item]
        metadata=json.loads((event/'metadata.json').read_text(encoding='utf8'))
        assert metadata['pcm_count']==24000 and metadata['xyz_count']>200
        assert sha256(event/'payload.bin')==metadata['input_hash']
        with wave.open(str(event/'audio.wav'),'rb') as wav:
            assert wav.getnframes()==24000 and wav.getframerate()==16000
        app.events.selection_set(item)
        app.view_event();app.root.update()
        popups=[child for child in app.root.winfo_children() if isinstance(child,tk.Toplevel)]
        assert popups,'Saved waveform dialog did not open'
        for popup in popups:popup.destroy()
        app.play()
        result['full_event']={'directory':str(event),'pcm_count':metadata['pcm_count'],
                              'xyz_count':metadata['xyz_count'],'payload_sha256':metadata['input_hash'],
                              'WAV_playback_API_returned':True,'waveform_dialog_opened':True}
        # Test frame scheduling with actual UART/display traffic; control is keyboard.
        app.show_page('game')
        panel.mode_var.set('键盘练习');panel._change_mode()
        panel.start_level(0)
        panel.frame_times.clear();panel.draw_times.clear();panel.delivery_delays.clear();panel.rendered_frames=0
        panel.last_frame=time.perf_counter()
        app.root.focus_force();panel.canvas.focus_set()
        app.root.after(10000,app.root.quit)
        app.root.mainloop()
        performance=panel.metrics()
        assert performance['fps']>=50,performance
        assert performance['rendered_frames']>=500,performance
        assert performance['receive_to_canvas_submit_p95_ms']<80,performance
        result['performance_with_live_board']=performance
        app.show_page('monitor')
        assert app.worker is worker and app.connected
        assert not worker.stats['connection_errors'],worker.stats['connection_errors']
        assert worker.panel.synced and not worker.panel.disabled
        result.update(passed=True,device=identity,board_monitor_threads=1,shared_worker_preserved=True,
                      panel_display_synced=True,callback_errors=errors,run_directory=str(app.run.path))
        assert not errors,errors
    except Exception as error:
        result.update(passed=False,error=repr(error),callback_errors=errors)
        raise
    finally:
        app.close()
        deadline=time.perf_counter()+15
        while app.worker and app.worker.is_alive() and time.perf_counter()<deadline:
            app.root.update();time.sleep(.01)
        for _ in range(20):
            try:app.root.update()
            except tk.TclError:break
            time.sleep(.01)
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
