from pycaw.pycaw import AudioUtilities
from audit import ROOT,Run,write_json
from hardware import hardware_lock
from protocol import Device
from capture import snap,export_event,status
from program import find_port
from selftest import stimulus
run=Run('audio_playback_diagnostic');run.snapshot('默认端点静音原因复核与临时解除静音的真实短音采样')
endpoint=AudioUtilities.GetSpeakers();volume=endpoint.EndpointVolume
muted=bool(volume.GetMute());scalar=volume.GetMasterVolumeLevelScalar()
run.event('audio_endpoint_before',device=endpoint.FriendlyName,muted=muted,volume_scalar=scalar)
try:
    volume.SetMute(0,None)
    run.event('audio_mute_temporarily_cleared',volume_scalar=scalar)
    play=stimulus(run)
    with hardware_lock(run),Device(find_port(),run) as device:
        before=status(device);event=snap(device,play)
        result=export_event(device,event,run.path/'physical/tone_unmuted')
        write_json(run.path/'result.json',{'before':before,'event':result,'output_device':endpoint.FriendlyName,'volume_scalar':scalar})
        print(result)
finally:
    volume.SetMute(int(muted),None)
    run.event('audio_endpoint_restored',muted=bool(volume.GetMute()),volume_scalar=volume.GetMasterVolumeLevelScalar())
    run.manifest();print('RUN_ID='+run.run_id)
