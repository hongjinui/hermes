---
name: refactor
description: Hermes 코드 공통화 및 리팩터링. 중복 코드 탐색, utils.py 공통 함수 추출, 예외처리 누락 점검, 일관성 검사를 수행.
argument-hint: "[파일명 | --audit | --utils | --exceptions]"
---

Hermes 코드베이스의 공통화 및 리팩터링 작업을 수행합니다.

## 인수가 없거나 `--audit`인 경우 — 전체 점검
모든 `.py` 파일을 읽어 아래 항목을 점검하고 보고서를 출력합니다:

### 1. 중복 코드 탐색
- 2개 이상 파일에서 반복되는 로직 (날짜 변환, 에러 로깅 패턴, DB 연결 등)
- 공통화 가능한 상수 (KST timezone, 기본값 등)

### 2. 예외처리 누락
- try/except 없이 외부 리소스 접근하는 곳 (DB, API, 파일 I/O)
- `list[0]` 형태의 인덱스 직접 접근 (IndexError 위험)
- 딕셔너리 `dict["key"]` 직접 접근 (KeyError 위험)

### 3. 일관성 점검
- KST 기준 날짜/시각 처리가 일관되게 적용됐는지
- 로깅 포맷이 통일됐는지
- 타입 힌트가 누락된 public 함수

### 4. utils.py 활용 여부
- `extract_claude_text`, `first` 함수가 모든 파일에서 올바르게 사용되는지
- utils.py에 추가하면 좋을 함수가 있는지

보고서 형식:
```
## [파일명]
- 문제: 설명
  위치: 함수명 또는 라인
  제안: 수정 방법
```

## `--utils`인 경우 — utils.py 공통 함수 추출
전체 코드를 분석해 utils.py에 추가할 만한 함수를 제안하고, 승인 시 추가합니다.
추가 전 반드시 어느 파일에서 몇 번 중복되는지 근거를 제시하세요.

## `--exceptions`인 경우 — 예외처리만 집중 점검
예외처리 누락 항목만 추려 심각도(CRITICAL / WARNING / INFO)와 함께 출력합니다.
- CRITICAL: 프로그램 중단 가능성 있는 미처리 예외
- WARNING: 데이터 유실 가능성
- INFO: 개선 권장

## 특정 파일명이 인수인 경우
해당 파일만 점검합니다. 예: `/refactor collector.py`
