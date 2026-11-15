import json,shutil
from audit import ROOT,Run,write_json,now
from music_wizard import fit_taps
from music_store import MusicStore

if __name__=='__main__':
 r=Run('music_tap_refinement');state=json.loads((ROOT/'state/music_wizard.json').read_text(encoding='utf8'));folder=ROOT/'runs'/state['run_id']
 checkpoint=json.loads((folder/'checkpoint.json').read_text(encoding='utf8'));assert not checkpoint['results'] and not checkpoint['tasks']
 previous=folder/'tap_selection.json';shutil.copy2(previous,folder/'tap_selection_original_600ms.json')
 candidates,best=fit_taps(checkpoint['calibration_windows']);assert best['success']>=4 and best['false']==0
 value={'candidates':candidates,'chosen':best,'window_ms':[best['min_ms'],best['max_ms']],'refractory_ms':100,'frozen_before_formal':True,
   'selection_uses_same_11_development_windows':True,'no_extra_operator_sampling':True,'refinement_run_id':r.run_id}
 write_json(previous,value);write_json(r.path/'result.json',value);MusicStore().set_setting('tap_profile',{k:best[k] for k in ('high','low','min_ms','max_ms')})
 write_json(ROOT/'state/music_operator_preferences.json',{'skip_physical_disconnect':True,'user_verbatim':'别的都搞了，离线断网这一步测试就算了，不要这一步','time':now(),
   'still_require_offline_mode_and_zero_AudioTag_requests':True,'do_not_claim_physical_disconnect_test_passed':True})
 r.status('MUSIC3_tap','passed','原11个校准窗按实际敲击间隔选择参数，未使用正式组',[str(previous.relative_to(ROOT))],'保持联网，继续仅离线模式的正式试次')
 print({k:best[k] for k in ('high','low','min_ms','max_ms','success','false')})
