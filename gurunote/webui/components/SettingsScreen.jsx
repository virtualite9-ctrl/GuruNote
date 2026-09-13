/* SPDX-License-Identifier: Elastic-2.0
 * Copyright (c) 2026 GuruNote contributors.
 *
 * Phase 2B-4c-1: SettingsScreen — Reference 디자인 (v2 extracted) 기반.
 *
 * Reference: docs/design/extracted/screens-editor-dashboard-settings.jsx:224
 *
 * Layout: 좌 nav 6항목 + 우 content card.
 * Step 2B-4c-1 범위: LLM Provider 섹션 + STT 섹션 풀 신축, 나머지 4 섹션 placeholder.
 *   - Step 2B-4c-2: Obsidian + Notion 풀 신축
 *   - Step 2B-4c-3: 고급 (WHISPERX 등) + GuruNote 정보
 */

const { useState, useEffect, useCallback } = React;

const SETTINGS_NAV_ITEMS = [
  { id: 'llm',       icon: 'smart_toy', label: 'LLM Provider' },
  { id: 'stt',       icon: 'mic',       label: 'STT 엔진' },
  { id: 'obsidian',  icon: 'hub',       label: 'Obsidian' },
  { id: 'notion',    icon: 'cloud',     label: 'Notion' },
  { id: 'advanced',  icon: 'tune',      label: '고급' },
  { id: 'about',     icon: 'info',      label: 'GuruNote 정보' },
];

const SETTINGS_PROVIDERS = [
  { id: 'openai',             label: 'OpenAI',     color: '#10a37f', defaultModel: 'gpt-4o-mini' },
  { id: 'anthropic',          label: 'Anthropic',  color: '#d97757', defaultModel: 'claude-sonnet-4-20250514' },
  { id: 'gemini',             label: 'Gemini',     color: '#4285f4', defaultModel: 'gemini-2.5-flash' },
  { id: 'openai_compatible',  label: 'Local',      color: '#5f6368', defaultModel: 'Ollama / vLLM' },
];

/* === SecretInput — type=password + visibility 토글 + "[저장됨]" 마스킹 === */
function SecretInput({ value, onChange, isSet, placeholder, mono }) {
  const [shown, setShown] = useState(false);
  const isMasked = isSet && value === '';

  return (
    <div className="settings-field__input-wrap">
      <input
        type={shown ? 'text' : 'password'}
        className={'settings-field__input settings-field__input--has-toggle' + (mono ? ' settings-field__input--mono' : '')}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={isMasked ? '●●●●●●●● [저장됨]' : (placeholder || '')}
      />
      <button
        type="button"
        className="settings-field__toggle"
        onClick={() => setShown(!shown)}
        title={shown ? '숨기기' : '보기'}
      >
        <span className="msi">{shown ? 'visibility_off' : 'visibility'}</span>
      </button>
    </div>
  );
}

/* === Field — label + input wrapper === */
function Field({ label, help, children }) {
  return (
    <div className="settings-field">
      <div className="settings-field__label">{label}</div>
      {children}
      {help && <div className="settings-field__help">{help}</div>}
    </div>
  );
}

