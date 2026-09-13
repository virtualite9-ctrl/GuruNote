"""
Step 3 & 4: LLM 기반 한국어 번역 + GuruNote 스타일 마크다운 요약.

- Provider: OpenAI (gpt-5.4) 또는 Anthropic (claude-sonnet-4-6)
- 긴 영상 대응: 세그먼트를 토큰 한도에 맞춰 청크 분할 → 청크별 번역 → 병합
- 번역 결과를 다시 요약 단계에 통째로 넣어 최종 마크다운을 만든다.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

import yaml

from gurunote.types import Segment, Transcript, _format_ts

ProgressFn = Callable[[str], None]


# =============================================================================
# 시스템 프롬프트 (PRD §3 - "매우 중요한 시스템 프롬프트 지시사항")
# =============================================================================

# Layer 11: TRANSLATION + SUMMARY (+ 향후 신규) prompt 공통 룰. 한자/일본어 차단,
# 첫 등장 영문 병기, 통용 표기 dict 핵심 — 양쪽 prompt 끝부분에 inline (DRY).
_SHARED_LANG_RULES = """

[출력 언어 + 표기 — 양쪽 prompt 공통 룰]

## 출력 언어 — 한국어 + 영문 병기만 허용
- 한국어 본문: 한국어 + 영문 병기 (필요 시).
- 영어 원문 영역: 영문 그대로.
- **금지 — 출력에 다음 문자/단어 절대 부재:**
  * 한자 (CJK Unified Ideographs): 这, 是, 因, 此, 也, 但, 这正是, 因此 등
  * 일본어 히라가나/가타카나: い, う, え, お, か, き, ため, には 등
  * 일본어 한자 어휘: 取り組み, 取り組んでいる, ためには, 場合, 仕組み 등
  * 중국어 간체/번체: 着, 过, 这, 那 등
- **모두 한국어 번역 또는 영문 그대로**:
  * 부정합: "슈나이더가 取り組んでいる 일" ✗ → 정합: "슈나이더가 추진하고 있는 일" ✓
  * 부정합: "这正是 우리가 하는 일" ✗ → 정합: "바로 이것이 우리가 하는 일" ✓
  * 부정합: "ためには 인프라가 필요" ✗ → 정합: "이를 위해서는 인프라가 필요" ✓

## 고유명사 첫 등장 영문 병기 (영상 전체 catch)
- 인명/지명/회사명/상품명/기술용어 첫 등장: `한국어 표기(English Name)` 형식.
  예) 슈나이더 일렉트릭(Schneider Electric), 판카즈 샤르마(Pankaj Sharma),
     젠슨 황(Jensen Huang)
- 이후 등장: 한국어만 (영문 병기 부재).
- chunk 분할 reset 절대 부재 — 영상 전체 한 번만 영문 병기.

## 통용 표기 dict (요약/타임라인 영역 정합 핵심)
- 인명: Jensen Huang→젠슨 황, Tiffany Janzen→티파니 잔젠,
        Pankaj Sharma→판카즈 샤르마, Sam Altman→샘 올트먼,
        Elon Musk→일론 머스크, Mark Zuckerberg→마크 저커버그,
        Dario Amodei→다리오 아모데이
- 회사: NVIDIA→엔비디아, Schneider Electric→슈나이더 일렉트릭,
        Motivair→모티브에어, OpenAI→OpenAI, Anthropic→앤트로픽
- AI/기술: AI Native→AI 네이티브, Energy Intelligence→에너지 인텔리전스,
          Digital Twin→디지털 트윈, SimReady→심레디,
          Brownfield→브라운필드, Liquid Cooling→액체 냉각
- 목록에 없는 유명 인물·기업은 **철자가 아니라 통용 발음**으로 음차하라
  (예: Palmer Luckey→팔머 럭키[러커이 ✗], Rick Rieder→릭 리더[리크 ✗]).
  외래어 표기법 규칙은 통용 표기를 모를 때만 쓰는 fallback.

## 한국어 중복 출력 절대 금지 (괄호 안은 영문 원본 전용)
- 정합: 슈나이더 일렉트릭(Schneider Electric) ✓ / 판카즈 샤르마(Pankaj Sharma) ✓
- 부정합: 슈나이더 일렉트릭(슈나이더 일렉트릭) ✗ / 판카즈 샤르마(판카즈 샤르마) ✗
"""


TRANSLATION_SYSTEM_PROMPT = """\
너는 GuruNote 의 수석 에디터이자 세계 최고 수준의 IT/AI 테크 저널리스트야.

다음 규칙을 반드시 지켜:
1. 입력은 영어 인터뷰/팟캐스트 스크립트이며 화자 라벨(Speaker A, Speaker B …)
   과 타임스탬프가 포함돼 있어. 화자 라벨과 타임스탬프 형식은 그대로 보존해.
2. **화자 표기 — 한국어 스크립트 vs 영어 원문 분리:**

   [첫 등장 정의 — 영상 전체 catch — 절대 원칙]
   - "첫 등장" = 영상 전체에서 해당 화자/entity 가 처음 등장하는 시점 한 번.
   - chunk 분할 내에서 reset 절대 부재 — 한 영상 내 한 번만 영문 병기.
   - 첫 등장 영문 병기 누락 절대 금지 (화자 라벨 + 본문 entity 동일 패턴, Rule 10 정합).

   [한국어 스크립트 영역]
   - 첫 등장 (★ 영문 병기 필수): `[HH:MM] 한국어 화자명(English Name): 본문`
     예) `[00:10] 티파니 잔젠(Tiffany Janzen): 안녕하세요...`
     예) `[00:21] 판카즈 샤르마(Pankaj Sharma): 감사합니다.`
   - 이후 등장: `[HH:MM] 한국어 화자명: 본문` (영문 병기 부재)
     예) `[00:13] 티파니 잔젠: 그 다음에...`
   - **"Speaker A/B/C" 메타 라벨은 한국어 스크립트에 출력 부재** —
     영상 컨텍스트(채널명/제목/챕터/자막)에서 화자 실명을 추론할 수
     있으면 한국어 화자명을 직접 사용.
   - 한국어 화자명은 Rule 10 통용 표기 dict 정합
     (예: Tiffany Janzen → 티파니 잔젠, Pankaj Sharma → 판카즈 샤르마,
     Jensen Huang → 젠슨 황).
   - 화자 실명 추론 부재 시 "화자 1", "화자 2" 등 한국어 라벨 또는
     Speaker A/B/C 그대로 사용.
   - **금지 사례 — 화자 라벨의 한국어 중복 출력 절대 부재:**
     * `[HH:MM] 판카즈 샤르마(판카즈 샤르마): ...` ✗ (한국어를 영문 자리에 중복)
     * `[HH:MM] 판카즈 샤르마(Pankaj Sharma): ...` ✓ (영문 원본만 병기)
     * 영문 원본 부재 entity → 영문 병기 부재 → `[HH:MM] 화자 1: ...`

   [영어 원문 스크립트 영역]
   - 형식: `**[HH:MM] Speaker A:** 본문` (Speaker A/B/C 라벨 그대로 보존).
   - 영문 화자 실명 부재 — Speaker A/B/C 라벨만 사용.

   [본문 영역 — 화자/entity 인용 처리]
   - 본문에서 화자 이름 또는 entity 인용 시 Rule 10 영문 병기 룰 정합:
     * 첫 등장 (★ 영문 병기 필수): `한국어 이름(English Name)` 형식
       예) "...담당 상무이사 판카즈 샤르마(Pankaj Sharma)께서 함께해 주셨습니다."
     * 이후 등장: 한국어 이름만 (영문 병기 부재)
   - 화자 라벨 + 본문 entity 모두 영상 전체 첫 등장 catch 동일 적용.
   - 본문에 영문 그대로만 출력 부재 — 한국어 표기 누락 절대 금지.
3. **메시지 앞에 "### 영상 컨텍스트" 섹션이 있으면** 거기 실린 업로드 날짜,
   채널명, 영상 제목/설명, 챕터 목록, 기존 자막 발췌를 **화자 이름 추론과
   챕터 경계 유지의 근거로 적극 활용**해. 설명에 진행자/게스트 이름이 있으면
   Speaker A, B 매핑을 거기에 맞춰.
4. LLM, RAG, Fine-tuning, Transformer, Embedding, Inference, Diffusion 등
   IT/AI 전문 용어는 직역하지 말고 영문을 병기하거나 업계 통용어로 자연스럽게
   번역해. (예: "파인튜닝(Fine-tuning)", "검색 증강 생성(RAG)")
5. 원문의 모든 절·정보를 한국어로 빠짐없이 옮긴다. 추임새(you know, I mean, like,
   kind of, sort of 등)와 군더더기 반복만 정리하고, 의미를 담은 절은 절대 생략하지
   않는다. 한국어 어순·표현으로 자연스럽게 재구성하되, 원문에 없는 내용 추가나 의미
   축약은 금지.
6. 출력은 오직 번역된 스크립트만. 설명/머리말/끝맺음 문장 금지.
7. **"### 영상 컨텍스트" 섹션은 화자/챕터 추론용 참고 메타데이터일 뿐 — 출력에
   그대로 포함하지 마. 컨텍스트의 제목/채널/게시일/태그/챕터/자막 발췌 등을
   본문에 echo 하지 마. 이미 있던 "### 영상 컨텍스트" / "### 번역 대상 스크립트"
   머리말 자체도 출력하지 마.**
8. **추론 과정·메타 분석은 출력 부재.** 다음 표현은 모두 금지:
   - "**참고 화자 매핑**:", "**추론된 화자 매핑**:", "**화자 매핑 근거**:",
     "**번역 노트**:", "**번역 의도**:", "**※ 분석**", "**※ 주의**" 등
     reasoning / commentary 섹션
   - 화자 매핑 결과는 규칙 2 형식으로만 표기 (한국어=한국어 실명, 영어=Speaker A/B/C).
9. **빈 content 영역의 timestamp + Speaker line 은 출력하지 마.**
   같은 timestamp + 같은 Speaker 가 연속 반복되면 1회만.
10. **고유명사(인명/지명/회사명/상품명) 한국어 표기 일관성:**

    [표기 결정 우선순위 — 위에서 아래로]
    1. 한국 언론·업계에서 **이미 통용되는 표기**를 최우선 (유명 인물·기업·제품).
       **철자가 아니라 발음**을 기준으로 음차하라 — 네가 아는 통용 발음을 끌어내라.
       예) Palmer Luckey → 팔머 럭키 (러커이 ✗ — `-ey` 는 [i] 발음),
           Rick Rieder → 릭 리더 (리크 ✗ — `Rick` 의 [ɪ] 는 '릭'),
           Demis Hassabis → 데미스 하사비스, Jensen Huang → 젠슨 황.
    2. 아래 [자주 등장 통용 표기] 목록에 있으면 그대로 사용.
    3. 위 1·2 로 정할 수 없을 때만 아래 외래어 표기법 규칙으로 음차 (fallback).
       — 외래어 규칙이 통용 표기를 덮어쓰지 않는다. 규칙은 모르는 이름의 마지막 수단.

    [핵심 원칙 — 국립국어원 외래어 표기법 정합 (위 3번 fallback 용)]
    - 자음: [k] → ㅋ(어두), ㄱ(받침) / [t] → ㅌ(어두), ㅅ(받침) /
      [tʃ] → 치(어두), ㅊ(어말) / [ʃ](sh) → 슈(모음 앞), 시(어말) /
      [n](어말) → ㄴ
    - 모음: [æ] → 애, [ʌ] → 어, [ə] → 어/이; 장모음은 한국어 정합.
    - [r]: 어두 → ㄹ, 어말 → 생략 또는 ㅡ

    [자주 등장 통용 표기 — 필수 정합]

    회사 (글로벌):
      NVIDIA→엔비디아, OpenAI→OpenAI, Anthropic→앤트로픽,
      Microsoft→마이크로소프트, Google→구글, Meta→메타, Apple→애플,
      Schneider Electric→슈나이더 일렉트릭, Samsung→삼성, AMD→AMD,
      Intel→인텔, Qualcomm→퀄컴, TSMC→TSMC, Tesla→테슬라, Amazon→아마존,
      Motivair→모티브에어, IBM→IBM, Oracle→오라클, Salesforce→세일즈포스,
      Adobe→어도비, Netflix→넷플릭스, ByteDance→바이트댄스, Alibaba→알리바바,
      Tencent→텐센트, SoftBank→소프트뱅크, Foxconn→폭스콘, Cisco→시스코,
      Dell→델, HP→HP, Sony→소니, LG→LG, NASA→미국 항공 우주국,
      Stripe→스트라이프, Rocket Lab→로켓랩, 1X→1X

    회사 (한국):
      Hyundai→현대, Kia→기아, POSCO→포스코, Hanwha→한화,
      SK Hynix→SK 하이닉스, Naver→네이버, Kakao→카카오,
      Innospace→이노스페이스, Lotte Chemical→롯데케미칼,
      ROBOTIS→로보티즈, SPHERE→스피어, Maeil Dairy→매일유업

    인명:
      Jensen Huang→젠슨 황, Sam Altman→샘 올트먼, Elon Musk→일론 머스크,
      Mark Zuckerberg→마크 저커버그, Satya Nadella→사티아 나델라,
      Sundar Pichai→순다르 피차이, Tim Cook→팀 쿡, Dario Amodei→다리오 아모데이,
      Lex Fridman→렉스 프리드먼, Andrej Karpathy→안드레 카파시,
      Yann LeCun→얀 르쿤, Geoffrey Hinton→제프리 힌턴,
      Demis Hassabis→데미스 허사비스, Ilya Sutskever→일리야 수츠케버,
      Greg Brockman→그렉 브록먼, Bill Gates→빌 게이츠,
      Pankaj Sharma→판카즈 샤르마, Tiffany Janzen→티파니 잔젠,
      Andrew Ross Sorkin→앤드루 로스 소킨, Jamie Dimon→제이미 다이먼,
      Lisa Su→리사 수, Pat Gelsinger→팻 겔싱어,
      Cristiano Amon→크리스티아노 아몬

    AI 제품/모델:
      Claude→클로드, Gemini→제미나이, ChatGPT→챗GPT, Copilot→코파일럿,
      DALL-E→달리; GPT/Llama/Mistral 등 모델명은 영문 그대로.

    기술 용어:
      HBM→HBM, DRAM→DRAM, NAND→NAND, HVAC→HVAC,
      Brownfield→브라운필드, Liquid Cooling→액체 냉각,
      Digital Twin→디지털 트윈, SimReady→심레디, Foundry→파운드리,
      AI Native→AI 네이티브, AI Factory→AI 팩토리,
      AI for Energy→AI for Energy (영문 유지),
      Energy for AI→Energy for AI (영문 유지),
      Energy Intelligence→에너지 인텔리전스

    [영문 병기 + 일관성 룰]
    - **첫 등장 = 영상 전체에서 해당 entity 가 처음 등장하는 시점 한 번** —
      chunk 분할 내에서 reset 절대 부재 (한 영상 내 한 번만 영문 병기).
    - 첫 등장 시 영문 병기: "슈나이더 일렉트릭(Schneider Electric)" — 이후 한국어만.
    - **첫 등장 영문 병기 누락 절대 금지** — 화자 라벨 + 본문 entity 동일 패턴
      (Rule 2 정합).
    - 영문 유지 entity (예: OpenAI) 는 첫 등장 시 "OpenAI(오픈AI)" 병기 후
      이후 영문만 — 한국어 표기를 다시 본문에 노출하지 마.
    - 같은 영상 내 같은 entity = 같은 표기 (chunk 별 변동 절대 금지).
    - dict 부재 entity + unsure → 음운 정합 한국어 또는 영문 그대로.
    - **한국어 중복 출력 절대 금지 (괄호 안은 영문 원본 전용):**
      * 정합: 슈나이더 일렉트릭(Schneider Electric) ✓ / 판카즈 샤르마(Pankaj Sharma) ✓
      * 부정합: 슈나이더 일렉트릭(슈나이더 일렉트릭) ✗ / 판카즈 샤르마(판카즈 샤르마) ✗
      * 영문 원본 미상 entity → 영문 병기 부재 (한국어만).
11. **출력 언어 — 한자/일본어/중국어 mix 절대 금지:**
    - 아래 [출력 언어 + 표기 — 양쪽 prompt 공통 룰] 섹션의 "출력 언어" 정합.
    - 본 룰 위반 시 LLM 출력 폐기 + 재생성 (daily quality bar 부정합).
12. **Entity 표기 일관 (Phase 2):**
    - context 영역에 "### 영상 entity 표기 일관" 블록이 있으면, 해당 dict 의
      한국어 표기를 **반드시** 사용 (LLM 변동 절대 부재).
    - dict 영역 entity 의 두 번째 이후 등장 시 영문 병기 부재 (이전 chunk 에서
      이미 첫 등장 병기 완료 가정).
    - dict 외부의 신규 entity 는 Rule 10 통용 표기 + Rule 2 첫 등장 영문 병기 정합.
13. **환각 금지** — 원문에 없는 표현·내용·중국어식 한자어 대조구(예: 而非, 不過)·임의의
    부연 설명을 추가하지 않는다. 번역 결과의 모든 문장은 원문에 대응이 있어야 한다.
14. **누락 금지** — 자조·관용·삽입절(특히 'which is what I am', 'you know what I mean'
    같은 자기 지칭/부연 절)을 빠짐없이 옮긴다. 추임새와 의미 있는 삽입절을 혼동하지 않는다.
15. **영어 단어 미번역 금지** — 영어 단어를 한국어 문장에 그대로 두지 않는다. 단 예외:
    영문 병기 '한국어(English)', 약어(AI, GPU, HBM, ETF 등), 모델/제품명(GPT, ChatGPT,
    Claude 등), 회사명. 일반 영단어(acceptable, reasonable, fine 등)는 반드시 한국어로 옮긴다.

## 충실 의역 — 좋은 예 / 나쁜 예

원문: 'As an American who likes innovation and who likes action as opposed to being a cultural idiot, which is what I am, I'm not big on the euro.'

✓ 좋은 예 (충실): '혁신과 행동을 좋아하는 미국인으로서 — 저는 문화적으로는 바보이긴 하지만요 — 유로에는 큰 관심이 없어요.'
- 'as opposed to being a cultural idiot'(자조 농담)을 직역, 'which is what I am'(자기 지칭) 살림, 한국어 어순 자연스러움
✗ 나쁜 예 (환각·누락·정반대 해석): '혁신과 행동을 선호하는 문화적 무지(而非 문화적 정체)를 택하는 것보다 낫다고 생각하는 미국인으로서, 저는 유로화에 크게 관심이 없어요.'
- 而非는 원문에 없는 환각, 'which is what I am' 누락, 자조 농담을 정반대로 뒤집음

원문: '10% or less tariffs are acceptable as a consumption tax to curb overconsumption.'

✓ 좋은 예: '10% 이하의 관세는 과소비를 억제하는 소비세로 용인할 수 있다.'
✗ 나쁜 예: '10% 이하 관세는acceptable하며...'
- 일반 영단어(acceptable)를 한국어로 옮기지 않고 띄어쓰기까지 붙음
""" + _SHARED_LANG_RULES


SUMMARY_SYSTEM_PROMPT = """\
너는 GuruNote 의 수석 에디터야. 아래 한국어 인터뷰 번역본을 바탕으로
다음 마크다운 구조에 정확히 맞춰 GuruNote 요약본을 작성해.

# 📌 영상 제목 및 핵심 주제 요약
- 영상 제목: {title}
- 핵심 주제를 **3줄 내외**로 요약.

# 💡 Guru's Insights (핵심 인사이트)
- **3~5개**의 굵은 불릿 포인트.
- 각 인사이트는 한 문장으로 압축한 뒤, 그 아래 1~2줄로 부연 설명.

# ⏱️ 타임라인별 주요 내용 요약
- `[MM:SS] 또는 [HH:MM:SS]` 형식의 타임스탬프 + 한 줄 요약 형태로 5~10개.
- 인터뷰 흐름이 잘 보이도록 시간 순서대로.
- **메시지 앞에 "### 영상 컨텍스트" 가 있고 그 안에 공식 챕터 목록이 주어졌다면,
  챕터 경계를 무시하지 말고 챕터 제목을 타임라인 항목의 뼈대로 삼아.**

규칙:
- 출력은 위 3개 섹션의 마크다운만. 다른 머리말/끝맺음 금지.
- 전문 용어는 영문 병기.
- "전체 스크립트 번역본" 섹션은 호출자가 별도로 붙이므로 여기에 포함하지 마.
- **공통 룰**: 한자/일본어 mix 절대 부재 + 통용 표기 dict 정합 + 첫 등장 영문 병기.
  아래 [출력 언어 + 표기 — 양쪽 prompt 공통 룰] 섹션 정합.

