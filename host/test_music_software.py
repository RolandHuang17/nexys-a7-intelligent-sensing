"""Network boundary tests use simulated transport, never a real account/key."""
import json,tempfile,uuid,wave
from pathlib import Path
from audit import ROOT,Run,write_json
from music_store import MusicStore
from music_online import AudioTagClient
from music_worker import recognize_recording

class Fake:
    def __init__(self,stats=None,timeout=False,result='found'):self.calls=[];self.value=stats;self.timeout=timeout;self.result=result
    def post(self,action,key,**values):
        self.calls.append(action)
        if action=='stat':
            if isinstance(self.value,Exception):raise self.value
            return self.value or {'success':True,'current_credit_balance':0,'identification_free_sec_remainder':100,'credits_spent':0}
        if action=='identify':
            if self.timeout:raise TimeoutError('simulated')
            return {'success':True,'token':'SIMULATED-TASK'}
        return {'success':True,'result':self.result,'data':[{'confidence':99,'tracks':[['Example title','Example artist','',2026]]}]}
def test():
    r=Run('test_music_software');rows=[]
    with tempfile.TemporaryDirectory() as tmp:
        base=Path(tmp);wav=base/'recording.wav'
        with wave.open(str(wav),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0'*320000)
        for name,mode,provider,confirmed,fake,expected in [
            ('仅离线','offline',lambda:'SIMULATED-SECRET',True,Fake(),[]),
            ('无Key','auto',lambda:None,True,Fake(),[]),
            ('未确认免费账户','auto',lambda:'SIMULATED-SECRET',False,Fake(),[]),
            ('断网','auto',lambda:'SIMULATED-SECRET',True,Fake(ConnectionError()),['stat']),
            ('额度不足','auto',lambda:'SIMULATED-SECRET',True,Fake({'success':True,'current_credit_balance':0,'identification_free_sec_remainder':9,'credits_spent':0}),['stat']),
            ('额度查询失败','auto',lambda:'SIMULATED-SECRET',True,Fake(ValueError()),['stat']),
            ('免费额度字段缺失','auto',lambda:'SIMULATED-SECRET',True,Fake({'success':True,'current_credit_balance':0,'credits_spent':0}),['stat']),
            ('免费额度非有限数','auto',lambda:'SIMULATED-SECRET',True,Fake({'success':True,'current_credit_balance':0,'identification_free_sec_remainder':float('nan'),'credits_spent':0}),['stat']),
            ('付费余额拒绝','auto',lambda:'SIMULATED-SECRET',True,Fake({'success':True,'current_credit_balance':1,'identification_free_sec_remainder':100,'credits_spent':0}),['stat']),
            ('额度足够','auto',lambda:'SIMULATED-SECRET',True,Fake(),['stat','identify','get_result','stat']),
            ('正常未命中','auto',lambda:'SIMULATED-SECRET',True,Fake(result='not found'),['stat','identify','get_result','stat']),
            ('上传超时','auto',lambda:'SIMULATED-SECRET',True,Fake(timeout=True),['stat','identify'])]:
            store=MusicStore(base/name);client=AudioTagClient(store,fake,provider,confirmed,poll_interval=0,poll_limit=1)
            identifier=uuid.uuid4().hex;result=client.recognize(identifier,wav,mode)
            assert fake.calls==expected,(name,fake.calls)
            if name=='上传超时':
                client.recognize(identifier,wav,mode);assert fake.calls==expected
                AudioTagClient(MusicStore(base/name),fake,provider,confirmed).recognize(identifier,wav,mode);assert fake.calls==expected
            if name=='额度足够':assert result['matched'] and result['cost_yuan']==0
            rows.append({'case':name,'evidence_kind':'simulated_service','calls':fake.calls,'result':result['reason'],'passed':True})
        store=MusicStore(base/'persist');song=None
        for _ in range(2):
            song=store.record_result(uuid.uuid4().hex,{'matched':True,'title':'Same song','artist':'Same artist','source':'local'},'offline',wav,'hash');store.favourite(song)
        restored=MusicStore(base/'persist');assert len(restored.history())==2
        with restored.db() as c:assert c.execute('SELECT count(*) FROM favourites').fetchone()[0]==1
        assert restored.statistics()[0]['count']==2
        assert len(restored.history(source='local',text='Same'))==2
        rows.append({'case':'两条历史一份收藏，重启读取与筛选统计','evidence_kind':'local_software_test','passed':True})
        class Matcher:
            def __init__(self,hit):self.hit=hit;self.paths=[]
            def match(self,path):
                self.paths.append(path)
                return {'matched':self.hit,'source':'local' if self.hit else 'none',**({'title':'Library song','artist':'Library artist'} if self.hit else {})}
        for name,mode,hit,fake,provider,expected,local_runs,source in [
            ('自动且本地有歌仍在线优先','auto',True,Fake(),lambda:'SIMULATED-SECRET',['stat','identify','get_result','stat'],0,'audiotag'),
            ('仅离线本地命中','offline',True,Fake(),lambda:'SIMULATED-SECRET',[],1,'local'),
            ('仅离线且本地未中','offline',False,Fake(),lambda:'SIMULATED-SECRET',[],1,'none'),
            ('自动在线未中回退本地','auto',True,Fake(result='not found'),lambda:'SIMULATED-SECRET',['stat','identify','get_result','stat'],1,'local'),
            ('自动两边未中','auto',False,Fake(result='not found'),lambda:'SIMULATED-SECRET',['stat','identify','get_result','stat'],1,'none'),
            ('自动无Key回退本地','auto',True,Fake(),lambda:None,[],1,'local'),
            ('自动额度不足不上传再查本地','auto',True,Fake({'success':True,'current_credit_balance':0,'identification_free_sec_remainder':9,'credits_spent':0}),lambda:'SIMULATED-SECRET',['stat'],1,'local'),
            ('自动断网不上传再查本地','auto',False,Fake(ConnectionError()),lambda:'SIMULATED-SECRET',['stat'],1,'none'),
            ('自动上传超时不重传再查本地','auto',True,Fake(timeout=True),lambda:'SIMULATED-SECRET',['stat','identify'],1,'local')]:
            isolated=MusicStore(base/name);client=AudioTagClient(isolated,fake,provider,True,poll_interval=0,poll_limit=1);matcher=Matcher(hit)
            result,local=recognize_recording(uuid.uuid4().hex,wav,mode,isolated,matcher,online=client)
            assert fake.calls==expected,(name,fake.calls)
            assert matcher.paths==([wav] if local_runs else []),(name,matcher.paths)
            assert result['source']==source and result['mode']==mode
            assert result['recognition_order']==('online_first' if mode=='auto' else 'offline_only')
            assert len(isolated.history())==1
            rows.append({'case':name,'evidence_kind':'simulated_service_with_real_orchestration','calls':fake.calls,'local_matcher_runs':local_runs,'result_source':source,'one_history_row':True,'passed':True})
    write_json(r.path/'result.json',{'cases':rows,'real_audiotag_requests':0,'cost_yuan':0})
    r.status('MUSIC2_software','passed','在线上传守卫、断网/额度未知/付费拒绝、超时及重启不重传、历史收藏持久化通过',
             [str((r.path/'result.json').relative_to(ROOT))],'继续实板与完整界面验证；模拟不替代真实在线结果');r.manifest();print(r.run_id)
if __name__=='__main__':test()
