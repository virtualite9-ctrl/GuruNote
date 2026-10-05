/* SPDX-License-Identifier: Elastic-2.0
 * Copyright (c) 2026 GuruNote contributors.
 *
 * Phase 2B-2 → Phase 2B-3-backend Step 3b-prep: presentational refactor.
 *   12 useStates + jobIdRef + bus listener + ticker + settings probe 모두 App.jsx
 *   로 lifted. MainScreen 은 form 입력 + 결과 표시만 담당. route 전환 시 unmount
 *   되어도 App.jsx 의 mainSession 이 보존되므로 form / log / result 모두 유지,
 *   bus listener detach 0 → mid-pipeline 이벤트 lost 0.
 *
 * 디자인 spec (docs/design/v2-reference.html 시각 참고):
 *   - 입력 카드 (URL + 파일 선택 XOR + 생성/중지)
 *   - STT 엔진 + LLM Provider segment
 *   - 파이프라인 카드 (5-step indicator + progress + meta)
 *   - 결과 카드 (4탭: 요약/한국어/영어/Log)
 *
 * Props (Step 3b-prep):
 *   - mainSession: { url, selectedFile, stt, llm, dragOver, running, pct, stage,
 *     log, result, startedAt, now } — App level lifted state.
 *   - updateMainSession(patch): App level partial update helper (object 또는
 *     prev => patch function form).
 *   - onPipelineStart(source): App level pipeline 시작 (start_pipeline + jobIdRef).
 *   - onPipelineStop(): App level pipeline 중지 (stop_pipeline).
 *   - newNoteRequestKey: historic — 사용 안 함, App.jsx 가 직접 mainSession reset.
 *     Future Step 3b-2/3/4 단축키 디버그/추적 용도로 prop 시그니처 유지.
 *
 * Bridge wiring (MainScreen 직접 호출):
 *   - pick_file → {path, size}
 *   (start_pipeline / stop_pipeline / get_settings / window.__emit 은 App.jsx)
 */

const { useState, useCallback } = React;

const SUPPORTED_AUDIO = ['.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg', '.wma', '.opus'];
const SUPPORTED_VIDEO = ['.mp4', '.mkv', '.avi', '.mov', '.webm', '.wmv', '.flv', '.ts', '.m4v'];
const SUPPORTED_EXTS = new Set([...SUPPORTED_AUDIO, ...SUPPORTED_VIDEO]);

const STT_OPTIONS = ['auto', 'whisperx', 'mlx', 'assemblyai'];
const LLM_OPTIONS = [
  { value: 'openai',            label: 'openai' },
  { value: 'anthropic',         label: 'anthropic' },
  { value: 'gemini',            label: 'gemini' },
  { value: 'openai_compatible', label: 'local' },
];

// 5-step pipeline thresholds (gui.py 와 동일).
const STEP_THRESHOLDS = [0.18, 0.55, 0.78, 0.90, 1.0];
const STEP_LABELS = ['오디오', 'STT', '번역', '요약', '조립'];

// Phase 2B-3-backend Layer 7: ResultPanel 외부 분리 (gurunote/webui/components/ResultPanel.jsx).
// MainScreen + HistoryScreen DetailPanel + EditorScreen Preview 영역에서 동일 사용.
// RESULT_TABS 상수와 ResultPanel 함수는 ResultPanel.jsx 로 이동.

/* === Helpers === */
function getExt(path) {
  const i = path.lastIndexOf('.');
  return i < 0 ? '' : path.slice(i).toLowerCase();
}
function basename(path) {
  const i = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'));
  return i < 0 ? path : path.slice(i + 1);
}
function formatSize(bytes) {
  if (bytes == null) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1073741824) return `${(bytes / 1048576).toFixed(1)} MB`;
  return `${(bytes / 1073741824).toFixed(2)} GB`;
}
function formatTime(sec) {
  if (sec == null || sec < 0) return '';
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

/* === Toast (전역 helper, App 에서 mount 한 toast container 사용) === */
function showToast(message, kind) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const t = document.createElement('div');
  t.className = 'toast' + (kind ? ` toast--${kind}` : '');
  t.textContent = message;
  container.appendChild(t);
  requestAnimationFrame(() => t.classList.add('toast--visible'));
  setTimeout(() => {
    t.classList.remove('toast--visible');
    setTimeout(() => t.remove(), 200);
  }, 4000);
}
window.showToast = showToast;

