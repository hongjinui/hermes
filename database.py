"""
SQLite 데이터베이스 관리
원본 메시지, 기사, 요약, 동기화 상태 저장
"""
import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self):
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER NOT NULL,
                    room_link TEXT NOT NULL,
                    room_title TEXT,
                    room_type TEXT NOT NULL,
                    text TEXT NOT NULL,
                    sender_id INTEGER,
                    timestamp TEXT NOT NULL,
                    urls TEXT DEFAULT '[]',
                    is_forwarded INTEGER DEFAULT 0,
                    summarized INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now', '+9 hours')),
                    UNIQUE(message_id, room_link)
                );

                CREATE TABLE IF NOT EXISTS articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE NOT NULL,
                    title TEXT,
                    text TEXT NOT NULL,
                    authors TEXT DEFAULT '[]',
                    publish_date TEXT,
                    message_id INTEGER,
                    room_link TEXT,
                    room_title TEXT,
                    source_type TEXT DEFAULT 'crawled',
                    created_at TEXT DEFAULT (datetime('now', '+9 hours'))
                );

                CREATE TABLE IF NOT EXISTS summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_link TEXT NOT NULL,
                    room_title TEXT,
                    summary TEXT NOT NULL,
                    message_ids TEXT NOT NULL,
                    date TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now', '+9 hours'))
                );

                CREATE TABLE IF NOT EXISTS sync_state (
                    room_link TEXT PRIMARY KEY,
                    room_title TEXT,
                    last_message_id INTEGER DEFAULT 0,
                    last_sync_at TEXT
                );

                CREATE TABLE IF NOT EXISTS crawl_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    attempted_at TEXT DEFAULT (datetime('now', '+9 hours'))
                );

                CREATE INDEX IF NOT EXISTS idx_messages_room ON messages(room_link);
                CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);
                CREATE INDEX IF NOT EXISTS idx_articles_url ON articles(url);
                CREATE INDEX IF NOT EXISTS idx_crawl_log_url ON crawl_log(url);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_summaries_room_date ON summaries(room_link, date);
            """)
            # 마이그레이션: articles.source_type (기존 DB 호환)
            existing = {
                row[1]
                for row in conn.execute("PRAGMA table_info(articles)").fetchall()
            }
            if "source_type" not in existing:
                conn.execute(
                    "ALTER TABLE articles ADD COLUMN source_type TEXT DEFAULT 'crawled'"
                )

    # ── 메시지 ─────────────────────────────────────────────────────────────────

    def save_messages_bulk(self, msgs: list[dict]) -> int:
        """메시지 목록 일괄 저장. 저장된 건수 반환"""
        if not msgs:
            return 0
        try:
            with self._connect() as conn:
                cursor = conn.executemany(
                    """INSERT OR IGNORE INTO messages
                       (message_id, room_link, room_title, room_type, text, sender_id, timestamp, urls, is_forwarded)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        (
                            msg["message_id"],
                            msg["room_link"],
                            msg.get("room_title"),
                            msg["room_type"],
                            msg["text"],
                            msg.get("sender_id"),
                            msg["timestamp"],
                            json.dumps(msg.get("urls", []), ensure_ascii=False),
                            1 if msg.get("is_forwarded") else 0,
                        )
                        for msg in msgs
                    ],
                )
                return cursor.rowcount
        except Exception as e:
            logger.error(f"메시지 일괄 저장 실패: {e}")
            return 0

    def get_unsummarized_chat_messages(self, room_link: str, date: str) -> list[dict]:
        """특정 날짜의 포워딩 아닌 유저 대화 메시지 중 아직 요약 안 된 것"""
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """SELECT * FROM messages
                       WHERE room_link = ? AND timestamp LIKE ? AND is_forwarded = 0 AND summarized = 0
                       ORDER BY timestamp""",
                    (room_link, f"{date}%"),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"미요약 메시지 조회 실패 [{room_link}] {date}: {e}")
            return []

    def mark_messages_summarized(self, message_ids: list[int], room_link: str):
        """요약 완료된 메시지 표시"""
        if not message_ids:
            return
        try:
            with self._connect() as conn:
                conn.execute(
                    f"""UPDATE messages SET summarized = 1
                        WHERE room_link = ? AND message_id IN ({','.join('?' * len(message_ids))})""",
                    [room_link] + message_ids,
                )
        except Exception as e:
            logger.error(f"메시지 요약 표시 실패 [{room_link}]: {e}")

    # ── 기사 ─────────────────────────────────────────────────────────────────

    def save_articles_bulk(self, articles: list[dict]) -> Optional[int]:
        """기사 목록 일괄 저장. 저장 건수 반환, 예외 시 None 반환."""
        if not articles:
            return 0
        try:
            with self._connect() as conn:
                cursor = conn.executemany(
                    """INSERT OR IGNORE INTO articles
                       (url, title, text, authors, publish_date, message_id, room_link, room_title, source_type)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        (
                            a["url"],
                            a.get("title", ""),
                            a["text"],
                            json.dumps(a.get("authors", []), ensure_ascii=False),
                            a.get("publish_date"),
                            a.get("message_id"),
                            a.get("room_link"),
                            a.get("room_title"),
                            a.get("source_type", "crawled"),
                        )
                        for a in articles
                    ],
                )
                return cursor.rowcount
        except Exception as e:
            logger.error(f"기사 일괄 저장 실패: {e}")
            return None

    def save_crawl_logs_bulk(self, logs: list[tuple[str, bool, Optional[str]]]):
        """crawl_log 일괄 저장. logs: [(url, success, error_message), ...]"""
        if not logs:
            return
        try:
            with self._connect() as conn:
                conn.executemany(
                    """INSERT INTO crawl_log (url, status, error_message)
                       VALUES (?, ?, ?)""",
                    [(url, "success" if ok else "failed", err) for url, ok, err in logs],
                )
        except Exception as e:
            logger.error(f"crawl_log 일괄 저장 실패: {e}")

    def save_crawl_log(self, url: str, success: bool, error_message: Optional[str] = None):
        try:
            with self._connect() as conn:
                conn.execute(
                    """INSERT INTO crawl_log (url, status, error_message)
                       VALUES (?, ?, ?)""",
                    (url, "success" if success else "failed", error_message),
                )
        except Exception as e:
            logger.error(f"crawl_log 저장 실패 [{url}]: {e}")

    def get_crawl_fail_count(self, url: str) -> int:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM crawl_log WHERE url = ? AND status = 'failed'",
                    (url,),
                ).fetchone()
            return row[0] if row else 0
        except Exception as e:
            logger.error(f"crawl_fail_count 조회 실패 [{url}]: {e}")
            return 0

    def article_exists(self, url: str) -> bool:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT 1 FROM articles WHERE url = ?", (url,)
                ).fetchone()
            return row is not None
        except Exception as e:
            logger.error(f"article_exists 조회 실패 [{url}]: {e}")
            return False

    # ── 요약 ─────────────────────────────────────────────────────────────────

    def save_summary(self, room_link: str, room_title: str | None, summary: str, message_ids: list[int], date: str):
        try:
            with self._connect() as conn:
                conn.execute(
                    """INSERT INTO summaries (room_link, room_title, summary, message_ids, date)
                       VALUES (?, ?, ?, ?, ?)""",
                    (room_link, room_title, summary, json.dumps(message_ids), date),
                )
        except Exception as e:
            logger.error(f"요약 저장 실패 [{room_link}]: {e}")

    # ── ChromaDB 싱크 헬퍼 ───────────────────────────────────────────────────────

    def get_articles_missing_from(self, chroma_urls: set[str]) -> list[dict]:
        """SQLite에 있는데 chroma_urls에 없는 기사 반환"""
        try:
            with self._connect() as conn:
                rows = conn.execute("SELECT url FROM articles").fetchall()
            sqlite_urls = {r["url"] for r in rows}
            missing_urls = sqlite_urls - chroma_urls
            if not missing_urls:
                return []
            placeholders = ",".join("?" * len(missing_urls))
            with self._connect() as conn:
                rows = conn.execute(
                    f"SELECT * FROM articles WHERE url IN ({placeholders})",
                    list(missing_urls),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"누락 기사 조회 실패: {e}")
            return []

    def get_summaries_missing_from(self, chroma_keys: set[tuple[str, str]]) -> list[dict]:
        """SQLite에 있는데 chroma_keys에 없는 요약 반환 (room_link+date 기준, 최신 1건씩)"""
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """SELECT room_link, room_title, summary, date
                       FROM summaries
                       GROUP BY room_link, date
                       HAVING id = MAX(id)"""
                ).fetchall()
            summaries = [dict(r) for r in rows]
            return [
                s for s in summaries
                if (s["room_link"], s["date"]) not in chroma_keys
            ]
        except Exception as e:
            logger.error(f"누락 요약 조회 실패: {e}")
            return []

    # ── 동기화 상태 ────────────────────────────────────────────────────────────

    def get_last_message_id(self, room_link: str) -> int:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT last_message_id FROM sync_state WHERE room_link = ?",
                    (room_link,),
                ).fetchone()
            return row["last_message_id"] if row else 0
        except Exception as e:
            logger.error(f"last_message_id 조회 실패 [{room_link}]: {e}")
            return 0

    def get_last_sync_date(self, room_link: str):
        """마지막 동기화 날짜 반환 (date 객체). 없으면 None."""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT last_sync_at FROM sync_state WHERE room_link = ?",
                    (room_link,),
                ).fetchone()
            if row and row["last_sync_at"]:
                from datetime import datetime
                return datetime.fromisoformat(row["last_sync_at"]).date()
            return None
        except Exception as e:
            logger.error(f"last_sync_at 조회 실패 [{room_link}]: {e}")
            return None

    def list_rooms(self) -> list[dict]:
        """sync_state 전체 반환 (room_link, room_title, last_message_id, last_sync_at)"""
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT room_link, room_title, last_message_id, last_sync_at FROM sync_state ORDER BY room_link"
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"list_rooms 조회 실패: {e}")
            return []

    def get_summary(self, room_link: str, date: str) -> dict | None:
        """특정 방+날짜의 최신 요약 1건 반환"""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """SELECT room_link, room_title, summary, date, created_at
                       FROM summaries
                       WHERE room_link = ? AND date = ?
                       ORDER BY id DESC LIMIT 1""",
                    (room_link, date),
                ).fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"get_summary 조회 실패 [{room_link}] {date}: {e}")
            return None

    def update_last_message_id(self, room_link: str, room_title: str | None, message_id: int):
        try:
            with self._connect() as conn:
                conn.execute(
                    """INSERT INTO sync_state (room_link, room_title, last_message_id, last_sync_at)
                       VALUES (?, ?, ?, datetime('now', '+9 hours'))
                       ON CONFLICT(room_link) DO UPDATE SET
                           room_title = excluded.room_title,
                           last_message_id = MAX(last_message_id, excluded.last_message_id),
                           last_sync_at = excluded.last_sync_at""",
                    (room_link, room_title, message_id),
                )
        except Exception as e:
            logger.error(f"sync_state 업데이트 실패 [{room_link}]: {e}")
