"""Brief logged physical tone for a live GUI check; restore the original audio settings."""
import os,time
from audit import ROOT,Run,write_json
from audio_stimulus import SpeakerStimulus

if __name__=='__main__':
    run=Run('monitor_gui_sound')
    try:
        with SpeakerStimulus(run,duration_s=2.8) as sound:
            sound.play()
            write_json(ROOT/'state/monitor_stimulus.json',{'pid':os.getpid(),'run_id':run.run_id,'state':'playing','metadata':sound.metadata})
            time.sleep(2.9)
    finally:
        write_json(ROOT/'state/monitor_stimulus.json',{'pid':None,'run_id':run.run_id,'state':'finished'})
        run.manifest()
