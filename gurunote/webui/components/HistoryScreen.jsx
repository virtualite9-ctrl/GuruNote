/* SPDX-License-Identifier: Elastic-2.0
 * Copyright (c) 2026 GuruNote contributors.
 *
 * Phase 2B-3a: HistoryScreen — 라이브러리 카드 그리드 (검색/필터 없이 정적).
 * 디자인 spec: docs/design/v2-reference.html (시각적 참고만).
 *
 * Bridge: list_history({limit, offset}) → {ok, total, items: [...]}
 *   각 item 에 video_id + thumbnail_url enrichment 적용됨 (bridge.py).
 *
 * Phase 2B-3b/c/d 에서 검색/필터/정렬/facet 추가.
 */

const { useState, useEffect, useMemo, useRef } = React;

/* === 출처 링크 / 다운로드 helpers (Phase 2B-4 wiring, B11) ===
   top-level 함수는 Babel standalone 에서 전역에 노출되므로 history 접두사로
   다른 컴포넌트 파일과의 충돌을 피한다. */

/* 출처 URL 을 시스템 브라우저로 연다 (bridge.open_external → webbrowser.open).
   pywebview 는 기본적으로 앱 webview 안에서 링크를 열어 UI 를 덮으므로 bridge 경유. */
async function historyOpenExternal(url) {
  if (!url) return;
  try {
    const r = await window.pywebview?.api?.open_external(url);
    if (r && r.ok === false) {
      window.showToast?.(`링크 열기 실패: ${r.error || '알 수 없는 오류'}`, 'error');
    }
  } catch (e) {
    window.showToast?.(`링크 열기 오류: ${e.message || e}`, 'error');
  }
}

/* 텍스트를 클립보드로 복사. navigator.clipboard 우선, 미지원 webview 는
   execCommand fallback (보안 컨텍스트 / user-gesture 제약 회피). */
async function historyCopyText(text) {
  if (!text) return;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      window.showToast?.('출처 URL을 복사했습니다.', 'success');
      return;
    }
  } catch (e) {
    /* navigator.clipboard 실패 → execCommand fallback 으로 진행 */
  }
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    window.showToast?.('출처 URL을 복사했습니다.', 'success');
  } catch (e) {
    window.showToast?.(`복사 실패: ${text}`, 'error');
  }
}

/* 노트 본문을 .md 파일로 저장. EditorScreen.handleDownload 와 동일하게
   이미 동작하는 bridge.save_result_as(네이티브 저장 다이얼로그) 를 재사용한다.
   - 상세 패널: 이미 로드된 detail.markdown 을 preloadedMarkdown 으로 전달
   - 목록 카드: 본문 미보유 → get_history_detail 로 먼저 로드 */
