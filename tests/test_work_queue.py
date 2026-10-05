from __future__ import annotations
import threading
import time

def wait_for(predicate, timeout=2):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if predicate():return
        time.sleep(0.005)
    assert predicate(), 'state transition timed out'

class FakeSession:
    def __init__(self, source, done, observed):
        self.source=source;self.done=done;self.observed=observed
        self.job_id='job-'+source['value'];self.exit=threading.Event();self.started=threading.Event()
        self.worker=type('Worker',(),{})();self.worker._thread=None
        self.result={'ok':True,'job_id':self.job_id};self.calls=0
    def start(self):
        self.worker._thread=threading.Thread(target=self._run,daemon=True)
        self.worker._thread.start();self.started.wait(1)
    def _run(self):self.started.set();self.exit.wait(2)
    def request_stop(self):self.result={'ok':False,'stopped':True,'job_id':self.job_id}
    def finish(self):self.exit.set()
    def finalize_if_ended(self, start_error=None):
        if self.worker._thread and self.worker._thread.is_alive():return
        self.calls+=1;self.done(dict(self.result,error=start_error) if start_error else self.result)

def test_fifo_waits_for_prior_worker_exit():
    from gurunote.webui.work_queue import PipelineQueue
    sessions={}
    def factory(source, done, observed):
        s=FakeSession(source,done,observed);sessions[source['value']]=s;return s
    q=PipelineQueue(factory)
    q.enqueue([{'value':'one'},{'value':'two'}])
    wait_for(lambda:'one' in sessions and sessions['one'].started.is_set())
    assert 'two' not in sessions
    sessions['one'].finish()
    wait_for(lambda:'two' in sessions and sessions['two'].started.is_set())
    assert not sessions['one'].worker._thread.is_alive()
    sessions['two'].finish()
    wait_for(lambda:all(x['status']=='completed' for x in q.snapshot()['items']))


def test_poll_start_failure_holds_slot_until_worker_is_dead():
    from gurunote.webui.work_queue import PipelineQueue
    sessions={};second_created=threading.Event()
    class BrokenPoll(FakeSession):
        def start(self):
            super().start()
            raise RuntimeError('poll setup failed after start')
    def factory(source,done,observed):
        s=(BrokenPoll if source['value']=='one' else FakeSession)(source,done,observed)
        sessions[source['value']]=s
        if source['value']=='two':second_created.set()
        return s
    q=PipelineQueue(factory);q.enqueue([{'value':'one'},{'value':'two'}])
    wait_for(lambda:'one' in sessions and sessions['one'].started.is_set())
    assert not second_created.wait(0.1), 'a live worker must retain its slot after polling fails'
    sessions['one'].finish()
    assert second_created.wait(1)
    assert q.snapshot()['items'][0]['status']=='failed'
    sessions['two'].finish()


def test_stop_pauses_and_resume_does_not_overlap_a_live_worker():
    from gurunote.webui.work_queue import PipelineQueue
    sessions={}
    def factory(source,done,observed):
        s=FakeSession(source,done,observed);sessions[source['value']]=s;return s
    q=PipelineQueue(factory);ids=q.enqueue([{'value':'one'},{'value':'two'}])['added']
    wait_for(lambda:'one' in sessions and sessions['one'].started.is_set())
    assert q.cancel(ids[0]) is True
    assert q.snapshot()['paused'] is True
    assert q.snapshot()['items'][0]['status']=='stopping'
    q.resume()
    assert 'two' not in sessions
    sessions['one'].finish()
    wait_for(lambda:'two' in sessions)
    assert q.snapshot()['items'][0]['status']=='stopped'
    sessions['two'].finish()


def test_exact_pending_duplicate_is_ignored_but_completed_can_run_again():
    from gurunote.webui.work_queue import PipelineQueue
    sessions=[]
    def factory(source,done,observed):
        s=FakeSession(source,done,observed);sessions.append(s);return s
    q=PipelineQueue(factory)
    first=q.enqueue([{'value':'one'},{'value':'one'}])
    assert len(first['added'])==1 and len(first['duplicates'])==1
    wait_for(lambda:len(sessions)==1 and sessions[0].started.is_set())
    assert q.enqueue([{'value':'one'}])['added']==[]
    sessions[0].finish();wait_for(lambda:q.snapshot()['items'][0]['status']=='completed')
    assert len(q.enqueue([{'value':'one'}])['added'])==1
    wait_for(lambda:len(sessions)==2);sessions[1].finish()


def test_pending_removal_never_starts_and_clear_keeps_active():
    from gurunote.webui.work_queue import PipelineQueue
    sessions={}
    def factory(source,done,observed):
        s=FakeSession(source,done,observed);sessions[source['value']]=s;return s
    q=PipelineQueue(factory);ids=q.enqueue([{'value':'one'},{'value':'two'}])['added']
    wait_for(lambda:'one' in sessions and sessions['one'].started.is_set())
    assert q.cancel(ids[1]) is True
    assert q.clear_finished()==1
    assert len(q.snapshot()['items'])==1
    sessions['one'].finish();wait_for(lambda:q.snapshot()['items'][0]['status']=='completed')
    assert 'two' not in sessions


def test_stale_preview_cannot_overwrite_a_different_active_item():
    from gurunote.webui.work_queue import PipelineQueue
    sessions={}
    def factory(source,done,observed):
        s=FakeSession(source,done,observed);sessions[source['value']]=s;return s
    q=PipelineQueue(factory);ids=q.enqueue([{'value':'one'},{'value':'two'}])['added']
    wait_for(lambda:'one' in sessions and sessions['one'].started.is_set())
    sessions['one'].observed('partial_result',{'job_id':'job-one','revision':1,'korean_transcript':'one preview'})
    assert q.get_result(ids[0])['korean_transcript']=='one preview'
    sessions['one'].finish();wait_for(lambda:'two' in sessions and sessions['two'].started.is_set())
    sessions['two'].observed('partial_result',{'job_id':'job-two','revision':2,'korean_transcript':'two preview'})
    sessions['one'].observed('partial_result',{'job_id':'job-one','revision':99,'korean_transcript':'stale'})
    sessions['two'].observed('partial_result',{'job_id':'job-two','revision':1,'korean_transcript':'older'})
    assert q.get_result(ids[1])['korean_transcript']=='two preview'
    sessions['two'].finish()
