"""
Hermes - 텔레그램 RAG 파이프라인 진입점
하루 한 번 수동 실행으로 밀린 메시지를 수집·처리
"""
import argparse
import asyncio
import logging
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

import yaml

from collector import TelegramCollector
from crawler import ArticleCrawler
from database import Database
from embedder import Embedder
from utils import KST

VALID_STEPS = {"collect", "crawl", "embed"}


def setup_logging(log_dir: str):
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(f"{log_dir}/hermes.log", encoding="utf-8"),
        ],
    )


def load_config(path: str = "config.yaml") -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        sys.exit(f"[오류] 설정 파일을 찾을 수 없습니다: {path}\nconfig.example.yaml을 복사해 config.yaml을 만들고 값을 채워주세요.")


async def sync_chromadb(db: Database, embedder: Embedder, crawler: ArticleCrawler, batch_size: int):
    """SQLite 기준으로 ChromaDB 누락분 재적재 (파이프라인 시작 시 호출)"""
    logger = logging.getLogger(__name__)

    # ── 기사 누락 체크 ──────────────────────────────────────────────────────
    try:
        result = embedder.col_articles.get(where={"chunk_index": 0}, include=["metadatas"])
        chroma_urls = {m["url"] for m in (result.get("metadatas") or [])}
    except Exception as e:
        logger.warning(f"ChromaDB 기사 목록 조회 실패, sync 스킵: {e}")
        chroma_urls = None

    if chroma_urls is not None:
        missing = db.get_articles_missing_from(chroma_urls)
        if missing:
            logger.warning(f"ChromaDB 누락 기사 {len(missing)}건 재적재 중...")
            chunks = [(a, crawler.chunk(a["text"])) for a in missing]
            embedder.add_article_chunks_bulk(chunks, batch_size=batch_size)
            logger.info(f"ChromaDB 기사 재적재 완료")

    # ── 요약 누락 체크 ──────────────────────────────────────────────────────
    try:
        result = embedder.col_summaries.get(include=["metadatas"])
        chroma_keys = {
            (m["room_link"], m["date"])
            for m in (result.get("metadatas") or [])
        }
    except Exception as e:
        logger.warning(f"ChromaDB 요약 목록 조회 실패, sync 스킵: {e}")
        chroma_keys = None

    if chroma_keys is not None:
        missing_summaries = db.get_summaries_missing_from(chroma_keys)
        if missing_summaries:
            logger.warning(f"ChromaDB 누락 요약 {len(missing_summaries)}건 재적재 중...")
            for s in missing_summaries:
                embedder.add_summary(s["room_link"], s["summary"], s["date"])
            logger.info(f"ChromaDB 요약 재적재 완료")


