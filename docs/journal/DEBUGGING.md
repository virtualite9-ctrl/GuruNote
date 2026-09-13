# GuruNote 디버깅 추적 사슬

> 특정 catch (버그/이상)을 추적하면서 어디까지 갔는지. 본인 catch + 본인 측정 오판 정정 둘 다 정직히 기록. 사료: git log + session_history_digest + backlog.md.

## 1. 초기 catch (4/11~4/20, 본인 기억 2차 사료 일부)

### 1.1 VibeVoice-ASR RTX5090 32GB OOM (32분 처리)

**catch**: 5-step 파이프라인 (v0.1.0) primary STT가 VibeVoice-ASR. 본인 RTX5090 32GB GPU에서 OOM + 32분 처리 시간 catch.

**추적**:
1. VibeVoice 모델 자체가 32GB 부족 — 양자화 미지원
2. AssemblyAI fallback catch이지만 클라우드 의존 catch 부재
3. WhisperX 평가 → 정합 catch

**해결**: v0.4.0 WhisperX 전면 교체 (ADR-001).

### 1.2 WhisperX API 변경 — diarize 호출 형식

**catch**: WhisperX 버전별 diarize API 호출 형식 catch (시점 기록 부재 — 본인 기억).

**추적**: 라이브러리 변경 catch 후 본 코드 조정.

**해결**: gurunote/stt.py에 catch (commit history catch 부재 — 본인 기억).

### 1.3 torch CPU 덮어쓰기

**catch**: torch GPU 패키지 catch 시도 후 CPU 패키지가 덮어쓰는 catch (의존성 충돌).

**추적**: requirements.txt 명시 catch + uv lock 격리.

**해결**: gurunote/_net.py / requirements.txt catch (시점 기록 부재).

### 1.4 pyannote 401 / sample audio

**catch**: pyannote/speaker-diarization 401 (HuggingFace 토큰 필요) + 모델 동의 미동의 catch.

**추적**: HF_TOKEN 환경 변수 → settings dialog → fallback 단일 화자.

**해결**: stt_mlx.py + settings.py catch ("HF_TOKEN 미설정 — 화자 분리 건너뜁니다" 안내).

---

## 2. 4월말 ~ 5월 초 — Layer 1~15 추적 (Phase 2B-3-backend)

### 2.1 Layer 1: pyannote max_speakers + embedding drift

**catch (5/8~9)**: 본인이 "Phase 2B-3-backend Step 3b-2 보류 + 본질 진단 진입" (5/8 15:43, 세션 사료). pyannote 결과에서 같은 화자가 chunk마다 다른 cluster catch (long-form embedding drift).

**추적 사슬**:
1. 5/8 16:09 Layer 1 fix 진입
2. 5/9 00:12 **"Layer 1 fix 작동 부재 — 진단 진입"** — 본인 catch
3. 5/9 00:58 **"본질 catch 정정 — 라이브러리 vs 모델 영역 분리"** — 결정
4. 5/9 07:02 graceful skip 영역 확정
5. 5/9 16:30 `d9c5f0b` Layer 1 fix: pyannote max_speakers cap + embedding clustering 합산 (cosine similarity ≥ 0.75 시 자동 합산)

**해결**: pyannote.audio 4.0+ DiarizeOutput.speaker_embeddings 활용. 외부 모델 catch 부재 (cluster 후처리).

### 2.2 Layer 5+6: LLM hallucination cascading + STT noise filter

**catch (5/9)**: NVIDIA GTC 영상의 같은 timestamp + 같은 화자의 빈 segment 904회 반복 → markdown 본문 904 줄 leak.

**추적**:
1. STT 단계에서 빈/noise placeholder ('.', '-', '—' 등) 사전 차단
2. 동일 (start, speaker, text) dedup
3. STT 단계 차단 시 downstream (LLM/exporter/화자 분리) 모두 자동 graceful

**해결**: `1846098` Layer 5+6 fix (gurunote/stt_mlx.py:198 NOISE_PLACEHOLDERS + dedup_key).

### 2.3 Layer 8: Tiffany Janzen 표기 (잰슨→잔젠) ⭐

**catch (5/9 14:35, 세션 사료)**: **본인이 사용자 catch**: "티파니 잰슨이 아니라 티파니 잔젠 (Tiffany Janzen). 내가 실수했거나 클로드가 실수한 것 같다. 특별한 지정 없는 한 외국인 인명 표준 표기법에 따를 것."

