import json,shutil,sys
from audit import ROOT,Run,sha256,write_json
from hardware import vivado
original=ROOT/'runs'/sys.argv[1]
run=Run('build_route_refinement');run.snapshot('从已验证源码对应的布线检查点继续物理优化，保持逻辑与构建号')
checkpoint=original/'implementation/routed.dcp'
run.event('checkpoint_resumed',original_run=original.name,checkpoint_sha256=sha256(checkpoint))
shutil.copy2(original/'build_inputs.json',run.path/'build_inputs.json')
output=run.path/'implementation'
rc,text=vivado(run,'resume_route.tcl',[ROOT,output,checkpoint], '对剩余47ps建立时间违例执行布线后物理优化并重新验收',timeout=900)
bit=output/'recorder_top.bit';ok=rc==0 and 'BUILD_PASSED' in text and bit.exists()
run.status('build','passed' if ok else 'failed','布线后时序优化通过' if ok else '时序仍未通过',
           [(run.path/'build_inputs.json').relative_to(ROOT).as_posix()], '下载并进行真实双通道自检' if ok else '继续诊断关键路径',
           bitstream_sha256=sha256(bit) if bit.exists() else None,config_sha256=sha256(ROOT/'constraints/nexys_a7_100t.xdc'),
           outputs=[bit.relative_to(ROOT).as_posix()] if bit.exists() else [])
print('RUN_ID='+run.run_id);raise SystemExit(0 if ok else 2)
