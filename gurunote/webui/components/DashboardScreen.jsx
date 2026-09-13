/* SPDX-License-Identifier: Elastic-2.0
 * Copyright (c) 2026 GuruNote contributors.
 *
 * Phase 2B-6c: DashboardScreen — KPI + 분야별 + 의미 검색 + 월별 + 태그.
 *
 * Reference: docs/design/extracted/screens-editor-dashboard-settings.jsx:101-219
 *
 * 사용자 결정:
 *   - C-1 KPI 4번째: '실패율' (Reference 정합)
 *   - C-2 의미 검색 인덱스: disabled placeholder + 'Phase 3A (RAG) 에서 활성화' tooltip
 *     (즐겨찾기 disable 패턴 재활용 — Phase 2B-5a)
 *   - C-3 월별 추이: 12개월 axis (30일 daily 폐기)
 *   - C-4 태그 클라우드: 보존 — Row 2 우측
 *   - Layout: 2 row × (2fr | 1fr) — Row 1: 분야별(2)+의미검색(1) / Row 2: 월별(2)+태그(1)
 *
 * Frontend only — bridge 추가 작업 0. App.jsx 의 historyItems (lifting state)
 * 를 props 로 받아 통계 계산.
 *
 * Babel standalone global scope 회피: 모든 top-level const 는 DASH_ 접두사.
 */

const { useMemo, useState } = React;

/* === KPI ico 색 (Reference 정합) === */
const DASH_KPI_COLORS = {
  notes:    '#1a73e8',  // blue
  duration: '#188038',  // green
  avg:      '#e37400',  // orange
  failure:  '#7b5ac1',  // purple
};

/* === 분야별 색 팔레트 — 라벨 hash 로 deterministic 매핑 === */
const DASH_FIELD_PALETTE = [
  '#1a73e8',  // blue
  '#188038',  // green
  '#e37400',  // orange
  '#7b5ac1',  // purple
  '#d93880',  // pink
  '#00897b',  // teal
  '#5f6368',  // gray
  '#c5221f',  // red
];

function dashFieldColor(label) {
  let h = 0;
  for (const c of label) h = (h * 31 + c.charCodeAt(0)) & 0x7fffffff;
  return DASH_FIELD_PALETTE[h % DASH_FIELD_PALETTE.length];
}

/* === 통계 헬퍼 === */
function computeStats(items) {
  if (!items || items.length === 0) {
    return {
      total: 0, totalDuration: 0, avgDuration: 0,
      completedCount: 0, failedCount: 0, failurePercent: 0,
    };
  }
  let totalDuration = 0;
  let completedCount = 0;
  let failedCount = 0;
  for (const it of items) {
    if (it.duration_sec > 0) totalDuration += it.duration_sec;
    if (it.status === 'completed' || it.status === 'done') completedCount++;
    if (it.status === 'failed' || it.status === 'error') failedCount++;
  }
  return {
    total: items.length,
    totalDuration,
    avgDuration: items.length > 0 ? totalDuration / items.length : 0,
    completedCount,
    failedCount,
    failurePercent: items.length > 0 ? (failedCount / items.length) * 100 : 0,
  };
}

function fmtDurationLong(sec) {
  if (!sec || sec <= 0) return '0분';
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (h > 0) return `${h}시간 ${m}분`;
  return `${m}분`;
}