async def run_pipeline(
    config: dict,
    from_date: date | None = None,
    to_date: date | None = None,
    only: str | None = None,
):
    logger = logging.getLogger(__name__)
    settings = config.get("settings", {})
    data_dir = settings.get("data_dir", "data")

    db_path = f"{data_dir}/telegram.db"
    chroma_path = f"{data_dir}/chroma_db"
    today = datetime.now(KST).date().isoformat()

    db = Database(db_path)
    embedder = Embedder(config, chroma_path)
    crawler = ArticleCrawler(
        chunk_size=settings.get("chunk_size", 500),
        timeout=settings.get("crawl_timeout", 10),
    )
    max_crawl_fails = settings.get("max_crawl_fails", 3)
    embed_batch_size = settings.get("embed_batch_size", 100)

    run_collect = only in (None, "collect")
    run_crawl = only in (None, "crawl")
    run_embed = only in (None, "embed")

    # ── 0. ChromaDB ↔ SQLite 싱크 (--only 지정 시 스킵) ─────────────────────
    if only is None:
        await sync_chromadb(db, embedder, crawler, embed_batch_size)

    # ── 1. 텔레그램 메시지 수집 ──────────────────────────────────────────────
    if run_collect:
        collector = TelegramCollector(config, db)
        await collector.connect()
        effective_to = to_date or datetime.now(KST).date()
        if from_date:
            logger.info(f"날짜 지정 수집 모드: {from_date} ~ {effective_to}")
        try:
            all_messages = await collector.collect_all(from_date=from_date, to_date=to_date)
        finally:
            await collector.disconnect()
        logger.info(f"총 {len(all_messages)}개 메시지 수집 완료")
    else:
        all_messages = []
        logger.info("수집 단계 스킵 (--only 지정)")

    # ── 2. 모든 메시지 SQLite 저장 + 벡터 적재 ──────────────────────────────
    article_msgs = [m for m in all_messages if m["room_type"] == "article"]
    conv_msgs = [m for m in all_messages if m["room_type"] == "conversation"]
    new_msg_count = 0
    dup_msg_count = 0

    if run_collect and all_messages:
        new_msg_count = db.save_messages_bulk(all_messages)
        dup_msg_count = len(all_messages) - new_msg_count
        logger.info(
            f"메시지 DB 저장: 신규 {new_msg_count}개 / 중복 스킵 {dup_msg_count}개"
            f" (기사방 {len(article_msgs)}개 / 대화방 {len(conv_msgs)}개)"
        )
        if run_embed:
            embedder.add_messages_bulk(all_messages, batch_size=embed_batch_size)

        last_ids: dict[str, tuple[str | None, int]] = {}
        for msg in all_messages:
            room_link = msg["room_link"]
            if room_link not in last_ids or msg["message_id"] > last_ids[room_link][1]:
                last_ids[room_link] = (msg.get("room_title"), msg["message_id"])
        for room_link, (room_title, last_id) in last_ids.items():
            db.update_last_message_id(room_link, room_title, last_id)

    # ── 3. URL 크롤링 (모든 방, 병렬) ────────────────────────────────────────
    crawled = 0
    failed = 0
    skipped = 0
    text_articles: list[dict] = []
    fwd_articles: list[dict] = []

    if run_crawl and all_messages:
        concurrency = settings.get("crawl_concurrency", 10)
        semaphore = asyncio.Semaphore(concurrency)
        loop = asyncio.get_event_loop()

        async def fetch_one(url: str, msg: dict):
            async with semaphore:
                article, error = await loop.run_in_executor(None, crawler.fetch, url)
                return article, error, url, msg

        seen_urls = set()
        tasks = []
        for msg in all_messages:
            for url in msg.get("urls", []):
                if db.article_exists(url) or url in seen_urls:
                    skipped += 1
                    continue
                if db.get_crawl_fail_count(url) >= max_crawl_fails:
                    logger.debug(f"실패 {max_crawl_fails}회 초과 스킵: {url}")
                    skipped += 1
                    continue
                seen_urls.add(url)
                tasks.append(fetch_one(url, msg))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        successful_articles: list[dict] = []
        articles_chunks: list[tuple[dict, list[str]]] = []
        crawl_logs: list[tuple[str, bool, str | None]] = []

        for result in results:
            if isinstance(result, Exception):
                logger.warning(f"크롤링 예외: {result}")
                continue
            article, error, url, msg = result
            if article:
                article["message_id"] = msg["message_id"]
                article["room_link"] = msg["room_link"]
                article["room_title"] = msg.get("room_title")
                article["source_type"] = "crawled"
                chunks = crawler.chunk(article["text"])
                successful_articles.append(article)
                articles_chunks.append((article, chunks))
                crawl_logs.append((article["url"], True, None))
            else:
                crawl_logs.append((url, False, error))
                failed += 1

        saved = db.save_articles_bulk(successful_articles)
        db.save_crawl_logs_bulk(crawl_logs)
        if saved is not None and run_embed:
            embedder.add_article_chunks_bulk(articles_chunks, batch_size=embed_batch_size)
        elif saved is None:
            logger.warning("크롤링 기사 SQLite 저장 실패 → ChromaDB 적재 스킵")
        crawled = len(successful_articles)
        logger.info(f"기사 크롤링: {crawled}개 성공, {failed}개 실패, {skipped}개 스킵")

        def _collect_pseudo_articles(msgs: list[dict], *, forwarded_only: bool, source_type: str) -> tuple[list[dict], list[tuple[dict, list[str]]]]:
            """메시지 목록에서 pseudo_article 목록과 청크 쌍 목록을 생성한다."""
            articles: list[dict] = []
            chunks: list[tuple[dict, list[str]]] = []
            for msg in msgs:
                if forwarded_only and not msg.get("is_forwarded"):
                    continue
                if msg.get("urls"):
                    continue
                text = msg.get("text", "").strip()
                if len(text) < 100:
                    continue
                synthetic_url = f"msg://{msg['room_link']}/{msg['message_id']}"
                if db.article_exists(synthetic_url):
                    continue
                pseudo_article = {
                    "url": synthetic_url,
                    "title": "",
                    "text": text,
                    "authors": [],
                    "publish_date": msg.get("timestamp", "")[:10],
                    "message_id": msg["message_id"],
                    "room_link": msg["room_link"],
                    "room_title": msg.get("room_title"),
                    "source_type": source_type,
                }
                articles.append(pseudo_article)
                chunks.append((pseudo_article, crawler.chunk(text)))
            return articles, chunks

        # ── 4. 기사방 텍스트 메시지 청킹 (URL 없고 100자 이상, 포워딩 여부 무관) ─
        if article_msgs:
            text_articles, text_articles_chunks = _collect_pseudo_articles(
                article_msgs, forwarded_only=False, source_type="article_text"
            )
            saved = db.save_articles_bulk(text_articles)
            if saved is not None and run_embed:
                embedder.add_article_chunks_bulk(text_articles_chunks, batch_size=embed_batch_size)
            elif saved is None:
                logger.warning("기사방 텍스트 SQLite 저장 실패 → ChromaDB 적재 스킵")
            logger.info(f"기사방 텍스트 청킹: {len(text_articles)}개")

        # ── 5. 대화방 포워딩 메시지 청킹 (스크랩 텍스트) ────────────────────────
        if conv_msgs:
            fwd_articles, fwd_articles_chunks = _collect_pseudo_articles(
                conv_msgs, forwarded_only=True, source_type="forwarded_text"
            )
            saved = db.save_articles_bulk(fwd_articles)
            if saved is not None and run_embed:
                embedder.add_article_chunks_bulk(fwd_articles_chunks, batch_size=embed_batch_size)
            elif saved is None:
                logger.warning("대화방 스크랩 SQLite 저장 실패 → ChromaDB 적재 스킵")
            logger.info(f"대화방 스크랩 텍스트 청킹: {len(fwd_articles)}개")
    elif run_crawl:
        logger.info("크롤링 단계: 수집된 메시지 없음 (스킵)")

    # ── 최종 요약 리포트 ─────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info(f"[파이프라인 완료] {today}" + (f" (--only {only})" if only else ""))
    logger.info(f"  메시지 수집   : 총 {len(all_messages)}개 (신규 {new_msg_count}개 / 중복 {dup_msg_count}개)")
    logger.info(f"  URL 크롤링    : 성공 {crawled}개 / 실패 {failed}개 / 스킵 {skipped}개")
    logger.info(f"  텍스트 청킹   : 기사방 {len(text_articles)}개 / 대화방 스크랩 {len(fwd_articles)}개")
    logger.info("=" * 60)


