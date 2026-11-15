"""Check the API-only UI flow without adding any physical acceptance evidence."""
import json,tempfile,tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import audit,music_api_wizard
from audit import Run,write_json


def test():
    run=Run('music_api_wizard_test');root=tk.Tk();root.withdraw();calls=[]
    try:
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            panel=SimpleNamespace(win=root,app=SimpleNamespace(connected=True),busy=False,
                policy=tk.StringVar(root),seconds=tk.StringVar(root),wake=tk.BooleanVar(root),stage=tk.StringVar(root),
                policy_changed=lambda:None,record=lambda:calls.append('record'),board=lambda action:calls.append(action))
            with patch.object(audit,'ROOT',folder),patch.object(music_api_wizard,'ROOT',folder):
                wizard=music_api_wizard.ApiAcceptanceWizard(panel)
                assert len(wizard.tasks)==3 and all(t['kind']=='online' for t in wizard.tasks)
                for i,task in enumerate(wizard.tasks):
                    wizard.next();assert panel.policy.get()=='自动' and panel.seconds.get()=='20' and panel.wake.get() is False
                    wizard.receive('music_started',{'job':{'id':str(i)}})
                    wizard.receive('music_complete',{'job':{'id':str(i)},'result':{
                        'matched':True,'source':'audiotag','title':task['title'],'artist':task['artist'],
                        'zero_cost_verified':True,'cost_yuan':0}})
                assert wizard.mode=='finished' and calls==['record','record','record','music_disable']
                result=json.loads((wizard.run.path/'result.json').read_text(encoding='utf8'))
                assert result['online_correct']==3 and result['target_met'] and result['actual_cost_yuan']==0
                assert result['remaining_offline_tests_cancelled_by_user']
                wizard.win.destroy()
        write_json(run.path/'result.json',{'passed':True,'evidence_kind':'local_Tk_with_simulated_recognition_results',
            'real_board_trials':0,'AudioTag_requests':0,'checks':['three_online_only_tasks','20_seconds_auto_mode','no_knock_or_offline_requirement','no_automatic_game','API_source_and_zero_cost_required']})
        run.manifest();print(run.run_id)
    finally:root.destroy()


if __name__=='__main__':test()
