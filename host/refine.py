import json,sys,shutil
from audit import ROOT,Run,sha256,write_json
from hardware import vivado

def refine(source):
    source=ROOT/'runs'/source
    run=Run('build_route_refinement');run.snapshot('逻辑不变，从已路由检查点继续小幅时序优化')
    shutil.copy2(source/'build_inputs.json',run.path/'build_inputs.json')
    checkpoint=source/'implementation/routed.dcp'
    run.event('checkpoint_resumed',source_run_id=source.name,checkpoint_sha256=sha256(checkpoint),
              logic_provenance='source run build_inputs.json and its source snapshot; refinement does not reread RTL')
    output=run.path/'implementation'
    rc,text=vivado(run,'refine.tcl',[ROOT,checkpoint,output],'同一逻辑路由检查点物理优化与完整时序复查',timeout=900)
    bit=output/'recorder_top.bit';passed=rc==0 and 'BUILD_PASSED' in text and bit.exists()
    run.status('build','passed' if passed else 'failed','同一逻辑检查点优化通过' if passed else '检查点优化仍未通过',
               [str((run.path/'build_inputs.json').relative_to(ROOT)),str(checkpoint.relative_to(ROOT))],
               '进入实板自检' if passed else '进一步修复首条时序路径',bitstream_sha256=sha256(bit) if bit.exists() else None,
               config_sha256=sha256(ROOT/'constraints/nexys_a7_100t.xdc'),outputs=[str(bit.relative_to(ROOT))] if bit.exists() else [])
    run.manifest();print('RUN_ID='+run.run_id);return 0 if passed else 2

if __name__=='__main__':raise SystemExit(refine(sys.argv[1]))