function fmtDurationShort(sec) {
  if (!sec || sec <= 0) return '0:00';
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function buildFieldDistribution(items, topN = 5) {
  const counts = new Map();
  for (const it of items) {
    if (it.field) counts.set(it.field, (counts.get(it.field) || 0) + 1);
  }
  return [...counts.entries()]
    .map(([label, count]) => ({ label, count, color: dashFieldColor(label) }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, 'ko'))
    .slice(0, topN);
}

function buildTagCloud(items, topN = 30) {
  const counts = new Map();
  for (const it of items) {
    for (const tag of (it.tags || [])) {
      if (tag) counts.set(tag, (counts.get(tag) || 0) + 1);
    }
  }
  return [...counts.entries()]
    .map(([label, count]) => ({ label, count }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, 'ko'))
    .slice(0, topN);
}

/* 최근 N일 daily aggregation (Toggle 의 'daily' 모드용) */
function buildTimeline(items, days = 30) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const buckets = [];
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    buckets.push({ date: d, count: 0 });
  }
  const startMs = buckets[0].date.getTime();
  for (const it of items) {
    if (!it.created_at) continue;
    const ts = new Date(it.created_at);
    if (isNaN(ts.getTime())) continue;
    const dayStart = new Date(ts);
    dayStart.setHours(0, 0, 0, 0);
    const ms = dayStart.getTime();
    if (ms < startMs) continue;
    const idx = Math.floor((ms - startMs) / (24 * 60 * 60 * 1000));
    if (idx >= 0 && idx < buckets.length) buckets[idx].count++;
  }
  return buckets;
}

/* 최근 12개월 monthly aggregation (Toggle 의 'monthly' 모드용) */
function buildMonthlyTrend(items, monthsBack = 12) {
  const today = new Date();
  today.setDate(1);
  today.setHours(0, 0, 0, 0);
  const buckets = [];
  for (let i = monthsBack - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setMonth(d.getMonth() - i);
    buckets.push({ year: d.getFullYear(), month: d.getMonth() + 1, count: 0 });
  }
  const idxOf = (y, m) => {
    for (let i = 0; i < buckets.length; i++) {
      if (buckets[i].year === y && buckets[i].month === m) return i;
    }
    return -1;
  };
  for (const it of items) {
    if (!it.created_at) continue;
    const d = new Date(it.created_at);
    if (isNaN(d.getTime())) continue;
    const i = idxOf(d.getFullYear(), d.getMonth() + 1);
    if (i >= 0) buckets[i].count++;
  }
  return buckets;
}

/* 이번 달 카운트 (KPI delta 용) */
function countThisMonth(items) {
  const now = new Date();
  const y = now.getFullYear();
  const m = now.getMonth();
  let c = 0;
  for (const it of items) {
    if (!it.created_at) continue;
    const d = new Date(it.created_at);
    if (isNaN(d.getTime())) continue;
    if (d.getFullYear() === y && d.getMonth() === m) c++;
  }
  return c;
}

/* === Components === */

/* KPI card — Reference 정합. 큰 숫자 + 컬러 ico + delta.
   showTrend=false 시 trending_up/down 아이콘 생략 (절대 카운트 같이 trend 의미가
   모호한 delta 용). */
function KPICard({ icon, label, value, delta, color, good, showTrend = true }) {
  return (
    <div className="kpi-card">
      <div
        className="kpi-card__ico"
        style={{ background: `${color}1a`, color }}
      >
        <span className="msi">{icon}</span>
      </div>
      <div className="kpi-card__value">{value}</div>
      <div className="kpi-card__label">{label}</div>
      {delta && (
        <div className={'kpi-card__delta' + (good ? ' kpi-card__delta--good' : '')}>
          {showTrend && (
            <span className="msi" style={{ fontSize: 14 }}>
              {delta.startsWith('-') ? 'trending_down' : 'trending_up'}
            </span>
          )}
          {delta}
        </div>
      )}
    </div>
  );
}

/* 분야별 분포 — 색상 dot + 가로 막대 + count */
function FieldDistribution({ data }) {
  if (data.length === 0) {
    return (
      <div className="dashboard-empty" style={{ padding: 'var(--sp-4)' }}>
        주제 데이터가 없습니다.
      </div>
    );
  }
  const max = data[0].count;
  return (
    <div className="bar-list">
      {data.map((row) => (
        <div key={row.label} className="bar-row">
          <span className="bar-row__label" title={row.label}>
            <span className="bar-row__dot" style={{ background: row.color }} />
            {row.label}
          </span>
          <div className="bar-row__track">
            <div
              className="bar-row__fill"
              style={{ width: `${(row.count / max) * 100}%`, background: row.color }}
            />
          </div>
          <span className="bar-row__count">{row.count}</span>
        </div>
      ))}
    </div>
  );
}

