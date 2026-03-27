"""
대화 요약 모듈 (Claude API)
conversation 타입 채팅방의 메시지를 배치로 요약
"""
import logging

import anthropic

from utils import extract_claude_text

logger = logging.getLogger(__name__)

SUMMARY_PROMPT = """다음은 텔레그램 채팅방 '{room_link}'의 {date} 대화 내용입니다.
핵심 내용을 한국어로 간결하게 요약해주세요.

요약 형식:
- 주요 주제 2~5개를 bullet point로
- 각 항목은 1~2문장 이내
- 중복/잡담은 제외
- 중요한 정보(수치, 이름, 링크 등)는 유지

대화 내용:
{messages}"""


class Summarizer:
    def __init__(self, config: dict):
        self.client = anthropic.Anthropic(api_key=config["anthropic"]["api_key"])
        self.model = config.get("settings", {}).get(
            "claude_model", "claude-sonnet-4-6"
        )
        self.batch_size = config.get("settings", {}).get("summary_batch_size", 50)

    def summarize(self, room_link: str, messages: list[dict], target_date: str) -> tuple[str, list[int]]:
        """메시지 목록을 배치로 나눠 요약 후 병합.
        (summary, summarized_message_ids) 반환 — 실패한 배치의 메시지 ID는 포함하지 않음.
        """
        if not messages:
            return "", []

        batches = [
            messages[i : i + self.batch_size]
            for i in range(0, len(messages), self.batch_size)
        ]

        batch_summaries = []
        summarized_message_ids: list[int] = []
        for i, batch in enumerate(batches):
            logger.debug(f"[{room_link}] 배치 {i+1}/{len(batches)} 요약 중...")
            summary = self._summarize_batch(room_link, batch, target_date)
            if summary:
                batch_summaries.append(summary)
                summarized_message_ids.extend(m["message_id"] for m in batch)

        if not batch_summaries:
            return "", []
        if len(batch_summaries) == 1:
            return batch_summaries[0], summarized_message_ids
        merged = self._merge_summaries(room_link, batch_summaries, target_date)
        return merged, summarized_message_ids

    def _summarize_batch(
        self, room_link: str, messages: list[dict], target_date: str
    ) -> str:
        text_block = "\n".join(
            f"[{m['timestamp'][:16]}] {m['text']}" for m in messages
        )
        prompt = SUMMARY_PROMPT.format(
            room_link=room_link,
            date=target_date,
            messages=text_block,
        )
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            return extract_claude_text(response)
        except Exception as e:
            logger.error(f"요약 API 호출 실패: {e}")
            return ""

    def _merge_summaries(
        self, room_link: str, summaries: list[str], target_date: str
    ) -> str:
        combined = "\n\n---\n\n".join(summaries)
        prompt = f"""다음은 채팅방 '{room_link}'의 {target_date} 대화를 여러 배치로 나눠 요약한 내용입니다.
이를 하나의 일관된 요약으로 병합해주세요. 중복은 제거하고 핵심만 유지하세요.

{combined}"""
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            return extract_claude_text(response)
        except Exception as e:
            logger.error(f"요약 병합 실패: {e}")
            return "\n\n".join(summaries)
