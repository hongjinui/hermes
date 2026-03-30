"""
기사 크롤링 모듈 (newspaper3k)
URL에서 기사 본문을 추출하고 청킹
"""
import logging
import re
from typing import Optional

import newspaper
from newspaper import Article

logger = logging.getLogger(__name__)


class ArticleCrawler:
    def __init__(self, chunk_size: int = 500, timeout: int = 10):
        self.chunk_size = chunk_size
        self.timeout = timeout

    def fetch(self, url: str) -> tuple[Optional[dict], Optional[str]]:
        """URL에서 기사 본문 추출. (article, error_message) 반환"""
        try:
            article = Article(url, language="ko", request_timeout=self.timeout)
            article.download()
            article.parse()

            if not article.text or len(article.text.strip()) < 100:
                return None, "본문 없음 또는 너무 짧음"

            return {
                "url": url,
                "title": article.title or "",
                "text": article.text,
                "authors": article.authors,
                "publish_date": (
                    article.publish_date.isoformat() if article.publish_date else None
                ),
            }, None
        except Exception as e:
            logger.warning(f"크롤링 실패 [{url}]: {e}")
            return None, str(e)

    def chunk(self, text: str) -> list[str]:
        """텍스트를 chunk_size 기준으로 분할 (문장 경계 존중)"""
        sentences = re.split(r"(?<=[.!?。])\s+", text)
        chunks = []
        current = ""

        for sentence in sentences:
            if len(current) + len(sentence) <= self.chunk_size:
                current += sentence + " "
            else:
                if current.strip():
                    chunks.append(current.strip())
                # 단일 문장이 chunk_size 초과하는 경우 강제 분할
                if len(sentence) > self.chunk_size:
                    for i in range(0, len(sentence), self.chunk_size):
                        chunks.append(sentence[i : i + self.chunk_size])
                    current = ""
                else:
                    current = sentence + " "

        if current.strip():
            chunks.append(current.strip())

        return chunks