**추적 사슬**:
1. 본인 daily 사용에서 잘못된 표기 catch
2. 5/9 23:30 `cf4a7bd` Layer 8: 고유명사 한국어 표기법 일관성 (전체 hotword 사전)
3. 5/9 23:39 `c2da2d3` Layer 8 fix-up: Tiffany Janzen 표준 표기 정정 (특정 인명)

**측정 오판/정정**: 5/17 13:58 본인 "티파니 잔젠 hallucinate 여부 재검증" — 추후 verify run에서도 catch 안 되는지 재확인.

**해결**: 외래어 표기법 표준 (문화체육관광부고시 제2017-14호) 적용. 이후 B06 Phase 2B-3-backend canonical translation으로 통합.

### 2.4 Layer 13: 화자 라벨 첫 등장 영문 병기

**catch (5/10)**: 본인 daily 사용에서 화자 라벨 (예: "젠슨 황")이 첫 등장 시 영문 병기 (Jensen Huang) 누락 catch.

**추적**:
1. 5/10 00:58 `027f243` Layer 13 fix: 화자 표기 한국어 + entity 영문 병기 명확화
2. **5/10 01:59 `12e1868` Layer 13 fix-up #2**: 화자 라벨 첫 등장 영문 병기 누락 fix — 1시간 catch 후 재패치

**해결**: LLM prompt rule 추가 — chunk reset 부재.

### 2.5 Layer 11/14/15: 한자/일본어 차단 + 본문 정합

**catch (5/10~11)**: LLM 출력에 한자 catch (예: "効率"), 일본어 가나 catch, 일부 일본어 마크다운 catch.

**추적**:
1. 5/10 19:01 `d30c782` Layer 11: Rule 11 한자/일본어 차단 + _SHARED_LANG_RULES 공통 상수
2. 5/10 20:27 `ee8b616` Layer 14: transcript line break 정규화
3. 5/11 00:34 `ece961e` Layer 15: METADATA prompt _SHARED_LANG_RULES inline
4. 5/11 21:41 `d7a726b` Layer 15 fix-up #1: title hallucination 가이드라인

**해결**: 다단계 rule 추가. 단 후속 Phase 3 (5/18)에서 코드 후처리로 대체 (Sub-path A+B+C).

---

## 3. 5월 중순 ~ 24 — 백엔드 품질 Phase 1~5 + 본 세션 (5/24)

### 3.1 Phase 1 Redesign — drift 본질 catch (5/13~16)

**catch**: LLM이 chunk N개 segment를 다른 line 수 (e.g. 25 expected → 23 outputs) 출력 catch (drift).

**추적**:
1. content drift catch (LLM이 본문 추가/누락)
2. truncation catch (finish_reason='length')
3. Index Mapping 시도 (zip 결정론 매핑)
4. json_schema strict (minItems/maxItems=N) 강제
5. segment count cap 15 (모델 attention tail drop catch — 6000 → 15 정정)

**측정 오판/정정**: 5/14 첫 시도 chunk char limit 6000 → 6000으로 줄여도 동일 gibberish. **본질 cause 부재** catch → segment count cap (15)이 본질 catch.

**해결**: `c68aab8` Phase 1 Redesign (5/16).

### 3.2 Phase 4a-1 xgrammar grammar-recovery loop (5/17)

**catch**: omlx 0.3.9 catch 후 xgrammar 0.2.0 catch + strict schema에서 일부 입력이 grammar-recovery loop 진입 → 8192 tokens 까지 rejected token 재샘플링 (slow chunk 245~281초).

**추적 사슬**:
1. 5/16 18:18 Phase 4a-1 마무리 옵션 A
2. 5/17 00:51 **commit 보류 — Verify 4회 반복 + 본질 cause 분석**
3. 5/17 10:42 stand-by 해제 (verify 분석 보조)
4. A-3 (strict 첫 시도 + 30초 timeout) 시도 — httpx read timeout 한계로 wall-clock 강제 부재 (dead code)
5. selective disable: 첫 strict → JSON parse fail 또는 finish_reason=length 시 json_object mode 전환

**측정 오판/정정**: A-3 timeout 시도가 작동 부재 — httpx read timeout이 wall-clock 강제 부재 catch. 본인 정직 catch (CHANGELOG/llm.py 주석에 기록).

**해결**: `b447a11` Phase 4a-1 selective disable + A-3 dead code revert.

### 3.3 B02 slow chunk wall-clock timeout (5/20, 5/23 R2 보강)

