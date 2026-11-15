"""Launch the user-visible Tk dashboard without opening an extra terminal window."""
import argparse,json,os,subprocess,sys
from audit import ROOT,Run,write_json

def launch():
    p=argparse.ArgumentParser();p.add_argument('--program',action='store_true');p.add_argument('--no-connect',action='store_true');p.add_argument('--guide',action='store_true');a=p.parse_args()
    run=Run('monitor_launcher');args=[str(ROOT/'.venv/Scripts/pythonw.exe'),str(ROOT/'host/monitor_gui.py')]
    if a.program:args.append('--program')
    if a.no_connect:args.append('--no-connect')
    if a.guide:args.append('--guide')
    with (run.path/'stdout.log').open('wb') as out,(run.path/'stderr.log').open('wb') as err:
        child=subprocess.Popen(args,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=out,stderr=err,
            creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP)
    record={'pid':child.pid,'run_id':run.run_id,'argv':args,'stdout':str((run.path/'stdout.log').relative_to(ROOT)),
            'stderr':str((run.path/'stderr.log').relative_to(ROOT))}
    write_json(ROOT/'state/monitor_launcher.json',record);run.event('gui_launched',**record);run.manifest();print(json.dumps(record,ensure_ascii=False))

if __name__=='__main__':launch()
