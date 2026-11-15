import hashlib,json,shutil
from audit import ROOT,Run,sha256,write_json
from hardware import vivado


def build(max_samples=160000):
    stage='build' if max_samples==160000 else 'MUSIC1_resource8'
    run=Run("build" if max_samples==160000 else 'build_music8')
    sources=sorted((ROOT/"rtl").glob("*.sv"))+[p for p in sorted((ROOT/'rtl').glob('*.svh')) if p.name!='build_id.svh']+sorted((ROOT/"constraints").glob("*.xdc"))
    manifest=[{"path":p.relative_to(ROOT).as_posix(),"sha256":sha256(p)} for p in sources]
    parameters={'MUSIC_MAX_SAMPLES':max_samples}
    digest=hashlib.sha256(json.dumps({'files':manifest,'parameters':parameters},sort_keys=True).encode()).hexdigest()
    (ROOT/"rtl/build_id.svh").write_text(f"`define RECORDER_BUILD_ID 32'h{digest[:8]}\n",encoding="ascii")
    frozen=run.path/'input_source'
    for folder in ('rtl','constraints','scripts'):shutil.copytree(ROOT/folder,frozen/folder)
    for item in manifest:assert sha256(frozen/item['path'])==item['sha256']
    write_json(run.path/"build_inputs.json",{"logic_sha256":digest,"build_id":digest[:8],"files":manifest,'parameters':parameters})
    run.event("build_identifier_generated",logic_sha256=digest,build_id=digest[:8])
    run.snapshot("A1 综合与布线输入，构建号由逻辑和约束摘要生成")
    output=run.path/"implementation"
    rc,text=vivado(run,"build.tcl",[frozen,output,max_samples],"从不可变输入副本综合、BRAM推断、布局布线、100MHz时序及位流生成",timeout=1800)
    bit=output/"recorder_top.bit"
    passed=rc==0 and "BUILD_PASSED" in text and "SERIAL_OUTPUT_CHECKS_PASSED" in text and "CRITICAL WARNING:" not in text and bit.exists()
    run.status(stage,"passed" if passed else "failed","实现与时序门槛通过" if passed else "实现失败，见完整编译日志",
               [(run.path/"build_inputs.json").relative_to(ROOT).as_posix()],"进入实板自检" if passed else "定位首个错误并修复重试",
               bitstream_sha256=sha256(bit) if bit.exists() else None,config_sha256=sha256(ROOT/"constraints/nexys_a7_100t.xdc"),
               outputs=[bit.relative_to(ROOT).as_posix()] if bit.exists() else [])
    print("RUN_ID="+run.run_id)
    if passed and max_samples==160000:
        resume=ROOT/'state/resume.json'
        if resume.exists():
            value=json.loads(resume.read_text(encoding='utf8'))
            value.update(requires_rebuild=False,validated_build_run_id=run.run_id,current_xdc_sha256=sha256(ROOT/'constraints/nexys_a7_100t.xdc'))
            write_json(resume,value)
    return 0 if passed else 2


if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--max-samples',type=int,choices=(128000,160000),default=160000)
    raise SystemExit(build(p.parse_args().max_samples))
