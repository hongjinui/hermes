---
name: gen-excel
description: SQLite DB 또는 직접 정의한 테이블 스키마를 hermes_tables.xlsx 형식으로 Excel 파일 생성. database.py 자동 파싱 또는 인자로 DB 경로/테이블 지정 가능.
argument-hint: "[출력파일명.xlsx] [db경로 또는 'auto']"
---

SQLite 테이블 정의를 hermes_tables.xlsx 형식의 Excel 파일로 생성합니다.

## 인자 파싱

`$ARGUMENTS` 형식: `[출력파일명.xlsx] [db경로]`

- 인자 없음 → 출력: `hermes_tables.xlsx`, DB: `database.py` 파싱 후 스키마 직접 사용
- 인자 1개 (`.xlsx` 끝) → 해당 파일명, DB: `database.py` 파싱
- 인자 1개 (`.db`/`.sqlite` 끝) → 출력: `hermes_tables.xlsx`, DB: 해당 경로
- 인자 2개 → 첫째=파일명, 둘째=DB 경로

## 실행 절차

1. **스키마 수집**
   - DB 경로가 주어진 경우: 해당 `.db` / `.sqlite` 파일에 직접 연결해 `sqlite_master`로 모든 테이블 및 컬럼 자동 조회
   - DB 경로가 없는 경우: `database.py`를 읽어 `CREATE TABLE` 구문 파싱으로 스키마 추출

2. **openpyxl 환경 준비** (없으면 설치):
   ```
   python3 -m venv /tmp/xlvenv && /tmp/xlvenv/bin/pip install openpyxl -q
   ```

3. **Python 스크립트를 `/tmp/gen_excel.py`로 작성 후 실행**

   시트 구성 (hermes_tables.xlsx 동일 형식):
   - **전체요약** 시트 (첫 번째): 테이블명 / 컬럼수 / 설명 / 주요 특이사항
   - **테이블별 시트**: 컬럼명 / 데이터타입 / 제약조건(PK·NOT NULL·UNIQUE·DEFAULT) / 설명 / 비고

   스타일 규칙:
   - 헤더 행: 굵게, 배경색 `4472C4` (파란 계열), 글자색 흰색
   - 전체요약 헤더: 배경색 `2F5496`
   - 컬럼 너비 자동 조정 (최소 12, 최대 50)
   - 모든 셀 테두리 적용

4. **설명 자동 생성 규칙**
   - `id` → "자동 증가 기본키"
   - `*_at` → "KST 기준 일시 (datetime('now', '+9 hours'))", 비고에 "KST" 명시
   - `timestamp` → "KST 기준 타임스탬프", 비고에 "KST"
   - `room_link` → "텔레그램 채널/그룹 링크"
   - `room_title` → "채널/그룹 표시명"
   - `urls` / `authors` / `message_ids` → "JSON 배열 (TEXT)"
   - `is_forwarded` / `summarized` → "0/1 불리언 플래그"
   - 그 외: 컬럼명을 스네이크케이스 분리해 자연어 설명 생성

5. **저장 경로**: `/Users/hongjin-ui/workspace/hermes/<출력파일명>`

6. **완료 출력**: 생성된 시트 목록, 총 테이블 수, 파일 전체 경로

## 주의

- `database.py` 파싱 시 실제 소스를 읽어 반영 (하드코딩 금지)
- DB 파일 직접 연결 시 `PRAGMA table_info(테이블명)` 으로 컬럼 메타 조회
- 이미 같은 이름의 파일이 있으면 덮어씀 (경고 출력 후 진행)
