"""
텔레그램 메시지 수집 모듈 (Telethon MTProto)
마지막 동기화 포인트 이후 새 메시지만 수집
"""
import asyncio
import logging
from datetime import datetime

from telethon import TelegramClient
from telethon.tl.types import Message, MessageEntityUrl, MessageEntityTextUrl

from utils import KST

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

    async def collect_all(self, from_date=None, to_date=None) -> list[dict]:
        """모든 채팅방에서 새 메시지 수집. from_date/to_date(date 객체)로 수집 범위 지정."""
        all_messages = []
        for room in self.config["chatrooms"]:
            messages = await self.collect_room(room["link"], room["type"], from_date=from_date, to_date=to_date)
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

    async def collect_room(self, room_link: str, room_type: str, from_date=None, to_date=None) -> list[dict]:
        """단일 채팅방 메시지 수집.
        from_date/to_date(date 객체)로 수집 범위 지정 (min_id 필터 무시).
        실패 시 max_collect_retries 횟수만큼 재시도. 전부 실패하면 [] 반환 후 crawl_log 기록.
        """
        today = datetime.now(KST).date()

        if from_date is not None:
            # 날짜 지정 모드: min_id 필터 없이 해당 날짜부터 재수집
            collect_from = from_date
            last_id = 0
        else:
            last_id = self.db.get_last_message_id(room_link)
            # 마지막 동기화 날짜부터 수집 (없으면 오늘만)
            last_sync_date = self.db.get_last_sync_date(room_link)
            collect_from = last_sync_date if last_sync_date else today

        collect_until = to_date if to_date is not None else today
        collect_from_dt = datetime(collect_from.year, collect_from.month, collect_from.day, tzinfo=KST)

        for attempt in range(1, self.max_collect_retries + 1):
            messages = []

            try:
                entity_input = int(room_link) if room_link.lstrip("-").isdigit() else room_link
                entity = await self.client.get_entity(entity_input)
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
                    entity, min_id=last_id, reverse=True, offset_date=collect_from_dt
                ):
                    if not isinstance(msg, Message) or not msg.text:
                        continue
                    msg_date = msg.date.astimezone(KST).date()
                    if msg_date < collect_from:
                        continue
                    if msg_date > collect_until:
                        break
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
        """메시지에서 URL 추출. 스킵 대상(레이블, 도메인, 확장자)은 제외.

        MessageEntityUrl: 메시지 텍스트에 raw URL이 그대로 있는 경우.
                          offset/length로 텍스트를 슬라이싱해 URL을 얻는다.
                          슬라이싱 결과가 http(s)://로 시작하지 않으면 garbage로 간주해 버린다.
        MessageEntityTextUrl: [label](url) 마크다운 처리된 경우.
                              entity.url에 실제 URL이 있고, offset/length는 display text 범위.
                              텍스트를 슬라이싱하면 label(garbage)이 나오므로 반드시 entity.url 사용.
        """
        urls = []
        if not msg.entities:
            return urls

        for entity in msg.entities:
            if isinstance(entity, MessageEntityUrl):
                url = msg.text[entity.offset : entity.offset + entity.length]
                # 슬라이싱 결과가 유효한 URL이 아니면 garbage (마크다운 잔재 등)
                if not url.startswith(("http://", "https://")):
                    logger.debug(f"MessageEntityUrl garbage 스킵: {url!r}")
                    continue
                prefix = msg.text[max(0, entity.offset - 20) : entity.offset]
                if self._should_skip_url(url, prefix=prefix):
                    continue
                urls.append(url)
            elif isinstance(entity, MessageEntityTextUrl):
                # entity.url이 실제 링크. offset/length는 display text(label) 범위
                display = msg.text[entity.offset : entity.offset + entity.length]
                if self._should_skip_url(entity.url, display=display):
                    continue
                urls.append(entity.url)

        return urls
