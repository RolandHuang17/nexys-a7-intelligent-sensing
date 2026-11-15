"""Recover a completed, audited build whose parent stopped before stage indexing."""
import json,sys
from audit import ROOT,Run,sha256,write_json

def recover(run_id):
    run=Run('build',run_id);rows=[json.loads(x) for x in (run.path/'actions.jsonl').read_text(encoding='utf8').splitlines()]
    finished=[x for x in rows if x['kind']=='command_finished'][-1]
    assert finished['returncode']==0 and not finished['timed_out']
    binary=ROOT/finished['outputs'][0];log=ROOT/finished['outputs'][1]
    assert sha256(binary)==finished['stdout_sha256']
    text=log.read_text(encoding='utf8')
    assert 'BUILD_PASSED' in text and 'SERIAL_OUTPUT_CHECKS_PASSED' in text and 'CRITICAL WARNING:' not in text
    inputs=json.loads((run.path/'build_inputs.json').read_text(encoding='utf8'))
    assert all(sha256(ROOT/x['path'])==x['sha256'] for x in inputs['files'])
    bit=run.path/'implementation/recorder_top.bit';assert bit.is_file()
    run.event('stage_index_recovered',reason='command_finished exit 0 and complete reports persisted; parent ended before status write',
              command_finished=finished,bitstream_sha256=sha256(bit),all_source_hashes_match=True)
    run.status('build','passed','已完成构建退出0，完整时序及五路输出门槛通过；恢复中断的状态索引',
               [str((run.path/'build_inputs.json').relative_to(ROOT)),str(log.relative_to(ROOT)),
                str((run.path/'implementation/serial_output_checks.txt').relative_to(ROOT))], '下载并实板自检',
               bitstream_sha256=sha256(bit),config_sha256=sha256(ROOT/'constraints/nexys_a7_100t.xdc'),
               outputs=[str(bit.relative_to(ROOT))])
    p=ROOT/'state/resume.json';s=json.loads(p.read_text(encoding='utf8'));s.update(requires_rebuild=False,validated_build_run_id=run_id)
    write_json(p,s);print('RECOVERED',run_id,inputs['build_id'])

if __name__=='__main__':recover(sys.argv[1])