/* === StepIndicator === */
function StepIndicator({ pct }) {
  return (
    <div className="steps">
      {STEP_LABELS.map((label, i) => (
        <React.Fragment key={i}>
          <div className={
            'step-node' +
            (pct >= STEP_THRESHOLDS[i] ? ' step-node--done' :
             (i === 0 && pct > 0) || (i > 0 && pct >= STEP_THRESHOLDS[i-1]) ? ' step-node--active' : '')
          }>
            {pct >= STEP_THRESHOLDS[i] ? '✓' : i + 1}
          </div>
          {i < STEP_LABELS.length - 1 && (
            <div className={
              'step-connector' +
              (pct >= STEP_THRESHOLDS[i] ? ' step-connector--done' : '')
            } />
          )}
        </React.Fragment>
      ))}
      {STEP_LABELS.map((label, i) => (
        <React.Fragment key={`l-${i}`}>
          <div className={
            'step-label' +
            (pct >= STEP_THRESHOLDS[i] || (i > 0 && pct >= STEP_THRESHOLDS[i-1]) ? ' step-label--active' : '')
          }>{label}</div>
          {i < STEP_LABELS.length - 1 && <div />}
        </React.Fragment>
      ))}
    </div>
  );
}

/* ResultPanel 은 외부 component (ResultPanel.jsx, window.ResultPanel) — Layer 7. */

