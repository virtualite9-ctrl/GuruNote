---
name: gurunote
description: "Use when turning a video or audio source into Korean notes, or when searching notes already made."
license: Elastic-2.0
compatibility: Agent Skills
metadata:
  version: "1.0.0"
  source: "GuruNote"
---
# GuruNote — 영상·오디오를 한국어 노트로

## 적용할 때
유튜브 링크나 로컬 음성/영상 파일을 한국어 노트(번역 + 요약 + 원문 스크립트)로 바꿀 때,
또는 이미 만들어 둔 노트를 찾을 때 쓴다. 자막만 뽑는 도구가 아니라 화자 분리 STT →
번역 → 요약 → 마크다운까지 하나로 처리한다.

## 두 가지 사용 경로

**MCP 서버** — `gurunote-mcp` (stdio). `pip install -e ".[mcp]"` 후 사용한다.
도구: `note_start` / `note_status` / `note_stop` / `note_jobs` / `history` /
`history_detail` / `search` / `export_obsidian` / `settings` / `app_info`.

**명령줄** — MCP 를 붙이지 않았을 때.

    gurunote note "<URL|파일>" --json
    gurunote history --limit 10 --json
    gurunote search "검색어" --json
    gurunote settings --json

`--json` 이면 stdout 이 JSON, 진행 로그는 stderr 로 분리된다. 종료 코드는 성공 0,
파이프라인 실패 1, 입력·옵션 오류 2, 시간 초과 124.

## 절차
1. `app_info` 로 버전과 선택 가능한 engine/provider 를 확인한다. 값을 추측하지 않는다.
2. 노트를 만들 때는 `note_start` 로 시작해 **job_id 를 받는다.** 한 번의 호출로 끝나기를
   기다리지 않는다 — 8분 영상이면 8분쯤 걸린다.
3. `note_status(job_id)` 로 확인한다. `status` 는 running / completed / failed / stopped.
   진행 중이면 `progress`(0~1)와 `log_tail` 로 어느 단계인지 알 수 있다. 완료 후 본문이
   필요하면 `include_note=true` 로 다시 부른다.
4. 실패하면 `error` 와 `pipeline_job_id` 를 그대로 사용자에게 전한다. 로그는
   `~/.gurunote/jobs/<pipeline_job_id>/` 에 있다. 원인을 지어내지 않는다.
5. 이미 만든 노트를 찾을 때는 `search`(의미 검색) 또는 `history`(최신순 목록)를 쓴다.
   `search` 가 `INDEX_NOT_BUILT` 나 `SEMANTIC_UNAVAILABLE` 을 돌려주면 인덱스가 없는
   것이므로 사용자에게 안내하고 `history` 로 대체한다.

## 주의
- **오래 걸린다.** STT 는 영상 길이에 비례하고, 번역은 로컬 모델이면 더 느리다. 작업을
  띄운 뒤 다른 일을 하다가 확인하는 편이 낫다.
- `settings` 는 비밀값을 설정 여부(true/false)로만 돌려준다. 값을 캐묻거나 로그에 남기지
  않는다.
- 로그에 `⚠ 2-pass 1단계 timeout` 이 반복되면 모델이 느린 것이다. 먼저 모델을 warm up
  해보고, 그래도 계속되면 `LLM_CHUNK_TIMEOUT_SEC` / `LLM_HTTP_TIMEOUT_SEC` 를 올리도록
  안내한다 (기본 60 / 90, 변경 후 재시작 필요).
- 노트 생성은 디스크에 파일을 쓰고 기록을 남긴다. 사용자가 요청하지 않은 영상을 임의로
  처리하지 않는다.
- `export_obsidian` 은 vault 에 파일을 만든다. 경로 설정이 없으면 실패하며, 임의의
  경로를 지어내지 않는다.
