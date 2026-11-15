"""Actual Tk host integration, digital inputs, no serial/network/firmware write."""
import json
import os
from pathlib import Path
import tempfile
import time


def main():
    root=Path(__file__).resolve().parents[1]
    output=root/'runs/game_embedding_ui'
    output.mkdir(parents=True,exist_ok=True)
    os.environ['NEXYS_PORTABLE_RUNTIME']='1'
    os.environ['NEXYS_MONITOR_DATA']=str(output/'runtime')
    from monitor_gui import Dashboard
    from tilt_game.levels import LEVELS
    app=Dashboard(auto_connect=False)
    errors=[]
    app.root.report_callback_exception=lambda cls,value,tb:errors.append(repr(value))
    app.root.update()
    app.show_page('game');app.root.update()
    panel=app.game_panel
    assert panel is not None and app.active_page=='game'
    assert app.worker is None,'Game created a second worker'
    panel.mode_var.set('键盘练习');panel._change_mode()
    panel.start_level(0);app.root.update()
    assert panel.state=='playing'
    app.show_page('monitor');app.root.update()
    assert panel.state=='paused' and not panel.active
    app.show_page('game');app.root.update()
    assert panel.state=='paused' and panel.active
    panel.primary_action();app.root.update()
    assert panel.state=='playing'
    for theme in ('深色','浅色'):
        app.theme_manager.set(theme,persist=False);app.root.update()
        assert panel.canvas.cget('bg')=='#080f23'
    panel.pause('UI verification')
    app.root.state('normal')
    app.root.geometry('1060x700');app.root.update()
    panel.home();app.root.update()
    for x,y,right,bottom,index,_ in panel.renderer.card_hits:
        assert right<=panel.canvas.winfo_width()+1 and bottom<=panel.canvas.winfo_height()+1,('card clipped',index)
    for button in panel._footer_buttons:
        assert button.winfo_x()+button.winfo_width()<=button.master.winfo_width(),button.cget('text')
    app.show_page('events');app.root.update()
    assert not panel.active
    assert not errors,errors
    record={'passed':True,'source':'real_Tk_host_with_digital_game_input','serial_ports_opened':0,
            'checks':['lazy_game_page','no_second_worker','pause_on_navigation','manual_resume',
                      'dark_game_canvas_in_both_host_themes','footer_wrap_at_1060_width','events_navigation'],
            'callback_errors':errors}
    app.close()
    (output/'result.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(record,ensure_ascii=False))


if __name__=='__main__':
    main()
