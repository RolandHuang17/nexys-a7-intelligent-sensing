"""Purpose-built local dashboard control, with a matching request receipt."""
import argparse,json,time,uuid
from audit import ROOT,write_json

def control(action,arguments=None):
    gui=json.loads((ROOT/'state/monitor_gui.json').read_text(encoding='utf8'))
    request={'id':uuid.uuid4().hex,'target_run_id':gui['run_id'],'action':action,'arguments':arguments or {}}
    write_json(ROOT/'state/monitor_control.json',request)
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        path=ROOT/'state/monitor_control_result.json'
        if path.exists():
            result=json.loads(path.read_text(encoding='utf8'))
            if result['id']==request['id']:return result
        time.sleep(.05)
    raise TimeoutError('界面未确认本机控制请求')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['show','dismiss_guide','guide','pause','snap','arm','mark','close','music','music_record','music_verify','music_demo','music_game','music_reveal','music_policy','music_favourite','music_enable','music_disable','music_wizard']);p.add_argument('--arguments',default='{}');a=p.parse_args()
    print(json.dumps(control(a.action,json.loads(a.arguments)),ensure_ascii=False))