/* === LLM Provider Section === */
function SettingsLLM({ values, secretsSet, onChange, onSave, dirty }) {
  const [testResult, setTestResult] = useState(null);
  const [testing, setTesting] = useState(false);

  const provider = values.LLM_PROVIDER || 'openai_compatible';
  const activeProvider = SETTINGS_PROVIDERS.find((p) => p.id === provider) || SETTINGS_PROVIDERS[3];

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await window.pywebview.api.test_connection({ provider });
      setTestResult(result);
    } catch (e) {
      setTestResult({ ok: false, error: e.message });
    } finally {
      setTesting(false);
    }
  };

  // Provider 별 키 매핑 (UI 표시용)
  const providerFields = {
    openai:            { keyName: 'OPENAI_API_KEY',    modelName: 'OPENAI_MODEL',   baseName: 'OPENAI_BASE_URL' },
    anthropic:         { keyName: 'ANTHROPIC_API_KEY', modelName: 'ANTHROPIC_MODEL', baseName: null },
    gemini:            { keyName: 'GOOGLE_API_KEY',    modelName: 'GEMINI_MODEL',   baseName: null },
    openai_compatible: { keyName: 'OPENAI_API_KEY',    modelName: 'OPENAI_MODEL',   baseName: 'OPENAI_BASE_URL' },
  };
  const cur = providerFields[provider] || providerFields.openai_compatible;

  return (
    <>
      <div className="settings-content__header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)' }}>
          <div className="settings-section-icon">
            <span className="msi">smart_toy</span>
          </div>
          <div>
            <div className="settings-content__title">LLM Provider</div>
            <div className="settings-content__sub">번역 + 요약에 사용할 AI 모델 선택</div>
          </div>
        </div>
      </div>

      {/* Provider grid 4 카드 */}
      <div className="provider-grid">
        {SETTINGS_PROVIDERS.map((p) => (
          <button
            key={p.id}
            type="button"
            className={'provider-card' + (provider === p.id ? ' provider-card--active' : '')}
            onClick={() => onChange('LLM_PROVIDER', p.id)}
          >
            <span className="provider-card__dot" style={{ background: p.color }} />
            <span className="provider-card__name">{p.label}</span>
            <span className="provider-card__model">{p.defaultModel}</span>
            {provider === p.id && (
              <span className="msi provider-card__check">check_circle</span>
            )}
          </button>
        ))}
      </div>

      {/* API Key (provider 별 동적) */}
      <Field label={`${activeProvider.label} API Key`}>
        <SecretInput
          value={values[cur.keyName] || ''}
          onChange={(v) => onChange(cur.keyName, v)}
          isSet={secretsSet[cur.keyName]}
          placeholder={`${cur.keyName} 입력`}
          mono
        />
      </Field>

      {/* Base URL (openai_compatible 시만) */}
      {provider === 'openai_compatible' && cur.baseName && (
        <Field label="Base URL" help="Ollama / vLLM 등 OpenAI 호환 endpoint">
          <input
            type="text"
            className="settings-field__input settings-field__input--mono"
            value={values[cur.baseName] || ''}
            onChange={(e) => onChange(cur.baseName, e.target.value)}
            placeholder="http://localhost:11434/v1"
          />
        </Field>
      )}

      {/* Model */}
      <Field label="모델">
        <input
          type="text"
          className="settings-field__input settings-field__input--mono"
          value={values[cur.modelName] || ''}
          onChange={(e) => onChange(cur.modelName, e.target.value)}
          placeholder={activeProvider.defaultModel}
        />
      </Field>

      {/* 3 column: Temperature / 번역 Max / 요약 Max */}
      <div className="settings-field-row">
        <Field label="Temperature" help="0.0 ~ 1.0">
          <input
            type="text"
            className="settings-field__input settings-field__input--mono"
            value={values.LLM_TEMPERATURE || ''}
            onChange={(e) => onChange('LLM_TEMPERATURE', e.target.value)}
            placeholder="0.6"
          />
        </Field>
        <Field label="번역 Max Tokens">
          <input
            type="text"
            className="settings-field__input settings-field__input--mono"
            value={values.LLM_TRANSLATION_MAX_TOKENS || ''}
            onChange={(e) => onChange('LLM_TRANSLATION_MAX_TOKENS', e.target.value)}
            placeholder="8192"
          />
        </Field>
        <Field label="요약 Max Tokens">
          <input
            type="text"
            className="settings-field__input settings-field__input--mono"
            value={values.LLM_SUMMARY_MAX_TOKENS || ''}
            onChange={(e) => onChange('LLM_SUMMARY_MAX_TOKENS', e.target.value)}
            placeholder="4096"
          />
        </Field>
      </div>

      {/* Test result */}
      {testResult && (
        <div className={'test-result ' + (testResult.ok ? 'test-result--success' : 'test-result--error')}>
          <span className="msi">{testResult.ok ? 'check_circle' : 'error'}</span>
          <span>{testResult.message || testResult.error}</span>
        </div>
      )}

      {/* Action bar */}
      <div className="settings-actions">
        <button
          type="button"
          className="btn btn--ghost"
          onClick={handleTest}
          disabled={testing}
        >
          <span className="msi">wifi_tethering</span>
          {testing ? '테스트 중...' : '연결 테스트'}
        </button>
        <div className="settings-actions__spacer" />
        <button
          type="button"
          className="btn btn--primary"
          onClick={onSave}
          disabled={!dirty}
        >
          <span className="msi">save</span>
          저장 {dirty ? `(${dirty})` : ''}
        </button>
      </div>
    </>
  );
}