충실도 룰 (요약은 압축하되 왜곡·날조는 금지):
- **환각 금지** — 입력 번역본에 실제로 있는 내용·인물만 쓴다. 입력에 등장하지 않는
  인물·기관·수치·발언을 새로 만들어 넣지 마라.
  예) 입력 본문에 없는 'Janet Yellen(재닛 옐런)', 'Jerome Powell(제롬 파월)' 을
      요약에 등장시키면 안 됨 (입력에 그 이름이 없으면 쓰지 마).
- **영어 단어 미번역 금지** — 영어 단어를 한국어 문장에 그대로 두지 않는다. 일반
  영단어는 반드시 한국어로 옮긴다. 단 예외: 영문 병기 '한국어(English)', 약어(AI,
  GPU, ETF 등), 모델/제품명, 회사명.
  예) '개인 투자자들의 formidable(강력한) 존재감' ✗ → '개인 투자자들의 강력한 존재감' ✓
- **인명 표기 일관** — 입력 번역본에 쓰인 인명 표기를 그대로 따른다. 같은 인물을
  요약에서 새로 음차하지 마라. 첫 등장 영문 병기는 유지.
  예) 본문이 '스탠 드러켄밀러' 면 요약도 '스탠 드러켄밀러' — '스턴 드러켄밀러' 처럼
      바꾸지 말 것.
