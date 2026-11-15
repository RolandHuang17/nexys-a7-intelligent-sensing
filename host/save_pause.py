"""User-requested shutdown checkpoint only; never resumes project work."""
import json
from pathlib import Path
from audit import ROOT,Run,write_json,sha256,now

run=Run('user_pause')
run.event('user_requested_stop',verbatim='我现在电脑马上关机，你先终止，然后保存好节点和进度，方便后面继续跑，必要的话写一个 md，记录，方便后续重新跑项目')
record={'execution_state':'user_paused','time':now(),'resume_only_after_user_instruction':True,
        'checkpoint_document':str(ROOT.parent/'项目暂停与恢复节点.md'),
        'checkpoint_sha256':sha256(ROOT.parent/'项目暂停与恢复节点.md'),
        'last_build':json.loads((ROOT/'state/build/status.json').read_text(encoding='utf8')),
        'last_programming':json.loads((ROOT/'state/active_device.json').read_text(encoding='utf8')),
        'current_xdc_sha256':sha256(ROOT/'constraints/nexys_a7_100t.xdc'),
        'requires_rebuild':True,'reason':'输出datapath_only约束补入显式-from，单独验证通过，但尚未完整重建',
        'first_resume_action':'read checkpoint; run.ps1 build; validate serial output constraints; selftest; physical replay; then guided collection',
        'formal_collection_started':False,'final_deliverables_complete':False,'hardware_disarm':'not_attempted'}
write_json(ROOT/'state/resume.json',record)
try:
    from hardware import hardware_lock
    from program import find_port
    from protocol import Device
    from capture import checked
    with hardware_lock(run),Device(find_port(),run) as device:
        checked(device.request('ARM',bytes((3,0)),timeout=.5,retries=0))
        raw=device.request('STATUS',timeout=.5,retries=0).payload
        (run.path/'final_status_payload.bin').write_bytes(raw)
    record['hardware_disarm']='acknowledged'
except Exception as error:
    record['hardware_disarm']='unavailable';record['disarm_error']=repr(error)
    run.event('pause_disarm_unavailable',error=repr(error))
record['saved']=now();record['pause_run_id']=run.run_id
write_json(ROOT/'state/resume.json',record)
(ROOT/'docs/CONTINUE.md').write_text('# 最新暂停节点\n\n用户于2026-11-13 22:23明确要求停止，电脑即将关机。未获恢复指令前不继续。\n\n**先阅读根目录 `项目暂停与恢复节点.md` 和 `state/resume.json`，这两份取代下列旧接续摘要。**\n\n'+(ROOT/'docs/CONTINUE.md').read_text(encoding='utf8'),encoding='utf8')
run.snapshot('用户关机暂停：保存完整源码、参数、未完成事项与下一步恢复入口')
run.event('execution_paused',checkpoint=str(ROOT.parent/'项目暂停与恢复节点.md'),hardware_disarm=record['hardware_disarm'])
run.manifest();print('PAUSE_SAVED',run.run_id,record['hardware_disarm'])

if __name__=='__main__':pass