/* === STT Section === */
function SettingsSTT({ values, secretsSet, onChange, onSave, dirty }) {
  const [hardware, setHardware] = useState(null);
  const [detecting, setDetecting] = useState(false);

  const detectHardware = useCallback(async () => {
    setDetecting(true);
    try {
      const result = await window.pywebview.api.detect_hardware();
      setHardware(result);
    } catch (e) {
      console.error('[STT] detect_hardware:', e);
    } finally {
      setDetecting(false);
    }
  }, []);

  useEffect(() => {
    detectHardware();
  }, [detectHardware]);

  return (
    <>
      <div className="settings-content__header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)' }}>
          <div className="settings-section-icon">
            <span className="msi">mic</span>
          </div>
          <div>
            <div className="settings-content__title">STT 엔진</div>
            <div className="settings-content__sub">음성 → 텍스트 변환 (자동 감지)</div>
          </div>
        </div>
      </div>

      {/* Detect banner */}
      {hardware && (
        <div className={'detect-banner ' + (hardware.gpu?.available ? 'detect-banner--good' : '')}>
          <span className="msi detect-banner__icon">memory</span>
          <div className="detect-banner__body">
            <div className="detect-banner__title">{hardware.banner.split(' — ')[0]}</div>
            <div className="detect-banner__sub">{hardware.banner.split(' — ')[1] || ''}</div>
          </div>
          <div className="detect-banner__action">
            <button
              type="button"
              className="btn btn--ghost"
              onClick={detectHardware}
              disabled={detecting}
              style={{ height: 28, padding: '0 12px', fontSize: 12 }}
            >
              <span className="msi" style={{ fontSize: 14 }}>refresh</span>
              {detecting ? '감지 중...' : '재감지'}
            </button>
          </div>
        </div>
      )}

      {/* MLX Whisper 모델 */}
      <Field label="MLX Whisper 모델 (Apple Silicon)" help="Hugging Face 모델 ID">
        <input
          type="text"
          className="settings-field__input settings-field__input--mono"
          value={values.MLX_WHISPER_MODEL || ''}
          onChange={(e) => onChange('MLX_WHISPER_MODEL', e.target.value)}
          placeholder="mlx-community/whisper-large-v3-mlx"
        />
      </Field>

      {/* HuggingFace Token (화자 분리) */}
      <Field label="HuggingFace 토큰" help="화자 분리 (pyannote.audio) 모델 다운로드용">
        <SecretInput
          value={values.HUGGINGFACE_TOKEN || ''}
          onChange={(v) => onChange('HUGGINGFACE_TOKEN', v)}
          isSet={secretsSet.HUGGINGFACE_TOKEN || secretsSet.HF_TOKEN}
          placeholder="hf_..."
          mono
        />
      </Field>

      {/* Action bar */}
      <div className="settings-actions">
        <div className="settings-actions__spacer" />
        <button
          type="button"
          className="btn btn--primary"
          onClick={onSave}
          disabled={!dirty}
        >
          <span className="msi">save</span>
          저장 {dirty ? `(${dirty})` : ''}
        </button>
      </div>
    </>
  );
}

