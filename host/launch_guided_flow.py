import os,sys,subprocess,json
from audit import ROOT,Run,write_json

run=Run('guided_flow_launcher')
out=(run.path/'flow_stdout.log').open('wb');err=(run.path/'flow_stderr.log').open('wb')
flags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP
argv=[sys.executable,str(ROOT/'host/guided_flow.py')]
try:
    child=subprocess.Popen(argv,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=out,stderr=err,
                           creationflags=flags|subprocess.CREATE_BREAKAWAY_FROM_JOB)
    mode='detached_and_breakaway'
except OSError as error:
    run.event('breakaway_unavailable',error=repr(error))
    child=subprocess.Popen(argv,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=out,stderr=err,creationflags=flags)
    mode='detached'
record={'pid':child.pid,'launcher_run_id':run.run_id,'stdout':str((run.path/'flow_stdout.log').relative_to(ROOT)),
        'stderr':str((run.path/'flow_stderr.log').relative_to(ROOT)),'mode':mode}
write_json(ROOT/'state/guided_flow_launcher.json',record)
run.event('guided_flow_started',argv=argv,**record);out.close();err.close();run.manifest();print(json.dumps(record))