""" + _SHARED_LANG_RULES


# =============================================================================
# Provider 추상화
# =============================================================================
@dataclass
class LLMConfig:
    provider: str            # "openai" | "openai_compatible" | "anthropic" | "gemini"
    model: str
    api_key: str
    base_url: str = ""
    temperature: float = 0.2
    translation_max_tokens: int = 8192
    summary_max_tokens: int = 4096
    # Phase 2 (B01) — entity cache + 화자 cache toggle.
    # True: chunk 1 차단 가능 (bootstrap LLM 호출 1회 + chunk loop 안 cache 갱신).
    # False: 종전 path (chunk 독립 처리, hallucinate 회귀 위험).
    enable_phase2: bool = True

    @classmethod
    def from_env(cls, provider: Optional[str] = None) -> "LLMConfig":
        """
        환경변수에서 LLMConfig 를 생성한다.

        provider 인자를 명시하면 그 값이 우선이고, 없으면 LLM_PROVIDER 환경변수를
        쓴다. 이 인자 덕분에 호출자는 process-wide `os.environ` 을 건드리지
        않고도 요청별로 provider 를 바꿀 수 있다 (Streamlit 같은 멀티 세션
        환경에서 race condition 회피).
        """
        provider = (provider or os.environ.get("LLM_PROVIDER", "openai")).lower().strip()
        temp = _float_env("LLM_TEMPERATURE", 0.2)
        translation_max_tokens = _int_env("LLM_TRANSLATION_MAX_TOKENS", 8192)
        summary_max_tokens = _int_env("LLM_SUMMARY_MAX_TOKENS", 4096)
        if provider == "anthropic":
            return cls(
                provider="anthropic",
                model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
                api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
                temperature=temp,
                translation_max_tokens=translation_max_tokens,
                summary_max_tokens=summary_max_tokens,
            )
        if provider == "gemini":
            return cls(
                provider="gemini",
                model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
                api_key=os.environ.get("GOOGLE_API_KEY", ""),
                temperature=temp,
                translation_max_tokens=translation_max_tokens,
                summary_max_tokens=summary_max_tokens,
            )
        if provider == "openai_compatible":
            return cls(
                provider="openai_compatible",
                model=os.environ.get("OPENAI_MODEL", "gpt-5.4"),
                api_key=os.environ.get("OPENAI_API_KEY", "local"),
                base_url=os.environ.get("OPENAI_BASE_URL", ""),
                temperature=temp,
                translation_max_tokens=translation_max_tokens,
                summary_max_tokens=summary_max_tokens,
            )
        # 'openai' provider intentionally ignores OPENAI_BASE_URL — that env
        # is only honored by 'openai_compatible'. Otherwise selecting "openai"
        # in the UI while OPENAI_BASE_URL points at oMLX/vLLM would silently
        # route through the local server, defeating the pill's meaning.
        return cls(
            provider="openai",
            model=os.environ.get("OPENAI_MODEL", "gpt-5.4"),
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            temperature=temp,
            translation_max_tokens=translation_max_tokens,
            summary_max_tokens=summary_max_tokens,
        )


def _int_env(key: str, default: int) -> int:
    try:
        val = int(os.environ.get(key, "").strip())
        return val if val > 0 else default
    except Exception:  # noqa: BLE001
        return default


def _float_env(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, "").strip())
    except Exception:  # noqa: BLE001
        return default


_log = logging.getLogger(__name__)

# Rate Limit 재시도 설정
_MAX_RETRIES = 4
_INITIAL_BACKOFF = 2.0  # 초

# 청크 번역 사이 지연 — API 분당 요청 제한(RPM) 에 걸리지 않기 위한 최소 쿨다운.
CHUNK_DELAY_SEC = 1.0


def _call_llm(config: LLMConfig, system: str, user: str, max_tokens: int = 4096) -> str:
    """
    단일 LLM 호출 — provider 에 맞춰 디스패치.

    Rate Limit(HTTP 429 / overloaded) 발생 시 지수 백오프(2s → 4s → 8s → 16s)로
    최대 _MAX_RETRIES 회 자동 재시도한다.
    """
    if config.provider in {"openai", "anthropic", "gemini"} and not config.api_key:
        raise RuntimeError(
            f"{config.provider.upper()}_API_KEY 가 .env 에 설정돼 있지 않습니다."
        )

    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return _call_llm_once(config, system, user, max_tokens)
        except Exception as exc:  # noqa: BLE001
            # Rate Limit / Overloaded 에러만 재시도, 나머지는 즉시 raise
            err_str = str(exc).lower()
            is_retryable = any(
                kw in err_str
                for kw in ("rate limit", "429", "overloaded", "too many requests")
            )
            if not is_retryable or attempt == _MAX_RETRIES:
                raise
            wait = _INITIAL_BACKOFF * (2 ** attempt)
            _log.warning("Rate limit hit (attempt %d/%d). %.1fs 후 재시도…", attempt + 1, _MAX_RETRIES, wait)
            last_exc = exc
            time.sleep(wait)

    # unreachable, but for type checker
    raise last_exc  # type: ignore[misc]


def _call_llm_once(config: LLMConfig, system: str, user: str, max_tokens: int) -> str:
    """실제 1 회 LLM 호출."""
    if config.provider == "anthropic":
        from anthropic import Anthropic  # type: ignore

        client = Anthropic(api_key=config.api_key)
        msg = client.messages.create(
            model=config.model,
            max_tokens=max_tokens,
            temperature=config.temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(
            getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text"
        ).strip()

    if config.provider == "gemini":
        from google import genai  # type: ignore

        client = genai.Client(api_key=config.api_key)
        resp = client.models.generate_content(
            model=config.model,
            contents=f"{system}\n\n{user}",
            config=genai.types.GenerateContentConfig(
                temperature=config.temperature,
                max_output_tokens=max_tokens,
            ),
        )
        return (resp.text or "").strip()

    # default: openai
    from openai import OpenAI  # type: ignore

    openai_kwargs: dict = {"api_key": (config.api_key or "local")}
    if config.base_url:
        openai_kwargs["base_url"] = config.base_url
    client = OpenAI(**openai_kwargs)
    # thinking_budget=0 — omlx 정식 thinking 강제 (omlx 설정 무관 일관성, 5/23 진단).
    # OpenAI 호환 API 관례상 모르는 파라미터는 무시 — 다른 provider 호환 영향 부재.
    # timeout — HTTP-level read timeout (batch 응답 정확 작동, 5/23 진단 stream=False catch).
    # ThreadPoolExecutor wrap (Step 3 통합)이 manual shutdown 안전망 결합.
    def _create():
        return client.chat.completions.create(
            model=config.model,
            max_tokens=max_tokens,
            temperature=config.temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            extra_body={"thinking_budget": 0},
            timeout=LLM_HTTP_TIMEOUT_SEC,
        )
    resp = _call_with_wall_clock_timeout(_create, LLM_HTTP_TIMEOUT_SEC)
    return (resp.choices[0].message.content or "").strip()


# =============================================================================
# 청크 분할 (PRD §5 - 토큰 제한 방지)
# =============================================================================
# 토큰 예산 ----------------------------------------------------------------
# 1 token ≈ 4 chars (영어 기준 보수적 추정).
# 한국어 번역은 보통 영어 입력보다 토큰을 1.0~1.3배 더 쓴다는 점, 그리고
# gpt-5.4 / claude-sonnet-4-6 의 응답 한도 안에 안전하게 들어와야 한다는
# 점을 같이 고려해 청크 입력을 ~12000 chars (≈ 3000 토큰) 로 잡는다.
# 이러면 출력은 최대 ~4000 토큰 수준에서 형성되며 TRANSLATION_MAX_TOKENS=8192
# 안에 충분히 들어와 mid-script truncation 위험이 사라진다.
DEFAULT_CHUNK_CHAR_LIMIT = 12_000  # 5/10 본인 설계 복원 (5/14 6000 가설 오류 revert)

# Phase 1 Redesign Step 2 정정 (5/14): 본질 cause = segment count (chunk char
# size 부재). 첫 시도 (12000 → 6000) 가설 catch:
#   - 25-segment E2E verify 결과 두 chunk limit 모두 1 chunk 정합 → chunk
#     size 변경 미작동
#   - gibberish 패턴 동일 (후반 line [01:14] [01:15] [01:23]) → cause 부재
# 진짜 cause: strict JSON schema 의 N 강제 + 모델 tail 위치 attention drop.
# 모델이 K<N 만 emit → fallback padding (의미 부재 한국어) = gibberish 정체.
# 차단: segment count cap — 모델 영역 attention 한계 직접 catch (15 = tail
# 안전 영역). char limit = LLM 토큰 한도 보조 safety net (요약 path 보존).
MAX_SEGMENTS_PER_CHUNK = 15

# 5/24 — STT 의미 단위 재분할 (GURUNOTE_SEGMENT_RESPLIT=1) on 시 적용.
# 재분할 후 segment 길이 ↑ → cs=15 default 시 일부 영상 chunk_max 5061 chars 까지
# 폭주 → 1-pass wall-clock 60초 timeout 다발. 다영상 6개 검증 (TED/인터뷰/긴발화):
#   - cs=12 + char_limit=2000 → chunk_max ≤ 1989, 1-pass timeout 6→1 (잔존 1건은
#     B02 안전망 + 빈 복구 시퀀스 catch).
#   - 2-pass 모든 영상 timeout 0 유지 + 1단계 정합 30→57~69% 향상.
# 토글 off 시 기존값 (12000/15) 보존 — daily 1-pass 동작 불변.
RESPLIT_CHAR_LIMIT = 2000
RESPLIT_SEGMENT_LIMIT = 12

# 번역/요약 호출의 응답 토큰 상한 (gpt-5.4 / claude-sonnet-4-6 둘 다
# 수용 가능한 안전한 값).
TRANSLATION_MAX_TOKENS = 8192
SUMMARY_MAX_TOKENS = 4096


def chunk_segments(
    segments: List[Segment],
    char_limit: int = DEFAULT_CHUNK_CHAR_LIMIT,
    segment_limit: int = MAX_SEGMENTS_PER_CHUNK,
) -> List[List[Segment]]:
    """char_limit + segment_limit 둘 중 먼저 도달 시 chunk 분할.

    char_limit  — LLM 입력 토큰 한도 보조 safety net (long-seg edge case).
    segment_limit — 모델 tail attention drop 차단 (본질 cause, 5/14 정정).

    한 세그먼트는 분할하지 않는다.
    """
    chunks: List[List[Segment]] = []
    current: List[Segment] = []
    current_size = 0

    for seg in segments:
        seg_text = seg.text or ""
        # 화자 라벨/타임스탬프 오버헤드까지 대략 30자 더해 추정
        seg_size = len(seg_text) + 30
        if current and (
            len(current) >= segment_limit
            or current_size + seg_size > char_limit
        ):
            chunks.append(current)
            current = []
            current_size = 0
        current.append(seg)
        current_size += seg_size

    if current:
        chunks.append(current)
    return chunks


def _segments_to_user_block(segments: List[Segment]) -> str:
    lines = []
    for seg in segments:
        ts = _format_ts(seg.start)
        lines.append(f"[{ts}] Speaker {seg.speaker}: {seg.text}")
    return "\n".join(lines)


# Phase 1 redesign — 5/12 trajectory 영역의 timestamp validation + retry helpers
# (_TS_FIND_RE / _TS_LINE_PREFIX_RE / _TS_PARSE_RE / _MAX_TS_RETRY / _extract_timestamps
# / _ts_to_seconds / _build_retry_block / _merge_retry_into_chunk) 모두 제거.
# 본질 cause 차단: Index Mapping path (translate_chunk_index_mapping_v2) 의 zip
# 결정론 매핑 + finish_reason continuation 으로 두 cause (content drift + truncation)
# 모두 근본 차단. helpers 영역은 본 파일 끝의 Phase 1 Redesign 섹션 참고.


# =============================================================================
# 영상 컨텍스트 빌더 (YouTube 메타데이터 → LLM user 메시지 머리말)
# =============================================================================
# 자막/설명이 너무 길면 LLM 토큰 예산을 압박하므로 적절히 잘라 쓴다.
_MAX_CONTEXT_DESCRIPTION = 1500   # chars
_MAX_CONTEXT_SUBTITLE = 2000      # chars


def build_video_context_block(video_context: Optional[dict]) -> str:
    """
    AudioDownloadResult 에서 파생된 dict 를 LLM 에 주입할 컨텍스트 블록으로 변환.

    Args:
        video_context: 다음 키를 가진 dict (모두 선택):
            - title, uploader, upload_date, webpage_url
            - description (str)
            - chapters (list[dict] with start/end/title 또는 Chapter 객체 리스트)
            - subtitles_text (str), subtitles_source (str)
            - tags (list[str])

    Returns:
        `"### 영상 컨텍스트\\n..."` 로 시작하는 멀티라인 문자열. 컨텍스트가 없으면 "".
    """
    if not video_context:
        return ""

    lines: List[str] = ["### 영상 컨텍스트"]

    title = (video_context.get("title") or "").strip()
    if title:
        lines.append(f"- 제목: {title}")

    uploader = (video_context.get("uploader") or "").strip()
    if uploader:
        lines.append(f"- 채널: {uploader}")

    upload_date = (video_context.get("upload_date") or "").strip()
    if upload_date:
        lines.append(f"- 게시일: {upload_date}")

    webpage_url = (video_context.get("webpage_url") or "").strip()
    if webpage_url:
        lines.append(f"- 원본 URL: {webpage_url}")

    tags = video_context.get("tags") or []
    if tags:
        lines.append(f"- 태그: {', '.join(tags[:10])}")

    description = (video_context.get("description") or "").strip()
    if description:
        if len(description) > _MAX_CONTEXT_DESCRIPTION:
            description = description[:_MAX_CONTEXT_DESCRIPTION] + "… (truncated)"
        lines.append("")
        lines.append("#### 영상 설명")
        lines.append(description)

    chapters = video_context.get("chapters") or []
    if chapters:
        lines.append("")
        lines.append("#### 공식 챕터")
        for ch in chapters:
            # Chapter 객체 또는 dict 둘 다 지원
            if hasattr(ch, "start"):
                start, title_ch = ch.start, ch.title  # type: ignore[union-attr]
            else:
                start, title_ch = ch.get("start", 0), ch.get("title", "")  # type: ignore[union-attr]
            lines.append(f"- [{_format_ts(float(start))}] {title_ch}")

    subtitle = (video_context.get("subtitles_text") or "").strip()
    if subtitle:
        source = video_context.get("subtitles_source") or "unknown"
        sub_snippet = subtitle
        if len(sub_snippet) > _MAX_CONTEXT_SUBTITLE:
            sub_snippet = sub_snippet[:_MAX_CONTEXT_SUBTITLE] + "… (truncated)"
        lines.append("")
        lines.append(f"#### 영상 기본 자막 발췌 ({source})")
        lines.append(sub_snippet)

    lines.append("")
    lines.append(
        "※ 위 정보를 화자 이름 추론과 챕터 경계 유지의 참고 자료로 사용해. "
        "아래부터 이어지는 스크립트가 실제 번역/요약 대상이야."
    )
    lines.append("")
    return "\n".join(lines)


# =============================================================================
# Post-process — 영문 병기 dedup (Layer 13 정합)
# =============================================================================
# 본질: 모델 prompt Rule 2 영역 "첫 등장만 영문 병기" 지시 — chunk 경계 영역
# memory 부재로 chunk 마다 첫 등장 catch (영상 단위 부재). 본 post-process 영역
# 결정론 dedup (LLM 호출 부재, RULE 5 정합).
#
# 정규식 영역 본질: Korean lookbehind 영역 (?<=[가-힣]) — 한국어 직후 (English)
# 영역만 catch. dedup key = English annotation 영역만 — prefix Korean text 영역
# 영향 본질 부재 (entity 본체 영역 prefix 영역 합쳐짐 catch 부재).
#   "...오늘 슈나이더 일렉트릭(Schneider Electric)..." 첫 catch
#   "...에서 슈나이더 일렉트릭(Schneider Electric)..." 두 번째 → 영문 영역 제거
_REPEATED_ANNOTATION_RE = re.compile(r"(?<=[가-힣])\s?\(([A-Za-z][^()]*?)\)")


def _strip_repeated_annotations(text: str) -> str:
    """첫 등장 후 영문 병기 영역 제거 (Layer 13 정합).

    "판카즈 샤르마(Pankaj Sharma)" → 첫 등장 보존.
    "판카즈 샤르마(Pankaj Sharma)" 두 번째 이후 → "판카즈 샤르마" (괄호 영역 제거).

    Lookbehind (?<=[가-힣]) — 한국어 직후 영역만 catch.
    한국어 prefix 영역 영향 본질 부재 (English key dedup, regex prefix bug 차단).
    """
    seen: set[str] = set()

    def _replace(match: re.Match) -> str:
        english = match.group(1).strip()
        if english in seen:
            return ""  # 두 번째 이후: 괄호 영역 영역 제거
        seen.add(english)
        return match.group(0)  # 첫 등장: 보존

    return _REPEATED_ANNOTATION_RE.sub(_replace, text)


# =============================================================================
# Post-process — Phase 3 한자/일본어 잔재 제거 (Sub-path A + B + C)
# =============================================================================
# 원인: Qwen3.6-35B-A3B-5bit 의 decoder-level collapse 로 한국어 출력 중 한자/
# 일본어 토큰이 간헐적 잔재. prompt rule 만으로 결정적 차단 부재.
# omlx 가 logit_bias 미지원 (5/18 catch) — token-level 차단 path 봉쇄.
#
# 처리 흐름:
#   1) 검출 (괄호 안 한자 표기 예외)
#   2) Sub-path A: gurunote/data/cjk_lookup.yaml 사전 lookup (긴 매칭 우선)
#   3) Sub-path B: LLM 재매핑 (chunk 단위, retry 최대 3회)
#   4) Sub-path C: 영문 원문 fallback + inline [⚠ fallback] 태그

_CJK_LOOKUP_PATH = Path(__file__).parent / "data" / "cjk_lookup.yaml"
_CJK_LOOKUP_CACHE: Optional[dict] = None

# CJK Unified Ideographs + 일본어 히라가나/가타카나
_CJK_DETECT_RE = re.compile(r"[一-鿿぀-ヿ]")
# 괄호 안 한자 표기 — 예외 (예: "양자역학(量子力學)")
_BRACKETED_CJK_RE = re.compile(r"\([^)]*[一-鿿぀-ヿ][^)]*\)")
# segment 라인 prefix: [MM:SS] Speaker label:
_SEGMENT_PREFIX_RE = re.compile(r"^\[(\d{1,2}):(\d{2})\]\s+([^:]+):\s*(.*)$")


def _load_cjk_lookup() -> dict:
    """yaml 사전 로드 + 캐시. 긴 매칭 우선을 위해 multi-char 를 길이순 정렬.

    Returns:
        {'multi': [(pat, repl), ...], 'single': [(pat, repl), ...]}
    """
    global _CJK_LOOKUP_CACHE
    if _CJK_LOOKUP_CACHE is not None:
        return _CJK_LOOKUP_CACHE
    with open(_CJK_LOOKUP_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    multi: List[tuple] = []
    for section in ("chinese", "japanese"):
        for k, v in (data.get(section) or {}).items():
            multi.append((str(k), str(v)))
    multi.sort(key=lambda x: -len(x[0]))  # 긴 매칭 우선
    single: List[tuple] = [
        (str(k), str(v)) for k, v in (data.get("single_char") or {}).items()
    ]
    _CJK_LOOKUP_CACHE = {"multi": multi, "single": single}
    return _CJK_LOOKUP_CACHE


def _detect_cjk_outside_brackets(text: str) -> List[str]:
    """괄호 밖 CJK 잔재 catch. 빈 리스트면 통과."""
    masked = _BRACKETED_CJK_RE.sub("[BRACKETED]", text)
    return _CJK_DETECT_RE.findall(masked)


def _apply_cjk_dict_lookup(text: str, lookup: dict) -> str:
    """Sub-path A — 사전 lookup. 괄호 안 한자 표기는 보존.

    multi 사전을 긴 매칭 우선으로 적용 후 single 사전 적용.
    """
    # 괄호 영역 보호 — placeholder 로 치환
    bracketed: List[str] = []

    def _save(m: re.Match) -> str:
        bracketed.append(m.group(0))
        return f"\x00BR{len(bracketed)-1}\x00"

    masked = _BRACKETED_CJK_RE.sub(_save, text)
    for pat, repl in lookup["multi"]:
        if pat in masked:
            masked = masked.replace(pat, repl)
    for pat, repl in lookup["single"]:
        if pat in masked:
            masked = masked.replace(pat, repl)
    # 괄호 영역 복원
    return re.sub(r"\x00BR(\d+)\x00", lambda m: bracketed[int(m.group(1))], masked)


def _llm_remap_cjk(
    text: str,
    config: "LLMConfig",
    max_retries: int = 3,
) -> Optional[str]:
    """Sub-path B — LLM 재매핑 retry max_retries회.

    성공 (잔재 0건) 시 결과 반환, 모두 실패 시 None.
    """
    system = (
        "다음 한국어 문장에 한자 또는 일본어 토큰이 남아있다. "
        "본 토큰을 자연스러운 한국어로 모두 치환한 결과만 출력하라. "
        "괄호 안 한자 표기 (예: '양자역학(量子力學)') 는 그대로 둔다. "
        "원문의 화자 라벨과 [MM:SS] 타임스탬프는 보존한다. "
        "설명이나 메타 텍스트 없이 치환된 본문만 한 줄로 출력하라."
    )
    for _ in range(max_retries):
        try:
            result = _call_llm(config, system, text, max_tokens=2048)
        except Exception:
            continue
        if result and not _detect_cjk_outside_brackets(result):
            return result.strip()
    return None


def post_process_cjk(
    result: str,
    segments: List[Segment],
    config: "LLMConfig",
    log: Optional[ProgressFn] = None,
) -> str:
    """Phase 3 후처리 — 한자/일본어 0건 보장 (Sub-path A → B → C).

    Args:
        result: translate_transcript 결과 본문 (segment 라인 \\n\\n join)
        segments: 원본 영문 segments (Sub-path C fallback 시 영문 원문 lookup)
        config: LLMConfig (Sub-path B LLM 호출용)
        log: 진행 콜백

    Returns:
        후처리된 result. 한자/일본어 0건 (Sub-path C fallback 적용된 segment 는
        영문 원문 + [⚠ fallback] 태그) 보장.
    """
    log_fn = log or (lambda _msg: None)
    lookup = _load_cjk_lookup()

    # segments 를 (mm, ss) 키로 인덱싱 — Sub-path C 의 영문 원문 lookup
    seg_by_ts: dict = {}
    for seg in segments:
        mm = int(seg.start) // 60
        ss = int(seg.start) % 60
        seg_by_ts[(mm, ss)] = seg

    sub_a_hits = 0
    sub_b_hits = 0
    sub_c_fallbacks: List[tuple] = []  # (mm, ss)

    parts = result.split("\n\n")
    processed: List[str] = []

    for part in parts:
        if not _detect_cjk_outside_brackets(part):
            processed.append(part)
            continue

        # Sub-path A
        after_a = _apply_cjk_dict_lookup(part, lookup)
        if not _detect_cjk_outside_brackets(after_a):
            sub_a_hits += 1
            processed.append(after_a)
            continue

        # Sub-path B — LLM 재매핑 (Sub-path A 결과를 입력으로)
        after_b = _llm_remap_cjk(after_a, config, max_retries=3)
        if after_b is not None:
            sub_b_hits += 1
            processed.append(after_b)
            continue

        # Sub-path C — 영문 fallback
        m = _SEGMENT_PREFIX_RE.match(part)
        if m:
            mm, ss = int(m.group(1)), int(m.group(2))
            speaker = m.group(3).strip()
            seg = seg_by_ts.get((mm, ss))
            if seg is not None:
                fallback_text = (
                    f"[{mm:02d}:{ss:02d}] {speaker}: {seg.text} [⚠ fallback]"
                )
                sub_c_fallbacks.append((mm, ss))
                processed.append(fallback_text)
                continue

        # segment 매핑 실패 — 잔재 그대로 (검증 단계에서 catch)
        processed.append(part)

    log_fn(
        f"   🔧 Phase 3 후처리 — Sub-A {sub_a_hits}건, "
        f"Sub-B {sub_b_hits}건, Sub-C fallback {len(sub_c_fallbacks)}건"
    )
    if sub_c_fallbacks:
        ts_list = ", ".join(f"[{mm:02d}:{ss:02d}]" for mm, ss in sub_c_fallbacks[:10])
        log_fn(f"   ⚠ Sub-C fallback timestamps: {ts_list}")

    return "\n\n".join(processed)


def post_process_cjk_text(
    text: str,
    config: "LLMConfig",
    log: Optional[ProgressFn] = None,
) -> str:
    """segment 없는 텍스트(제목·요약)용 CJK 후처리 — Sub-path A 사전 + B LLM 재매핑.

    본문 ``post_process_cjk`` 와 같은 A/B 골격을 재사용하되, **Sub-path C(영문 fallback)
    는 제외** — 제목·요약은 segment timestamp 매핑이 없기 때문. A·B 후에도 남는 한자는
    그대로 둔다 (드묾 — 사용자 노트 편집으로 보정; 비우거나 추가 재요청 안 함).

    한자 없으면 즉시 반환 (비용 0). 본문 후처리(``post_process_cjk``)는 건드리지 않는다.
    """
    if not text or not _detect_cjk_outside_brackets(text):
        return text
    log_fn = log or (lambda _msg: None)
    lookup = _load_cjk_lookup()
    a_hits = 0
    b_hits = 0
    out: List[str] = []
    for part in text.split("\n\n"):
        if not _detect_cjk_outside_brackets(part):
            out.append(part)
            continue
        # Sub-path A — 사전 lookup
        after_a = _apply_cjk_dict_lookup(part, lookup)
        if not _detect_cjk_outside_brackets(after_a):
            a_hits += 1
            out.append(after_a)
            continue
        # Sub-path B — LLM 재매핑 (성공 시 clean, 실패 시 None)
        after_b = _llm_remap_cjk(after_a, config, max_retries=3)
        if after_b is not None:
            b_hits += 1
            out.append(after_b)
            continue
        # Sub-path C 제외 — A 적용본(최선) 유지, 잔재는 그대로
        out.append(after_a)
    if log and (a_hits or b_hits):
        log_fn(f"   🔧 CJK 후처리(제목·요약) — Sub-A {a_hits}건, Sub-B {b_hits}건")
    return "\n\n".join(out)


def _detect_unexpected_changes(
    original: str,
    canonical: str,
    entity_cache: dict,
) -> List[str]:
    """canonicalize 전후 비교 — entity 표기 외 변경 감지.

    줄 단위 비교로, entity_cache 의 한국어 표기 등장이 부재한 줄 변경을 의심으로 기록.
    완벽한 검증 부재 — daily 사용 빈도 데이터 수집 목적 (P-다 path).

    Args:
        original: canonicalize 전 본문.
        canonical: LLM canonicalize 결과 본문.
        entity_cache: B06 신 형식 `{english: {korean, type, source}}` dict.

    Returns:
        의심 변경 줄의 요약 list (로그 용). 변경 부재 시 빈 list.
        줄 수 불일치 시 첫 entry 가 줄 수 불일치 알림.
    """
    orig_lines = original.split("\n")
    canon_lines = canonical.split("\n")

    if len(orig_lines) != len(canon_lines):
        return [f"줄 수 불일치: {len(orig_lines)} → {len(canon_lines)}"]

    cache_koreans = {
        meta.get("korean", "")
        for meta in entity_cache.values()
        if isinstance(meta, dict) and meta.get("korean")
    }

    suspect: List[str] = []
    for i, (o, c) in enumerate(zip(orig_lines, canon_lines)):
        if o == c:
            continue
        # entity_cache 의 표기 중 하나가 canonical 줄에 새로 등장하면 정상 변경 추정.
        is_entity_change = any(k in c and k not in o for k in cache_koreans)
        if not is_entity_change:
            o_short = o[:40] + ("…" if len(o) > 40 else "")
            c_short = c[:40] + ("…" if len(c) > 40 else "")
            suspect.append(f"  L{i}: {o_short!r} → {c_short!r}")

    return suspect


def _canonicalize_entity_names(
    result: str,
    entity_cache: dict,
    config: "LLMConfig",
    log: Optional[ProgressFn] = None,
) -> str:
    """B06 §4.3 — 영상 전체 결과의 entity 표기 통일.

    entity_cache 의 canonical 표기 + 외래어 표기법 short version 을 LLM 참조로 주입.
    chunk drift (예: chunk 1 의 '판카즈' vs chunk 2+ 의 '판카지') 통일.

    우선순위 (§3.4):
        1. TRANSLATION_SYSTEM_PROMPT Rule 10 통용 표기 dict
        2. entity_cache 의 canonical 표기 (영상 단위 정답)
        3. 외래어 표기법 short version
        4. LLM 자유 출력

    Args:
        result: post_process_cjk 결과 본문.
        entity_cache: B06 신 형식 `{english: {korean, type, source}}` dict.
        config: LLM 호출용.
        log: 진행 콜백.

    Returns:
        canonicalize 결과. cache 부재, body 크기 한계 초과, LLM 실패, 본문 길이 변동 큼
        catch 시 원본 그대로 (safe fallback).
    """
    log_fn = log or (lambda _msg: None)
    if not entity_cache:
        return result
    if len(result) > _CANONICALIZE_MAX_BODY_CHARS:
        log_fn(
            f"   ⚠ canonicalize skip — body {len(result)} chars 초과 한계 "
            f"{_CANONICALIZE_MAX_BODY_CHARS}"
        )
        return result

    cache_block = _build_entity_cache_block(entity_cache)
    if not cache_block:
        return result

    loanword_block = _LOANWORD_SHORT
    loanword_section = (
        f"\n\n[외래어 표기법 참조 — 표 1 영어 자모 + 제4장 인명·지명]\n{loanword_block}\n"
        if loanword_block
        else ""
    )

    system = (
        "다음 한국어 번역 본문에서 인명·회사명·지명 등 고유 명사의 표기를 통일하라.\n\n"
        "통일 규칙 (우선순위 위에서 아래로):\n"
        "1. 한국에서 이미 통용되는 표기 (예: Schneider Electric → 슈나이더 일렉트릭)\n"
        "2. 아래 entity 표기 일관 dict 의 한국어 표기 (영상 단위 정답)\n"
        "3. 통용 표기·entity dict 부재 시 외래어 표기법 표준 적용\n\n"
        "[형식 보존 — 변경 금지]\n"
        "- 줄 수 보존, timestamp `[MM:SS]` 보존, 화자 라벨 보존, 본문 의미 보존.\n"
        "- 변경 대상은 고유 명사 표기만 — 본문 단어, 어미, 조사 변경 부재.\n"
        "- **인명·회사명·지명 표기 외의 모든 글자는 원본 그대로 글자 단위 복사하라.**\n"
        "- 일반 단어 (예: '소프트웨어', '데이터', '인프라', '클라우드') 의 철자를 절대 바꾸지 말라.\n"
        "- 아래 entity dict 에 부재한 표기는 원본 그대로 유지하라.\n"
        "- 출력 형식 = 변경된 본문 그대로 (설명·헤더 부재).\n\n"
        f"{cache_block}{loanword_section}"
    )

    try:
        canonical = _call_llm(config, system, result, max_tokens=config.translation_max_tokens or TRANSLATION_MAX_TOKENS)
    except Exception as exc:
        log_fn(f"   ⚠ canonicalize LLM 실패 (원본 유지): {exc}")
        return result

    if not canonical or not canonical.strip():
        log_fn("   ⚠ canonicalize 빈 응답 (원본 유지)")
        return result

    # 본문 길이 변동 큼 catch — LLM 이 본문 truncate 또는 expand 한 경우 차단.
    # ±10% 영역 정합 (translation 결과 ±수십 글자 변동은 표기 변경에 정합).
    orig_lines = result.count("\n")
    new_lines = canonical.count("\n")
    if orig_lines > 0 and abs(new_lines - orig_lines) / max(orig_lines, 1) > 0.10:
        log_fn(
            f"   ⚠ canonicalize 줄 수 변동 큼 (원본 {orig_lines} → {new_lines}, 원본 유지)"
        )
        return result

    # P-다 — entity 외 본문 변경 감지 로그 (canonical 그대로 반환, daily 빈도 수집).
    suspects = _detect_unexpected_changes(result, canonical, entity_cache)
    if suspects:
        log_fn(
            f"   ⚠ canonicalize entity 외 변경 의심 {len(suspects)}건 (canonical 채택, 로그만):"
        )
        for s in suspects[:5]:
            log_fn(s)
        if len(suspects) > 5:
            log_fn(f"   ⚠ … 외 {len(suspects) - 5}건")

    log_fn(
        f"   🔧 entity canonicalize 적용 ({len(entity_cache)}건 cache, "
        f"줄 수 {orig_lines} → {new_lines})"
    )
    return canonical.strip()


# =============================================================================
# Pre-process — Phase 2 entity cache + 화자 cache (chunk 간 일관성)
# =============================================================================
# 원인: chunk 독립 처리로 chunk 1 의 entity 표기 결정이 chunk 2+ 에 전파 부재.
# 5/13 사례: 스키에더(chunk 1) vs 슈나이더(chunk 2+) — chunk 경계 referent 단절.
# 5/18 사례: 샘 올트먼 5회 — 영상 부재 인물 hallucinate (chunk 1 차단 부재).
#
# 처리 흐름 ((e) Entity Cache + (b) Two-Stage 결합):
#   1) Bootstrap (Two-Stage 부분): 영상 메타 + 자막에서 사전 entity 추출
#      → entity_cache 초기 영역 채움 → chunk 1 부터 정합 dict
#   2) chunk 별 (Entity Cache): chunk 출력 → speaker line prefix entity 추출
#      → entity_cache 갱신 → 다음 chunk context 에 prepend

# Speaker line prefix 정규식 — 본문 중간의 기술 용어 영문 병기 (예: "AI 네이티브(AI Native)")
# false positive 차단. line 시작에서만 매칭.
_SPEAKER_LINE_RE = re.compile(
    r"^\[(\d{1,2}:\d{2})\]\s+([^:(]+?)\s*(?:\(([^)]+)\))?\s*:",
    re.MULTILINE,
)

# English Name 정합 catch — 영문 + 공백/점/하이픈/어포스트로피만 (예: "Pankaj Sharma", "J.P.", "O'Brien").
_ENGLISH_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z\s\.\-']*$")


# 병기 패턴: 한국어 문자 바로 뒤의 `(English)` — 괄호 안이 ASCII 영문만 (한글 부재).
# "OpenAI(오픈AI)" 처럼 괄호 안에 한글이 있으면 매칭 부재 (영문 원어 병기만 대상).
_ENGLISH_ANNOT_RE = re.compile(r"(?<=[가-힣])\(([A-Za-z][A-Za-z0-9\s.\-']*)\)")


def _correct_english_annotations(
    text: str, source_corpus: str, log: Optional[ProgressFn] = None
) -> str:
    """`한국어(English)` 병기의 영문 철자를 **소스에 실재하는 철자**로 결정론적 검증.

    LLM 이 영문 원어를 자유 생성하다 철자를 오염시키는 문제(예: Anduril→Danduril,
    제목 포함) 차단. 소스(transcript 전문 + 제목)는 정답 철자의 근거.

    각 병기 영문에 대해:
      1. 소스에 (대소문자 무시) 그대로 있으면 → 소스 철자/케이싱으로 정규화.
      2. 단일 토큰이 소스에 없으면 → 소스 단어 중 충분히 가까운 것(보수적 cutoff)으로 교정.
      3. 다단어는 모든 토큰이 소스 근거를 가질 때만 채택, 아니면 생략.
      4. 소스에 근거 없음 → 병기 삭제 (한국어만 남김, 틀린 철자 박지 않음).

    LLM 무관 순수 함수. 한국어 표기·화자 라벨·timestamp 는 건드리지 않는다.
    """
    if not text or not source_corpus:
        return text

    corpus_lower = source_corpus.lower()
    # 소스 영문 단어 풀 + 케이싱 복원 맵 (lower → 첫 등장 원본 케이싱).
    # 순수 알파벳 토큰으로 분리 — 소유격/문장부호 (예: "Anduril's", "U.S.") 가
    # 매칭을 가리지 않도록 ("Anduril's" → "Anduril" + "s").
    case_map: dict = {}
    for w in re.findall(r"[A-Za-z]+", source_corpus):
        case_map.setdefault(w.lower(), w)
    pool_lower = list(case_map.keys())  # 대소문자 무시 fuzzy 매칭용

    stats = {"corrected": 0, "dropped": 0}

    def _restore_case(tokens: list) -> str:
        return " ".join(case_map.get(t.lower(), t) for t in tokens)

    def _fix(eng: str):
        e = eng.strip()
        toks = e.split()
        # 1) 전체 구가 소스에 그대로 → 케이싱만 소스 정규화 (과교정 부재).
        if e.lower() in corpus_lower:
            return _restore_case(toks)
        # 2) 단일 토큰 → 소스 단어 중 보수적 최근접 교정 (대소문자 무시 비교).
        if len(toks) == 1:
            m = difflib.get_close_matches(e.lower(), pool_lower, n=1, cutoff=0.84)
            if m:
                stats["corrected"] += 1
                return case_map[m[0]]
            stats["dropped"] += 1
            return None
        # 3) 다단어 → 토큰별 소스 근거(정확/최근접) 전부 확보 시만 채택.
        fixed = []
        for t in toks:
            if t.lower() in corpus_lower:
                fixed.append(case_map[t.lower()])
            else:
                mm = difflib.get_close_matches(t.lower(), pool_lower, n=1, cutoff=0.84)
                if not mm:
                    stats["dropped"] += 1
                    return None
                fixed.append(case_map[mm[0]])
        if fixed != toks:
            stats["corrected"] += 1
        return " ".join(fixed)

    def _repl(m: "re.Match") -> str:
        fixed = _fix(m.group(1))
        return "" if fixed is None else f"({fixed})"

    out = _ENGLISH_ANNOT_RE.sub(_repl, text)
    if log and (stats["corrected"] or stats["dropped"]):
        log(
            f"   🔧 영문 병기 소스 검증: 교정 {stats['corrected']}건 / "
            f"생략 {stats['dropped']}건"
        )
    return out


# `한국어 인명(English Name)` 병기 — 한국어 부분 + 영문 부분 둘 다 캡처.
# 한국어 인명 = `(` 직전의 한글 단어 run (공백/가운뎃점 연결). 콜론·기타 문자는 경계.
_KOREAN_ANNOT_RE = re.compile(
    r"([가-힣]+(?:[ ·][가-힣]+)*)\(([A-Za-z][A-Za-z\s.\-']*)\)"
)


def _correct_korean_in_annotations(text: str, canonical: dict) -> str:
    """`한국어(English)` 병기에서 **English key 가 통용 dict 에 있으면 한국어를 dict 표기로
    강제 교정** (제목용). LLM 이 인명을 오음차해도(예: 스타니슬라프 드루킨밀러(Stan
    Druckenmiller)) 영문 원어로 dict 조회 → 통용 표기(스탠 드러켄밀러)로 교체.

    `_correct_english_annotations`(영문 철자 검증)와 방향이 반대 — 이쪽은 한국어를 고친다.
    dict 미수록 영문은 불변 (과교정 부재). 영문 병기 없는 인명은 매칭 불가 → 그대로.
    """
    if not text or not canonical:
        return text
    eff = _canonical_effective(canonical)  # {english.lower(): 통용 한국어}
    if not eff:
        return text

    def _repl(m: "re.Match") -> str:
        korean, english = m.group(1), m.group(2)
        canon = eff.get(english.strip().lower())
        if canon and canon != korean:
            return f"{canon}({english})"
        return m.group(0)

    return _KOREAN_ANNOT_RE.sub(_repl, text)


def _extract_entities(translated_chunk: str) -> dict:
    """chunk 출력의 speaker line prefix 에서 entity 추출.

    Phase 1 redesign 출력 형식 정합:
        첫 등장: "[MM:SS] 한국어 화자명(English Name): 본문"
        이후:    "[MM:SS] 한국어 화자명: 본문"

    Line prefix 한정 매칭으로 본문 중간의 기술 용어 (예: "AI 네이티브(AI Native)") 부재.

    B06 신 형식 (Phase 2B-3 migration, 5/20):
        반환 dict 의 값은 `{korean, type, source}` 신 자료구조.
        chunk 추출은 speaker line prefix 에서 catch 한 entity 이므로 type 기본 "speaker",
        source 자동 "chunk_extract".

    Returns:
        `{English Name: {"korean": str, "type": "speaker", "source": "chunk_extract"}}` dict.
        영문 병기 부재 line 은 skip.
    """
    entities: dict = {}
    for m in _SPEAKER_LINE_RE.finditer(translated_chunk):
        korean = m.group(2).strip()
        english_raw = m.group(3)
        if not english_raw:
            continue
        english = english_raw.strip()
        if _ENGLISH_NAME_RE.match(english):
            entities[english] = {
                "korean": korean,
                "type": "speaker",
                "source": "chunk_extract",
            }
    return entities


def _build_entity_cache_block(entity_cache: dict) -> str:
    """entity_cache 를 LLM context 영역의 markdown block 으로 변환.

    Args:
        entity_cache: B06 신 형식 `{English Name: {korean, type, source}}` dict.

    Returns:
        빈 dict 시 "".
        그 외: "### 영상 entity 표기 일관\n- English Name → 한국어 표기\n..."
    """
    if not entity_cache:
        return ""
    lines = ["### 영상 entity 표기 일관"]
    for english, meta in entity_cache.items():
        korean = meta.get("korean", "") if isinstance(meta, dict) else ""
        if not korean:
            continue
        lines.append(f"- {english} → {korean}")
    return "\n".join(lines)


def _bootstrap_entity_cache_from_metadata(
    video_context: Optional[dict],
    subtitles_text: Optional[str],
    config: "LLMConfig",
) -> dict:
    """영상 메타 + 자막에서 사전 entity 추출 ((b) Two-Stage 부분 적용).

    B06 통합 (5/20):
        - cache 조회 (`_load_entity_cache`) 우선 — cache hit 시 LLM 호출 부재.
        - cache miss 시 LLM 호출 prompt 에 외래어 표기법 short version + 4단계 우선순위 명시.
        - LLM 출력 형식: `English Name → 한국어 표기 [type]` (type ∈ {person, company, place, product}).

    Args:
        video_context: AudioDownloadResult.to_context_dict() 형태. None 가능. video_id 키
            부재 path — fallback 으로 video_title hash 사용 (`_compute_cache_key_from_title`).
        subtitles_text: 영문 자막 본문 (부재 시 None). 길이 큰 자막은 첫 3000자만 사용.
        config: LLM 호출용.

    Returns:
        B06 신 형식 `{English Name: {korean, type, source}}` dict. 추출 실패 시 빈 dict.
    """
    video_title = (video_context or {}).get("title", "") if video_context else ""
    cache_key = (
        (video_context or {}).get("id")
        or (video_context or {}).get("video_id")
        or _compute_cache_key_from_title(video_title)
    )

    if cache_key:
        # 5/23 — cache hit 시 speakers 도 함께 로드 (schema v2). 옛 cache (v1) 자동 invalidate.
        cached_full = _load_entity_cache_full(cache_key)
        if cached_full is not None:
            entities_cached = cached_full["entities"]
            speakers_cached = cached_full["speakers"]
            if speakers_cached:
                entities_cached["__speakers__"] = speakers_cached
            return entities_cached

    parts: List[str] = []
    if video_context:
        description = video_context.get("description", "")
        uploader = video_context.get("uploader", "")
        if video_title:
            parts.append(f"Title: {video_title}")
        if uploader:
            parts.append(f"Uploader: {uploader}")
        if description:
            parts.append(f"Description: {description}")
    if subtitles_text:
        parts.append(f"Subtitles (excerpt):\n{subtitles_text[:3000]}")

    if not parts:
        return {}

    text = "\n\n".join(parts)
    # B06 §3.3 R4 — 외래어 표기법 short version inline + §3.4 4단계 우선순위 명시.
    loanword_block = _LOANWORD_SHORT
    loanword_section = (
        f"\n\n[외래어 표기법 참조 자료 — 표 1 영어 자모 + 제4장 인명·지명 표기 원칙]\n{loanword_block}\n"
        if loanword_block
        else ""
    )
    # 5/23 — speakers 식별 추가 (영상당 1회 LLM). entity 와 같은 호출에서 catch.
    system = (
        "다음 영문 영상 메타 + 자막에서 다음 두 가지를 추출하라:\n\n"
        "**Part 1: 고유 명사 (인명, 회사명, 제품명, 지명) entity 추출**\n"
        "각 항목을 'English Name → 한국어 표기 [type]' 형식으로 한 줄에 하나씩 출력하라. "
        "type ∈ {person, company, place, product}.\n\n"
        "**Part 2: 화자 식별 (영상 등장 화자)**\n"
        "STT 가 화자를 'A', 'B', 'C' 등 단일 영문 라벨로 catch. 영상 메타·자막에서 "
        "각 라벨의 실명을 추론하여 다음 형식으로 출력:\n"
        "'SPEAKER A => English Name | 한국어 표기'\n"
        "예: SPEAKER A => Pankaj Sharma | 판카즈 샤르마\n"
        "추론 불가 라벨 부재 시 해당 라벨 생략 (fallback 은 코드가 catch).\n\n"
        "**한국어 표기 우선순위 (Part 1, 2 공통, 위에서 아래로)**:\n"
        "1. 한국에서 이미 통용되는 표기를 최우선. **철자가 아니라 발음**을 기준으로 음차하라\n"
        "   (예: Schneider Electric → 슈나이더 일렉트릭 [company], "
        "Palmer Luckey → 팔머 럭키 [person] (러커이 ✗), Rick Rieder → 릭 리더 [person] (리크 ✗)).\n"
        "2. 통용 표기 부재 시 아래 외래어 표기법 표준 적용 (예: Pankaj Sharma → 판카즈 샤르마 [person])\n"
        "3. 그 외는 영어 자모 한글 대조표 정합 자유 출력"
        f"{loanword_section}\n"
        "**출력 형식**: 설명·헤더·메타 텍스트 부재. 매핑만 출력.\n"
        "Part 1 (entity) 와 Part 2 (speaker) 줄 형식이 다르니 구분되어 catch 가능.\n"
        "추출할 entity 또는 speaker 부재 시 해당 부분 생략."
    )

    try:
        result = _call_llm(config, system, text, max_tokens=2048)
    except Exception:
        return {}

    if not result:
        return {}

    entities: dict = {}
    speakers: dict = {}
    speaker_re = re.compile(r"^\s*SPEAKER\s+([A-Z])\s*=>\s*(.+?)\s*\|\s*(.+?)\s*$")
    for line in result.splitlines():
        line = line.strip()
        if not line:
            continue
        # speaker 패턴 우선 catch (SPEAKER X => English | 한국어)
        sp_match = speaker_re.match(line)
        if sp_match:
            label = sp_match.group(1)
            sp_english = sp_match.group(2).strip()
            sp_korean = sp_match.group(3).strip()
            if label and sp_korean:
                speakers[label] = {"english": sp_english, "korean": sp_korean}
            continue
        # entity 패턴 (English → 한국어 [type])
        if "→" not in line:
            continue
        left, right = line.split("→", 1)
        english = left.strip().lstrip("-").strip()
        right_str = right.strip()
        type_match = re.search(r"\[(person|company|place|product)\]\s*$", right_str)
        entity_type = type_match.group(1) if type_match else "unknown"
        korean = re.sub(r"\s*\[[^\]]+\]\s*$", "", right_str).strip()
        if english and korean and _ENGLISH_NAME_RE.match(english):
            entities[english] = {
                "korean": korean,
                "type": entity_type,
                "source": "bootstrap",
            }

    # 5/23 — 화자 식별 결과를 in-memory cache attribute 로 부착 (호출자가 catch 가능).
    # 기존 entities 반환 형식 유지 (1-pass 호환) + speakers 는 module-level 임시 저장.
    if speakers:
        entities["__speakers__"] = speakers   # 마커 키 — translate_transcript 에서 추출
    return entities


# B06 (Phase 2B-3) — entity_cache 디스크 저장 + 재로드.
# spec: docs/research/phase2b_canonical_translation_spec.md §3.1, §3.2, §4.1, §4.4.
# 본인 결정 (5/20):
#   - §3.1 cache 저장 위치: A 영상별 분리 (~/.gurunote/entity_cache/<video_id>.json)
#   - §3.2 JSON 자료구조: entities 통합 list + type + loanword_spec_version
#   - §3.5 invalidate: spec_version 변경 시 자동 재bootstrap
CACHE_DIR = Path.home() / ".gurunote" / "entity_cache"
LOANWORD_SPEC_VERSION = "2017-14"

# 5/23 — cache schema 버전. speakers 필드 추가로 옛 cache 자동 invalidate.
# v1: entities only (B06 §3.2)
# v2: entities + speakers (화자 라벨 코드 부착, 식별 1회 + 결정론적 표기)
CACHE_SCHEMA_VERSION = "2"

# B06 외래어 표기법 자료 file — bootstrap 용 short version + Phase 3 후처리 용 full body.
_LOANWORD_FILE = Path(__file__).parent / "data" / "loanword_orthography.md"

# B06 §4.3 — _canonicalize_entity_names LLM 호출 안전 한계 (본문 token 추정).
# qwen3.6-35b-q5 의 max_ctx 32K 정합. 본문 + short loanword + entity_cache + system
# prompt 합 ~24K token 정합 (영상 ~50KB 본문 = ~17K token + short loanword ~700 +
# entity_cache prepend ~500 + system ~5K). 본 한계 초과 시 canonicalize skip.
_CANONICALIZE_MAX_BODY_CHARS = 60000


def _compute_cache_key_from_title(video_title: str) -> str:
    """video_id 부재 시 video_title hash 로 cache key 생성 — spec §3.1 fallback.

    AudioDownloadResult.to_context_dict() 가 video_id 를 dict 에 포함 부재 — 본 fallback 으로
    같은 영상 재처리 시에도 cache hit 가능.
    """
    if not video_title:
        return ""
    return "title_" + hashlib.sha256(video_title.encode("utf-8")).hexdigest()[:16]


def _load_loanword_short_version() -> str:
    """Bootstrap LLM prompt 용 외래어 표기법 short version — spec §3.3 R4 정합.

    추출 영역:
        - 표 1 (국제 음성 기호 + 한글 대조표) — 영어 음운 매핑 catch
        - 제4장 (인명·지명 표기의 원칙) — 본 phase 본질 자료

    Returns:
        markdown body. 자료 file 부재 시 "" (호출자가 prompt 에서 자동 skip).
    """
    if not _LOANWORD_FILE.exists():
        return ""
    text = _LOANWORD_FILE.read_text(encoding="utf-8")

    table1_match = re.search(
        r"###\s*표\s*1.*?(?=###\s*표\s*2|\Z)",
        text,
        flags=re.DOTALL,
    )
    table1 = table1_match.group(0).strip() if table1_match else ""

    chapter4_match = re.search(
        r"##\s*제4장.*?(?=##\s*제\d+장|##\s*부\s*칙|\Z)",
        text,
        flags=re.DOTALL,
    )
    chapter4 = chapter4_match.group(0).strip() if chapter4_match else ""

    parts = [p for p in (table1, chapter4) if p]
    return "\n\n".join(parts)


def _load_loanword_full_body() -> str:
    """Phase 3 후처리 용 외래어 표기법 전체 본문 — spec §3.3 R4 정합.

    Returns:
        markdown body. 자료 file 부재 시 "" (Sub-B 가 자동 skip).
    """
    if not _LOANWORD_FILE.exists():
        return ""
    return _LOANWORD_FILE.read_text(encoding="utf-8")


# B06 module-level cache — bootstrap 호출 시마다 file 재읽기 부재.
_LOANWORD_SHORT = _load_loanword_short_version()


def _get_cache_file_path(video_id: str) -> Path:
    """영상 ID 기반 cache file 경로 — `~/.gurunote/entity_cache/<video_id>.json`."""
    return CACHE_DIR / f"{video_id}.json"


def _save_entity_cache(
    video_id: str,
    video_title: str,
    entities: dict,
    speakers: Optional[dict] = None,
    spec_version: str = LOANWORD_SPEC_VERSION,
) -> None:
    """entity_cache 디스크 저장 (5/23 — speakers 필드 추가, schema v2).

    Args:
        video_id: YouTube 영상 ID (cache key).
        video_title: 영상 제목 (debug 용).
        entities: in-memory dict — `{english: {korean, type, source}}`.
        speakers: speaker mapping `{label: {english, korean}}` (예: {"A": {"english":
            "Pankaj Sharma", "korean": "판카즈 샤르마"}}). None 또는 빈 dict 가능.
        spec_version: 외래어 표기법 본문 버전 (LOANWORD_SPEC_VERSION 기본).

    Side effects:
        CACHE_DIR 부재 시 자동 생성. file 덮어쓰기.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _entity_item(english: str, meta: dict) -> dict:
        item = {
            "english": english,
            "korean": meta.get("korean", ""),
            "type": meta.get("type", "unknown"),
            "source": meta.get("source", "unknown"),
        }
        # 검색 그라운딩 교정 entity 만 원래 철자를 기록 (load_stt_corrections 가 역추적).
        # 비교정 entity 는 필드 자체를 생략 — additive·optional (옛 cache·기존 동작 호환).
        orig = (meta.get("original_english") or "").strip()
        if orig:
            item["original_english"] = orig
        return item

    entities_list = [_entity_item(english, meta) for english, meta in entities.items()]

    speakers_list = [
        {
            "label": label,
            "english": meta.get("english", ""),
            "korean": meta.get("korean", ""),
        }
        for label, meta in (speakers or {}).items()
    ]

    data = {
        "video_id": video_id,
        "video_title": video_title,
        "created_at": datetime.now().astimezone().isoformat(),
        "cache_schema_version": CACHE_SCHEMA_VERSION,
        "loanword_spec_version": spec_version,
        "entities": entities_list,
        "speakers": speakers_list,
    }

    cache_path = _get_cache_file_path(video_id)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_entity_cache(
    video_id: str,
    expected_spec_version: str = LOANWORD_SPEC_VERSION,
) -> Optional[dict]:
    """entity_cache 디스크 로드 — entities 만 반환 (기존 호출자 호환).

    Args:
        video_id: YouTube 영상 ID.
        expected_spec_version: 현재 외래어 표기법 본문 버전.

    Returns:
        `{english: {korean, type, source}}` dict 또는 None.
        None 시 호출자는 bootstrap 재실행.
    """
    full = _load_entity_cache_full(video_id, expected_spec_version)
    return full["entities"] if full is not None else None


