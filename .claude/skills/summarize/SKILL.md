---
name: summarize
description: 텔레그램 메시지 수집 후 Claude Code가 직접 대화를 요약하여 DB에 저장. 수집→요약→저장 전체 흐름을 한 번에 수행.
argument-hint: "[날짜범위] [--collect-only | --summarize-only | --status]"
---

텔레그램 대화 메시지를 수집하고 Claude Code가 직접 요약하여 DB에 저장합니다.
Anthropic API 없이 Claude Code 자체가 요약을 수행합니다.

`$ARGUMENTS` 를 참고하여 적절한 작업을 수행하세요.

## 프로젝트 정보
- Python: `/Users/jinui/workspace/hermes/.venv/bin/python`
- 작업 디렉토리: `/Users/jinui/workspace/hermes`
- 헬퍼 도구: `summary_helper.py` (status, export, export-all, save, save-one, verify)

## 인수 없는 경우 (기본: 오늘 수집+요약)
1. 미요약 현황 확인: `.venv/bin/python summary_helper.py status`
2. 미요약 메시지가 없으면 → 오늘 날짜로 수집 실행 후 요약
3. 미요약 메시지가 있으면 → 바로 요약 진행

## 날짜 범위 지정 (예: `4/8~4/12`, `2026-04-08 2026-04-12`)
1. 파이프라인 실행으로 메시지 수집:
   ```bash
   .venv/bin/python main.py --date <시작> --to-date <종료>
   ```
2. 수집 완료 후 요약 진행

## `--collect-only`
수집만 수행하고 요약은 하지 않습니다.
```bash
.venv/bin/python main.py --date <시작> --to-date <종료>
```

## `--summarize-only`
수집 없이 DB에 있는 미요약 메시지만 요약합니다.

## `--status`
```bash
.venv/bin/python summary_helper.py status
```

## 요약 수행 절차

### 1단계: 미요약 현황 파악
```bash
.venv/bin/python summary_helper.py status
```

### 2단계: 방별/날짜별 메시지 읽기
대량 메시지(100건+)가 있는 방은 Agent를 사용해 병렬 처리합니다.

메시지 읽기:
```bash
# 특정 방/날짜 (샘플링)
.venv/bin/python summary_helper.py export <room_link> <date> --sample --limit 100

# 전체 미요약 메시지 개요
.venv/bin/python summary_helper.py export-all --limit 80
```

또는 sqlite3로 직접 조회:
```bash
sqlite3 data/telegram.db "SELECT '[' || substr(timestamp,1,16) || '] ' || substr(text,1,200) FROM messages WHERE room_link='<room_link>' AND room_type='conversation' AND summarized=0 AND is_forwarded=0 AND DATE(timestamp)='<date>' ORDER BY timestamp;"
```

### 3단계: 요약 생성
메시지를 읽고 아래 형식으로 요약을 생성합니다:
- 주요 주제 2~5개를 bullet point로
- 각 항목은 1~2문장 이내
- 중복/잡담은 제외
- 중요한 정보(수치, 이름, 링크 등)는 유지

### 4단계: DB 저장
방법 A — JSON 파일로 일괄 저장 (권장):
```json
[
  {
    "room_link": "-100xxx",
    "room_title": "방 이름",
    "date": "2026-04-08",
    "msg_ids": [1, 2, 3],
    "summary": "- 요약 내용\n- 항목2"
  }
]
```
```bash
.venv/bin/python summary_helper.py save <json_file>
```

방법 B — Python 스크립트 작성하여 실행:
```python
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from database import Database

DB_PATH = str(Path(__file__).parent / "data" / "telegram.db")
db = Database(DB_PATH)

SUMMARIES = [...]  # 위 JSON과 같은 형식

for s in SUMMARIES:
    db.save_summary(s["room_link"], s["room_title"], s["summary"], s["msg_ids"], s["date"])
    db.mark_messages_summarized(s["msg_ids"], s["room_link"])
    print(f"OK: [{s['room_title']}] {s['date']} — {len(s['msg_ids'])}건")
```

방법 C — 단건 저장:
```bash
.venv/bin/python summary_helper.py save-one <room_link> <date> "요약 텍스트"
```

### 5단계: 검증
```bash
.venv/bin/python summary_helper.py verify
```

## 대량 처리 전략
- 100건 이하: 직접 읽고 요약
- 100~500건: export --sample로 샘플링하여 요약
- 500건 이상: Agent를 사용해 병렬 처리. 각 Agent가 방 하나씩 담당
  ```
  Agent(subagent_type="general-purpose", prompt="... 메시지 읽고 요약 후 DB 저장 ...")
  ```

## 주의사항
- summaries 테이블에 (room_link, date) unique index가 있으므로 같은 방/날짜를 두 번 저장하면 에러 발생
- 저장 전 해당 날짜에 이미 요약이 있는지 확인 필요
- 임시 스크립트는 작업 후 정리
