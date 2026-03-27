#!/bin/bash
set -e

echo "=== Hermes 설치 ==="

# 절대경로 감지
HERMES_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$HERMES_DIR/.venv/bin/python"
CLAUDE_CONFIG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"

# Python 버전 확인
python3 -c "import sys; assert sys.version_info >= (3,11), 'Python 3.11 이상 필요'" \
  || { echo "Python 3.11 이상이 필요합니다."; exit 1; }

# 가상환경 생성
if [ ! -d "$HERMES_DIR/.venv" ]; then
  echo "가상환경 생성 중..."
  python3 -m venv "$HERMES_DIR/.venv"
fi

# 패키지 설치
echo "패키지 설치 중..."
"$PYTHON" -m pip install --upgrade pip -q
"$PYTHON" -m pip install -r "$HERMES_DIR/requirements.txt" -q
"$PYTHON" -m pip install mcp-server-sqlite -q

# 디렉토리 생성
mkdir -p "$HERMES_DIR/data" "$HERMES_DIR/logs"

# config.yaml 복사
if [ ! -f "$HERMES_DIR/config.yaml" ]; then
  cp "$HERMES_DIR/config.example.yaml" "$HERMES_DIR/config.yaml"
  echo ""
  echo "config.yaml 이 생성되었습니다. 아래 항목을 채워주세요:"
  echo "  - telegram.api_id / api_hash / phone"
  echo "  - anthropic.api_key"
  echo "  - chatrooms 목록"
else
  echo "config.yaml 이 이미 존재합니다."
fi

# Claude Desktop MCP 설정
echo ""
echo "Claude Desktop MCP 설정 중..."
mkdir -p "$(dirname "$CLAUDE_CONFIG")"

cat > "$CLAUDE_CONFIG" << EOF
{
  "mcpServers": {
    "hermes": {
      "command": "$PYTHON",
      "args": ["$HERMES_DIR/mcp_server.py"]
    },
    "sqlite": {
      "command": "$PYTHON",
      "args": ["-m", "mcp_server_sqlite", "--db-path", "$HERMES_DIR/data/telegram.db"]
    }
  }
}
EOF

echo "Claude Desktop 설정 완료: $CLAUDE_CONFIG"

echo ""
echo "=== 설치 완료 ==="
echo ""
echo "다음 단계:"
echo "  1. config.yaml 에 API 키와 채팅방 링크 입력"
echo "  2. .venv/bin/python main.py  (메시지 수집)"
echo "  3. Claude Desktop 재시작"