def _load_entity_cache_full(
    video_id: str,
    expected_spec_version: str = LOANWORD_SPEC_VERSION,
) -> Optional[dict]:
    """5/23 — cache 전체 로드 (entities + speakers). schema v2 검증.

    schema_version 불일치 시 None (옛 cache 자동 invalidate — speakers 부재).

    Returns:
        `{"entities": {english: meta}, "speakers": {label: {english, korean}}}` 또는 None.
    """
    cache_path = _get_cache_file_path(video_id)
    if not cache_path.exists():
        return None

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    # schema v2 검증 — speakers 필드 추가로 옛 cache (v1, schema field 부재) 자동 invalidate.
    if data.get("cache_schema_version") != CACHE_SCHEMA_VERSION:
        return None
    if data.get("loanword_spec_version") != expected_spec_version:
        return None

    entities: dict = {}
    for item in data.get("entities", []):
        english = item.get("english")
        korean = item.get("korean")
        if not english or not korean:
            continue
        entities[english] = {
            "korean": korean,
            "type": item.get("type", "unknown"),
            "source": item.get("source", "unknown"),
        }
        orig = (item.get("original_english") or "").strip()
        if orig:
            entities[english]["original_english"] = orig

    speakers: dict = {}
    for item in data.get("speakers", []):
        label = item.get("label")
        english = item.get("english", "")
        korean = item.get("korean", "")
        if not label or not korean:
            continue
        speakers[label] = {"english": english, "korean": korean}

    return {"entities": entities, "speakers": speakers}


def load_speaker_names(video_context: Optional[dict]) -> dict:
    """영상의 화자 라벨 → English 실명 매핑을 디스크 cache 에서 읽어 반환.

    exporter 의 영어 원문 섹션이 화자 라벨(`A`/`B`) 대신 실명을 찍도록 쓰는 공개 헬퍼.
    `translate_transcript` 가 번역 끝에 저장한 entity cache(`speakers` 필드)를 재사용한다.
    cache_key 산출은 `translate_transcript` 의 저장 경로와 **같은 우선순위**(id → video_id
    → title hash)를 따라 단일 출처를 유지.

    Args:
        video_context: `AudioDownloadResult.to_context_dict()` 형태 (id/video_id/title).

    Returns:
        `{라벨: English 실명}` dict. 다음 경우 모두 **빈 dict**(호출자는 라벨 fallback):
        cache 파일 부재 / schema·spec 버전 불일치 (`_load_entity_cache_full` → None) /
        speakers 부재 / phase2 off 로 저장된 적 없음 / 손상. 예외는 삼켜 깨지지 않는다.
    """
    if not video_context:
        return {}
    try:
        cache_key = (
            video_context.get("id")
            or video_context.get("video_id")
            or _compute_cache_key_from_title(video_context.get("title", ""))
        )
        if not cache_key:
            return {}
        full = _load_entity_cache_full(cache_key)
        if not full:
            return {}
        speakers = full.get("speakers") or {}
        names: dict = {}
        for label, meta in speakers.items():
            if not isinstance(meta, dict):
                continue
            english = (meta.get("english") or "").strip()
            if label and english:
                names[label] = english
        return names
    except Exception:  # noqa: BLE001 — 표시용 부가 정보라 실패는 빈 dict 로 degrade
        return {}


def _verify_entities_with_search(entity_cache: dict, search_fn: Callable, log=None) -> dict:
    """검색 그라운딩 — person/company entity 의 영문 철자를 주입받은 search_fn 으로 검증·교정.

    인명·회사명 STT 오인식(예: Kevin Wurst → Kevin Warsh)을 외부 근거로 통일. search_fn 은
    의존성 주입 (`search_fn(name, hint) -> 교정 english | None`). 테스트는 가짜 함수를 주입.

    동작:
        - 대상: `type ∈ {person, company}` 이고 아직 검색 안 한 (source != "search") entity.
        - 교정 시 entity_cache 의 key 를 정답으로 교체 — 원래 key 는 `original_english` 로
          보존(frontmatter/원문 전파용), `source="search"` 마킹(재검색 방지).
        - 같은 이름 불일치 통일: 한 영상에 Wurst·Warsh 둘 다 있으면 정답(Warsh)으로 병합.
        - search_fn 실패(예외)는 마킹 안 함(다음 기회 재시도). 성공·교정불필요(None/동일)는
          source 만 마킹.

    Returns:
        `{원래 english: 교정 english}` — 본문 병기 치환 + 소스 풀 주입에 쓴다. 교정 없으면 {}.
    """
    corrections: dict = {}
    if not entity_cache:
        return corrections
    targets = [
        eng for eng, meta in list(entity_cache.items())
        if eng != "__speakers__" and isinstance(meta, dict)
        and meta.get("type") in ("person", "company")
        and meta.get("source") != "search"
    ]
    for eng in targets:
        meta = entity_cache.get(eng)
        if not isinstance(meta, dict) or meta.get("source") == "search":
            continue  # 같은 run 에서 통일로 이미 처리된 경우 skip
        searched_ok = True
        try:
            corrected = search_fn(eng, meta.get("type"))
        except Exception:  # noqa: BLE001 — 검색 실패는 graceful skip (교정 없이 진행)
            corrected = None
            searched_ok = False  # 실패는 마킹 안 함 — 다음 기회 재시도 (transient 보호)
        if not corrected or not isinstance(corrected, str) or corrected.strip() == eng:
            if searched_ok:
                meta["source"] = "search"  # 검색했으나 교정 불필요 — 마킹 (재검색 방지)
            continue
        corrected = corrected.strip()
        existing = entity_cache.get(corrected)
        new_meta = dict(existing) if isinstance(existing, dict) else dict(meta)
        new_meta["source"] = "search"
        new_meta["original_english"] = eng
        new_meta.setdefault("type", meta.get("type", "unknown"))
        if not new_meta.get("korean"):
            new_meta["korean"] = meta.get("korean", "")
        entity_cache[corrected] = new_meta
        if eng != corrected:
            entity_cache.pop(eng, None)
        corrections[eng] = corrected
    if log and corrections:
        log("   🔎 검색 그라운딩 교정 "
            f"{len(corrections)}건: " + ", ".join(f"{o}→{c}" for o, c in corrections.items()))
    return corrections


