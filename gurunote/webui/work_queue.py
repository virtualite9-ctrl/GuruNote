"""Process-local serial queue for the desktop pipeline, no persistent replay."""
from __future__ import annotations
from copy import deepcopy
import threading
import time
import math
import statistics
import uuid
from typing import Any, Callable

def estimate_job_finish(started_at, now, progress, status='running'):
    elapsed=max(0.0,now-started_at) if started_at is not None else 0.0
    data={'elapsed_seconds':elapsed,'remaining_seconds':None,'estimated_end_at':None}
    if status!='running' or elapsed<3 or not math.isfinite(progress) or not 0.05<=progress<1:
        return data
    remaining=max(1,math.ceil(elapsed*(1-progress)/progress))
    data.update(remaining_seconds=remaining,estimated_end_at=now+remaining)
    return data

class PipelineQueue:
    def __init__(self, session_factory: Callable, emit: Callable | None = None, clock=time.time):
        self._factory=session_factory
        self._emit=emit or (lambda snapshot:None)
        self._items:list[dict[str,Any]]=[]
        self._lock=threading.RLock()
        self._active:str | None=None
        self._paused=False
        self._clock=clock
        self._version=0
        self._durations=[]

    def snapshot(self):
        with self._lock:
            now=self._clock();items=[]
            for item in self._items:
                record={k:deepcopy(v) for k,v in item.items() if k not in ('session','result','preview','stop_requested')}
                observed_at=item.get('finished_at') or now
                record.update(estimate_job_finish(item.get('started_at'),observed_at,item.get('progress',0.0),item['status']))
                record['has_result']=bool(item.get('result') or item.get('preview'))
                items.append(record)
            active=next((x for x in items if x['queue_id']==self._active),None)
            remaining=active.get('remaining_seconds') if active else 0
            pending=sum(x['status']=='queued' for x in items)
            typical=statistics.median(self._durations) if self._durations else (active['elapsed_seconds']+remaining if active and remaining is not None else None)
            total=None if self._paused or remaining is None or (pending and typical is None) else remaining+(typical or 0)*pending
            return {'items':items,'version':self._version,'active_queue_id':self._active,'active_job_id':active['job_id'] if active else None,'paused':self._paused,'remaining_seconds':total,'estimated_end_at':now+total if total is not None and (active or pending) else None,'eta_basis':'observed-duration heuristic; different media lengths can change it'}

    def _announce(self):
        try:self._emit(self.snapshot())
        except Exception:pass  # Closing the view cannot strand a pipeline slot.

    def enqueue(self,sources):
        added=[];duplicates=[]
        with self._lock:
            for source in sources:
                key=(source.get('kind'),str(source.get('value','')).strip())
                if any((x['source'].get('kind'),str(x['source'].get('value','')).strip())==key and x['status'] in ('queued','starting','running','stopping') for x in self._items):
                    duplicates.append(source.get('value'));continue
                ident=uuid.uuid4().hex
                self._items.append({'queue_id':ident,'source':deepcopy(source),'status':'queued','job_id':None,'session':None,'progress':0.0,'started_at':None,'finished_at':None})
                added.append(ident)
                self._version+=1
        self._start_next()
        self._announce()
        return {'ok':True,'added':added,'duplicates':duplicates,'queue':self.snapshot()}

    def cancel(self,queue_id):
        session=None
        with self._lock:
            item=next((x for x in self._items if x['queue_id']==queue_id),None)
            if item is None or item['status'] in ('completed','failed','stopped','cancelled'):return False
            if item['status']=='queued':item['status']='cancelled'
            else:
                item['status']='stopping';item['stop_requested']=True;self._paused=True;session=item.get('session')
            self._version+=1
        if session is not None:session.request_stop()
        self._announce();return True

    def pause(self):
        with self._lock:self._paused=True;self._version+=1
        self._announce();return self.snapshot()

    def resume(self):
        with self._lock:self._paused=False;self._version+=1
        self._start_next();self._announce();return self.snapshot()

    def clear_finished(self):
        with self._lock:
            before=len(self._items)
            self._items=[x for x in self._items if x['status'] not in ('completed','failed','stopped','cancelled')]
            removed=before-len(self._items)
            self._version+=1
        self._announce();return removed

    def get_result(self,queue_id):
        with self._lock:
            item=next((x for x in self._items if x['queue_id']==queue_id),None)
            if item is None:return None
            return deepcopy(item.get('result') or item.get('preview'))

    def _observe(self,item,event,data):
        with self._lock:
            if item['queue_id']!=self._active or item['status'] not in ('running','stopping') or data.get('job_id')!=item['job_id']:return
            if event=='progress':
                value=data.get('pct')
                if isinstance(value,(int,float)) and math.isfinite(value):item['progress']=max(item['progress'],min(1,max(0,value)))
            elif event=='partial_result' and item['status']=='running':
                revision=data.get('revision',0);previous=item.get('preview',{}).get('revision',0)
                if type(revision) is not int or revision<=previous:return
                item['preview']=deepcopy(data)
            else:return
            self._version+=1
        self._announce()

    def _start_next(self):
        with self._lock:
            if self._active is not None or self._paused:return
            item=next((x for x in self._items if x['status']=='queued'),None)
            if item is None:return
            item['status']='starting';self._active=item['queue_id'];self._version+=1
        threading.Thread(target=self._run_item,args=(item,),daemon=True,name='gurunote-queue').start()

    def _run_item(self,item):
        session=None
        start_error=None
        def terminal(data):
            if start_error:
                data={'ok':False,'error':start_error,'job_id':getattr(session,'job_id',None)}
            self._finish(item,data)
        try:
            session=self._factory(item['source'],terminal,lambda event,data:self._observe(item,event,data))
            with self._lock:
                item['session']=session;item['job_id']=session.job_id
                item['status']='stopping' if item.get('stop_requested') else 'running'
                item['started_at']=self._clock();self._version+=1
            self._announce()
            if item.get('stop_requested'):
                session.request_stop()
                terminal({'ok':False,'stopped':True,'job_id':session.job_id,'error':'실행 전 중지되었습니다.'})
                logger=getattr(session.worker,'_job_logger',None)
                if logger is not None:logger.close()
                return
            session.start()
        except Exception as exc:
            start_error=str(exc)
            if session is not None:
                try:session.request_stop()
                except Exception:pass
        # The slot survives a start/polling exception until the actual worker dies.
        if session is not None:
            thread=getattr(session.worker,'_thread',None)
            if thread is not None and thread.ident is not None:thread.join()
            try:session.finalize_if_ended(start_error)
            except Exception as exc:terminal({'ok':False,'error':str(exc)})
        else:terminal({'ok':False,'error':start_error or 'SESSION_START_FAILED'})
        with self._lock:
            unsettled=item['status'] not in ('completed','failed','stopped','cancelled')
        if unsettled:terminal({'ok':False,'error':'PIPELINE_EXITED_WITHOUT_RESULT'})

    def _finish(self,item,result):
        with self._lock:
            if item['status'] in ('completed','failed','stopped','cancelled'):return
            item['status']='completed' if result.get('ok') else ('stopped' if result.get('stopped') else 'failed')
            item['result']=deepcopy(result)
            item['finished_at']=self._clock()
            if item['status']=='completed':
                item['progress']=1.0
                if item.get('started_at') is not None:self._durations.append(max(0,item['finished_at']-item['started_at']))
            self._version+=1
            if self._active==item['queue_id']:self._active=None
        self._announce()
        self._start_next()
