"""Observe real USB absence/reappearance without changing any driver."""
import json,os,time
from pathlib import Path
from audit import ROOT,Run,write_json,now
from device_discovery import candidates

def main():
    r=Run('portable_hotplug');data=Path(os.environ['LOCALAPPDATA'])/'NexysMonitor';end=time.monotonic()+150
    missing=None;returned=None;stale=False;rows=[]
    while time.monotonic()<end:
        boards=[b.record() for b in candidates()]
        try:gui=json.loads((data/'state/monitor_gui.json').read_text(encoding='utf8'))
        except (OSError,ValueError):gui={}
        row={'time':now(),'devices':boards,'gui':gui};rows.append(row)
        with (r.path/'trace.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
        if not boards and missing is None:missing=now();r.event('usb_absence_observed')
        if missing and (gui.get('last_receive_age_s') or 0)>1.5:stale=True
        if missing and boards and returned is None:returned=now();r.event('usb_reappearance_observed',devices=boards)
        if returned and len(rows)>3 and all(x['devices'] for x in rows[-3:]):break
        time.sleep(.5)
    result={'run_id':r.run_id,'real_usb_absence':missing,'real_usb_return':returned,'stale_state_observed':stale,
            'trace_rows':len(rows),'after_return_needs_firmware_check':True}
    write_json(r.path/'result.json',result);write_json(ROOT/'state/portable_hotplug_result.json',result)
    r.event('hotplug_observation_finished',**result);r.manifest();print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