def load_stt_corrections(video_context: Optional[dict]) -> dict:
    """검색 그라운딩 교정 쌍을 디스크 cache 에서 읽어 `{원래 english: 교정 english}` 반환.

    exporter 가 영어 원문 섹션 표시 치환(Wurst→Warsh) + frontmatter 기록에 쓰는 공개 헬퍼.
    `_verify_entities_with_search` 가 entity meta 에 남긴 `original_english` 를 역으로 모은다.
    cache 부재·schema 불일치·교정 부재·손상은 모두 **빈 dict** (호출자는 교정 없이 진행).
    load_speaker_names 와 같은 cache_key 우선순위(단일 출처).
    """
    if not video_context:
        return {}
    try:
        cache_key = (
            video_context.get("id")
            or video_context.get("video_id")
            or _compute_cache_key_from_title(video_context.get("title", ""))
        )
        if not cache_key:
            return {}
        full = _load_entity_cache_full(cache_key)
        if not full:
            return {}
        out: dict = {}
        for english, meta in (full.get("entities") or {}).items():
            if not isinstance(meta, dict):
                continue
            orig = (meta.get("original_english") or "").strip()
            if orig and english and orig != english:
                out[orig] = english
        return out
    except Exception:  # noqa: BLE001 — 표시용 부가 정보라 실패는 빈 dict 로 degrade
        return {}


# =============================================================================
# Health check — omlx xgrammar 사전 점검 (5/23)
# =============================================================================
# 배경: omlx 0.3.8→0.3.9 업그레이드가 xgrammar 모듈 제거 → structured output 강제 부재
# → 전체 chunk timeout 다발 (5/22~5/23 4개 모델 비교에서 27b 모델 두 개 case catch).
# 본인 결정 (5/23): GuruNote 가 사전 점검하여 부재 시 RuntimeError + 복구 안내.
# 캐싱: omlx `/v1/models` 응답의 `created` 필드 (서버 시작 시점 단일값) 를 signature 로
# 사용 → omlx 재시작 정확 감지. 6시간 TTL fallback.

_XGRAMMAR_CHECK_CACHE: dict = {
    "checked_at": 0.0,
    "omlx_signature": None,
    "result": None,
}
_XGRAMMAR_CHECK_TTL_SEC = 21600  # 6시간 fallback


def _get_omlx_signature(config: "LLMConfig") -> Optional[str]:
    """omlx 서버 재시작 감지용 signature — `/v1/models` 응답의 `created` 첫 timestamp.

    omlx 의 모든 model `created` 필드는 서버 시작 시점 단일값 (5/23 실측 catch).
    재시작 시 변경 → cache invalidate.

    Returns:
        signature str, omlx 접근 실패 시 None (TTL fallback 사용).
    """
    if not config.base_url:
        return None
    try:
        import httpx  # noqa: PLC0415
        headers = {}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        resp = httpx.get(
            f"{config.base_url.rstrip('/')}/models",
            headers=headers,
            timeout=5.0,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        models = data.get("data", [])
        if not models:
            return None
        return str(models[0].get("created", ""))
    except Exception:
        return None


def _check_xgrammar_available(
    config: "LLMConfig",
    log: Optional[ProgressFn] = None,
) -> bool:
    """omlx xgrammar 작동 사전 점검 — 최소 json_schema 요청 1회. 캐싱 적용.

    omlx 0.3.9 의 xgrammar 모듈이 부재 시 schema strict 가 무시되어 구조 강제 부재
    → grammar-recovery loop → wall-clock timeout 다발 (5/22 catch).

    Args:
        config: LLM 호출용. provider 가 openai_compatible 부재 시 skip (True).
        log: 진행 콜백.

    Returns:
        True: xgrammar 정상 (또는 점검 대상 부재). False: 부재 — 호출자가 차단.
    """
    log_fn = log or (lambda _m: None)
    # openai_compatible 외 provider 는 본 점검 부재 (anthropic / gemini 등은 schema path 다름).
    if config.provider != "openai_compatible":
        return True

    now = time.time()
    sig = _get_omlx_signature(config)
    cache = _XGRAMMAR_CHECK_CACHE
    if (
        cache["result"] is not None
        and cache["omlx_signature"] == sig
        and sig is not None
        and (now - cache["checked_at"]) < _XGRAMMAR_CHECK_TTL_SEC
    ):
        return cache["result"]

    test_schema = {
        "type": "object",
        "properties": {"ok": {"type": "string"}},
        "required": ["ok"],
        "additionalProperties": False,
    }
    try:
        content, _fr = _call_llm_with_continuation(
            config,
            [{"role": "user", "content": 'Return JSON: {"ok": "yes"}'}],
            max_tokens=32,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "xgrammar_healthcheck",
                    "schema": test_schema,
                    "strict": True,
                },
            },
        )
        parsed = json.loads(content)
        result = isinstance(parsed, dict) and "ok" in parsed
    except Exception as exc:
        log_fn(f"   ⚠ xgrammar 점검 실패: {exc}")
        result = False

    cache["checked_at"] = now
    cache["omlx_signature"] = sig
    cache["result"] = result
    return result


# =============================================================================
# Step 3: 번역
# =============================================================================
# =============================================================================
# 인명 통용 표기 결정론적 교정 (A 보완, 5/26)
# =============================================================================
# 원인: entity_cache / speaker_cache 의 한국어 표기가 bootstrap LLM(또는 디스크 캐시)
# 의 first-seen 으로 고정 → 번역 프롬프트(A, Rule 10)가 우선순위상(캐시 1번) 못 이김.
# 디스크 캐시 hit 시 LLM 자체 우회. → 캐시에 들어간 표기를 편집 가능한 통용 dict 로
# **결정론적 교정** (B 의 _correct_english_annotations 와 같은 접근). dict 미수록 인명은
# 건드리지 않는다 (과교정 부재).
_CANONICAL_NAMES_PATH = Path.home() / ".gurunote" / "canonical_names.json"
_CANONICAL_NAMES_DEFAULT = {
    "Palmer Luckey": "팔머 럭키",
    "Rick Rieder": "릭 리더",
}


def _load_canonical_names() -> dict:
    """통용 표기 dict 로드 — 신 구조 `{English: {"auto": str, "user": str}}`.

    - auto = GuruNote 가 작업 중 자동 기록한 표기. user = 사용자가 수정한 표기.
    - 옛 flat 구조 `{English: "한국어"}` 는 값을 **user 로 마이그레이션** (사용자가 넣은
      초기값으로 간주). 파일 없음/손상 시 기본값(user)으로 생성.
    """
    raw = None
    try:
        if _CANONICAL_NAMES_PATH.exists():
            data = json.loads(_CANONICAL_NAMES_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                raw = data
    except Exception:  # noqa: BLE001 — 손상은 기본값으로 degrade
        raw = None

    if raw is None:
        out = {k: {"auto": "", "user": v} for k, v in _CANONICAL_NAMES_DEFAULT.items()}
        _save_canonical_names(out)  # 최초 생성
        return out

    out: dict = {}
    for k, v in raw.items():
        if not k:
            continue
        if isinstance(v, dict):  # 신 구조
            out[str(k)] = {
                "auto": str(v.get("auto") or ""),
                "user": str(v.get("user") or ""),
            }
        elif v:  # 옛 flat → 값을 user 로 마이그레이션
            out[str(k)] = {"auto": "", "user": str(v)}
    return out


def _save_canonical_names(canonical: dict) -> None:
    """`{English: {auto, user}}` atomic 저장 (tmp → os.replace). auto/user 둘 다 빈
    항목은 제외. 실패는 best-effort (다음 기회에 재저장)."""
    clean: dict = {}
    for k, v in canonical.items():
        if not k:
            continue
        if isinstance(v, dict):
            a, u = str(v.get("auto") or "").strip(), str(v.get("user") or "").strip()
        else:  # 방어 — flat 잔존
            a, u = "", str(v).strip()
        if a or u:
            clean[str(k)] = {"auto": a, "user": u}
    try:
        _CANONICAL_NAMES_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CANONICAL_NAMES_PATH.with_name(_CANONICAL_NAMES_PATH.name + ".tmp")
        tmp.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, _CANONICAL_NAMES_PATH)
    except Exception:  # noqa: BLE001
        pass


def _canonical_effective(canonical: dict) -> dict:
    """English.lower() → 적용할 한국어 (**user 우선**, 없으면 auto). 둘 다 없으면 제외.
    신 구조·옛 flat 모두 수용 (호출부 호환)."""
    out: dict = {}
    for k, v in canonical.items():
        if not k:
            continue
        if isinstance(v, dict):
            kor = (v.get("user") or v.get("auto") or "").strip()
        else:
            kor = str(v).strip()
        if kor:
            out[str(k).lower()] = kor
    return out


def _record_auto_spellings(auto_acc: dict, cache: dict, kind: str) -> None:
    """캐시의 **교정 전 raw** 한국어 표기를 auto 누적 dict 에 모은다 (English → korean).
    kind="entity": `{Eng: {korean}}`, kind="speaker": `{label: {english, korean}}`."""
    if not cache:
        return
    if kind == "entity":
        for eng, meta in cache.items():
            if eng == "__speakers__" or not isinstance(meta, dict):
                continue
            kor = (meta.get("korean") or "").strip()
            if eng.strip() and kor:
                auto_acc[eng.strip()] = kor
    else:  # speaker
        for _label, meta in cache.items():
            if not isinstance(meta, dict):
                continue
            eng = (meta.get("english") or "").strip()
            kor = (meta.get("korean") or "").strip()
            if eng and kor:
                auto_acc[eng] = kor


def _persist_auto_spellings(auto_acc: dict) -> None:
    """누적된 auto 표기를 dict 파일에 병합 저장 — **auto 만 갱신, user 불변**."""
    if not auto_acc:
        return
    try:
        canonical = _load_canonical_names()
        changed = False
        for eng, kor in auto_acc.items():
            entry = canonical.get(eng)
            if entry is None:
                canonical[eng] = {"auto": kor, "user": ""}
                changed = True
            elif entry.get("auto") != kor:
                entry["auto"] = kor  # user 는 건드리지 않음
                changed = True
        if changed:
            _save_canonical_names(canonical)
    except Exception:  # noqa: BLE001 — best-effort
        pass


def _apply_canonical_to_entity_cache(entity_cache: dict, canonical: dict, log=None) -> int:
    """entity_cache `{English: {korean,...}}` 의 English key 가 통용 dict 에 있으면
    korean 을 강제 교정 (user 우선, 대소문자 무시). dict 미수록 key 는 불변."""
    if not entity_cache or not canonical:
        return 0
    lower = _canonical_effective(canonical)
    n = 0
    for eng, meta in entity_cache.items():
        if eng == "__speakers__" or not isinstance(meta, dict):
            continue
        canon = lower.get(eng.lower())
        if canon and meta.get("korean") != canon:
            meta["korean"] = canon
            n += 1
    if log and n:
        log(f"   🔧 통용 표기 교정 (entity {n}건)")
    return n


def _apply_canonical_to_speaker_cache(speaker_cache: dict, canonical: dict, log=None) -> int:
    """speaker_cache `{label: {english, korean}}` 의 english 가 통용 dict 에 있으면
    korean 을 강제 교정 (user 우선). 화자 라벨이 본문 prefix 를 지배하므로 함께 교정."""
    if not speaker_cache or not canonical:
        return 0
    lower = _canonical_effective(canonical)
    n = 0
    for _label, meta in speaker_cache.items():
        if not isinstance(meta, dict):
            continue
        eng = (meta.get("english") or "").strip()
        canon = lower.get(eng.lower())
        if canon and meta.get("korean") != canon:
            meta["korean"] = canon
            n += 1
    if log and n:
        log(f"   🔧 통용 표기 교정 (speaker {n}건)")
    return n


def refresh_canonical_in_markdown(md: str, canonical: dict) -> tuple:
    """완성된 노트(md)에서 auto 표기를 user 표기로 텍스트 치환 (A-2 ③ 리프레시).

    - **auto·user 둘 다 있고 서로 다른 항목만** 대상 (옛 auto 표기를 user 로 교체).
      user 만/auto 만인 항목은 바꿀 옛 표기가 없어 skip.
    - 일반형(`팰머 러커이`) + 태그 언더스코어형(`팰머_러커이`) 둘 다 치환.
    - **단일 패스 정규식**(긴 패턴 우선)으로 치환 — 삽입된 user 텍스트를 재검색하지 않아
      연쇄 치환이 일어나지 않는다. auto 가 한국어라 영어 원문 섹션은 자동 무영향.

    Returns: (new_md, 바뀐 항목 수).
    """
    if not md or not canonical:
        return md, 0
    repl_map: dict = {}
    matched_autos: set = set()
    for v in canonical.values():
        if not isinstance(v, dict):
            continue
        auto = (v.get("auto") or "").strip()
        user = (v.get("user") or "").strip()
        if not (auto and user and auto != user):
            continue
        # 일반형
        if auto in md:
            repl_map[auto] = user
            matched_autos.add(auto)
        # 태그 언더스코어형
        auto_tag, user_tag = auto.replace(" ", "_"), user.replace(" ", "_")
        if auto_tag != auto and auto_tag in md:
            repl_map[auto_tag] = user_tag
            matched_autos.add(auto)
    if not repl_map:
        return md, 0
    # 긴 검색어 우선 (substring 항목이 더 긴 항목 안에서 잘못 잡히는 것 방지).
    keys = sorted(repl_map, key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(k) for k in keys))
    new_md = pattern.sub(lambda m: repl_map[m.group(0)], md)
    return new_md, len(matched_autos)


def translate_transcript(
    transcript: Transcript,
    config: Optional[LLMConfig] = None,
    progress: Optional[ProgressFn] = None,
    video_context: Optional[dict] = None,
    stop_event=None,  # threading.Event — chunk 사이 polling
    search_fn: Optional[Callable] = None,  # 검색 그라운딩 의존성 주입 (인명·회사명 교정)
) -> str:
    """
    Transcript → 한국어로 번역된 스크립트 (문자열).
    화자 라벨과 타임스탬프는 보존된다.

    Args:
        transcript: STT 결과
        config: LLM 설정
        progress: 진행 콜백
        video_context: YouTube 메타데이터 dict (AudioDownloadResult.to_context_dict()
            형태). 제공되면 LLM 의 화자 이름 추론과 챕터 유지에 활용된다.
        stop_event: threading.Event — set 되면 청크 사이에 RuntimeError raise.
            gui.PipelineWorker._stop_event 와 같은 인스턴스를 넘겨 사용자
            중지 요청을 단계 내부에서 catch.
    """
    log = progress or (lambda _msg: None)
    config = config or LLMConfig.from_env()

    # 5/23 — omlx xgrammar 사전 점검 (structured output 강제 부재 시 timeout 다발 catch).
    if not _check_xgrammar_available(config, log):
        raise RuntimeError(
            "omlx xgrammar 미작동 — structured output 강제 부재 → 처리 시 timeout 다발 + "
            "품질 저하 위험. Episilon 서버에서 복구 필요:\n"
            "  brew reinstall omlx --with-grammar\n"
            "  brew services restart jundot/omlx/omlx"
        )

    # 5/24 — STT 의미 단위 재분할 적용 시 chunk size 자동 축소.
    # transcript.raw["segment_resplit"]=True (stt_mlx.py 토글 on) → cs=12, char_limit=2000.
    # off → 기존 (cs=15, char_limit=12000) — daily 1-pass 동작 보존.
    resplit_applied = bool(getattr(transcript, "raw", None)
                            and transcript.raw.get("segment_resplit"))
    if resplit_applied:
        chunks = chunk_segments(
            transcript.segments,
            char_limit=RESPLIT_CHAR_LIMIT,
            segment_limit=RESPLIT_SEGMENT_LIMIT,
        )
        log(f"🌐 LLM 번역 시작 — {len(chunks)} 청크 (cs={RESPLIT_SEGMENT_LIMIT}, "
            f"char_limit={RESPLIT_CHAR_LIMIT}, 재분할 적용) ({config.provider}/{config.model})")
    else:
        chunks = chunk_segments(transcript.segments)
        log(f"🌐 LLM 번역 시작 — {len(chunks)} 청크 ({config.provider}/{config.model})")

    context_block = build_video_context_block(video_context)
    if context_block:
        log("📖 영상 컨텍스트(게시일/챕터/자막)를 LLM 에 주입합니다.")

    # Phase 2 (B01) — entity cache + 화자 cache.
    # (b) Two-Stage 부분 적용: 영상 메타 + 자막에서 사전 entity 추출 → chunk 1 차단 catch.
    # (e) Entity Cache: chunk 출력 → entity 추출 → 다음 chunk context prepend.
    # 5/23 — speakers 식별 추가 (영상당 1회 LLM, 2-pass 화자 라벨 코드 부착용).
    entity_cache: dict = {}
    speaker_cache: dict = {}
    if config.enable_phase2:
        subtitles_text = (video_context or {}).get("subtitles_text") if video_context else None
        bootstrap = _bootstrap_entity_cache_from_metadata(video_context, subtitles_text, config)
        if bootstrap:
            # 5/23 — bootstrap 결과의 __speakers__ 마커 추출 (cache file 와 caller 분리).
            speaker_cache = bootstrap.pop("__speakers__", {}) or {}
            entity_cache.update(bootstrap)
            log(f"   📚 entity cache bootstrap — {len(bootstrap)}건 사전 추출")
            if speaker_cache:
                log(f"   🎤 speaker cache bootstrap — {len(speaker_cache)}명 식별")

    # A 보완 (5/26) — 통용 표기 결정론적 교정. bootstrap(디스크 캐시 hit 포함) 직후·
    #   chunk loop 전에 적용 → cache_block prepend + 화자 라벨이 교정된 표기로. 저장(아래)
    #   은 이 뒤라 디스크 캐시도 self-heal (옛 "팰머 러커이" → "팔머 럭키").
    canonical_names = _load_canonical_names() if config.enable_phase2 else {}
    auto_acc: dict = {}  # English → 교정 전 raw 표기 (작업 끝에 auto 로 누적 저장)
    if config.enable_phase2:
        # 자동 채움 — 교정 전 raw 표기를 먼저 캡처 (user 가 auto 로 덮이지 않게).
        _record_auto_spellings(auto_acc, entity_cache, "entity")
        _record_auto_spellings(auto_acc, speaker_cache, "speaker")
        _apply_canonical_to_entity_cache(entity_cache, canonical_names, log)
        _apply_canonical_to_speaker_cache(speaker_cache, canonical_names, log)

    # 5/23 — 영상 단위 첫 등장 catch (화자 라벨 영문 병기 first-occurrence, 2-pass 전용).
    seen_speakers: set = set()

    translated_parts: List[str] = []
    for i, chunk in enumerate(chunks, start=1):
        if stop_event is not None and stop_event.is_set():
            raise RuntimeError("사용자가 작업 중지를 요청했습니다.")
        # 청크 간 쿨다운 — API Rate Limit 방지 (첫 청크는 건너뜀)
        if i > 1:
            time.sleep(CHUNK_DELAY_SEC)
        log(f"   ↳ 청크 {i}/{len(chunks)} 번역 중…")

        # Phase 2 — context_block 에 entity_cache 블록 prepend (chunk 간 일관성).
        cache_block = _build_entity_cache_block(entity_cache) if config.enable_phase2 else ""
        extended_context = f"{context_block}\n\n{cache_block}" if cache_block else context_block

        # Phase 1 Redesign — Structured Output Index Mapping + finish_reason Continuation.
        # 본질 cause 차단: (1) Content drift — LLM 이 timestamp 출력 부재 → 순서만 매핑
        # (zip 100% 결정론). (2) Truncation — finish_reason='length' 명시 catch + retry.
        # 기존 Phase 1 retry/marker 로직 (5/12 trajectory) 영역 제거 — Index Mapping path
        # 가 두 본질 cause 모두 근본 차단.
        # 5/23 — 2-pass 시 speaker_cache + seen_speakers 전달 (화자 라벨 코드 부착).
        translated = translate_chunk_index_mapping_v2(
            chunk, extended_context, config, log,
            speaker_cache=speaker_cache,
            seen_speakers=seen_speakers,
        )
        translated_parts.append(translated)

        # Phase 2 — chunk 출력의 speaker line prefix entity 추출 + cache 갱신.
        if config.enable_phase2:
            new_entities = _extract_entities(translated)
            if new_entities:
                added = {k: v for k, v in new_entities.items() if k not in entity_cache}
                if added:
                    entity_cache.update(added)
                    # 자동 채움 — chunk 신규 entity 의 raw 표기 캡처 (교정 전).
                    _record_auto_spellings(auto_acc, added, "entity")
                    # A 보완 — chunk 신규 entity 도 통용 표기 교정.
                    _apply_canonical_to_entity_cache(added, canonical_names, log)
                    log(f"   📚 entity cache 갱신: +{len(added)}건 (누적 {len(entity_cache)}건)")

    log("✅ 번역 완료")

    # 검색 그라운딩 (GURUNOTE_SEARCH_GROUNDING, 기본 off) — 인명·회사명 STT 오인식을
    # 주입받은 search_fn 으로 교정. entity_cache 의 english key 를 정답으로 교체(원래 키는
    # original_english 로 보존) + source="search" 마킹(재검색 방지). 디스크 저장(아래) 전에
    # 실행해 교정된 cache 가 영속. 반환 {원래 english: 교정 english} 는 본문/원문/frontmatter
    # 전파에 쓴다. 토글 off·search_fn 부재·예외는 교정 없이 graceful skip.
    stt_corrections: dict = {}
    if (config.enable_phase2 and search_fn is not None
            and os.environ.get("GURUNOTE_SEARCH_GROUNDING", "0") == "1"):
        # 캐시-히트 재처리 — 이미 교정된 entity(source="search")는 _verify 가 건너뛰므로,
        # original_english 로 교정 쌍을 먼저 복원해야 본문 병기·소스 주입이 일관 유지된다.
        for _eng, _meta in entity_cache.items():
            if isinstance(_meta, dict) and _meta.get("original_english"):
                stt_corrections[_meta["original_english"]] = _eng
        # 신규(아직 검색 안 한) entity 교정을 누적.
        stt_corrections.update(_verify_entities_with_search(entity_cache, search_fn, log))

    # A-2 ① — 자동 채움: 작업 중 본 고유명사의 raw 표기를 통용 dict 의 auto 로 누적 저장.
    #   user 는 불변. ②편집 UI 가 auto 를 보여주고 사용자가 user 로 수정 → 다음 작업부터 적용.
    if config.enable_phase2 and auto_acc:
        _persist_auto_spellings(auto_acc)

    # B06 — 영상 처리 완료 시 entity_cache 디스크 저장 (spec §4.4).
    # cache key 는 video_id 우선, 부재 시 video_title hash fallback.
    # speaker_cache 만 있고 entity 0건인 영상도 저장 — 안 그러면 영어 원문 화자 실명이
    # 디스크에 안 남아 load_speaker_names 가 {} → 라벨 fallback (번역본 실명/원문 라벨 불일치).
    if config.enable_phase2 and (entity_cache or speaker_cache):
        video_title_for_cache = (video_context or {}).get("title", "") if video_context else ""
        cache_key = (
            (video_context or {}).get("id")
            or (video_context or {}).get("video_id")
            or _compute_cache_key_from_title(video_title_for_cache)
        )
        if cache_key:
            try:
                _save_entity_cache(
                    cache_key, video_title_for_cache, entity_cache,
                    speakers=speaker_cache,
                )
                log(
                    f"   💾 entity cache 저장: {len(entity_cache)}건 / "
                    f"speakers {len(speaker_cache)}명 → {cache_key}"
                )
            except Exception as exc:
                log(f"   ⚠ entity cache 저장 실패 (무시): {exc}")

    # Index Mapping path 의 출력은 결정론적 \n\n 정합 — Layer 14 lookahead regex
    # 정규화 영역 부재 (chunk join 만으로 충분).
    normalized_parts = translated_parts
    result = "\n\n".join(normalized_parts).strip()
    # C (5/28) — 본문 라인 레벨 연속 반복 축약 (더듬거림 구간을 2-pass 가 같은 문장으로
    #   채우는 회귀 차단). 1-pass·2-pass 공통 조립 직후, 다른 후처리 전.
    result = _collapse_repeated_lines(result, log)
    # Phase 3 — 한자/일본어 잔재 후처리 (Sub-path A → B → C).
    # Sub-path A 사전 lookup → 미적중 시 Sub-path B LLM 재매핑 → 그래도 잔재 시
    # Sub-path C 영문 원문 fallback. 본 단계로 한자/일본어 0건 보장.
    result = post_process_cjk(result, transcript.segments, config, log)
    # B06 §4.3 — entity 표기 통일 (한자/일본어 0건 보장 후 한국어 본문에 적용).
    # entity_cache 의 canonical 표기 + 외래어 표기법 short version 으로 chunk drift 통일.
    if config.enable_phase2:
        result = _canonicalize_entity_names(result, entity_cache, config, log)
    # 검색 그라운딩 — 한국어 본문 병기의 교정 영문 전파 (Wurst)→(Warsh).
    #   result 텍스트 치환 (병기는 괄호 안 영문). 영어 원문 섹션·frontmatter 는 exporter 가
    #   디스크 cache(original_english)에서 따로 전파 (load_stt_corrections).
    for _orig, _corr in stt_corrections.items():
        result = result.replace(f"({_orig})", f"({_corr})")
    # B (5/26) — 영문 병기 철자를 소스(transcript 전문 + 제목)로 결정론적 검증.
    #   LLM 이 영문 원어를 자유 생성하다 오염(Anduril→Danduril)시키는 것 차단.
    _src_title = (video_context or {}).get("title", "") if video_context else ""
    source_corpus = " ".join(s.text for s in transcript.segments)
    if _src_title:
        source_corpus = f"{source_corpus} {_src_title}"
    # 검색 그라운딩 — 교정 영문을 소스 풀에 주입해 _correct_english_annotations 가 교정
    #   병기((Warsh))를 소스 부재로 DROP 하지 않게 (소스는 raw STT=Wurst 라 누락 위험).
    if stt_corrections:
        source_corpus = f"{source_corpus} " + " ".join(stt_corrections.values())
    result = _correct_english_annotations(result, source_corpus, log)
    # 영상 단위 영문 병기 첫 등장만 남기고 반복 병기 dedup (Layer 13 정합).
    return _strip_repeated_annotations(result)


