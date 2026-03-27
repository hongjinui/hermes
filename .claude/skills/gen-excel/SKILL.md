---
name: gen-excel
description: Hermes 프로젝트의 SQLite 테이블 정의를 Excel 파일로 생성. database.py 스키마를 읽어 컬럼명, 타입, 제약조건, 설명을 담은 xlsx 파일 생성.
argument-hint: "[출력파일명.xlsx]"
---

Hermes SQLite 테이블 정의 Excel 파일을 생성합니다.

## 실행 절차

1. `database.py`를 읽어 최신 스키마(테이블명, 컬럼, 타입, 제약조건) 파악
2. 출력 파일명은 `$ARGUMENTS`가 있으면 그 값, 없으면 `hermes_tables.xlsx` 사용
3. `/tmp/xlvenv`에 openpyxl 설치 확인 (없으면 설치):
   ```
   python3 -m venv /tmp/xlvenv && /tmp/xlvenv/bin/pip install openpyxl -q
   ```
4. Python 스크립트를 `/tmp/gen_excel.py`로 작성한 뒤 실행:
   - 시트 구성: 각 테이블마다 별도 시트 + 첫 번째에 "전체요약" 시트
   - 전체요약 시트: 테이블명, 컬럼수, 설명, 주요 특이사항
   - 개별 시트: 컬럼명 / 데이터타입 / 제약조건 / 설명 / 비고(KST 여부 등) 컬럼 포함
   - 헤더는 굵게, 첫 행 배경색 적용 (파란 계열)
   - 컬럼 너비 자동 조정
5. 생성된 파일을 `/Users/hongjin-ui/workspace/hermes/` 에 저장
6. 완료 후 생성된 시트 목록과 파일 경로 출력

## 포함할 테이블
- messages (메시지 원본)
- articles (크롤링 기사 + pseudo 기사)
- summaries (대화 요약)
- sync_state (방별 동기화 상태)
- crawl_log (크롤링 시도 로그)

## 주의
- database.py의 실제 스키마를 직접 읽어 반영 (오래된 스키마 하드코딩 금지)
- KST 관련 컬럼(timestamp, created_at, last_sync_at, attempted_at)은 비고에 "KST" 명시
