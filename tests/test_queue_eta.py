import math


def test_eta_is_unknown_without_progress_or_observations():
    from gurunote.webui.work_queue import estimate_job_finish
    assert estimate_job_finish(100,100,0,'running')['remaining_seconds'] is None
    assert estimate_job_finish(100,101,0.5,'running')['estimated_end_at'] is None


def test_eta_uses_elapsed_observations_and_never_sits_in_past():
    from gurunote.webui.work_queue import estimate_job_finish
    a=estimate_job_finish(100,110,0.5,'running')
    assert a['elapsed_seconds']==10 and a['remaining_seconds']==10
    assert a['estimated_end_at']==120
    b=estimate_job_finish(100,140,0.5,'running')
    assert b['remaining_seconds']==40 and b['estimated_end_at']>140


def test_finished_or_stopping_has_no_pending_eta():
    from gurunote.webui.work_queue import estimate_job_finish
    for status in ['completed','failed','stopped','stopping','cancelled','queued']:
        assert estimate_job_finish(100,110,0.5,status)['remaining_seconds'] is None


def test_nonfinite_or_out_of_range_progress_is_unknown():
    from gurunote.webui.work_queue import estimate_job_finish
    for p in [math.nan,math.inf,-1,1,2]:
        assert estimate_job_finish(100,110,p,'running')['estimated_end_at'] is None
