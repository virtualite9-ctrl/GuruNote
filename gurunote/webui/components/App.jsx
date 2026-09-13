/* SPDX-License-Identifier: Elastic-2.0
 * Copyright (c) 2026 GuruNote contributors.
 *
 * Phase 2B-1 + 2B-2 + 2B-3c-rework: App — Sidebar + route-based screen switch.
 * Phase 2B-3c-rework: list_history state lifting — Sidebar 의 nav/library 카운트
 * 와 HistoryScreen 의 카드 그리드가 같은 데이터를 공유.
 */

const { useState, useEffect, useCallback, useRef } = React;

const ROUTE_LABELS = {
  main:      { title: '생성',      phase: '2B-2' },
  history:   { title: '히스토리',  phase: '2B-3' },
  editor:    { title: '노트 편집', phase: '2B-4' },
  dashboard: { title: '대시보드',  phase: '2B-4' },
  settings:  { title: '설정',      phase: '2B-4' },
};

/* Phase 2B-3-backend Step 3b-prep: MainScreen 의 모든 session state 가 App level
 * 로 lifted. route 전환 시 MainScreen 이 unmount 되어도 form / log / result 보존,
 * bus listener detach 0, mid-pipeline 이벤트 lost 0. handleNewNote / ⌘N 시 이
 * default 로 reset. probe 가 settings.values.LLM_PROVIDER 로 llm 덮어씀. */
const APP_DEFAULT_MAIN_SESSION = {
  url: '',
  selectedFile: null,
  stt: 'auto',
  llm: 'openai',
  dragOver: false,
  running: false,
  pct: 0,
  stage: null,
  log: [],
  result: null,
  startedAt: null,
  now: 0,
};

function ScreenPlaceholder({ route }) {
  const meta = ROUTE_LABELS[route] || { title: route, phase: '?' };
  return (
    <div className="screen-placeholder">
      <h2>{meta.title}</h2>
      <p>이 화면은 Phase {meta.phase} 에서 본격 구현됩니다.</p>
    </div>
  );
}