**catch**: chunk 9 / chunk 14가 250~281초 처리 (Phase 4a-1 selective disable 부재 시).

**추적**:
1. 5/20 16:25 `2ed4701` B02: ThreadPoolExecutor + future.result(timeout=60) wrap
2. 5/22 17:26 `988b4c1` B02 한계 1: wall-clock timeout 후 R1 padding fallback (`[⚠ timeout]` marker)
3. 5/23 12:07 `f314d6e` B02 수정: ThreadPoolExecutor `shutdown(wait=False, cancel_futures=True)` — 964초 thread 완료 대기 catch 부재
4. 5/23 13:11 `97855bd` B02 R2: 즉시 padding → strict retry 후 fallback

**측정 오판/정정**: 처음 `shutdown(wait=True)` catch는 964초 thread 완료 대기 catch → 즉시 raise 부재. 본인 catch + 수정.

**해결**: 본인 production catch 부재 (timeout 자연 발생 부재) — unit test 9/9 catch.

### 3.4 B06 entity_cache + 판카지 회귀 (5/20~22)

**catch (5/20 08:20, 세션 사료)**: **본인: "판카지 샤르마 회귀 진단 우선"** — 5/18 verify에서 판카지 191건 → B01 (entity_cache) 후 0건 → 5/20 회귀 catch (다시 발생).

**추적 사슬**:
1. 5/20 08:29 본인: "추가 verify 1~2회 — '판카지' 회귀 결정론 catch"
2. 5/20 09:13 본인: "두 사안 진단 — '판카지' 회귀 원인 + B02 복구 path 옵션"
3. entity_cache 디스크 저장 부재 catch (메모리만)
4. bootstrap path가 chunk 1 매번 재호출
5. canonicalize LLM 단계가 cache 표기를 변경 catch
6. 5/21 21:03 `4a8f281` B06: entity_cache 디스크 + 외래어 표기법 + canonicalize
7. 5/22 17:23 `9afcc93` B06 한계 2: canonicalize 미세 본문 변경 차단
8. 5/22 20:57 `f58d5f2` B06 보완 verify 3회 통과 (판카지 0건, 판카즈 샤르마 202~206건)

**해결**: schema v2 (entities + speakers) + `_detect_unexpected_changes` (의심 변경 로그).

### 3.5 2-pass 빈 output 복구 시퀀스 (5/23)

**catch**: 2-pass 2단계 strict json_schema에서 일부 outputs가 빈 string ("") catch.

**추적**:
1. 본인 verify에서 5건 빈 catch
2. retry (3회) catch 부족 — 모델이 같은 빈 출력
3. 1단계 line 수 정합 (N==len) catch 시 1단계 본문 활용 path
4. 1단계도 부재 시 segment 단독 재번역 (1-pass 방식)
5. 그래도 부재 시 `[번역 누락]` marker

**측정 오판/정정**: 5건 빈 → 복구 catch 후 marker 0건 catch. 단 본문 4건 timestamp 원본과 불일치 (정렬 어긋남) — **leak 아님 = 정렬 어긋남** catch. 본인 정직 catch.

**해결**: `599c94b` 3단계 안전망 (retry → 1단계 활용 → 단독 재번역 → marker).

### 3.6 D context leak → STT 잘림 발견 (5/24, Phase 5)

**catch (5/24)**: D segment 단독 번역 prototype catch ([320.7] / [365.7] / [574.0] 3 사례).

**추적 사슬 (긴 수렴)**:
1. **[320.7] 보고 catch 부족**: 본인이 처음 "context 흡수 leak"으로 catch — 실제는 target 원본 자체에 명사 catch (정확한 번역). **측정 오판 정직 catch**.
2. [365.7] / [574.0]: target STT 자체가 미완 끝 ("secure and" / "during a meeting,") catch — 모델이 의미 완결 욕구로 다음 segment 흡수
3. 본질 catch: **Whisper segment 잘림 = 음성 신호 기반 (의미 단위 부재)** — 같은 catch가 1-pass hallucinate + 2-pass SHIFT + 본문 가독성 4개 단계 공통 catch
4. F (D 직전 합치기) 우회 path → 모든 단계 catch 부재
5. **STT 직후 1회 재분할 path 채택** (모델 비의존 = 코드)
6. word-level 구두점 + 끝 검사 + 화자 우선 prototype
7. 1-pass timeout 76% 증가 catch → chunk_size 자동 축소 sweep
8. chunk_size 12 + char_limit=2000 catch
9. 다영상 6개 검증 → 5/6 catch, 1개 (F3QDC7HDMyg 38분 영상) 부족 catch → char_limit=2000 검증
10. 통합 본체 검증 (HEAD 527d2ea) — prototype = 통합 일치

