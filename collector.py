"""
텔레그램 메시지 수집 모듈 (Telethon MTProto)
마지막 동기화 포인트 이후 새 메시지만 수집
"""
import asyncio
import logging
from datetime import timezone, timedelta

KST = timezone(timedelta(hours=9))

from telethon import TelegramClient
from telethon.tl.types import Message, MessageEntityUrl, MessageEntityTextUrl

logger = logging.getLogger(__name__)

# URL 앞 레이블이 이 패턴에 해당하면 크롤링 스킵
URL_SKIP_LABELS = ["회사정보", "기업정보"]

# 크롤링 의미 없는 도메인 (영상, 미디어 등)
URL_SKIP_DOMAINS = {
    "youtube.com", "youtu.be", "m.youtube.com",
}

# 크롤링 의미 없는 파일 확장자
URL_SKIP_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
    ".mp4", ".mov", ".avi", ".mkv", ".webm",
    ".pdf", ".zip", ".rar",
}


class TelegramCollector:
    def __init__(self, config: dict, db):
        self.config = config
        self.db = db
        try:
            api_id = int(config["telegram"]["api_id"])
        except (KeyError, ValueError, TypeError) as e:
            raise ValueError(f"config.yaml의 telegram.api_id가 올바르지 않습니다: {e}")
        self.client = TelegramClient(
            "hermes_session",
            api_id,
            config["telegram"]["api_hash"],
        )
        self.max_collect_retries = int(config.get("settings", {}).get("max_collect_retries", 3))

    async def connect(self):
        try:
            await self.client.start(phone=self.config["telegram"]["phone"])
            logger.info("텔레그램 연결 완료")
        except Exception as e:
            raise RuntimeError(f"텔레그램 인증 실패: {e}") from e

    async def disconnect(self):
        await self.client.disconnect()

    async def collect_all(self) -> list[dict]:
        """모든 채팅방에서 새 메시지 수집"""
        all_messages = []
        for room in self.config["chatrooms"]:
            messages = await self.collect_room(room["link"], room["type"])
            all_messages.extend(messages)

            if messages:
                first_ts = messages[0]["timestamp"][:16]
                last_ts = messages[-1]["timestamp"][:16]
                title = messages[0].get("room_title") or room["link"]
                url_count = sum(1 for m in messages if m.get("urls"))
                fwd_count = sum(1 for m in messages if m.get("is_forwarded"))
                logger.info(
                    f"[{title}] 수집: {len(messages)}개"
                    f" | 날짜: {first_ts} ~ {last_ts}"
                    f" | URL포함: {url_count}개 / 포워딩: {fwd_count}개"
                )
            else:
                logger.info(f"[{room['link']}] 수집: 0개")
        return all_messages

    async def collect_room(self, room_link: str, room_type: str) -> list[dict]:
        """단일 채팅방 메시지 수집 (마지막 동기화 이후).
        실패 시 max_collect_retries 횟수만큼 재시도. 전부 실패하면 [] 반환 후 crawl_log 기록.
        """
        last_id = self.db.get_last_message_id(room_link)

        for attempt in range(1, self.max_collect_retries + 1):
            messages = []

            try:
                entity = await self.client.get_entity(room_link)
            except Exception as e:
                logger.warning(f"채팅방 접근 실패 [{room_link}] ({attempt}/{self.max_collect_retries}): {e}")
                if attempt < self.max_collect_retries:
                    await asyncio.sleep(2 ** attempt)
                    continue
                logger.error(f"채팅방 접근 최대 재시도 초과, 스킵 [{room_link}]")
                self.db.save_crawl_log(room_link, False, str(e))
                return []

            room_title = getattr(entity, "title", None) or getattr(entity, "first_name", room_link)

            try:
                async for msg in self.client.iter_messages(
                    entity, min_id=last_id, reverse=True
                ):
                    if not isinstance(msg, Message) or not msg.text:
                        continue
                    urls = self._extract_urls(msg)
                    messages.append({
                        "message_id": msg.id,
                        "room_link": room_link,
                        "room_title": room_title,
                        "room_type": room_type,
                        "text": msg.text,
                        "sender_id": msg.sender_id,
                        "timestamp": msg.date.astimezone(KST).isoformat(),
                        "urls": urls,
                        "is_forwarded": msg.fwd_from is not None,
                    })
                return messages  # 정상 완료
            except Exception as e:
                logger.warning(f"메시지 수집 중단 [{room_link}] ({attempt}/{self.max_collect_retries}): {e}")
                if attempt < self.max_collect_retries:
                    await asyncio.sleep(2 ** attempt)
                    continue
                logger.error(f"메시지 수집 최대 재시도 초과, 스킵 [{room_link}]")
                self.db.save_crawl_log(room_link, False, str(e))
                return []

        return []

    def _should_skip_url(self, url: str, prefix: str = "", display: str = "") -> bool:
        """스킵 대상 URL 여부 확인"""
        from urllib.parse import urlparse
        from pathlib import PurePosixPath
        parsed = urlparse(url)
        domain = parsed.netloc.lstrip("www.")
        ext = PurePosixPath(parsed.path).suffix.lower()
        return (
            any(label in prefix or label in display for label in URL_SKIP_LABELS)
            or domain in URL_SKIP_DOMAINS
            or ext in URL_SKIP_EXTENSIONS
        )

    def _extract_urls(self, msg: Message) -> list[str]:
        """메시지에서 URL 추출. 스킵 대상(레이블, 도메인, 확장자)은 제외."""
        urls = []
        if not msg.entities:
            return urls

        for entity in msg.entities:
            if isinstance(entity, MessageEntityUrl):
                prefix = msg.text[max(0, entity.offset - 20) : entity.offset]
                url = msg.text[entity.offset : entity.offset + entity.length]
                if self._should_skip_url(url, prefix=prefix):
                    continue
                urls.append(url)
            elif isinstance(entity, MessageEntityTextUrl):
                display = msg.text[entity.offset : entity.offset + entity.length]
                if self._should_skip_url(entity.url, display=display):
                    continue
                urls.append(entity.url)

        return urls