# =============================================================================
# Step 4: 요약 (GuruNote 스타일)
# =============================================================================
def summarize_translation(
    translated_text: str,
    title: str,
    config: Optional[LLMConfig] = None,
    progress: Optional[ProgressFn] = None,
    video_context: Optional[dict] = None,
    stop_event=None,  # threading.Event — partial 사이 polling
) -> str:
    """
    번역본 → 마크다운 요약 (영상 제목/인사이트/타임라인 섹션).
    전체 스크립트는 포함하지 않으며 호출자가 별도로 붙인다.

    video_context 가 제공되면 공식 챕터 목록을 타임라인 섹션의 뼈대로
    사용하도록 LLM 에 주입한다.

    stop_event: threading.Event — set 되면 partial 요약 사이 / 최종 통합 직전에
    RuntimeError raise. translate_transcript 와 같은 패턴.
    """
    log = progress or (lambda _msg: None)
    config = config or LLMConfig.from_env()

    def _check_stop() -> None:
        if stop_event is not None and stop_event.is_set():
            raise RuntimeError("사용자가 작업 중지를 요청했습니다.")

    system = SUMMARY_SYSTEM_PROMPT.format(title=title)
    context_block = build_video_context_block(video_context)
    if context_block:
        translated_text = (
            f"{context_block}\n### 번역본\n{translated_text}"
        )

    # 요약 단계도 본문이 매우 길면 1차 요약 → 합치기 → 최종 요약 두 단계.
    if len(translated_text) > DEFAULT_CHUNK_CHAR_LIMIT:
        log("🧪 번역본이 길어 청크별 요약 후 최종 통합합니다…")
        partials: List[str] = []
        # 청크 분할은 빈 줄 기준 단순 분할로 충분
        paragraphs = translated_text.split("\n\n")
        buf: List[str] = []
        size = 0
        for p in paragraphs:
            if size + len(p) > DEFAULT_CHUNK_CHAR_LIMIT and buf:
                _check_stop()
                partial = _call_llm(
                    config,
                    system=system,
                    user="다음 부분 번역본의 핵심 인사이트와 타임라인만 요약해:\n\n"
                    + "\n\n".join(buf),
                    max_tokens=config.summary_max_tokens or SUMMARY_MAX_TOKENS,
                )
                partials.append(partial)
                buf = []
                size = 0
            buf.append(p)
            size += len(p)
        if buf:
            _check_stop()
            partials.append(
                _call_llm(
                    config,
                    system=system,
                    user="다음 부분 번역본의 핵심 인사이트와 타임라인만 요약해:\n\n"
                    + "\n\n".join(buf),
                    max_tokens=config.summary_max_tokens or SUMMARY_MAX_TOKENS,
                )
            )
        merged_user = (
            "아래는 같은 영상의 부분 요약본들이야. 이를 통합해 GuruNote 스타일의 "
            "최종 요약본을 한 번 더 정리해 줘.\n\n" + "\n\n---\n\n".join(partials)
        )
        log("📝 부분 요약 통합 중…")
        _check_stop()
        merged = _call_llm(
            config,
            system=system,
            user=merged_user,
            max_tokens=config.summary_max_tokens or SUMMARY_MAX_TOKENS,
        ).strip()
        # Phase 3 보완 — 요약 섹션 한자/일본어 후처리 (segment-less A+B).
        merged = post_process_cjk_text(merged, config, log)
        # 요약 충실도 (5/28) — 인명 병기의 영문 key 로 통용 dict 조회 → 한국어 강제 교정.
        #   요약 LLM 이 본문 표기('스탠')를 자율 변형('스턴')해도 결정론적으로 통일.
        return _correct_korean_in_annotations(merged, _load_canonical_names())

    log("📝 GuruNote 요약본 생성 중…")
    _check_stop()
    summary = _call_llm(
        config,
        system=system,
        user=translated_text,
        max_tokens=config.summary_max_tokens or SUMMARY_MAX_TOKENS,
    ).strip()
    # Phase 3 보완 — 요약 섹션 한자/일본어 후처리 (segment-less A+B).
    summary = post_process_cjk_text(summary, config, log)
    # 요약 충실도 (5/28) — 인명 병기의 영문 key 로 통용 dict 조회 → 한국어 강제 교정.
    #   요약 LLM 이 본문 표기('스탠')를 자율 변형('스턴')해도 결정론적으로 통일.
    return _correct_korean_in_annotations(summary, _load_canonical_names())


# =============================================================================
# 메타데이터 자동 추출 (Phase A — 지식 증류기)
# =============================================================================
METADATA_SYSTEM_PROMPT = """당신은 IT/AI 컨텐츠 큐레이터입니다.
주어진 한국어로 번역된 인터뷰/팟캐스트 스크립트와 영상 메타데이터를 보고,
지식 증류 노트를 분류·검색하기 위한 메타데이터를 JSON 형식으로 추출합니다.

추출 항목:
1. organized_title: 사람이 보기 쉬운 한국어 제목 (60자 이내)
   - ★★ 원본 영상 제목이 주어지면 (영상 메타의 '제목' 이 비어있지 않으면) → **원문의 구조·
     형식·문답·말장난을 한국어로 그대로 살려 직역**한다. 접두사("Bonus:")·부제·게임/코너 형식·
     문답 구조를 **보존**하고, **내용을 요약하거나 형식을 뭉개지 말 것.** 자연스러운 한국어
     어순은 허용하되 원문의 구조와 의미를 잃지 마라. (사용자가 원본 맥락을 알고 있음.)
     예) "Bonus: I Say Economy, You Say…with Stan Druckenmiller" (단어 연상 게임 형식)
        ✓ "보너스: 내가 '경제'라고 하면 당신은? — 스탠 드러켄밀러(Stan Druckenmiller)"
          (게임 문답 구조 보존)
        ✗ "보너스: 경제 단어 연상 — 스탠 드러켄밀러" (형식 뭉갬 — 게임 구조 손실)
        ✗ "스탠 드러켄밀러: 금리·관세·달러 전망" (내용 요약 — 절대 금지)
   - 원본 제목이 **비어있을 때만** (메타에 제목 부재) → 인물·주제 중심으로 새로 작성.
   - ★ title 등장 인물 룰 (Layer 15 fix-up #1 — hallucination 차단):
     * 영상의 실제 화자 + 영상의 핵심 주제만 포함.
     * 본문에서 단순 인용된 인물 (키노트 발표자, 언급된 학자, 화자가 인용한
       다른 사람 등) 은 title 등장 절대 부재.
     * 영상의 실제 화자는 transcript 의 화자 라벨에서 확인 — 인용 인물과 구분.
   - 형식 예시 (다양 패턴 — 영상 성격에 맞게 선택):
     * 단순 번역: "엔비디아 GTC 스튜디오: 슈나이더 일렉트릭의 AI 인프라 인사이트"
     * 화자 + 주제: "판카즈 샤르마(Pankaj Sharma): AI 팩토리의 에너지 인텔리전스"
     * 주제 중심: "AI 팩토리 에너지 인프라: Energy for AI vs AI for Energy"
   - 부정합 사례: 본문에서 단순 인용된 인물을 title 화자로 배치 ✗
2. field: 분야 (한국어, 1~3단어)
   - 예: "AI/ML", "AI 하드웨어", "스타트업", "철학", "양자 컴퓨팅", "정치"
3. tags: 정확히 5개의 짧은 키워드 (한글 또는 영문 약어)
   - YouTube 의 원본 태그가 주어지면 적합한 것을 우선 활용
   - 부족하면 본문 내용에서 핵심 주제어 추가
   - 예: ["NVIDIA", "스케일링 법칙", "GPU", "젠슨 황", "AGI"]
""" + _SHARED_LANG_RULES + """

[중요 — title + tags 영역의 표기 룰 (Layer 15)]
- title 영역: 본문과 동일 패턴 — 첫 등장 entity 영문 병기 적용.
  예: "슈나이더 일렉트릭(Schneider Electric): AI 팩토리 인프라"
  예: "젠슨 황(Jensen Huang): NVIDIA - 4조 달러 기업"
  부정합: "슈나이더일렉트릭" (띄어쓰기 누락) ✗
- tags 영역: 통용 표기 dict 정합 (한국어 표기). 영문 병기 부재 (hashtag 부자연).
  정합: ["슈나이더 일렉트릭", "AI 팩토리", "에너지 효율"]
  부정합: ["슈나이더_일렉트릭(Schneider_Electric)"] ✗ (영문 병기 hashtag)
- title 60자 제한 — 영문 병기 추가해도 일반 entity 빈도 영역 50자 안쪽 안전.

오로지 다음 JSON 만 출력하세요. 다른 설명/마크다운 없이 순수 JSON:
{
  "organized_title": "...",
  "field": "...",
  "tags": ["...", "...", "...", "...", "..."]
}
"""