/* === MainScreen === */
function MainScreen({
  // eslint-disable-next-line no-unused-vars
  newNoteRequestKey,
  mainSession,
  updateMainSession,
  restoreQueueResult,
  onPipelineStart,
  onPipelineStop,
}) {
  // Step 3b-prep: 모든 state 는 props 의 mainSession 에서 destructure.
  // route 전환 시 MainScreen 이 unmount 되어도 App.jsx 의 mainSession 이 보존됨.
  const {
    url, selectedFile, stt, llm, dragOver,
    running, pct, stage, log, result, startedAt, now,
  } = mainSession;

  // XOR 토글: URL 입력 시 파일 비움 (값이 실제 입력된 경우만)
  const handleUrlChange = (e) => {
    const v = e.target.value;
    if (v && selectedFile) {
      updateMainSession({ url: v, selectedFile: null });
    } else {
      updateMainSession({ url: v });
    }
  };

  // XOR 토글: 파일 선택 성공 시 URL 비움
  const handlePickFile = useCallback(async () => {
    try {
      const pickResult = await window.pywebview.api.pick_file();
      if (!pickResult?.path) return; // cancelled — preserve URL
      const ext = getExt(pickResult.path);
      if (!SUPPORTED_EXTS.has(ext)) {
        showToast(
          `지원하지 않는 형식입니다: ${ext}\n지원: ${[...SUPPORTED_AUDIO, ...SUPPORTED_VIDEO].join(' ')}`,
          'warning'
        );
        return;
      }
      updateMainSession({
        selectedFile: { path: pickResult.path, size: pickResult.size },
        url: '',
      });
    } catch (e) {
      console.error('[pick_file]', e);
      showToast(`파일 선택 오류: ${e.message || e}`, 'error');
    }
  }, [updateMainSession]);

  const handleRemoveFile = () => updateMainSession({ selectedFile: null });

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    updateMainSession({ dragOver: false });
    const files = e.dataTransfer?.files;
    if (!files || files.length === 0) return;
    if (files.length > 1) {
      showToast('파일은 1개만 선택할 수 있습니다.', 'warning');
      return;
    }
    const f = files[0];
    const fullPath = f.pywebviewFullPath || f.name;
    if (!SUPPORTED_EXTS.has(getExt(fullPath))) {
      showToast(`지원하지 않는 형식입니다: ${getExt(fullPath)}`, 'warning');
      return;
    }
    updateMainSession({
      selectedFile: { path: fullPath, size: typeof f.size === 'number' ? f.size : null },
      url: '',
    });
  };

  // 생성하기 — 폼 검증 후 onPipelineStart(source) 호출 (App.jsx 가 start_pipeline + jobIdRef 처리)
  const handleRun = () => {
    let source;
    if (selectedFile) {
      source = { kind: 'local', value: selectedFile.path, engine: stt, provider: llm, diarization_backend: mainSession.diarization || 'resemblyzer' };
    } else if (url.trim()) {
      source = url.split(/\r?\n/).map((s) => s.trim()).filter(Boolean).map((value) => ({ kind: 'youtube', value, engine: stt, provider: llm, diarization_backend: mainSession.diarization || 'resemblyzer' }));
    } else {
      showToast('URL 또는 파일을 먼저 선택하세요.', 'warning');
      return;
    }
    onPipelineStart(source);
  };

  // 중지 — App.jsx 의 onPipelineStop 호출 (jobIdRef 기반 stop_pipeline)
  const handleStop = () => onPipelineStop();

  const canRun = selectedFile || url.trim();
  const elapsed = Math.floor(mainSession.elapsedSeconds || 0);
  const viewQueueItem = async (id) => {
    const request = {};
    updateMainSession({ viewingQueueId: id, resultSelectionRequest: request, automaticRestoreRequest: null });
    const qid = id || mainSession.queue?.active_queue_id;
    const jobId = mainSession.queue?.items?.find((x) => x.queue_id === qid)?.job_id;
    if (!qid) { updateMainSession({ result: null }); return; }
    try {
      const data = await window.pywebview.api.get_pipeline_queue_result(qid);
      restoreQueueResult(data, { queueId: qid, jobId, request, viewingId: id });
    } catch (e) { showToast(`결과 조회 실패: ${e.message || e}`, 'error'); }
  };

  return (
    <div className="main-screen">
      {/* === 입력 카드 === */}
      <section className="card">
        <div className="card__header">
          <div>
            <div className="card__title">지식을 증류하세요</div>
            <div className="card__sub">유튜브 링크 또는 로컬 오디오/비디오 파일에서 화자 분리된 한국어 요약본을 생성합니다.</div>
          </div>
          <span className="card__chip">
            <span className="msi" style={{ fontSize: 14 }}>memory</span>
            Apple Silicon · MLX
          </span>
        </div>

        <div className="input-row">
          <textarea
            rows={4}
            aria-label="여러 링크 입력"
            className={'url-input' + (dragOver ? ' url-input--drag-over' : '')}
            placeholder="유튜브 링크를 한 줄에 하나씩 입력하세요. 파일도 선택할 수 있습니다."
            value={url}
            onChange={handleUrlChange}
            onDragEnter={(e) => { e.preventDefault(); updateMainSession({ dragOver: true }); }}
            onDragOver={(e) => e.preventDefault()}
            onDragLeave={() => updateMainSession({ dragOver: false })}
            onDrop={handleDrop}
            autoComplete="off"
          />
          <button type="button" className="btn btn--ghost" onClick={handlePickFile} disabled={running}>
            <span className="msi">folder_open</span>
            파일 선택
          </button>
          <button type="button" className="btn btn--primary" onClick={handleRun} disabled={!canRun}>
            <span className="msi">playlist_add</span>
            대기열에 추가
          </button>
          {running && (
            <button type="button" className="btn btn--ghost" onClick={handleStop}>
              <span className="msi">stop</span>
              현재 작업 중지
            </button>
          )}
        </div>

        {selectedFile && (
          <div className="file-badge">
            <span className="file-badge__icon msi">
              {SUPPORTED_VIDEO.includes(getExt(selectedFile.path)) ? 'movie' : 'music_note'}
            </span>
            <span className="file-badge__name" title={selectedFile.path}>{basename(selectedFile.path)}</span>
            {selectedFile.size != null && (
              <span className="file-badge__size">{formatSize(selectedFile.size)}</span>
            )}
            <button type="button" className="file-badge__remove" onClick={handleRemoveFile} aria-label="파일 선택 취소">
              <span className="msi" style={{ fontSize: 16 }}>close</span>
            </button>
          </div>
        )}

        <div className="options-row">
          <div className="opt-group">
            <div className="opt-group__label">화자분리</div>
            <select aria-label="화자분리 방식" className="diarization-select" value={mainSession.diarization || 'resemblyzer'} onChange={(e) => updateMainSession({ diarization: e.target.value })} disabled={running}>
              <option value="resemblyzer">토큰 없이 로컬 (근사 분리)</option>
              <option value="auto">자동 (기존 토큰이 있으면 pyannote)</option>
              <option value="pyannote">pyannote (HF 토큰 필요)</option>
              <option value="none">분리하지 않음</option>
            </select>
            <span className="queue-hint">로컬 모드는 겹치는 말·짧은 구간에서 정확도가 낮을 수 있습니다.</span>
          </div>
          <div className="opt-group">
            <div className="opt-group__label">STT 엔진</div>
            <div className="segmented">
              {STT_OPTIONS.map(opt => (
                <button
                  key={opt}
                  type="button"
                  className={'seg-opt' + (stt === opt ? ' seg-opt--active' : '')}
                  onClick={() => updateMainSession({ stt: opt })}
                  disabled={running}
                >{opt}</button>
              ))}
            </div>
          </div>

          <div className="opt-group">
            <div className="opt-group__label">LLM Provider</div>
            <div className="segmented">
              {LLM_OPTIONS.map(opt => (
                <button
                  key={opt.value}
                  type="button"
                  className={'seg-opt' + (llm === opt.value ? ' seg-opt--active' : '')}
                  onClick={() => updateMainSession({ llm: opt.value })}
                  disabled={running}
                >{opt.label}</button>
              ))}
            </div>
          </div>
        </div>
      </section>

      <GNQueuePanel queueState={mainSession.queue} onView={viewQueueItem} viewing={mainSession.viewingQueueId} />
      {/* === 파이프라인 카드 === */}
      <section className="card">
        <div className="card__header">
          <div className="card__title" style={{ fontSize: 16 }}>파이프라인</div>
          <span style={{ fontSize: 13, color: 'var(--gn-on-surface-muted)' }}>
            {running ? (stage || '처리 중…') : '대기'}
          </span>
        </div>

        <StepIndicator pct={pct} />

        <div className={'progress' + (running ? '' : ' progress--idle')}>
          <div className="progress__bar">
            <div className="progress__fill" style={{ width: `${pct * 100}%` }} />
          </div>
          <div className="progress__meta">
            <span>{Math.round(pct * 100)}%</span>
            <span>{formatTime(elapsed)} 경과</span>
            <span>예상 종료: {GNQueueFinish(mainSession.queue?.items?.find((x) => x.queue_id === mainSession.queue.active_queue_id)?.estimated_end_at)}</span>
          </div>
        </div>
      </section>

      {/* === 결과 카드 === */}
      <section className="card">
        <div className="card__header">
          <div className="card__title" style={{ fontSize: 16 }}>
            {result?.video_title || '결과'}
          </div>
        </div>
        <ResultPanel result={result} log={log} />
      </section>
    </div>
  );
}

