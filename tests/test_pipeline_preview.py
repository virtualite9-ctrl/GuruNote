from types import SimpleNamespace


def test_translate_reports_accumulated_chunks_before_return(monkeypatch):
    from gurunote.llm import translate as m
    from gurunote.types import Segment, Transcript
    cfg=SimpleNamespace(enable_phase2=False,provider='fixture',model='fixture')
    tr=Transcript([Segment('A',0,2,'one'),Segment('B',2,4,'two')],engine='fixture')
    chunks=[[tr.segments[0]],[tr.segments[1]]]
    monkeypatch.setattr(m.client,'_check_xgrammar_available',lambda *a:True)
    monkeypatch.setattr(m.chunking,'chunk_segments',lambda *a,**k:chunks)
    monkeypatch.setattr(m.chunking,'CHUNK_DELAY_SEC',0)
    monkeypatch.setattr(m.context,'build_video_context_block',lambda *a:'')
    monkeypatch.setattr(m,'translate_chunk_index_mapping_v2',lambda chunk,*a,**k:chunk[0].text+' 번역')
    monkeypatch.setattr(m.postprocess,'post_process_cjk',lambda text,*a:text)
    seen=[]
    result=m.translate_transcript(tr,config=cfg,on_partial=seen.append)
    assert len(seen)==2
    assert seen[0]['completed_chunks']==1 and seen[0]['total_chunks']==2
    assert seen[0]['text']=='one 번역'
    assert seen[1]['text']==result


def test_worker_preview_is_latest_snapshot_not_an_unbounded_stream(monkeypatch):
    import queue
    from gurunote.pipeline_worker import PipelineWorker
    monkeypatch.setattr('gurunote.pipeline_worker.JobLogger',lambda *a:SimpleNamespace(write=lambda *a:None,close=lambda:None))
    w=PipelineWorker('mlx','openai')
    w._publish_partial(stage='stt',english_transcript='source')
    w._publish_partial(stage='translation',korean_transcript='first')
    w._publish_partial(stage='translation',korean_transcript='first second')
    latest=w.partial_queue.get_nowait()
    assert latest['english_transcript']=='source'
    assert latest['korean_transcript']=='first second'
    assert latest['is_partial'] and latest['revision']==3
    assert w.partial_queue.empty()


def test_bridge_batch_reports_invalid_lines_without_losing_valid(monkeypatch):
    from gurunote.webui.bridge import Api
    from tests.test_work_queue import FakeSession, wait_for
    sessions=[]
    def factory(window,source,on_terminal=None,on_event=None):
        s=FakeSession(source,on_terminal,on_event);sessions.append(s);return s
    monkeypatch.setattr('gurunote.webui.session.PipelineSession',factory)
    monkeypatch.setenv('OPENAI_BASE_URL','http://fixture.invalid')
    api=Api();api.bind_window(SimpleNamespace(evaluate_js=lambda *a:None))
    good={'kind':'youtube','value':'https://youtu.be/aaaaaaaaaaa','engine':'mlx','provider':'openai_compatible','diarization_backend':'resemblyzer'}
    bad=dict(good,value='not-a-url')
    r=api.enqueue_pipeline_batch([good,bad])
    assert r['ok'] and len(r['added'])==1 and len(r['errors'])==1
    wait_for(lambda:len(sessions)==1 and sessions[0].started.is_set())
    assert sessions[0].source['diarization_backend']=='resemblyzer'
    assert api.get_pipeline_queue()['items'][0]['source']['value']==good['value']
    sessions[0].finish()