async function historyDownloadJob(item, preloadedMarkdown) {
  if (!item) return;
  const title = item.organized_title || item.title || 'GuruNote';
  const safeTitle = title.replace(/[\\/:*?"<>|]/g, '_').slice(0, 80) || 'GuruNote';
  try {
    let markdown = preloadedMarkdown;
    if (!markdown) {
      const d = await window.pywebview?.api?.get_history_detail({ job_id: item.job_id });
      if (!d?.ok || !d.markdown) {
        window.showToast?.(`다운로드 실패: ${d?.error || '본문을 불러올 수 없습니다'}`, 'error');
        return;
      }
      markdown = d.markdown;
    }
    const result = await window.pywebview.api.save_result_as({
      markdown,
      default_filename: `${safeTitle}.md`,
    });
    if (result?.cancelled) return;
    if (result?.path) {
      window.showToast?.(`저장됨: ${result.path}`, 'success');
    } else {
      window.showToast?.(`다운로드 실패: ${result?.error || '알 수 없는 오류'}`, 'error');
    }
  } catch (e) {
    console.error('[HistoryScreen] download:', e);
    window.showToast?.(`다운로드 오류: ${e.message || e}`, 'error');
  }
}

/* 노트를 Obsidian vault 로 내보낸다 (bridge.send_obsidian — RAG 유사 노트 wikilink 포함).
   카드 hub 아이콘 + 상세 패널 Obsidian 버튼 공용. (방향 3) */
async function historyExportObsidian(item) {
  if (!item?.job_id) return;
  window.showToast?.('Obsidian 으로 내보내는 중…', 'info');
  try {
    const r = await window.pywebview?.api?.send_obsidian(item.job_id);
    if (r?.ok) {
      const rc = r.related_count || 0;
      const link = rc ? ` (연관 노트 ${rc}개 링크)` : '';
      window.showToast?.(`Obsidian 저장됨: ${r.path}${link}`, 'success');
    } else if (r?.code === 'NO_VAULT') {
      window.showToast?.('Obsidian Vault 경로 미설정 — 설정 → Obsidian 에서 지정하세요.', 'error');
    } else {
      window.showToast?.(`Obsidian 내보내기 실패: ${r?.error || '알 수 없는 오류'}`, 'error');
    }
  } catch (e) {
    window.showToast?.(`Obsidian 오류: ${e.message || e}`, 'error');
  }
}

/* 통용 표기 새로고침 (A-2 ③) — 기존 노트의 auto 표기를 user 표기로 텍스트 치환.
   bridge.refresh_job_canonical 호출. 갱신 markdown 을 반환해 호출부가 화면 재로드 판단. */
async function historyRefreshCanonical(jobId) {
  if (!jobId) return null;
  try {
    const r = await window.pywebview?.api?.refresh_job_canonical(jobId);
    if (r?.ok) {
      if (r.changed > 0) {
        window.showToast?.(`통용 표기 ${r.changed}개 갱신됨`, 'success');
      } else {
        window.showToast?.('갱신할 표기 없음 (이미 최신)', 'info');
      }
      return r;
    }
    window.showToast?.(`새로고침 실패: ${r?.error || '알 수 없는 오류'}`, 'error');
  } catch (e) {
    window.showToast?.(`새로고침 오류: ${e.message || e}`, 'error');
  }
  return null;
}

/* created_at(저장 형식 = ISO UTC) 을 KST "YYYY-MM-DD HH:mm" 으로 표시.
   저장값은 불변 — 정렬(localeCompare/Date.parse)이 ISO 에 의존하므로 표시 단계만 변환.
   timeZone 'Asia/Seoul' 고정(시스템 로컬 무관) + hourCycle h23(자정 = 00). formatToParts
   로 부분을 뽑아 업로드일(2026-03-12)과 같은 결의 "-" 구분자로 조립. 파싱 실패/빈 값이면
   원본 그대로 반환 (Invalid Date / NaN 출력 회피 — RULE 12). */
const HISTORY_KST_DT_FMT = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Seoul',
  year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
});
function historyFormatCreatedAt(iso) {
  if (!iso) return iso || '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const p = {};
  for (const part of HISTORY_KST_DT_FMT.formatToParts(d)) p[part.type] = part.value;
  return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}`;
}

/* === Search helpers (Phase 2B-3b) === */
function useDebounced(value, delay) {
  const [debouncedValue, setDebouncedValue] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebouncedValue(value), delay);
    return () => clearTimeout(id);
  }, [value, delay]);
  return debouncedValue;
}

function filterItems(items, term) {
  if (!term) return items;
  const t = term.toLowerCase().trim();
  if (!t) return items;
  return items.filter((item) => {
    const title = (item.organized_title || item.title || '').toLowerCase();
    const uploader = (item.uploader || '').toLowerCase();
    const tags = (item.tags || []).join(' ').toLowerCase();
    return title.includes(t) || uploader.includes(t) || tags.includes(t);
  });
}

/* === Sort helpers (Phase 2B-3c) === */
const SORT_OPTIONS = [
  { id: 'latest',   label: '최신순' },
  { id: 'oldest',   label: '오래된순' },
  { id: 'duration', label: '길이 긴 순' },
  { id: 'title',    label: '제목 A-Z' },
];

function sortItems(items, sortBy) {
  // 비파괴 — 항상 새 배열 반환.
  const arr = [...items];
  switch (sortBy) {
    case 'oldest':
      return arr.sort((a, b) =>
        (a.created_at || '').localeCompare(b.created_at || ''));
    case 'duration':
      return arr.sort((a, b) =>
        (b.duration_sec || 0) - (a.duration_sec || 0));
    case 'title':
      return arr.sort((a, b) =>
        (a.organized_title || a.title || '').localeCompare(
          b.organized_title || b.title || '', 'ko'));
    case 'latest':
    default:
      return arr.sort((a, b) =>
        (b.created_at || '').localeCompare(a.created_at || ''));
  }
}

/* === Facet helpers (Phase 2B-3d) === */
const FACET_GROUPS = [
  { id: 'field',    icon: 'category', label: '주제' },
  { id: 'uploader', icon: 'person',   label: '인물' },
  { id: 'title',    icon: 'subject',  label: '제목' },
  { id: 'tag',      icon: 'sell',     label: '태그' },
];

/* Phase 2B-6d: field facet item 의 컬러 dot — Dashboard 의 컬러 매핑과 정합.
   Dashboard 의 DASH_FIELD_PALETTE / dashFieldColor 를 의도적으로 복제 (코드 12L,
   shared module 도입 전 단순 duplicate). 같은 label 은 두 화면에서 동일 색. */
const HISTORY_FIELD_PALETTE = [
  '#1a73e8', '#188038', '#e37400', '#7b5ac1',
  '#d93880', '#00897b', '#5f6368', '#c5221f',
];
function historyFieldColor(label) {
  let h = 0;
  for (const c of label) h = (h * 31 + c.charCodeAt(0)) & 0x7fffffff;
  return HISTORY_FIELD_PALETTE[h % HISTORY_FIELD_PALETTE.length];
}

function buildFacets(items) {
  const fields = new Map();
  const uploaders = new Map();
  const titles = new Set();
  const tags = new Map();

  for (const it of items) {
    if (it.field) fields.set(it.field, (fields.get(it.field) || 0) + 1);
    if (it.uploader) uploaders.set(it.uploader, (uploaders.get(it.uploader) || 0) + 1);
    if (it.organized_title) titles.add(it.organized_title);
    for (const tag of (it.tags || [])) {
      if (tag) tags.set(tag, (tags.get(tag) || 0) + 1);
    }
  }

  const toSortedArr = (map) =>
    [...map.entries()]
      .map(([label, count]) => ({ label, count }))
      .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, 'ko'));

  return {
    field:    toSortedArr(fields),
    uploader: toSortedArr(uploaders),
    title:    [...titles]
                .sort((a, b) => a.localeCompare(b, 'ko'))
                .map((t) => ({ label: t, count: 1 })),
    tag:      toSortedArr(tags),
  };
}

function SortChips({ value, onChange }) {
  return (
    <div className="sort-chips" role="radiogroup" aria-label="정렬 기준">
      {SORT_OPTIONS.map((opt) => (
        <button
          key={opt.id}
          type="button"
          role="radio"
          aria-checked={value === opt.id}
          className={'sort-chip' + (value === opt.id ? ' sort-chip--active' : '')}
          onClick={() => onChange(opt.id)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

/* === FacetPanel (Phase 2B-3d) === */
function FacetPanel({ items, activeFacets, onToggle, initialExpandedGroup }) {
  // Phase 2B-5a: groups start expanded by default (empty Set). initialExpandedGroup
  // is informational here — all groups already expand on mount, but we use it as
  // the trigger to scrollIntoView the named group's header.
  const [collapsed, setCollapsed] = useState(new Set());
  const [searchTerm, setSearchTerm] = useState('');
  const groupHeaderRefs = useRef({});

  const facets = useMemo(() => buildFacets(items), [items]);

  // Phase 2B-5a: scroll the requested group's header into view on mount.
  useEffect(() => {
    if (!initialExpandedGroup) return;
    const el = groupHeaderRefs.current[initialExpandedGroup];
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggleGroup = (id) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const filterFacetItems = (arr) => {
    const t = searchTerm.trim().toLowerCase();
    if (!t) return arr;
    return arr.filter((it) => it.label.toLowerCase().includes(t));
  };

  return (
    <aside className="history-screen__facets">
      <div className="facet-panel__header">
        <span className="msi" style={{ fontSize: 16 }}>account_tree</span>
        <span>내비게이션</span>
      </div>

      <input
        type="text"
        className="facet-panel__search"
        placeholder="트리 내 검색..."
        value={searchTerm}
        onChange={(e) => setSearchTerm(e.target.value)}
      />

      {FACET_GROUPS.map((group) => {
        const arr = filterFacetItems(facets[group.id] || []);
        if (arr.length === 0) return null;
        const isCollapsed = collapsed.has(group.id);
        return (
          <div
            key={group.id}
            className={'facet-group' + (isCollapsed ? ' facet-group--collapsed' : '')}
          >
            <button
              type="button"
              className="facet-group__header"
              ref={(el) => { groupHeaderRefs.current[group.id] = el; }}
              onClick={() => toggleGroup(group.id)}
              aria-expanded={!isCollapsed}
            >
              <span className="msi facet-group__icon">{group.icon}</span>
              <span>{group.label}</span>
              <span className="facet-group__count">{arr.length}</span>
              <span className="msi facet-group__chevron">expand_more</span>
            </button>
            <div className="facet-group__items">
              {arr.slice(0, 30).map((item) => {
                const facetKey = `${group.id}:${item.label}`;
                const active = activeFacets.has(facetKey);
                // Phase 2B-6d: field facet 만 deterministic 컬러 dot (Dashboard 정합).
                const dotStyle = group.id === 'field'
                  ? { background: historyFieldColor(item.label) }
                  : undefined;
                return (
                  <button
                    key={facetKey}
                    type="button"
                    className={'facet-item' + (active ? ' facet-item--active' : '')}
                    onClick={() => onToggle(group.id, item.label)}
                  >
                    <span
                      className={'facet-item__dot' + (group.id === 'field' ? ' facet-item__dot--field' : '')}
                      style={dotStyle}
                    />
                    <span className="facet-item__label" title={item.label}>{item.label}</span>
                    <span className="facet-item__count">{item.count}</span>
                  </button>
                );
              })}
            </div>
          </div>
        );
      })}
    </aside>
  );
}

/* === ActiveFilters chain (Phase 2B-3d) === */
function ActiveFilters({ search, activeFacets, onClearSearch, onResetFacet, onClearAll }) {
  const facetArr = [...activeFacets];
  if (!search && facetArr.length === 0) return null;

  return (
    <div className="active-filters">
      <span>적용된 필터:</span>
      {search && (
        <span className="active-filter">
          검색: "{search}"
          <button type="button" className="active-filter__remove" onClick={onClearSearch} aria-label="검색 제거">
            <span className="msi" style={{ fontSize: 12 }}>close</span>
          </button>
        </span>
      )}
      {facetArr.map((key) => {
        const idx = key.indexOf(':');
        const group = key.slice(0, idx);
        const label = key.slice(idx + 1);
        const groupLabel = (FACET_GROUPS.find((g) => g.id === group) || {}).label || group;
        return (
          <span key={key} className="active-filter">
            {groupLabel}: {label}
            <button type="button" className="active-filter__remove" onClick={() => onResetFacet(key)} aria-label="필터 제거">
              <span className="msi" style={{ fontSize: 12 }}>close</span>
            </button>
          </span>
        );
      })}
      <button type="button" className="active-filters__clear" onClick={onClearAll}>
        모두 비우기
      </button>
    </div>
  );
}

/* === DetailPanel (Phase 2B-3d) — slide-in modal === */
/* 의미 검색 결과 리스트 — 연관 노트(상세 패널) + "의미 검색" 칩(오버레이) 공용.
   results: [{job_id, score, title, preview, chunk_idx}], onSelect(job_id). (B12) */
function HistoryRelatedList({ results, loading, error, onSelect }) {
  if (loading) {
    return <div style={{ fontSize: 13, color: 'var(--gn-on-surface-muted)', padding: '8px 0' }}>의미 검색 중…</div>;
  }
  if (error) {
    return <div style={{ fontSize: 13, color: 'var(--gn-danger)', padding: '8px 0', whiteSpace: 'pre-wrap' }}>{error}</div>;
  }
  if (!results || results.length === 0) {
    return <div style={{ fontSize: 13, color: 'var(--gn-on-surface-muted)', padding: '8px 0' }}>연관 노트가 없습니다.</div>;
  }
  return (
    <div className="related-notes" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {results.map((r) => (
        <button
          key={`${r.job_id}-${r.chunk_idx}`}
          type="button"
          className="related-note"
          onClick={() => onSelect?.(r.job_id)}
          style={{
            textAlign: 'left', background: 'var(--gn-surface-2, rgba(255,255,255,0.04))',
            border: '1px solid var(--gn-border, rgba(255,255,255,0.08))', borderRadius: 8,
            padding: '8px 10px', cursor: 'pointer', font: 'inherit', color: 'inherit',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
            <span style={{ fontWeight: 600, fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {r.title || '제목 없음'}
            </span>
            <span style={{ fontSize: 12, color: 'var(--gn-primary, #3b82f6)', flexShrink: 0 }}>
              유사도 {Math.round((r.score || 0) * 100)}%
            </span>
          </div>
          <div style={{ fontSize: 12, color: 'var(--gn-on-surface-muted, #888)', marginTop: 4, lineHeight: 1.5, maxHeight: 40, overflow: 'hidden' }}>
            {r.preview}
          </div>
        </button>
      ))}
    </div>
  );
}

function DetailPanel({ item, onClose, onEdit, onOpenRelated }) {
  useEffect(() => {
    const onEsc = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onEsc);
    return () => document.removeEventListener('keydown', onEsc);
  }, [onClose]);

  // Phase 2B-3-backend Layer 7: 카드 클릭 시 본문 + 로그 fetch → ResultPanel 마운트.
  //   bridge.get_history_detail → korean_transcript / english_transcript / summary_html
  //   bridge.get_history_log → pipeline.log content (string)
  //   item 변경 시 다시 fetch (cancelled flag 으로 race 방어).
  const [detail, setDetail] = useState(null);
  const [logText, setLogText] = useState('');
  const [detailLoading, setDetailLoading] = useState(false);
  // A-2 ③ — 통용 표기 새로고침 후 본문 재로드 트리거.
  const [detailReloadKey, setDetailReloadKey] = useState(0);
  useEffect(() => {
    if (!item?.job_id) {
      setDetail(null);
      setLogText('');
      return undefined;
    }
    let cancelled = false;
    setDetailLoading(true);
    (async () => {
      try {
        while (!window.pywebview?.api && !cancelled) {
          await new Promise((r) => setTimeout(r, 50));
        }
        if (cancelled) return;
        const [d, l] = await Promise.all([
          window.pywebview.api.get_history_detail({ job_id: item.job_id }),
          window.pywebview.api.get_history_log({ job_id: item.job_id }),
        ]);
        if (cancelled) return;
        if (d?.ok) setDetail(d);
        if (l?.ok) setLogText(l.log || '');
      } catch (e) {
        console.warn('[DetailPanel] fetch failed:', e);
      } finally {
        if (!cancelled) setDetailLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [item?.job_id, detailReloadKey]);

  // A-2 ③ — 통용 표기 새로고침: auto→user 텍스트 치환 후 본문 재로드.
  const handleRefreshCanonical = async () => {
    if (!item?.job_id) return;
    const r = await historyRefreshCanonical(item.job_id);
    if (r?.ok && r.changed > 0) setDetailReloadKey((k) => k + 1);
  };

  // B12: 연관 노트 (의미 검색) — 버튼 클릭 시 현재 노트 본문으로 top-K 유사 검색.
  const [related, setRelated] = useState({ open: false, loading: false, results: null, error: '' });
  // item 이 바뀌면 연관 노트 패널 닫기 (stale 결과 방지).
  useEffect(() => { setRelated({ open: false, loading: false, results: null, error: '' }); }, [item?.job_id]);

  const handleRelated = async () => {
    if (!item?.job_id) return;
    setRelated({ open: true, loading: true, results: null, error: '' });
    try {
      const r = await window.pywebview.api.semantic_search({ job_id: item.job_id });
      if (r?.ok) {
        setRelated({ open: true, loading: false, results: r.results || [], error: '' });
      } else {
        setRelated({ open: true, loading: false, results: null, error: r?.error || '연관 노트 검색 실패' });
      }
    } catch (e) {
      setRelated({ open: true, loading: false, results: null, error: `오류: ${e.message || e}` });
    }
  };

  if (!item) return null;

  const title = item.organized_title || item.title || '제목 없음';
  const dur = item.duration_sec > 0
    ? `${Math.floor(item.duration_sec / 60)}:${String(Math.floor(item.duration_sec % 60)).padStart(2, '0')}`
    : null;

  return (
    <div className="detail-overlay" onClick={onClose}>
      <div className="detail-panel" onClick={(e) => e.stopPropagation()}>
        <div className="detail-panel__header">
          <h2 className="detail-panel__title" title={title}>{title}</h2>
          <button type="button" className="detail-panel__close" onClick={onClose} aria-label="닫기">
            <span className="msi">close</span>
          </button>
        </div>

        <div className="detail-panel__body">
          <div className="detail-thumb">
            {item.thumbnail_url && <img src={item.thumbnail_url} alt={title} />}
          </div>

          <dl className="detail-meta-grid">
            {item.field        && (<><dt>주제</dt><dd>{item.field}</dd></>)}
            {item.uploader     && (<><dt>업로더</dt><dd>{item.uploader}</dd></>)}
            {item.upload_date  && (<><dt>업로드일</dt><dd>{item.upload_date}</dd></>)}
            {item.created_at   && (<><dt>생성일</dt><dd>{historyFormatCreatedAt(item.created_at)}</dd></>)}
            {dur               && (<><dt>길이</dt><dd>{dur}</dd></>)}
            {item.num_speakers > 0 && (<><dt>화자 수</dt><dd>{item.num_speakers}명</dd></>)}
            {item.stt_engine   && (<><dt>STT</dt><dd>{item.stt_engine}</dd></>)}
            {item.llm_provider && (<><dt>LLM</dt><dd>{item.llm_provider}</dd></>)}
            {item.status       && (<><dt>상태</dt><dd>{item.status}</dd></>)}
            {item.source_url   && (
              <>
                <dt>출처</dt>
                <dd className="detail-source">
                  <button
                    type="button"
                    className="detail-source__link"
                    title="브라우저에서 열기"
                    onClick={() => historyOpenExternal(item.source_url)}
                    style={{
                      background: 'none', border: 'none', padding: 0,
                      color: 'var(--gn-primary, #3b82f6)', textDecoration: 'underline',
                      cursor: 'pointer', font: 'inherit', textAlign: 'left',
                      wordBreak: 'break-all',
                    }}
                  >
                    {item.source_url}
                  </button>
                  <button
                    type="button"
                    className="detail-source__copy"
                    title="URL 복사"
                    onClick={() => historyCopyText(item.source_url)}
                    style={{
                      background: 'none', border: 'none', padding: '0 0 0 6px',
                      color: 'var(--gn-on-surface-muted, #888)', cursor: 'pointer',
                      verticalAlign: 'middle',
                    }}
                  >
                    <span className="msi" style={{ fontSize: 16 }}>content_copy</span>
                  </button>
                </dd>
              </>
            )}
          </dl>

          {item.tags && item.tags.length > 0 && (
            <>
              <div className="detail-section-title">태그</div>
              <div className="detail-tags">
                {item.tags.map((tag) => (
                  <span key={tag} className="detail-tag">{tag}</span>
                ))}
              </div>
            </>
          )}

          {item.error_message && (
            <>
              <div className="detail-section-title" style={{ color: 'var(--gn-danger)' }}>오류 메시지</div>
              <div style={{ fontSize: 12, color: 'var(--gn-danger)', whiteSpace: 'pre-wrap' }}>
                {item.error_message}
              </div>
            </>
          )}

          <div className="detail-section-title">본문</div>
          {detailLoading && !detail && (
            <div style={{ color: 'var(--gn-on-surface-muted)', fontSize: 13 }}>
              불러오는 중…
            </div>
          )}
          {!detailLoading && !detail && (
            <div style={{ color: 'var(--gn-on-surface-muted)', fontSize: 13 }}>
              본문 데이터가 없습니다.
            </div>
          )}
          {detail && (
            <ResultPanel result={detail} log={logText} />
          )}

          {related.open && (
            <>
              <div className="detail-section-title">연관 노트</div>
              <HistoryRelatedList
                results={related.results}
                loading={related.loading}
                error={related.error}
                onSelect={(jid) => { if (onOpenRelated) onOpenRelated(jid); }}
              />
            </>
          )}
        </div>

        <div className="detail-actions-bar">
          <button type="button" className="btn btn--ghost" onClick={() => { if (onEdit) onEdit(item); onClose(); }}>
            <span className="msi">edit</span>
            편집
          </button>
          <button type="button" className="btn btn--ghost" onClick={() => historyDownloadJob(item, detail?.markdown)}>
            <span className="msi">download</span>
            다운로드
          </button>
          <button type="button" className="btn btn--ghost" onClick={() => historyExportObsidian(item)}>
            <span className="msi">hub</span>
            Obsidian
          </button>
          <button type="button" className="btn btn--ghost" onClick={handleRefreshCanonical} title="통용 표기(인명) 수정을 이 노트에 반영">
            <span className="msi">sync</span>
            표기 새로고침
          </button>
          <button type="button" className="btn btn--ghost" onClick={handleRelated} disabled={related.loading}>
            <span className="msi">device_hub</span>
            {related.loading ? '검색 중…' : '연관 노트'}
          </button>
        </div>
      </div>
    </div>
  );
}

const STATUS_BADGE = {
  completed: { label: '완료',    cls: 'job-card__badge--success' },
  done:      { label: '완료',    cls: 'job-card__badge--success' },
  failed:    { label: '실패',    cls: 'job-card__badge--error' },
  error:     { label: '실패',    cls: 'job-card__badge--error' },
  running:   { label: '진행 중', cls: 'job-card__badge--running' },
  stopped:   { label: '중지',    cls: 'job-card__badge--error' },
};

function formatDuration(sec) {
  if (sec == null || sec <= 0) return '';
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${m}:${String(s).padStart(2, '0')}`;
}

