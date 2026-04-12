"""
공통 유틸리티 함수
"""
from datetime import timezone, timedelta
from typing import TypeVar

KST = timezone(timedelta(hours=9))

T = TypeVar("T")


def first(lst: list[T], default: T = None) -> T:
    """리스트가 비어있으면 default 반환, 아니면 첫 번째 요소 반환"""
    return lst[0] if lst else default


def extract_claude_text(response, default: str = "") -> str:
    """Claude API 응답에서 텍스트 추출. content가 비어있으면 default 반환"""
    if not response.content:
        return default
    block = first(response.content)
    return block.text.strip() if block and hasattr(block, "text") else default
