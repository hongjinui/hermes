---
name: simulate
description: Hermes 파이프라인 리소스 시뮬레이션. 방 구성과 메시지 수를 인자로 주면 SQLite/ChromaDB insert 횟수, 배치 수, 메모리 피크를 단계별로 계산해 출력.
argument-hint: "기사방:N:M 대화방:N:M [url비율:0.N] [크롤성공률:0.N] [포워딩비율:0.N] [텍스트비율:0.N]"
---

Hermes 파이프라인 실행 시 SQLite/ChromaDB insert 횟수와 메모리 사용량을 시뮬레이션합니다.

## 인자 파싱

`$ARGUMENTS` 예시:
- `기사방:3:1000 대화방:1:500` → 기사방 3개 각 1000개, 대화방 1개 500개
- `기사방:3:1000 대화방:2:500 url비율:0.4 크롤성공률:0.8`
- 인자 없으면 예시 시나리오 (기사방 3개×1000, 대화방 1개×500) 사용

파싱 규칙:
- `기사방:N:M` → article type 방 N개, 각 M개 메시지
- `대화방:N:M` → conversation type 방 N개, 각 M개 메시지
- `url비율:0.N` → 메시지 중 URL 포함 비율 (기본 0.30)
- `크롤성공률:0.N` → 크롤링 성공률 (기본 0.70)
- `포워딩비율:0.N` → 대화방 메시지 중 포워딩 비율 (기본 0.20)
- `텍스트비율:0.N` → 기사방 메시지 중 URL 없는 100자+ 비율 (기본 0.50)

## 실행 절차

Python 스크립트를 `/tmp/hermes_simulate.py`로 작성 후 실행.

### 시뮬레이션 로직 (main.py 파이프라인 순서 기준)

파이프라인 단계별로 다음을 계산:

**Step 0 — 초기화**
```
article_rooms = N개, 각 M개
conv_rooms    = N개, 각 M개
total_msgs    = article_msgs + conv_msgs
```

**Step 1 — 메시지 수집 및 SQLite 저장 (main.py:120)**
```
SQLite messages INSERT = total_msgs  (save_messages_bulk, 1회 executemany)
SQLite sync_state UPSERT = article_rooms + conv_rooms  (방별 1회)
```

**Step 2 — ChromaDB messages 벡터 적재 (main.py:128)**
```
chroma_messages INSERT = total_msgs
chroma_messages 배치 수 = ceil(total_msgs / batch_size)  # batch_size=100
```

**Step 3 — URL 크롤링 (main.py:140~197)**
```
url_msgs = total_msgs × url비율
크롤_성공 = url_msgs × 크롤성공률
크롤_실패 = url_msgs × (1 - 크롤성공률)

SQLite articles INSERT = 크롤_성공  (save_articles_bulk, 1회 executemany)
SQLite crawl_log INSERT = url_msgs  (성공+실패 모두, save_crawl_logs_bulk)

평균 청크 수 = ceil(avg_article_len / chunk_size)  # avg_article_len=1500, chunk_size=500 → 3청크
chroma_articles INSERT = 크롤_성공 × 평균청크수
chroma_articles 배치 수 = ceil(chroma_articles INSERT / batch_size)
```

**Step 4 — 기사방 텍스트 청킹 (main.py:199~229)**
```
article_text_msgs = article_msgs_total × (1 - url비율) × 텍스트비율
  # URL 없는 메시지 중 100자+ 비율

SQLite articles INSERT = article_text_msgs  (pseudo article, msg:// URL)
chroma_articles INSERT += article_text_msgs × 평균청크수
```

**Step 5 — 대화방 포워딩 청킹 (main.py:231~263)**
```
fwd_msgs = conv_msgs_total × 포워딩비율
  # URL 없는 포워딩 메시지 중 100자+ (단순화: 포워딩×0.8 가정)
fwd_text = fwd_msgs × 0.8

SQLite articles INSERT = fwd_text
chroma_articles INSERT += fwd_text × 평균청크수
```

**Step 6 — 대화 요약 (main.py:265~280)**
```
# 방별 1개 요약 (오늘 날짜 기준)
summarizable = conv_msgs_total × (1 - 포워딩비율)  # 포워딩 아닌 메시지

SQLite summaries INSERT = conv_rooms  (방별 1건)
chroma_summaries INSERT = conv_rooms  (방별 1 doc)
Claude API 호출 = conv_rooms  # summarizer.summarize() 1회/방
```

