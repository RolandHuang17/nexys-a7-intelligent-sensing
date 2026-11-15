import sys,psutil
from audit import ROOT,Run
run_id=sys.argv[1]
assert (ROOT/'runs'/run_id/'build_inputs.json').exists()
run=Run('build',run_id)
matches=[]
for process in psutil.process_iter(['pid','name','cmdline']):
    if process.info['name'].lower()=='vivado.exe' and run_id in ' '.join(process.info['cmdline'] or []):
        matches.append(process)
        run.event('build_stopped_for_structural_fix',pid=process.pid,argv=process.info['cmdline'],
                  reason='路由估计仍约 -3.6 ns；已对日志指出的触发元数据路径做结构流水化，停止旧版本无效优化并保留全部现场')
        process.terminate();process.wait(timeout=20)
print('Stopped owned Vivado processes:',[p.pid for p in matches]);run.manifest()
