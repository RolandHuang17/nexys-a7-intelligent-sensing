"""Exercise the actual Tk resume flow without hardware or network requests."""
import json,tempfile,tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import audit,music_wizard,music_online_wizard
from audit import Run,write_json


def test():
    run=Run('test_music_resume')
    root=tk.Tk();root.withdraw()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);run_id='saved_physical_round'
            saved={'mode':'resume_ready','step':5,'active':None,
                'results':[{'trial':i+1,'kind':'online','online_correct':i==3} for i in range(5)],
                'calibration_windows':[{'step':i,'rows':[]} for i in range(11)],
                'tasks':[{'kind':'online'}]*5+[{'kind':'wake','number':1}],
                'favourite_check':{'song_id':'test_song','presses':2,'favourite_rows':1},
                'interrupted_attempts':[{'trial':6,'outcome':'interrupted_not_counted_as_success'}],
                'dev_results':[{'trial':i+1} for i in range(5)]}
            def panel():
                return SimpleNamespace(win=root,app=SimpleNamespace(connected=True),busy=False,
                    policy=tk.StringVar(root),seconds=tk.StringVar(root),wake=tk.BooleanVar(root),
                    policy_changed=lambda:None,enable=lambda:None,
                    store=SimpleNamespace(setting=lambda *args:{}))
            with patch.object(audit,'ROOT',folder),patch.object(music_wizard,'ROOT',folder),patch.object(music_online_wizard,'ROOT',folder):
                write_json(folder/'state/music_wizard.json',{'run_id':run_id})
                checkpoint=folder/'runs'/run_id/'checkpoint.json';write_json(checkpoint,saved)
                wizard=music_online_wizard.OnlineAcceptanceWizard(panel())
                assert '断网' not in wizard.instruction.get()
                assert not any(isinstance(w,tk.Checkbutton) or w.winfo_class()=='TCheckbutton' for w in wizard.win.winfo_children())
                wizard.next()
                assert wizard.mode=='formal_ready' and wizard.step==5
                assert wizard.p.policy.get()=='仅离线' and wizard.p.seconds.get()=='8'
                after=json.loads(checkpoint.read_text(encoding='utf8'))
                for key in ('results','calibration_windows','favourite_check','interrupted_attempts','dev_results'):
                    assert after[key]==saved[key],key
                wizard.win.destroy()
                # A crash during the sixth trial retains that attempt without
                # changing the first five results or turning it into a success.
                saved['active']={'trial':6,'kind':'wake','job_id':'interrupted-job'}
                saved['mode']='formal_recording';saved['game_evidence']={'round_id':'saved-game'}
                write_json(checkpoint,saved)
                wizard=music_online_wizard.OnlineAcceptanceWizard(panel())
                assert wizard.step==5 and wizard.results==saved['results']
                assert len(wizard.attempts)==2 and wizard.attempts[-1]['job_id']=='interrupted-job'
                assert wizard.game_evidence==saved['game_evidence']
                assert json.loads(checkpoint.read_text(encoding='utf8'))['game_evidence']==saved['game_evidence']
                wizard.win.destroy()
                # The separate original offline workflow keeps its own prompt.
                saved['active']=None;write_json(checkpoint,saved)
                wizard=music_wizard.MusicAcceptanceWizard(panel())
                assert '正式离线试次仍需确认电脑断网' in wizard.instruction.get()
                wizard.win.destroy()
        write_json(run.path/'result.json',{'passed':True,'evidence_kind':'local_Tk_resume_integration',
            'checks':['online_resume_without_disconnect_prompt','resume_trial_6_preserves_trial_1_to_5',
                'preserve_calibration_and_development','preserve_favourite_and_interrupted_attempts',
                'save_and_restore_game_evidence','original_offline_confirmation_retained'],
            'physical_trials_added':0,'AudioTag_requests':0})
        run.manifest();print(run.run_id)
    finally:root.destroy()


if __name__=='__main__':test()