/* === Obsidian Section === */
function SettingsObsidian({ values, secretsSet, onChange, onSave, dirty }) {
  const [vaultInfo, setVaultInfo] = useState(null);
  const [detecting, setDetecting] = useState(false);

  const detectVault = useCallback(async () => {
    setDetecting(true);
    try {
      const result = await window.pywebview.api.detect_obsidian_vault();
      setVaultInfo(result);
    } catch (e) {
      console.error('[Obsidian] detect_obsidian_vault:', e);
    } finally {
      setDetecting(false);
    }
  }, []);

  useEffect(() => {
    detectVault();
  }, [detectVault]);

  const handleBrowse = async () => {
    try {
      const result = await window.pywebview.api.select_obsidian_vault_dir();
      if (result?.ok && !result.cancelled) {
        onChange('OBSIDIAN_VAULT_PATH', result.path);
        if (!result.valid_vault && window.showToast) {
          window.showToast('선택한 폴더에 .obsidian/ 가 없습니다 — Vault 가 아닐 수 있음', 'warning');
        }
      }
    } catch (e) {
      console.error('[Obsidian] select dir:', e);
      if (window.showToast) window.showToast(`폴더 선택 오류: ${e.message}`, 'error');
    }
  };

  const currentPath = values.OBSIDIAN_VAULT_PATH || '';

  return (
    <>
      <div className="settings-content__header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)' }}>
          <div className="settings-section-icon">
            <span className="msi">hub</span>
          </div>
          <div>
            <div className="settings-content__title">Obsidian Vault</div>
            <div className="settings-content__sub">노트 자동 저장 위치 (마크다운 출력)</div>
          </div>
        </div>
      </div>

      {/* Detect banner */}
      {vaultInfo && vaultInfo.detected && (
        <div className="detect-banner detect-banner--good">
          <span className="msi detect-banner__icon">check_circle</span>
          <div className="detect-banner__body">
            <div className="detect-banner__title">Vault 감지됨</div>
            <div className="detect-banner__sub" style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>
              {vaultInfo.path}
            </div>
          </div>
          <div className="detect-banner__action">
            <button
              type="button"
              className="btn btn--ghost"
              onClick={detectVault}
              disabled={detecting}
              style={{ height: 28, padding: '0 12px', fontSize: 12 }}
            >
              <span className="msi" style={{ fontSize: 14 }}>refresh</span>
              {detecting ? '감지 중...' : '재감지'}
            </button>
          </div>
        </div>
      )}
      {vaultInfo && !vaultInfo.detected && (
        <div className="detect-banner">
          <span className="msi detect-banner__icon">info</span>
          <div className="detect-banner__body">
            <div className="detect-banner__title">Vault 미감지</div>
            <div className="detect-banner__sub">
              아래 '찾아보기' 버튼으로 Vault 경로를 직접 선택하세요.
            </div>
          </div>
          <div className="detect-banner__action">
            <button
              type="button"
              className="btn btn--ghost"
              onClick={detectVault}
              disabled={detecting}
              style={{ height: 28, padding: '0 12px', fontSize: 12 }}
            >
              <span className="msi" style={{ fontSize: 14 }}>refresh</span>
              {detecting ? '감지 중...' : '재감지'}
            </button>
          </div>
        </div>
      )}

      {/* Vault Path */}
      <Field label="Vault 경로" help="Obsidian Vault 폴더 (.obsidian/ 가 있는 폴더)">
        <div style={{ display: 'flex', gap: 'var(--sp-2)' }}>
          <input
            type="text"
            className="settings-field__input settings-field__input--mono"
            value={currentPath}
            onChange={(e) => onChange('OBSIDIAN_VAULT_PATH', e.target.value)}
            placeholder="/Users/me/Documents/MyVault"
            style={{ flex: 1 }}
          />
          <button
            type="button"
            className="btn btn--ghost"
            onClick={handleBrowse}
            style={{ flexShrink: 0 }}
          >
            <span className="msi">folder_open</span>
            찾아보기
          </button>
        </div>
      </Field>

      {/* Subfolder */}
      <Field label="하위 폴더" help="Vault 내 GuruNote 노트 저장 폴더 (없으면 생성)">
        <input
          type="text"
          className="settings-field__input settings-field__input--mono"
          value={values.OBSIDIAN_SUBFOLDER || ''}
          onChange={(e) => onChange('OBSIDIAN_SUBFOLDER', e.target.value)}
          placeholder="GuruNote"
        />
      </Field>

      {/* Action bar */}
      <div className="settings-actions">
        <div className="settings-actions__spacer" />
        <button
          type="button"
          className="btn btn--primary"
          onClick={onSave}
          disabled={!dirty}
        >
          <span className="msi">save</span>
          저장 {dirty ? `(${dirty})` : ''}
        </button>
      </div>
    </>
  );
}