def extract_metadata(
    translated_text: str,
    video_meta: Optional[dict] = None,
    config: Optional[LLMConfig] = None,
    log: Optional[Callable[[str], None]] = None,
) -> dict:
    """
    번역된 스크립트 + 영상 메타데이터에서 분류용 메타데이터를 추출.

    Args:
        translated_text: `translate_transcript` 의 결과 (전체 또는 앞부분 발췌)
        video_meta: yt-dlp 의 영상 메타 (title, uploader, tags, description 등)
        config: LLMConfig
        log: 진행 로그 콜백

    Returns:
        {
            "organized_title": str,
            "field": str,
            "tags": list[str] (5개),
        }
        실패 시 빈 dict 반환 (파이프라인 진행 방해 안 함).
    """
    log = log or (lambda _msg: None)
    config = config or LLMConfig.from_env()
    video_meta = video_meta or {}

    # LLM 입력 분량 제한 — 앞부분 + 뒷부분 발췌로 토큰 절감
    excerpt = _excerpt_for_metadata(translated_text)

    youtube_title = video_meta.get("title", "") or ""
    uploader = video_meta.get("uploader", "") or ""
    youtube_tags = video_meta.get("tags") or []
    youtube_tag_block = (
        f"\n원본 YouTube 태그: {', '.join(youtube_tags[:15])}" if youtube_tags else ""
    )

    # 제목 지시 분기 — 원본 제목 유무에 따라 직역/요약 신호 명시.
    if youtube_title.strip():
        title_directive = (
            f"- 제목: {youtube_title}\n"
            f"  → organized_title: **위 원본 제목을 구조 그대로 직역**하라 (접두사·게임/문답 형식·"
            f"말장난 보존, 형식 뭉개기·내용 요약 금지). "
            f"인명은 첫 등장 영문 병기 `한국어(English)` 필수.\n"
        )
    else:
        title_directive = (
            "- 제목: (원본 제목 부재)\n"
            "  → organized_title: 인물·주제 중심으로 새로 작성하라.\n"
        )
    user = (
        f"### 영상 메타\n"
        f"{title_directive}"
        f"- 업로더: {uploader}{youtube_tag_block}\n\n"
        f"### 한국어 번역 발췌\n{excerpt}\n"
    )

    log("🏷️  메타데이터(제목/분야/태그) 추출 중…")
    # JSON 은 짧지만 한국어 제목/태그가 길 수 있으므로 config.summary_max_tokens 를
    # 기준으로 여유를 두되, 하한 1024 로 최소 응답 공간 보장.
    metadata_max_tokens = max(1024, (config.summary_max_tokens or 4096) // 4)
    try:
        raw = _call_llm(
            config,
            system=METADATA_SYSTEM_PROMPT,
            user=user,
            max_tokens=metadata_max_tokens,
        )
        meta = _parse_metadata_json(raw)
        # B (5/26) — organized_title 영문 병기도 소스(원본 제목 + 번역 본문)로 검증.
        #   summarize/extract 는 entity_cache 미참조 → 제목 오타(Danduril)는 별도 차단.
        if meta.get("organized_title"):
            title_corpus = f"{youtube_title} {translated_text}"
            meta["organized_title"] = _correct_english_annotations(
                meta["organized_title"], title_corpus
            )
            # 제목 품질 — 인명 병기의 영문 key 로 통용 dict 조회 → 한국어 강제 교정
            #   (LLM 오음차 "스타니슬라프 드루킨밀러(Stan Druckenmiller)" → "스탠 드러켄밀러").
            meta["organized_title"] = _correct_korean_in_annotations(
                meta["organized_title"], _load_canonical_names()
            )
        # Phase 3 보완 — 제목/분야/태그 한자·일본어 후처리 (segment-less A+B).
        if meta.get("organized_title"):
            meta["organized_title"] = post_process_cjk_text(meta["organized_title"], config, log)
        if meta.get("field"):
            meta["field"] = post_process_cjk_text(meta["field"], config, log)
        if meta.get("tags"):
            meta["tags"] = [post_process_cjk_text(t, config, log) for t in meta["tags"]]
        return meta
    except Exception as exc:  # noqa: BLE001
        log(f"  메타데이터 추출 실패 (무시하고 계속): {exc}")
        return {}


def _excerpt_for_metadata(text: str, max_chars: int = 6000) -> str:
    """메타 추출용 발췌 — 앞 70% / 뒤 30% 비율로 자른다."""
    if len(text) <= max_chars:
        return text
    head = int(max_chars * 0.7)
    tail = max_chars - head
    return text[:head] + "\n\n[…중간 생략…]\n\n" + text[-tail:]


def _parse_metadata_json(raw: str) -> dict:
    """LLM 응답에서 JSON 객체를 추출 (마크다운 코드블록 래핑 허용)."""
    import json
    import re

    if not raw or not raw.strip():
        return {}

    # ```json ... ``` 또는 ``` ... ``` 코드블록 제거
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    payload = fence.group(1) if fence else raw

    # JSON 객체 첫 등장 부분만 추출 (LLM 이 앞뒤로 텍스트 붙이는 경우)
    obj_match = re.search(r"\{.*\}", payload, re.DOTALL)
    if not obj_match:
        return {}

    try:
        data = json.loads(obj_match.group(0))
    except json.JSONDecodeError:
        return {}

    # 스키마 검증 + 정규화
    title_raw = data.get("organized_title")
    field_raw = data.get("field")
    title = title_raw.strip() if isinstance(title_raw, str) else ""
    field = field_raw.strip() if isinstance(field_raw, str) else ""

    tags_raw = data.get("tags") or []
    if not isinstance(tags_raw, list):
        tags_raw = []
    # 문자열만 허용 — `None` / `{}` / 숫자 등이 `str(None)` 거쳐 "None" 같은
    # 쓰레기 태그로 저장되는 것을 방지.
    tags = [t.strip() for t in tags_raw if isinstance(t, str) and t.strip()][:5]

    if not (title or field or tags):
        return {}

    return {
        "organized_title": title,
        "field": field,
        "tags": tags,
    }


def test_connection(config: Optional[LLMConfig] = None) -> str:
    """현재 설정으로 LLM API 연결을 테스트한다."""
    cfg = config or LLMConfig.from_env()
    text = _call_llm(
        cfg,
        system="You are a connection tester. Reply only with: OK",
        user="ping",
        max_tokens=16,
    )
    if not text.strip():
        raise RuntimeError("LLM 응답이 비어 있습니다.")
    return text.strip()


# =============================================================================
# Phase 1 Redesign — Structured Output Index Mapping + finish_reason Continuation
# =============================================================================
# 본질 cause 차단 (체크포인트 2 — 단일 chunk 영역 verify):
#   1. Content drift — LLM 이 timestamp 출력 부재 → 순서만 매핑 (zip 영역 100%)
#   2. Truncation — finish_reason='length' 명시 catch + continuation 영역
# 본 spec: docs/research/phase1_redesign_research.md
# 5/12 endpoint verify: qwen3.6-35b-q5 — finish_reason + json_object + json_schema 모두 정합.
# 기존 Phase 1 helpers (5/12 trajectory) 영역 보존 — 체크포인트 3 시 통합 결정.


# B02 — wall-clock timeout 강제 (Phase 4a-1 httpx read timeout 한계 차단).
# Phase 4a-1 의 timeout 파라미터는 httpx request-level (read/connect/write 각각).
# streaming 응답에서 read 가 연속 발생하는 grammar-recovery loop 진입 시 wall-clock
# 강제 부재 (chunk 9/14 케이스: 250초+ 소비, b447a11 commit 메시지 catch).
#
# 본 wrap 은 ThreadPoolExecutor + future.result(timeout) 으로 wall-clock 강제 catch.
# Daemon thread 가 서버 응답까지 메모리 살짝 차지 (GC 정리) — server 측 generation
# abort 부재이지만 client 측 abort 충분 (본인 omlx 환경 catch).
DEFAULT_LLM_CHUNK_TIMEOUT_SEC = 60.0

# B02 한계 1 — wall-clock timeout 발생 시 padding 표기 (5/22 보완).
# 일반 길이 미스매치 fallback 의 "[번역 누락]" 과 구분 — Obsidian 노트 timeout 빈도 catch.
# R1 path: timeout 발생 시 retry 부재로 즉시 expected_count 만큼 본 marker 로 padding,
# 영상 전체 rc=0 보장. timeout chunk 는 LLM grammar-recovery loop 상태로 retry 효과
# 불확실 (5/22 Run 1 청크 5 사례) — 본인 daily 영상 완성 우선 결정 정합.
TIMEOUT_PADDING_MARKER = "[⚠ timeout]"

# B02 한계 1 수정 (5/23) — HTTP-level read timeout (openai SDK timeout 파라미터).
# 5/23 진단: `with ThreadPoolExecutor` 의 __exit__ shutdown(wait=True) 가 60초 raise 후에도
# thread 끝까지 대기 → 실질 wall-clock 부재 (964초 폭주 발생). 두 안전장치 동시 적용:
#   1. HTTP-level timeout (openai SDK → httpx read timeout) — batch 응답에서 정확 작동
#   2. ThreadPoolExecutor shutdown(wait=False) — HTTP timeout 부재 path 안전망
# 정상 chunk 처리 시간(5/23 verify 기준 24~84초) 통과 + 폭주(964초) 차단 정합.
LLM_HTTP_TIMEOUT_SEC = 90.0


def _call_with_wall_clock_timeout(fn, timeout_sec: float, *args, **kwargs):
    """sync 함수를 별 thread 에서 실행 + wall-clock timeout 강제 (B02).

    5/23 수정: `with ThreadPoolExecutor` 의 __exit__ shutdown(wait=True) 가 timeout
    raise 후에도 thread 완료까지 대기하던 결함 catch 후, manual `shutdown(wait=False)`
    로 변경. timeout 시 caller 즉시 raise, thread 는 백그라운드 잔류 (HTTP-level
    timeout 으로 thread 자체도 곧 종료).

    Args:
        fn: sync callable.
        timeout_sec: wall-clock 한계 (초).
        *args, **kwargs: fn 인자.

    Returns:
        fn 의 return 값.

    Raises:
        TimeoutError: timeout_sec 초과 시 즉시 raise (thread 완료 대기 부재).
        fn 자체 raise 시 본 exception propagate.
    """
    ex = ThreadPoolExecutor(max_workers=1)
    future = ex.submit(fn, *args, **kwargs)
    try:
        result = future.result(timeout=timeout_sec)
        # 정상 완료 시 immediate cleanup (wait=True 정합, thread 이미 종료).
        ex.shutdown(wait=True)
        return result
    except FutureTimeoutError:
        # 핵심: wait=False — thread 완료 대기 부재로 caller 즉시 raise.
        # cancel_futures=True — 미시작 future cancel (Python 3.9+).
        ex.shutdown(wait=False, cancel_futures=True)
        raise TimeoutError(
            f"LLM 호출 wall-clock timeout — {timeout_sec}초 초과 (B02)"
        )


def _call_llm_once_with_reason(
    config: LLMConfig,
    messages: list,
    max_tokens: int,
    response_format: Optional[dict] = None,
    timeout: Optional[float] = None,
) -> tuple:
    """단일 LLM 호출 — (content, finish_reason) tuple 반환.

    기존 `_call_llm_once` 는 content string 만 반환 (Layer 13 / Layer 14 / Step 3b-3
    등 다른 호출자가 finish_reason 불필요). 본 함수는 Index Mapping path 전용 —
    truncation 명시적 catch + JSON 응답 길이 검증을 위해 finish_reason 노출.

    openai / openai_compatible provider 만 지원 (anthropic / gemini 는 별도 mapping
    필요 — 본 path 의 endpoint 가 OpenAI compat 영역).

    Args:
        timeout: request-level timeout (초). None 이면 SDK 기본값 사용. Phase 4a-1
            에서 xgrammar grammar-recovery loop 조기 차단용으로 사용 (첫 시도 strict
            mode 에 30초 적용). timeout 초과 시 openai.APITimeoutError 발생.

    Wall-clock timeout (B02, 5/20):
        본 함수 안의 client.chat.completions.create 호출은 ThreadPoolExecutor +
        future.result(timeout=DEFAULT_LLM_CHUNK_TIMEOUT_SEC) wrap 으로 wall-clock
        강제. httpx timeout 의 한계 (read streaming 시 wall-clock 부재) catch.

    Returns:
        tuple[str, str]: (content, finish_reason ∈ {"stop", "length", "content_filter", ...})
    """
    from openai import OpenAI  # noqa: PLC0415

    openai_kwargs: dict = {"api_key": (config.api_key or "local")}
    if config.base_url:
        openai_kwargs["base_url"] = config.base_url
    client = OpenAI(**openai_kwargs)

    kwargs: dict = {
        "model": config.model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": config.temperature,
        # thinking_budget=0 — omlx 정식 thinking 강제 (5/23 진단). openai SDK extra_body
        # 경유로 알려지지 않은 파라미터 호환성 catch.
        "extra_body": {"thinking_budget": 0},
        # HTTP-level read timeout (5/23 수정) — batch 응답에서 정확 작동 (stream=False catch).
        # ThreadPool wrapper 결합으로 이중 안전장치.
        "timeout": LLM_HTTP_TIMEOUT_SEC,
    }
    if response_format:
        kwargs["response_format"] = response_format
    if timeout is not None:
        # caller 가 명시 timeout 지정 시 override (xgrammar healthcheck path 등).
        kwargs["timeout"] = timeout

    # B02 — wall-clock timeout 강제 (slow chunk grammar-recovery loop 차단).
    # 5/23 수정: manual shutdown(wait=False) 적용 — timeout 시 caller 즉시 raise.
    resp = _call_with_wall_clock_timeout(
        client.chat.completions.create,
        DEFAULT_LLM_CHUNK_TIMEOUT_SEC,
        **kwargs,
    )
    choice = resp.choices[0]
    return (choice.message.content or ""), (choice.finish_reason or "unknown")


def _build_freeform_translation_prompt(inputs: list, context: str) -> str:
    """(가) 옵션 A 1단계 — schema 부재 자유 번역 prompt (5/23 — 화자 라벨 제거).

    DCCD 패턴: 1단계 자유 추론 (schema 부담 부재) → 2단계 정렬 (schema strict).
    5/23 — 화자 라벨이 LLM 처리에서 제외 (client zip 코드 부착). 입력 형식 변경:
    "A: text" → "text" 만. 모델이 본문 번역에만 집중.

    Args:
        inputs: ["text", ...] N개 (speaker prefix 제거된 본문만).
        context: 영상 컨텍스트 + entity_cache markdown block (B06 §4.1 정합).

    Returns:
        user prompt 문자열. system = TRANSLATION_SYSTEM_PROMPT 재사용.
    """
    return f"""[자유 번역 영역 — (가) 옵션 A 1단계, schema 부재, 5/23 화자 라벨 제거]

다음 {len(inputs)}개 segment 본문을 한국어로 번역하라:

1. 형식 제약 부재. 원문의 모든 절·정보를 빠짐없이 충실하게 한국어로 옮기되, 한국어로 자연스럽게 재구성. 환각·누락·일반 영어 leak 금지.
2. **각 segment 를 빈 줄 (`\\n\\n`) 로 구분하여 정확히 {len(inputs)}개 출력**.
3. **화자 라벨 출력 절대 부재** — 입력에 화자 prefix 부재, 출력도 화자 부재.
   본문 한국어 번역만 출력 (예: "안녕하세요. 오늘은…" 형식, "이름: 본문" 형식 절대 부재).
4. timestamp 출력 절대 부재 (클라이언트가 별도 부착).
5. 다른 모든 규칙 (Rule 3~11 + _SHARED_LANG_RULES) 정합 유지.
6. segment 를 합치거나 나누지 말 것 — 입력 {len(inputs)}개 ↔ 출력 {len(inputs)}개.

{context}

Input ({len(inputs)}개 segment 본문, 영어 text 만):
{json.dumps({"inputs": inputs}, ensure_ascii=False, indent=2)}

Output (정확히 {len(inputs)}개 한국어 본문, `\\n\\n` 구분, 화자/timestamp 부재):"""


def _build_alignment_prompt(inputs: list, freeform_translation: str) -> str:
    """(가) 옵션 A prototype 2단계 — 자유 번역 정렬 prompt (schema strict 강제).

    1단계 자유 번역을 입력 N개에 1:1 매핑하는 N개 outputs 배열로 정렬.
    번역 내용 변경 부재 — 재정렬·재조립만.

    Args:
        inputs: 원본 ["Speaker A: text", ...] N개.
        freeform_translation: 1단계 자유 번역 결과 (line break 구분 추정).

    Returns:
        user prompt 문자열. system = TRANSLATION_SYSTEM_PROMPT 재사용.
    """
    return f"""[정렬 영역 — (가) 옵션 A 2단계, schema strict, 5/23 화자 라벨 제거]

다음 자유 번역의 내용을 입력 {len(inputs)}개 segment 에 1:1 대응하는 {len(inputs)}개 outputs 배열로 재배치하라:

**핵심 원칙**:
1. **번역 내용/의미 보존 — 재배치만, 새 번역 생성 부재** — 1단계 자유 번역의 단어와 표현을 그대로 사용하되 (내용 추가·삭제·수정 절대 부재, 새로 번역하지 말 것), 입력 {len(inputs)}개 segment 경계에 맞춰 재배치만 한다.
2. **outputs 배열은 정확히 {len(inputs)} 개 항목, 입력 순서 유지**.

**재배치 규칙 (rule 1/3 충돌 해소)**:
3. 1단계 자유 번역이 segment 합쳤으면 (예: 입력 3개 → 자유 번역 2개), 자연스러운 의미 경계로 다시 나눠 {len(inputs)}개로 만들 것.
4. 1단계 자유 번역이 segment 나눴으면 (예: 입력 2개 → 자유 번역 3개), 의미 단위로 합쳐 {len(inputs)}개로 만들 것.

**금지 사항 (빈/반복/화자 차단)**:
5. **빈 string output 절대 부재** — 모든 outputs 항목은 비어있지 않은 한국어 번역. 부족분을 빈 칸으로 채우지 말 것.
6. **같은 본문 반복 절대 부재** — outputs 항목들이 서로 다른 내용. 부족분을 라인 반복으로 채우지 말 것.
7. 입력 {len(inputs)}개가 모두 비슷한 짧은 발화여도, 자유 번역의 해당 부분을 각각 정확히 매핑할 것.
8. **화자 라벨 출력 절대 부재** (5/23 — 코드 부착으로 분리) — 각 output 은 본문 한국어만. "이름:" 같은 화자 prefix 절대 부재.

**출력 형식**:
9. JSON 형식: {{"outputs": [str, str, ...]}}
10. timestamp 출력 절대 부재.

Input ({len(inputs)}개 원본 segment 본문, 영어 text 만):
{json.dumps({"inputs": inputs}, ensure_ascii=False, indent=2)}

자유 번역 결과 (1단계 출력):
{freeform_translation}

Output (JSON 만, 화자/timestamp 부재, 다른 텍스트 부재):"""


def _build_index_mapping_prompt(inputs: list, context: str) -> str:
    """Index Mapping 영역의 user prompt — TRANSLATION_SYSTEM_PROMPT 가 system 영역
    이라 가정. 본 user prompt 는 출력 형식 override 만 명시 (entity / Layer 8/11/13/15
    규칙은 system 에서 catch).

    Rule 1, 2 (timestamp 보존 / [HH:MM] 형식) override:
      - 출력 형식 = JSON {"outputs": [...]}
      - timestamp 영역 부재 (클라이언트가 zip 으로 별도 부착)
      - speaker label 영역 = Rule 2 의 한국어 화자명 정합 (예: "판카즈 샤르마(Pankaj Sharma): 본문")
    """
    return f"""[출력 형식 영역 — Rule 1, 2 의 timestamp 부분 override]

이번 호출은 Index Mapping path 영역. 출력 형식을 다음과 같이 변경한다:

1. 응답은 반드시 JSON 형식: {{"outputs": [str, str, ...]}}
2. outputs 배열은 정확히 {len(inputs)}개 항목 (같은 순서)
3. timestamp 출력 절대 부재 (클라이언트가 별도 부착)
4. 각 output string 형식: "한국어 화자명(English Name): 본문" (첫 등장) 또는 "한국어 화자명: 본문" (이후)
5. "Speaker A/B/C" 영문 라벨 출력 절대 부재 — Rule 2 정합 한국어 화자명
6. 다른 모든 규칙 (Rule 3~11 + _SHARED_LANG_RULES) 정합 유지

{context}

Input ({len(inputs)}개 항목, 각 "Speaker X: 영어 text" 형식):
{json.dumps({"inputs": inputs}, ensure_ascii=False, indent=2)}

Output (JSON 만, 다른 텍스트 부재):"""


def _call_llm_with_continuation(
    config: LLMConfig,
    messages: list,
    max_tokens: int,
    response_format: Optional[dict] = None,
    max_continuations: int = 3,
    timeout: Optional[float] = None,
) -> tuple:
    """finish_reason='length' 시 자동 continuation.

    truncation 명시 검출 + 이어쓰기 (drift 차단). JSON mode 영역의 continuation
    은 구조 보존 영역에서 본질 한계 영역 — 체크포인트 2 영역은 작은 chunk
    영역 → truncation 부재 가정. 진짜 truncation 시 _call_llm_with_index_mapping
    의 outer retry 영역에서 길이 미스매치 영역 catch + feedback retry.

    Args:
        timeout: request-level timeout (초). None 이면 SDK 기본값. Phase 4a-1 의
            xgrammar grammar-recovery loop 조기 차단용으로 inner 호출에 forward.

    Returns:
        tuple[str, str]: (accumulated_content, last_finish_reason)
    """
    accumulated = ""
    last_finish_reason = "unknown"
    current_messages = list(messages)

    for _cont in range(max_continuations + 1):
        content, finish_reason = _call_llm_once_with_reason(
            config, current_messages, max_tokens, response_format, timeout=timeout
        )
        accumulated += content
        last_finish_reason = finish_reason

        if finish_reason == "stop":
            return accumulated, finish_reason
        if finish_reason == "length":
            # JSON mode 영역의 continuation 은 본질 한계 영역 — outer retry 영역에서 처리
            if response_format and response_format.get("type", "").startswith("json"):
                return accumulated, finish_reason
            # Non-JSON 영역만 continuation
            current_messages = current_messages + [
                {"role": "assistant", "content": accumulated},
                {"role": "user", "content": "Continue from where you stopped. Do not repeat previous content."},
            ]
            continue
        # content_filter 등 — break
        break

    return accumulated, last_finish_reason


def _call_llm_with_index_mapping(
    config: LLMConfig,
    prompt: str,
    expected_count: int,
    max_retries: int = 3,
    log: Optional[ProgressFn] = None,
    enable_loose_on_timeout: bool = False,
    reject_empty_outputs: bool = False,
) -> list:
    """Index Mapping + 길이 검증 + retry feedback.

    Args:
        enable_loose_on_timeout: True 시 timeout 발생 → strict→loose 전환 (R3-수정,
            (가) 옵션 A 2단계 전용). 기본 False — 1-pass 동작 보존.
        reject_empty_outputs: True 시 outputs 안에 빈 string 있으면 retry 트리거
            (5/23 — 2-pass 빈 output 복구 1차). 기본 False — 1-pass 동작 보존
            (1-pass 는 화자 라벨 포함 출력이라 빈 비현실적이지만 명시 분리).

    Returns:
        List[str]: outputs 배열 (길이 = expected_count 보장, fallback 시 [번역 누락] padding)
    """
    log_fn = log or print
    # System = TRANSLATION_SYSTEM_PROMPT (Layer 8/11/13/15 entity 규칙 포함).
    # User = _build_index_mapping_prompt 의 출력 형식 override (JSON outputs 배열).
    messages: list = [
        {"role": "system", "content": TRANSLATION_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    # json_schema strict 모드 — minItems/maxItems 로 정확히 N개 강제.
    # 5/13 E2E 결과의 길이 미스매치 (23/22 outputs vs 25 expected) 근본 차단.
    # 5/12 endpoint verify: qwen3.6-35b-q5 의 json_schema strict + additionalProperties=False 정합.
    strict_response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "translation_outputs",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "outputs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": expected_count,
                        "maxItems": expected_count,
                    },
                },
                "required": ["outputs"],
                "additionalProperties": False,
            },
        },
    }
    # Phase 4a-1 — xgrammar grammar-recovery loop 회피용 fallback mode.
    # 5/16 진단: xgrammar 0.2.0 + strict schema 에서 일부 입력이 grammar-recovery
    # loop 진입 → 8192 tokens 까지 rejected token 재샘플링 (slow chunk 245~281초).
    # 첫 시도 strict, 실패 시 json_object mode 로 전환:
    #   - JSON parse fail 또는 finish_reason=length → loose mode 전환 후 retry
    #   - json_object 는 JSON 구문만 강제, 스키마 길이 강제 없음 → grammar 복잡도 낮음
    #   - 기존 length mismatch retry 가 결과 검증 담당 (양 환경 safety net)
    #
    # 5/17 시도 (실패, dead code 제거됨):
    #   - A-3 (strict 첫 시도 + 30초 timeout): httpx read timeout 한계로 wall-clock
    #     강제 불가 (chunk 9 가 281초 소비했지만 timeout 미발동). retry loop 의
    #     try/except APITimeoutError 블록은 dead code 가 되어 제거. helper 함수
    #     timeout 파라미터 시그니처는 future hook (wall-clock timeout 도입 시
    #     재활용) 으로 유지.
    loose_response_format = {"type": "json_object"}
    max_tokens = config.translation_max_tokens or TRANSLATION_MAX_TOKENS
    outputs: list = []
    use_strict_mode = True
    # R2 (5/23) — timeout 시 마지막 시도가 timeout 이었는지 추적 (fallback marker 결정).
    last_error_was_timeout = False

    for retry in range(max_retries):
        active_response_format = strict_response_format if use_strict_mode else loose_response_format
        try:
            content, finish_reason = _call_llm_with_continuation(
                config, messages, max_tokens, response_format=active_response_format
            )
            last_error_was_timeout = False
        except TimeoutError as exc:
            # R2 (5/23) — wall-clock timeout 시 strict mode 유지 retry. 90초 차단(f314d6e)
            # 후 간헐적 폭주 chunk 가 다음 시도에서 풀릴 가능성 catch.
            # R3-수정 (5/23, (가) 옵션 A 2단계 전용): enable_loose_on_timeout=True 시
            # strict → loose 전환. 1-pass 동작 보존을 위해 기본 False.
            log_fn(
                f"   ⚠ chunk wall-clock timeout — retry {retry + 1}/{max_retries}: {exc}"
            )
            if enable_loose_on_timeout and use_strict_mode:
                log_fn(f"   ↳ R3-수정: timeout 시 json_object mode 전환 (strict 부담 회피)")
                use_strict_mode = False
            last_error_was_timeout = True
            continue
        # JSON 파싱
        try:
            parsed = json.loads(content)
            outputs = parsed.get("outputs", []) or []
        except json.JSONDecodeError as exc:
            log_fn(f"   ⚠ JSON 파싱 부재 (retry {retry + 1}/{max_retries}): {exc}")
            # 첫 실패 시 loose mode 전환 (xgrammar grammar-recovery loop 회피)
            if use_strict_mode:
                log_fn(f"   ↳ json_object mode 전환 (xgrammar 우회)")
                use_strict_mode = False
            messages.append({
                "role": "user",
                "content": (
                    f"Previous response was not valid JSON. Return only "
                    f'{{"outputs": [...]}} with exactly {expected_count} items.'
                ),
            })
            continue

        # 길이 검증 — drift 근본 차단
        if len(outputs) == expected_count:
            # 5/23 — 빈 string 검출 (reject_empty_outputs=True 시, 2-pass 전용).
            # 1-pass 는 화자 라벨 포함 출력이라 빈 비현실적 — 기본 False 로 동작 보존.
            empty_indices = [
                i for i, o in enumerate(outputs)
                if not isinstance(o, str) or not o.strip()
            ]
            if reject_empty_outputs and empty_indices:
                log_fn(
                    f"   ⚠ 빈 output {len(empty_indices)}건 catch "
                    f"(idx={empty_indices[:5]}{'...' if len(empty_indices) > 5 else ''}, "
                    f"retry {retry + 1}/{max_retries})"
                )
                # strict mode 라면 loose 전환 (자유도 catch — 본문 채우기 가능성 ↑)
                if use_strict_mode:
                    log_fn(f"   ↳ 빈 output retry — json_object mode 전환")
                    use_strict_mode = False
                messages.append({"role": "assistant", "content": content})
                messages.append({
                    "role": "user",
                    "content": (
                        f"Previous output had {len(empty_indices)} empty items "
                        f"at indices {empty_indices[:10]}. "
                        f"All {expected_count} outputs MUST be non-empty Korean translations. "
                        f"Do NOT use empty strings or placeholders. Return complete JSON."
                    ),
                })
                continue
            log_fn(f"   ✅ Index Mapping 정합 — {len(outputs)} outputs (finish_reason={finish_reason})")
            return outputs

        # finish_reason=length + strict mode → grammar-recovery loop 가능성 → mode 전환
        if finish_reason == "length" and use_strict_mode:
            log_fn(f"   ↳ finish_reason=length 감지, json_object mode 전환 (xgrammar 우회)")
            use_strict_mode = False

        log_fn(
            f"   ⚠ 길이 미스매치: {len(outputs)} != {expected_count} "
            f"(retry {retry + 1}/{max_retries}, finish_reason={finish_reason})"
        )
        messages.append({"role": "assistant", "content": content})
        messages.append({
            "role": "user",
            "content": (
                f"Previous output had {len(outputs)} items. Need exactly "
                f"{expected_count} items in same order. Return complete JSON: "
                '{"outputs": [...]}.'
            ),
        })

    # 3 retries 모두 실패 — fallback (padding 또는 truncate).
    # R2 (5/23): 마지막 시도가 timeout 이면 [⚠ timeout] marker, 그 외 일반 [번역 누락].
    fallback_marker = TIMEOUT_PADDING_MARKER if last_error_was_timeout else "[번역 누락]"
    log_fn(
        f"   ⚠ Index Mapping retry {max_retries}회 실패 — fallback "
        f"({len(outputs)} → {expected_count}, marker={fallback_marker!r})"
    )
    if len(outputs) < expected_count:
        outputs = list(outputs) + [fallback_marker] * (expected_count - len(outputs))
    else:
        outputs = list(outputs)[:expected_count]
    return outputs