/* 의미 검색 인덱스 — gurunote.semantic 재배선 (B12).
   마운트 시 통계 로드, Rebuild 버튼 → bridge.rebuild_index. 선택 의존성
   (requirements-search.txt) 미설치 시 안내. */
function SemanticIndexCard() {
  const [info, setInfo] = useState(null);   // {available, built, model, num_chunks, num_jobs, built_at}
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    try {
      while (!window.pywebview?.api) {
        await new Promise((r) => setTimeout(r, 50));
      }
      const r = await window.pywebview.api.semantic_index_stats();
      if (r?.ok) setInfo(r);
    } catch (e) {
      console.warn('[SemanticIndexCard] stats:', e);
    }
  };
  useEffect(() => { refresh(); }, []);

  const handleRebuild = async () => {
    if (busy) return;
    setBusy(true);
    window.showToast?.('의미 검색 인덱스를 빌드합니다… (첫 실행 시 모델 ~117MB 다운로드)', 'info');
    try {
      const r = await window.pywebview.api.rebuild_index();
      if (r?.ok) {
        window.showToast?.(`인덱스 빌드 완료: ${r.num_jobs}개 노트 / ${r.num_chunks} chunk`, 'success');
        await refresh();
      } else {
        window.showToast?.(`빌드 실패: ${r?.error || '알 수 없는 오류'}`, 'error');
      }
    } catch (e) {
      window.showToast?.(`빌드 오류: ${e.message || e}`, 'error');
    } finally {
      setBusy(false);
    }
  };

  // 의존성 미설치 — 안내 (카드 자체에 표시, toast 아님).
  if (info && info.available === false) {
    return (
      <div className="semantic-card semantic-card--disabled">
        <div style={{ fontSize: 12, color: 'var(--gn-on-surface-muted)', lineHeight: 1.6, padding: '4px 0 10px' }}>
          의미 검색 의존성이 설치되지 않았습니다.<br />
          <code>pip install -r requirements-search.txt</code><br />
          설치 후 재실행하면 활성화됩니다.
        </div>
        <button type="button" className="btn btn--ghost btn--sm semantic-card__action" disabled>
          <span className="msi">refresh</span>
          Semantic Rebuild
        </button>
      </div>
    );
  }

  const built = info?.built;
  const fmt = (v) => (v === undefined || v === null || v === '' ? '—' : v);
  const builtAt = built && info?.built_at ? String(info.built_at).replace('T', ' ').slice(0, 16) : '—';

  return (
    <div className={'semantic-card' + (busy ? ' semantic-card--busy' : '')}>
      <div className="semantic-card__rows">
        <div className="semantic-card__row">
          <span className="semantic-card__k">모델</span>
          <span className="semantic-card__v">{built ? fmt(info?.model) : '—'}</span>
        </div>
        <div className="semantic-card__row">
          <span className="semantic-card__k">Chunks</span>
          <span className="semantic-card__v">{built ? fmt(info?.num_chunks) : '—'}</span>
        </div>
        <div className="semantic-card__row">
          <span className="semantic-card__k">작업 수</span>
          <span className="semantic-card__v">{built ? fmt(info?.num_jobs) : '—'}</span>
        </div>
        <div className="semantic-card__row">
          <span className="semantic-card__k">빌드 시각</span>
          <span className="semantic-card__v">{builtAt}</span>
        </div>
      </div>
      <button
        type="button"
        className="btn btn--ghost btn--sm semantic-card__action"
        onClick={handleRebuild}
        disabled={busy}
        title={built ? '인덱스 재빌드' : '인덱스 처음 빌드'}
      >
        <span className="msi">refresh</span>
        {busy ? '빌드 중…' : (built ? 'Semantic Rebuild' : '인덱스 빌드')}
      </button>
    </div>
  );
}