/* === Notion Section === */
function SettingsNotion({ values, secretsSet, onChange, onSave, dirty }) {
  return (
    <>
      <div className="settings-content__header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)' }}>
          <div className="settings-section-icon">
            <span className="msi">cloud</span>
          </div>
          <div>
            <div className="settings-content__title">Notion 통합</div>
            <div className="settings-content__sub">노트를 Notion 페이지/데이터베이스로 export</div>
          </div>
        </div>
      </div>

      {/* Integration Token */}
      <Field
        label="Integration Token"
        help="https://www.notion.so/my-integrations 에서 발급한 secret"
      >
        <SecretInput
          value={values.NOTION_TOKEN || ''}
          onChange={(v) => onChange('NOTION_TOKEN', v)}
          isSet={secretsSet.NOTION_TOKEN}
          placeholder="secret_..."
          mono
        />
      </Field>

      {/* Parent ID */}
      <Field
        label="Parent ID (UUID)"
        help="노트가 저장될 database 또는 page 의 UUID"
      >
        <input
          type="text"
          className="settings-field__input settings-field__input--mono"
          value={values.NOTION_PARENT_ID || ''}
          onChange={(e) => onChange('NOTION_PARENT_ID', e.target.value)}
          placeholder="1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d"
        />
      </Field>

      {/* Parent Type */}
      <Field label="Parent Type">
        <select
          className="settings-field__input settings-field__input--mono"
          value={values.NOTION_PARENT_TYPE || 'database'}
          onChange={(e) => onChange('NOTION_PARENT_TYPE', e.target.value)}
          style={{ height: 36, cursor: 'pointer' }}
        >
          <option value="database">database</option>
          <option value="page">page</option>
        </select>
      </Field>

      {/* Action bar */}
      <div className="settings-actions">
        <div className="settings-actions__spacer" />
        <button
          type="button"
          className="btn btn--primary"
          onClick={onSave}
          disabled={!dirty}
        >
          <span className="msi">save</span>
          저장 {dirty ? `(${dirty})` : ''}
        </button>
      </div>
    </>
  );
}

/* === Advanced Section === */
function SettingsAdvanced({ values, secretsSet, onChange, onSave, dirty }) {
  return (
    <>
      <div className="settings-content__header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)' }}>
          <div className="settings-section-icon">
            <span className="msi">tune</span>
          </div>
          <div>
            <div className="settings-content__title">고급</div>
            <div className="settings-content__sub">전문가용 설정 — 다른 LLM provider 키 + WhisperX (NVIDIA)</div>
          </div>
        </div>
      </div>

      {/* === Anthropic === */}
      <div className="settings-group">
        <div className="settings-group__title">Anthropic</div>
        <Field label="ANTHROPIC_API_KEY">
          <SecretInput
            value={values.ANTHROPIC_API_KEY || ''}
            onChange={(v) => onChange('ANTHROPIC_API_KEY', v)}
            isSet={secretsSet.ANTHROPIC_API_KEY}
            placeholder="sk-ant-..."
            mono
          />
        </Field>
        <Field label="ANTHROPIC_MODEL">
          <input
            type="text"
            className="settings-field__input settings-field__input--mono"
            value={values.ANTHROPIC_MODEL || ''}
            onChange={(e) => onChange('ANTHROPIC_MODEL', e.target.value)}
            placeholder="claude-sonnet-4-20250514"
          />
        </Field>
      </div>

      {/* === Gemini === */}
      <div className="settings-group">
        <div className="settings-group__title">Google Gemini</div>
        <Field label="GOOGLE_API_KEY">
          <SecretInput
            value={values.GOOGLE_API_KEY || ''}
            onChange={(v) => onChange('GOOGLE_API_KEY', v)}
            isSet={secretsSet.GOOGLE_API_KEY}
            placeholder="AIza..."
            mono
          />
        </Field>
        <Field label="GEMINI_MODEL">
          <input
            type="text"
            className="settings-field__input settings-field__input--mono"
            value={values.GEMINI_MODEL || ''}
            onChange={(e) => onChange('GEMINI_MODEL', e.target.value)}
            placeholder="gemini-2.5-flash"
          />
        </Field>
      </div>

      {/* === WhisperX === */}
      <div className="settings-group">
        <div className="settings-group__title">WhisperX (NVIDIA GPU 환경)</div>
        <div className="settings-group__sub">CUDA 가속 STT — Linux/Windows 환경에서 사용. Mac 에서는 MLX Whisper 사용 권장.</div>
        <div className="settings-field-row" style={{ gridTemplateColumns: '2fr 1fr' }}>
          <Field label="WHISPERX_MODEL">
            <input
              type="text"
              className="settings-field__input settings-field__input--mono"
              value={values.WHISPERX_MODEL || ''}
              onChange={(e) => onChange('WHISPERX_MODEL', e.target.value)}
              placeholder="distil-large-v3"
            />
          </Field>
          <Field label="WHISPERX_BATCH_SIZE">
            <input
              type="text"
              className="settings-field__input settings-field__input--mono"
              value={values.WHISPERX_BATCH_SIZE || ''}
              onChange={(e) => onChange('WHISPERX_BATCH_SIZE', e.target.value)}
              placeholder="16"
            />
          </Field>
        </div>
      </div>

      {/* === AssemblyAI === */}
      <div className="settings-group">
        <div className="settings-group__title">AssemblyAI (선택적 클라우드 STT)</div>
        <Field label="ASSEMBLYAI_API_KEY">
          <SecretInput
            value={values.ASSEMBLYAI_API_KEY || ''}
            onChange={(v) => onChange('ASSEMBLYAI_API_KEY', v)}
            isSet={secretsSet.ASSEMBLYAI_API_KEY}
            placeholder="AssemblyAI API key"
            mono
          />
        </Field>
      </div>

      {/* Action bar */}
      <div className="settings-actions">
        <div className="settings-actions__spacer" />
        <button
          type="button"
          className="btn btn--primary"
          onClick={onSave}
          disabled={!dirty}
        >
          <span className="msi">save</span>
          저장 {dirty ? `(${dirty})` : ''}
        </button>
      </div>
    </>
  );
}