/* === DeleteConfirmDialog (Phase 2B-3-backend Step 3b-2) ===
 * Material-style modal — 노트 정보 표시 (제목 / 생성일 / 화자수 / 분야) + Esc /
 * backdrop 클릭 close + loading state. Autosave 영역 보존을 사용자 안내하지는
 * 않음 (CSS 단계에서 부수 메시지 추가 가능). item null 시 렌더 부재. */
function DeleteConfirmDialog({ item, onCancel, onConfirm, loading }) {
  useEffect(() => {
    if (!item) return undefined;
    const onKey = (e) => { if (e.key === 'Escape' && !loading) onCancel(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [item, onCancel, loading]);

  // B14: vault 에 이 노트의 Obsidian 사본(표식)이 있나 — 있을 때만 안내 표시.
  const [vaultCopy, setVaultCopy] = useState({ has: false, count: 0 });
  useEffect(() => {
    if (!item?.job_id) { setVaultCopy({ has: false, count: 0 }); return undefined; }
    let cancelled = false;
    (async () => {
      try {
        const r = await window.pywebview?.api?.has_vault_copy(item.job_id);
        if (!cancelled && r?.ok) setVaultCopy({ has: !!r.has_copy, count: r.count || 0 });
      } catch (e) {
        /* 확인 실패 — 안내만 생략, 삭제는 정상 진행 */
      }
    })();
    return () => { cancelled = true; };
  }, [item?.job_id]);

  if (!item) return null;
  const title = item.title || '(제목 없음)';
  const createdAt = item.created_at ? historyFormatCreatedAt(item.created_at) : '(생성일 부재)';
  const numSpeakers = item.num_speakers ?? '?';
  const field = item.field || '미분류';
  return (
    <div className="gn-confirm-overlay" onClick={() => !loading && onCancel()}>
      <div className="gn-confirm-card" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <h3>노트를 삭제하시겠습니까?</h3>
        <div className="gn-confirm-info">
          <div><strong>제목</strong><span>{title}</span></div>
          <div><strong>생성일</strong><span>{createdAt}</span></div>
          <div><strong>화자 수</strong><span>{numSpeakers}</span></div>
          <div><strong>분야</strong><span>{field}</span></div>
        </div>
        {vaultCopy.has && (
          <div
            className="gn-confirm-warn"
            style={{
              display: 'flex', alignItems: 'center', gap: 6, marginTop: 10,
              fontSize: 13, color: 'var(--gn-on-surface-muted, #888)',
            }}
          >
            <span className="msi" style={{ fontSize: 16 }}>hub</span>
            Obsidian 사본도 함께 삭제됩니다{vaultCopy.count > 1 ? ` (${vaultCopy.count}개)` : ''}.
          </div>
        )}
        <div className="gn-confirm-actions">
          <button type="button" className="btn btn--ghost" onClick={onCancel} disabled={loading}>
            취소
          </button>
          <button type="button" className="btn btn--danger" onClick={onConfirm} disabled={loading}>
            {loading ? '삭제 중…' : '삭제'}
          </button>
        </div>
      </div>
    </div>
  );
}

function JobCard({ item, onClick, onEdit, onDelete }) {
  const [imgError, setImgError] = useState(false);
  const status = STATUS_BADGE[item.status] || { label: item.status || '?', cls: '' };
  const title = item.organized_title || item.title || '제목 없음';
  const showImg = item.thumbnail_url && !imgError;

  return (
    <article className="job-card" onClick={() => onClick && onClick(item)}>
      <div className="job-card__thumb">
        {showImg ? (
          <img
            src={item.thumbnail_url}
            alt={title}
            onError={() => setImgError(true)}
            loading="lazy"
          />
        ) : (
          <div className="job-card__thumb-fallback">
            <span className="job-card__thumb-fallback-label">텍스트 온리</span>
            <div className="job-card__thumb-fallback-title">{title}</div>
          </div>
        )}
        <span className={'job-card__badge ' + status.cls}>{status.label}</span>
        {item.duration_sec > 0 && (
          <span className="job-card__duration">{formatDuration(item.duration_sec)}</span>
        )}
      </div>
      <div className="job-card__body">
        {item.field && <span className="job-card__field">{item.field}</span>}
        <h3 className="job-card__title">{title}</h3>
        <div className="job-card__meta">
          {item.uploader && <span>{item.uploader}</span>}
          {item.upload_date && <span>· {item.upload_date}</span>}
        </div>
        {item.tags && item.tags.length > 0 && (
          <div className="job-card__tags">
            {item.tags.slice(0, 4).map(tag => (
              <span key={tag} className="job-card__tag">{tag}</span>
            ))}
          </div>
        )}
      </div>
      <div className="job-card__actions" onClick={(e) => e.stopPropagation()}>
        <button
          type="button"
          className="job-action"
          title="열기"
          onClick={() => onClick && onClick(item)}
        >
          <span className="msi">open_in_new</span>
        </button>
        <button
          type="button"
          className="job-action"
          title="편집"
          onClick={() => onEdit && onEdit(item)}
        >
          <span className="msi">edit</span>
        </button>
        <button
          type="button"
          className="job-action"
          title="다운로드"
          onClick={() => historyDownloadJob(item, null)}
        >
          <span className="msi">download</span>
        </button>
        <button
          type="button"
          className="job-action"
          title="Obsidian 으로 내보내기"
          onClick={() => historyExportObsidian(item)}
        >
          <span className="msi">hub</span>
        </button>
        <button
          type="button"
          className="job-action job-action--more"
          title="삭제"
          onClick={() => onDelete && onDelete(item)}
        >
          <span className="msi">delete</span>
        </button>
      </div>
    </article>
  );
}

/**
 * HistoryScreen — props 로 items / loading / error / onReload 받음.
 * list_history 호출은 App.jsx 에서 lifting 하여 Sidebar 카운트와 공유.
 */
function HistoryScreen({
  items, total, loading, error, onReload, onEditNote,
  // Phase 2B-5a: 1-shot initial filter from sidebar library shortcuts
  initialFacets,           // Set<"groupId:label"> | undefined
  initialTimeWindow,       // null | number (days) | undefined
  initialExpandedGroup,    // 'tag' | 'field' | ... | undefined — auto-expand + scrollIntoView
  onFilterApplied,         // () => void — called once on mount so App.jsx can clear historyFilter
  // Phase 2B-3-backend Step 3b-2: delete 후 historyRefreshKey++ (App.jsx)
  onHistoryRefresh,        // () => void — bridge.delete_history 성공 시 호출
}) {
  // Phase 2B-3b: 검색 + chips state
  const [searchInput, setSearchInput] = useState('');
  const debouncedSearch = useDebounced(searchInput, 150);
  const filteredItems = useMemo(
    () => filterItems(items, debouncedSearch),
    [items, debouncedSearch]
  );

  // Phase 2B-3d: facet filter — Set of "groupId:label"
  const [activeFacets, setActiveFacets] = useState(
    () => (initialFacets ? new Set(initialFacets) : new Set())
  );

  // Phase 2B-5a: 시간 window filter — facet 와 별개의 dimension (AND)
  const [timeWindow, setTimeWindow] = useState(initialTimeWindow || null);

  // Phase 2B-5a: 1-shot reset — initial filter 를 mount 시 1회 적용 후 부모에 알림
  useEffect(() => {
    if (onFilterApplied) onFilterApplied();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleFacetToggle = (groupId, label) => {
    const key = `${groupId}:${label}`;
    setActiveFacets((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  const handleResetFacet = (key) => {
    setActiveFacets((prev) => {
      const next = new Set(prev);
      next.delete(key);
      return next;
    });
  };

  const handleClearAll = () => {
    setSearchInput('');
    setActiveFacets(new Set());
    setTimeWindow(null);
  };

  // facet filter — 검색 결과에 적용 (AND across groups)
  const facetFilteredItems = useMemo(() => {
    if (activeFacets.size === 0) return filteredItems;
    return filteredItems.filter((item) => {
      for (const key of activeFacets) {
        const idx = key.indexOf(':');
        const group = key.slice(0, idx);
        const label = key.slice(idx + 1);
        switch (group) {
          case 'field':    if (item.field !== label) return false; break;
          case 'uploader': if (item.uploader !== label) return false; break;
          case 'title':    if (item.organized_title !== label) return false; break;
          case 'tag':      if (!(item.tags || []).includes(label)) return false; break;
          default: break;
        }
      }
      return true;
    });
  }, [filteredItems, activeFacets]);

  // Phase 2B-5a: timeWindow filter — facet 결과 위에 적용 (별도 dimension)
  const timeWindowFilteredItems = useMemo(() => {
    if (!timeWindow) return facetFilteredItems;
    const cutoff = Date.now() - timeWindow * 24 * 60 * 60 * 1000;
    return facetFilteredItems.filter((it) => {
      const ts = it.created_at ? Date.parse(it.created_at) : NaN;
      return Number.isFinite(ts) && ts >= cutoff;
    });
  }, [facetFilteredItems, timeWindow]);

  // Phase 2B-3c: 정렬 state — timeWindow 결과 위에 적용 (filter chain 의 마지막)
  const [sortBy, setSortBy] = useState('latest');
  const sortedFinalItems = useMemo(
    () => sortItems(timeWindowFilteredItems, sortBy),
    [timeWindowFilteredItems, sortBy]
  );

  // Phase 2B-3d: detail view state
  const [detailItem, setDetailItem] = useState(null);

  // B12: "의미 검색" 칩 → semantic_search 오버레이 결과.
  const [semantic, setSemantic] = useState({ open: false, loading: false, results: null, error: '', query: '' });

  // Phase 2B-3-backend Step 3b-2: delete confirm dialog state
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleteLoading, setDeleteLoading] = useState(false);

  const handleDeleteRequest = (item) => setDeleteTarget(item);
  const handleDeleteCancel = () => { if (!deleteLoading) setDeleteTarget(null); };
  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return;
    setDeleteLoading(true);
    try {
      const result = await window.pywebview.api.delete_history(deleteTarget.job_id);
      if (result?.ok) {
        const label = deleteTarget.title || deleteTarget.job_id;
        const vd = result.vault_deleted || 0;
        const suffix = vd > 0 ? ` (Obsidian 사본 ${vd}개 포함)` : '';
        if (window.showToast) window.showToast(`삭제됨: ${label}${suffix}`);
        if (result.vault_error && window.showToast) {
          window.showToast('Obsidian 사본 삭제 실패 — 라이브러리는 삭제됨', 'warning');
        }
        setDeleteTarget(null);
        if (onHistoryRefresh) onHistoryRefresh();
      } else {
        const msg = result?.error || '알 수 없는 오류';
        if (window.showToast) window.showToast(`삭제 실패: ${msg}`, 'error');
      }
    } catch (e) {
      if (window.showToast) window.showToast(`삭제 오류: ${e?.message || e}`, 'error');
    } finally {
      setDeleteLoading(false);
    }
  };

  const handleChipClick = (chip) => {
    if (window.showToast) {
      // chip 이 이미 '검색' 으로 끝나면 ('의미 검색') 추가 ' 검색' 없이 조사만 — 'X 검색 검색은' 중복 회피.
      const tail = chip.endsWith('검색') ? '은' : ' 검색은';
      window.showToast(`${chip}${tail} Phase 3A (RAG) 에서 활성화됩니다.`);
    }
  };

  const handleCardClick = (item) => {
    setDetailItem(item);
  };

  // B12: 연관 노트 결과에서 노트 선택 → 해당 노트 상세 열기.
  const handleOpenRelated = (jid) => {
    const found = items.find((it) => it.job_id === jid);
    if (found) {
      setSemantic((s) => ({ ...s, open: false }));
      setDetailItem(found);
    } else {
      window.showToast?.('해당 노트를 목록에서 찾을 수 없습니다.', 'error');
    }
  };

  // B12: "의미 검색" 칩 → 현재 검색어로 semantic_search, 오버레이에 결과 표시.
  const handleSemanticSearch = async () => {
    const q = searchInput.trim();
    if (!q) {
      window.showToast?.('검색어를 입력한 뒤 의미 검색을 누르세요.', 'info');
      return;
    }
    setSemantic({ open: true, loading: true, results: null, error: '', query: q });
    try {
      const r = await window.pywebview.api.semantic_search({ query: q, top_k: 20 });
      if (r?.ok) {
        setSemantic({ open: true, loading: false, results: r.results || [], error: '', query: q });
      } else {
        setSemantic({ open: true, loading: false, results: null, error: r?.error || '의미 검색 실패', query: q });
      }
    } catch (e) {
      setSemantic({ open: true, loading: false, results: null, error: `오류: ${e.message || e}`, query: q });
    }
  };

  return (
    <div className="history-screen">
      <div className="history-toolbar">
        <div className="search-box">
          <span className="msi search-box__icon">search</span>
          <input
            type="text"
            className="search-box__input"
            placeholder="제목 / 업로더 / 태그 검색..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            autoComplete="off"
          />
          {searchInput && (
            <button
              type="button"
              className="search-box__clear"
              onClick={() => setSearchInput('')}
              aria-label="검색어 비우기"
            >
              <span className="msi" style={{ fontSize: 18 }}>close</span>
            </button>
          )}
        </div>

        <div className="filter-chips">
          <button
            type="button"
            className="filter-chip"
            onClick={() => handleChipClick('본문 포함')}
          >
            <span className="filter-chip__icon msi">description</span>
            본문 포함
          </button>
          <button
            type="button"
            className="filter-chip"
            onClick={handleSemanticSearch}
            title="검색어로 의미 유사 노트 찾기 (RAG)"
          >
            <span className="filter-chip__icon msi">psychology</span>
            의미 검색
          </button>
        </div>

        <SortChips value={sortBy} onChange={setSortBy} />

        {timeWindow && (
          <div className="hist-toolbar__chip hist-toolbar__chip--active">
            <span className="msi" style={{ fontSize: 14 }}>schedule</span>
            최근 {timeWindow}일
            <button
              type="button"
              className="hist-toolbar__chip-clear"
              onClick={() => setTimeWindow(null)}
              title="시간 필터 해제"
              aria-label="시간 필터 해제"
            >
              <span className="msi" style={{ fontSize: 14 }}>close</span>
            </button>
          </div>
        )}

        <button
          type="button"
          className="btn btn--ghost btn--sm history-toolbar__refresh"
          onClick={onReload}
          disabled={loading}
        >
          <span className="msi">refresh</span>
          새로고침
        </button>
      </div>

      <ActiveFilters
        search={debouncedSearch}
        activeFacets={activeFacets}
        onClearSearch={() => setSearchInput('')}
        onResetFacet={handleResetFacet}
        onClearAll={handleClearAll}
      />

      <div className="history-screen__body">
        <div className="history-screen__main">
          {debouncedSearch && (
            <div className="history-result-meta">
              "<b>{debouncedSearch}</b>" 검색 결과 <b>{sortedFinalItems.length}</b>개 · 전체 {items.length}개
            </div>
          )}

          {error && (
            <div className="history-empty" style={{ borderColor: 'var(--gn-danger)', color: 'var(--gn-danger)' }}>
              오류: {error}
            </div>
          )}

          {!loading && !error && items.length === 0 && (
            <div className="history-empty">
              아직 증류된 노트가 없습니다.<br />
              생성 화면에서 첫 노트를 만들어보세요.
            </div>
          )}

          {!loading && !error && items.length > 0 && (debouncedSearch || activeFacets.size > 0 || timeWindow) && sortedFinalItems.length === 0 && (
            <div className="history-empty">
              조건에 해당하는 노트가 없습니다.
            </div>
          )}

          {!loading && sortedFinalItems.length > 0 && (
            <div className="job-grid">
              {sortedFinalItems.map((item) => (
                <JobCard
                  key={item.job_id}
                  item={item}
                  onClick={handleCardClick}
                  onEdit={(it) => onEditNote && onEditNote(it.job_id)}
                  onDelete={handleDeleteRequest}
                />
              ))}
            </div>
          )}

          {loading && (
            <div className="history-loading">불러오는 중...</div>
          )}
        </div>

        <FacetPanel
          items={items}
          activeFacets={activeFacets}
          onToggle={handleFacetToggle}
          initialExpandedGroup={initialExpandedGroup}
        />
      </div>

      {detailItem && (
        <DetailPanel
          item={detailItem}
          onClose={() => setDetailItem(null)}
          onEdit={(it) => onEditNote && onEditNote(it.job_id)}
          onOpenRelated={handleOpenRelated}
        />
      )}

      {semantic.open && (
        <div
          className="detail-overlay"
          onClick={() => setSemantic((s) => ({ ...s, open: false }))}
        >
          <div
            className="detail-panel"
            onClick={(e) => e.stopPropagation()}
            style={{ maxWidth: 560 }}
          >
            <div className="detail-panel__header">
              <h2 className="detail-panel__title">의미 검색: “{semantic.query}”</h2>
              <button
                type="button"
                className="detail-panel__close"
                onClick={() => setSemantic((s) => ({ ...s, open: false }))}
                aria-label="닫기"
              >
                <span className="msi">close</span>
              </button>
            </div>
            <div className="detail-panel__body">
              <HistoryRelatedList
                results={semantic.results}
                loading={semantic.loading}
                error={semantic.error}
                onSelect={handleOpenRelated}
              />
            </div>
          </div>
        </div>
      )}

      <DeleteConfirmDialog
        item={deleteTarget}
        onCancel={handleDeleteCancel}
        onConfirm={handleDeleteConfirm}
        loading={deleteLoading}
      />
    </div>
  );
}

window.HistoryScreen = HistoryScreen;
