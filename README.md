# Hermes

텔레그램 채널/그룹에서 메시지를 수집하고, 기사를 크롤링하며, 대화를 요약해 Claude Desktop에서 RAG 검색이 가능하도록 만드는 파이프라인입니다.

## 구조

```
텔레그램 채널/그룹
    │
    ▼
collector.py        메시지 수집 (Telethon MTProto)
    │
    ├─ 기사방 ──── crawler.py       URL 기사 크롤링
    │              embedder.py      텍스트 청킹 → ChromaDB
    │
    └─ 대화방 ──── summarizer.py    유저 대화 일별 요약 (Claude)
                   embedder.py      요약 + 스크랩 → ChromaDB
                       │
                       ▼
                   database.py      SQLite (원본 저장)
                   ChromaDB         벡터 검색
                       │
                       ▼
                   mcp_server.py    Claude Desktop 연동 (MCP)
```

### 채팅방 타입

| 타입 | 설명 | 처리 방식 |
|------|------|----------|
| `article` | 기사/스크랩 위주 채널 | URL → 기사 크롤링, 텍스트 → 청킹 저장 |
| `conversation` | 유저 대화 그룹 | 포워딩 → 청킹 저장, 직접 작성 → 일별 요약 |

## 준비물

- Python 3.11+
- [Telegram API 키](https://my.telegram.org) (api_id, api_hash)
- [Anthropic API 키](https://console.anthropic.com)
- [Claude Desktop](https://claude.ai/download)

## 설치

```bash
git clone https://github.com/YOUR_USERNAME/hermes.git
cd hermes
bash setup.sh
```

설치 후 `config.yaml`을 열어 아래 항목을 입력합니다.

## 설정

```yaml
telegram:
  api_id: "12345678"              # my.telegram.org에서 발급
  api_hash: "abcdef1234..."       # my.telegram.org에서 발급
  phone: "+821012345678"          # 국가코드 포함

anthropic:
  api_key: "sk-ant-..."           # console.anthropic.com에서 발급

chatrooms:
  - link: "https://t.me/채널명"
    type: "article"
  - link: "https://t.me/+초대링크해시"   # 비공개방은 초대링크
    type: "conversation"

settings:
  chunk_size: 500
  claude_model: "claude-sonnet-4-6"
  summary_batch_size: 50
  data_dir: "data"
  log_dir: "logs"
```

> **주의**: `config.yaml`은 `.gitignore`에 포함되어 있어 GitHub에 올라가지 않습니다.

## 실행

### 메시지 수집 (매일 1회)

```bash
.venv/bin/python main.py
```

첫 실행 시 텔레그램 인증번호 입력이 필요합니다. 이후 세션이 저장되어 자동 로그인됩니다.

### Claude Desktop 연동 (MCP)

`setup.sh`가 자동으로 `~/Library/Application Support/Claude/claude_desktop_config.json`을 생성합니다.

Claude Desktop을 재시작하면 아래처럼 사용할 수 있습니다.

> "지난주 AI 관련 주요 내용 요약해줘"
> "비트코인 언급된 메시지 찾아줘"

## 파일 구조

```
hermes/
├── main.py              파이프라인 진입점
├── collector.py         텔레그램 메시지 수집
├── crawler.py           기사 크롤링 및 청킹
├── embedder.py          벡터 임베딩 (sentence-transformers)
├── summarizer.py        대화 요약 (Claude API)
├── database.py          SQLite 관리
├── mcp_server.py        Claude Desktop MCP 서버
├── config.example.yaml  설정 템플릿
├── requirements.txt     패키지 목록
└── setup.sh             설치 스크립트
```