/* === About Section === */
function SettingsAbout() {
  const [appInfo, setAppInfo] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        while (!window.pywebview?.api && !cancelled) {
          await new Promise((r) => setTimeout(r, 50));
        }
        if (cancelled) return;
        const result = await window.pywebview.api.get_app_info();
        if (!cancelled && result?.ok) setAppInfo(result);
      } catch (e) {
        console.error('[About] get_app_info:', e);
      }
    };
    load();
    return () => { cancelled = true; };
  }, []);

  const handleCheckUpdate = () => {
    if (window.showToast) {
      window.showToast('업데이트 확인 기능은 곧 추가됩니다 (Phase 2C 예정)', 'info');
    }
  };

  return (
    <>
      <div className="settings-content__header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)' }}>
          <div className="settings-section-icon">
            <span className="msi">info</span>
          </div>
          <div>
            <div className="settings-content__title">GuruNote 정보</div>
            <div className="settings-content__sub">버전 · 라이선스 · 저장소</div>
          </div>
        </div>
      </div>

      <div className="settings-about">
        <div className="settings-about__logo">
          <span>G</span>
        </div>
        <div className="settings-about__name">GuruNote</div>
        <div className="settings-about__version">
          v{appInfo?.version || '1.0.0.1'}
        </div>
        <div className="settings-about__desc">
          유튜브 링크 한 줄로 한국어 요약본을 생성합니다.
          음성 → 텍스트 → 번역 → 요약 → 마크다운까지, 로컬에서 끝까지.
        </div>

        <div className="settings-about__meta">
          <div className="settings-about__meta-row">
            <span className="settings-about__meta-label">라이선스</span>
            <span className="settings-about__meta-value">{appInfo?.license || 'Elastic License 2.0'}</span>
          </div>
          {appInfo?.github_url && (
            <div className="settings-about__meta-row">
              <span className="settings-about__meta-label">저장소</span>
              <a
                href={appInfo.github_url}
                target="_blank"
                rel="noopener noreferrer"
                className="settings-about__meta-link"
              >
                <span className="msi" style={{ fontSize: 14 }}>open_in_new</span>
                {appInfo.github_url.replace('https://', '')}
              </a>
            </div>
          )}
        </div>

        <button
          type="button"
          className="btn btn--tonal settings-about__update-btn"
          onClick={handleCheckUpdate}
        >
          <span className="msi">system_update</span>
          업데이트 확인
        </button>
      </div>
    </>
  );
}

