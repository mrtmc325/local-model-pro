from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from local_model_pro.config import Settings
from local_model_pro.conversation_store import ConversationStore
from local_model_pro.ollama_client import OllamaClient, OllamaStreamError
from local_model_pro.qdrant_memory import MemoryResult, QdrantError, QdrantMemoryIndex
from local_model_pro.url_review import ReviewedPage, URLReviewClient, URLReviewError

_SQL_PATTERN = re.compile(r"\b(select|insert|update|delete|from|where|join|drop|table|into|values)\b", re.IGNORECASE)
_WORD_PATTERN = re.compile(r"[A-Za-z0-9']+")
_CAPITALIZED_PATTERN = re.compile(r"\b[A-Z][a-zA-Z]{2,}\b")
_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_PATTERN = re.compile(r"\b(?:\+?\d{1,2}[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}\b")
_NEGATION_PATTERN = re.compile(r"\b(no|not|never|none|without|isn't|aren't|wasn't|weren't)\b", re.IGNORECASE)
_NUMERIC_PATTERN = re.compile(r"\b\d[\d,./:-]*\b")
_YEAR_PATTERN = re.compile(r"\b(?:19|20)\d{2}\b")
_RELATIVE_THIS_YEAR_PATTERN = re.compile(
    r"\b(this year|current year|year to date|ytd|so far this year)\b",
    re.IGNORECASE,
)
_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "our",
    "so",
    "that",
    "the",
    "their",
    "them",
    "they",
    "this",
    "to",
    "us",
    "was",
    "we",
    "what",
    "when",
    "where",
    "who",
    "why",
    "with",
    "you",
    "your",
}
_FORUM_HINTS = {"reddit.com", "quora.com", "stackexchange.com", "forum", "community"}
_SOCIAL_HINTS = {"facebook.com", "x.com", "twitter.com", "instagram.com", "linkedin.com", "tiktok.com"}
_OFFICIAL_HINTS = {".gov", ".edu", "fema.gov", "ready.gov", "weather.gov", "who.int", "cdc.gov"}
_MEDIA_HINTS = {
    "nytimes.com",
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "cnn.com",
    "theguardian.com",
}
_META_MEMORY_NOISE_HINTS = {
    "for accurate details",
    "best to refer to recent news",
    "check recent news sources",
    "official statements",
    "no specific information available",
    "lacks supporting evidence",
}
_RECENCY_HINTS = {
    "this year",
    "current year",
    "year to date",
    "ytd",
    "today",
    "this month",
    "this week",
    "latest",
    "recent",
}


@dataclass(frozen=True)
class QueryPlan:
    reason: str
    meaning: str
    purpose: str
    db_query: str
    web_query: str
    fallback: bool = False


@dataclass(frozen=True)
class EvidenceCard:
    evidence_id: str
    source_type: str
    actor_scope: str
    label: str
    content: str
    url: str | None
    source_session: str | None
    confidence: float
    pii_flag: bool
    used_verbatim: bool


@dataclass(frozen=True)
class GroundedClaim:
    claim_id: str
    text: str
    evidence_ids: list[str]
    confidence: float
    status: str


@dataclass(frozen=True)
class GroundedResponse:
    status: str
    answer_text: str
    claims: list[GroundedClaim]
    overall_confidence: float
    clarify_question: str
    note: str
    reasoning_text: str = ""
    debug_text: str = ""


@dataclass(frozen=True)
class SavedMemoryEvent:
    artifact_id: str
    file_path: str
    indexed_count: int
    note: str
    summary: str
    author: str | None


@dataclass(frozen=True)
class URLReviewSavedItem:
    url: str
    status: str
    raw_file: str | None
    meaning_file: str | None
    artifact_id: str | None
    indexed_count: int
    error: str | None
    final_url: str | None = None
    title: str | None = None
    meaning: str | None = None
    key_facts: list[str] | None = None
    domain: str | None = None
    source_type: str | None = None
    reviewed_chars: int | None = None


class RecursivePlanner:
    def __init__(
        self,
        *,
        settings: Settings,
        ollama: OllamaClient,
    ) -> None:
        self._settings = settings
        self._ollama = ollama

    @staticmethod
    def _extract_json_object(raw_text: str) -> dict[str, Any] | None:
        cleaned = raw_text.strip()
        if not cleaned:
            return None
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            return None
        candidate = match.group(0)
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _normalize_string(value: Any) -> str:
        if not isinstance(value, str):
            return ""
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _sanitize_lookup_query(
        candidate: str,
        *,
        prompt: str,
        meaning: str,
        purpose: str,
    ) -> str:
        normalized = re.sub(r"\s+", " ", candidate).strip()
        if not normalized:
            normalized = prompt.strip()

        if _SQL_PATTERN.search(normalized) or ";" in normalized:
            fallback = f"{meaning} {purpose}".strip()
            normalized = fallback or prompt.strip()

        if len(normalized) < 6:
            normalized = prompt.strip()

        if len(normalized) > 280:
            normalized = f"{normalized[:277]}..."
        return normalized

    @staticmethod
    def _normalize_relative_time_references(prompt: str, candidate: str) -> str:
        prompt_text = (prompt or "").strip().lower()
        query_text = (candidate or "").strip()
        if not query_text:
            return query_text

        current_year = str(datetime.now(timezone.utc).year)
        if _RELATIVE_THIS_YEAR_PATTERN.search(prompt_text):
            if _YEAR_PATTERN.search(query_text):
                query_text = _YEAR_PATTERN.sub(current_year, query_text)
            elif current_year not in query_text:
                query_text = f"{query_text} {current_year}"

        if "today" in prompt_text and "today" not in query_text.lower():
            query_text = f"{query_text} today"

        return re.sub(r"\s+", " ", query_text).strip()

    def _fallback(self, prompt: str) -> QueryPlan:
        text = prompt.strip()
        return QueryPlan(
            reason="User needs accurate and actionable help for a current request.",
            meaning=text,
            purpose="Provide a useful response backed by reliable context.",
            db_query=text,
            web_query=text,
            fallback=True,
        )

    async def _run_pass(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any] | None:
        try:
            raw = await self._ollama.chat(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                num_ctx=max(1024, min(self._settings.default_num_ctx, 4096)),
            )
        except OllamaStreamError:
            return None
        return self._extract_json_object(raw)

    async def build_plan(
        self,
        *,
        prompt: str,
        history: list[dict[str, str]],
        model: str,
    ) -> QueryPlan:
        base = self._fallback(prompt)
        passes = max(0, self._settings.knowledge_recursion_passes)
        if passes == 0:
            return base

        planner_model = self._settings.knowledge_planner_model or model
        recent_lines = []
        for item in history[-6:]:
            role = item.get("role", "").strip().lower()
            content = item.get("content", "").strip()
            if role in {"user", "assistant"} and content:
                recent_lines.append(f"{role}: {content}")
        history_text = "\n".join(recent_lines) if recent_lines else "(none)"

        pass1 = await self._run_pass(
            model=planner_model,
            system_prompt=(
                "You break down user intent for retrieval planning.\n"
                "Return JSON only with keys: reason, meaning, purpose.\n"
                "Use plain concise text."
            ),
            user_prompt=(
                f"Prompt: {prompt}\n"
                f"Recent history:\n{history_text}\n"
            ),
        )
        if not pass1:
            return base

        reason = self._normalize_string(pass1.get("reason")) or base.reason
        meaning = self._normalize_string(pass1.get("meaning")) or base.meaning
        purpose = self._normalize_string(pass1.get("purpose")) or base.purpose
        if passes == 1:
            return QueryPlan(
                reason=reason,
                meaning=meaning,
                purpose=purpose,
                db_query=prompt,
                web_query=prompt,
                fallback=False,
            )

        pass2 = await self._run_pass(
            model=planner_model,
            system_prompt=(
                "You convert intent into retrieval queries.\n"
                "Return JSON only with keys: db_query, web_query.\n"
                "Use natural language only. Do not output SQL or code.\n"
                "db_query should be semantic and context-rich.\n"
                "web_query should be internet-search friendly and concise."
            ),
            user_prompt=(
                f"Original prompt: {prompt}\n"
                f"Reason: {reason}\n"
                f"Meaning: {meaning}\n"
                f"Purpose: {purpose}\n"
            ),
        )
        if not pass2:
            return QueryPlan(
                reason=reason,
                meaning=meaning,
                purpose=purpose,
                db_query=prompt,
                web_query=prompt,
                fallback=False,
            )

        db_query = self._sanitize_lookup_query(
            self._normalize_string(pass2.get("db_query")) or prompt,
            prompt=prompt,
            meaning=meaning,
            purpose=purpose,
        )
        db_query = self._normalize_relative_time_references(prompt, db_query)
        web_query = self._sanitize_lookup_query(
            self._normalize_string(pass2.get("web_query")) or prompt,
            prompt=prompt,
            meaning=meaning,
            purpose=purpose,
        )
        web_query = self._normalize_relative_time_references(prompt, web_query)
        if passes == 2:
            return QueryPlan(
                reason=reason,
                meaning=meaning,
                purpose=purpose,
                db_query=db_query,
                web_query=web_query,
                fallback=False,
            )

        now_label = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
        pass3 = await self._run_pass(
            model=planner_model,
            system_prompt=(
                "You refine retrieval planning.\n"
                "Return JSON only with keys: reason, meaning, purpose, db_query, web_query.\n"
                "Use natural language only. Do not output SQL or code.\n"
                "Adjust phrasing for the current date/time context."
            ),
            user_prompt=(
                f"UTC now: {now_label}\n"
                f"Original prompt: {prompt}\n"
                f"Current reason: {reason}\n"
                f"Current meaning: {meaning}\n"
                f"Current purpose: {purpose}\n"
                f"Current db_query: {db_query}\n"
                f"Current web_query: {web_query}\n"
            ),
        )
        if not pass3:
            return QueryPlan(
                reason=reason,
                meaning=meaning,
                purpose=purpose,
                db_query=db_query,
                web_query=web_query,
                fallback=False,
            )

        final_reason = self._normalize_string(pass3.get("reason")) or reason
        final_meaning = self._normalize_string(pass3.get("meaning")) or meaning
        final_purpose = self._normalize_string(pass3.get("purpose")) or purpose

        return QueryPlan(
            reason=final_reason,
            meaning=final_meaning,
            purpose=final_purpose,
            db_query=self._normalize_relative_time_references(
                prompt,
                self._sanitize_lookup_query(
                    self._normalize_string(pass3.get("db_query")) or db_query,
                    prompt=prompt,
                    meaning=final_meaning,
                    purpose=final_purpose,
                ),
            ),
            web_query=self._normalize_relative_time_references(
                prompt,
                self._sanitize_lookup_query(
                    self._normalize_string(pass3.get("web_query")) or web_query,
                    prompt=prompt,
                    meaning=final_meaning,
                    purpose=final_purpose,
                ),
            ),
            fallback=False,
        )