/* 일별 작업 추이 — 최근 N일 (default 30) flex-based 가로 bar 차트 */
function ActivityTimeline({ buckets }) {
  if (buckets.length === 0) return null;
  const max = Math.max(...buckets.map((b) => b.count), 1);
  const first = buckets[0].date;
  const last = buckets[buckets.length - 1].date;
  const middle = buckets[Math.floor(buckets.length / 2)].date;
  const fmtDate = (d) => `${d.getMonth() + 1}/${d.getDate()}`;
  return (
    <>
      <div className="timeline-chart">
        {buckets.map((b, i) => (
          <div
            key={i}
            className={'timeline-bar' + (b.count === 0 ? ' timeline-bar--empty' : '')}
            style={{ height: b.count === 0 ? '2px' : `${(b.count / max) * 100}%` }}
            title={`${fmtDate(b.date)} · ${b.count}개 노트`}
          />
        ))}
      </div>
      <div className="timeline-axis">
        <span>{fmtDate(first)}</span>
        <span>{fmtDate(middle)}</span>
        <span>{fmtDate(last)}</span>
      </div>
    </>
  );
}

/* 월별 작업 추이 — 최근 12개월 세로 bar */
function MonthlyTrend({ buckets }) {
  if (buckets.length === 0) return null;
  const max = Math.max(...buckets.map((b) => b.count), 1);
  return (
    <div className="month-chart">
      {buckets.map((b) => (
        <div key={`${b.year}-${b.month}`} className="month-col">
          <div
            className={'month-col__bar' + (b.count === 0 ? ' month-col__bar--empty' : '')}
            style={{ height: b.count === 0 ? '2px' : `${(b.count / max) * 100}%` }}
            title={`${b.year}년 ${b.month}월 · ${b.count}개`}
          />
          <span className="month-col__label">{b.month}월</span>
        </div>
      ))}
    </div>
  );
}

/* 태그 클라우드 — top 30, 빈도 비례 font-size */
function TagCloud({ tags }) {
  if (tags.length === 0) {
    return (
      <div className="dashboard-empty" style={{ padding: 'var(--sp-4)' }}>
        태그 데이터가 없습니다.
      </div>
    );
  }
  const max = tags[0].count;
  const min = tags[tags.length - 1].count;
  const range = Math.max(max - min, 1);
  const sizeFor = (count) => {
    const t = (count - min) / range;
    return (0.85 + t * 0.55).toFixed(2);
  };
  return (
    <div className="tag-cloud">
      {tags.map((tag) => (
        <span
          key={tag.label}
          className="tag-cloud__item"
          style={{ fontSize: `${sizeFor(tag.count)}em` }}
          title={`${tag.label} (${tag.count}회)`}
        >
          {tag.label}
          <span className="tag-cloud__count">{tag.count}</span>
        </span>
      ))}
    </div>
  );
}

/* === Card wrapper — dash-grid 안의 표준 카드.
   extra slot: head 우측에 toggle / 액션 버튼 등 배치 (segmented control 등). */
function DashCard({ icon, title, sub, span, extra, children }) {
  const style = span ? { gridColumn: `span ${span}` } : undefined;
  return (
    <div className="dash-card" style={style}>
      <div className="dash-card__head">
        <span className="msi dash-card__head-ico">{icon}</span>
        <h3 className="dash-card__head-title">{title}</h3>
        {sub && <span className="dash-card__head-sub">{sub}</span>}
        {extra && <div className="dash-card__head-extra">{extra}</div>}
      </div>
      <div className="dash-card__body">{children}</div>
    </div>
  );
}

