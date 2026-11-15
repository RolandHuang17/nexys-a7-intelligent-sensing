"""Read-only free-account check. Credentials never pass through argv or logs."""
import json,os,shutil
from pathlib import Path
from audit import ROOT,Run,write_json
from music_online import AudioTagClient

if __name__=='__main__':
    r=Run('music_free_account_check')
    attestation=ROOT/'state/music_account_attestation.json'
    if attestation.exists():
        dest=Path(os.environ['LOCALAPPDATA'])/'NexysMonitor/state/music_account_attestation.json'
        dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(attestation,dest)
    result=AudioTagClient(audit=r.event).verify()
    write_json(r.path/'result.json',result)
    r.status('MUSIC4_account','passed' if result.get('ok') else 'pending',
        '只查询stat，未提交录音；免费账户守卫通过' if result.get('ok') else '免费账户尚未通过守卫',
        [str((r.path/'result.json').relative_to(ROOT))],'正式库外录音准备后提交一次并核对费用')
    print(json.dumps({'run_id':r.run_id,**result},ensure_ascii=False))
