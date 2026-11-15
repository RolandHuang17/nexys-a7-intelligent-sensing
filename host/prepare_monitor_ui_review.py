"""Verify pause semantics and prepare an actual, source-linked GUI screenshot review."""
import json,os,subprocess,sys,time
from audit import ROOT,Run,write_json
from monitor_control import control

if __name__=='__main__':
    run=Run('monitor_ui_review');run.snapshot('实时界面最终功能和截图检查，使用真实传感器数据')
    gui=json.loads((ROOT/'state/monitor_gui.json').read_text(encoding='utf8'));assert gui['connected']
    control('show');control('pause');time.sleep(1.1)
    before=json.loads((ROOT/'state/monitor_gui.json').read_text(encoding='utf8'));assert before['paused']
    time.sleep(1.2);after=json.loads((ROOT/'state/monitor_gui.json').read_text(encoding='utf8'))
    assert after['render_count']==before['render_count'] and after['last_board_tick']>before['last_board_tick']
    control('pause');control('snap')
    run.event('gui_pause_verified',before=before,after=after,semantics='画面停止重绘，板端数据继续读取和存盘')
    write_json(run.path/'pause_test.json',{'passed':True,'before':before,'after':after})
    out=(run.path/'sound_stdout.log').open('wb');err=(run.path/'sound_stderr.log').open('wb')
    child=subprocess.Popen([sys.executable,ROOT/'host/monitor_demo_sound.py'],cwd=ROOT,stdin=subprocess.DEVNULL,
        stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
    out.close();err.close()
    write_json(ROOT/'state/monitor_review_pending.json',{'run_id':run.run_id,'gui_run_id':gui['run_id'],
        'sound_pid':child.pid,'source':'actual_application','next_action':'捕获真实窗口并检查历史波形、再完成review.json'})
    run.event('gui_sound_launched',pid=child.pid);run.manifest();print(run.run_id)