/* === DashboardScreen === */
function DashboardScreen({ items, loading, error }) {
  // Phase 2B-6c-3: 작업 추이 axis toggle — daily(30일) / monthly(12개월).
  // Default 'daily' — 최근 활동 추적이 더 의미 있는 기본값 (사용자 결정).
  const [trendMode, setTrendMode] = useState('daily');

  const stats = useMemo(() => computeStats(items), [items]);
  const fieldData = useMemo(() => buildFieldDistribution(items, 5), [items]);
  const tagData = useMemo(() => buildTagCloud(items, 30), [items]);
  const dailyData = useMemo(() => buildTimeline(items, 30), [items]);
  const monthlyData = useMemo(() => buildMonthlyTrend(items, 12), [items]);
  const monthlyDelta = useMemo(() => countThisMonth(items), [items]);

  return (
    <div className="dashboard-screen">
      {loading && (
        <div className="dashboard-empty" style={{ color: 'var(--gn-on-surface-muted)' }}>
          불러오는 중...
        </div>
      )}
      {error && (
        <div className="dashboard-empty" style={{ color: 'var(--gn-danger)' }}>
          <span className="msi">error</span>
          <div>오류: {error}</div>
        </div>
      )}

      {!loading && stats.total === 0 && !error && (
        <div className="dashboard-empty">
          <span className="msi">analytics</span>
          <div>아직 통계를 표시할 노트가 없습니다.</div>
          <div style={{ fontSize: 12, marginTop: 8 }}>
            생성 화면에서 첫 노트를 만들어보세요.
          </div>
        </div>
      )}

      {stats.total > 0 && (
        <>
          {/* KPI row — 4 metric cards */}
          <div className="kpi-grid">
            <KPICard
              icon="library_books"
              label="총 노트"
              value={stats.total}
              delta={monthlyDelta > 0 ? `+${monthlyDelta} 이번 달` : null}
              color={DASH_KPI_COLORS.notes}
            />
            <KPICard
              icon="schedule"
              label="총 처리 시간"
              value={fmtDurationShort(stats.totalDuration)}
              delta={null}
              color={DASH_KPI_COLORS.duration}
            />
            <KPICard
              icon="timeline"
              label="평균 길이"
              value={fmtDurationShort(stats.avgDuration)}
              delta={null}
              color={DASH_KPI_COLORS.avg}
            />
            <KPICard
              icon="error_outline"
              label="실패율"
              value={`${stats.failurePercent.toFixed(1)}%`}
              delta={stats.failedCount > 0 ? `실패 ${stats.failedCount}건` : null}
              color={DASH_KPI_COLORS.failure}
              good={stats.failurePercent < 5}
              showTrend={false}
            />
          </div>

          {/* dash-grid: Row 1 (분야별 span2 / 의미검색 1) + Row 2 (월별 span2 / 태그 1) */}
          <div className="dash-grid">
            <DashCard icon="pie_chart" title="분야별 분포" sub="top 5" span={2}>
              <FieldDistribution data={fieldData} />
            </DashCard>
            <DashCard icon="auto_awesome" title="의미 검색 인덱스">
              <SemanticIndexCard />
            </DashCard>
            <DashCard
              icon="show_chart"
              title="작업 추이"
              sub={trendMode === 'daily' ? '최근 30일' : '최근 12개월'}
              span={2}
              extra={
                <div className="dash-toggle" role="radiogroup" aria-label="작업 추이 axis">
                  <button
                    type="button"
                    role="radio"
                    aria-checked={trendMode === 'daily'}
                    className={'dash-toggle__btn' + (trendMode === 'daily' ? ' dash-toggle__btn--active' : '')}
                    onClick={() => setTrendMode('daily')}
                  >
                    30일
                  </button>
                  <button
                    type="button"
                    role="radio"
                    aria-checked={trendMode === 'monthly'}
                    className={'dash-toggle__btn' + (trendMode === 'monthly' ? ' dash-toggle__btn--active' : '')}
                    onClick={() => setTrendMode('monthly')}
                  >
                    12개월
                  </button>
                </div>
              }
            >
              {trendMode === 'daily' ? (
                <ActivityTimeline buckets={dailyData} />
              ) : (
                <MonthlyTrend buckets={monthlyData} />
              )}
            </DashCard>
            <DashCard icon="sell" title="태그 클라우드" sub={`top ${tagData.length}`}>
              <TagCloud tags={tagData} />
            </DashCard>
          </div>
        </>
      )}
    </div>
  );
}

window.DashboardScreen = DashboardScreen;
