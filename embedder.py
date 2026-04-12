"""
벡터 임베딩 + ChromaDB 적재 모듈
sentence-transformers 로컬 모델 사용
device 우선순위: config.yaml settings.device > cuda > mps > cpu
"""
import logging
from typing import Optional

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

logger = logging.getLogger(__name__)

COLLECTION_MESSAGES = "messages"
COLLECTION_ARTICLES = "articles"
COLLECTION_SUMMARIES = "summaries"

DEFAULT_MODEL = "paraphrase-multilingual-mpnet-base-v2"


def _resolve_device(config_device: str | None) -> str:
    """사용할 device 결정. config 명시 > cuda > mps > cpu 순으로 자동 감지."""
    if config_device:
        logger.info(f"임베딩 device: config 지정값 '{config_device}' 사용")
        return config_device

    try:
        import torch
        if torch.cuda.is_available():
            logger.info("임베딩 device: cuda 자동 감지")
            return "cuda"
        if torch.backends.mps.is_available():
            logger.info("임베딩 device: mps 자동 감지 (Apple Silicon)")
            return "mps"
    except ImportError:
        pass

    logger.info("임베딩 device: cpu 사용 (cuda/mps 없음)")
    return "cpu"


class Embedder:
    def __init__(self, config: dict, chroma_path: str):
        settings = config.get("settings", {})
        model_name = settings.get("embedding_model", DEFAULT_MODEL)
        device = _resolve_device(settings.get("device"))

        self.chroma = chromadb.PersistentClient(path=chroma_path)
        ef = SentenceTransformerEmbeddingFunction(
            model_name=model_name,
            device=device,
        )

        self.col_messages = self.chroma.get_or_create_collection(
            COLLECTION_MESSAGES, embedding_function=ef
        )
        self.col_articles = self.chroma.get_or_create_collection(
            COLLECTION_ARTICLES, embedding_function=ef
        )
        self.col_summaries = self.chroma.get_or_create_collection(
            COLLECTION_SUMMARIES, embedding_function=ef
        )

    # ── 메시지 ─────────────────────────────────────────────────────────────────

    def add_messages_bulk(self, msgs: list[dict], batch_size: int = 100):
        """메시지 목록을 batch_size씩 나눠 벡터 적재"""
        for i in range(0, len(msgs), batch_size):
            batch = msgs[i:i + batch_size]
            ids, docs, metas = [], [], []
            for msg in batch:
                ids.append(f"msg_{msg['room_link']}_{msg['message_id']}")
                docs.append(msg["text"])
                metas.append({
                    "room_link": msg["room_link"],
                    "room_type": msg["room_type"],
                    "timestamp": msg["timestamp"],
                    "message_id": str(msg["message_id"]),
                })
            try:
                self.col_messages.add(ids=ids, documents=docs, metadatas=metas)
            except Exception as e:
                if "already exists" not in str(e).lower():
                    logger.error(f"메시지 벡터 배치 적재 실패 [{i}~{i+len(batch)}]: {e}")

    # ── 기사 청크 ──────────────────────────────────────────────────────────────

    def add_article_chunks_bulk(self, articles_chunks: list[tuple[dict, list[str]]], batch_size: int = 100):
        """(article, chunks) 리스트를 받아 모든 청크를 batch_size씩 나눠 적재"""
        ids, docs, metas = [], [], []
        for article, chunks in articles_chunks:
            for i, chunk in enumerate(chunks):
                ids.append(f"article_{article['url']}_{i}")
                docs.append(chunk)
                metas.append({
                    "url": article["url"],
                    "title": article.get("title", ""),
                    "room_link": article.get("room_link", ""),
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "publish_date": article.get("publish_date") or "",
                })

        for i in range(0, len(ids), batch_size):
            try:
                self.col_articles.add(
                    ids=ids[i:i + batch_size],
                    documents=docs[i:i + batch_size],
                    metadatas=metas[i:i + batch_size],
                )
            except Exception as e:
                if "already exists" not in str(e).lower():
                    logger.error(f"기사 청크 배치 적재 실패 [{i}~{i+batch_size}]: {e}")

    # ── 요약 ─────────────────────────────────────────────────────────────────

    def add_summary(self, room_link: str, summary: str, date: str) -> bool:
        """결정적 ID(room_link+date)로 요약 벡터 적재. 성공 여부 반환."""
        doc_id = f"summary_{room_link}_{date}"
        try:
            self.col_summaries.add(
                ids=[doc_id],
                documents=[summary],
                metadatas=[{"room_link": room_link, "date": date}],
            )
            return True
        except Exception as e:
            if "already exists" in str(e).lower():
                return True  # 이미 있으면 성공으로 간주
            logger.error(f"요약 벡터 적재 실패 [{doc_id}]: {e}")
            return False

    # ── 검색 ─────────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        n_results: int = 10,
        where: Optional[dict] = None,
    ) -> dict:
        """모든 컬렉션에서 통합 검색"""
        empty = {"documents": [[]], "metadatas": [[]], "distances": [[]]}
        results = {}
        for name, col in [
            ("messages", self.col_messages),
            ("articles", self.col_articles),
            ("summaries", self.col_summaries),
        ]:
            try:
                count = col.count()
                if count == 0:
                    results[name] = empty
                    continue
                kwargs = dict(query_texts=[query], n_results=min(n_results, count))
                if where:
                    kwargs["where"] = where
                results[name] = col.query(**kwargs)
            except Exception as e:
                logger.error(f"검색 실패 [{name}]: {e}")
                results[name] = empty

        return results

    def search_collection(
        self,
        collection: str,
        query: str,
        n_results: int = 10,
        where: Optional[dict] = None,
    ) -> dict:
        """특정 컬렉션에서 검색"""
        col_map = {
            "messages": self.col_messages,
            "articles": self.col_articles,
            "summaries": self.col_summaries,
        }
        empty = {"documents": [[]], "metadatas": [[]], "distances": [[]]}
        col = col_map.get(collection)
        if not col:
            return empty

        try:
            count = col.count()
            if count == 0:
                return empty
            kwargs = dict(query_texts=[query], n_results=min(n_results, count))
            if where:
                kwargs["where"] = where
            return col.query(**kwargs)
        except Exception as e:
            logger.error(f"검색 실패 [{collection}]: {e}")
            return empty