**측정 오판/정정 정직 catch**:
- **leak [320.7] 보고 catch 부족** — 첫 보고에서 leak이라 판정, 실제는 원본 정확. 본인 catch + 보고서 정정.
- **2-pass cs=12 부분 데이터 보고** — process 중간 종료 catch 보고 → 실제는 정상 완료 catch. 본인 정정.
- 두 catch 모두 정직히 보고서에 기록.

**해결**: `527d2ea` Phase 5 통합 (재분할 + char_limit + envvar 토글) + 검증 산출물 보존 (`373d5db`).

---

## 4. 본 세션 (5/24) 긴 수렴 — 추적 사슬 한 줄

```
27b 느림 (5/22)
→ 환경 오염 (xgrammar 부재, omlx 0.3.9 catch)
→ xgrammar 복구 + 4 모델 재비교
→ 2-pass 옵션 A 시도 (자유 번역 → 정렬)
→ 화자 라벨 rule 1 prompt 충돌
→ 화자 코드 부착 (LLM 식별 1회)
→ pyannote 3.1 → community-1 (speaker confusion)
→ 빈 output 복구 시퀀스 (5건 → 복구)
→ 정렬 어긋남 (본문 4건 timestamp 원본과 불일치, leak 부재)
→ D segment 단독 번역 prototype
→ context leak [365.7] [574.0]
→ STT 잘림 본질 catch (음성 신호 vs 의미 단위)
→ word-level 의미 단위 재분할
→ 1-pass timeout 증가 (긴 영상)
→ chunk_size 자동 축소 sweep
→ 다영상 6개 견고성 검증
→ F3QDC7HDMyg 38분 영상 catch 부족
→ char_limit=2000 검증
→ 통합 본체 검증 (모델 비의존 hardness 도달)
→ daily 검증 영상 2개 토글 on (5/24 저녁, `6dc9934`)
→ default on 결정 (off 안전망 유지)
→ v1.0.0.0 선언 + README 60% 재작성 (`2971939`)
→ main 통합 시 unrelated histories 발견 (4bcbee6 vs af50c2e)
→ archive/main-pre-cli 보존 + force-with-lease 통일
```

## 4-1. Phase 5 마무리 (5/24, `6dc9934`) — 짧은 추적

**daily 검증 영상 2 개 토글 on 측정**:
- xKK5ze3FukQ (Boston Dynamics, 5.7 분): 96 → 49 segments (-49 %), timeout 0, CJK 0, **5 명 화자 중 3 명만 bootstrap 식별** — 메타데이터 한계 (백로그 B08 등록)
- zNuOOMM20Tk (NVIDIA Podcast, 33.4 분): 586 → 294 segments (-50 %), timeout 0, CJK 0, 2/2 화자 식별

**결정 사슬**:
1. 토글 on 결과 통과 → default 전환 후보
2. test 2 건 회귀 — `test_default_off_uses_one_pass` (`delenv` 가정) 가 default on 으로 변경 시 깨짐
3. test 의도 갱신: `test_explicit_off_uses_one_pass` (env=`0` 명시 시 1-pass) + `test_env_default_on` (env 부재 시 `1`)
4. 183 tests passed → commit + push

## 4-2. v1.0.0.0 + main 통합 (5/24 저녁) — 사전 점검 + 안전망

**gui.py/app.py legacy 이동 검토 → 결정적 의존성 사전 발견**:
- 초기 의도: gui.py / app.py 둘 다 `docs/legacy/` 이동
- 참조 스캔 결과: `gurunote/webui/session.py:67` 에 `from gui import PipelineWorker` — React UI 가 옛 CustomTkinter UI 파일의 클래스를 import
- 진단: `gui.py` (CustomTkinter) 안에 `PipelineWorker` 클래스가 들어있고, React UI 가 그걸 그대로 사용. legacy 이동 시 React UI 깨짐.
- 결정 (Path C, ADR-013): 파일 이동 0, README/안내만 갱신. `PipelineWorker` 분리는 백로그 B09.