window.MainScreen = MainScreen;

function GNQueueFinish(value) {
  return typeof value === 'number' ? new Date(value * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '계산 중';
}
function GNQueuePanel({ queueState, onView, viewing }) {
  const q = queueState || { items: [] };
  const labels = { queued: '대기', starting: '시작 중', running: '처리 중', stopping: '중지 대기', completed: '완료', failed: '실패', stopped: '중지', cancelled: '제거' };
  const action = async (method, id) => { try { await window.pywebview.api[method](id); } catch (e) { window.showToast?.(e.message || String(e), 'error'); } };
  return <section className="card queue-card" aria-label="작업 대기열">
    <div className="card__header"><div className="card__title">작업 대기열</div><div className="queue-actions">
      <button type="button" className="btn btn--ghost" onClick={() => action(q.paused ? 'resume_pipeline_queue' : 'pause_pipeline_queue')}>{q.paused ? '대기열 계속' : '대기열 일시정지'}</button>
      <button type="button" className="btn btn--ghost" onClick={() => action('clear_finished_pipeline_queue')}>완료 항목 비우기</button>
    </div></div>
    <p className="queue-hint">전체 예상 종료: <strong>{GNQueueFinish(q.estimated_end_at)}</strong> · 최근 처리시간 기준 참고값이며 영상 길이에 따라 달라집니다.</p>
    {!q.items.length && <p className="queue-hint">등록된 작업이 없습니다. 여러 링크를 한 번에 추가할 수 있습니다.</p>}
    <div className="queue-list">{q.items.map((x, i) => <div className={'queue-item' + (x.queue_id === q.active_queue_id ? ' queue-item--active' : '')} key={x.queue_id}>
      <span className="queue-index">{i + 1}</span><span className="queue-source" title={x.source.value}>{x.source.value}</span><span className="queue-state">{labels[x.status] || x.status}</span>
      {x.status === 'queued' && <button type="button" className="btn btn--ghost" aria-label={`${i + 1}번 대기 작업 제거`} onClick={() => action('cancel_pipeline_queue_item', x.queue_id)}>제거</button>}
      {x.has_result && <button type="button" className="btn btn--ghost" onClick={() => onView(x.queue_id)}>결과 보기</button>}
    </div>)}</div>
    {viewing && <button type="button" className="btn btn--ghost" onClick={() => onView(null)}>진행 중 결과로 돌아가기</button>}
  </section>;
}