### 메모리 추정

파이프라인 실행 중 메모리 피크 시점을 추적:

```
# 피크 1: collect_all() 완료 직후 (all_messages 리스트)
all_messages 메모리 = total_msgs × avg_msg_size  # avg_msg_size ≈ 800 bytes (텍스트 포함)

# 피크 2: URL 크롤링 결과 수집 직후 (articles + chunks 동시 메모리)
articles_chunks 메모리 = 크롤_성공 × avg_article_len × 1.5  # 원문 + 청크 오버헤드

# 피크 3: ChromaDB add 직전 배치 (ids + docs + metas × batch_size)
chroma_batch 메모리 = batch_size × avg_doc_size  # ≈ 100 × 1500 bytes
```

### 출력 형식

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 Hermes 파이프라인 시뮬레이션
 시나리오: 기사방 3개×1000, 대화방 1개×500
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[입력 파라미터]
  기사방         : 3개 × 1,000개 = 3,000 메시지
  대화방         : 1개 × 500개  = 500 메시지
  전체 메시지    : 3,500개
  URL 포함 비율  : 30% → 1,050개 URL 메시지
  크롤링 성공률  : 70% → 735개 기사
  (기타 파라미터...)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[Step 1] 메시지 저장
  SQLite messages   : INSERT 3,500행 (executemany 1회)
  SQLite sync_state : UPSERT 4행 (방별 1회)

[Step 2] 메시지 벡터 임베딩
  ChromaDB messages : ADD 3,500개 (배치 35회 × 100개)

[Step 3] URL 크롤링
  크롤 시도         : 1,050개
  SQLite articles   : INSERT 735행 (executemany 1회)
  SQLite crawl_log  : INSERT 1,050행 (executemany 1회)
  ChromaDB articles : ADD 2,205개 청크 (735기사 × 평균3청크, 배치 23회)

[Step 4] 기사방 텍스트 청킹
  대상 메시지       : 1,050개 (URL없는 기사방 메시지 × 50%)
  SQLite articles   : INSERT 1,050행
  ChromaDB articles : ADD 3,150개 청크 (배치 32회)

[Step 5] 대화방 포워딩 청킹
  대상 메시지       : 80개 (포워딩 × 텍스트 보유)
  SQLite articles   : INSERT 80행
  ChromaDB articles : ADD 240개 청크 (배치 3회)

[Step 6] 대화 요약
  대상 방           : 1개
  SQLite summaries  : INSERT 1행
  ChromaDB summaries: ADD 1개 (배치 1회)
  Claude API 호출   : 1회 (방당 1회)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[SQLite 합계]
  messages   : 3,500 INSERT
  articles   : 1,865 INSERT (크롤 735 + 텍스트 1,050 + 포워딩 80)
  crawl_log  : 1,050 INSERT
  summaries  : 1 INSERT
  sync_state : 4 UPSERT
  ────────────────────────────
  총 DB 작업 : 6,420행

[ChromaDB 합계]
  messages   : 3,500 벡터
  articles   : 5,595 벡터 (청크 합산)
  summaries  : 1 벡터
  ────────────────────────────
  총 벡터    : 9,096개
  총 배치    : 94회

[메모리 피크 추정]
  피크1 all_messages  : ~2.8 MB  (3,500 × 800B)
  피크2 articles+청크 : ~1.1 MB  (735 × 1,500B × 1.5)
  피크3 ChromaDB 배치 : ~0.1 MB  (100 × 1,500B)
  예상 피크           : ~4~6 MB  (Python 런타임 제외)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 주의

- 크롤링은 비동기 병렬 처리(`asyncio.gather`) → 메모리는 concurrency(기본 10)개씩 동시 점유
- ChromaDB 배치는 embed_batch_size(기본 100) 기준이며 실제 임베딩 모델 메모리는 별도 (sentence-transformers ~500MB 상시)
- 시뮬레이션은 추정값이며 실제 URL/텍스트 분포, 중복 메시지에 따라 달라질 수 있음
- config.yaml의 `chunk_size`, `embed_batch_size`, `crawl_concurrency` 값도 읽어 반영할 것
