"""Drive this app's documented local control inbox for repeatable review scenes."""
import argparse,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'host'))
from ui_benchmark import control,read_json

p=argparse.ArgumentParser();p.add_argument('--profile',type=Path,default=Path('runs/ui_frozen_review/profile'))
p.add_argument('--theme');p.add_argument('--page');p.add_argument('--width',type=int);p.add_argument('--height',type=int)
p.add_argument('--action');p.add_argument('--arguments',default='{}');a=p.parse_args()
root=a.profile;state=read_json(root/'state/monitor_gui.json');assert state.get('pid'),state
actions=[]
if a.width:actions.append(('resize',{'width':a.width,'height':a.height or 800}))
if a.theme:actions.append(('ui_theme',{'theme':a.theme}))
if a.page:actions.append(('ui_page',{'page':a.page}))
if a.action:actions.append((a.action,json.loads(a.arguments)))
for action,args in actions:
 identifier=control(root,state['run_id'],action,args)
 deadline=time.monotonic()+10
 while read_json(root/'state/monitor_control_result.json').get('id')!=identifier:
  if time.monotonic()>deadline:raise TimeoutError(action)
  time.sleep(.1)
 time.sleep(.25)
print(json.dumps({'run_id':state['run_id'],'scene':actions},ensure_ascii=False))