class KnowledgeAssistService:
    def __init__(
        self,
        *,
        settings: Settings,
        ollama: OllamaClient,
        store: ConversationStore,
        memory_index: QdrantMemoryIndex,
    ) -> None:
        self._settings = settings
        self._ollama = ollama
        self._store = store
        self._memory_index = memory_index
        self._planner = RecursivePlanner(settings=settings, ollama=ollama)
        self._url_review_client = URLReviewClient(
            timeout_seconds=settings.url_review_timeout_seconds,
            max_bytes=settings.url_review_max_bytes,
        )

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [token.lower() for token in _WORD_PATTERN.findall(text)]

    @staticmethod
    def _source_scope(*, item_actor_id: str, session_id: str, actor_id: str, current_session_id: str) -> str:
        if session_id == current_session_id:
            return "same_session"
        if item_actor_id == actor_id:
            return "same_user"
        return "shared"

    @staticmethod
    def _scope_priority(scope: str) -> int:
        if scope == "same_session":
            return 0
        if scope == "same_user":
            return 1
        return 2

    @staticmethod
    def _detect_pii(content: str) -> bool:
        lowered = content.lower()
        romantic_keywords = {
            "girlfriend",
            "boyfriend",
            "wife",
            "husband",
            "fiance",
            "fiancee",
            "my girl",
            "my guy",
            "romantic",
            "dating",
        }
        if _EMAIL_PATTERN.search(content) or _PHONE_PATTERN.search(content):
            return True
        return any(keyword in lowered for keyword in romantic_keywords)

    @staticmethod
    def _allow_cross_user_for_content(content: str) -> bool:
        return not KnowledgeAssistService._detect_pii(content)

    @staticmethod
    def domain_for_url(url: str) -> str:
        parsed = urlparse(url)
        host = parsed.netloc.lower().strip().rstrip(".")
        if host.startswith("www."):
            host = host[4:]
        return host

    @staticmethod
    def classify_source_type_for_url(url: str) -> str:
        host = KnowledgeAssistService.domain_for_url(url)

        if any(token in host for token in _FORUM_HINTS):
            return "web_user_story_forum"
        if any(token in host for token in _SOCIAL_HINTS):
            return "web_user_story_forum"
        if any(host.endswith(token) or token in host for token in _OFFICIAL_HINTS):
            return "web_official"
        if any(token in host for token in _MEDIA_HINTS):
            return "web_media"
        return "web_media"

    @staticmethod
    def source_confidence(source_type: str, base_score: float = 0.65) -> float:
        if source_type == "manual_save":
            return min(0.93, max(0.62, base_score + 0.10))
        if source_type == "web_review":
            return min(0.86, max(0.50, base_score + 0.06))
        if source_type == "memory_same_session":
            return min(0.90, max(0.60, base_score + 0.08))
        if source_type == "memory_same_user":
            return min(0.88, max(0.56, base_score + 0.08))
        if source_type == "memory_shared":
            return min(0.84, max(0.46, base_score + 0.04))
        if source_type == "web_official":
            return min(0.90, max(0.58, base_score + 0.12))
        if source_type == "web_media":
            return min(0.82, max(0.48, base_score + 0.04))
        if source_type == "web_user_story_forum":
            return min(0.70, max(0.35, base_score - 0.10))
        return min(0.75, max(0.40, base_score))

    @staticmethod
    def _term_overlap_score(text: str, terms: list[str]) -> float:
        if not terms:
            return 0.0
        lower_text = text.lower()
        hits = sum(1 for term in terms if term in lower_text)
        return hits / max(1, len(terms))

    @staticmethod
    def _extract_terms(text: str, *, max_terms: int = 16) -> list[str]:
        terms: list[str] = []
        seen: set[str] = set()
        for token in [item.lower() for item in _WORD_PATTERN.findall(text)]:
            if len(token) < 2:
                continue
            if token in _STOP_WORDS:
                continue
            if token in seen:
                continue
            seen.add(token)
            terms.append(token)
            if len(terms) >= max_terms:
                break
        return terms

    @staticmethod
    def _short_phrases(terms: list[str], *, max_phrases: int = 8) -> list[str]:
        phrases: list[str] = []
        for size in (2, 3):
            for idx in range(0, len(terms) - size + 1):
                phrases.append(" ".join(terms[idx : idx + size]))
                if len(phrases) >= max_phrases:
                    return phrases
        return phrases

    def _expand_memory_queries(
        self,
        *,
        query: str,
        query_plan: QueryPlan | None,
    ) -> list[str]:
        candidates: list[str] = [query.strip()]
        if query_plan:
            candidates.extend(
                [
                    query_plan.db_query.strip(),
                    query_plan.meaning.strip(),
                    query_plan.purpose.strip(),
                    query_plan.reason.strip(),
                    f"{query_plan.meaning.strip()} {query_plan.purpose.strip()}".strip(),
                ]
            )

        terms = self._extract_terms(" ".join(candidates), max_terms=24)
        if terms:
            candidates.append(" ".join(terms[:8]))
            candidates.extend(self._short_phrases(terms, max_phrases=12))

        named_entities = []
        for candidate in candidates:
            for match in _CAPITALIZED_PATTERN.findall(candidate):
                if match.lower() in _STOP_WORDS:
                    continue
                named_entities.append(match)
        if named_entities:
            candidates.append(" ".join(named_entities[:5]))

        normalized: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            text = re.sub(r"\s+", " ", candidate).strip()
            if len(text) < 3:
                continue
            lowered = text.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            normalized.append(text)
            if len(normalized) >= 16:
                break
        return normalized

    async def save_session(
        self,
        *,
        session_id: str,
        model: str,
        system_prompt: str | None,
        actor_id: str,
    ) -> None:
        await asyncio.to_thread(
            self._store.upsert_session,
            session_id=session_id,
            model=model,
            system_prompt=system_prompt,
            actor_id=actor_id,
        )

    async def save_turn(
        self,
        *,
        session_id: str,
        speaker: str,
        content: str,
        request_id: str | None,
        model: str | None,
        actor_id: str,
    ) -> int:
        pii_flag = self._detect_pii(content)
        allow_cross_user = self._allow_cross_user_for_content(content)
        return await asyncio.to_thread(
            self._store.append_turn,
            session_id=session_id,
            speaker=speaker,
            content=content,
            request_id=request_id,
            model=model,
            actor_id=actor_id,
            pii_flag=pii_flag,
            allow_cross_user=allow_cross_user,
        )

    @staticmethod
    def _slug(value: str, *, fallback: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
        cleaned = cleaned.strip("._-")
        return cleaned[:80] or fallback

    def _actor_export_dir(self, actor_id: str) -> Path:
        base = Path(self._settings.memory_export_dir).expanduser().resolve()
        actor_slug = self._slug(actor_id or "anonymous", fallback="anonymous")
        target = base / actor_slug
        target.mkdir(parents=True, exist_ok=True)
        return target

    @staticmethod
    def _content_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _build_metadata_header(metadata: dict[str, str | None], *, content_hash: str) -> str:
        lines = ["---"]
        for key, value in metadata.items():
            safe_value = (value or "").replace("\n", " ").strip()
            lines.append(f"{key}: {safe_value}")
        lines.append(f"content_sha256: {content_hash}")
        lines.append("---")
        return "\n".join(lines)

    def _write_artifact_file(
        self,
        *,
        actor_id: str,
        prefix: str,
        extension: str,
        metadata: dict[str, str | None],
        body: str,
    ) -> tuple[str, str]:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        nonce = uuid.uuid4().hex[:8]
        file_name = f"{prefix}_{timestamp}_{nonce}.{extension.lstrip('.')}"
        target_dir = self._actor_export_dir(actor_id)
        final_path = target_dir / file_name
        content_hash = self._content_hash(body)
        header = self._build_metadata_header(metadata, content_hash=content_hash)
        payload = f"{header}\n\n{body.rstrip()}\n"

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(target_dir),
            prefix=".tmp_",
            suffix=".part",
            delete=False,
        ) as tmp:
            tmp.write(payload)
            tmp.flush()
            os.fsync(tmp.fileno())
            temp_path = tmp.name

        os.replace(temp_path, final_path)
        return str(final_path), content_hash

    async def _add_memory_artifact(
        self,
        *,
        artifact_id: str,
        session_id: str,
        actor_id: str,
        request_id: str | None,
        artifact_type: str,
        source_url: str | None,
        author: str | None,
        summary: str | None,
        file_path: str,
        content_hash: str,
    ) -> None:
        await asyncio.to_thread(
            self._store.add_memory_artifact,
            artifact_id=artifact_id,
            session_id=session_id,
            actor_id=actor_id,
            request_id=request_id,
            artifact_type=artifact_type,
            source_url=source_url,
            author=author,
            summary=summary,
            file_path=file_path,
            content_hash=content_hash,
        )

    async def _load_turns_for_snapshot(self, *, session_id: str) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self._store.list_turns,
            session_id=session_id,
            limit=max(1, self._settings.direct_save_max_turns),
        )

    @staticmethod
    def _format_session_snapshot(turns: list[dict[str, Any]]) -> str:
        lines: list[str] = ["# Session Snapshot", ""]
        if not turns:
            lines.append("No turns available.")
            return "\n".join(lines)

        for row in turns:
            speaker = str(row.get("speaker", "unknown")).strip() or "unknown"
            created_at = str(row.get("created_at", "")).strip()
            content = str(row.get("content", "")).strip()
            if not content:
                continue
            header = f"## [{speaker}] {created_at}" if created_at else f"## [{speaker}]"
            lines.append(header)
            lines.append(content)
            lines.append("")
        return "\n".join(lines).strip()

    @staticmethod
    def _fallback_summary_from_snapshot(snapshot_text: str, save_text: str) -> tuple[str, list[str]]:
        fallback_line = save_text.strip() or "Saved conversation context for future retrieval."
        compact = re.sub(r"\s+", " ", snapshot_text).strip()
        if len(compact) > 260:
            compact = compact[:257] + "..."
        meaning = f"{fallback_line} Context: {compact}" if compact else fallback_line
        return meaning, [fallback_line]

    @staticmethod
    def _extract_json_array(raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []
        out: list[str] = []
        seen: set[str] = set()
        for item in raw:
            text = re.sub(r"\s+", " ", str(item)).strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            if len(text) > 240:
                text = text[:237] + "..."
            out.append(text)
            if len(out) >= 6:
                break
        return out

    async def _summarize_direct_save(
        self,
        *,
        save_text: str,
        snapshot_text: str,
        model: str,
    ) -> tuple[str, list[str]]:
        try:
            raw = await self._ollama.chat(
                model=self._settings.knowledge_insight_model or model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Summarize a saved conversation snapshot for memory indexing.\n"
                            "Return JSON only with keys: meaning, key_facts.\n"
                            "key_facts must be a JSON array of short strings."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Save request: {save_text}\n\n"
                            f"Snapshot:\n{snapshot_text[:12000]}"
                        ),
                    },
                ],
                temperature=0.0,
                num_ctx=max(2048, min(self._settings.default_num_ctx, 6144)),
            )
        except OllamaStreamError:
            return self._fallback_summary_from_snapshot(snapshot_text, save_text)

        payload = RecursivePlanner._extract_json_object(raw)
        if not payload:
            return self._fallback_summary_from_snapshot(snapshot_text, save_text)

        meaning = re.sub(r"\s+", " ", str(payload.get("meaning", ""))).strip()
        key_facts = self._extract_json_array(payload.get("key_facts"))
        if not meaning:
            meaning, fallback_facts = self._fallback_summary_from_snapshot(snapshot_text, save_text)
            if not key_facts:
                key_facts = fallback_facts
        return meaning, key_facts

    async def _index_custom_insights(
        self,
        *,
        session_id: str,
        actor_id: str,
        model: str,
        source_type: str,
        insights: list[str],
        quote_text: str,
    ) -> int:
        count = 0
        pii_flag = self._detect_pii(quote_text)
        allow_cross_user = self._allow_cross_user_for_content(quote_text)
        for insight in insights:
            clean = re.sub(r"\s+", " ", insight).strip()
            if not clean:
                continue
            insight_id = str(uuid.uuid4())
            try:
                await asyncio.to_thread(
                    self._store.add_insight,
                    session_id=session_id,
                    speaker="me",
                    insight=clean,
                    insight_id=insight_id,
                    actor_id=actor_id,
                    pii_flag=pii_flag,
                    allow_cross_user=allow_cross_user,
                    source_type=source_type,
                    quote_text=quote_text[:240],
                )
                vector = await self._ollama.embed(
                    model=self._settings.embedding_model,
                    text=clean,
                )
                await self._memory_index.upsert(
                    point_id=insight_id,
                    vector=vector,
                    payload={
                        "insight_id": insight_id,
                        "insight": clean,
                        "source_session": session_id,
                        "speaker": "me",
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "actor_id": actor_id,
                        "pii_flag": pii_flag,
                        "allow_cross_user": allow_cross_user,
                        "source_type": source_type,
                        "quote_text": quote_text[:240],
                    },
                )
                count += 1
            except (OllamaStreamError, QdrantError, ValueError):
                continue
        return count

    async def save_direct_memory(
        self,
        *,
        session_id: str,
        actor_id: str,
        request_id: str,
        model: str,
        save_text: str,
        author: str | None,
    ) -> SavedMemoryEvent:
        turns = await self._load_turns_for_snapshot(session_id=session_id)
        snapshot_text = self._format_session_snapshot(turns)
        meaning, key_facts = await self._summarize_direct_save(
            save_text=save_text,
            snapshot_text=snapshot_text,
            model=model,
        )

        file_path, content_hash = self._write_artifact_file(
            actor_id=actor_id,
            prefix="session_snapshot",
            extension="md",
            metadata={
                "artifact_type": "session_snapshot",
                "session_id": session_id,
                "actor_id": actor_id,
                "request_id": request_id,
                "author": author,
                "source_url": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            body=snapshot_text,
        )

        artifact_id = str(uuid.uuid4())
        await self._add_memory_artifact(
            artifact_id=artifact_id,
            session_id=session_id,
            actor_id=actor_id,
            request_id=request_id,
            artifact_type="session_snapshot",
            source_url=None,
            author=author,
            summary=meaning[:500],
            file_path=file_path,
            content_hash=content_hash,
        )

        insights = [meaning]
        insights.extend(key_facts)
        if save_text.strip():
            insights.append(save_text.strip())
        indexed_count = await self._index_custom_insights(
            session_id=session_id,
            actor_id=actor_id,
            model=model,
            source_type="manual_save",
            insights=insights,
            quote_text=save_text.strip() or meaning,
        )
        note = "Session snapshot saved and indexed."
        if indexed_count == 0:
            note = "Session snapshot saved, but indexing yielded no records."

        return SavedMemoryEvent(
            artifact_id=artifact_id,
            file_path=file_path,
            indexed_count=indexed_count,
            note=note,
            summary=meaning,
            author=author,
        )

    @staticmethod
    def _fallback_page_meaning(page: ReviewedPage) -> tuple[str, list[str]]:
        text = re.sub(r"\s+", " ", page.text).strip()
        if len(text) > 700:
            text = text[:697] + "..."
        meaning = f"{page.title}: {text}" if text else page.title
        facts: list[str] = []
        for line in page.text.splitlines():
            clean = re.sub(r"\s+", " ", line).strip()
            if len(clean) < 20:
                continue
            facts.append(clean[:220])
            if len(facts) >= 4:
                break
        if not facts and meaning:
            facts.append(meaning[:220])
        return meaning, facts

    @staticmethod
    def _clean_review_line(value: str, *, max_chars: int) -> str:
        cleaned = re.sub(r"\s+", " ", value).strip()
        if not cleaned:
            return ""
        noise_phrases = (
            "cookie policy",
            "privacy policy",
            "terms of service",
            "sign in",
            "log in",
            "subscribe",
            "newsletter",
            "all rights reserved",
        )
        lowered = cleaned.lower()
        if any(phrase in lowered for phrase in noise_phrases):
            return ""
        if len(cleaned) > max_chars:
            cleaned = cleaned[: max_chars - 3].rstrip() + "..."
        return cleaned

    def _normalize_review_summary(
        self,
        *,
        page: ReviewedPage,
        meaning: str,
        key_facts: list[str],
    ) -> tuple[str, list[str]]:
        meaning_limit = max(180, int(self._settings.web_review_meaning_max_chars))
        clean_meaning = self._clean_review_line(meaning, max_chars=meaning_limit)
        if not clean_meaning:
            fallback_meaning, fallback_facts = self._fallback_page_meaning(page)
            clean_meaning = self._clean_review_line(fallback_meaning, max_chars=meaning_limit)
            key_facts = key_facts or fallback_facts

        fact_limit = min(240, max(80, meaning_limit // 3))
        normalized_facts: list[str] = []
        seen: set[str] = set()
        for fact in key_facts:
            clean_fact = self._clean_review_line(str(fact), max_chars=fact_limit)
            if not clean_fact:
                continue
            key = clean_fact.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized_facts.append(clean_fact)
            if len(normalized_facts) >= 5:
                break

        if not normalized_facts and clean_meaning:
            normalized_facts = [self._clean_review_line(clean_meaning, max_chars=fact_limit)]

        return clean_meaning, [item for item in normalized_facts if item]

    async def _summarize_reviewed_page(
        self,
        *,
        page: ReviewedPage,
        model: str,
    ) -> tuple[str, list[str]]:
        try:
            raw = await self._ollama.chat(
                model=self._settings.knowledge_insight_model or model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Summarize reviewed web page content for memory retrieval.\n"
                            "Return JSON only with keys: meaning, key_facts.\n"
                            "key_facts must be concise factual bullets."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"URL: {page.final_url}\n"
                            f"Title: {page.title}\n"
                            f"Content:\n{page.text[:12000]}"
                        ),
                    },
                ],
                temperature=0.0,
                num_ctx=max(2048, min(self._settings.default_num_ctx, 6144)),
            )
        except OllamaStreamError:
            fallback_meaning, fallback_facts = self._fallback_page_meaning(page)
            return self._normalize_review_summary(
                page=page,
                meaning=fallback_meaning,
                key_facts=fallback_facts,
            )

        payload = RecursivePlanner._extract_json_object(raw)
        if not payload:
            fallback_meaning, fallback_facts = self._fallback_page_meaning(page)
            return self._normalize_review_summary(
                page=page,
                meaning=fallback_meaning,
                key_facts=fallback_facts,
            )

        meaning = re.sub(r"\s+", " ", str(payload.get("meaning", ""))).strip()
        key_facts = self._extract_json_array(payload.get("key_facts"))
        if not meaning:
            meaning, fallback_facts = self._fallback_page_meaning(page)
            if not key_facts:
                key_facts = fallback_facts
        return self._normalize_review_summary(
            page=page,
            meaning=meaning,
            key_facts=key_facts,
        )

    async def review_and_save_urls(
        self,
        *,
        session_id: str,
        actor_id: str,
        request_id: str,
        model: str,
        urls: list[str],
        author: str | None = None,
        start_index: int = 1,
    ) -> tuple[list[URLReviewSavedItem], list[EvidenceCard]]:
        items: list[URLReviewSavedItem] = []
        evidence_cards: list[EvidenceCard] = []
        next_label = max(1, start_index)
        for raw_url in urls[: max(1, self._settings.url_review_max_urls)]:
            source_type = self.classify_source_type_for_url(raw_url)
            domain = self.domain_for_url(raw_url)
            try:
                page = await self._url_review_client.fetch(url=raw_url)
                try:
                    meaning, key_facts = await asyncio.wait_for(
                        self._summarize_reviewed_page(page=page, model=model),
                        timeout=max(4, self._settings.url_review_timeout_seconds),
                    )
                except (asyncio.TimeoutError, OllamaStreamError):
                    fallback_meaning, fallback_facts = self._fallback_page_meaning(page)
                    meaning, key_facts = self._normalize_review_summary(
                        page=page,
                        meaning=fallback_meaning,
                        key_facts=fallback_facts,
                    )
                source_type = self.classify_source_type_for_url(page.final_url)
                domain = self.domain_for_url(page.final_url)
                reviewed_chars = len(page.text)

                raw_file, raw_hash = self._write_artifact_file(
                    actor_id=actor_id,
                    prefix="url_raw",
                    extension="txt",
                    metadata={
                        "artifact_type": "url_raw",
                        "session_id": session_id,
                        "actor_id": actor_id,
                        "request_id": request_id,
                        "author": author,
                        "source_url": page.final_url,
                        "created_at": page.fetched_at,
                    },
                    body=page.text,
                )

                meaning_body_lines = [f"# {page.title}", "", f"URL: {page.final_url}", "", "## Meaning", meaning, ""]
                if key_facts:
                    meaning_body_lines.append("## Key Facts")
                    for fact in key_facts:
                        meaning_body_lines.append(f"- {fact}")
                    meaning_body_lines.append("")
                meaning_body = "\n".join(meaning_body_lines).rstrip() + "\n"
                meaning_file, meaning_hash = self._write_artifact_file(
                    actor_id=actor_id,
                    prefix="url_meaning",
                    extension="md",
                    metadata={
                        "artifact_type": "url_meaning",
                        "session_id": session_id,
                        "actor_id": actor_id,
                        "request_id": request_id,
                        "author": author,
                        "source_url": page.final_url,
                        "created_at": page.fetched_at,
                    },
                    body=meaning_body,
                )

                raw_artifact_id = str(uuid.uuid4())
                await self._add_memory_artifact(
                    artifact_id=raw_artifact_id,
                    session_id=session_id,
                    actor_id=actor_id,
                    request_id=request_id,
                    artifact_type="url_raw",
                    source_url=page.final_url,
                    author=author,
                    summary=page.title[:240],
                    file_path=raw_file,
                    content_hash=raw_hash,
                )
                meaning_artifact_id = str(uuid.uuid4())
                await self._add_memory_artifact(
                    artifact_id=meaning_artifact_id,
                    session_id=session_id,
                    actor_id=actor_id,
                    request_id=request_id,
                    artifact_type="url_meaning",
                    source_url=page.final_url,
                    author=author,
                    summary=meaning[:500],
                    file_path=meaning_file,
                    content_hash=meaning_hash,
                )

                insights = [f"{page.title}: {meaning}"]
                insights.extend(key_facts)
                indexed_count = await self._index_custom_insights(
                    session_id=session_id,
                    actor_id=actor_id,
                    model=model,
                    source_type="web_review",
                    insights=insights,
                    quote_text=f"{page.title} {meaning}",
                )

                source_type = "web_review"
                label = f"E{next_label}"
                next_label += 1
                content_bits = [page.title, meaning]
                for fact in key_facts[:4]:
                    content_bits.append(f"fact: {fact}")
                evidence_cards.append(
                    EvidenceCard(
                        evidence_id=f"web-review:{uuid.uuid4().hex[:8]}",
                        source_type=source_type,
                        actor_scope="web",
                        label=label,
                        content="\n".join(content_bits),
                        url=page.final_url,
                        source_session=None,
                        confidence=self.source_confidence("web_review", base_score=0.72),
                        pii_flag=False,
                        used_verbatim=False,
                    )
                )

                items.append(
                    URLReviewSavedItem(
                        url=raw_url,
                        status="saved",
                        raw_file=raw_file,
                        meaning_file=meaning_file,
                        artifact_id=meaning_artifact_id,
                        indexed_count=indexed_count,
                        error=None,
                        final_url=page.final_url,
                        title=page.title,
                        meaning=meaning,
                        key_facts=key_facts,
                        domain=domain,
                        source_type=source_type,
                        reviewed_chars=reviewed_chars,
                    )
                )
            except Exception as exc:
                items.append(
                    URLReviewSavedItem(
                        url=raw_url,
                        status="failed",
                        raw_file=None,
                        meaning_file=None,
                        artifact_id=None,
                        indexed_count=0,
                        error=str(exc),
                        domain=domain,
                        source_type=source_type,
                    )
                )
        return items, evidence_cards

    async def review_web_results_for_context(
        self,
        *,
        model: str,
        web_results: list[dict[str, Any]],
        max_urls: int | None = None,
        start_index: int = 1,
    ) -> tuple[list[URLReviewSavedItem], list[EvidenceCard]]:
        """
        Fetch and summarize top web-search URLs for same-turn context/evidence only.
        This path intentionally does not write artifacts or index memory.
        """
        items: list[URLReviewSavedItem] = []
        evidence_cards: list[EvidenceCard] = []
        next_label = max(1, start_index)

        limit = max(
            1,
            int(
                max_urls
                if max_urls is not None
                else self._settings.web_assist_page_review_max_urls
            ),
        )
        candidates: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for row in web_results:
            url = str(row.get("url", "")).strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            candidates.append(row)
            if len(candidates) >= limit:
                break

        for row in candidates:
            raw_url = str(row.get("url", "")).strip()
            if not raw_url:
                continue
            source_type = str(row.get("source_type", "")).strip() or self.classify_source_type_for_url(raw_url)
            domain = self.domain_for_url(raw_url)
            try:
                page = await self._url_review_client.fetch(url=raw_url)
                source_type = self.classify_source_type_for_url(page.final_url)
                domain = self.domain_for_url(page.final_url)
                # Keep web-assist scraping resilient: if summarization stalls/fails,
                # fall back to deterministic extraction from fetched page text.
                try:
                    meaning, key_facts = await asyncio.wait_for(
                        self._summarize_reviewed_page(page=page, model=model),
                        timeout=max(4, self._settings.url_review_timeout_seconds),
                    )
                except (asyncio.TimeoutError, OllamaStreamError):
                    fallback_meaning, fallback_facts = self._fallback_page_meaning(page)
                    meaning, key_facts = self._normalize_review_summary(
                        page=page,
                        meaning=fallback_meaning,
                        key_facts=fallback_facts,
                    )
                content_bits = [page.title, meaning]
                for fact in key_facts[:4]:
                    content_bits.append(f"fact: {fact}")
                evidence_cards.append(
                    EvidenceCard(
                        evidence_id=f"web-review:{uuid.uuid4().hex[:8]}",
                        source_type="web_review",
                        actor_scope="web",
                        label=f"E{next_label}",
                        content="\n".join(content_bits),
                        url=page.final_url,
                        source_session=None,
                        confidence=self.source_confidence("web_review", base_score=0.74),
                        pii_flag=False,
                        used_verbatim=False,
                    )
                )
                next_label += 1
                items.append(
                    URLReviewSavedItem(
                        url=raw_url,
                        status="saved",
                        raw_file=None,
                        meaning_file=None,
                        artifact_id=None,
                        indexed_count=0,
                        error=None,
                        final_url=page.final_url,
                        title=page.title,
                        meaning=meaning,
                        key_facts=key_facts,
                        domain=domain,
                        source_type=source_type,
                        reviewed_chars=len(page.text),
                    )
                )
            except Exception as exc:
                items.append(
                    URLReviewSavedItem(
                        url=raw_url,
                        status="failed",
                        raw_file=None,
                        meaning_file=None,
                        artifact_id=None,
                        indexed_count=0,
                        error=str(exc),
                        domain=domain,
                        source_type=source_type,
                    )
                )
        return items, evidence_cards

    async def build_query_plan(
        self,
        *,
        prompt: str,
        history: list[dict[str, str]],
        model: str,
    ) -> QueryPlan:
        return await self._planner.build_plan(
            prompt=prompt,
            history=history,
            model=model,
        )

    async def _derive_insights(
        self,
        *,
        speaker: str,
        content: str,
        model: str,
    ) -> list[str]:
        if not content.strip():
            return []

        insight_model = self._settings.knowledge_insight_model or model
        try:
            raw = await self._ollama.chat(
                model=insight_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Convert one chat turn into reusable abstract insights.\n"
                            "Return JSON only: {\"insights\": [\"...\", \"...\"]}.\n"
                            "Rules:\n"
                            "- Keep named entities when they matter for retrieval quality.\n"
                            "- No secrets, tokens, credentials, or contact details.\n"
                            "- Avoid exact long verbatim copy."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Speaker: {speaker}\nTurn:\n{content}",
                    },
                ],
                temperature=0.0,
                num_ctx=max(1024, min(self._settings.default_num_ctx, 4096)),
            )
        except OllamaStreamError:
            return []

        parsed = RecursivePlanner._extract_json_object(raw)
        if not parsed:
            return []
        raw_insights = parsed.get("insights", [])
        if not isinstance(raw_insights, list):
            return []

        seen: set[str] = set()
        clean: list[str] = []
        for item in raw_insights:
            text = str(item).strip()
            if not text:
                continue
            if len(text) > 360:
                text = f"{text[:357]}..."
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            clean.append(text)
            if len(clean) >= 4:
                break
        return clean

    @staticmethod
    def _fallback_insight_from_turn(content: str) -> str:
        flattened = re.sub(r"\s+", " ", content).strip()
        if not flattened:
            return "Prior discussion contained relevant context."
        if len(flattened) > 160:
            flattened = flattened[:157] + "..."
        return f"Prior conversation context: {flattened}"

    async def index_turn_insights(
        self,
        *,
        session_id: str,
        speaker: str,
        content: str,
        model: str,
        actor_id: str,
    ) -> None:
        pii_flag = self._detect_pii(content)
        allow_cross_user = self._allow_cross_user_for_content(content)
        quote_text = re.sub(r"\s+", " ", content).strip()
        if len(quote_text) > 240:
            quote_text = quote_text[:237] + "..."

        insights = await self._derive_insights(
            speaker=speaker,
            content=content,
            model=model,
        )
        if not insights:
            insights = [self._fallback_insight_from_turn(content)]

        for insight in insights:
            insight_id = str(uuid.uuid4())
            try:
                await asyncio.to_thread(
                    self._store.add_insight,
                    session_id=session_id,
                    speaker=speaker,
                    insight=insight,
                    insight_id=insight_id,
                    actor_id=actor_id,
                    pii_flag=pii_flag,
                    allow_cross_user=allow_cross_user,
                    source_type="insight",
                    quote_text=quote_text,
                )
                vector = await self._ollama.embed(
                    model=self._settings.embedding_model,
                    text=insight,
                )
                await self._memory_index.upsert(
                    point_id=insight_id,
                    vector=vector,
                    payload={
                        "insight_id": insight_id,
                        "insight": insight,
                        "source_session": session_id,
                        "speaker": speaker,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "actor_id": actor_id,
                        "pii_flag": pii_flag,
                        "allow_cross_user": allow_cross_user,
                        "source_type": "insight",
                        "quote_text": quote_text,
                    },
                )
            except (OllamaStreamError, QdrantError, ValueError):
                continue

    def _memory_key(self, item: MemoryResult) -> str:
        return f"{item.evidence_id}::{item.source_session}::{item.speaker}"

    def _scope_filter(self, *, item_actor_id: str, pii_flag: bool, allow_cross_user: bool, actor_id: str) -> bool:
        if item_actor_id == actor_id:
            return True
        if pii_flag:
            return False
        return bool(allow_cross_user)

    @staticmethod
    def _is_meta_memory_noise(item: MemoryResult) -> bool:
        text = f"{item.insight} {item.quote_text or ''}".lower()
        return any(phrase in text for phrase in _META_MEMORY_NOISE_HINTS)

    @staticmethod
    def _query_has_recency_intent(query: str, query_plan: QueryPlan | None = None) -> bool:
        combined = " ".join(
            part.strip().lower()
            for part in [
                query or "",
                query_plan.db_query if query_plan else "",
                query_plan.web_query if query_plan else "",
                query_plan.meaning if query_plan else "",
                query_plan.purpose if query_plan else "",
            ]
            if part
        )
        return any(hint in combined for hint in _RECENCY_HINTS)

    def _apply_memory_quality_adjustment(
        self,
        *,
        candidate: MemoryResult,
        score: float,
        recency_intent: bool,
    ) -> float:
        adjusted = score
        if self._is_meta_memory_noise(candidate):
            adjusted -= 0.18
            if candidate.source_type == "insight":
                adjusted -= 0.06
            if recency_intent:
                adjusted -= 0.08
        return max(0.0, min(1.0, adjusted))

    @staticmethod
    def _insight_dedupe_key(item: MemoryResult) -> str:
        return re.sub(r"\s+", " ", item.insight).strip().lower()

    async def search_memory(
        self,
        *,
        query: str,
        actor_id: str,
        current_session_id: str,
        query_plan: QueryPlan | None = None,
    ) -> list[MemoryResult]:
        normalized = query.strip()
        if not normalized:
            return []

        recency_intent = self._query_has_recency_intent(normalized, query_plan)
        expanded_queries = self._expand_memory_queries(query=normalized, query_plan=query_plan)
        terms = self._extract_terms(" ".join(expanded_queries), max_terms=28)
        results_map: dict[str, MemoryResult] = {}

        for variant in expanded_queries:
            try:
                vector = await self._ollama.embed(
                    model=self._settings.embedding_model,
                    text=variant,
                )
                semantic_results = await self._memory_index.search(
                    vector=vector,
                    limit=max(self._settings.knowledge_memory_top_k * 3, 8),
                    score_threshold=max(0.0, self._settings.knowledge_memory_score_threshold - 0.1),
                )
            except (OllamaStreamError, QdrantError):
                semantic_results = []

            for item in semantic_results:
                if not self._scope_filter(
                    item_actor_id=item.actor_id,
                    pii_flag=item.pii_flag,
                    allow_cross_user=item.allow_cross_user,
                    actor_id=actor_id,
                ):
                    continue
                rerank = self._term_overlap_score(f"{item.insight} {item.quote_text or ''}", terms)
                combined_score = max(item.score, min(1.0, (item.score * 0.65) + (rerank * 0.35)))
                candidate = MemoryResult(
                    evidence_id=item.evidence_id,
                    insight=item.insight,
                    score=self._apply_memory_quality_adjustment(
                        candidate=item,
                        score=combined_score,
                        recency_intent=recency_intent,
                    ),
                    source_session=item.source_session,
                    speaker=item.speaker,
                    created_at=item.created_at,
                    actor_id=item.actor_id,
                    pii_flag=item.pii_flag,
                    allow_cross_user=item.allow_cross_user,
                    source_type=item.source_type,
                    quote_text=item.quote_text,
                )
                key = self._memory_key(candidate)
                existing = results_map.get(key)
                if existing is None or candidate.score > existing.score:
                    results_map[key] = candidate

        lexical_insights = await asyncio.to_thread(
            self._store.search_insights_by_terms,
            terms=terms,
            actor_id=actor_id,
            current_session_id=current_session_id,
            include_shared=True,
            limit=max(self._settings.knowledge_memory_top_k * 4, 12),
        )
        for insight in lexical_insights:
            overlap = self._term_overlap_score(f"{insight.insight} {insight.quote_text or ''}", terms)
            score = min(0.25 + overlap * 0.55, 0.90)
            base_candidate = MemoryResult(
                evidence_id=insight.insight_id,
                insight=insight.insight,
                score=score,
                source_session=insight.session_id,
                speaker=insight.speaker,
                created_at=insight.created_at,
                actor_id=insight.actor_id,
                pii_flag=insight.pii_flag,
                allow_cross_user=insight.allow_cross_user,
                source_type=insight.source_type,
                quote_text=insight.quote_text,
            )
            candidate = MemoryResult(
                evidence_id=insight.insight_id,
                insight=insight.insight,
                score=self._apply_memory_quality_adjustment(
                    candidate=base_candidate,
                    score=score,
                    recency_intent=recency_intent,
                ),
                source_session=insight.session_id,
                speaker=insight.speaker,
                created_at=insight.created_at,
                actor_id=insight.actor_id,
                pii_flag=insight.pii_flag,
                allow_cross_user=insight.allow_cross_user,
                source_type=insight.source_type,
                quote_text=insight.quote_text,
            )
            key = self._memory_key(candidate)
            existing = results_map.get(key)
            if existing is None or candidate.score > existing.score:
                results_map[key] = candidate

        if len(results_map) < self._settings.knowledge_memory_top_k:
            turn_hits = await asyncio.to_thread(
                self._store.search_turns_by_terms,
                terms=terms,
                actor_id=actor_id,
                current_session_id=current_session_id,
                include_shared=True,
                limit=max(self._settings.knowledge_memory_top_k * 3, 10),
            )
            for turn in turn_hits:
                overlap = self._term_overlap_score(turn.content, terms)
                excerpt = re.sub(r"\s+", " ", turn.content).strip()
                if len(excerpt) > 220:
                    excerpt = excerpt[:217] + "..."
                candidate = MemoryResult(
                    evidence_id=f"turn:{turn.turn_id}",
                    insight=self._fallback_insight_from_turn(turn.content),
                    score=min(0.22 + overlap * 0.45, 0.82),
                    source_session=turn.session_id,
                    speaker=turn.speaker,
                    created_at=turn.created_at,
                    actor_id=turn.actor_id,
                    pii_flag=turn.pii_flag,
                    allow_cross_user=turn.allow_cross_user,
                    source_type="turn",
                    quote_text=excerpt,
                )
                key = self._memory_key(candidate)
                existing = results_map.get(key)
                if existing is None or candidate.score > existing.score:
                    results_map[key] = candidate

        ranked = sorted(
            results_map.values(),
            key=lambda item: (
                self._scope_priority(
                    self._source_scope(
                        item_actor_id=item.actor_id,
                        session_id=item.source_session,
                        actor_id=actor_id,
                        current_session_id=current_session_id,
                    )
                ),
                -item.score,
                item.created_at,
            )
        )
        deduped: list[MemoryResult] = []
        seen_insights: set[str] = set()
        for item in ranked:
            dedupe_key = self._insight_dedupe_key(item)
            if dedupe_key and dedupe_key in seen_insights:
                continue
            if dedupe_key:
                seen_insights.add(dedupe_key)
            deduped.append(item)
            if len(deduped) >= self._settings.knowledge_memory_top_k:
                break
        return deduped

    @staticmethod
    def is_exact_concrete_request(prompt: str, plan: QueryPlan | None) -> bool:
        text = f"{prompt} {plan.meaning if plan else ''} {plan.purpose if plan else ''}".lower()
        cues = [
            "exact",
            "concrete",
            "what did",
            "date",
            "time",
            "number",
            "how many",
            "which",
            "specific",
            "verbatim",
            "quote",
            "this year",
            "current year",
            "year to date",
            "today",
            "this week",
            "this month",
            "latest",
        ]
        return any(cue in text for cue in cues)

    def memory_to_evidence_cards(
        self,
        *,
        memory_results: list[MemoryResult],
        actor_id: str,
        current_session_id: str,
        start_index: int = 1,
    ) -> list[EvidenceCard]:
        cards: list[EvidenceCard] = []
        idx = start_index
        for item in memory_results:
            scope = self._source_scope(
                item_actor_id=item.actor_id,
                session_id=item.source_session,
                actor_id=actor_id,
                current_session_id=current_session_id,
            )
            source_type = {
                "same_session": "memory_same_session",
                "same_user": "memory_same_user",
                "shared": "memory_shared",
            }[scope]

            label = f"E{idx}"
            used_verbatim = bool(item.quote_text and scope in {"same_session", "same_user"})
            content = item.insight
            if used_verbatim:
                content = f"{item.insight}\nVerbatim: \"{item.quote_text}\""

            cards.append(
                EvidenceCard(
                    evidence_id=item.evidence_id,
                    source_type=source_type,
                    actor_scope=scope,
                    label=label,
                    content=content,
                    url=None,
                    source_session=item.source_session,
                    confidence=self.source_confidence(source_type, base_score=item.score),
                    pii_flag=item.pii_flag,
                    used_verbatim=used_verbatim,
                )
            )
            idx += 1
        return cards

    def web_to_evidence_cards(
        self,
        *,
        web_results: list[dict[str, str]],
        start_index: int,
    ) -> list[EvidenceCard]:
        cards: list[EvidenceCard] = []
        idx = start_index
        for row in web_results:
            url = str(row.get("url", "")).strip()
            title = str(row.get("title", "")).strip() or url
            snippet = str(row.get("snippet", "")).strip()
            if not url:
                continue
            source_type = str(row.get("source_type", "")).strip() or self.classify_source_type_for_url(url)
            if not source_type.startswith("web_"):
                source_type = self.classify_source_type_for_url(url)
            tag_hint = "user story / forum" if source_type == "web_user_story_forum" else source_type.replace("web_", "")
            label = f"E{idx}"
            cards.append(
                EvidenceCard(
                    evidence_id=f"web:{idx}:{uuid.uuid4().hex[:8]}",
                    source_type=source_type,
                    actor_scope="web",
                    label=label,
                    content=f"{title}\n{snippet}\nsource_tag={tag_hint}",
                    url=url,
                    source_session=None,
                    confidence=self.source_confidence(source_type, base_score=0.64),
                    pii_flag=False,
                    used_verbatim=False,
                )
            )
            idx += 1
        return cards

    @staticmethod
    def _split_claims(answer_text: str) -> list[str]:
        claims: list[str] = []
        for part in re.split(r"(?<=[.!?])\s+", answer_text.strip()):
            text = part.strip()
            if len(text) < 8:
                continue
            claims.append(text)
        return claims[:8]

    @staticmethod
    def _claim_support_score(claim_text: str, cards: list[EvidenceCard]) -> tuple[float, list[str], bool]:
        terms = KnowledgeAssistService._extract_terms(claim_text, max_terms=16)
        if not terms:
            return 0.0, [], False

        scored: list[tuple[float, EvidenceCard]] = []
        for card in cards:
            overlap = KnowledgeAssistService._term_overlap_score(card.content, terms)
            score = (overlap * 0.65) + (card.confidence * 0.35)
            scored.append((score, card))
        scored.sort(key=lambda item: item[0], reverse=True)

        selected: list[str] = []
        for score, card in scored[:3]:
            if score < 0.28:
                continue
            selected.append(card.label)

        if not selected:
            return 0.0, [], False
        best_score = scored[0][0]
        used_verbatim = any(card.used_verbatim and card.label in selected for _, card in scored[:3])
        return min(best_score, 1.0), selected, used_verbatim

    @staticmethod
    def _find_card_by_label(cards: list[EvidenceCard], label: str) -> EvidenceCard | None:
        for card in cards:
            if card.label == label:
                return card
        return None

    @staticmethod
    def _detect_claim_conflict(claim: GroundedClaim, cards: list[EvidenceCard]) -> bool:
        if len(claim.evidence_ids) < 2:
            return False
        bound_cards = [KnowledgeAssistService._find_card_by_label(cards, label) for label in claim.evidence_ids]
        usable = [card for card in bound_cards if card is not None]
        if len(usable) < 2:
            return False

        for idx, left in enumerate(usable):
            for right in usable[idx + 1 :]:
                left_terms = set(KnowledgeAssistService._extract_terms(left.content, max_terms=24))
                right_terms = set(KnowledgeAssistService._extract_terms(right.content, max_terms=24))
                if not left_terms or not right_terms:
                    continue
                overlap = len(left_terms & right_terms) / max(1, min(len(left_terms), len(right_terms)))
                if overlap < 0.35:
                    continue
                left_nums = set(_NUMERIC_PATTERN.findall(left.content))
                right_nums = set(_NUMERIC_PATTERN.findall(right.content))
                if left_nums and right_nums and left_nums != right_nums:
                    return True
                left_neg = bool(_NEGATION_PATTERN.search(left.content))
                right_neg = bool(_NEGATION_PATTERN.search(right.content))
                if left_neg != right_neg and overlap >= 0.5:
                    return True
        return False

    @staticmethod
    def _claim_line(claim: GroundedClaim) -> str:
        return f"- {claim.text} (conf:{claim.confidence:.2f}, status:{claim.status})"

    @staticmethod
    def _source_line(card: EvidenceCard) -> str:
        scope_part = f" scope={card.actor_scope}" if card.actor_scope else ""
        if card.url:
            return f"[{card.label}] {card.source_type}{scope_part} conf={card.confidence:.2f} {card.url}"
        if card.source_session:
            return (
                f"[{card.label}] {card.source_type}{scope_part} "
                f"conf={card.confidence:.2f} session={card.source_session}"
            )
        return f"[{card.label}] {card.source_type}{scope_part} conf={card.confidence:.2f}"

    @staticmethod
    def _strip_source_artifacts(answer_text: str) -> str:
        text = answer_text
        text = re.sub(r"\[E\d+\]", "", text)
        filtered_lines: list[str] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            lower = line.lower()
            if lower.startswith("source:"):
                continue
            if lower.startswith("sources:"):
                continue
            if lower.startswith("url:"):
                continue
            filtered_lines.append(raw_line)
        cleaned = "\n".join(filtered_lines)
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    @staticmethod
    def _shorten(text: str, *, limit: int = 130) -> str:
        clean = re.sub(r"\s+", " ", text).strip()
        if len(clean) <= limit:
            return clean
        return clean[: limit - 3].rstrip() + "..."

    @staticmethod
    def _build_grounded_reasoning_and_debug(
        *,
        reasoning_mode: str,
        evidence_cards: list[EvidenceCard],
        claims: list[GroundedClaim],
        status: str,
        overall_confidence: float,
        exact_required: bool,
        unsupported_count: int,
        conflict_pairs: list[tuple[str, str]],
        note: str,
    ) -> tuple[str, str]:
        mode = (reasoning_mode or "hidden").strip().lower()
        if mode not in {"summary", "verbose", "debug"}:
            return "", ""

        scope_counts: dict[str, int] = {}
        source_counts: dict[str, int] = {}
        for card in evidence_cards:
            scope_counts[card.actor_scope] = scope_counts.get(card.actor_scope, 0) + 1
            source_counts[card.source_type] = source_counts.get(card.source_type, 0) + 1

        grounded_count = sum(1 for claim in claims if claim.status == "grounded")
        weak_count = sum(1 for claim in claims if claim.status == "weak")

        scope_summary = ", ".join(f"{scope}:{count}" for scope, count in sorted(scope_counts.items()))
        if not scope_summary:
            scope_summary = "none"

        reasoning_lines = [
            f"Used {len(evidence_cards)} evidence cards ({scope_summary}).",
            f"Grounding status is {status} with confidence {overall_confidence:.2f}.",
        ]
        if claims:
            reasoning_lines.append(
                f"Claims assessed: grounded={grounded_count}, weak={weak_count}, unsupported={unsupported_count}."
            )
        if conflict_pairs:
            reasoning_lines.append("Detected conflicting evidence across retrieved items.")
        if exact_required:
            reasoning_lines.append("Exact-request checks were applied for concrete fields.")
        if note:
            reasoning_lines.append(f"Grounding note: {KnowledgeAssistService._shorten(note, limit=180)}")

        if mode in {"verbose", "debug"}:
            top_cards = sorted(evidence_cards, key=lambda card: card.confidence, reverse=True)[:4]
            if top_cards:
                reasoning_lines.append("Top evidence considered:")
                for card in top_cards:
                    reasoning_lines.append(
                        f"- {card.label} {card.source_type} conf={card.confidence:.2f}: "
                        f"{KnowledgeAssistService._shorten(card.content, limit=150)}"
                    )

        debug_text = ""
        if mode == "debug":
            labels = [card.label for card in evidence_cards]
            evidence_ids = [card.evidence_id for card in evidence_cards]
            source_summary = ", ".join(f"{k}:{v}" for k, v in sorted(source_counts.items()))
            conflict_summary = ", ".join(f"{left}/{right}" for left, right in conflict_pairs)
            debug_lines = [
                f"evidence_labels={labels}",
                f"evidence_ids={evidence_ids}",
                f"source_type_counts={source_summary or 'none'}",
                f"status={status}",
                f"overall_confidence={overall_confidence:.2f}",
                f"weak_claims={weak_count}",
                f"unsupported_claims={unsupported_count}",
                f"conflicts={conflict_summary or 'none'}",
                f"exact_required={exact_required}",
            ]
            debug_text = "\n".join(debug_lines)

        return "\n".join(reasoning_lines), debug_text

    async def generate_grounded_response(
        self,
        *,
        prompt: str,
        model: str,
        grounded_profile: str,
        exact_required: bool,
        evidence_cards: list[EvidenceCard],
        reasoning_mode: str = "hidden",
    ) -> GroundedResponse:
        if not evidence_cards:
            clarify = "I couldn't verify enough evidence yet. Can you clarify the exact fact or timeframe you want verified?"
            reasoning_text, debug_text = self._build_grounded_reasoning_and_debug(
                reasoning_mode=reasoning_mode,
                evidence_cards=[],
                claims=[],
                status="insufficient",
                overall_confidence=0.0,
                exact_required=exact_required,
                unsupported_count=0,
                conflict_pairs=[],
                note="No evidence available.",
            )
            return GroundedResponse(
                status="insufficient",
                answer_text="",
                claims=[],
                overall_confidence=0.0,
                clarify_question=clarify,
                note="No evidence available.",
                reasoning_text=reasoning_text,
                debug_text=debug_text,
            )

        evidence_lines = []
        for card in evidence_cards:
            evidence_lines.append(f"{card.label} [{card.source_type}] conf={card.confidence:.2f}")
            evidence_lines.append(card.content)
            if card.url:
                evidence_lines.append(f"URL: {card.url}")
            evidence_lines.append("---")

        system_prompt = (
            "You produce grounded answers only from provided evidence.\n"
            "Return JSON only with fields: answer, note.\n"
            "Requirements:\n"
            "- Add confidence marker '(conf:0.xx)' to factual statements.\n"
            "- If evidence is weak, explicitly say not 100% factual.\n"
            "- Do not include source sections, URLs, or evidence labels in the final answer text.\n"
            "- Do not invent facts outside evidence."
        )
        user_prompt = (
            f"Grounded profile: {grounded_profile}\n"
            f"Exact required: {exact_required}\n"
            f"Question: {prompt}\n"
            "Evidence:\n"
            + "\n".join(evidence_lines)
        )

        try:
            raw = await self._ollama.chat(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                num_ctx=max(2048, min(self._settings.default_num_ctx, 6144)),
            )
            payload = RecursivePlanner._extract_json_object(raw)
        except OllamaStreamError:
            payload = None

        if payload and isinstance(payload.get("answer"), str):
            answer_text = payload.get("answer", "").strip()
            note = str(payload.get("note", "")).strip()
        else:
            top = evidence_cards[0]
            answer_text = (
                f"Based on available evidence (conf:{top.confidence:.2f}), "
                f"I can state: {top.content}\n"
                "This is not 100% factual without additional corroboration."
            )
            note = "fallback synthesis"

        if not answer_text:
            answer_text = "I could not synthesize a grounded answer from the current evidence."
        answer_text = self._strip_source_artifacts(answer_text)

        claims_raw = self._split_claims(answer_text)
        claims: list[GroundedClaim] = []
        unsupported_count = 0
        for text in claims_raw:
            support_score, evidence_labels, used_verbatim = self._claim_support_score(text, evidence_cards)
            if support_score >= 0.72:
                status = "grounded"
            elif support_score >= 0.45:
                status = "weak"
            else:
                status = "unsupported"
                unsupported_count += 1
            if status != "unsupported" and not evidence_labels:
                status = "unsupported"
                unsupported_count += 1

            confidence = min(max(support_score, 0.0), 1.0)
            claims.append(
                GroundedClaim(
                    claim_id=str(uuid.uuid4()),
                    text=text,
                    evidence_ids=evidence_labels,
                    confidence=confidence,
                    status=status,
                )
            )

        conflict_pairs: list[tuple[str, str]] = []
        for claim in claims:
            if self._detect_claim_conflict(claim, evidence_cards):
                if len(claim.evidence_ids) >= 2:
                    pair = (claim.evidence_ids[0], claim.evidence_ids[1])
                    if pair not in conflict_pairs:
                        conflict_pairs.append(pair)
        weak_count = sum(1 for claim in claims if claim.status == "weak")

        if claims:
            overall = sum(item.confidence for item in claims) / len(claims)
        else:
            overall = 0.0

        if exact_required and (unsupported_count > 0 or weak_count > 0 or conflict_pairs):
            conflict_note = " Conflicting evidence detected." if conflict_pairs else ""
            clarify = (
                "I can’t verify the exact concrete data yet. "
                "Which exact phrase, date, or field should I validate first?"
            )
            insufficient_note = f"Exact request has weak, unsupported, or conflicting claims.{conflict_note}"
            reasoning_text, debug_text = self._build_grounded_reasoning_and_debug(
                reasoning_mode=reasoning_mode,
                evidence_cards=evidence_cards,
                claims=claims,
                status="insufficient",
                overall_confidence=overall,
                exact_required=exact_required,
                unsupported_count=unsupported_count,
                conflict_pairs=conflict_pairs,
                note=insufficient_note,
            )
            return GroundedResponse(
                status="insufficient",
                answer_text="",
                claims=claims,
                overall_confidence=overall,
                clarify_question=clarify,
                note=insufficient_note,
                reasoning_text=reasoning_text,
                debug_text=debug_text,
            )

        if unsupported_count == 0 and weak_count == 0 and not conflict_pairs:
            status = "full"
        else:
            status = "partial"

        if conflict_pairs:
            answer_text = (
                answer_text.rstrip()
                + "\n\nPotential evidence conflict detected across retrieved records. "
                "Presenting both interpretations; clarify which source should be authoritative."
            )

        if (unsupported_count > 0 or weak_count > 0 or conflict_pairs) and "not 100% factual" not in answer_text.lower():
            answer_text = answer_text.rstrip() + "\n\nThis response is not 100% factual; some claims are weakly grounded."

        if claims:
            answer_text = answer_text.rstrip() + "\n\nClaim confidence:\n" + "\n".join(
                self._claim_line(claim) for claim in claims
            )

        reasoning_text, debug_text = self._build_grounded_reasoning_and_debug(
            reasoning_mode=reasoning_mode,
            evidence_cards=evidence_cards,
            claims=claims,
            status=status,
            overall_confidence=overall,
            exact_required=exact_required,
            unsupported_count=unsupported_count,
            conflict_pairs=conflict_pairs,
            note=note,
        )

        return GroundedResponse(
            status=status,
            answer_text=answer_text,
            claims=claims,
            overall_confidence=overall,
            clarify_question="",
            note=note,
            reasoning_text=reasoning_text,
            debug_text=debug_text,
        )

    async def log_grounded_run_start(
        self,
        *,
        run_id: str,
        session_id: str,
        actor_id: str,
        mode: str,
        profile: str,
        prompt: str,
    ) -> None:
        await asyncio.to_thread(
            self._store.start_grounded_run,
            run_id=run_id,
            session_id=session_id,
            actor_id=actor_id,
            mode=mode,
            profile=profile,
            prompt=prompt,
        )

    async def log_grounded_evidence(
        self,
        *,
        run_id: str,
        cards: list[EvidenceCard],
    ) -> None:
        for card in cards:
            await asyncio.to_thread(
                self._store.add_grounded_evidence,
                evidence_id=card.evidence_id,
                run_id=run_id,
                source_type=card.source_type,
                actor_scope=card.actor_scope,
                pii_flag=card.pii_flag,
                label=card.label,
                content=card.content,
                url=card.url,
                source_session=card.source_session,
                confidence=card.confidence,
            )

    async def log_grounded_claims(
        self,
        *,
        run_id: str,
        claims: list[GroundedClaim],
        cards: list[EvidenceCard],
        is_exact_required: bool,
    ) -> None:
        label_to_card = {card.label: card for card in cards}
        for claim in claims:
            await asyncio.to_thread(
                self._store.add_grounded_claim,
                claim_id=claim.claim_id,
                run_id=run_id,
                claim_text=claim.text,
                is_exact_required=is_exact_required,
                support_status=claim.status,
                confidence=claim.confidence,
            )
            for label in claim.evidence_ids:
                card = label_to_card.get(label)
                if not card:
                    continue
                await asyncio.to_thread(
                    self._store.link_claim_evidence,
                    claim_id=claim.claim_id,
                    evidence_id=card.evidence_id,
                    support_score=claim.confidence,
                    used_verbatim=card.used_verbatim,
                )

    async def log_grounded_run_finish(self, *, run_id: str, status: str, note: str | None) -> None:
        await asyncio.to_thread(
            self._store.finish_grounded_run,
            run_id=run_id,
            status=status,
            note=note,
        )