**main 통합 시 unrelated histories 발견**:
1. `git fetch origin` 후 `git log --left-right --graph origin/main...redesign/tailwind-v2` — `>` 만 보임, `<` 부재
2. `git merge-base origin/main redesign/tailwind-v2` — **빈 결과 반환**
3. `git log --reverse` 양쪽 첫 commit: main `4bcbee6 Initial commit` vs redesign `af50c2e Initial commit` — 같은 메시지, 다른 hash
4. 진단: 두 브랜치가 별도 `git init` 으로 시작한 별개 트리. 공통 조상 부재. 본인 기억으로는 4/19 직후 웹 Claude → 로컬 CLI Claude Code 전환 시 환경 변경.
5. STOP RULE 발동 — 본인 결정 path 4 가지 제시 후 본인 선택 (옛 main archive 보존 + force-with-lease).

**안전망 시퀀스 (force push 전 필수)**:
1. `git branch archive/main-pre-cli origin/main`
2. `git push origin archive/main-pre-cli` → `9b6c62...` 확인 (211 commit, root `4bcbee6` 도달)
3. `git merge-base --is-ancestor 4bcbee6 archive/main-pre-cli` → 통과
4. `git checkout main && git reset --hard redesign/tailwind-v2`
5. `git push origin main --force-with-lease` → `+ 9b6c621...2971939 main -> main (forced update)` 성공

**해결**: ADR-012 안전망 보존 + force-with-lease 통일.

---

## 5. 패턴 정리

### 본인 catch 시점 (사용자 daily 사용 catch)

- **5/9 14:35**: Tiffany Janzen 표기 (잰슨→잔젠)
- **5/20 08:20**: 판카지 샤르마 회귀
- **5/14 09:36**: 정전 대비 HANDOFF
- 다수 의 catch — Layer 9/13/14/15 본인 사용 catch 동기

### 본질 catch 정정 (본인이 catch 부재 → 진단 → 정정)

- 5/9 Layer 1 작동 부재 → "라이브러리 vs 모델 영역 분리" 정정
- 5/14 Phase 1 chunk char 6000 가설 오류 → segment count cap 15 정정
- 5/17 Phase 4a-1 A-3 timeout 부재 → selective disable 채택
- 5/24 [320.7] leak 오판 → 원본 catch + 본인 정정

### 측정 오판 정직 catch (보고서에 catch)

- 5/24 [320.7] leak 부재 — 첫 보고 정정
- 5/24 2-pass cs=12 process 중간 종료 보고 → 정상 완료 — 본인 정정
- 5/28 타임스탬프 토글을 exporter(데이터) 층에 붙인 적용 지점 오판 → revert → 뷰어(표시) 층 재구현 (§7)
- 5/29 자동 내보내기 "성공 토스트 누락 버그" 보고 → 계측으로 r=ok:true 확인, 4초 표시 안에 놓친 인지 문제 = 버그 아님 (§8)

## 6. v1.0.0.6~0.7 인명/고유명사 품질 (5/26)

**진단 (read-only)**: daily 노트에서 두 종류 오류 — (A) 음차 방향 "팰머 러커이/리크 리더"(통용은 팔머 럭키/릭 리더), (B) 영문 병기 철자 "안두릴(Danduril)"(원문 Anduril). 코드 추적으로 원인 분리:
- (A) 통용 dict 미수록 인명 → LLM 이 외래어 표기법 규칙(`llm.py:144`)으로 철자 추정 → `entity_cache` 가 그 첫 표기를 first-seen 고정(`_extract_entities` 가 LLM 출력 prefix 에서 harvest) → **"일관되게 틀림"** (340/280 회 변형 0 은 캐시가 일관성만 보장한 결과).
- (B) 원본 제목·다운로드 로그는 Anduril 정확, **LLM 생성 organized_title 이 Danduril** → STT 아님, 번역 단계 자유 생성 오염. `summarize/extract_metadata` 가 원본 제목(정답)을 입력받고도 오염 → 소스를 프롬프트에 넣는 것만으론 부족, 능동 검증 필요.

**B 구현 중 함정 2건** (검증으로 catch):
1. **소유격 토큰화 함정** — 소스에서 영문 단어 풀을 `[A-Za-z][A-Za-z0-9.\-']*` 로 뽑으니 `Anduril's` 가 한 토큰 → standalone `Anduril` 부재 → "Danduril" 의 difflib 매칭 실패(생략). **순수 알파벳 `[A-Za-z]+` 분리**로 `Anduril's` → `Anduril`+`s` 해결.
2. **difflib 대소문자 함정** — `get_close_matches` 가 대소문자 구분이라 "Danduril"(대문자 D) vs "Anduril"(대문자 A) 의 a/A 케이스 불일치로 ratio 0.8 < 0.84 → 매칭 실패. **소문자로 매칭 후 케이싱 복원** (case_map) → ratio 0.93, 교정 성공.

