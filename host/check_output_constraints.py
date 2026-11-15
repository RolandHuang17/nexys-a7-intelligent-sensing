from audit import ROOT,Run
from hardware import vivado
run=Run('output_constraint_check');run.snapshot('修正datapath_only需要显式起点的告警，并逐输出查看实际最大延迟')
rc,text=vivado(run,'check_output_constraints.tcl',[ROOT/'runs/20261113T221255_286066_build/implementation/routed.dcp',run.path],
               '在已路由设计上验证串行输出最大传播约束和覆盖情况',timeout=180)
run.manifest();print('RUN_ID='+run.run_id);raise SystemExit(rc)