def _parse_date(value: str) -> date:
    """YYYY-MM-DD 형식의 날짜 문자열을 date 객체로 변환. 형식 오류 시 한국어 메시지로 종료."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"날짜 형식이 올바르지 않습니다: '{value}'\n"
            "YYYY-MM-DD 형식으로 입력하세요. 예: --date 2024-01-15"
        )


def main():
    parser = argparse.ArgumentParser(description="Hermes 텔레그램 RAG 파이프라인")
    parser.add_argument(
        "--date",
        type=_parse_date,
        metavar="YYYY-MM-DD",
        help="이 날짜부터 수집 시작 (예: --date 2024-01-15). --to-date 없으면 오늘까지.",
    )
    parser.add_argument(
        "--to-date",
        type=_parse_date,
        metavar="YYYY-MM-DD",
        dest="to_date",
        help="수집 종료 날짜 (포함). --date와 같은 날 지정하면 당일만 수집.",
    )
    parser.add_argument(
        "--only",
        choices=sorted(VALID_STEPS),
        metavar="STEP",
        help="단일 단계만 실행. STEP: collect / crawl / embed",
    )
    args = parser.parse_args()

    config = load_config()
    settings = config.get("settings", {})
    setup_logging(settings.get("log_dir", "logs"))
    asyncio.run(
        run_pipeline(
            config,
            from_date=args.date,
            to_date=args.to_date,
            only=args.only,
        )
    )


if __name__ == "__main__":
    main()