**해결**: (A) `77dd6b0` 프롬프트 Rule 10 우선순위 역전. (B) `8f836a0` `_correct_english_annotations` 결정론적 소스 검증. 둘 다 end-to-end 동시 확인 (팔머 럭키/릭 리더 + Anduril 정확/Danduril 0).

> 프로세스 메모: B14 삭제 동기화 검증 시 `delete_history`(실제 job 삭제) REPL 호출이 prod 데이터 보호 분류기에 차단됨 — vault 측 `delete_from_vault` 독립 검증(임시 vault)으로 대체. 정직 기록.

---

## 7. 타임스탬프 토글 — 적용 지점 오판 → revert → 재구현 (v1.0.0.21, 5/28~29)

**현상**: 뷰어에서 한국어·영어 원문의 `[MM:SS]` 타임스탬프를 화면에서만 켜고 끄는 토글이 필요.

**추적 사슬**:
1. **첫 구현 — 적용 지점 오판** (`9a12566`, "전체 스크립트 타임스탬프 표시 토글 (설정)"): 토글을 설정 + exporter 경로에 붙임. 의도는 "뷰어 표시 단계"에서만 끄는 것(원본 불변)인데, 적용 지점이 어긋남.
2. **정직한 되돌림** (`c3b58bb` Revert): 잘못 적용한 커밋을 git revert 로 깔끔히 되돌림(부분 수선 대신 통째 revert).
3. **뷰어판 재구현** (`ca9ebf1`): `ResultPanel` 의 useState 로 한·영 탭에서만, 표시 직전 정규식으로 `[MM:SS]` 만 떼어냄. 화자명·원본(result.md) 불변.
4. 같은 묶음에서 본문 **드래그 복사** 불가도 수정(`26b3f2a`, `user-select: text` 명시).

**측정/적용 오판 정정**: "표시 토글"을 데이터(exporter) 층에 붙인 것이 오판. 표시 전용 기능은 표시 층(뷰어)에만 둬야 원본이 안전하다 — revert 후 뷰어판으로 바로잡음. 두 commit(오판 + revert)을 history 에 남겨 추적 가능.

## 8. 자동 내보내기 토스트 "버그 아님" 규명 + temperature 한계 (5/29)

**현상 보고**: 자동 내보내기가 vault 에 .md 는 만드는데 "성공" 토스트가 안 뜬다고 보고됨. 수동 버튼은 정상.

**추적 사슬**:
1. 정적 코드 분석 — 성공 토스트(`App.jsx`)와 NO_VAULT 토스트가 같은 if/else 사슬·같은 await 깊이. 같은 `showToast`·같은 컨테이너(항상 mount). 코드 논리상 새 job_id 첫 내보내기는 성공 분기에 들어가야 함 → **정적으로 모순**.
2. **임시 계측** — await 직후 반환값 `r` 을 토스트로 노출(v1.0.0.26 직전, `bc830a0`).
3. 실측 — 새 영상 첫 자동 내보내기에서 성공 토스트(초록 보더)가 **정상으로 떴음**. 토스트가 4초 후 사라져 사용자가 그 순간 놓친 것 = **버그 아님**.
4. 역할을 마친 계측 제거 + 타입별 좌측 보더 시각 구분 영구화(`a05925c`, ADR-022) — 이후 성공/건너뜀/실패를 색으로 구분.

**measurement 오판 정정**: "토스트 누락 버그"로 보고됐으나 실제는 표시 시간(4초) 안에 놓친 인지 문제. 계측으로 r=ok:true 확인 후 "버그 아님" 확정 — 코드 수정 0.

**별건 — temperature 0.6 품질 편차 (드러켄밀러 재처리)**: 같은 영상 재처리에서 temperature 0.6 에서도 `formidable`/`brilliant`/`Rates` 영어 누출 + 원문에 없는 "제롬 파월" 환각 재확인. ADR-019(0.6 유지) 의 한계 증거. 프롬프트·temperature 로는 고유명사 오류를 못 막음 → 검색 그라운딩(ADR-020) + 요약 충실도(B22) 대상.

---

**자료 출처**: 1.x는 본인 기억 2차 사료 + git/CHANGELOG. 2.x/3.x는 session_history_digest + git log + backlog.md 1차/혼합. 4/5는 본 세션 본인 catch. 6은 5/26 본 세션 진단·구현 catch.