function App() {
  const [route, setRoute] = useState('main');
  const [version, setVersion] = useState(null);

  // Phase 2B-4a: 현재 편집 중인 job_id (HistoryScreen → EditorScreen 진입)
  const [currentJobId, setCurrentJobId] = useState(null);
  const navigateToEditor = useCallback((jobId) => {
    setCurrentJobId(jobId);
    setRoute('editor');
  }, []);

  // Phase 2B-6d: 히스토리 sub-context — '라이브러리' 아래의 어느 진입점인지 추적.
  //   null      = 메인 nav 직접 진입 (default 'history')
  //   'recent'  = 사이드바 '최근 7일' 진입
  //   'tags'    = 사이드바 '태그' 진입
  //   handleLibraryNav 가 set, handleSidebarNavigate('history') 가 clear.
  //   TopBar 의 title 동적 변경에 사용 (breadcrumbs ['라이브러리'] + h2 '최근 7일' 등).
  const [historyContext, setHistoryContext] = useState(null);

  // Phase 2B-5b-2 + 2B-6d: Sidebar 메인 nav 클릭 wrapper.
  //   - '노트 편집' → currentJobId reset (stale fetch 회피, Step 2B-5b-2)
  //   - '히스토리'  → historyContext clear (라이브러리 sub-context 잔재 회피)
  //   - 카드 [편집] 액션의 navigateToEditor 는 이 핸들러를 거치지 않으므로 명시적
  //     jobId 흐름은 무손상.
  const handleSidebarNavigate = useCallback((target) => {
    if (target === 'editor') {
      setCurrentJobId(null);
    }
    if (target === 'history') {
      setHistoryContext(null);
    }
    setRoute(target);
  }, []);

  // History state — Sidebar 카운트 + HistoryScreen 그리드 공유.
  const [historyItems, setHistoryItems] = useState([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState(null);

  // Phase 2B-5a: 1-shot initial filter for HistoryScreen (sidebar library shortcuts).
  // Shape: { initialFacets?: Set, initialTimeWindow?: number, initialExpandedGroup?: string }
  // Cleared by HistoryScreen via onFilterApplied so subsequent direct nav (e.g.
  // "히스토리" main-nav click) doesn't re-apply a stale filter.
  const [historyFilter, setHistoryFilter] = useState(null);
  // Monotonic counter — incremented on every library nav so HistoryScreen's React
  // key changes, forcing a remount that re-runs useState initializers with the
  // new initial* props. onFilterApplied does NOT touch this, so resetting
  // historyFilter to null after mount doesn't trigger a second remount.
  const [historyFilterKey, setHistoryFilterKey] = useState(0);

  const handleLibraryNav = useCallback((libType) => {
    if (libType === 'recent') {
      setHistoryFilter({ initialTimeWindow: 7 });
      setHistoryFilterKey((k) => k + 1);
      setHistoryContext('recent');
      setRoute('history');
    } else if (libType === 'tags') {
      setHistoryFilter({ initialExpandedGroup: 'tag' });
      setHistoryFilterKey((k) => k + 1);
      setHistoryContext('tags');
      setRoute('history');
    }
    // 'favorites' is disabled; no handler invocation.
  }, []);

  // Phase 2B-6d: SearchPalette (⌘K) state.
  //   open=true 시 SearchPalette 마운트, false 시 언마운트.
  //   Trigger: ⌘K 글로벌 keydown / TopBar gn-search onClick / Esc 로 close.
  const [searchPaletteOpen, setSearchPaletteOpen] = useState(false);
  const openSearchPalette = useCallback(() => setSearchPaletteOpen(true), []);
  const closeSearchPalette = useCallback(() => setSearchPaletteOpen(false), []);
  const handlePaletteSelect = useCallback((item) => {
    setSearchPaletteOpen(false);
    if (item?.job_id) {
      setCurrentJobId(item.job_id);
      setRoute('editor');
    }
  }, []);

  // Phase 2B-3-backend Step 3b-prep: lifted MainScreen session state.
  //   12 fields (url, selectedFile, stt, llm, dragOver, running, pct, stage, log,
  //   result, startedAt, now). updateMainSession 은 object 또는 function form 의
  //   partial update helper. jobIdRef 는 App lifecycle 의 ref (handleRun write,
  //   handleStop read). historyRefreshKey 는 counter (onResult 시 ++ → loadHistory
  //   재호출, Sidebar / HistoryScreen / DashboardScreen 자동 update).
  const [mainSession, setMainSession] = useState(APP_DEFAULT_MAIN_SESSION);
  const updateMainSession = useCallback((patch) => {
    setMainSession((prev) => (
      typeof patch === 'function'
        ? { ...prev, ...patch(prev) }
        : { ...prev, ...patch }
    ));
  }, []);
  const jobIdRef = useRef(null);
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0);

  // Phase 2B-6d + Step 3b-prep: 새 노트 만들기 CTA (⌘N) — counter pattern.
  //   Sidebar CTA 또는 ⌘N keydown 시 mainSession reset (모두 default) + counter
  //   increment + setRoute('main'). 진행 중 (running) 가드는 여기서 처리.
  //   newNoteRequestKey 는 historic — MainScreen 의 reset useEffect 가 사용했으나
  //   App.jsx 가 직접 setMainSession 으로 reset 하므로 사실상 deprecated.
  //   Future Step 3b-2/3/4 의 단축키 디버그/추적 용도로 유지.
  const [newNoteRequestKey, setNewNoteRequestKey] = useState(0);
  const handleNewNote = useCallback(() => {
    if (mainSession.running) {
      if (window.showToast) window.showToast('처리 중입니다. 완료 후 새로 시작하세요.', 'warning');
      return;
    }
    setMainSession({ ...APP_DEFAULT_MAIN_SESSION });
    setNewNoteRequestKey((k) => k + 1);
    setRoute('main');
  }, [mainSession.running]);

  // Pipeline 시작 / 중지 (MainScreen 의 handleRun / handleStop 이동).
  //   start_pipeline 이 r.job_id 반환 → jobIdRef.current 저장 (handleStop 사용).
  //   onResult 시점에 jobIdRef.current = null 로 clear (bus listener 안에서).
  const handlePipelineStart = useCallback(async (source) => {
    updateMainSession({
      running: true,
      pct: 0,
      stage: null,
      log: [],
      result: null,
      startedAt: Date.now(),
      now: Date.now(),
    });
    try {
      const r = await window.pywebview.api.start_pipeline(source);
      jobIdRef.current = r.job_id;
    } catch (e) {
      console.error('[start_pipeline]', e);
      const msg = (e && e.message) || String(e);
      if (window.showToast) window.showToast(`파이프라인 시작 실패: ${msg}`, 'error');
      updateMainSession({ running: false });
    }
  }, [updateMainSession]);

  const handlePipelineStop = useCallback(async () => {
    if (!jobIdRef.current) return;
    try {
      await window.pywebview.api.stop_pipeline(jobIdRef.current);
      if (window.showToast) window.showToast('중지 요청을 보냈습니다. 현재 단계가 끝나면 중지됩니다.');
    } catch (e) {
      const msg = (e && e.message) || String(e);
      if (window.showToast) window.showToast(`중지 실패: ${msg}`, 'error');
    }
  }, []);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      while (!window.pywebview?.api) {
        await new Promise((r) => setTimeout(r, 50));
      }
      const result = await window.pywebview.api.list_history();
      if (!result?.ok) {
        throw new Error(result?.error || 'list_history failed');
      }
      setHistoryItems(result.items || []);
      setHistoryTotal(result.total || 0);
    } catch (e) {
      console.error('[App] list_history failed:', e);
      setHistoryError(e.message || String(e));
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  // App 버전 probe — mount 시 한 번.
  useEffect(() => {
    let cancelled = false;
    const probe = async () => {
      while (!window.pywebview?.api && !cancelled) {
        await new Promise((r) => setTimeout(r, 50));
      }
      if (cancelled) return;
      try {
        const info = await window.pywebview.api.get_app_info();
        if (!cancelled && info?.version) setVersion(info.version);
      } catch (e) {
        console.warn('[app] get_app_info failed:', e);
      }
    };
    probe();
    return () => { cancelled = true; };
  }, []);

  // Phase 2B-3-backend Step 3b-prep: history refresh trigger.
  //   loadHistory 가 [historyRefreshKey, loadHistory] dependency 로 재호출됨.
  //   Mount 시 (key=0) 도 호출되어 초기 list_history 트리거.
  //   Bus listener 의 onResult 시점에 setHistoryRefreshKey(k => k + 1) → re-fetch.
  useEffect(() => {
    loadHistory();
  }, [historyRefreshKey, loadHistory]);

  // Phase 2B-3-backend Step 3b-prep: settings probe — App mount 시 한 번.
  //   기존 MainScreen 의 probe useEffect 이동. settings.values.LLM_PROVIDER 가
  //   있으면 mainSession.llm 덮어씀 (default 'openai' → 사용자 환경 값).
  useEffect(() => {
    let cancelled = false;
    const probe = async () => {
      while (!window.pywebview?.api && !cancelled) {
        await new Promise((r) => setTimeout(r, 50));
      }
      if (cancelled) return;
      try {
        const settings = await window.pywebview.api.get_settings();
        if (cancelled) return;
        if (settings?.values?.LLM_PROVIDER) {
          updateMainSession({ llm: settings.values.LLM_PROVIDER });
        }
      } catch (e) {
        console.warn('[App] get_settings failed:', e);
      }
    };
    probe();
    return () => { cancelled = true; };
  }, [updateMainSession]);

  // Phase 2B-3-backend Step 3b-prep: bus listener — App level mount, listener
  //   detach 0. window.bus 는 idempotent 초기화. window.__emit 은 bridge.py 의
  //   evaluate_js("window.__emit(...)") push 의 entry point. onResult 시점에
  //   historyRefreshKey++ → 사이드바 카운터 + 히스토리 / 대시보드 자동 update.
  useEffect(() => {
    if (!window.bus) {
      window.bus = new EventTarget();
      window.__emit = (name, payload) =>
        window.bus.dispatchEvent(new CustomEvent(name, { detail: payload }));
    }

    const onProgress = (e) => {
      if (typeof e.detail?.pct === 'number') updateMainSession({ pct: e.detail.pct });
    };
    const onLog = (e) => {
      if (e.detail?.line) updateMainSession((prev) => ({ log: [...prev.log, e.detail.line] }));
    };
    const onLogBatch = (e) => {
      if (Array.isArray(e.detail?.lines)) updateMainSession((prev) => ({ log: [...prev.log, ...e.detail.lines] }));
    };
    const onStageChange = (e) => {
      if (e.detail?.stage) updateMainSession({ stage: e.detail.stage });
    };
    const onResult = (e) => {
      const payload = e.detail || {};
      jobIdRef.current = null;
      if (!payload.ok) {
        if (window.showToast) {
          window.showToast(`파이프라인 실패: ${payload.error || '알 수 없는 오류'}`, 'error');
        }
        updateMainSession({ running: false, result: null });
        return;
      }
      updateMainSession({ running: false, pct: 1.0, result: payload });
      // History refresh trigger — Sidebar / HistoryScreen / DashboardScreen 자동.
      setHistoryRefreshKey((k) => k + 1);

      // B16-2: 자동 내보내기 토글(GURUNOTE_OBSIDIAN_AUTOEXPORT="1") on 이면 작업 완료
      //   직후 Obsidian vault 로 내보낸다. best-effort — 작업 결과는 이미 저장됐으므로
      //   내보내기 실패해도 완료 흐름은 정상. 토글 off(기본) 면 무동작.
      const jid = payload.job_id;
      if (jid) {
        (async () => {
          try {
            const s = await window.pywebview?.api?.get_settings();
            if (!(s?.ok && s.values?.GURUNOTE_OBSIDIAN_AUTOEXPORT === '1')) return;
            const r = await window.pywebview.api.send_obsidian(jid, true);
            if (r?.skipped) {
              window.showToast?.('이미 내보낸 노트 — 건너뜀', 'info');
            } else if (r?.ok) {
              const rc = r.related_count || 0;
              window.showToast?.(`Obsidian 자동 내보내기 완료${rc ? ` (연관 노트 ${rc}개)` : ''}`, 'success');
            } else if (r?.code === 'NO_VAULT') {
              window.showToast?.('자동 내보내기 — Obsidian Vault 미설정 (설정 → Obsidian)', 'error');
            } else {
              window.showToast?.(`자동 내보내기 실패: ${r?.error || '알 수 없는 오류'}`, 'error');
            }
          } catch (err) {
            window.showToast?.(`자동 내보내기 오류: ${err.message || err}`, 'error');
          }
        })();
      }
    };

    window.bus.addEventListener('progress', onProgress);
    window.bus.addEventListener('log', onLog);
    window.bus.addEventListener('log_batch', onLogBatch);
    window.bus.addEventListener('stage_change', onStageChange);
    window.bus.addEventListener('result', onResult);

    return () => {
      window.bus.removeEventListener('progress', onProgress);
      window.bus.removeEventListener('log', onLog);
      window.bus.removeEventListener('log_batch', onLogBatch);
      window.bus.removeEventListener('stage_change', onStageChange);
      window.bus.removeEventListener('result', onResult);
    };
  }, [updateMainSession]);

  // Elapsed-time ticker — running 시만, mainSession.now 1초 간격 update.
  useEffect(() => {
    if (!mainSession.running) return undefined;
    const id = setInterval(() => updateMainSession({ now: Date.now() }), 1000);
    return () => clearInterval(id);
  }, [mainSession.running, updateMainSession]);

  // Phase 2B-6d: 글로벌 keydown — ⌘K (SearchPalette open) + ⌘N (새 노트).
  //   ⌘S 는 EditorScreen 내부 listener 가 담당 (충돌 없음 — 다른 키).
  //   SearchPalette 의 자체 Esc 처리는 SearchPalette 내부에서 (open 시만 등록).
  useEffect(() => {
    const onKey = (e) => {
      if (!(e.metaKey || e.ctrlKey)) return;
      const k = e.key.toLowerCase();
      if (k === 'k') {
        e.preventDefault();
        setSearchPaletteOpen(true);
      } else if (k === 'n') {
        e.preventDefault();
        handleNewNote();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [handleNewNote]);

  // Phase 2B-3-backend Step 3b-2: EditorScreen 진입 중 노트 삭제 시 redirect.
  //   historyItems 변화 감지 — currentJobId 가 list 에서 사라지면 history 로 이동.
  //   초기 로드 중 (items 비어있을 때) 는 skip — false redirect 회피.
  //   반응적 패턴: bulk delete / 외부 sync 등 다른 trigger 에서도 동일 작동.
  useEffect(() => {
    if (route !== 'editor' || !currentJobId) return undefined;
    if (historyItems.length === 0) return undefined;
    const exists = historyItems.some((item) => item.job_id === currentJobId);
    if (!exists) {
      setRoute('history');
      if (window.showToast) window.showToast('노트가 삭제되었습니다');
    }
    return undefined;
  }, [route, currentJobId, historyItems]);

  return (
    <>
      <div className="gn-window">
        <div className="gn-body">
          <Sidebar
            route={route}
            onNavigate={handleSidebarNavigate}
            version={version}
            historyItems={historyItems}
            historyTotal={historyTotal}
            onLibraryNav={handleLibraryNav}
            onNewNote={handleNewNote}
          />
          <main className="gn-main">
            <TopBar
              route={route}
              historyContext={historyContext}
              onSearchOpen={openSearchPalette}
            />
            <div className="gn-content">{
            route === 'main'    ? (
              <MainScreen
                newNoteRequestKey={newNoteRequestKey}
                mainSession={mainSession}
                updateMainSession={updateMainSession}
                onPipelineStart={handlePipelineStart}
                onPipelineStop={handlePipelineStop}
              />
            ) :
            route === 'history' ? (
              <HistoryScreen
                key={`history-${historyFilterKey}`}
                items={historyItems}
                total={historyTotal}
                loading={historyLoading}
                error={historyError}
                onReload={loadHistory}
                onEditNote={navigateToEditor}
                initialFacets={historyFilter?.initialFacets}
                initialTimeWindow={historyFilter?.initialTimeWindow}
                initialExpandedGroup={historyFilter?.initialExpandedGroup}
                onFilterApplied={() => setHistoryFilter(null)}
                onHistoryRefresh={() => setHistoryRefreshKey((k) => k + 1)}
              />
            ) :
            route === 'editor' ? (
              <EditorScreen
                jobId={currentJobId}
                onBackToLibrary={() => setRoute('history')}
                onHistoryRefresh={() => setHistoryRefreshKey((k) => k + 1)}
              />
            ) :
            route === 'dashboard' ? (
              <DashboardScreen
                items={historyItems}
                total={historyTotal}
                loading={historyLoading}
                error={historyError}
                onReload={loadHistory}
              />
            ) :
            route === 'settings' ? (
              <SettingsScreen />
            ) :
            <ScreenPlaceholder route={route} />
          }</div>
          </main>
        </div>
      </div>
      <SearchPalette
        open={searchPaletteOpen}
        items={historyItems}
        onClose={closeSearchPalette}
        onSelect={handlePaletteSelect}
      />
      <div id="toast-container" className="toast-container" />
    </>
  );
}

window.App = App;
