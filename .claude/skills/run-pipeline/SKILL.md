---
name: run-pipeline
description: Hermes 텔레그램 RAG 파이프라인 실행 및 디버깅. 파이프라인 실행, 로그 확인, 에러 진단, DB 상태 점검을 한 번에 수행.
argument-hint: "[--dry-run | --check-db | --logs]"
---

Hermes 파이프라인 관련 작업을 수행합니다. `$ARGUMENTS`를 참고하여 아래 중 적절한 작업을 실행하세요.

## 인수가 없거나 `--run`인 경우
1. `config.yaml` 존재 여부 확인
2. `.venv` 가상환경 존재 여부 확인
3. 아래 명령어로 파이프라인 실행:
   ```
   cd /Users/hongjin-ui/workspace/hermes && .venv/bin/python main.py
   ```
4. 실행 후 `logs/hermes.log` 마지막 50줄 출력
5. 에러가 있으면 원인 분석 및 수정 방법 제시

## `--dry-run`인 경우
config.yaml을 읽어 아래를 검증하고 보고서 출력:
- telegram.api_id / api_hash / phone 설정 여부
- anthropic.api_key 설정 여부
- chatrooms 목록 (링크, 타입)
- settings 값 (chunk_size, embed_batch_size, crawl_timeout 등)
- data/ 디렉터리 및 DB 파일 존재 여부

## `--check-db`인 경우
SQLite DB(`data/telegram.db`)의 현황을 확인하고 표 형태로 출력:
```sql
SELECT '메시지' as 테이블, COUNT(*) as 건수 FROM messages
UNION ALL SELECT '기사', COUNT(*) FROM articles
UNION ALL SELECT '요약', COUNT(*) FROM summaries
UNION ALL SELECT '동기화상태', COUNT(*) FROM sync_state
UNION ALL SELECT '크롤로그', COUNT(*) FROM crawl_log;
```
그리고 sync_state 전체 내용을 출력해 각 방의 마지막 동기화 시각과 message_id를 보여주세요.

## `--logs`인 경우
`logs/hermes.log`의 마지막 100줄을 읽어:
- ERROR / WARNING 라인만 추출해 요약
- 정상 완료됐는지 ("파이프라인 완료" 포함 여부) 확인
- 크롤링 성공/실패/스킵 통계 추출해 출력
