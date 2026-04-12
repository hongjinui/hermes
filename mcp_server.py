"""
MCP 서버 - Claude Desktop 연동
ChromaDB에서 RAG 검색 후 답변 생성
"""
import json
import logging
import sys
from pathlib import Path

import anthropic
import yaml

from database import Database
from utils import extract_claude_text, first

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).parent))

from embedder import Embedder

logger = logging.getLogger(__name__)

# ── MCP 프로토콜 헬퍼 ────────────────────────────────────────────────────────


def send_response(response: dict):
    print(json.dumps(response, ensure_ascii=False), flush=True)


def read_request() -> dict | None:
    line = sys.stdin.readline()
    if not line:
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError as e:
        logger.error(f"JSON 파싱 실패: {e} | 원본: {line!r}")
        return {}


# ── 핵심 도구 함수 ────────────────────────────────────────────────────────────


def search_knowledge(embedder: Embedder, query: str, collection: str = "all", n: int = 10) -> str:
    """RAG 검색"""
    if collection == "all":
        results = embedder.search(query, n_results=n)
        parts = []
        for col_name, res in results.items():
            docs = first(res.get("documents", []), default=[])
            metas = first(res.get("metadatas", []), default=[])
            for doc, meta in zip(docs, metas):
                parts.append(f"[{col_name}] {meta}\n{doc}")
        return "\n\n".join(parts) if parts else "검색 결과 없음"
    else:
        res = embedder.search_collection(collection, query, n_results=n)
        docs = first(res.get("documents", []), default=[])
        metas = first(res.get("metadatas", []), default=[])
        parts = [f"{meta}\n{doc}" for doc, meta in zip(docs, metas)]
        return "\n\n".join(parts) if parts else "검색 결과 없음"


def answer_with_rag(
    embedder: Embedder,
    claude: anthropic.Anthropic,
    model: str,
    query: str,
    collection: str = "all",
) -> str:
    """검색 결과를 컨텍스트로 Claude 답변 생성"""
    context = search_knowledge(embedder, query, collection)

    prompt = f"""다음은 텔레그램 채팅방에서 수집된 관련 정보입니다:

{context}

위 정보를 바탕으로 다음 질문에 답변해주세요. 정보가 부족하면 솔직히 말씀해주세요.

질문: {query}"""

    response = claude.messages.create(
        model=model,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return extract_claude_text(response)


def tool_list_rooms(db: Database) -> str:
    """sync_state에서 수집된 방 목록 반환"""
    rooms = db.list_rooms()
    if not rooms:
        return "수집된 방이 없습니다."
    lines = []
    for r in rooms:
        name = r.get("room_title") or r["room_link"]
        lines.append(
            f"{name} ({r['room_link']})  마지막 메시지: {r['last_message_id']}  동기화: {r.get('last_sync_at', '-')}"
        )
    return "\n".join(lines)


def tool_get_summary(db: Database, room_link: str, date: str) -> str:
    """특정 방+날짜의 요약 반환"""
    row = db.get_summary(room_link, date)
    if row is None:
        return f"{room_link} / {date} 에 해당하는 요약이 없습니다."
    name = row.get("room_title") or room_link
    return f"[{name}] {row['date']}\n\n{row['summary']}"


# ── MCP 핸들러 ────────────────────────────────────────────────────────────────


TOOLS = [
    {
        "name": "search",
        "description": "텔레그램에서 수집한 메시지/기사/요약에서 키워드 검색",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "검색 키워드 또는 문장"},
                "collection": {
                    "type": "string",
                    "enum": ["all", "messages", "articles", "summaries"],
                    "description": "검색할 컬렉션 (기본값: all)",
                    "default": "all",
                },
                "n_results": {
                    "type": "integer",
                    "description": "반환할 결과 수 (기본값: 10)",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "ask",
        "description": "수집된 정보를 기반으로 질문에 답변 (RAG)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "질문"},
                "collection": {
                    "type": "string",
                    "enum": ["all", "messages", "articles", "summaries"],
                    "description": "검색 대상 컬렉션 (기본값: all)",
                    "default": "all",
                },
            },
            "required": ["question"],
        },
    },
    {
        "name": "list_rooms",
        "description": "수집된 텔레그램 방 목록과 마지막 동기화 정보를 반환",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_summary",
        "description": "특정 방과 날짜의 대화 요약을 반환",
        "inputSchema": {
            "type": "object",
            "properties": {
                "room_link": {"type": "string", "description": "텔레그램 방 링크 (예: some_channel)"},
                "date": {"type": "string", "description": "날짜 (YYYY-MM-DD 형식, 예: 2024-01-15)"},
            },
            "required": ["room_link", "date"],
        },
    },
]


def handle_request(request: dict, embedder: Embedder, db: Database, claude: anthropic.Anthropic, config: dict) -> dict:
    method = request.get("method")
    req_id = request.get("id")
    model = config.get("settings", {}).get("claude_model", "claude-sonnet-4-6")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "hermes", "version": "1.0.0"},
            },
        }

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        params = request.get("params") or {}
        tool_name = params.get("name", "")
        args = params.get("arguments", {})

        try:
            if tool_name == "search":
                result = search_knowledge(
                    embedder,
                    args["query"],
                    args.get("collection", "all"),
                    args.get("n_results", 10),
                )
            elif tool_name == "ask":
                result = answer_with_rag(
                    embedder, claude, model, args["question"], args.get("collection", "all")
                )
            elif tool_name == "list_rooms":
                result = tool_list_rooms(db)
            elif tool_name == "get_summary":
                result = tool_get_summary(db, args["room_link"], args["date"])
            else:
                result = f"알 수 없는 도구: {tool_name}"

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": result}]},
            }
        except Exception as e:
            logger.error(f"도구 실행 오류 [{tool_name}]: {e}")
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32603, "message": str(e)},
            }

    # notifications (응답 불필요)
    if method and method.startswith("notifications/"):
        return None

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"알 수 없는 메서드: {method}"},
    }


def main():
    _root = Path(__file__).parent
    (_root / "logs").mkdir(exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=[logging.FileHandler(str(_root / "logs" / "mcp_server.log"))],
    )

    config_path = _root / "config.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)

    data_dir = config.get("settings", {}).get("data_dir", "data")
    chroma_path = str(_root / data_dir / "chroma_db")
    db_path = str(_root / data_dir / "telegram.db")

    embedder = Embedder(config, chroma_path)
    db = Database(db_path)
    claude = anthropic.Anthropic(api_key=config["anthropic"]["api_key"])

    logger.info("Hermes MCP 서버 시작")

    while True:
        request = read_request()
        if request is None:
            break
        response = handle_request(request, embedder, db, claude, config)
        if response is not None:
            send_response(response)


if __name__ == "__main__":
    main()