# A5 (5/23) — 2-pass 정렬 깨짐 deterministic 후처리.
# prompt 의존 부재 안전망 — 35b 가 rule 무시 시에도 차단.
_SPEAKER_PREFIX_RE = re.compile(r"^[A-Z]:\s+")


def _strip_input_speaker_prefix(text: str) -> str:
    """input 의 'A:'/'B:' 같은 단일 영문 대문자 prefix 를 제거.

    35b 가 1단계 자유 번역에서 input 의 `"A: text"` 형식 prefix 를 한국어 라벨 앞에
    잔존시킬 case 차단 (1단계 prompt rule 5 모호성, 5/23 진단).

    정상 형식 보호:
        - "한국어 화자명: 본문" — 한국어는 영문 대문자 부재 → 매치 부재 ✅
        - "한국어 화자명(English Name): 본문" — 영문 병기는 line 시작 부재 → 매치 부재 ✅
        - "Jensen Huang: 본문" — 영문 단어는 다음 글자가 소문자 → 매치 부재 ✅
        - "A: 티파니 잔젠: 본문" — 단일 대문자 + 콜론 + 공백 → 매치 → "티파니 잔젠: 본문" ✅

    Args:
        text: chunk output 한 항목.

    Returns:
        prefix strip 후 text. 매치 부재 시 원본 그대로.
    """
    return _SPEAKER_PREFIX_RE.sub("", text)


# 본문 라인 레벨 연속 반복 축약 (C, 5/28) — 더듬거림 구간을 2-pass 2단계가 같은
# 문장으로 채우는 회귀 차단. 같은 화자 + 같은 텍스트가 연속 N회+ 이고 텍스트가 충분히
# 길면 첫 라인만 남긴다. 짧은 발화(네./맞습니다.)·다른 화자 동일 발화·marker 는 보존.
_DEDUP_LINE_RE = re.compile(r"^(\[\d{1,2}:\d{2}(?::\d{2})?\])\s+([^:]+):\s*(.*)$", re.DOTALL)
_DEDUP_MIN_LEN = 10   # 텍스트 길이 < 이 값이면 횟수 무관 보존 (짧은 동의/감사/단어연상)
_DEDUP_MIN_RUN = 3    # 연속 동일 라인이 이 횟수 이상이면 축약
_DEDUP_SKIP_PREFIXES = ("[번역 누락]", "[⚠", "(음성 인식 오류")


def _collapse_repeated_lines(text: str, log: Optional[ProgressFn] = None) -> str:
    """같은 화자 + 같은 텍스트가 `_DEDUP_MIN_RUN` 회 이상 연속이고 텍스트가
    `_DEDUP_MIN_LEN` 자 이상이면 **첫 라인만 남기고 제거** (timestamp 는 첫 라인 것).

    1-pass·2-pass 공통 본문 조립 직후 적용. 짧은 발화(네./맞습니다.)·다른 화자 동일
    발화·marker([번역 누락]/[⚠ timeout]/음성 인식 오류) 는 보존 (실데이터 임계 근거).
    """
    parts = text.split("\n\n")
    out: List[str] = []
    collapsed = 0
    i, n = 0, len(parts)
    while i < n:
        m = _DEDUP_LINE_RE.match(parts[i].strip())
        if not m:
            out.append(parts[i])
            i += 1
            continue
        sp, tx = m.group(2).strip(), m.group(3).strip()
        # 연속 동일 (화자+텍스트) 그룹 길이 측정
        j = i + 1
        while j < n:
            mj = _DEDUP_LINE_RE.match(parts[j].strip())
            if not mj or mj.group(2).strip() != sp or mj.group(3).strip() != tx:
                break
            j += 1
        run = j - i
        is_marker = any(tx.startswith(p) for p in _DEDUP_SKIP_PREFIXES)
        if run >= _DEDUP_MIN_RUN and len(tx) >= _DEDUP_MIN_LEN and not is_marker:
            out.append(parts[i])  # 첫 라인만 유지
            collapsed += run - 1
        else:
            out.extend(parts[i:j])
        i = j
    if log and collapsed:
        log(f"   🔧 연속 반복 라인 축약 — {collapsed}줄 제거 (더듬거림 회귀 차단)")
    return "\n\n".join(out)


def _post_process_two_pass_outputs(
    outputs: list,
    expected_count: int,
    log: Optional[ProgressFn] = None,
) -> list:
    """A5 — 2-pass outputs deterministic 후처리 (5/23).

    1. **prefix strip**: 각 output 의 'A:'/'B:' 같은 입력 prefix 잔존 제거.
    2. **빈 segment 검출**: 빈 string output 을 "[번역 누락]" marker 로 교체.
    3. **반복 라인 검출**: consecutive 동일 output 발견 시 log 경고 (자동 제거 부재
       — 짧은 발화의 정상 반복 오인 방지).

    Args:
        outputs: _call_llm_with_index_mapping 결과 list.
        expected_count: 기대 길이 (안전 검사용).
        log: 진행 콜백.

    Returns:
        후처리된 outputs list (길이 = expected_count 보존).
    """
    log_fn = log or (lambda _m: None)
    processed = [_strip_input_speaker_prefix(o or "") for o in outputs]

    # 빈 segment → [번역 누락] marker
    empty_count = 0
    for i, o in enumerate(processed):
        if not o or not o.strip():
            processed[i] = "[번역 누락]"
            empty_count += 1
    if empty_count:
        log_fn(f"   ⚠ 2-pass 빈 output {empty_count}건 → [번역 누락] padding")

    # 연속 동일 라인 검출 (경고만)
    repeat_count = 0
    for i in range(1, len(processed)):
        if processed[i] == processed[i - 1] and processed[i] != "[번역 누락]":
            repeat_count += 1
    if repeat_count:
        log_fn(
            f"   ⚠ 2-pass 연속 동일 output {repeat_count}건 catch — 정상 반복 가능성"
        )

    return processed


def _resolve_speaker_label(
    speaker: str,
    speaker_cache: Optional[dict],
    seen_speakers: set,
) -> str:
    """5/23 — STT speaker label ("A","B",...) → 한국어 화자 라벨 결정론적 부착.

    영상 단위 첫 등장 영문 병기 catch (Layer 13 정합). cache 부재 fallback "화자 N".

    Args:
        speaker: STT label (예: "A","B","C",...).
        speaker_cache: {"A": {"english": "Pankaj Sharma", "korean": "판카즈 샤르마"}, ...}.
            None 또는 빈 dict 가능 (fallback 진입).
        seen_speakers: 영상 단위 첫 등장 catch set. 호출 후 본 함수가 add.

    Returns:
        라벨 문자열 (예: "판카즈 샤르마(Pankaj Sharma)" 첫 등장 / "판카즈 샤르마" 이후 / "화자 1" fallback).
    """
    is_first = speaker not in seen_speakers
    seen_speakers.add(speaker)

    meta = (speaker_cache or {}).get(speaker)
    if meta and meta.get("korean"):
        korean = meta["korean"]
        english = meta.get("english", "")
        if is_first and english:
            return f"{korean}({english})"
        return korean

    # fallback: "A" → "화자 1", "B" → "화자 2", ...
    try:
        idx = ord(speaker.upper()[0]) - ord("A") + 1
        if 1 <= idx <= 26:
            return f"화자 {idx}"
    except (IndexError, TypeError):
        pass
    return f"화자 {speaker or '?'}"


def _translate_chunk_two_pass(
    chunk: List[Segment],
    context_block: str,
    config: LLMConfig,
    log: Optional[ProgressFn] = None,
) -> List[str]:
    """(가) 옵션 A prototype — 2-pass 자유 번역 + 정렬.

    1단계: schema 부재 자유 번역 (`_build_freeform_translation_prompt`).
        - `_call_llm` 경유 (f314d6e wall-clock + HTTP timeout 안전망 적용).
        - response_format 부재 — 모델이 추론 부담 부재로 자연 한국어 catch.
    2단계: 자유 번역 결과를 N개 outputs 로 정렬 (`_build_alignment_prompt`).
        - `_call_llm_with_index_mapping` 재사용 + enable_loose_on_timeout=True (R3-수정).
        - schema strict (minItems/maxItems=N) 으로 N개 정합 보장.

    5/23 — 입력에서 speaker prefix 제거 ("A: text" → "text"). 화자 라벨은 client zip
    에서 코드 부착 (translate_chunk_index_mapping_v2). rule 1 딜레마 근본 해소.

    Args:
        chunk: 입력 segment N개.
        context_block: 영상 컨텍스트 + entity_cache (B06 §4.1).
        config: LLM 호출용.
        log: 진행 콜백.

    Returns:
        List[str]: 정렬된 outputs N개 (본문만, 화자 부재). fallback 시 padding 적용.
    """
    log_fn = log or (lambda _m: None)
    # 5/23 — speaker prefix 제거. 본문만 입력 → LLM 화자 처리 부재.
    inputs = [s.text for s in chunk]

    # 1단계 — 자유 번역.
    log_fn(f"   ↳ 2-pass 1단계: 자유 번역 ({len(inputs)} segments)")
    freeform_prompt = _build_freeform_translation_prompt(inputs, context_block)
    try:
        freeform = _call_llm(
            config,
            system=TRANSLATION_SYSTEM_PROMPT,
            user=freeform_prompt,
            max_tokens=config.translation_max_tokens or TRANSLATION_MAX_TOKENS,
        )
    except TimeoutError as exc:
        # 1단계 timeout — 2단계 정렬 input 부재 → 즉시 fallback padding.
        log_fn(f"   ⚠ 2-pass 1단계 timeout — 전체 fallback ({len(inputs)} segments): {exc}")
        return [TIMEOUT_PADDING_MARKER] * len(inputs)

    if not freeform or not freeform.strip():
        log_fn(f"   ⚠ 2-pass 1단계 빈 응답 — 전체 fallback ({len(inputs)} segments)")
        return ["[번역 누락]"] * len(inputs)

    # 5/23 — 1단계 결과 로깅 (책임 단계 확정 + 옵션 나 활용 자료).
    freeform_lines = [line.strip() for line in freeform.split("\n\n") if line.strip()]
    log_fn(
        f"   📝 2-pass 1단계 출력 — {len(freeform_lines)} lines / N={len(inputs)}, "
        f"empty lines: {sum(1 for ln in freeform_lines if not ln)}"
    )

    # 2단계 — 정렬 (schema strict + R3-수정 loose 전환 + 빈 output retry).
    log_fn(f"   ↳ 2-pass 2단계: 정렬 ({len(inputs)} outputs schema strict)")
    alignment_prompt = _build_alignment_prompt(inputs, freeform)
    outputs = _call_llm_with_index_mapping(
        config,
        alignment_prompt,
        expected_count=len(inputs),
        max_retries=3,
        log=log,
        enable_loose_on_timeout=True,
        reject_empty_outputs=True,   # 5/23 — 1차 복구: 빈 string retry
    )

    # 5/23 — 복구 시퀀스 (2차 + 3차).
    outputs = _recover_empty_outputs(
        outputs, freeform_lines, inputs, chunk, config, log,
    )

    # A5 (5/23) — deterministic 후처리 (prefix strip + 잔존 빈 → marker + 반복 경고).
    return _post_process_two_pass_outputs(outputs, len(inputs), log)


def _recover_empty_outputs(
    outputs: List[str],
    freeform_lines: List[str],
    inputs: List[str],
    chunk: List[Segment],
    config: LLMConfig,
    log: Optional[ProgressFn] = None,
) -> List[str]:
    """5/23 — 2-pass 빈 output 복구 시퀀스 (2차 + 3차).

    2차 (옵션 나): 1단계 자유 번역 line 수가 N 과 정합하면 해당 index 의 1단계 본문 활용
        → LLM 호출 0 으로 복구.
    3차 (옵션 다): 1단계도 빈 또는 line 수 불일치 → 해당 segment STT text 단독 재번역
        (1-pass 방식, 본 segment 하나만 _call_llm 호출).

    Args:
        outputs: 2단계 정렬 결과 N개 (일부 빈 가능).
        freeform_lines: 1단계 자유 번역 결과를 빈 줄 구분으로 split.
        inputs: 원본 STT text N개.
        chunk: 원본 segment N개 (speaker 정보 등).
        config: LLM 호출용.
        log: 진행 콜백.

    Returns:
        복구된 outputs N개 (실패 시 빈 잔존 — A5 가 marker 교체).
    """
    log_fn = log or (lambda _m: None)
    processed = list(outputs)

    # 2차 — 1단계 자유 번역 활용 (line 수 정합 시).
    if len(freeform_lines) == len(inputs):
        recovered_2nd = 0
        for i, out in enumerate(processed):
            if not isinstance(out, str) or not out.strip():
                candidate = freeform_lines[i].strip() if i < len(freeform_lines) else ""
                if candidate:
                    processed[i] = candidate
                    recovered_2nd += 1
        if recovered_2nd:
            log_fn(f"   🛟 빈 output 복구 2차 (1단계 활용): {recovered_2nd}건")

    # 3차 — 단독 재번역 (해당 segment STT text 만).
    still_empty = [
        i for i, o in enumerate(processed)
        if not isinstance(o, str) or not o.strip()
    ]
    if still_empty:
        log_fn(f"   🛟 빈 output 복구 3차 (단독 재번역): {len(still_empty)}건 시도")
        recovered_3rd = 0
        for i in still_empty:
            seg_text = inputs[i] if i < len(inputs) else ""
            if not seg_text or not seg_text.strip():
                continue   # STT 원본도 빈 — 복구 부재 → 최종 marker
            try:
                solo = _call_llm(
                    config,
                    system=TRANSLATION_SYSTEM_PROMPT,
                    user=(
                        f"[단독 재번역 — (가) 2-pass 3차 복구]\n\n"
                        f"다음 영어 발화 1건을 자연스러운 한국어로 번역하라. "
                        f"화자 라벨/timestamp 출력 부재 — 본문 한국어만.\n\n"
                        f"Input: {seg_text!r}\n\n"
                        f"Output (한국어 본문만):"
                    ),
                    max_tokens=512,
                )
                if solo and solo.strip():
                    processed[i] = solo.strip()
                    recovered_3rd += 1
            except Exception as exc:
                log_fn(f"   ⚠ 빈 output 복구 3차 idx={i} 실패: {exc}")
        if recovered_3rd:
            log_fn(f"   🛟 빈 output 복구 3차 (단독 재번역): {recovered_3rd}건 catch")
        remaining = sum(
            1 for o in processed
            if not isinstance(o, str) or not o.strip()
        )
        if remaining:
            log_fn(f"   ⚠ 복구 후에도 잔존 빈 output: {remaining}건 → 최종 marker")

    return processed


def translate_chunk_index_mapping_v2(
    chunk: List[Segment],
    context_block: str,
    config: LLMConfig,
    log: Optional[ProgressFn] = None,
    speaker_cache: Optional[dict] = None,
    seen_speakers: Optional[set] = None,
) -> str:
    """단일 chunk 영역의 Index Mapping 적용 — 체크포인트 2 verify 영역.

    체크포인트 3 시 translate_transcript 영역 통합 결정.

    (가) 옵션 A prototype 토글 (5/23):
        GURUNOTE_TWO_PASS 환경변수 (기본 on). off 강제: GURUNOTE_TWO_PASS=0.
        2-pass 분리 (자유 번역 → 정렬). off 시 기존 1-pass 보존.

    5/23 — speaker_cache + seen_speakers 인자 추가 (2-pass 화자 라벨 코드 부착).
        1-pass path 영향 부재 (인자 사용 부재).
    """
    is_two_pass = os.environ.get("GURUNOTE_TWO_PASS", "1") == "1"

    if is_two_pass:
        # 2-pass — 입력 본문만 (speaker prefix 부재), 화자 라벨은 client zip 코드 부착.
        outputs = _translate_chunk_two_pass(chunk, context_block, config, log)
    else:
        # 1-pass — 기존 path 보존 (speaker prefix 포함된 input, LLM 이 화자 라벨 출력).
        inputs = [f"{s.speaker}: {s.text}" for s in chunk]
        prompt = _build_index_mapping_prompt(inputs, context_block)
        outputs = _call_llm_with_index_mapping(
            config, prompt, expected_count=len(inputs), max_retries=3, log=log,
        )

    # 클라이언트 측 timestamp 부착 — zip 으로 결정론적 매핑 (drift 불가능).
    # Line break = \n\n (Layer 14 정합 — Index Mapping 영역 결정론적 정합).
    # 5/23 — 2-pass 시 화자 라벨도 client zip 코드 부착 (식별 1회 + 결정론적).
    # 1-pass 시 LLM output 에 화자 라벨 포함됨 → korean 그대로 사용 (기존 동작).
    result_lines: List[str] = []
    # 2-pass 경로의 seen_speakers — caller (translate_transcript) 가 영상 단위 공유.
    # caller 부재 시 chunk 단위 로컬 set (단독 호출 case).
    local_seen = seen_speakers if seen_speakers is not None else set()
    for segment, korean in zip(chunk, outputs):
        ts = f"[{_format_ts(segment.start)}]"
        if is_two_pass:
            speaker_label = _resolve_speaker_label(segment.speaker, speaker_cache, local_seen)
            result_lines.append(f"{ts} {speaker_label}: {korean}")
        else:
            result_lines.append(f"{ts} {korean}")
    return "\n\n".join(result_lines)
