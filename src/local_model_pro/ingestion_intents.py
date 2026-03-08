from __future__ import annotations

import re
from dataclasses import dataclass

_URL_PATTERN = re.compile(r"https?://[^\s<>'\"\])]+", re.IGNORECASE)
_SAVE_TRIGGER_PATTERN = re.compile(
    r"\b(?:save\s+(?:this|that|it)?\s*for\s+later|save\s+for\s+later|remember\s+this\s+for\s+later|store\s+this\s+for\s+later)\b",
    re.IGNORECASE,
)
_AUTHOR_PATTERN = re.compile(
    r"\b(?:you\s+are\s+the\s+author|author)\s*[:\-]?\s*([A-Za-z][A-Za-z0-9 .'-]{1,79})",
    re.IGNORECASE,
)
_REVIEW_VERB_PATTERN = re.compile(
    r"\b(?:review|analy[sz]e|summari[sz]e|audit|inspect|check)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PromptIngestionIntent:
    save_requested: bool
    save_text: str
    author: str | None
    review_requested: bool
    review_urls: list[str]


def _normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _extract_author(text: str) -> str | None:
    match = _AUTHOR_PATTERN.search(text)
    if not match:
        return None
    author = _normalize_spaces(match.group(1))
    if not author:
        return None
    author = author.rstrip(".,;:")
    return author or None


def _extract_save_text(text: str) -> str:
    stripped = _SAVE_TRIGGER_PATTERN.sub("", text, count=1)
    stripped = _AUTHOR_PATTERN.sub("", stripped, count=1)
    stripped = _normalize_spaces(stripped).strip(" ,.;:-")
    if stripped:
        return stripped
    return _normalize_spaces(text)


def _extract_urls(text: str, *, max_urls: int) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for match in _URL_PATTERN.finditer(text):
        url = match.group(0).rstrip(".,;:)")
        canonical = url.lower()
        if canonical in seen:
            continue
        seen.add(canonical)
        urls.append(url)
        if len(urls) >= max_urls:
            break
    return urls


def parse_prompt_ingestion_intent(prompt: str, *, max_urls: int = 3) -> PromptIngestionIntent:
    text = _normalize_spaces(prompt)
    save_requested = bool(_SAVE_TRIGGER_PATTERN.search(text))
    author = _extract_author(text) if save_requested else None
    save_text = _extract_save_text(text) if save_requested else ""

    review_urls = _extract_urls(text, max_urls=max(1, max_urls))
    review_requested = bool(_REVIEW_VERB_PATTERN.search(text)) and bool(review_urls)

    return PromptIngestionIntent(
        save_requested=save_requested,
        save_text=save_text,
        author=author,
        review_requested=review_requested,
        review_urls=review_urls,
    )
