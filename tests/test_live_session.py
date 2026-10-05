import queue
import threading
from types import SimpleNamespace


def fake_worker():
    end=threading.Event();t=threading.Thread(target=lambda:end.wait(2),daemon=True);t.start()
    return SimpleNamespace(job_id='fixture-job',msg_queue=queue.Queue(),progress_queue=queue.Queue(),partial_queue=queue.Queue(),result_queue=queue.Queue(),_thread=t,_stop_event=threading.Event(),request_stop=lambda:None),end


def test_session_emits_partial_before_final_and_marks_revision(monkeypatch):
    from gurunote.webui.session import PipelineSession
    worker,end=fake_worker();monkeypatch.setattr('gurunote.webui.session.PipelineWorker',lambda **kw:worker)
    events=[];window=SimpleNamespace(evaluate_js=lambda js:None)
    s=PipelineSession(window,{'kind':'youtube','value':'fixture','engine':'mlx','provider':'openai'})
    monkeypatch.setattr(s,'_schedule_poll',lambda:None)
    monkeypatch.setattr(s,'_emit',lambda event,data:events.append((event,data)))
    worker.partial_queue.put({'stage':'translation','korean_transcript':'첫 청크','revision':1,'is_partial':True})
    s._poll()
    assert events[0][0]=='partial_result'
    assert events[0][1]['job_id']=='fixture-job'
    assert events[0][1]['korean_transcript']=='첫 청크'
    assert not s._done
    end.set();worker._thread.join()


def test_no_result_exit_is_failed_instead_of_stranding_queue(monkeypatch):
    from gurunote.webui.session import PipelineSession
    worker,end=fake_worker();end.set();worker._thread.join()
    monkeypatch.setattr('gurunote.webui.session.PipelineWorker',lambda **kw:worker)
    s=PipelineSession(SimpleNamespace(evaluate_js=lambda js:None),{'kind':'youtube','value':'fixture','engine':'mlx','provider':'openai'})
    events=[];monkeypatch.setattr(s,'_emit',lambda event,data:events.append((event,data)))
    monkeypatch.setattr(s,'_schedule_poll',lambda:None)
    s._poll()
    assert s._done
    assert events[-1][0]=='result' and events[-1][1]['ok'] is False
    assert 'WITHOUT_RESULT' in events[-1][1]['error']


def test_terminal_result_waits_for_worker_cleanup_ack(monkeypatch):
    from gurunote.webui.session import PipelineSession
    worker,end=fake_worker();monkeypatch.setattr('gurunote.webui.session.PipelineWorker',lambda **kw:worker)
    s=PipelineSession(SimpleNamespace(evaluate_js=lambda js:None),{'kind':'youtube','value':'fixture','engine':'mlx','provider':'openai'})
    events=[];monkeypatch.setattr(s,'_emit',lambda event,data:events.append((event,data)))
    monkeypatch.setattr(s,'_schedule_poll',lambda:None)
    worker.result_queue.put({'ok':False,'error':'fixture failure'})
    s._poll();assert not s._done and not events
    end.set();worker._thread.join();s._poll()
    assert s._done and len(events)==1


def test_final_result_dequeue_cannot_race_supervisor_finalization(monkeypatch):
    """Pause after a real queue dequeue, before the poller can store its result."""
    from gurunote.webui.session import PipelineSession

    worker, end = fake_worker()
    end.set()
    worker._thread.join()
    removed = threading.Event()
    release = threading.Event()
    attempted = threading.Event()
    supervisor_done = threading.Event()
    lock_was_busy = []
    errors = []

    class PausingQueue(queue.Queue):
        def get_nowait(self):
            value = super().get_nowait()
            removed.set()
            if not release.wait(3):
                raise AssertionError('Poller test barrier timed out')
            return value

    class ObservedLock:
        def __init__(self):
            self.lock = threading.RLock()

        def __enter__(self):
            if threading.current_thread().name == 'test-supervisor':
                acquired = self.lock.acquire(blocking=False)
                lock_was_busy.append(not acquired)
                attempted.set()
                if not acquired:
                    self.lock.acquire()
            else:
                self.lock.acquire()
            return self

        def __exit__(self, *args):
            self.lock.release()

    worker.result_queue = PausingQueue()
    worker.result_queue.put({'ok': True, 'full_md': '', 'summary_md': 'fixture summary'})
    monkeypatch.setattr('gurunote.webui.session.PipelineWorker', lambda **kw: worker)
    session = PipelineSession(SimpleNamespace(evaluate_js=lambda js: None),
                              {'kind': 'youtube', 'value': 'fixture', 'engine': 'mlx', 'provider': 'openai'})
    monkeypatch.setattr(session, '_terminal_lock', ObservedLock())
    events = []
    monkeypatch.setattr(session, '_emit', lambda event, data: events.append((event, data)))
    monkeypatch.setattr(session, '_schedule_poll', lambda: None)

    def invoke(fn, done=None):
        try:
            fn()
        except Exception as exc:
            errors.append(exc)
        finally:
            if done is not None:
                done.set()

    poller = threading.Thread(target=lambda: invoke(session._poll), name='test-poller')
    supervisor = threading.Thread(target=lambda: invoke(session.finalize_if_ended, supervisor_done),
                                  name='test-supervisor')
    poller.start()
    try:
        assert removed.wait(3)
        supervisor.start()
        assert attempted.wait(3)
        if not lock_was_busy[0]:
            assert supervisor_done.wait(3)  # Reproduce the original, unlocked dequeue gap.
    finally:
        release.set()
        poller.join(3)
        if supervisor.ident is not None:
            supervisor.join(3)
    assert not errors
    assert not poller.is_alive() and not supervisor.is_alive()
    results = [data for event, data in events if event == 'result']
    assert len(results) == 1
    assert results[0]['ok'] is True, results
    assert results[0]['summary_md'] == 'fixture summary'


