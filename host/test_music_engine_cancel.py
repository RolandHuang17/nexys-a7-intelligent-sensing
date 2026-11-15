"""Focused worker ownership/cancellation tests; no UART, HTTP, Tk or real kill."""
import json,queue,threading,time,unittest
from unittest.mock import patch
from music_worker import MusicEngine

class Lines:
    def __init__(self):self.queue=queue.Queue();self.closed=False
    def __iter__(self):return self
    def __next__(self):
        line=self.queue.get()
        if line is None:raise StopIteration
        return line
    def put(self,value):self.queue.put(json.dumps(value)+'\n')
    def end(self):self.queue.put(None)
    def close(self):self.closed=True

class Input:
    def __init__(self):self.lines=[];self.closed=False
    def write(self,line):
        if self.closed:raise BrokenPipeError()
        self.lines.append(json.loads(line))
    def flush(self):pass
    def close(self):self.closed=True

class Process:
    def __init__(self,pid):
        self.pid=pid;self.stdin=Input();self.stdout=Lines();self.stderr=Lines();self.done=threading.Event();self.returncode=None
    def stop(self):
        if not self.done.is_set():
            self.returncode=0;self.stdout.end();self.stderr.end();self.done.set()
    def wait(self,timeout=None):
        if not self.done.wait(timeout):raise TimeoutError('owned worker did not stop')
        return self.returncode

class CancellationTests(unittest.TestCase):
    def setUp(self):
        self.messages=[];self.processes=[];self.stopped=[];self.engines=[]
        def spawn(*args,**kwargs):
            p=Process(7000+len(self.processes));self.processes.append(p);return p
        def stop(process):self.stopped.append(process);process.stop()
        self.spawn=patch('subprocess.Popen',side_effect=spawn).start()
        self.terminate=patch('pc_shazam_backend.terminate_owned_worker',side_effect=stop).start()
    def tearDown(self):
        for engine in self.engines:engine.close()
        for process in self.processes:process.stop()
        patch.stopall()
    def engine(self):
        engine=MusicEngine(self.messages.append);self.engines.append(engine);return engine
    def await_(self,predicate):
        end=time.monotonic()+2
        while time.monotonic()<end:
            if predicate():return
            time.sleep(.005)
        self.fail('Worker cancellation did not settle')
    def acknowledgements(self):return [m for m in self.messages if m.get('action')=='cancelled']

    def test_idle_capture_cancel_keeps_worker_and_prevents_late_submission(self):
        engine=self.engine();original=engine.process
        engine.cancel('recording-not-submitted')
        self.assertEqual(self.acknowledgements(),[{'id':'recording-not-submitted','action':'cancelled','ok':True,'worker_restarted':False}])
        engine.submit('match',id='recording-not-submitted',wav='saved.wav')
        self.assertIs(engine.process,original);self.assertEqual(original.stdin.lines,[]);self.terminate.assert_not_called()

    def test_match_cancel_replaces_only_owned_tree_and_next_job_works(self):
        engine=self.engine();old=engine.process;engine.submit('match',id='cancel-me',wav='saved.wav')
        engine.cancel('cancel-me');self.await_(lambda:bool(self.acknowledgements()))
        new=engine.process;self.assertIsNot(old,new);self.assertEqual(self.stopped,[old])
        self.assertEqual(self.acknowledgements()[0],{'id':'cancel-me','action':'cancelled','ok':True,'worker_restarted':True})
        engine.submit('match',id='next',wav='same-saved.wav')
        self.assertEqual(new.stdin.lines[-1]['id'],'next')
        new.stdout.put({'id':'next','action':'match','ok':True,'result':{'matched':False}})
        self.await_(lambda:any(m.get('id')=='next' for m in self.messages))
        self.assertFalse(any(m.get('action')=='worker_exit' for m in self.messages))

    def test_old_generation_progress_result_and_exit_are_silent(self):
        engine=self.engine();old=engine.process;engine.submit('match',id='old')
        started=threading.Event();release=threading.Event()
        def stop(process):started.set();release.wait(1);process.stop()
        self.terminate.side_effect=stop
        engine.cancel('old');self.assertTrue(started.wait(1))
        old.stdout.put({'id':'old','action':'match_progress','ok':True,'message':'late'})
        old.stdout.put({'id':'old','action':'match','ok':True,'result':{'matched':True}})
        release.set();self.await_(lambda:bool(self.acknowledgements()))
        self.assertEqual([m['action'] for m in self.messages],['cancelled'])
        self.await_(lambda:old.stdout.closed and old.stderr.closed)
        self.assertFalse(engine.process.stdout.closed)

    def test_duplicate_cancel_and_new_submission_during_restart(self):
        engine=self.engine();engine.submit('match',id='old')
        started=threading.Event();release=threading.Event()
        def stop(process):started.set();release.wait(1);process.stop()
        self.terminate.side_effect=stop
        engine.cancel('old');self.assertTrue(started.wait(1));engine.cancel('old')
        engine.submit('verify',id='after-cancel',mode='auto')
        release.set();self.await_(lambda:bool(self.acknowledgements()))
        self.assertEqual(self.spawn.call_count,2);self.assertEqual(self.terminate.call_count,1)
        self.assertEqual(engine.process.stdin.lines,[{'id':'after-cancel','action':'verify','mode':'auto'}])
        self.assertEqual(len(self.acknowledgements()),1)

    def test_finished_result_before_cancel_is_retained_without_restart(self):
        engine=self.engine();old=engine.process;engine.submit('match',id='finished')
        old.stdout.put({'id':'finished','action':'match','ok':True,'result':{'matched':True}})
        self.await_(lambda:any(m.get('id')=='finished' for m in self.messages))
        engine.cancel('finished');self.assertFalse(self.acknowledgements()[0]['worker_restarted'])
        self.assertEqual(self.messages[0]['result'],{'matched':True});self.terminate.assert_not_called()

    def test_close_during_cancel_does_not_resurrect_a_worker(self):
        engine=self.engine();engine.submit('match',id='old')
        started=threading.Event();release=threading.Event()
        def stop(process):started.set();release.wait(1);process.stop()
        self.terminate.side_effect=stop
        engine.cancel('old');self.assertTrue(started.wait(1));engine.close();release.set()
        self.await_(lambda:engine.process.stdout.closed)
        self.assertEqual(self.spawn.call_count,1);self.assertEqual(self.messages,[])

    def test_restart_failure_reports_cancel_error_instead_of_false_ready(self):
        engine=self.engine();engine.submit('match',id='old')
        self.spawn.side_effect=OSError('fixture: replacement unavailable')
        engine.cancel('old');self.await_(lambda:bool(self.acknowledgements()))
        ack=self.acknowledgements()[0]
        self.assertFalse(ack['ok']);self.assertFalse(ack['worker_restarted']);self.assertEqual(ack['error_type'],'OSError')
        self.assertFalse(any(m.get('action')=='worker_exit' for m in self.messages))

if __name__=='__main__':unittest.main()