/* === SettingsScreen === */
function SettingsScreen() {
  const [activeNav, setActiveNav] = useState('llm');
  const [values, setValues] = useState({});
  const [secretsSet, setSecretsSet] = useState({});
  const [originalValues, setOriginalValues] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Load settings
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        while (!window.pywebview?.api && !cancelled) {
          await new Promise((r) => setTimeout(r, 50));
        }
        if (cancelled) return;
        const result = await window.pywebview.api.get_settings();
        if (cancelled) return;
        if (!result?.ok) throw new Error(result?.error || 'failed');
        setValues(result.values || {});
        setSecretsSet(result.secrets_set || {});
        setOriginalValues(result.values || {});
      } catch (e) {
        if (!cancelled) setError(e.message || String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, []);

  const handleChange = useCallback((key, value) => {
    setValues((prev) => ({ ...prev, [key]: value }));
  }, []);

  // Dirty count — 변경된 키 수
  // Note: secret keys are not in values until the user types something, so any
  // typed-in secret counts as dirty too (originalValues[secret] is undefined →
  // '' fallback != typed value).
  const dirtyCount = (() => {
    let count = 0;
    const allKeys = new Set([...Object.keys(values), ...Object.keys(originalValues)]);
    for (const key of allKeys) {
      const cur = values[key] ?? '';
      const orig = originalValues[key] ?? '';
      if (cur !== orig) count++;
    }
    return count;
  })();

  const handleSave = async () => {
    if (dirtyCount === 0) return;

    // Patch — 변경된 키만
    const patch = {};
    const allKeys = new Set([...Object.keys(values), ...Object.keys(originalValues)]);
    for (const key of allKeys) {
      const cur = values[key] ?? '';
      const orig = originalValues[key] ?? '';
      if (cur !== orig) patch[key] = cur;
    }

    try {
      const result = await window.pywebview.api.save_settings(patch);
      if (result?.ok) {
        // 다시 로드 (secrets_set 업데이트 반영, secret 인풋 비우기)
        const fresh = await window.pywebview.api.get_settings();
        if (fresh?.ok) {
          setValues(fresh.values || {});
          setSecretsSet(fresh.secrets_set || {});
          setOriginalValues(fresh.values || {});
        }
        if (window.showToast) window.showToast(`${result.changed}개 설정 저장됨`, 'success');
      } else {
        if (window.showToast) window.showToast(`저장 실패: ${result?.error}`, 'error');
      }
    } catch (e) {
      if (window.showToast) window.showToast(`저장 오류: ${e.message}`, 'error');
    }
  };

  if (loading) {
    return (
      <div className="settings-screen">
        <div style={{ padding: 'var(--sp-6)', color: 'var(--gn-on-surface-muted)' }}>
          불러오는 중...
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="settings-screen">
        <div style={{ color: 'var(--gn-danger)', padding: 'var(--sp-4)' }}>오류: {error}</div>
      </div>
    );
  }

  return (
    <div className="settings-screen">
      <div className="settings-layout">
        {/* Nav */}
        <nav className="settings-nav">
          {SETTINGS_NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={'settings-nav-item' + (activeNav === item.id ? ' settings-nav-item--active' : '')}
              onClick={() => setActiveNav(item.id)}
            >
              <span className="msi settings-nav-item__icon">{item.icon}</span>
              <span className="settings-nav-item__label">{item.label}</span>
              <span className="msi settings-nav-item__chevron">chevron_right</span>
            </button>
          ))}
        </nav>

        {/* Content */}
        <div className="settings-content">
          {activeNav === 'llm' && (
            <SettingsLLM
              values={values}
              secretsSet={secretsSet}
              onChange={handleChange}
              onSave={handleSave}
              dirty={dirtyCount}
            />
          )}
          {activeNav === 'stt' && (
            <SettingsSTT
              values={values}
              secretsSet={secretsSet}
              onChange={handleChange}
              onSave={handleSave}
              dirty={dirtyCount}
            />
          )}
          {activeNav === 'obsidian' && (
            <SettingsObsidian
              values={values}
              secretsSet={secretsSet}
              onChange={handleChange}
              onSave={handleSave}
              dirty={dirtyCount}
            />
          )}
          {activeNav === 'notion' && (
            <SettingsNotion
              values={values}
              secretsSet={secretsSet}
              onChange={handleChange}
              onSave={handleSave}
              dirty={dirtyCount}
            />
          )}
          {activeNav === 'advanced' && (
            <SettingsAdvanced
              values={values}
              secretsSet={secretsSet}
              onChange={handleChange}
              onSave={handleSave}
              dirty={dirtyCount}
            />
          )}
          {activeNav === 'about' && (
            <SettingsAbout />
          )}
        </div>
      </div>
    </div>
  );
}

window.SettingsScreen = SettingsScreen;