def test_queue_supervisor_waits_for_terminal_result_delivery(monkeypatch):
    """An in-flight result event must not become a no-result queue failure."""
    from gurunote.webui.session import PipelineSession
    from gurunote.webui.work_queue import PipelineQueue

    worker, end = fake_worker()
    started = threading.Event()
    supervisor_ready = threading.Event()
    allow_supervisor = threading.Event()
    supervisor_attempted = threading.Event()
    supervisor_returned = threading.Event()
    emit_started = threading.Event()
    release_emit = threading.Event()
    finish_seen = threading.Event()
    lock_was_busy = []
    holder = {}
    errors = []
    finish_calls = []
    worker.start = started.set
    monkeypatch.setattr('gurunote.webui.session.PipelineWorker', lambda **kw: worker)

    class DeliveryLock:
        def __init__(self):
            self.lock = threading.RLock()

        def __enter__(self):
            if threading.current_thread().name == 'gurunote-queue':
                acquired = self.lock.acquire(blocking=False)
                lock_was_busy.append(not acquired)
                supervisor_attempted.set()
                if not acquired:
                    self.lock.acquire()
            else:
                self.lock.acquire()
            return self

        def __exit__(self, *args):
            self.lock.release()

    def factory(source, terminal, observed):
        session = PipelineSession(SimpleNamespace(evaluate_js=lambda js: None), source,
                                  on_terminal=terminal, on_event=observed)
        monkeypatch.setattr(session, '_terminal_lock', DeliveryLock())
        monkeypatch.setattr(session, '_schedule_poll', lambda: None)
        original_finalize = session.finalize_if_ended
        original_emit = session._emit

        def finalize(start_error=None):
            if threading.current_thread().name == 'gurunote-queue':
                supervisor_ready.set()
                if not allow_supervisor.wait(3):
                    raise AssertionError('Supervisor test barrier timed out')
                try:
                    return original_finalize(start_error)
                finally:
                    supervisor_returned.set()
            return original_finalize(start_error)

        def emit(event, data):
            if event == 'result':
                emit_started.set()
                if not release_emit.wait(3):
                    raise AssertionError('Result delivery test barrier timed out')
            original_emit(event, data)

        monkeypatch.setattr(session, 'finalize_if_ended', finalize)
        monkeypatch.setattr(session, '_emit', emit)
        holder['session'] = session
        return session

    queue_controller = PipelineQueue(factory)
    original_finish = queue_controller._finish

    def finish(item, data):
        finish_calls.append(dict(data))
        original_finish(item, data)
        finish_seen.set()

    monkeypatch.setattr(queue_controller, '_finish', finish)
    response = queue_controller.enqueue([{'kind': 'youtube', 'value': 'fixture',
                                         'engine': 'mlx', 'provider': 'openai'}])
    queue_id = response['added'][0]
    poller = None
    try:
        assert started.wait(3)
        worker.result_queue.put({'ok': True, 'full_md': '', 'summary_md': 'queue summary'})
        end.set()
        worker._thread.join(3)
        assert supervisor_ready.wait(3)

        def poll():
            try:
                holder['session']._poll()
            except Exception as exc:
                errors.append(exc)

        poller = threading.Thread(target=poll, name='test-terminal-poller')
        poller.start()
        assert emit_started.wait(3)  # _done is now set; UI delivery is still in flight.
        allow_supervisor.set()
        assert supervisor_attempted.wait(3)
        if not lock_was_busy[0]:
            assert finish_seen.wait(3)  # Original code wrongly settles the item as failed.
    finally:
        end.set()
        allow_supervisor.set()
        release_emit.set()
        if poller is not None:
            poller.join(3)
        worker._thread.join(3)
    assert supervisor_returned.wait(3)
    assert finish_seen.wait(3)
    assert not errors
    assert poller is not None and not poller.is_alive()
    item = queue_controller.snapshot()['items'][0]
    assert item['status'] == 'completed', queue_controller.get_result(queue_id)
    assert len(finish_calls) == 1, finish_calls
    assert finish_calls[0]['ok'] is True
    result = queue_controller.get_result(queue_id)
    assert result is not None
    assert result['summary_md'] == 'queue summary'
