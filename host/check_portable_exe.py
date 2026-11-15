"""Execute only a copied EXE with a clean data directory and no development PATH."""
import json,os,shutil,sys,subprocess,time
from audit import ROOT,Run,sha256,write_json

def main():
    r=Run('portable_isolation_check');copy=ROOT/'.portable_verify/中文 路径';copy.mkdir(parents=True,exist_ok=True)
    source=ROOT/'deliver/软件/开发板实时监测.exe';exe=copy/source.name;shutil.copy2(source,exe)
    data=r.path/'clean_user_data';temp=r.path/'extract_temp';temp.mkdir()
    env={k:v for k,v in os.environ.items() if not k.startswith(('PYTHON','CONDA','VIRTUAL_ENV','RECORDER_'))}
    env.update(PATH=os.path.join(os.environ['SystemRoot'],'System32'),NEXYS_MONITOR_DATA=str(data),TEMP=str(temp),TMP=str(temp))
    rc,_=r.command([exe,'--self-check'],'仅复制单个EXE，在无开发PATH和空数据目录执行资源与依赖自检',cwd=copy,env=env,timeout=90)
    assert rc==0
    result=json.loads((data/'self_check.json').read_text(encoding='utf8'))
    assert result['frozen'] and result['resources_verified']
    expected=json.loads((ROOT/'deliver/软件/软件版本.json').read_text(encoding='utf8'))
    assert sha256(exe)==expected['exe_sha256']
    assert result['data_directory']==str(data) and result['firmware']==expected['firmware']
    assert result['app_version']==expected['app_version']
    record={'source':'packaged_application_test','exe_sha256':sha256(exe),'self_check':result,
            'no_python_or_vivado_in_path':True,'only_exe_copied':True,'clean_data':True,
            'not_a_second_computer_test':True}
    write_json(r.path/'result.json',record);write_json(ROOT/'state/portable_isolation.json',{'run_id':r.run_id,**record})
    r.event('single_exe_isolation_passed',**record);r.manifest();print(r.run_id)

if __name__=='__main__':main()
